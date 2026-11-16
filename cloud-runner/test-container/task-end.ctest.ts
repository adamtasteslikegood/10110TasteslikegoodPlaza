import { afterAll, beforeAll, describe, expect, it } from "vitest"
import { agentHome, agentUser, asAgent, eventsPath, MAX_STDERR_BYTES, MAX_STDOUT_FILE_BYTES, stderrPath, TASK_FILE_REFUSED, taskDirectory } from "../src/container"
import { ContainerHost, TaskFileError, type Task } from "../src/host"
import { containerOf, inBox, startBox, stopBox, until } from "./box"

// PLZG-311: how a task is ended for certain, and the probe scripts no other
// test drives. Every command is the one the Worker sends, through the real
// ContainerHost, in a container from the real image.

let box: string
let host: ContainerHost

const rootSh = (script: string) => inBox(box, ["/bin/sh", "-c", script])

// How many processes in the box have exactly this command line.
async function running(command: string): Promise<number> {
	const listed = await rootSh(`for d in /proc/[0-9]*; do tr '\\0' ' ' <"$d/cmdline" 2>/dev/null; echo; done`)
	return listed.stdout.split("\n").filter((line) => line.trim() === command).length
}

// Starts argv as a task and answers it once its pid file is written.
async function startTask(argv: string[]): Promise<Task> {
	await host.resetTask()
	await host.startTask(argv, {})
	let task: Awaited<ReturnType<ContainerHost["readTask"]>>
	await until(async () => (task = await host.readTask()) !== undefined)
	if (task === undefined || task === "invalid") throw new Error("no task")
	return task
}

beforeAll(async () => {
	box = startBox()
	host = new ContainerHost(containerOf(box), () => ({}) as Fetcher)
	// The task's working directory; no test here needs a clone in it.
	await rootSh(`install -d -o ${agentUser} -g ${agentUser} /workspace/repo`)
})

afterAll(() => stopBox(box))

describe("ending the agent's processes", () => {
	it("reaches a process that left the task's group, which the group KILL does not", async () => {
		const task = await startTask(["/bin/sh", "-c", "setsid -f sleep 3001; sleep 3002"])
		await until(async () => (await running("sleep 3001")) === 1 && (await running("sleep 3002")) === 1)

		await host.signalTask(task, "KILL")
		await until(async () => !(await host.taskAlive(task)))
		expect(await running("sleep 3002")).toBe(0)
		expect(await running("sleep 3001")).toBe(1)
		// It still holds the task's output pipes, so the copiers have not ended.
		expect(await host.outputDone()).toBe(false)

		expect(await host.endAgentProcesses()).toBe(true)
		expect(await running("sleep 3001")).toBe(0)
		await until(() => host.outputDone())
		// The leader was KILLed with its group before the sweep, so it wrote no exit code.
		expect(await host.exitCode()).toBeUndefined()
	})

	it("leaves root's processes alone, and says so when the agent has none", async () => {
		await rootSh("setsid -f sleep 3003")
		expect(await host.endAgentProcesses()).toBe(true)
		expect(await running("sleep 3003")).toBe(1)
		expect(await running("sleep infinity")).toBe(1)
	})

	it("ends a process the agent started outside any task", async () => {
		await inBox(box, asAgent(["env", `HOME=${agentHome}`, "/bin/sh", "-c", "setsid -f sleep 3004"]))
		expect(await running("sleep 3004")).toBe(1)
		expect(await host.endAgentProcesses()).toBe(true)
		expect(await running("sleep 3004")).toBe(0)
	})

	it("alone would let the leader record 137, which is why the group KILL comes first", async () => {
		await startTask(["sleep", "3005"])
		await until(async () => (await running("sleep 3005")) === 1)

		expect(await host.endAgentProcesses()).toBe(true)
		let code: number | undefined
		await until(async () => (code = await host.exitCode()) !== undefined)
		expect(code).toBe(137)
	})
})

