import { evictDurableObject, runDurableObjectAlarm, runInDurableObject } from "cloudflare:test"
import { env as workerEnv } from "cloudflare:workers"
import { describe, expect, it } from "vitest"
import { abandonedPushError } from "../src/persist"
import { MAX_OUTPUT_BYTES, MAX_RUN_ERROR, MAX_RUN_MS, OUTPUT_ERROR, PID_GRACE_MS, TASK_FILES_ERROR } from "../src/runstate"
import { TRUNCATED_RESULT_ERROR } from "../src/agent"
import type { Env } from "../src/types"
import type { Workspace } from "../src/workspace"
import { FakeHost } from "./fakehost"

const env = workerEnv as unknown as Env
const repo = "https://github.com/acme/app"
const resultLine = JSON.stringify({ type: "result", result: "done" })
const fast = { pidWait: 20, stopWait: 20, poll: 5, snapshotWait: 20 }

type Seams = { sandbox: FakeHost; timing: typeof fast }
type Stored = {
	state: string
	persistPending?: boolean
	startedAt?: number
	error?: string
	task?: unknown
	snapshot?: string
	snapshotPending?: boolean
	snapshotAttempts?: number
	snapshotStale?: boolean
	replaceInstance?: boolean
	resumed?: boolean
	resultLine?: string
}

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
	it("re-arms after a throw while the run is running (F1d)", async () => {
		const { stub, fake } = await started()
		fake.failOnce.readOutput = new Error("exec failed")

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

async function notices(stub: Stub): Promise<unknown[]> {
	const read = await direct(stub, (w) => w.events(0))
	if (read === "missing") throw new Error("the workspace is missing")
	return read.events.filter((e) => e.type === "runner").map((e) => (e.payload as { notice: string }).notice)
}

// A workspace whose first run ended and was pushed and snapshotted (snap-1).
async function afterOneRun(fake = new FakeHost()) {
	const opened = await started(fake)
	fake.finishTask(0, [resultLine])
	expect(await opened.stub.status()).toMatchObject({ state: "succeeded" })
	expect((await stored(opened.stub)).snapshot).toBe("snap-1")
	return opened
}

describe("Workspace replaces an instance it cannot trust (Copilot C4)", () => {
	it("persists a run that never wrote its pid file, then destroys the instance; the next start restores the snapshot", async () => {
		const fake = new FakeHost()
		fake.startMode = "no-pid"
		const { stub } = await started(fake)
		await edit(stub, (record) => {
			record.startedAt = Date.now() - PID_GRACE_MS - 1
		})

		expect((await stub.status()).state).toBe("lost")
		expect(fake.calls.filter((c) => ["push work", "snapshot", "destroy"].includes(c))).toEqual(["push work", "snapshot", "destroy"])
		expect(fake.running).toBe(false)
		expect((await stored(stub)).replaceInstance).toBeFalsy()

		fake.startMode = "spawn"
		expect(await stub.startRun("next", false, 5)).toEqual({ run: 2 })
		expect(fake.calls).toContain("startFromSnapshot snap-1")
		expect(await stub.status()).toMatchObject({ state: "running", restored: "snapshot", uncommittedLost: false })
	})

	it("replaces a running instance whose pid file it cannot read, and signals nothing", async () => {
		const { stub, fake } = await created()
		fake.pidInvalid = true

		expect(await stub.startRun("hello", false, 5)).toEqual({ run: 1 })
		expect(fake.calls.filter((c) => c.startsWith("signal"))).toEqual([])
		const order = fake.calls.filter((c) => ["destroy", "startFromImage", "resetTask", "startTask"].includes(c))
		expect(order).toEqual(["startFromImage", "destroy", "startFromImage", "resetTask", "startTask"])
		expect(fake.count("clone work")).toBe(2)
	})

	it("replaces the instance for a stored group ID of 1 from before parseTask refused it (Copilot C2)", async () => {
		const { stub, fake } = await created()
		await edit(stub, (record) => {
			record.task = { pid: 1, boot: fake.boot }
		})

		expect(await stub.startRun("hello", false, 5)).toEqual({ run: 1 })
		expect(fake.calls).not.toContain("signal 1 KILL")
		expect(fake.count("destroy")).toBe(1)
	})

	it("does not wait for a timed-out snapshot when a new run needs the instance replaced", async () => {
		const fake = new FakeHost()
		fake.startMode = "no-pid"
		fake.snapshotDelayMs = 100
		const { stub } = await started(fake)
		await edit(stub, (record) => {
			record.startedAt = Date.now() - PID_GRACE_MS - 1
		})

		expect((await stub.status()).state).toBe("lost")
		expect(await stored(stub)).toMatchObject({ snapshotPending: true, replaceInstance: true })
		expect(fake.running).toBe(true) // the destroy waits for the snapshot retry

		fake.startMode = "spawn"
		fake.snapshotDelayMs = 100
		expect(await stub.startRun("next", false, 5)).toEqual({ run: 2 })
		expect(fake.count("destroy")).toBe(1)
		expect(fake.count("clone work")).toBe(2)
		expect(await stub.status()).toMatchObject({ restored: "branch", uncommittedLost: true })
		expect(await stored(stub)).toMatchObject({ snapshotPending: false, replaceInstance: false })
	})
})

describe("Workspace stale snapshot (Copilot C5)", () => {
	it("restores the old snapshot after a run lost with its container, says the work was lost and starts a new conversation", async () => {
		const { stub, fake } = await afterOneRun()
		expect(await stub.startRun("second", false, 5)).toEqual({ run: 2 })
		expect((await stored(stub)).resumed).toBe(true)
		fake.running = false

		expect((await stub.status()).state).toBe("lost")
		expect(await stored(stub)).toMatchObject({ snapshot: "snap-1", snapshotStale: true })

		expect(await stub.startRun("third", false, 5)).toEqual({ run: 3 })
		expect(fake.calls).toContain("startFromSnapshot snap-1")
		expect(await stub.status()).toMatchObject({ restored: "snapshot", uncommittedLost: true })
		const record = await stored(stub)
		expect(record.resumed).toBe(false)
		expect(record.snapshotStale).toBeFalsy()
	})

	it("keeps the old snapshot, marked stale, when the push was given up with the container gone", async () => {
		const { stub, fake } = await afterOneRun()
		await stub.startRun("second", false, 5)
		fake.finishTask(0, [resultLine])
		fake.failOnce.push = new Error("object reset")
		await expect(direct(stub, (w) => w.status())).rejects.toThrow(/object reset/)

		fake.running = false
		expect(await stub.status()).toMatchObject({ pushError: abandonedPushError })
		expect(await stored(stub)).toMatchObject({ snapshot: "snap-1", snapshotStale: true })
		await stub.startRun("third", false, 5)
		expect(await stub.status()).toMatchObject({ restored: "snapshot", uncommittedLost: true })
	})
})

describe("Workspace finish (Copilot C6)", () => {
	it("kills the task's group before it reads the output, pushes or snapshots", async () => {
		const { stub, fake } = await started()
		fake.finishTask(0, [resultLine], true)
		expect(fake.groups.get(100)?.alive).toBe(true)

		expect(await stub.status()).toMatchObject({ state: "succeeded", result: "done" })
		expect(fake.groups.get(100)?.alive).toBe(false)
		const order = fake.calls.filter((c) => ["signal 100 KILL", "push work", "snapshot"].includes(c))
		expect(order).toEqual(["signal 100 KILL", "push work", "snapshot"])
	})
})

describe("Workspace snapshot timeout (Copilot C8)", () => {
	it("stores the push, keeps the snapshot pending for the alarm, and gives up after three attempts", async () => {
		const fake = new FakeHost()
		const { stub } = await started(fake)
		fake.finishTask(0, [resultLine])
		fake.snapshotDelayMs = 100

		expect(await stub.status()).toMatchObject({ state: "succeeded", pushed: { commit: "commit-1" } })
		expect(await stored(stub)).toMatchObject({ persistPending: false, snapshotPending: true, snapshotAttempts: 1 })
		expect(await alarmAt(stub)).not.toBeNull()

		expect(await runDurableObjectAlarm(stub)).toBe(true)
		expect(await stored(stub)).toMatchObject({ snapshotPending: true, snapshotAttempts: 2 })
		expect(await runDurableObjectAlarm(stub)).toBe(true)
		expect(await stored(stub)).toMatchObject({ snapshotPending: false, snapshot: undefined })
		expect(await alarmAt(stub)).toBeNull()

		expect(fake.count("push work")).toBe(1)
		expect(fake.count("snapshot")).toBe(3)
		expect(await notices(stub)).toEqual(["run started", "run ended", "pushed", "snapshot timed out", "snapshot timed out", "snapshot failed"])
	})

	it("keeps a snapshot that answers on a retry", async () => {
		const fake = new FakeHost()
		const { stub } = await started(fake)
		fake.finishTask(0, [resultLine])
		fake.snapshotDelayMs = 100
		await stub.status()

		fake.snapshotDelayMs = 0
		expect(await runDurableObjectAlarm(stub)).toBe(true)
		expect(await stored(stub)).toMatchObject({ snapshotPending: false, snapshot: "snap-2" })
	})

	it("drops a still-pending snapshot when the next run starts, since the stored one is behind the branch", async () => {
		const fake = new FakeHost()
		const { stub } = await afterOneRun(fake)
		await stub.startRun("second", false, 5)
		fake.finishTask(0, [resultLine])
		fake.snapshotDelayMs = 100
		await stub.status()
		expect(await stored(stub)).toMatchObject({ snapshot: "snap-1", snapshotPending: true })

		// Only the alarm retries a snapshot; the new run drops the pending one.
		expect(await stub.startRun("third", false, 5)).toEqual({ run: 3 })
		expect(await stored(stub)).toMatchObject({ snapshot: undefined, snapshotPending: false })
	})
})

describe("Workspace new instance readiness (Copilot C9)", () => {
	it("sets intercepts only after the new instance answers, and a start that never answers leaves nothing set up", async () => {
		const fake = new FakeHost()
		fake.imageFailures = 1
		const { stub } = await open(fake)

		await expect(direct(stub, (w) => w.create(repo, "work", []))).rejects.toThrow(/did not answer/)
		expect(fake.calls).toEqual(["startFromImage"])

		expect(await stub.create(repo, "work", [])).not.toBe("conflict")
		expect(fake.calls.slice(1, 4)).toEqual(["startFromImage", "image ready", "setPolicy "])
	})
})

describe("Workspace oversized result (Copilot round 2, E1)", () => {
	// 300 KiB: over the 256 KiB payload cap, well under a read chunk.
	const text = "x".repeat(300 * 1024)

	it("fails a run whose oversized result says is_error", async () => {
		const { stub, fake } = await started()
		fake.finishTask(1, [JSON.stringify({ type: "result", subtype: "error_max_turns", is_error: true, result: text })])
		expect(await stub.status()).toMatchObject({ state: "failed", error: "error_max_turns" })
	})

	it("fails a run whose oversized result cannot be parsed", async () => {
		const { stub, fake } = await started()
		fake.finishTask(0, [`{"type":"result","is_error":false,"result":"${text}`])
		expect(await stub.status()).toMatchObject({ state: "failed", error: TRUNCATED_RESULT_ERROR })
	})

	it("stores a small sentinel for an oversized result with a huge usage object (F1b)", async () => {
		const { stub, fake } = await started()
		const usage = { input_tokens: 1, padding: "u".repeat(1024 * 1024) }
		fake.finishTask(0, [JSON.stringify({ type: "result", subtype: "success", is_error: false, usage, result: "done" })])

		expect(await stub.status()).toMatchObject({ state: "succeeded", result: "" })
		const kept = (await stored(stub)).resultLine as string
		expect(new TextEncoder().encode(kept).length).toBeLessThan(16 * 1024)
		expect(JSON.parse(kept)).toMatchObject({ is_error: false, truncated: true })
	})

	it("succeeds a run whose oversized result is a success, with the result marked truncated", async () => {
		const { stub, fake } = await started()
		fake.finishTask(0, [JSON.stringify({ type: "result", subtype: "success", is_error: false, num_turns: 3, result: text })])
		expect(await stub.status()).toMatchObject({ state: "succeeded", result: "" })
		expect(await notices(stub)).toContain("result truncated")
	})
})

describe("Workspace push policy (Copilot C11)", () => {
	it("gives Outbound the workspace branch on create and on every later setup", async () => {
		const { stub, fake } = await open()
		expect(await stub.create(repo, "work", ["example.org"])).not.toBe("conflict")
		expect(fake.policies.at(-1)).toEqual({ repoPath: "/acme/app", branch: "work", allow: ["example.org"] })

		fake.running = false
		expect(await stub.startRun("hello", false, 5)).toEqual({ run: 1 })
		expect(fake.policies.at(-1)).toEqual({ repoPath: "/acme/app", branch: "work", allow: ["example.org"] })
	})

	it("sets a policy with no repository and no branch before a create and after a failed clone", async () => {
		const fake = new FakeHost()
		fake.cloneError = "fatal: not found"
		const { stub } = await open(fake)
		expect(await stub.create(repo, "work", [])).toMatchObject({ cloneError: "fatal: not found" })
		expect(fake.policies).toEqual([
			{ repoPath: "", branch: "", allow: [] },
			{ repoPath: "/acme/app", branch: "work", allow: [] },
			{ repoPath: "", branch: "", allow: [] },
		])
	})
})

describe("Workspace output limits (Copilot C10)", () => {
	it("kills and fails a run whose stdout passed 64 MiB, then persists it", async () => {
		const { stub, fake } = await started()
		fake.outputSize = MAX_OUTPUT_BYTES + 1

		expect(await stub.status()).toMatchObject({ state: "failed", error: OUTPUT_ERROR, pushed: { commit: "commit-1" } })
		expect(fake.calls).toContain("signal 100 KILL")
		expect(fake.groups.get(100)?.alive).toBe(false)
	})

	it("fails a run that exited after its stdout passed 64 MiB", async () => {
		const { stub, fake } = await started()
		fake.finishTask(141, [resultLine])
		fake.outputSize = MAX_OUTPUT_BYTES + 1

		expect(await stub.status()).toMatchObject({ state: "failed", error: OUTPUT_ERROR })
	})

	it("takes the result from the events read during the run, not a second read of stdout", async () => {
		const { stub, fake } = await started()
		fake.stdout = new TextEncoder().encode(`${resultLine}\n`)
		await direct(stub, (w) => w.events(0)) // ingested while the task runs

		fake.finishTask(0, []) // the file now holds nothing past what was read
		fake.stdout = new TextEncoder().encode(`${resultLine}\n`)
		expect(await stub.status()).toMatchObject({ state: "succeeded", result: "done" })
	})
})

// F1: the agent can replace a task file with a directory or a FIFO, so every
// probe that reads one throws, on every call. The run must still end.
describe("Workspace task files the agent broke (F1)", () => {
	// A run that ended untrusted: failed, not pushed or snapshotted, its instance
	// destroyed, and later requests answered normally.
	async function endedUntrusted(stub: Stub, fake: FakeHost, error = TASK_FILES_ERROR) {
		expect(await stub.status()).toMatchObject({ state: "failed", error })
		expect(fake.count("push work")).toBe(0)
		expect(fake.count("snapshot")).toBe(0)
		expect(fake.count("destroy")).toBe(1)
		expect(fake.running).toBe(false)
		expect((await stored(stub)).replaceInstance).toBe(false)
		expect(await stub.status()).toMatchObject({ state: "failed", error })
	}

	it.each(["outputBytes", "exitCode", "readTask"] as const)("ends the run when %s throws mid-run, after a KILL of the stored group", async (probe) => {
		const { stub, fake } = await started()
		expect((await stub.status()).state).toBe("running") // the pid is read and stored
		fake.broken.add(probe)

		await endedUntrusted(stub, fake)
		expect(fake.calls).toContain("signal 100 KILL")
		expect(fake.groups.get(100)?.alive).toBe(false)
	})

	it("ends an overdue run by the overdue rule, whatever the probes do", async () => {
		const { stub, fake } = await started()
		expect((await stub.status()).state).toBe("running")
		for (const probe of ["outputBytes", "exitCode", "readTask", "readOutput", "outputDone"] as const) fake.broken.add(probe)
		await edit(stub, (record) => {
			record.startedAt = Date.now() - MAX_RUN_MS - 1
		})

		await endedUntrusted(stub, fake, MAX_RUN_ERROR)
		expect(fake.calls).toContain("signal 100 KILL")
	})

	it("ends an overdue run before it reads any task file", async () => {
		const { stub, fake } = await started()
		fake.finishTask(0, [resultLine])
		await edit(stub, (record) => {
			record.startedAt = Date.now() - MAX_RUN_MS - 1
		})

		expect(await stub.status()).toMatchObject({ state: "failed", error: MAX_RUN_ERROR })
	})

	it("marks the stored snapshot stale, so the next restore says the run's work was lost", async () => {
		const { stub, fake } = await afterOneRun()
		await stub.startRun("second", false, 5)
		fake.broken.add("outputBytes")

		expect(await stub.status()).toMatchObject({ state: "failed", error: TASK_FILES_ERROR })
		expect(await stored(stub)).toMatchObject({ snapshot: "snap-1", snapshotStale: true })
		fake.broken.clear()
		expect(await stub.startRun("third", false, 5)).toEqual({ run: 3 })
		expect(await stub.status()).toMatchObject({ restored: "snapshot", uncommittedLost: true })
	})

	it("stops a run whose probes throw with 200 and an ended state", async () => {
		const { stub, fake } = await started()
		expect((await stub.status()).state).toBe("running")
		fake.broken.add("exitCode")
		fake.broken.add("readTask")

		const status = await stub.stop()
		expect(status).toMatchObject({ state: "failed", error: TASK_FILES_ERROR })
		expect(fake.running).toBe(false)
	})

	it("stops a run whose probes throw inside stop itself, answering stopped and replacing the instance", async () => {
		const { stub, fake } = await started()
		fake.broken.add("outputDone") // read only once the signals are sent

		expect(await stub.stop()).toMatchObject({ state: "stopped", error: TASK_FILES_ERROR })
		expect(fake.calls.filter((c) => c.startsWith("signal 100"))).toContain("signal 100 KILL")
		expect(fake.count("push work")).toBe(0)
		expect(fake.count("destroy")).toBe(1)
		expect(fake.running).toBe(false)
		expect(await stub.status()).toMatchObject({ state: "stopped" })
	})

	it("answers a stop with the ended state when the refresh before it fails", async () => {
		const { stub, fake } = await started()
		fake.finishTask(0, [resultLine])
		fake.failOnce.push = new Error("object reset")

		expect(await stub.stop()).toMatchObject({ state: "succeeded", result: "done" })
		expect(await stored(stub)).toMatchObject({ persistPending: true })
	})

	it("ends the run on the alarm, which then needs no re-arm, instead of throwing every tick", async () => {
		const { stub, fake } = await started()
		fake.broken.add("outputBytes")

		expect(await runDurableObjectAlarm(stub)).toBe(true)
		expect((await stored(stub)).state).toBe("failed")
		expect(await alarmAt(stub)).toBeNull()
	})
})
