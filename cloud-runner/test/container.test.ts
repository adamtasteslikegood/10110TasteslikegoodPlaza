import { describe, expect, it } from "vitest"
import { parseLine } from "../src/agent"
import { asAgent, capDiff, capOutput, MAX_EXEC_OUTPUT_BYTES, completeLines, diffCutLine, leadingType, lineEvent, MAX_DIFF_BYTES, parseTask, run, runBytes } from "../src/container"
import { MAX_PAYLOAD_BYTES } from "../src/events"

const bytes = (text: string) => new TextEncoder().encode(text)
const text = (line: Uint8Array) => new TextDecoder().decode(line)

describe("completeLines", () => {
	it("keeps the bytes after the last newline for later", () => {
		const { lines, consumed } = completeLines(bytes('{"a":1}\n{"b":2}\n{"c"'))
		expect(lines.map(text)).toEqual(['{"a":1}', '{"b":2}'])
		expect(consumed).toBe(16)
	})
	it("consumes nothing without a newline", () => {
		expect(completeLines(bytes('{"partial"'))).toEqual({ lines: [], consumed: 0 })
	})
	it("counts bytes, not characters", () => {
		const { consumed } = completeLines(bytes("é\n"))
		expect(consumed).toBe(3)
	})
	it("keeps a blank line as an empty line", () => {
		expect(completeLines(bytes("\n\n")).lines.map(text)).toEqual(["", ""])
	})
})

describe("leadingType", () => {
	it("reads the type at the start of a line", () => {
		expect(leadingType('{"type":"assistant","message":')).toBe("assistant")
	})
	it("answers unknown otherwise", () => {
		expect(leadingType('{"message":{"type":"x"}')).toBe("unknown")
	})
})

describe("lineEvent", () => {
	it("parses a line under the cap", () => {
		expect(lineEvent(bytes('{"type":"system","x":1}'), parseLine)).toEqual({ type: "system", payload: { type: "system", x: 1 } })
	})
	it("skips a line that is not JSON", () => {
		expect(lineEvent(bytes("not json"), parseLine)).toBeUndefined()
	})
	it("keeps only the type and size of a line over the cap", () => {
		const line = bytes(`{"type":"user","text":"${"x".repeat(MAX_PAYLOAD_BYTES)}"}`)
		expect(lineEvent(line, parseLine)).toEqual({ type: "user", payload: { truncated: true, bytes: line.byteLength } })
	})
})

describe("runBytes", () => {
	const container = (exitCode: number, stdout: string, stderr = "") =>
		({ exec: async () => ({ output: async () => ({ exitCode, stdout: bytes(stdout), stderr: bytes(stderr) }) }) }) as unknown as Container
	it("returns stdout of a command that succeeds", async () => {
		expect(text(await runBytes(container(0, "abc"), ["true"]))).toBe("abc")
	})
	it("throws with the exit code and stderr of a command that fails", async () => {
		await expect(runBytes(container(1, "", "tail: cannot open"), ["tail"])).rejects.toThrow(/exited with 1.*tail: cannot open/)
	})
})

describe("parseTask", () => {
	it("reads the group ID and boot ID of a pid file", () => {
		expect(parseTask("123 0a1b-c2\n")).toEqual({ pid: 123, boot: "0a1b-c2" })
	})
	it("refuses a partial or odd pid file", () => {
		for (const text of ["", "123", "123 ", "x 1", "12 a b", "-1 a"]) expect(parseTask(text), text).toBeUndefined()
	})
	it("refuses group ID 0 or 1, which kill would read as every process (Copilot C2)", () => {
		for (const text of ["0 a", "1 a", "00 a", "01 a"]) expect(parseTask(text), text).toBeUndefined()
		expect(parseTask("2 a")).toEqual({ pid: 2, boot: "a" })
	})
})

