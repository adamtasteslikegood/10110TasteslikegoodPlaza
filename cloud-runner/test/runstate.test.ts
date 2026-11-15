import { describe, expect, it } from "vitest"
import {
	admit,
	admitCreate,
	afterRestore,
	conversation,
	conversationAfter,
	judgeRun,
	MAX_RUN_MS,
	needsAlarm,
	persistAction,
	PID_GRACE_MS,
	restorePath,
	stopOutcome,
	type RunCheck,
} from "../src/runstate"

const check = (o: Partial<RunCheck>): RunCheck => ({ containerRunning: true, taskSeen: true, taskAlive: true, elapsedMs: 1000, ...o })

describe("judgeRun", () => {
	it("calls a run whose container is gone container-gone, exit code or not", () => {
		expect(judgeRun(check({ containerRunning: false }))).toBe("container-gone")
		expect(judgeRun(check({ containerRunning: false, exitCode: 0 }))).toBe("container-gone")
	})
	it("leaves a run with an exit code for the caller to finish", () => {
		expect(judgeRun(check({ exitCode: 1, taskAlive: false }))).toBe("exited")
		expect(judgeRun(check({ exitCode: 0, elapsedMs: MAX_RUN_MS * 2 }))).toBe("exited")
	})
	it("keeps a run that is alive", () => {
		expect(judgeRun(check({}))).toBe("running")
	})
	it("calls a run whose process group is gone without an exit code process-gone", () => {
		expect(judgeRun(check({ taskAlive: false }))).toBe("process-gone")
	})
	it("gives a run with no pid file 60 s, then calls it never-started", () => {
		expect(judgeRun(check({ taskSeen: false, taskAlive: false, elapsedMs: PID_GRACE_MS - 1 }))).toBe("running")
		expect(judgeRun(check({ taskSeen: false, taskAlive: false, elapsedMs: PID_GRACE_MS }))).toBe("never-started")
	})
	it("calls a live run overdue at 60 minutes", () => {
		expect(MAX_RUN_MS).toBe(60 * 60 * 1000)
		expect(judgeRun(check({ elapsedMs: MAX_RUN_MS - 1 }))).toBe("running")
		expect(judgeRun(check({ elapsedMs: MAX_RUN_MS }))).toBe("overdue")
		expect(judgeRun(check({ taskSeen: false, taskAlive: false, elapsedMs: MAX_RUN_MS }))).toBe("overdue")
	})
})

describe("persistAction", () => {
	it("persists a pending push while the container runs, and gives it up when it is gone", () => {
		expect(persistAction({ pending: false, containerRunning: true })).toBe("none")
		expect(persistAction({ pending: false, containerRunning: false })).toBe("none")
		expect(persistAction({ pending: true, containerRunning: true })).toBe("persist")
		expect(persistAction({ pending: true, containerRunning: false })).toBe("abandon")
	})
})

describe("needsAlarm", () => {
	it("keeps the alarm for a running run or a pending push", () => {
		expect(needsAlarm("running", false)).toBe(true)
		expect(needsAlarm("succeeded", true)).toBe(true)
		for (const s of ["none", "idle", "succeeded", "failed", "stopped", "lost"] as const) expect(needsAlarm(s, false)).toBe(false)
	})
})

describe("admitCreate", () => {
	const repo = "https://github.com/acme/app"
	it("creates when there is no workspace", () => {
		expect(admitCreate({ allow: [] }, { repo, branch: "main", allow: [] })).toBe("create")
	})
	it("answers the same workspace for the same repo, branch and host list in any order", () => {
		expect(admitCreate({ repo, branch: "main", allow: ["a.example", "b.example"] }, { repo, branch: "main", allow: ["b.example", "a.example"] })).toBe("same")
	})
	it("answers conflict for a different host list, branch or repo", () => {
		const stored = { repo, branch: "main", allow: ["a.example"] }
		expect(admitCreate(stored, { repo, branch: "main", allow: ["b.example"] })).toBe("conflict")
		expect(admitCreate(stored, { repo, branch: "main", allow: [] })).toBe("conflict")
		expect(admitCreate(stored, { repo, branch: "dev", allow: ["a.example"] })).toBe("conflict")
		expect(admitCreate(stored, { repo: `${repo}2`, branch: "main", allow: ["a.example"] })).toBe("conflict")
	})
})

describe("admit", () => {
	it("refuses a busy workspace", () => expect(admit("running", true)).toBe("busy"))
	it("starts from idle and lost", () => {
		expect(admit("idle", true)).toBe("start")
		expect(admit("lost", true)).toBe("start")
	})
	it("starts after a finished run", () => {
		for (const s of ["succeeded", "failed", "stopped"] as const) expect(admit(s, true)).toBe("start")
	})
	it("reports a missing workspace first", () => {
		expect(admit("none", false)).toBe("missing")
		expect(admit("running", false)).toBe("missing")
	})
})

