import { describe, expect, it } from "vitest"
import { AGENT_LEFT, agentHome, agentUser, asAgent, NO_AGENT_USER, repositoryDirectory, resetTaskCommand, TASK_FILE_REFUSED, taskDirectory } from "../src/container"
import { ContainerHost, parseExitCode, probeFailure, readFailure, TaskFileError } from "../src/host"

// G2: only the probe scripts' own refusal code, and only the listed file-level
// read errors, mean a task file is not what the runner wrote.

// A container whose every exec ends with this exit code and stderr.
const exiting = (exitCode: number, stdout = "") =>
	({
		exec: async () => ({
			output: async () => ({ exitCode, stdout: new TextEncoder().encode(stdout), stderr: new TextEncoder().encode("probe said no") }),
		}),
	}) as unknown as Container

const hostExiting = (exitCode: number, stdout = "") => new ContainerHost(exiting(exitCode, stdout), () => ({}) as Fetcher)

// What the sandbox SDK throws for a failed file operation, as SandboxFileError.is reads it.
const fileError = (code: string) =>
	Object.assign(new Error(`${code} on read`), { name: "SandboxFileError", code, operation: "readFile", path: "/workspace/task/pid", detail: "" })

describe("probe exit codes (G2)", () => {
	it("refuses with exit 64, which is TASK_FILE_REFUSED", () => {
		expect(TASK_FILE_REFUSED).toBe(64)
	})

	it.each([137, 143, 127, 126, 255, 1, 2])("treats exit %i of the stdout.log probes as a plain error", async (code) => {
		const host = hostExiting(code)
		for (const probe of [host.outputBytes(), host.readOutput(0, 10)]) {
			const error = await probe.then(() => undefined, (e: unknown) => e)
			expect(error).toBeInstanceOf(Error)
			expect(error).not.toBeInstanceOf(TaskFileError)
			expect((error as Error).message).toContain(`exited ${code}`)
		}
	})

	it("treats the refusal code of the stdout.log probes as a TaskFileError", async () => {
		const host = hostExiting(TASK_FILE_REFUSED)
		await expect(host.outputBytes()).rejects.toBeInstanceOf(TaskFileError)
		await expect(host.readOutput(0, 10)).rejects.toBeInstanceOf(TaskFileError)
	})

	it("reads a size and a chunk when the probes exit 0", async () => {
		expect(await hostExiting(0, "42\n").outputBytes()).toBe(42)
		expect(new TextDecoder().decode(await hostExiting(0, "abc").readOutput(0, 10))).toBe("abc")
	})

	it("names the code in the error, whichever class it is", () => {
		expect(probeFailure("read it", 64, "x")).toBeInstanceOf(TaskFileError)
		expect(probeFailure("read it", 143, "x").message).toContain("exited 143")
	})
})

describe("task file read errors (G2)", () => {
	it.each(["EISDIR", "ENOTDIR", "ELOOP", "ENXIO", "EACCES", "EPERM"])("classifies %s as a TaskFileError", (code) => {
		expect(readFailure("/workspace/task/pid", fileError(code))).toBeInstanceOf(TaskFileError)
	})

	it.each(["EIO", "ENOSPC", "EMFILE", "ENOMEM", "UNKNOWN"])("keeps %s as the plain error it was", (code) => {
		const error = fileError(code)
		expect(readFailure("/workspace/task/pid", error)).toBe(error)
	})

	it("keeps an error that is not a file error as it was", () => {
		const error = new Error("transport closed")
		expect(readFailure("/workspace/task/pid", error)).toBe(error)
	})
})

// G6: the runner writes exit-code with a temp file and a rename, so the file is
// one decimal exit status and a newline, or it is not what the runner wrote.
describe("exit-code file (G6)", () => {
	it.each([
		["0\n", 0],
		["0", 0],
		["143", 143],
		["255\n", 255],
		["1\n", 1],
	])("reads %j as %i", (text, code) => {
		expect(parseExitCode(text)).toBe(code)
	})

	it.each(["0abc", "abc", "-1", "256", "1e2", " 0", "00", "", "\n", "0\n\n", "0 ", "+1", "0x1", "1.0", "1000"])("refuses %j as a TaskFileError", (text) => {
		expect(() => parseExitCode(text)).toThrow(TaskFileError)
	})

	// readOptionalText answers undefined for ENOENT; that stays "no exit code yet".
	it("reads no exit code while the file does not exist", () => {
		expect(parseExitCode(undefined)).toBeUndefined()
	})
})

