import type { RunState } from "./types"

export type Observed = { containerRunning: boolean; pidAlive: boolean; exitCode?: number }

// What the stored state really is, given what the container shows now.
// A run with an exit code stays "running": the caller reads its output and finishes it.
export function settle(stored: RunState, o: Observed): RunState {
	if (stored !== "running") return stored
	if (o.exitCode !== undefined) return "running"
	return o.containerRunning && o.pidAlive ? "running" : "lost"
}

export function admit(settled: RunState, hasWorkspace: boolean): "start" | "busy" | "missing" {
	if (!hasWorkspace) return "missing"
	return settled === "running" ? "busy" : "start"
}

export function conversation(fresh: boolean, hasConversation: boolean, storedId: string | undefined, newId: string): { sessionId: string; resume: boolean } {
	if (!fresh && hasConversation && storedId) return { sessionId: storedId, resume: true }
	return { sessionId: newId, resume: false }
}