describe("conversation", () => {
	it("resumes the stored conversation", () => {
		expect(conversation(false, true, "a", "b")).toEqual({ sessionId: "a", resume: true })
	})
	it("starts a new one when fresh", () => {
		expect(conversation(true, true, "a", "b")).toEqual({ sessionId: "b", resume: false })
	})
	it("starts a new one when there is no conversation", () => {
		expect(conversation(false, false, "a", "b")).toEqual({ sessionId: "b", resume: false })
	})
	it("starts a new one when the stored id is missing", () => {
		expect(conversation(false, true, undefined, "b")).toEqual({ sessionId: "b", resume: false })
	})
})

describe("stopOutcome", () => {
	const base = { pidPresent: true, taskAlive: false, resultSeen: false }
	it("calls a run killed by the signal stopped", () => {
		expect(stopOutcome({ ...base, exitCode: 143 })).toBe("stopped")
		expect(stopOutcome({ ...base, exitCode: 137 })).toBe("stopped")
	})
	it("finishes a run that ended on its own before the signal", () => {
		expect(stopOutcome({ ...base, exitCode: 0 })).toBe("finish")
		expect(stopOutcome({ ...base, exitCode: 1 })).toBe("finish")
	})
	it("finishes a run whose result was written, whatever its exit code", () => {
		expect(stopOutcome({ ...base, exitCode: 143, resultSeen: true })).toBe("finish")
		expect(stopOutcome({ ...base, exitCode: 137, resultSeen: true })).toBe("finish")
	})
	it("never calls a run stopped while its task is alive", () => {
		expect(stopOutcome({ ...base, taskAlive: true })).toBe("still-running")
	})
	it("never calls a run stopped before its task wrote its pid", () => {
		expect(stopOutcome({ ...base, pidPresent: false })).toBe("still-running")
		expect(stopOutcome({ ...base, pidPresent: false, taskAlive: true })).toBe("still-running")
	})
	it("calls a run stopped when its task is gone but left no exit code", () => {
		expect(stopOutcome(base)).toBe("stopped")
	})
})

describe("conversationAfter", () => {
	it("at start: only a resumed run has a conversation", () => {
		expect(conversationAfter("started", true, false)).toBe(true)
		expect(conversationAfter("started", false, false)).toBe(false)
	})
	it("a run that answered keeps its conversation, however it ended", () => {
		for (const end of ["finished", "stopped", "lost"] as const) {
			expect(conversationAfter(end, false, true), end).toBe(true)
			expect(conversationAfter(end, true, true), end).toBe(true)
		}
	})
	it("a run that ended on its own without answering starts the next one fresh", () => {
		expect(conversationAfter("finished", true, false)).toBe(false)
		expect(conversationAfter("finished", false, false)).toBe(false)
	})
	it("a run cut short keeps a resumed conversation, not a fresh one", () => {
		for (const end of ["stopped", "lost"] as const) {
			expect(conversationAfter(end, true, false), end).toBe(true)
			expect(conversationAfter(end, false, false), end).toBe(false)
		}
	})
})

describe("restorePath", () => {
	const base = { hasSnapshot: true, snapshotStartFailed: false, hasRepo: true }
	it("starts from the stored snapshot", () => expect(restorePath(base)).toBe("snapshot"))
	it("clones the branch when there is no snapshot", () => {
		expect(restorePath({ ...base, hasSnapshot: false })).toBe("branch")
	})
	it("clones the branch when the snapshot did not start", () => {
		expect(restorePath({ ...base, snapshotStartFailed: true })).toBe("branch")
	})
	it("starts a bare image before the workspace has a repository", () => {
		expect(restorePath({ hasSnapshot: false, snapshotStartFailed: false, hasRepo: false })).toBe("image")
		expect(restorePath({ ...base, hasRepo: false })).toBe("image")
	})
})

describe("afterRestore", () => {
	it("a snapshot keeps the conversation and the snapshot, and loses nothing", () => {
		for (const hasConversation of [true, false]) {
			expect(afterRestore("snapshot", { generation: 3, hasConversation })).toEqual({
				restored: "snapshot",
				uncommittedLost: false,
				hasConversation,
				keepSnapshot: true,
				notice: { notice: "instance started", generation: 3, from: "snapshot" },
			})
		}
	})
	it("a branch clone after an earlier instance forgets the conversation and says work was lost", () => {
		expect(afterRestore("branch", { generation: 2, hasConversation: true })).toEqual({
			restored: "branch",
			uncommittedLost: true,
			hasConversation: false,
			keepSnapshot: false,
			notice: { notice: "instance started", generation: 2, from: "branch" },
		})
	})
	it("names why the snapshot was not used", () => {
		expect(afterRestore("branch", { generation: 2, hasConversation: true, snapshotError: "Snapshot not found" }).notice).toEqual({
			notice: "instance started",
			generation: 2,
			from: "branch",
			snapshotError: "Snapshot not found",
		})
	})
	it("a first instance loses nothing and appends no notice", () => {
		const first = afterRestore("branch", { generation: 1, hasConversation: false })
		expect(first.uncommittedLost).toBe(false)
		expect(first.notice).toBeUndefined()
	})
	it("a bare image sets no restore fields and appends no notice", () => {
		expect(afterRestore("image", { generation: 2, hasConversation: true })).toEqual({ hasConversation: false, keepSnapshot: false })
	})
})
