import { evictDurableObject, runDurableObjectAlarm, runInDurableObject } from "cloudflare:test"
import { env as workerEnv } from "cloudflare:workers"
import { describe, expect, it } from "vitest"
import { abandonedPushError } from "../src/persist"
import { MAX_RUN_ERROR, MAX_RUN_MS, PID_GRACE_MS } from "../src/runstate"
import type { Env } from "../src/types"
import type { Workspace } from "../src/workspace"
import { FakeHost } from "./fakehost"

const env = workerEnv as unknown as Env
const repo = "https://github.com/acme/app"
const resultLine = JSON.stringify({ type: "result", result: "done" })
const fast = { pidWait: 20, stopWait: 20, poll: 5 }

type Seams = { sandbox: FakeHost; timing: typeof fast }
type Stored = { state: string; persistPending?: boolean; startedAt?: number; error?: string; task?: unknown }

// A real Workspace object with the fake container in its one seam. The seam is
// a private field, set from inside the object; an eviction drops it, so attach()
// is called again after one.
let n = 0
async function open(fake = new FakeHost()) {
	const stub = env.WORKSPACE.getByName(`workspace-test-${++n}`)
	await attach(stub, fake)
	return { stub, fake }
}

type Stub = ReturnType<typeof env.WORKSPACE.getByName>

function attach(stub: Stub, fake: FakeHost): Promise<void> {
	return runInDurableObject(stub, (instance) => {
		Object.assign(instance as unknown as Seams, { sandbox: fake, timing: fast })
	})
}

function stored(stub: Stub): Promise<Stored> {
	return runInDurableObject(stub, (_instance, state) => state.storage.kv.get<Stored>("workspace") as Stored)
}

function edit(stub: Stub, change: (record: Stored) => void): Promise<void> {
	return runInDurableObject(stub, (_instance, state) => {
		const record = state.storage.kv.get<Stored>("workspace") as Stored
		change(record)
		state.storage.kv.put("workspace", record)
	})
}

// Calls the object directly. A method that throws over RPC is also reported by
// the test runtime as an unhandled rejection, so the throwing cases use this.
function direct<R>(stub: Stub, call: (workspace: Workspace) => Promise<R>): Promise<R> {
	return runInDurableObject(stub, (instance) => call(instance as unknown as Workspace))
}

function alarmAt(stub: Stub): Promise<number | null> {
	return runInDurableObject(stub, (_instance, state) => state.storage.getAlarm())
}

async function created(fake?: FakeHost) {
	const opened = await open(fake)
	const made = await opened.stub.create(repo, "work", ["example.com"])
	expect(made).not.toBe("conflict")
	return opened
}

async function started(fake?: FakeHost) {
	const opened = await created(fake)
	expect(await opened.stub.startRun("hello", false, 5)).toEqual({ run: 1 })
	return opened
}

describe("Workspace create", () => {
	it("answers conflict for the same repository with another host list (m4)", async () => {
		const { stub } = await created()
		expect(await stub.create(repo, "work", ["other.example"])).toBe("conflict")
		expect(await stub.create(repo, "other", ["example.com"])).toBe("conflict")
	})

	it("answers the status for the same host list in another case or order", async () => {
		const { stub } = await open()
		await stub.create(repo, "work", ["b.example", "a.example"])
		const again = await stub.create(repo, "work", ["A.example", "b.example", "a.example"])
		expect(again).toMatchObject({ status: { state: "idle" } })
	})
})