describe("ending a task's group", () => {
	it("ends a group that ignores TERM with KILL, and the leader then writes no exit code", async () => {
		const task = await startTask(["/bin/sh", "-c", "trap '' TERM; sleep 3006"])
		await until(async () => (await running("sleep 3006")) === 1)

		await host.signalTask(task, "TERM")
		await new Promise((resolve) => setTimeout(resolve, 1000))
		expect(await host.taskAlive(task)).toBe(true)
		expect(await host.exitCode()).toBeUndefined()

		await host.signalTask(task, "KILL")
		await until(async () => !(await host.taskAlive(task)))
		expect(await running("sleep 3006")).toBe(0)
		// The copiers are in sessions of their own: they drain and end.
		await until(() => host.outputDone())
		expect(await host.exitCode()).toBeUndefined()
	})

	it("signals nothing for a task of another boot", async () => {
		const task = await startTask(["sleep", "3007"])
		await until(async () => (await running("sleep 3007")) === 1)

		const other = { pid: task.pid, boot: "another-boot" }
		expect(await host.taskAlive(other)).toBe(false)
		await host.signalTask(other, "KILL")
		await new Promise((resolve) => setTimeout(resolve, 500))
		expect(await host.taskAlive(task)).toBe(true)

		await host.signalTask(task, "KILL")
		await until(async () => !(await host.taskAlive(task)))
	})
})

describe("the output caps", () => {
	it("keeps one byte more of stdout than a run may write, so a run over the cap shows", async () => {
		await startTask(["/bin/sh", "-c", `head -c ${MAX_STDOUT_FILE_BYTES + 1024 * 1024} /dev/zero`])
		await until(() => host.outputDone(), 60_000)

		expect(await host.outputBytes()).toBe(MAX_STDOUT_FILE_BYTES)
		// The writer does not block on a full pipe: the copier ended, so it got SIGPIPE.
		let code: number | undefined
		await until(async () => (code = await host.exitCode()) !== undefined)
		expect(code).toBe(141)
	})

	it("keeps the last MiB of stderr", async () => {
		await startTask(["/bin/sh", "-c", `{ head -c ${MAX_STDERR_BYTES + 4096} /dev/zero | tr '\\0' a; echo the end; } >&2`])
		await until(() => host.outputDone(), 60_000)

		expect((await rootSh(`wc -c <${stderrPath}`)).stdout.trim()).toBe(String(MAX_STDERR_BYTES))
		expect((await host.stderrTail()).endsWith("athe end\n")).toBe(true)
	})
})

describe("the stdout.log probes", () => {
	const decoder = new TextDecoder()

	it("read a size of 0 and no bytes before the file exists", async () => {
		await host.resetTask()
		expect(await host.outputBytes()).toBe(0)
		expect((await host.readOutput(0, 100)).byteLength).toBe(0)
	})

	it("read a range of the file from a byte offset", async () => {
		await rootSh(`printf 'one\\ntwo\\nthree\\n' >${eventsPath}`)
		expect(await host.outputBytes()).toBe(14)
		expect(decoder.decode(await host.readOutput(0, 100))).toBe("one\ntwo\nthree\n")
		expect(decoder.decode(await host.readOutput(4, 3))).toBe("two")
		expect((await host.readOutput(14, 100)).byteLength).toBe(0)
	})

	it("measure a line from an offset, and say whether it has ended", async () => {
		await rootSh(`{ echo short; head -c 5000 /dev/zero | tr '\\0' x; echo; printf unfinished; } >${eventsPath}`)
		expect(await host.lineLength(0)).toEqual({ bytes: 6, ended: true })
		expect(await host.lineLength(6)).toEqual({ bytes: 5001, ended: true })
		expect(await host.lineLength(6 + 5001)).toEqual({ bytes: 10, ended: false })
	})

	it.each([
		["a directory", `rm -rf ${eventsPath} && mkdir ${eventsPath}`],
		["a FIFO, which would block a read", `rm -rf ${eventsPath} && mkfifo ${eventsPath}`],
		["a link to a directory", `rm -rf ${eventsPath} && ln -s ${taskDirectory} ${eventsPath}`],
	])("refuse %s in the file's place with the task-file code", async (_what, plant) => {
		expect((await rootSh(plant)).exitCode).toBe(0)

		for (const probe of [host.outputBytes(), host.readOutput(0, 100)]) {
			const error = await probe.then(
				() => undefined,
				(e: unknown) => e,
			)
			expect(error).toBeInstanceOf(TaskFileError)
			expect((error as Error).message).toContain(`exited ${TASK_FILE_REFUSED}`)
		}

		await rootSh(`rm -rf ${eventsPath}`)
	})
})
