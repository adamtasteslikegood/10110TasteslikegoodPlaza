import { describe, expect, it } from "vitest"
import { afterPersist, pushErrorText } from "../src/persist"

describe("pushErrorText", () => {
	it("keeps the last 2000 characters", () => {
		const text = pushErrorText(`${"a".repeat(3000)}end`, 128)
		expect(text).toHaveLength(2000)
		expect(text.endsWith("end")).toBe(true)
	})
	it("strips a credential from a URL", () => {
		expect(pushErrorText("fatal: unable to access 'https://user:tok@github.com/o/r/': 403", 128)).toBe(
			"fatal: unable to access 'https://github.com/o/r/': 403",
		)
		expect(pushErrorText("https://x-access-token:ghp_secret@github.com/o/r", 128)).not.toContain("ghp_secret")
	})
	it("strips before cutting, so no tail of a credential is left", () => {
		const text = pushErrorText(`https://user:${"t".repeat(2500)}@github.com/o/r`, 128)
		expect(text).toBe("https://github.com/o/r")
	})
	it("leaves a plain URL and a later address alone", () => {
		const stderr = "remote: Permission to o/r denied. https://github.com/o/r contact a@b.c"
		expect(pushErrorText(stderr, 128)).toBe(stderr)
	})
	it("names the exit code when git wrote nothing", () => {
		expect(pushErrorText("", 128)).toBe("git push exited with 128")
	})
})

describe("afterPersist", () => {
	it("stores the pushed commit, clears the push error and keeps the new snapshot", () => {
		expect(afterPersist(4, { commit: "abc" }, { id: "s1", size: 10 })).toEqual({
			pushed: { commit: "abc" },
			pushError: undefined,
			snapshot: "s1",
			notices: [
				{ notice: "pushed", run: 4, commit: "abc" },
				{ notice: "snapshot saved", run: 4, bytes: 10 },
			],
		})
	})
	it("a refused push keeps the last pushed commit and still keeps the snapshot", () => {
		const after = afterPersist(2, { error: "denied" }, { id: "s2", size: 5 })
		expect(after).not.toHaveProperty("pushed")
		expect(after).toMatchObject({ pushError: "denied", snapshot: "s2" })
		expect(after.notices[0]).toEqual({ notice: "push failed", run: 2, error: "denied" })
	})
	it("a failed snapshot drops the stored one and says why", () => {
		const after = afterPersist(3, { commit: "abc" }, { error: "not supported" })
		expect(after).toHaveProperty("snapshot", undefined)
		expect(after.notices[1]).toEqual({ notice: "snapshot failed", run: 3, error: "not supported" })
	})
})
