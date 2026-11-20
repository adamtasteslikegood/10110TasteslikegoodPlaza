import { agentHome, asAgent, emptyCloneCommand, execTimeout, imageLayout, layoutPath, repositoryDirectory, run, tail, trustEnv } from "./container"

// What outlives a container instance: the pushed branch and the snapshot. The
// git commands and the snapshot call live here; what they mean for the record
// is decided in runstate.ts. Every git command runs as the agent (asAgent), in
// the agent's home: the clone is the agent's, and so is what git runs from it.
export const gitEnv = { ...trustEnv, HOME: agentHome }

// A push that is refused must fail, never wait at a prompt for a user name.
const pushEnv = { ...gitEnv, GIT_TERMINAL_PROMPT: "0" }

// The end of git's stderr for the status. The push URL is the plain
// repository URL and the token is added outside the container, so none should
// appear; anything between "://" and "@" is cut anyway, before truncating, so
// no part of one is ever stored.
export function pushErrorText(stderr: string, exitCode: number): string {
	return tail(stderr.replace(/:\/\/[^\s@]*@/g, "://")) || `git push exited with ${exitCode}`
}

export type Pushed = { commit: string } | { error: string }
export type Saved = { id: string; size: number } | { error: string }

// What a run's push leaves in the record, and its runner notice. A refused push
// keeps the last pushed commit; the run's own state is never touched. The push
// is stored before the snapshot is taken, so a snapshot that times out does not
// push again (Copilot C8).
export function afterPush(run: number, pushed: Pushed) {
	const done = { persistPending: false, snapshotPending: true, snapshotAttempts: 0 }
	return "commit" in pushed
		? { fields: { pushed: { commit: pushed.commit }, pushError: undefined, ...done }, notice: { notice: "pushed", run, commit: pushed.commit } }
		: { fields: { pushError: pushed.error, ...done }, notice: { notice: "push failed", run, error: pushed.error } }
}

// A snapshot is tried at most this many times when it times out.
export const MAX_SNAPSHOT_ATTEMPTS = 3

const snapshotSettled = { snapshotPending: false, snapshotAttempts: undefined, snapshotStale: undefined }

// A snapshot not taken (failed, given up, or no longer possible) drops the
// stored one: it predates this run, and the next instance must not restore
// files behind the pushed branch.
export function abandonSnapshot(run: number, error: string) {
	return { fields: { snapshot: undefined, ...snapshotSettled }, notice: { notice: "snapshot failed", run, error } }
}

// What a snapshot attempt (the attempt-th) leaves in the record.
export function afterSnapshot(run: number, saved: Saved | "timeout", attempt: number) {
	if (saved === "timeout") {
		return attempt < MAX_SNAPSHOT_ATTEMPTS
			? { fields: { snapshotPending: true }, notice: { notice: "snapshot timed out", run, attempt } }
			: abandonSnapshot(run, `The snapshot timed out ${MAX_SNAPSHOT_ATTEMPTS} times`)
	}

	return "id" in saved
		? { fields: { snapshot: saved.id, ...snapshotSettled }, notice: { notice: "snapshot saved", run, bytes: saved.size } }
		: abandonSnapshot(run, saved.error)
}

// A push and snapshot that were due when the container was already gone. The
// stored snapshot predates the run but nothing newer was pushed, so it still
// holds the best files there are: it is kept, marked stale, and the next
// restore says the run's work was lost (Copilot C5).
export const abandonedPushError = "The container stopped before the branch was pushed"

export function afterAbandon(run: number) {
	return {
		persistPending: false,
		pushError: abandonedPushError,
		snapshotStale: true,
		notice: { notice: "push failed", run, error: abandonedPushError },
	}
}

