import { describe, expect, it } from "vitest"
import { admit, conversation, settle } from "../src/runstate"

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
