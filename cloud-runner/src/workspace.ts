import { Files } from "@cloudflare/sandbox"
import { DurableObject } from "cloudflare:workers"
import { agentArgv, agentEnv, outcome, parseLine } from "./agent"
import {
	chunkScript,
	completeLines,
	diffScript,
	eventsPath,
	exitCodePath,
	leadingType,
	lineEvent,
	longLineScript,
	pidPath,
	readLines,
	readOptionalText,
	repositoryDirectory,
	run,
	runBytes,
	signalScript,
	stderrPath,
	tail,
	taskDirectory,
	taskRunningScript,
	taskScript,
} from "./container"
import { EventLog } from "./events"
import type { OutboundProps } from "./outbound"
import { afterPersist, clone, gitEnv, push, snapshot, startFromImage, startFromSnapshot } from "./persist"
import { admit, afterRestore, conversation, conversationAfter, restorePath, settle, stopOutcome, type Observed } from "./runstate"
import type { Env, Event, RunState, Status } from "./types"

const inactivityTimeout = 15 * 60 * 1000
const runCheckInterval = 60 * 1000
const stopWait = 10 * 1000
const pidWait = 5 * 1000
const chunkBytes = 4 * 1024 * 1024
const recordKey = "workspace"

// Everything the object keeps between requests: one small record, read with one get.
type Record_ = {
	repo?: string
	branch?: string
	allow: string[]
	run: number
	generation: number
	sessionId?: string
	hasConversation: boolean
	resumed?: boolean // the current run resumes sessionId
	state: RunState
	result?: string
	error?: string
	pushed?: { commit: string }
	pushError?: string
	snapshot?: string // id of the snapshot taken after the last run
	restored?: "snapshot" | "branch"
	uncommittedLost?: boolean
	eventsOffset: number // bytes of stdout.log already in the event log
}

