import { describe, expect, it } from "vitest"
import { TASK_FILE_REFUSED } from "../src/container"
import { ContainerHost, probeFailure, readFailure, TaskFileError } from "../src/host"

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
