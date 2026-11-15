import { DurableObject } from "cloudflare:workers"
import { agentArgv, agentEnv, outcome, parseLine } from "./agent"
import { completeLines, leadingType, lineEvent } from "./container"
import { EventLog } from "./events"
import { ContainerHost, type Host, type Task } from "./host"
import { afterAbandon, afterPersist, gitEnv, messageOf } from "./persist"
import {
	admit,
	admitCreate,
	afterRestore,
	conversation,
	conversationAfter,
	judgeRun,
	MAX_RUN_ERROR,
	needsAlarm,
	persistAction,
	restorePath,
	stopOutcome,
} from "./runstate"
import type { Env, Event, RunState, Status } from "./types"

const inactivityTimeout = 15 * 60 * 1000
const runCheckInterval = 60 * 1000
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
	startedAt?: number // ms epoch of the current run's start
	task?: Task // the current run's task, once its pid file was read
	persistPending?: boolean // the run ended; push and snapshot are not stored yet
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
	// The container, said as intent. Built on first use; tests set a fake here.
	private sandbox?: Host
	// How long to wait for a pid file and for a signalled task, and how often to look.
	private timing = { pidWait: 5 * 1000, stopWait: 10 * 1000, poll: 500 }

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
			const admitted = admitCreate(record, { repo, branch, allow })

			if (admitted === "conflict") {
				return "conflict"
			}

			if (admitted === "same") {
				return { status: statusOf(record) }
			}

			await this.ensureStarted(record)
			await this.host.setPolicy({ repoPath: new URL(repo).pathname, allow })
			const cloned = await this.host.clone(repo, branch)

			if (cloned !== undefined) {
				await this.host.setPolicy({ repoPath: "", allow: [] })
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

			// A task an earlier start left behind must not share the clone with this one.
			const leftover = (await this.host.readTask()) ?? record.task

			if (leftover) {
				await this.host.signalTask(leftover, "KILL")
			}

			await this.host.resetTask()

			// The run is stored and watched before the task starts, so a start that
			// fails halfway still leaves a record of it.
			record.run += 1
			Object.assign(record, {
				state: "running",
				startedAt: Date.now(),
				task: undefined,
				persistPending: undefined,
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

			try {
				await this.host.startTask(
					agentArgv({ prompt, model: this.env.MODEL, maxTurns, sessionId, resume }),
					{ ...gitEnv, ...agentEnv(this.env.AI_GATEWAY_ACCOUNT_ID, this.env.AI_GATEWAY_ID) },
				)
			} catch (error) {
				// The launcher can fail after the task started; then the run goes on.
				if ((await this.waitForTask(record)) === undefined) {
					Object.assign(record, {
						state: "failed",
						error: `The run did not start: ${messageOf(error)}`,
						hasConversation: conversationAfter("lost", resume, false),
					})
					this.save(record)
					this.note(record, { notice: "run ended", run: record.run, state: record.state })
					throw error
				}
			}

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
			const task = await this.waitForTask(record)

			if (task) {
				await this.host.signalTask(task, "TERM")
				await this.waitFor(this.timing.stopWait, async () => (await this.host.exitCode()) !== undefined)
				// Members of the group that ignore TERM outlive the leader: always KILL.
				await this.host.signalTask(task, "KILL")

				if ((await this.host.exitCode()) === undefined) {
					await this.waitFor(this.timing.stopWait, async () => !(await this.host.taskAlive(task)))
				}
			}

			const exitCode = await this.host.exitCode()
			const taskAlive = exitCode === undefined && task !== undefined && (await this.host.taskAlive(task))
			const resultSeen = exitCode !== undefined && (await this.host.resultLines()).length > 0
			const decision = stopOutcome({ exitCode, pidPresent: task !== undefined, taskAlive, resultSeen })

			if (decision === "still-running") {
				return "still-running"
			}

			if (decision === "finish") {
				await this.finish(record, exitCode as number)
				return statusOf(record)
			}

			await this.ingest(record)
			Object.assign(record, { state: "stopped", hasConversation: conversationAfter("stopped", record.resumed === true, false), persistPending: true })
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
			return this.host.diff()
		})
	}

	destroyWorkspace(): Promise<void> {
		return this.exclusive(async () => {
			if (this.host.running) {
				await this.host.destroy()
			}

			this.eventLog.clear()
			await this.ctx.storage.deleteAlarm()
			await this.ctx.storage.deleteAll()
			// deleteAll() drops the events table too.
			this.eventLog = new EventLog(this.ctx.storage.sql)
			this.ready = false
		})
	}

	// Watches a running run and retries a push and snapshot not yet stored. It
	// re-arms itself whatever happened, while the stored record still needs it.
	async alarm(): Promise<void> {
		await this.exclusive(async () => {
			try {
				const record = await this.refresh()

				if (record.state === "running") {
					await this.ingest(record)
				}
			} catch (error) {
				console.error(`Workspace alarm failed: ${messageOf(error)}`)
			} finally {
				const stored = this.load()

				if (needsAlarm(stored.state, stored.persistPending === true)) {
					await this.ctx.storage.setAlarm(Date.now() + runCheckInterval)
				}
			}
		})
	}

	private get host(): Host {
		this.sandbox ??= new ContainerHost(this.ctx.container, (props) => this.ctx.exports.Outbound({ props }))
		return this.sandbox
	}

	// After a run ends or is stopped: push the branch, then snapshot the instance.
	// The end state was stored with persistPending, so an interruption anywhere
	// here is retried by the next refresh.
	private async finishRun(record: Record_): Promise<void> {
		const action = persistAction({ pending: record.persistPending === true, containerRunning: this.host.running })

		if (action === "none") {
			return
		}

		if (action === "abandon" || record.branch === undefined) {
			const { notice, ...fields } = afterAbandon(record.run)
			Object.assign(record, fields)
			this.save(record)
			this.note(record, notice)
			return
		}

		const pushed = await this.host.push(record.branch)
		const { notices, ...fields } = afterPersist(record.run, pushed, await this.host.snapshot())
		Object.assign(record, fields, { persistPending: false })
		this.save(record)
		for (const notice of notices) this.note(record, notice)
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

	// The stored record, with a running run judged against what the container
	// shows and a pending push and snapshot done. Never starts a container.
	private async refresh(): Promise<Record_> {
		const record = this.load()

		// After this object restarts, a running container needs its intercepts again.
		if (this.host.running && !this.ready) {
			await this.setUp(record)
		}

		if (record.state === "running") {
			await this.check(record)
		}

		if (record.persistPending) {
			await this.finishRun(record)
		}

		return record
	}

	// Ends a stored running run that is no longer running, by the rules in judgeRun.
	private async check(record: Record_): Promise<void> {
		if (record.startedAt === undefined) {
			record.startedAt = Date.now() // a run stored before the field existed
			this.save(record)
		}

		const running = this.host.running
		let exitCode = running ? await this.host.exitCode() : undefined
		const task = running && exitCode === undefined ? await this.knownTask(record) : undefined
		const taskAlive = task !== undefined && (await this.host.taskAlive(task))

		if (task !== undefined && !taskAlive) {
			// The task can finish after the first read, so read the exit code again.
			exitCode = await this.host.exitCode()
		}

		const verdict = judgeRun({ containerRunning: running, exitCode, taskSeen: task !== undefined, taskAlive, elapsedMs: Date.now() - record.startedAt })

		switch (verdict) {
			case "running":
				return
			case "exited":
				return this.finish(record, exitCode as number)
			case "container-gone":
				return this.endLost(record, "The container stopped before the run ended", false)
			case "process-gone":
				return this.endLost(record, "The agent process ended without writing an exit code", true)
			case "never-started":
				return this.endLost(record, "The agent did not write its pid file within 60 seconds", true)
			case "overdue":
				if (task) await this.host.signalTask(task, "KILL")
				await this.ingest(record)
				Object.assign(record, {
					state: "failed",
					error: MAX_RUN_ERROR,
					hasConversation: conversationAfter("stopped", record.resumed === true, false),
					persistPending: true,
				})
				this.save(record)
				this.note(record, { notice: "run ended", run: record.run, state: record.state })
				return this.finishRun(record)
		}
	}

	// A run that ended without an exit code. With the container still up, its
	// output is read and the branch pushed as after any other run.
	private async endLost(record: Record_, error: string, containerRunning: boolean): Promise<void> {
		if (containerRunning) await this.ingest(record)
		Object.assign(record, {
			state: "lost",
			error,
			hasConversation: conversationAfter("lost", record.resumed === true, false),
			persistPending: containerRunning || undefined,
		})
		this.save(record)
		this.note(record, { notice: "run lost", run: record.run, error })
		if (containerRunning) await this.finishRun(record)
	}

	// The current run's task: the pid file, else the one read earlier (the file
	// can be removed during a run). Stored once seen.
	private async knownTask(record: Record_): Promise<Task | undefined> {
		const task = (await this.host.readTask()) ?? record.task

		if (task && (task.pid !== record.task?.pid || task.boot !== record.task.boot)) {
			record.task = task
			this.save(record)
		}

		return task
	}

	// Up to pidWait for the task to write its pid file.
	private async waitForTask(record: Record_): Promise<Task | undefined> {
		let task: Task | undefined
		await this.waitFor(this.timing.pidWait, async () => (task = await this.knownTask(record)) !== undefined)
		return task
	}

	private async finish(record: Record_, exitCode: number): Promise<void> {
		await this.ingest(record)

		const results = await this.host.resultLines()
		const ended = outcome(results, exitCode, await this.host.stderrTail())

		Object.assign(record, {
			state: ended.state,
			result: ended.state === "succeeded" ? ended.result : undefined,
			error: ended.state === "failed" ? ended.error : undefined,
			hasConversation: conversationAfter("finished", record.resumed === true, results.length > 0),
			persistPending: true,
		})
		this.save(record)
		this.note(record, { notice: "run ended", run: record.run, state: record.state })
		await this.finishRun(record)
	}

	// Adds the complete lines of stdout.log past eventsOffset to the event log.
	private async ingest(record: Record_): Promise<void> {
		if (!this.host.running) {
			return
		}

		for (;;) {
			const chunk = await this.host.readOutput(record.eventsOffset, chunkBytes)
			const { lines, consumed } = completeLines(chunk)

			if (consumed === 0) {
				if (chunk.byteLength < chunkBytes) {
					return // nothing new, or a line still being written
				}

				// One line longer than a whole chunk: skip it, keeping its type and size.
				const { bytes, ended } = await this.host.lineLength(record.eventsOffset)

				if (!ended) {
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

	// Polls every timing.poll ms for up to ms; true once done() holds.
	private async waitFor(ms: number, done: () => Promise<boolean>): Promise<boolean> {
		for (let waited = 0; ; waited += this.timing.poll) {
			if (await done()) return true
			if (waited >= ms) return false
			await sleep(this.timing.poll)
		}
	}

	// Makes sure a container runs with this object's intercepts and idle timeout.
	private async ensureStarted(record: Record_): Promise<void> {
		if (this.host.running) {
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
		const snapshotError = record.snapshot === undefined ? undefined : await this.host.startFromSnapshot(record.snapshot)
		const path = restorePath({ hasSnapshot: record.snapshot !== undefined, snapshotStartFailed: snapshotError !== undefined, hasRepo: record.repo !== undefined })

		if (path !== "snapshot") this.host.startFromImage()
		await this.setUp(record)

		if (path === "branch") {
			const cloned = await this.host.clone(record.repo as string, record.branch as string)

			if (cloned !== undefined) {
				// The next request starts another instance and clones again.
				await this.host.destroy()
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
			await this.host.setPolicy(record.repo === undefined ? { repoPath: "", allow: [] } : { repoPath: new URL(record.repo).pathname, allow: record.allow })
			await this.host.setInactivityTimeout(inactivityTimeout)
		} catch (error) {
			// The next request starts a new container.
			await this.host.destroy()
			throw error
		}

		this.ready = true
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
