import { Files, SandboxFileError } from "@cloudflare/sandbox"
import {
	capDiff,
	capOutput,
	type CommandResult,
	chunkScript,
	copyScript,
	diffScript,
	eventsPath,
	execOutput,
	execTimeout,
	exitCodePath,
	longLineScript,
	outputBytesScript,
	outputDoneScript,
	parseTask,
	pidPath,
	readOptionalText,
	repositoryDirectory,
	run,
	signalScript,
	stderrPath,
	tail,
	taskAliveScript,
	taskDirectory,
	taskScript,
	type Task,
} from "./container"
import type { OutboundProps } from "./outbound"
import { clone, gitEnv, push, snapshot, startFromImage, startFromSnapshot, type Pushed, type Saved } from "./persist"

export type { Task } from "./container"
export type Signal = "TERM" | "KILL"

// The container answered, and its answer shows a task file is not what the
// runner wrote: a read failed with a file-level error other than not-found, or
// a probe script ran and refused the file. Every other failure of a probe (an
// exec timeout or reject, a transport error, a container that is stopping) is
// an ordinary Error, and the Workspace treats it as transient (R1).
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
	// Removes and recreates the task directory.
	resetTask(): Promise<void>
	// Starts the detached task. Can throw after the task has started.
	startTask(argv: string[], env: Record<string, string>): Promise<void>
	// The task the pid file names, if it has been written; "invalid" when the file
	// exists but names no usable group.
	readTask(): Promise<Task | "invalid" | undefined>
	// Whether a live (not zombie) process of the task's group runs in this instance.
	taskAlive(task: Task): Promise<boolean>
	signalTask(task: Task, signal: Signal): Promise<void>
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
	exec(argv: string[]): Promise<CommandResult>
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
		const diff = await execOutput(this.c, ["/bin/sh", "-c", diffScript, "diff"], { cwd: repositoryDirectory, env: {} }, execTimeout.short)
		return diff.exitCode === 0 ? { ok: true, text: capDiff(new Uint8Array(diff.stdout)) } : { ok: false, text: tail(new TextDecoder().decode(diff.stderr)) }
	}

	async resetTask(): Promise<void> {
		await this.files.remove(taskDirectory, { recursive: true, force: true })
		await this.files.mkdir(taskDirectory, { recursive: true })
	}

	async startTask(argv: string[], env: Record<string, string>): Promise<void> {
		const started = await run(this.c, ["/bin/sh", "-c", taskScript, "agent", taskDirectory, copyScript, ...argv], repositoryDirectory, env)

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

	async exitCode(): Promise<number | undefined> {
		const text = await readTaskFile(this.files, exitCodePath)
		return text === undefined ? undefined : Number.parseInt(text, 10)
	}

	async readOutput(offset: number, max: number): Promise<Uint8Array> {
		const command = ["/bin/sh", "-c", chunkScript, "ingest", String(offset + 1), eventsPath, String(max)]
		const output = await execOutput(this.c, command, { cwd: "/", env: {} }, execTimeout.short)

		// The script ran and refused stdout.log: it is not the file the copier writes.
		if (output.exitCode !== 0) {
			throw new TaskFileError(`Could not read ${eventsPath}: ${tail(new TextDecoder().decode(output.stderr), 500)}`)
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

		// The script ran and refused stdout.log, or printed no size.
		if (probe.exitCode !== 0 || !Number.isFinite(bytes)) {
			throw new TaskFileError(`Could not read the size of ${eventsPath}: ${tail(probe.stderr, 500)}`)
		}

		return bytes
	}

	async outputDone(): Promise<boolean> {
		return (await run(this.c, ["/bin/sh", "-c", outputDoneScript, "done", taskDirectory], "/", {})).exitCode === 0
	}

	async stderrTail(): Promise<string> {
		return (await run(this.c, ["tail", "-c", "2000", stderrPath], "/", {})).stdout
	}

	async exec(argv: string[]): Promise<CommandResult> {
		// No credential: the trust env only, and git never waits at a prompt.
		const output = await execOutput(this.c, argv, { cwd: repositoryDirectory, env: { ...gitEnv, GIT_TERMINAL_PROMPT: "0" } }, execTimeout.short)
		return { exitCode: output.exitCode, stdout: capOutput(output.stdout), stderr: capOutput(output.stderr) }
	}
}

// A task file read: undefined while it does not exist. Any other file-level
// error the container reports (a directory, no permission) is a TaskFileError;
// an exec or transport failure stays an ordinary Error (R1).
async function readTaskFile(files: Files, path: string): Promise<string | undefined> {
	try {
		return await readOptionalText(files, path)
	} catch (error) {
		if (SandboxFileError.is(error)) {
			throw new TaskFileError(`Could not read ${path}: ${error.code} ${error.message}`)
		}

		throw error
	}
}
