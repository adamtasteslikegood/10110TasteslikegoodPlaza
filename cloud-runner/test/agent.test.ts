import { describe, expect, it } from "vitest"
import { agentArgv, agentEnv, outcome, parseLine } from "../src/agent"

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
