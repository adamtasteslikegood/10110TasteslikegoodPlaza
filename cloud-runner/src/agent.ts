export type RunOptions = { prompt: string; model: string; maxTurns: number; sessionId: string; resume: boolean }

export function agentArgv(o: RunOptions): string[] {
	return [
		"claude",
		"--print",
		"--output-format",
		"stream-json",
		"--verbose",
		"--dangerously-skip-permissions",
		"--model",
		o.model,
		"--max-turns",
		String(o.maxTurns),
		...(o.resume ? ["--resume", o.sessionId] : ["--session-id", o.sessionId]),
		"--",
		o.prompt,
	]
}

export function agentEnv(accountId: string, gatewayId: string): Record<string, string> {
	return {
		ANTHROPIC_API_KEY: "provided-by-worker",
		ANTHROPIC_BASE_URL: `https://gateway.ai.cloudflare.com/v1/${accountId}/${gatewayId}/anthropic`,
		CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
		IS_SANDBOX: "1",
	}
}

// undefined for a blank line, text that is not JSON, or JSON that is not an object with a string `type`.
export function parseLine(line: string): { type: string; payload: unknown } | undefined {
	const text = line.trim()
	if (!text) return undefined
	let payload: unknown
	try {
		payload = JSON.parse(text)
	} catch {
		return undefined
	}
	if (typeof payload !== "object" || payload === null) return undefined
	const type = (payload as { type?: unknown }).type
	return typeof type === "string" ? { type, payload } : undefined
}

export const TRUNCATED_RESULT_ERROR = "the run's result was over 256 KiB and could not be read"

const KEPT_RESULT_FIELDS = ["subtype", "num_turns", "total_cost_usd", "usage", "session_id"]
// A kept field whose JSON is longer than this is dropped, so the stored record stays small (F1b).
export const MAX_KEPT_FIELD_BYTES = 4096

const encoder = new TextEncoder()

// What is kept of a result line over the payload cap (Copilot round 2, E1):
// is_error and the other fields that classify the run, each at most
// MAX_KEPT_FIELD_BYTES, without the result text. A line that does not parse as
// a result, whose is_error is not a boolean, or that was never read whole
// (undefined), is marked unreadable, and outcome() fails the run on it.
export function resultSentinel(text: string | undefined): string {
	const parsed = text === undefined ? undefined : parseLine(text)
	const payload = parsed?.payload as Record<string, unknown> | undefined

	if (parsed?.type !== "result" || typeof payload?.is_error !== "boolean") {
		return JSON.stringify({ type: "result", truncated: true, unreadable: true })
	}

	const small = (name: string) => name in payload && encoder.encode(JSON.stringify(payload[name]) ?? "").length <= MAX_KEPT_FIELD_BYTES
	const kept = Object.fromEntries(KEPT_RESULT_FIELDS.filter(small).map((name) => [name, payload[name]]))
	return JSON.stringify({ type: "result", truncated: true, is_error: payload.is_error, ...kept })
}

export function outcome(
	lines: Iterable<string>,
	exitCode: number,
	stderrTail: string,
): { state: "succeeded"; result: string; truncated?: true } | { state: "failed"; error: string } {
	let last: { is_error?: unknown; result?: unknown; subtype?: unknown; truncated?: unknown; unreadable?: unknown } | undefined
	for (const line of lines) {
		const parsed = parseLine(line)
		if (parsed?.type === "result") last = parsed.payload as typeof last
	}
	if (!last) return { state: "failed", error: `claude exited with ${exitCode}: ${stderrTail}` }
	if (last.unreadable === true) return { state: "failed", error: TRUNCATED_RESULT_ERROR }
	const result = typeof last.result === "string" ? last.result : undefined
	if (last.is_error === true) return { state: "failed", error: result ?? (typeof last.subtype === "string" ? last.subtype : "error") }
	return last.truncated === true ? { state: "succeeded", result: "", truncated: true } : { state: "succeeded", result: result ?? "" }
}