// The work's value, or "timeout" once ms have passed. The work is not
// cancelled; its late value is ignored.
export async function within<T>(work: Promise<T>, ms: number): Promise<T | "timeout"> {
	let timer: ReturnType<typeof setTimeout> | null = null
	const late = new Promise<"timeout">((resolve) => {
		timer = setTimeout(() => resolve("timeout"), ms)
	})

	try {
		return await Promise.race([work, late])
	} finally {
		if (timer !== null) clearTimeout(timer)
	}
}

// undefined on success, else the end of git's stderr. Root makes the empty
// directory, the agent's, and git clones into it as the agent. A failed clone
// leaves no directory.
export async function clone(container: Container, repo: string, branch: string): Promise<string | undefined> {
	let failed: string | undefined

	try {
		const emptied = await run(container, emptyCloneCommand, "/", {})
		if (emptied.exitCode !== 0) throw new Error(`Could not make ${repositoryDirectory}: ${tail(emptied.stderr, 500)}`)
		const cloned = await run(container, asAgent(["git", "clone", "--branch", branch, "--", repo, repositoryDirectory]), "/workspace", gitEnv, execTimeout.clone)
		if (cloned.exitCode !== 0) failed = tail(cloned.stderr) || `git clone exited with ${cloned.exitCode}`
	} catch (error) {
		failed = messageOf(error)
	}

	if (failed !== undefined) {
		await run(container, ["rm", "-rf", "--", repositoryDirectory], "/", {})
		return failed
	}

	for (const [key, value] of [
		["user.name", "Plaza cloud agent"],
		["user.email", "plaza-cloud-agent@users.noreply.github.com"],
	]) {
		await run(container, asAgent(["git", "config", key, value]), repositoryDirectory, gitEnv)
	}

	return undefined
}

// Pushes the clone's HEAD to the branch. Never throws.
export async function push(container: Container, branch: string): Promise<Pushed> {
	try {
		const pushed = await run(container, asAgent(["git", "push", "origin", `HEAD:refs/heads/${branch}`]), repositoryDirectory, pushEnv, execTimeout.push)

		if (pushed.exitCode !== 0) {
			return { error: pushErrorText(pushed.stderr, pushed.exitCode) }
		}

		const head = await run(container, asAgent(["git", "rev-parse", "HEAD"]), repositoryDirectory, gitEnv)
		return head.exitCode === 0 ? { commit: head.stdout.trim() } : { error: tail(head.stderr) || "git rev-parse HEAD failed" }
	} catch (error) {
		return { error: pushErrorText(messageOf(error), -1) }
	}
}

export type Synced = "current" | "fast-forwarded" | { diverged: true } | { error: string }

// Moves the clone to the branch as it is on the remote, when that is a
// fast-forward, so a run starts from what is on GitHub. Git talks to the remote
// through the Worker's proxy, as in a push: no credential is passed here. The
// only way HEAD moves is `merge --ff-only`; an uncommitted file is never
// discarded. Commits the remote lacks (a push that failed) stay for the closing
// push. Never throws.
export async function syncBranch(container: Container, branch: string): Promise<Synced> {
	const git = (args: string[], timeoutMs = execTimeout.short, env = gitEnv) => run(container, asAgent(["git", ...args]), repositoryDirectory, env, timeoutMs)

	try {
		const fetched = await git(["fetch", "origin", branch], execTimeout.push, pushEnv)
		if (fetched.exitCode !== 0) return { error: pushErrorText(fetched.stderr, fetched.exitCode) }

		const [head, theirs] = await Promise.all([git(["rev-parse", "HEAD"]), git(["rev-parse", "FETCH_HEAD"])])
		if (head.exitCode !== 0 || theirs.exitCode !== 0) return { error: tail(head.stderr || theirs.stderr) || "git rev-parse failed" }
		if (head.stdout.trim() === theirs.stdout.trim()) return "current"

		// Exit 0: an ancestor; 1: not one; anything else is git failing.
		const behind = await git(["merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD"])
		if (behind.exitCode > 1) return { error: tail(behind.stderr) || `git merge-base exited with ${behind.exitCode}` }

		if (behind.exitCode === 0) {
			const merged = await git(["merge", "--ff-only", "FETCH_HEAD"])
			return merged.exitCode === 0 ? "fast-forwarded" : { diverged: true }
		}

		const ahead = await git(["merge-base", "--is-ancestor", "FETCH_HEAD", "HEAD"])
		if (ahead.exitCode > 1) return { error: tail(ahead.stderr) || `git merge-base exited with ${ahead.exitCode}` }
		return ahead.exitCode === 0 ? "current" : { diverged: true }
	} catch (error) {
		return { error: pushErrorText(messageOf(error), -1) }
	}
}