// PLZG-311: the agent is not root, and the clone's config, hooks and drivers are
// the agent's to write. The container tests (test-container/) show what these
// commands do in a real container; here, which user each is sent as.
describe("who runs what (PLZG-311)", () => {
	type Sent = { command: string[]; cwd?: string; env?: Record<string, string>; user?: string }
	const agentPrefix = asAgent([])

	// A container that records every exec and answers it with exit 0 and this stdout.
	const recording = (stdout = "") => {
		const sent: Sent[] = []
		const container = {
			running: true,
			exec: async (command: string[], options: { cwd?: string; env?: Record<string, string>; user?: string }) => {
				sent.push({ command, cwd: options.cwd, env: options.env, user: options.user })
				return { output: async () => ({ exitCode: 0, stdout: new TextEncoder().encode(stdout), stderr: new Uint8Array() }) }
			},
		} as unknown as Container
		return { sent, host: new ContainerHost(container, () => ({}) as Fetcher) }
	}

	const asTheAgent = (sent: Sent) => agentPrefix.every((part, i) => sent.command[i] === part)

	it("sends every command of a clone, push, diff and test exec in the clone as the agent, with the agent's home", async () => {
		const { sent, host } = recording("abc\n")
		await host.clone("https://github.com/o/r", "main")
		await host.push("main")
		await host.diff()
		await host.exec(["git", "status"])

		const inClone = sent.filter((s) => s.cwd === repositoryDirectory || s.command.includes("git"))
		expect(inClone.length).toBeGreaterThanOrEqual(6)
		for (const s of inClone) {
			expect(asTheAgent(s), s.command.join(" ")).toBe(true)
			expect(s.env?.HOME ?? agentHome, s.command.join(" ")).toBe(agentHome)
			expect(s.user).toBeUndefined()
		}
	})

	it("starts the task's leader as root and only the agent's command as the agent", async () => {
		const { sent, host } = recording()
		await host.startTask(["claude", "--print"], { HOME: agentHome })
		const [launch] = sent
		expect(launch.command.slice(0, 2)).toEqual(["/bin/sh", "-c"])
		expect(launch.command.slice(-(agentPrefix.length + 2))).toEqual([...agentPrefix, "claude", "--print"])
		expect(launch.command).toContain(taskDirectory)
	})

	it("makes the task directory as root, for root alone", async () => {
		const { sent, host } = recording()
		await host.resetTask()
		expect(sent.map((s) => s.command)).toEqual([resetTaskCommand])
		expect(resetTaskCommand.slice(-2)).toEqual(["root", "700"])
	})

	it("sweeps the agent user's processes by name, and only exit 0 means none is left", async () => {
		const { sent, host } = recording()
		expect(await host.endAgentProcesses()).toBe(true)
		expect(sent[0].command.slice(0, 2)).toEqual(["/bin/sh", "-c"])
		expect(sent[0].command.at(-1)).toBe(agentUser)
		expect(sent[0].command[2]).toContain(`[ "$uid" -gt 0 ] || exit ${NO_AGENT_USER}`)

		// The script's own answers: a process is left, or the image has no such user.
		for (const code of [AGENT_LEFT, NO_AGENT_USER]) expect(await hostExiting(code).endAgentProcesses()).toBe(false)
	})

	it.each([137, 143, 126, 127, 255, 1, 2])("treats exit %i of the sweep as a plain error, which says nothing about the agent's processes (G2)", async (code) => {
		await expect(hostExiting(code).endAgentProcesses()).rejects.toThrow(`exited ${code}`)
	})

	it("runs a test exec as root, with root's home, only when asked", async () => {
		const { sent, host } = recording()
		await host.exec(["id"], true)
		expect(sent[0].command).toEqual(["id"])
		expect(sent[0].env?.HOME).toBe("/root")
	})
})
