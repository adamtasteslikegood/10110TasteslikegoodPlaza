import { Files, SandboxFileError } from "@cloudflare/sandbox"
import {
	AGENT_LEFT,
	agentUser,
	asAgent,
	capDiff,
	capOutput,
	type CommandResult,
	chunkScript,
	diffScript,
	endUserScript,
	eventsPath,
	execOutput,
	execTimeout,
	exitCodePath,
	longLineScript,
	NO_AGENT_USER,
	outputBytesScript,
	outputDoneScript,
	parseTask,
	pidPath,
	readOptionalText,
	repositoryDirectory,
	resetTaskCommand,
	run,
	signalScript,
	TASK_FILE_REFUSED,
	stderrPath,
	tail,
	taskAliveScript,
	taskCommand,
	taskDirectory,
	trustEnv,
	type Task,
} from "./container"
import type { OutboundProps } from "./outbound"
import { clone, gitEnv, push, snapshot, startFromImage, startFromSnapshot, type Pushed, type Saved } from "./persist"

export type { Task } from "./container"
export type Signal = "TERM" | "KILL"

// The container answered, and its answer shows a task file is not what the
// runner wrote: a read failed with one of the file-level errors in
// wrongFileCodes, or a probe script exited TASK_FILE_REFUSED. Every other
// failure of a probe (an exec timeout or reject, a transport error, a container
// that is stopping, any other exit code or error code) is an ordinary Error,
// and the Workspace treats it as transient (R1, G2).
export class TaskFileError extends Error {
	override name = "TaskFileError"
}

// Everything the Workspace object asks of its container, said as intent. The
// object keeps the order of these calls and the record; ContainerHost turns each
// into execs and file reads. Tests drive a real Workspace with a fake one.
export interface Host {
	readonly running: boolean
	// Resolves once an exec on the new instance answers; throws (instance destroyed) if none does.
	startFromImage(): Promise<void>
	startFromSnapshot(id: string): Promise<string | undefined>
	destroy(): Promise<void>
	setPolicy(props: OutboundProps): Promise<void>
	setInactivityTimeout(ms: number): Promise<void>
	clone(repo: string, branch: string): Promise<string | undefined>
	push(branch: string): Promise<Pushed>
	snapshot(): Promise<Saved>
	diff(): Promise<{ ok: boolean; text: string }>
	// Removes and recreates the task directory, root's alone.
	resetTask(): Promise<void>
	// Starts the detached task: argv runs as the agent user, under a leader that
	// is root's. Can throw after the task has started.
	startTask(argv: string[], env: Record<string, string>): Promise<void>
	// The task the pid file names, if it has been written; "invalid" when the file
	// exists but names no usable group.
	readTask(): Promise<Task | "invalid" | undefined>
	// Whether a live (not zombie) process of the task's group runs in this instance.
	taskAlive(task: Task): Promise<boolean>
	signalTask(task: Task, signal: Signal): Promise<void>
	// KILLs every process of the agent user, in a task's group or not; true once
	// none is left, false when one is or the image has no such user. Throws when
	// the sweep itself could not run, which says nothing about them. It ends a
	// running task's agent too, and the leader then records 137: only for an
	// instance with no run running.
	endAgentProcesses(): Promise<boolean>
	exitCode(): Promise<number | undefined>
	// Up to max bytes of stdout.log from byte offset (0-based).
	readOutput(offset: number, max: number): Promise<Uint8Array>
	// The length of the line at offset, newline included, and whether it has ended.
	lineLength(offset: number): Promise<{ bytes: number; ended: boolean }>
	// The size of stdout.log in bytes, 0 before it exists.
	outputBytes(): Promise<number>
	// Whether the task's stdout and stderr copiers have ended, so the logs are complete.
	outputDone(): Promise<boolean>
	stderrTail(): Promise<string>
	// Test-only: runs argv in the clone with the git trust env, each stream capped.
	// As the agent user, or as root when asked.
	exec(argv: string[], root?: boolean): Promise<CommandResult>
}

export class ContainerHost implements Host {
	constructor(
		private readonly container: Container | undefined,
		private readonly outbound: (props: OutboundProps) => Fetcher,
	) {}

	get running(): boolean {
		return this.container?.running === true
	}

