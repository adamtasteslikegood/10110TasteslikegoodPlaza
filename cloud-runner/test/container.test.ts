import { describe, expect, it } from "vitest"
import { parseLine } from "../src/agent"
import { completeLines, leadingType, lineEvent, parseTask, runBytes } from "../src/container"
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
})
