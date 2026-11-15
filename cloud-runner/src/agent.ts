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

export function outcome(
	lines: Iterable<string>,
	exitCode: number,
	stderrTail: string,
): { state: "succeeded"; result: string } | { state: "failed"; error: string } {
	let last: { is_error?: unknown; result?: unknown; subtype?: unknown } | undefined
	for (const line of lines) {
		const parsed = parseLine(line)
		if (parsed?.type === "result") last = parsed.payload as typeof last
	}
	if (!last) return { state: "failed", error: `claude exited with ${exitCode}: ${stderrTail}` }
	const result = typeof last.result === "string" ? last.result : undefined
	if (last.is_error === true) return { state: "failed", error: result ?? (typeof last.subtype === "string" ? last.subtype : "error") }
	return { state: "succeeded", result: result ?? "" }
}
