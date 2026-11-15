import { describe, expect, it } from "vitest"
import { agentArgv, agentEnv, outcome, parseLine, resultSentinel, TRUNCATED_RESULT_ERROR } from "../src/agent"

const base = { prompt: "fix it", model: "claude-sonnet-5-5", maxTurns: 20, sessionId: "sess-1" }
const head = ["claude", "--print", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions", "--model", "claude-sonnet-5-5", "--max-turns", "20"]

describe("agentArgv", () => {
	it("starts a session on the first run", () => {
		expect(agentArgv({ ...base, resume: false })).toEqual([...head, "--session-id", "sess-1", "--", "fix it"])
	})
	it("resumes a session on a later run", () => {
		expect(agentArgv({ ...base, resume: true })).toEqual([...head, "--resume", "sess-1", "--", "fix it"])
	})
	it("keeps a prompt that starts with dashes after --", () => {
		const argv = agentArgv({ ...base, prompt: "--help me", resume: false })
		expect(argv.slice(-2)).toEqual(["--", "--help me"])
	})
	it("never disables session persistence", () => {
		expect(agentArgv({ ...base, resume: false })).not.toContain("--no-session-persistence")
	})
})

describe("agentEnv", () => {
	it("has exactly the four variables", () => {
		const env = agentEnv("acct", "gw")
		expect(Object.keys(env).sort()).toEqual(["ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "IS_SANDBOX"])
		expect(env.ANTHROPIC_API_KEY).toBe("provided-by-worker")
		expect(env.ANTHROPIC_BASE_URL).toBe("https://gateway.ai.cloudflare.com/v1/acct/gw/anthropic")
	})
})

describe("parseLine", () => {
	it("parses a JSON object with a type", () => {
		expect(parseLine('{"type":"assistant","x":1}')).toEqual({ type: "assistant", payload: { type: "assistant", x: 1 } })
	})
	it("returns undefined for blank and non-JSON lines", () => {
		expect(parseLine("")).toBeUndefined()
		expect(parseLine("   ")).toBeUndefined()
		expect(parseLine("not json")).toBeUndefined()
	})
	it("returns undefined for JSON that is not an object with a string type", () => {
		expect(parseLine("42")).toBeUndefined()
		expect(parseLine("null")).toBeUndefined()
		expect(parseLine('{"x":1}')).toBeUndefined()
	})
})

describe("outcome", () => {
	it("succeeds on a result line", () => {
		const lines = ['{"type":"system"}', '{"type":"result","subtype":"success","is_error":false,"result":"done"}']
		expect(outcome(lines, 0, "")).toEqual({ state: "succeeded", result: "done" })
	})
	it("fails on an error result, using result then subtype", () => {
		expect(outcome(['{"type":"result","subtype":"error_max_turns","is_error":true,"result":"too many"}'], 1, "")).toEqual({ state: "failed", error: "too many" })
		expect(outcome(['{"type":"result","subtype":"error_max_turns","is_error":true}'], 1, "")).toEqual({ state: "failed", error: "error_max_turns" })
	})
	it("fails with the exit code and stderr when there is no result line", () => {
		expect(outcome(["garbage", '{"type":"assistant"}', ""], 137, "killed")).toEqual({ state: "failed", error: "claude exited with 137: killed" })
	})
	it("lets the last result line decide", () => {
		const lines = ['{"type":"result","is_error":true,"result":"a"}', '{"type":"result","is_error":false,"result":"b"}']
		expect(outcome(lines, 0, "")).toEqual({ state: "succeeded", result: "b" })
	})
	it("treats a successful result with no text as an empty result", () => {
		expect(outcome(['{"type":"result","subtype":"success","is_error":false}'], 0, "")).toEqual({ state: "succeeded", result: "" })
	})
})

// Copilot round 2, E1: a result line over the payload cap keeps what classifies the run.
describe("resultSentinel", () => {
	const big = "x".repeat(1000) // stands for the result text that is dropped
	const line = (fields: Record<string, unknown>) => JSON.stringify({ type: "result", ...fields, result: big })

	it("keeps the classifying fields and drops the result text", () => {
		const usage = { input_tokens: 3, output_tokens: 4 }
		const sentinel = JSON.parse(resultSentinel(line({ subtype: "success", is_error: false, num_turns: 2, total_cost_usd: 0.5, usage, session_id: "s1", other: "y" })))
		expect(sentinel).toEqual({ type: "result", truncated: true, subtype: "success", is_error: false, num_turns: 2, total_cost_usd: 0.5, usage, session_id: "s1" })
	})

	// F1b: a kept field can be as large as the line, and the record must stay small.
	it("drops a kept field over 4 KiB, keeps is_error, and classifies the run the same", () => {
		const usage = { input_tokens: 3, padding: "u".repeat(1024 * 1024) }
		for (const is_error of [false, true]) {
			const sentinel = resultSentinel(line({ subtype: "success", is_error, num_turns: 2, usage, session_id: "s1" }))
			expect(new TextEncoder().encode(sentinel).length).toBeLessThan(16 * 1024)
			expect(JSON.parse(sentinel)).toEqual({ type: "result", truncated: true, subtype: "success", is_error, num_turns: 2, session_id: "s1" })
		}
		expect(outcome([resultSentinel(line({ is_error: false, usage }))], 0, "")).toEqual({ state: "succeeded", result: "", truncated: true })
		expect(outcome([resultSentinel(line({ subtype: "error_max_turns", is_error: true, usage }))], 1, "")).toEqual({ state: "failed", error: "error_max_turns" })
	})

	it("marks a result whose is_error is not a boolean as unreadable", () => {
		for (const fields of [{}, { is_error: "false" }, { is_error: { x: 1 } }, { is_error: null }]) {
			expect(JSON.parse(resultSentinel(line(fields)))).toEqual({ type: "result", truncated: true, unreadable: true })
		}
	})

	it("marks a line it cannot parse, or never saw whole, as unreadable", () => {
		for (const text of [line({ is_error: false }).slice(0, 500), "not json", "[1]", JSON.stringify({ type: "assistant" }), undefined]) {
			expect(JSON.parse(resultSentinel(text))).toEqual({ type: "result", truncated: true, unreadable: true })
		}
	})
})

describe("outcome of a truncated result (Copilot round 2, E1)", () => {
	it("fails an oversized error result", () => {
		const sentinel = resultSentinel(JSON.stringify({ type: "result", subtype: "error_during_execution", is_error: true, result: "x".repeat(1000) }))
		expect(outcome([sentinel], 1, "")).toEqual({ state: "failed", error: "error_during_execution" })
	})

	it("fails an oversized result it could not read, naming the truncated result", () => {
		expect(TRUNCATED_RESULT_ERROR).toContain("result")
		expect(outcome([resultSentinel("{\"type\":\"result\",\"is_er")], 0, "")).toEqual({ state: "failed", error: TRUNCATED_RESULT_ERROR })
	})

	it("succeeds an oversized successful result, with an empty result marked truncated", () => {
		const sentinel = resultSentinel(JSON.stringify({ type: "result", subtype: "success", is_error: false, result: "x".repeat(1000) }))
		expect(outcome([sentinel], 0, "")).toEqual({ state: "succeeded", result: "", truncated: true })
	})
})