// Saves the instance's root filesystem. Never throws: snapshots are in public
// beta and may be missing under wrangler dev.
export async function snapshot(container: Container): Promise<Saved> {
	try {
		const saved = await container.snapshotContainer({ name: "workspace" })
		return { id: saved.id, size: saved.size }
	} catch (error) {
		return { error: messageOf(error) }
	}
}

const instance = "standard-1"

// How long a new instance from the image gets to answer its first exec: one
// try a second for up to two minutes.
export const imageReadiness = { attempts: 120, delayMs: 1000 }

// start() returns before the instance is up, and an exec on an instance not
// yet running fails at once, so this probes until one answers. Intercepts are
// registered only after, on an instance that runs (Copilot C9). An instance
// that never answers is destroyed.
export async function startFromImage(container: Container, wait = imageReadiness): Promise<void> {
	container.start({ image: container.images.agent, instance, enableInternet: false })
	let last = "no answer"

	for (let attempt = 1; attempt <= wait.attempts; attempt++) {
		try {
			const probe = await run(container, ["true"], "/", {})
			if (probe.exitCode === 0) return
			last = `true exited with ${probe.exitCode}`
		} catch (error) {
			last = messageOf(error)
		}

		if (attempt < wait.attempts) await new Promise((resolve) => setTimeout(resolve, wait.delayMs))
	}

	if (container.running) await container.destroy()
	throw new Error(`The new instance did not answer after ${wait.attempts} attempts: ${last}`)
}

// Why an instance restored from a snapshot cannot be used, or undefined. Its
// layout mark must be this image's: a snapshot from before the agent user has
// none, a clone that is root's and the conversation in root's home (PLZG-311).
// Then it must hold the clone, as the agent sees it.
export async function restoredProblem(container: Container, timeoutMs = execTimeout.short): Promise<string | undefined> {
	const mark = await run(container, ["cat", "--", layoutPath], "/", {}, timeoutMs)

	if (mark.exitCode !== 0 || mark.stdout.trim() !== imageLayout) {
		const found = mark.exitCode === 0 ? JSON.stringify(mark.stdout.trim().slice(0, 40)) : "none"
		return `The snapshot's image layout is ${found}, not ${JSON.stringify(imageLayout)}: it is from another version of the image`
	}

	const probe = await run(container, asAgent(["git", "rev-parse", "--git-dir"]), repositoryDirectory, gitEnv)
	return probe.exitCode === 0 ? undefined : `The restored instance has no clone: ${tail(probe.stderr, 200)}`
}

// undefined once an instance runs from the snapshot and can be used, else why
// not; a failed instance is destroyed. start() returns before the instance is
// up, so a snapshot that cannot be restored shows in the first exec.
export async function startFromSnapshot(container: Container, id: string): Promise<string | undefined> {
	try {
		container.start({ containerSnapshot: { id }, instance, enableInternet: false })
		// The first exec on a new instance waits for it to boot.
		const problem = await restoredProblem(container, execTimeout.restore)

		if (problem === undefined) {
			return undefined
		}

		throw new Error(problem)
	} catch (error) {
		if (container.running) await container.destroy()
		return messageOf(error)
	}
}

export function messageOf(error: unknown): string {
	return tail(error instanceof Error ? error.message : String(error), 500)
}
