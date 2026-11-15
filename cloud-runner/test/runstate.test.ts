import { describe, expect, it } from "vitest"
import { admit, afterRestore, conversation, conversationAfter, restorePath, settle, stopOutcome } from "../src/runstate"

describe("settle", () => {
	it("calls a running run lost when the container is gone", () => {
		expect(settle("running", { containerRunning: false, pidAlive: false })).toBe("lost")
	})
	it("calls a running run lost when the process is gone", () => {
		expect(settle("running", { containerRunning: true, pidAlive: false })).toBe("lost")
	})
	it("keeps a run that is alive", () => {
		expect(settle("running", { containerRunning: true, pidAlive: true })).toBe("running")
	})
	it("leaves a run with an exit code running for the caller to finish", () => {
		expect(settle("running", { containerRunning: false, pidAlive: false, exitCode: 0 })).toBe("running")
		expect(settle("running", { containerRunning: true, pidAlive: false, exitCode: 1 })).toBe("running")
	})
	it("passes every other state through", () => {
		for (const s of ["none", "idle", "succeeded", "failed", "stopped", "lost"] as const) {
			expect(settle(s, { containerRunning: false, pidAlive: false })).toBe(s)
		}
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
