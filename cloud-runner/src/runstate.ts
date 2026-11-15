import type { RunState } from "./types"

// A run longer than this is killed and fails (controller ruling: 60 minutes).
export const MAX_RUN_MS = 60 * 60 * 1000
export const MAX_RUN_ERROR = "run exceeded 60 minutes"
// The task writes its pid file as it starts; none this long after the start means it never ran.
export const PID_GRACE_MS = 60 * 1000

export type RunCheck = { containerRunning: boolean; exitCode?: number; taskSeen: boolean; taskAlive: boolean; elapsedMs: number }
export type Verdict = "running" | "exited" | "container-gone" | "process-gone" | "never-started" | "overdue"

// What a stored running run really is, given what the container shows now.
// "exited": the caller reads its output and finishes it. The other non-running
// verdicts end the run; all but "container-gone" can still push and snapshot.
export function judgeRun(o: RunCheck): Verdict {
	if (!o.containerRunning) return "container-gone"
	if (o.exitCode !== undefined) return "exited"
	if (o.elapsedMs >= MAX_RUN_MS) return "overdue"
	if (!o.taskSeen) return o.elapsedMs >= PID_GRACE_MS ? "never-started" : "running"
	return o.taskAlive ? "running" : "process-gone"
}

// A run that ended stores persistPending with its end state, and clears it once
// push and snapshot are stored. A pending one is done when the container still
// runs, else given up: that instance's files are gone.
export function persistAction(o: { pending: boolean; containerRunning: boolean }): "none" | "persist" | "abandon" {
	if (!o.pending) return "none"
	return o.containerRunning ? "persist" : "abandon"
}

// The alarm watches a running run, and retries a push and snapshot not yet done.
export function needsAlarm(state: RunState, persistPending: boolean): boolean {
	return state === "running" || persistPending
}

type Workspace = { repo?: string; branch?: string; allow: string[] }

const hostList = (allow: string[]) => [...new Set(allow.map((host) => host.toLowerCase()))].sort().join(" ")

// A PUT on a workspace that exists answers its status only when it asks for the
// same repository, branch and host list; anything else is a conflict.
export function admitCreate(stored: Workspace, wanted: Required<Workspace>): "create" | "same" | "conflict" {
	if (stored.repo === undefined) return "create"
	const same = stored.repo === wanted.repo && stored.branch === wanted.branch && hostList(stored.allow) === hostList(wanted.allow)
	return same ? "same" : "conflict"
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

export type RestorePath = "snapshot" | "branch" | "image"

// How a new container instance gets its files. A snapshot needs a repository;
// one that did not start falls back to a fresh clone of the pushed branch.
export function restorePath(o: { hasSnapshot: boolean; snapshotStartFailed: boolean; hasRepo: boolean }): RestorePath {
	if (!o.hasRepo) return "image"
	return o.hasSnapshot && !o.snapshotStartFailed ? "snapshot" : "branch"
}

export type Restored = {
	restored?: "snapshot" | "branch"
	uncommittedLost?: boolean
	hasConversation: boolean
	keepSnapshot: boolean
	notice?: { notice: "instance started"; generation: number; from: "snapshot" | "branch"; snapshotError?: string }
}

// What a new instance's path does to the record. A snapshot carries the files
// and Claude Code's session; a clone carries neither, so work done in an earlier
// instance and not pushed is gone, and the stored snapshot (absent or broken) is
// dropped. Only an instance that replaces an earlier one is noted.
export function afterRestore(path: RestorePath, o: { generation: number; hasConversation: boolean; snapshotError?: string }): Restored {
	if (path === "image") return { hasConversation: false, keepSnapshot: false }

	const replaces = o.generation > 1
	const notice = replaces
		? { notice: "instance started" as const, generation: o.generation, from: path, ...(o.snapshotError === undefined ? {} : { snapshotError: o.snapshotError }) }
		: undefined
	const fields = path === "snapshot"
		? { restored: path, uncommittedLost: false, hasConversation: o.hasConversation, keepSnapshot: true }
		: { restored: path, uncommittedLost: replaces, hasConversation: false, keepSnapshot: false }

	return notice === undefined ? fields : { ...fields, notice }
}