describe("exec timeouts", () => {
	// A command that never ends on its own. The fallback timer ends the test
	// even if the timeout were missing; it is far longer than the timeout.
	const hung = () => {
		const seen: { signal?: AbortSignal } = {}
		const container = {
			exec: async (_command: string[], options: { signal?: AbortSignal }) => {
				seen.signal = options.signal
				return { output: () => new Promise((resolve) => setTimeout(() => resolve({ exitCode: 0, stdout: bytes("late"), stderr: bytes("") }), 2000)) }
			},
		} as unknown as Container
		return { container, seen }
	}

	it("rejects a command past its timeout and aborts its signal", async () => {
		const { container, seen } = hung()
		const started = Date.now()
		await expect(run(container, ["git", "push", "origin"], "/", {}, 20)).rejects.toThrow("git push timed out after 0.02 s")
		expect(Date.now() - started).toBeLessThan(1000)
		expect(seen.signal?.aborted).toBe(true)
	})

	it("leaves no timeout pending once the command has ended (PLZG-311)", async () => {
		// A pending timer keeps the Durable Object in memory, and the container's
		// idle timeout only starts once it has left: the timer must go with the command.
		const seen: { signal?: AbortSignal } = {}
		const container = {
			exec: async (_command: string[], options: { signal?: AbortSignal }) => {
				seen.signal = options.signal
				return { output: async () => ({ exitCode: 0, stdout: bytes("done"), stderr: bytes("") }) }
			},
		} as unknown as Container

		expect((await run(container, ["git", "status"], "/", {}, 20)).stdout).toBe("done")
		await new Promise((resolve) => setTimeout(resolve, 80))
		expect(seen.signal?.aborted).toBe(false)
	})

	it("names a shell script by its $0", async () => {
		const { container } = hung()
		await expect(runBytes(container, ["/bin/sh", "-c", "tail", "ingest"], "/", {}, 20)).rejects.toThrow("sh ingest timed out")
	})

	it("names a command run as the agent without the setpriv prefix (PLZG-311)", async () => {
		const { container } = hung()
		await expect(run(container, asAgent(["git", "push", "origin"]), "/", {}, 20)).rejects.toThrow("git push timed out")
		await expect(runBytes(container, asAgent(["/bin/sh", "-c", "git diff", "diff"]), "/", {}, 20)).rejects.toThrow("sh diff timed out")
	})

	it("passes a signal to every exec", async () => {
		const seen: unknown[] = []
		const container = {
			exec: async (_command: string[], options: { signal?: AbortSignal }) => {
				seen.push(options.signal)
				return { output: async () => ({ exitCode: 0, stdout: bytes(""), stderr: bytes("") }) }
			},
		} as unknown as Container
		await run(container, ["true"], "/", {})
		await runBytes(container, ["true"])
		expect(seen).toHaveLength(2)
		for (const signal of seen) expect(signal).toBeInstanceOf(AbortSignal)
	})
})

describe("capDiff", () => {
	it("keeps a diff within the limit as it is", () => {
		expect(capDiff(bytes("diff --git a/x b/x\n+é\n"))).toBe("diff --git a/x b/x\n+é\n")
		const full = new Uint8Array(MAX_DIFF_BYTES).fill(0x61)
		expect(capDiff(full)).toHaveLength(MAX_DIFF_BYTES)
	})

	it("cuts a longer diff after its last whole line and says so", () => {
		const line = "+".padEnd(99, "x") + "\n" // 100 bytes
		const input = bytes(line.repeat(Math.ceil(MAX_DIFF_BYTES / 100) + 5))
		const out = capDiff(input)
		const kept = out.slice(0, -diffCutLine.length)
		expect(out.endsWith(diffCutLine)).toBe(true)
		expect(kept.length % 100).toBe(0)
		expect(bytes(kept).byteLength).toBeLessThanOrEqual(MAX_DIFF_BYTES)
		expect(bytes(kept).byteLength).toBeGreaterThan(MAX_DIFF_BYTES - 100)
	})

	it("cuts at the limit when there is no newline, and never splits the cut line", () => {
		const out = capDiff(new Uint8Array(MAX_DIFF_BYTES + 1).fill(0x61))
		expect(out).toBe(`${"a".repeat(MAX_DIFF_BYTES)}\n${diffCutLine}`)
	})
})

describe("capOutput", () => {
	const bytes = (text: string) => new TextEncoder().encode(text)

	it("keeps output up to the cap and cuts the bytes past it", () => {
		expect(capOutput(bytes("hello"))).toBe("hello")
		expect(capOutput(new Uint8Array(MAX_EXEC_OUTPUT_BYTES).fill(0x61))).toHaveLength(MAX_EXEC_OUTPUT_BYTES)
		expect(capOutput(new Uint8Array(MAX_EXEC_OUTPUT_BYTES + 10).fill(0x61))).toHaveLength(MAX_EXEC_OUTPUT_BYTES)
		expect(capOutput(new ArrayBuffer(3))).toBe("\0\0\0")
	})
})
