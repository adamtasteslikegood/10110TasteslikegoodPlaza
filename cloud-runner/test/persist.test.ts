import { describe, expect, it } from "vitest"
import { imageLayout, layoutPath } from "../src/container"
import { abandonedPushError, abandonSnapshot, afterAbandon, afterPush, afterSnapshot, gitErrorText, MAX_SNAPSHOT_ATTEMPTS, pushErrorText, startFromImage, startFromSnapshot, within } from "../src/persist"

// Fixtures with userinfo are assembled from parts, so no line of this file looks like a
// credential in a URL to a secret scanner. Nothing here is a real credential.
const FAKE_TOKEN = ["not", "a", "real", "token"].join("-")
const withUserinfo = (user: string, secret: string) => "https://" + [user, secret].join(":") + "@" + "github.com/o/r"

describe("pushErrorText", () => {
	it("keeps the last 2000 characters", () => {
		const text = pushErrorText(`${"a".repeat(3000)}end`, 128)
		expect(text).toHaveLength(2000)
		expect(text.endsWith("end")).toBe(true)
	})
	it("strips a credential from a URL", () => {
		expect(pushErrorText(`fatal: unable to access '${withUserinfo("user", "tok")}/': 403`, 128)).toBe(
			"fatal: unable to access 'https://github.com/o/r/': 403",
		)
		expect(pushErrorText(withUserinfo("x-access-token", FAKE_TOKEN), 128)).not.toContain(FAKE_TOKEN)
	})
	it("strips before cutting, so no tail of a credential is left", () => {
		const text = pushErrorText(withUserinfo("user", "t".repeat(2500)), 128)
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

describe("gitErrorText", () => {
	it("names the command that exited when git wrote nothing", () => {
		expect(gitErrorText("", 128, "fetch")).toBe("git fetch exited with 128")
		expect(gitErrorText("", 1, "merge")).toBe("git merge exited with 1")
	})
	it("strips a credential as a push error does", () => {
		expect(gitErrorText(withUserinfo("x-access-token", FAKE_TOKEN), 128, "fetch")).not.toContain(FAKE_TOKEN)
	})
})

describe("afterPush", () => {
	it("stores the pushed commit, clears the push error and leaves the snapshot pending (Copilot C8)", () => {
		expect(afterPush(4, { commit: "abc" })).toEqual({
			fields: { pushed: { commit: "abc" }, pushError: undefined, persistPending: false, snapshotPending: true, snapshotAttempts: 0 },
			notice: { notice: "pushed", run: 4, commit: "abc" },
		})
	})
	it("a refused push keeps the last pushed commit and still leaves the snapshot pending", () => {
		const after = afterPush(2, { error: "denied" })
		expect(after.fields).not.toHaveProperty("pushed")
		expect(after.fields).toMatchObject({ pushError: "denied", persistPending: false, snapshotPending: true })
		expect(after.notice).toEqual({ notice: "push failed", run: 2, error: "denied" })
	})
})

describe("afterSnapshot", () => {
	it("keeps a new snapshot and clears the retry and stale marks", () => {
		expect(afterSnapshot(4, { id: "s1", size: 10 }, 1)).toEqual({
			fields: { snapshot: "s1", snapshotPending: false, snapshotAttempts: undefined, snapshotStale: undefined },
			notice: { notice: "snapshot saved", run: 4, bytes: 10 },
		})
	})
	it("a failed snapshot drops the stored one, which is behind the pushed branch, and says why", () => {
		expect(afterSnapshot(3, { error: "not supported" }, 1)).toEqual({
			fields: { snapshot: undefined, snapshotPending: false, snapshotAttempts: undefined, snapshotStale: undefined },
			notice: { notice: "snapshot failed", run: 3, error: "not supported" },
		})
	})
	it("a timed-out snapshot stays pending until its third attempt (Copilot C8)", () => {
		expect(MAX_SNAPSHOT_ATTEMPTS).toBe(3)
		for (const attempt of [1, 2]) {
			expect(afterSnapshot(5, "timeout", attempt)).toEqual({
				fields: { snapshotPending: true },
				notice: { notice: "snapshot timed out", run: 5, attempt },
			})
		}
		expect(afterSnapshot(5, "timeout", 3)).toEqual({
			fields: { snapshot: undefined, snapshotPending: false, snapshotAttempts: undefined, snapshotStale: undefined },
			notice: { notice: "snapshot failed", run: 5, error: "The snapshot timed out 3 times" },
		})
	})
})

describe("abandonSnapshot", () => {
	it("drops a pending snapshot's stored predecessor, which is behind the pushed branch", () => {
		expect(abandonSnapshot(6, "why")).toEqual({
			fields: { snapshot: undefined, snapshotPending: false, snapshotAttempts: undefined, snapshotStale: undefined },
			notice: { notice: "snapshot failed", run: 6, error: "why" },
		})
	})
})

describe("afterAbandon", () => {
	it("clears the pending flag, records why nothing was pushed, and keeps the snapshot marked stale (Copilot C5)", () => {
		expect(afterAbandon(3)).toEqual({
			persistPending: false,
			pushError: abandonedPushError,
			snapshotStale: true,
			notice: { notice: "push failed", run: 3, error: abandonedPushError },
		})
	})
})

describe("within", () => {
	it("answers the work's value when it ends in time", async () => {
		expect(await within(Promise.resolve("done"), 50)).toBe("done")
	})
	it("answers timeout when the work is slower, without waiting for it", async () => {
		const slow = new Promise((resolve) => setTimeout(() => resolve("late"), 200))
		const started = Date.now()
		expect(await within(slow, 10)).toBe("timeout")
		expect(Date.now() - started).toBeLessThan(150)
	})
})

describe("startFromImage (Copilot C9)", () => {
	const bytes = (text: string) => new TextEncoder().encode(text)
	// A container whose first `failures` execs fail as on an instance still booting.
	const booting = (failures: number) => {
		const seen = { starts: 0, execs: 0, destroyed: false }
		const container = {
			images: { agent: "agent-image" },
			get running() {
				return seen.starts > 0 && !seen.destroyed
			},
			start: () => {
				seen.starts += 1
			},
			destroy: async () => {
				seen.destroyed = true
			},
			exec: async () => {
				seen.execs += 1
				if (seen.execs <= failures) throw new Error("container is not running")
				return { output: async () => ({ exitCode: 0, stdout: bytes(""), stderr: bytes("") }) }
			},
		} as unknown as Container
		return { container, seen }
	}

	it("returns once an exec on the new instance answers", async () => {
		const { container, seen } = booting(3)
		await startFromImage(container, { attempts: 10, delayMs: 1 })
		expect(seen).toEqual({ starts: 1, execs: 4, destroyed: false })
	})

	it("gives up after its attempts, destroys the instance and says why", async () => {
		const { container, seen } = booting(100)
		await expect(startFromImage(container, { attempts: 5, delayMs: 1 })).rejects.toThrow("The new instance did not answer after 5 attempts: container is not running")
		expect(seen).toEqual({ starts: 1, execs: 5, destroyed: true })
	})
})

// PLZG-311: a snapshot holds a whole root filesystem. One from an image with
// another layout (before the agent user: no mark at all) must not be restored.
describe("startFromSnapshot", () => {
	const bytes = (text: string) => new TextEncoder().encode(text)
	// A container restored from a snapshot whose layout mark reads `mark`.
	const restored = (mark: string | undefined) => {
		const seen = { started: [] as unknown[], destroyed: false, commands: [] as string[][] }
		const container = {
			get running() {
				return seen.started.length > 0 && !seen.destroyed
			},
			start: (options: unknown) => {
				seen.started.push(options)
			},
			destroy: async () => {
				seen.destroyed = true
			},
			exec: async (command: string[]) => {
				seen.commands.push(command)
				const readsMark = command.includes(layoutPath)
				const exitCode = readsMark && mark === undefined ? 1 : 0
				return { output: async () => ({ exitCode, stdout: bytes(readsMark ? `${mark}\n` : ".git\n"), stderr: bytes(readsMark ? "No such file" : "") }) }
			},
		} as unknown as Container
		return { container, seen }
	}

	it("keeps an instance whose layout mark is this image's and that holds the clone", async () => {
		const { container, seen } = restored(imageLayout)
		expect(await startFromSnapshot(container, "snap-1")).toBeUndefined()
		expect(seen.destroyed).toBe(false)
		expect(seen.started).toEqual([{ containerSnapshot: { id: "snap-1" }, instance: "standard-1", enableInternet: false }])
	})

	it.each([undefined, "1", ""])("destroys an instance whose layout mark is %j and says why", async (mark) => {
		const { container, seen } = restored(mark)
		expect(await startFromSnapshot(container, "snap-1")).toMatch(/layout/)
		expect(seen.destroyed).toBe(true)
		expect(seen.commands.some((command) => command.includes("git"))).toBe(false)
	})
})
