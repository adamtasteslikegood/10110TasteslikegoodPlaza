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
