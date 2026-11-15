import { Files } from "@cloudflare/sandbox"
import { parseLine } from "./agent"
import {
	chunkScript,
	diffScript,
	eventsPath,
	exitCodePath,
	longLineScript,
	parseTask,
	pidPath,
	readLines,
	readOptionalText,
	repositoryDirectory,
	run,
	runBytes,
	signalScript,
	stderrPath,
	tail,
	taskAliveScript,
	taskDirectory,
	taskScript,
	type Task,
} from "./container"
import type { OutboundProps } from "./outbound"
import { clone, push, snapshot, startFromImage, startFromSnapshot, type Pushed, type Saved } from "./persist"

export type { Task } from "./container"
export type Signal = "TERM" | "KILL"

// Everything the Workspace object asks of its container, said as intent. The
// object keeps the order of these calls and the record; ContainerHost turns each
// into execs and file reads. Tests drive a real Workspace with a fake one.
export interface Host {
	readonly running: boolean
	startFromImage(): void
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
	// The task the pid file names, if it has been written.
	readTask(): Promise<Task | undefined>
	// Whether a live (not zombie) process of the task's group runs in this instance.
	taskAlive(task: Task): Promise<boolean>
	signalTask(task: Task, signal: Signal): Promise<void>
	exitCode(): Promise<number | undefined>
	// Up to max bytes of stdout.log from byte offset (0-based).
	readOutput(offset: number, max: number): Promise<Uint8Array>
	// The length of the line at offset, newline included, and whether it has ended.
	lineLength(offset: number): Promise<{ bytes: number; ended: boolean }>
	resultLines(): Promise<string[]>
	stderrTail(): Promise<string>
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

	startFromImage(): void {
		startFromImage(this.c)
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
		const diff = await run(this.c, ["/bin/sh", "-c", diffScript], repositoryDirectory, {})
		return diff.exitCode === 0 ? { ok: true, text: diff.stdout } : { ok: false, text: tail(diff.stderr) }
	}

	async resetTask(): Promise<void> {
		await this.files.remove(taskDirectory, { recursive: true, force: true })
		await this.files.mkdir(taskDirectory, { recursive: true })
	}

	async startTask(argv: string[], env: Record<string, string>): Promise<void> {
		const started = await run(this.c, ["/bin/sh", "-c", taskScript, "agent", taskDirectory, ...argv], repositoryDirectory, env)

		if (started.exitCode !== 0) {
			throw new Error(`The task launcher exited with ${started.exitCode}: ${tail(started.stderr, 500)}`)
		}
	}

	async readTask(): Promise<Task | undefined> {
		const text = await readOptionalText(this.files, pidPath)
		return text === undefined ? undefined : parseTask(text)
	}

	async taskAlive(task: Task): Promise<boolean> {
		const probe = await run(this.c, ["/bin/sh", "-c", taskAliveScript, "probe", String(task.pid), task.boot], "/", {})
		return probe.exitCode === 0
	}

	async signalTask(task: Task, signal: Signal): Promise<void> {
		// Fails when the group is gone already, which is fine.
		await run(this.c, ["/bin/sh", "-c", signalScript, "signal", String(task.pid), task.boot, signal], "/", {})
	}

	async exitCode(): Promise<number | undefined> {
		const text = await readOptionalText(this.files, exitCodePath)
		return text === undefined ? undefined : Number.parseInt(text, 10)
	}

	readOutput(offset: number, max: number): Promise<Uint8Array> {
		return runBytes(this.c, ["/bin/sh", "-c", chunkScript, "ingest", String(offset + 1), eventsPath, String(max)])
	}

	async lineLength(offset: number): Promise<{ bytes: number; ended: boolean }> {
		const probe = await run(this.c, ["/bin/sh", "-c", longLineScript, "line", String(offset + 1), eventsPath], "/", {})
		const [bytes, ended] = probe.stdout.trim().split(/\s+/).map(Number)
		return { bytes, ended: ended === 1 }
	}

	async resultLines(): Promise<string[]> {
		const results: string[] = []
		for await (const line of readLines((await this.files.readFile(eventsPath)).body)) {
			if (parseLine(line)?.type === "result") results.push(line)
		}
		return results
	}

	async stderrTail(): Promise<string> {
		return (await run(this.c, ["tail", "-c", "2000", stderrPath], "/", {})).stdout
	}
}