	private get c(): Container {
		if (!this.container) {
			throw new Error("No container is configured")
		}

		return this.container
	}

	private get files(): Files {
		return new Files(this.c)
	}

	startFromImage(): Promise<void> {
		return startFromImage(this.c)
	}

	startFromSnapshot(id: string): Promise<string | undefined> {
		return startFromSnapshot(this.c, id)
	}

	async destroy(): Promise<void> {
		await this.c.destroy()
	}

	// Registering again replaces the handler, so this also changes the policy.
	async setPolicy(props: OutboundProps): Promise<void> {
		const outbound = this.outbound(props)
		await this.c.interceptAllOutboundHttp(outbound)
		await this.c.interceptOutboundHttps("*", outbound)
	}

	setInactivityTimeout(ms: number): Promise<void> {
		return this.c.setInactivityTimeout(ms)
	}

	clone(repo: string, branch: string): Promise<string | undefined> {
		return clone(this.c, repo, branch)
	}

	push(branch: string): Promise<Pushed> {
		return push(this.c, branch)
	}

	snapshot(): Promise<Saved> {
		return snapshot(this.c)
	}

	async diff(): Promise<{ ok: boolean; text: string }> {
		const diff = await execOutput(this.c, asAgent(["/bin/sh", "-c", diffScript, "diff"]), { cwd: repositoryDirectory, env: gitEnv }, execTimeout.short)
		return diff.exitCode === 0 ? { ok: true, text: capDiff(new Uint8Array(diff.stdout)) } : { ok: false, text: tail(new TextDecoder().decode(diff.stderr)) }
	}

	async resetTask(): Promise<void> {
		const reset = await run(this.c, resetTaskCommand, "/", {})

		if (reset.exitCode !== 0) {
			throw new Error(`Could not make ${taskDirectory}: ${tail(reset.stderr, 500)}`)
		}
	}

	async startTask(argv: string[], env: Record<string, string>): Promise<void> {
		const started = await run(this.c, taskCommand(argv), repositoryDirectory, env)

		if (started.exitCode !== 0) {
			throw new Error(`The task launcher exited with ${started.exitCode}: ${tail(started.stderr, 500)}`)
		}
	}

	async readTask(): Promise<Task | "invalid" | undefined> {
		const text = await readTaskFile(this.files, pidPath)
		return text === undefined ? undefined : (parseTask(text) ?? "invalid")
	}

	async taskAlive(task: Task): Promise<boolean> {
		const probe = await run(this.c, ["/bin/sh", "-c", taskAliveScript, "probe", String(task.pid), task.boot], "/", {})
		return probe.exitCode === 0
	}

	async signalTask(task: Task, signal: Signal): Promise<void> {
		// Group 0 is the caller's own and -1 is every process (Copilot C2).
		if (task.pid <= 1) return

		// Fails when the group is gone already, which is fine.
		await run(this.c, ["/bin/sh", "-c", signalScript, "signal", String(task.pid), task.boot, signal], "/", {})
	}

	async endAgentProcesses(): Promise<boolean> {
		const swept = await run(this.c, ["/bin/sh", "-c", endUserScript, "sweep", agentUser], "/", {})
		if (swept.exitCode === 0) return true
		if (swept.exitCode === AGENT_LEFT || swept.exitCode === NO_AGENT_USER) return false
		throw new Error(`Could not end the agent's processes: the sweep exited ${swept.exitCode}: ${tail(swept.stderr, 500)}`)
	}

	async exitCode(): Promise<number | undefined> {
		return parseExitCode(await readTaskFile(this.files, exitCodePath))
	}

	async readOutput(offset: number, max: number): Promise<Uint8Array> {
		const command = ["/bin/sh", "-c", chunkScript, "ingest", String(offset + 1), eventsPath, String(max)]
		const output = await execOutput(this.c, command, { cwd: "/", env: {} }, execTimeout.short)

		if (output.exitCode !== 0) {
			throw probeFailure(`read ${eventsPath}`, output.exitCode, new TextDecoder().decode(output.stderr))
		}

		return new Uint8Array(output.stdout)
	}

