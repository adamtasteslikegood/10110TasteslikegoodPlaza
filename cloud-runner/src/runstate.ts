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

export type StopObserved = { exitCode?: number; pidPresent: boolean; taskAlive: boolean; resultSeen: boolean }

const signalExits = new Set([143, 137]) // TERM and KILL

// What a stop request leaves, read after the signals. A run that answered, or
// ended with an exit code of its own, finishes as usual. A task that may still
// be alive (alive, or no pid yet) is never called stopped.
export function stopOutcome(o: StopObserved): "stopped" | "finish" | "still-running" {
	if (o.exitCode !== undefined) {
		return o.resultSeen || !signalExits.has(o.exitCode) ? "finish" : "stopped"
	}

	return !o.pidPresent || o.taskAlive ? "still-running" : "stopped"
}

// Whether the next run can resume the session, at each point of a run.
// Claude Code keeps a session once it has answered. A run that ended on its own
// without answering (a resume that found no session, a crash) leaves none. A run
// cut short keeps the session it resumed; a fresh one may never have saved its own.
export function conversationAfter(point: "started" | "finished" | "stopped" | "lost", resumed: boolean, resultSeen: boolean): boolean {
	if (point === "started") return resumed
	if (resultSeen) return true
	return point !== "finished" && resumed
}
