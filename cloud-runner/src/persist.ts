import { Files } from "@cloudflare/sandbox"
import { execTimeout, repositoryDirectory, run, tail, trustEnv } from "./container"

// What outlives a container instance: the pushed branch and the snapshot. The
// git commands and the snapshot call live here; what they mean for the record
// is decided in runstate.ts.
export const gitEnv = { ...trustEnv, HOME: "/root" }

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

// What a run's push and snapshot leave in the record, and the runner notices
// for them. A refused push keeps the last pushed commit; the run's own state is
// never touched. A failed snapshot drops the stored one: it predates this run,
// and the next instance must not restore files behind the pushed branch.
export function afterPersist(run: number, pushed: Pushed, saved: Saved) {
	const push = "commit" in pushed
		? { fields: { pushed: { commit: pushed.commit }, pushError: undefined }, notice: { notice: "pushed", run, commit: pushed.commit } }
		: { fields: { pushError: pushed.error }, notice: { notice: "push failed", run, error: pushed.error } }
	const snap = "id" in saved ? { notice: "snapshot saved", run, bytes: saved.size } : { notice: "snapshot failed", run, error: saved.error }

	return { ...push.fields, snapshot: "id" in saved ? saved.id : undefined, notices: [push.notice, snap] }
}

// A push and snapshot that were due when the container was already gone. The
// stored snapshot predates the run, so it is dropped: the next instance clones
// the pushed branch and reports the run's files lost.
export const abandonedPushError = "The container stopped before the branch was pushed"

export function afterAbandon(run: number) {
	return {
		persistPending: false,
		pushError: abandonedPushError,
		snapshot: undefined,
		notice: { notice: "push failed", run, error: abandonedPushError },
	}
}

// undefined on success, else the end of git's stderr. A failed clone leaves no directory.
export async function clone(container: Container, repo: string, branch: string): Promise<string | undefined> {
	const files = new Files(container)
	await files.remove(repositoryDirectory, { recursive: true, force: true })
	let failed: string | undefined

	try {
		const cloned = await run(container, ["git", "clone", "--branch", branch, "--", repo, repositoryDirectory], "/workspace", gitEnv, execTimeout.clone)
		if (cloned.exitCode !== 0) failed = tail(cloned.stderr) || `git clone exited with ${cloned.exitCode}`
	} catch (error) {
		failed = messageOf(error)
	}

	if (failed !== undefined) {
		await files.remove(repositoryDirectory, { recursive: true, force: true })
		return failed
	}

	for (const [key, value] of [
		["user.name", "Plaza cloud agent"],
		["user.email", "plaza-cloud-agent@users.noreply.github.com"],
	]) {
		await run(container, ["git", "config", key, value], repositoryDirectory, gitEnv)
	}

	return undefined
}

// Pushes the clone's HEAD to the branch. Never throws.
export async function push(container: Container, branch: string): Promise<Pushed> {
	try {
		const pushed = await run(container, ["git", "push", "origin", `HEAD:refs/heads/${branch}`], repositoryDirectory, pushEnv, execTimeout.push)

		if (pushed.exitCode !== 0) {
			return { error: pushErrorText(pushed.stderr, pushed.exitCode) }
		}

		const head = await run(container, ["git", "rev-parse", "HEAD"], repositoryDirectory, gitEnv)
		return head.exitCode === 0 ? { commit: head.stdout.trim() } : { error: tail(head.stderr) || "git rev-parse HEAD failed" }
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

export function startFromImage(container: Container): void {
	container.start({ image: container.images.agent, instance, enableInternet: false })
}

// undefined once an instance runs from the snapshot and holds the clone, else
// why not; a failed instance is destroyed. start() returns before the instance
// is up, so a snapshot that cannot be restored shows in the first exec.
export async function startFromSnapshot(container: Container, id: string): Promise<string | undefined> {
	try {
		container.start({ containerSnapshot: { id }, instance, enableInternet: false })
		// The first exec on a new instance waits for it to boot.
		const probe = await run(container, ["git", "rev-parse", "--git-dir"], repositoryDirectory, gitEnv, execTimeout.restore)

		if (probe.exitCode === 0) {
			return undefined
		}

		throw new Error(`The restored instance has no clone: ${tail(probe.stderr, 200)}`)
	} catch (error) {
		if (container.running) await container.destroy()
		return messageOf(error)
	}
}

export function messageOf(error: unknown): string {
	return tail(error instanceof Error ? error.message : String(error), 500)
}