	async lineLength(offset: number): Promise<{ bytes: number; ended: boolean }> {
		const probe = await run(this.c, ["/bin/sh", "-c", longLineScript, "line", String(offset + 1), eventsPath], "/", {})
		const [bytes, ended] = probe.stdout.trim().split(/\s+/).map(Number)
		return { bytes, ended: ended === 1 }
	}

	async outputBytes(): Promise<number> {
		const probe = await run(this.c, ["/bin/sh", "-c", outputBytesScript, "size", eventsPath], "/", {})
		const bytes = Number(probe.stdout.trim())

		if (probe.exitCode !== 0) {
			throw probeFailure(`read the size of ${eventsPath}`, probe.exitCode, probe.stderr)
		}

		// A script that exited 0 without a size: the exec, not the file, went wrong.
		if (!Number.isFinite(bytes)) {
			throw new Error(`Could not read the size of ${eventsPath}: the probe printed no size`)
		}

		return bytes
	}

	async outputDone(): Promise<boolean> {
		return (await run(this.c, ["/bin/sh", "-c", outputDoneScript, "done", taskDirectory], "/", {})).exitCode === 0
	}

	async stderrTail(): Promise<string> {
		return (await run(this.c, ["tail", "-c", "2000", stderrPath], "/", {})).stdout
	}

	async exec(argv: string[], root = false): Promise<CommandResult> {
		// No credential: the trust env only, and git never waits at a prompt.
		const env = { ...(root ? { ...trustEnv, HOME: "/root" } : gitEnv), GIT_TERMINAL_PROMPT: "0" }
		const output = await execOutput(this.c, root ? argv : asAgent(argv), { cwd: repositoryDirectory, env }, execTimeout.short)
		return { exitCode: output.exitCode, stdout: capOutput(output.stdout), stderr: capOutput(output.stderr) }
	}
}

// A probe script's non-zero exit: TaskFileError only when the script itself
// refused the file (G2). 137 and 143 (the probe KILLed or TERMed while the
// container stops), 126 and 127 (no shell), 255 and the rest are plain Errors.
export function probeFailure(what: string, exitCode: number, stderr: string): Error {
	const message = `Could not ${what}: the probe exited ${exitCode}: ${tail(stderr, 500)}`
	return exitCode === TASK_FILE_REFUSED ? new TaskFileError(message) : new Error(message)
}

// The exit-code file as the runner writes it: "$?" and a newline, put in place
// with a temp file and a rename, so it is never seen empty or half written (G6).
// undefined while it does not exist. Anything else, empty included, is not what
// the runner wrote: a TaskFileError, so no NaN or prefix ("0abc") reaches judgeRun.
export function parseExitCode(text: string | undefined): number | undefined {
	if (text === undefined) return undefined
	const digits = text.endsWith("\n") ? text.slice(0, -1) : text

	if (!/^(0|[1-9]\d{0,2})$/.test(digits) || Number(digits) > 255) {
		throw new TaskFileError(`${exitCodePath} is not an exit status: ${JSON.stringify(text.slice(0, 40))}`)
	}

	return Number(digits)
}

// The SandboxFileError codes (native Linux errnos) that mean the path exists
// but is the wrong kind of thing or can't be read, so the agent changed it (G2):
// EISDIR (a directory), ENOTDIR (a path part is not a directory), ELOOP (a
// symlink loop), ENXIO (a socket or a FIFO with no writer), EACCES and EPERM (no
// permission). ENOENT is "not written yet". Every other code, UNKNOWN included,
// may be the container's own trouble (EIO, ENOSPC, EMFILE, ENOMEM), so it is plain.
const wrongFileCodes: ReadonlySet<string> = new Set(["EISDIR", "ENOTDIR", "ELOOP", "ENXIO", "EACCES", "EPERM"])

// What a failed task file read is: a TaskFileError for a listed file-level code,
// else the error as it was.
export function readFailure(path: string, error: unknown): unknown {
	if (SandboxFileError.is(error) && wrongFileCodes.has(error.code)) {
		return new TaskFileError(`Could not read ${path}: ${error.code} ${error.message}`)
	}

	return error
}

// A task file read: undefined while it does not exist (R1, G2).
async function readTaskFile(files: Files, path: string): Promise<string | undefined> {
	try {
		return await readOptionalText(files, path)
	} catch (error) {
		throw readFailure(path, error)
	}
}