const blank = (): Record_ => ({ allow: [], run: 0, generation: 0, hasConversation: false, state: "none", eventsOffset: 0 })

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export class Workspace extends DurableObject<Env> {
	private eventLog: EventLog
	private ready = false // intercepts and idle timeout are set on the running container
	private queue: Promise<unknown> = Promise.resolve()

	constructor(ctx: DurableObjectState, env: Env) {
		super(ctx, env)
		this.eventLog = new EventLog(ctx.storage.sql)

		const container = ctx.container

		if (container?.running) {
			void ctx.blockConcurrencyWhile(() => container.setInactivityTimeout(inactivityTimeout))
		}
	}

	create(repo: string, branch: string, allow: string[]): Promise<{ status: Status; cloneError?: string } | "conflict"> {
		return this.exclusive(async () => {
			const record = await this.refresh()

			if (record.repo !== undefined) {
				return record.repo === repo && record.branch === branch ? { status: statusOf(record) } : "conflict"
			}

			await this.ensureStarted(record)
			await this.intercept({ repoPath: new URL(repo).pathname, allow })
			const cloned = await clone(this.container, repo, branch)

			if (cloned !== undefined) {
				await this.intercept({ repoPath: "", allow: [] })
				return { status: statusOf(record), cloneError: cloned }
			}

			Object.assign(record, { repo, branch, allow, state: "idle", hasConversation: false })
			this.save(record)
			return { status: statusOf(record) }
		})
	}

	status(): Promise<Status> {
		return this.exclusive(async () => statusOf(await this.refresh()))
	}

	startRun(prompt: string, fresh: boolean, maxTurns: number): Promise<{ run: number } | "busy" | "missing"> {
		return this.exclusive(async () => {
			const record = await this.refresh()
			const decision = admit(record.state, record.repo !== undefined)

			if (decision !== "start") {
				return decision
			}

			// Starting a new instance clones again and forgets the conversation.
			await this.ensureStarted(record)
			const { sessionId, resume } = conversation(fresh, record.hasConversation, record.sessionId, crypto.randomUUID())

			await this.files.remove(taskDirectory, { recursive: true, force: true })
			await this.files.mkdir(taskDirectory, { recursive: true })
			await this.container.exec(
				[
					"/bin/sh",
					"-c",
					taskScript,
					"agent",
					taskDirectory,
					...agentArgv({ prompt, model: this.env.MODEL, maxTurns, sessionId, resume }),
				],
				{
					cwd: repositoryDirectory,
					env: { ...gitEnv, ...agentEnv(this.env.AI_GATEWAY_ACCOUNT_ID, this.env.AI_GATEWAY_ID) },
					stdout: "ignore",
					stderr: "ignore",
				},
			)

			record.run += 1
			Object.assign(record, {
				state: "running",
				sessionId,
				resumed: resume,
				hasConversation: conversationAfter("started", resume, false),
				eventsOffset: 0,
				result: undefined,
				error: undefined,
			})
			this.save(record)
			this.note(record, { notice: "run started", run: record.run })
			await this.ctx.storage.setAlarm(Date.now() + runCheckInterval)
			return { run: record.run }
		})
	}

	events(after: number): Promise<{ events: Event[]; next: number } | "missing"> {
		return this.exclusive(async () => {
			const record = await this.refresh()

			if (record.repo === undefined) {
				return "missing"
			}

			if (record.state === "running") {
				await this.ingest(record)
			}

			return this.eventLog.readAfter(after)
		})
	}

	stop(): Promise<Status | "missing" | "still-running"> {
		return this.exclusive(async () => {
			const record = await this.refresh()

			if (record.repo === undefined) {
				return "missing"
			}

			if (record.state !== "running") {
				return statusOf(record)
			}

			// refresh() saw the container running, or the run would be lost.
			// A stop right after the start can come before the task wrote its pid.
			await this.waitFor(pidWait, async () => (await readOptionalText(this.files, pidPath)) !== undefined)

			if (!(await this.signalUntilExit("TERM"))) {
				await this.signalUntilExit("KILL")
			}

			const exitCode = await this.readExitCode()
			const pidPresent = (await readOptionalText(this.files, pidPath)) !== undefined
			const taskAlive = exitCode === undefined && pidPresent && (await this.taskRunning())
			const resultSeen = exitCode !== undefined && (await this.resultLines()).length > 0
			const decision = stopOutcome({ exitCode, pidPresent, taskAlive, resultSeen })

			if (decision === "still-running") {
				return "still-running"
			}

			if (decision === "finish") {
				await this.finish(record, exitCode as number)
				return statusOf(record)
			}

			await this.ingest(record)
			record.state = "stopped"
			record.hasConversation = conversationAfter("stopped", record.resumed === true, false)
			this.save(record)
			this.note(record, { notice: "run stopped", run: record.run })
			await this.finishRun(record)
			return statusOf(record)
		})
	}

	diff(): Promise<{ ok: boolean; text: string } | "missing"> {
		return this.exclusive(async () => {
			const record = await this.refresh()

			if (record.repo === undefined) {
				return "missing"
			}

			await this.ensureStarted(record)
			const diff = await run(this.container, ["/bin/sh", "-c", diffScript], repositoryDirectory, {})
			return diff.exitCode === 0 ? { ok: true, text: diff.stdout } : { ok: false, text: tail(diff.stderr) }
		})
	}

	destroyWorkspace(): Promise<void> {
		return this.exclusive(async () => {
			if (this.ctx.container?.running) {
				await this.ctx.container.destroy()
			}

			this.eventLog.clear()
			await this.ctx.storage.deleteAlarm()
			await this.ctx.storage.deleteAll()
			// deleteAll() drops the events table too.
			this.eventLog = new EventLog(this.ctx.storage.sql)
			this.ready = false
		})
	}

	async alarm(): Promise<void> {
		await this.exclusive(async () => {
			const record = await this.refresh()

			if (record.state !== "running") {
				return
			}

			await this.ingest(record)
			await this.ctx.storage.setAlarm(Date.now() + runCheckInterval)
		})
	}

	// After a run ends or is stopped: push the branch, then snapshot the instance.
	private async finishRun(record: Record_): Promise<void> {
		if (!this.ctx.container?.running || record.branch === undefined) {
			return
		}

		const pushed = await push(this.container, record.branch)
		const { notices, ...fields } = afterPersist(record.run, pushed, await snapshot(this.container))
		Object.assign(record, fields)
		this.save(record)
		for (const notice of notices) this.note(record, notice)
	}

	private get container(): Container {
		const container = this.ctx.container

		if (!container) {
			throw new Error("No container is configured")
		}

		return container
	}

	private get files(): Files {
		return new Files(this.container)
	}

	// One public method or alarm at a time. A clone can outlast
	// blockConcurrencyWhile, so this is a promise chain instead.
	private exclusive<T>(work: () => Promise<T>): Promise<T> {
		const result = this.queue.then(work, work)
		this.queue = result.catch(() => undefined)
		return result
	}

	private load(): Record_ {
		return this.ctx.storage.kv.get<Record_>(recordKey) ?? blank()
	}

	private save(record: Record_): void {
		this.ctx.storage.kv.put(recordKey, record)
	}

	private note(record: Record_, payload: unknown): void {
		this.eventLog.append(record.run, record.generation, "runner", payload)
	}

	// The stored record, with a running run settled against what the container
	// shows. Never starts a container.
	private async refresh(): Promise<Record_> {
		const record = this.load()

		// After this object restarts, a running container needs its intercepts again.
		if (this.ctx.container?.running && !this.ready) {
			await this.setUp(record)
		}

		if (record.state !== "running") {
			return record
		}

		const observed = await this.observe()
		const settled = settle(record.state, observed)

		if (settled === "lost") {
			record.state = "lost"
			record.error = "The container stopped before the run ended"
			record.hasConversation = conversationAfter("lost", record.resumed === true, false)
			this.save(record)
			this.note(record, { notice: "run lost", run: record.run })
		} else if (observed.exitCode !== undefined) {
			await this.finish(record, observed.exitCode)
		}

		return record
	}

	private async observe(): Promise<Observed> {
		if (!this.ctx.container?.running) {
			return { containerRunning: false, pidAlive: false }
		}

		const exitCode = await this.readExitCode()

		if (exitCode !== undefined) {
			return { containerRunning: true, pidAlive: false, exitCode }
		}

		if ((await readOptionalText(this.files, pidPath)) === undefined) {
			// The task writes its process ID right after it starts.
			return { containerRunning: true, pidAlive: true }
		}

		if (await this.taskRunning()) {
			return { containerRunning: true, pidAlive: true }
		}

		// The task can finish after the first read, so read the exit code again.
		return { containerRunning: true, pidAlive: false, exitCode: await this.readExitCode() }
	}

	private async taskRunning(): Promise<boolean> {
		const probe = await run(this.container, ["/bin/sh", "-c", taskRunningScript, "probe", pidPath], "/", {})
		return probe.exitCode === 0
	}

	private async resultLines(): Promise<string[]> {
		const results: string[] = []
		for await (const line of readLines((await this.files.readFile(eventsPath)).body)) {
			if (parseLine(line)?.type === "result") results.push(line)
		}
		return results
	}

	private async readExitCode(): Promise<number | undefined> {
		const text = await readOptionalText(this.files, exitCodePath)
		return text === undefined ? undefined : Number.parseInt(text, 10)
	}

	private async finish(record: Record_, exitCode: number): Promise<void> {
		await this.ingest(record)

		const results = await this.resultLines()
		const stderr = await run(this.container, ["tail", "-c", "2000", stderrPath], "/", {})
		const ended = outcome(results, exitCode, stderr.stdout)

		record.state = ended.state
		record.result = ended.state === "succeeded" ? ended.result : undefined
		record.error = ended.state === "failed" ? ended.error : undefined
		record.hasConversation = conversationAfter("finished", record.resumed === true, results.length > 0)
		this.save(record)
		this.note(record, { notice: "run ended", run: record.run, state: record.state })
		await this.finishRun(record)
	}

	// Adds the complete lines of stdout.log past eventsOffset to the event log.
	private async ingest(record: Record_): Promise<void> {
		if (!this.ctx.container?.running) {
			return
		}

		for (;;) {
			const from = String(record.eventsOffset + 1)
			const chunk = await runBytes(this.container, ["/bin/sh", "-c", chunkScript, "ingest", from, eventsPath, String(chunkBytes)])
			const { lines, consumed } = completeLines(chunk)

			if (consumed === 0) {
				if (chunk.byteLength < chunkBytes) {
					return // nothing new, or a line still being written
				}

				// One line longer than a whole chunk: skip it, keeping its type and size.
				const probe = await run(this.container, ["/bin/sh", "-c", longLineScript, "line", from, eventsPath], "/", {})
				const [bytes, ended] = probe.stdout.trim().split(/\s+/).map(Number)

				if (ended !== 1) {
					return
				}

				const type = leadingType(new TextDecoder().decode(chunk.subarray(0, 256)))
				this.eventLog.append(record.run, record.generation, type, { truncated: true, bytes: bytes - 1 })
				record.eventsOffset += bytes
				this.save(record)
				continue
			}

			// No await from here to save(): the events and the offset are stored together.
			for (const line of lines) {
				const event = lineEvent(line, parseLine)
				if (event) this.eventLog.append(record.run, record.generation, event.type, event.payload)
			}

			record.eventsOffset += consumed
			this.save(record)

			if (chunk.byteLength < chunkBytes) {
				return
			}
		}
	}

	// TERM or KILL to the run's process group, then up to stopWait for its exit code.
	private async signalUntilExit(signal: "TERM" | "KILL"): Promise<boolean> {
		await run(this.container, ["/bin/sh", "-c", signalScript, "signal", pidPath, signal], "/", {})
		return this.waitFor(stopWait, async () => (await this.readExitCode()) !== undefined)
	}

	// Polls every 500 ms for up to ms; true once done() holds.
	private async waitFor(ms: number, done: () => Promise<boolean>): Promise<boolean> {
		for (let waited = 0; ; waited += 500) {
			if (await done()) return true
			if (waited >= ms) return false
			await sleep(500)
		}
	}

	// Makes sure a container runs with this object's intercepts and idle timeout.
	private async ensureStarted(record: Record_): Promise<void> {
		if (this.ctx.container?.running) {
			if (!this.ready) {
				await this.setUp(record)
			}

			return
		}

		await this.startInstance(record)
	}

	// A new instance: from the stored snapshot if it starts, else from the image
	// with a fresh clone of the branch. refresh() has already settled a lost run.
	private async startInstance(record: Record_): Promise<void> {
		record.generation += 1
		this.save(record)
		const snapshotError = record.snapshot === undefined ? undefined : await startFromSnapshot(this.container, record.snapshot)
		const path = restorePath({ hasSnapshot: record.snapshot !== undefined, snapshotStartFailed: snapshotError !== undefined, hasRepo: record.repo !== undefined })

		if (path !== "snapshot") startFromImage(this.container)
		await this.setUp(record)

		if (path === "branch") {
			const cloned = await clone(this.container, record.repo as string, record.branch as string)

			if (cloned !== undefined) {
				// The next request starts another instance and clones again.
				await this.container.destroy()
				this.ready = false
				throw new Error(`Clone failed on a new instance: ${cloned}`)
			}
		}

		const { notice, keepSnapshot, ...fields } = afterRestore(path, { generation: record.generation, hasConversation: record.hasConversation, snapshotError })
		Object.assign(record, fields, { snapshot: keepSnapshot ? record.snapshot : undefined })
		this.save(record)
		if (notice) this.note(record, notice)
	}

	private async setUp(record: Record_): Promise<void> {
		this.ready = false

		try {
			await this.intercept(record.repo === undefined ? { repoPath: "", allow: [] } : { repoPath: new URL(record.repo).pathname, allow: record.allow })
			await this.container.setInactivityTimeout(inactivityTimeout)
		} catch (error) {
			// The next request starts a new container.
			await this.container.destroy()
			throw error
		}

		this.ready = true
	}

	// Registering again replaces the handler, so this also changes the policy.
	private async intercept(props: OutboundProps): Promise<void> {
		const outbound = this.ctx.exports.Outbound({ props })
		await this.container.interceptAllOutboundHttp(outbound)
		await this.container.interceptOutboundHttps("*", outbound)
	}
}

function statusOf(record: Record_): Status {
	return {
		state: record.repo === undefined ? "none" : record.state,
		run: record.run,
		generation: record.generation,
		repo: record.repo,
		branch: record.branch,
		result: record.result,
		error: record.error,
		pushed: record.pushed,
		pushError: record.pushError,
		restored: record.restored,
		uncommittedLost: record.uncommittedLost,
	}
}