describe("Workspace start (I3)", () => {
	it("answers busy to a second start during a run, and starts one task", async () => {
		const { stub, fake } = await started()
		expect(await stub.startRun("again", false, 5)).toBe("busy")
		expect(fake.count("startTask")).toBe(1)
	})

	it("keeps a run whose launcher failed after the task started, and starts no second agent", async () => {
		const fake = new FakeHost()
		fake.startMode = "spawn-then-throw"
		const { stub } = await created(fake)

		expect(await stub.startRun("hello", false, 5)).toEqual({ run: 1 })
		expect((await stub.status()).state).toBe("running")
		expect(await stub.startRun("again", false, 5)).toBe("busy")
		expect(fake.count("startTask")).toBe(1)
		expect([...fake.groups.values()].filter((g) => g.alive)).toHaveLength(1)
	})

	it("stores the run before the task starts, and fails it when no task appeared", async () => {
		const fake = new FakeHost()
		fake.startMode = "throw"
		const { stub } = await created(fake)

		await expect(direct(stub, (w) => w.startRun("hello", false, 5))).rejects.toThrow(/exec failed/)
		const status = await stub.status()
		expect(status).toMatchObject({ state: "failed", run: 1 })
		expect(status.error).toMatch(/^The run did not start: /)
	})

	it("kills a group an earlier start left behind before it resets the task directory", async () => {
		const { stub, fake } = await created()
		fake.groups.set(7, { alive: true, ignoresTerm: true })
		fake.task = { pid: 7, boot: fake.boot }

		await stub.startRun("hello", false, 5)
		const order = fake.calls.filter((c) => c === "signal 7 KILL" || c === "resetTask" || c === "startTask")
		expect(order).toEqual(["signal 7 KILL", "resetTask", "startTask"])
		expect(fake.groups.get(7)?.alive).toBe(false)
	})
})

describe("Workspace stop (I3)", () => {
	it("sends KILL after TERM even when the leader exited on TERM", async () => {
		const { stub, fake } = await started()
		const status = await stub.stop()
		expect(status).toMatchObject({ state: "stopped" })
		expect(fake.calls.filter((c) => c.startsWith("signal 100"))).toEqual(["signal 100 TERM", "signal 100 KILL"])
		expect(fake.count("push work")).toBe(1)
	})

	it("ends a group that ignores TERM with KILL", async () => {
		const fake = new FakeHost()
		fake.ignoresTerm = true
		const { stub } = await started(fake)

		expect(await stub.stop()).toMatchObject({ state: "stopped" })
		expect(fake.groups.get(100)?.alive).toBe(false)
	})
})

describe("Workspace push and snapshot after an interruption (I2)", () => {
	it("pushes and snapshots on the next refresh after a reset between the end and the push", async () => {
		const { stub, fake } = await started()
		fake.finishTask(0, [resultLine])
		fake.failOnce.push = new Error("object reset")

		await expect(direct(stub, (w) => w.status())).rejects.toThrow(/object reset/)
		expect(await stored(stub)).toMatchObject({ state: "succeeded", persistPending: true })

		await evictDurableObject(stub)
		await attach(stub, fake)
		const status = await stub.status()

		expect(status).toMatchObject({ state: "succeeded", result: "done", pushed: { commit: "commit-2" } })
		expect(fake.count("snapshot")).toBe(1)
		expect((await stored(stub)).persistPending).toBe(false)
	})

	it("gives the push up, and says so, when the container is gone by then", async () => {
		const { stub, fake } = await started()
		fake.finishTask(0, [resultLine])
		fake.failOnce.push = new Error("object reset")
		await expect(direct(stub, (w) => w.status())).rejects.toThrow(/object reset/)

		fake.running = false
		const status = await stub.status()
		expect(status).toMatchObject({ state: "succeeded", pushError: abandonedPushError })
		expect(fake.count("snapshot")).toBe(0)
		expect((await stored(stub)).persistPending).toBe(false)
	})
})

describe("Workspace alarm (I5)", () => {
	it("re-arms after a throw", async () => {
		const { stub, fake } = await started()
		fake.failOnce.exitCode = new Error("exec failed")

		expect(await runDurableObjectAlarm(stub)).toBe(true)
		expect(await alarmAt(stub)).not.toBeNull()
		expect((await stored(stub)).state).toBe("running")
	})

	it("stays armed while a push is pending, then clears", async () => {
		const { stub, fake } = await started()
		fake.finishTask(0, [resultLine])
		fake.failOnce.push = new Error("push hung up")

		expect(await runDurableObjectAlarm(stub)).toBe(true)
		expect(await stored(stub)).toMatchObject({ state: "succeeded", persistPending: true })
		expect(await alarmAt(stub)).not.toBeNull()

		expect(await runDurableObjectAlarm(stub)).toBe(true)
		expect((await stored(stub)).persistPending).toBe(false)
		expect(await alarmAt(stub)).toBeNull()
	})
})

describe("Workspace run limits (I6)", () => {
	it("kills a run past the wall-clock limit, fails it and pushes", async () => {
		const { stub, fake } = await started()
		await edit(stub, (record) => {
			record.startedAt = Date.now() - MAX_RUN_MS - 1
		})

		const status = await stub.status()
		expect(status).toMatchObject({ state: "failed", error: MAX_RUN_ERROR, pushed: { commit: "commit-1" } })
		expect(fake.calls).toContain("signal 100 KILL")
		expect(fake.groups.get(100)?.alive).toBe(false)
		expect(fake.count("snapshot")).toBe(1)
	})

	it("keeps a run with no pid file running for the grace period, then calls it lost and pushes", async () => {
		const fake = new FakeHost()
		fake.startMode = "no-pid"
		const { stub } = await started(fake)
		expect((await stub.status()).state).toBe("running")

		await edit(stub, (record) => {
			record.startedAt = Date.now() - PID_GRACE_MS - 1
		})
		const status = await stub.status()
		expect(status.state).toBe("lost")
		expect(status.error).toMatch(/pid file/)
		expect(fake.count("push work")).toBe(1)
	})

	it("keeps watching the task it saw when the pid file is removed during a run", async () => {
		const { stub, fake } = await started()
		expect((await stub.status()).state).toBe("running") // the pid is read and stored
		fake.task = undefined
		await edit(stub, (record) => {
			record.startedAt = Date.now() - PID_GRACE_MS - 1
		})

		expect((await stub.status()).state).toBe("running")
		fake.groups.get(100)!.alive = false
		expect((await stub.status()).state).toBe("lost")
	})
})

describe("Workspace lost run (I4, m6)", () => {
	it("reads the output and pushes when the task is gone with no exit code but the container runs", async () => {
		const { stub, fake } = await started()
		fake.stdout = new TextEncoder().encode(`${JSON.stringify({ type: "assistant", text: "hi" })}\n`)
		fake.groups.get(100)!.alive = false

		const status = await stub.status()
		expect(status).toMatchObject({ state: "lost", pushed: { commit: "commit-1" } })
		const read = await direct(stub, (w) => w.events(0))
		if (read === "missing") throw new Error("the workspace is missing")
		expect(read.events.map((e) => e.type)).toContain("assistant")
	})

	it("does not push when the container is gone", async () => {
		const { stub, fake } = await started()
		fake.running = false

		expect(await stub.status()).toMatchObject({ state: "lost", error: "The container stopped before the run ended" })
		expect(fake.count("push work")).toBe(0)
	})
})

describe("Workspace test-only routes", () => {
	it("replaceInstance destroys the container and keeps the record, so a running run is judged lost", async () => {
		const { stub, fake } = await started()
		const before = await stored(stub)

		expect(await stub.replaceInstance()).toMatchObject({ state: "running", run: 1 })
		expect(fake.count("destroy")).toBe(1)
		expect(fake.running).toBe(false)
		expect(await stored(stub)).toMatchObject({ state: before.state, startedAt: before.startedAt })
		expect(await stub.status()).toMatchObject({ state: "lost", error: "The container stopped before the run ended" })
		expect(await stub.startRun("next", false, 5)).toEqual({ run: 2 })
		expect(fake.count("startFromImage")).toBe(2)
	})

	it("replaceInstance and exec answer missing for a workspace never created", async () => {
		const { stub, fake } = await open()
		expect(await stub.replaceInstance()).toBe("missing")
		expect(await stub.exec(["true"])).toBe("missing")
		expect(fake.calls).toEqual([])
	})

	it("exec runs the command in a running instance, starting one when there is none", async () => {
		const { stub, fake } = await created()
		fake.execResult = { exitCode: 3, stdout: "a", stderr: "b" }
		expect(await stub.exec(["git", "status"])).toEqual({ exitCode: 3, stdout: "a", stderr: "b" })
		expect(fake.calls.at(-1)).toBe("exec git status")

		await stub.replaceInstance()
		await stub.exec(["true"])
		expect(fake.running).toBe(true)
		expect(fake.count("startFromImage")).toBe(2)
	})
})
