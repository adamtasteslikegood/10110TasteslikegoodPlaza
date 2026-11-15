import { DurableObject } from "cloudflare:workers"
import { agentArgv, agentEnv, outcome, parseLine, resultSentinel } from "./agent"
import { completeLines, leadingType, lineEvent } from "./container"
import { EventLog, MAX_PAYLOAD_BYTES } from "./events"
import { ContainerHost, TaskFileError, type Host, type Task } from "./host"
import { abandonSnapshot, afterAbandon, afterPush, afterSnapshot, gitEnv, messageOf, within } from "./persist"
import {
	admit,
	admitCreate,
	afterRestore,
	conversation,
	conversationAfter,
	countsNow,
	judgeRun,
	leftoverAction,
	MAX_OUTPUT_BYTES,
	MAX_RUN_ERROR,
	MAX_RUN_MS,
	needsAlarm,
	OUTPUT_ERROR,
	OVERDUE_ATTEMPT_LIMIT,
	persistAction,
	restorePath,
	RUN_CHECK_INTERVAL_MS,
	stopOutcome,
	TASK_FILE_FAILURE_LIMIT,
	TASK_FILES_ERROR,
} from "./runstate"
import type { CommandResult } from "./container"
import type { Env, Event, RunState, Status } from "./types"

const inactivityTimeout = 15 * 60 * 1000
const runCheckInterval = RUN_CHECK_INTERVAL_MS
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
	persistPending?: boolean // the run ended; its push is not stored yet
	snapshotPending?: boolean // the push is stored; the snapshot after it is not yet (Copilot C8)
	snapshotAttempts?: number // snapshot attempts made for the last run, at most MAX_SNAPSHOT_ATTEMPTS
	snapshotStale?: boolean // the stored snapshot predates a run whose work was lost (Copilot C5)
	replaceInstance?: boolean // the instance may run a process no task id names: destroy it once persisted (Copilot C4)
	resultLine?: string // the current run's last result event, read during ingest (Copilot C10)
	taskFileFailures?: number // checks in a row of the current run that ended in a TaskFileError (R1)
	lastTaskFileFailureAt?: number // ms epoch of the last one counted, at most one per check interval (G3)
	overdueAttempts?: number // checks of the overdue run that failed with a plain error (G1)
	lastOverdueAttemptAt?: number // ms epoch of the last one counted, at most one per check interval (G1)
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
	// How long to wait for a pid file, for a signalled task and for a snapshot,
	// and how often to look.
	private timing = { pidWait: 5 * 1000, stopWait: 10 * 1000, poll: 500, snapshotWait: 3 * 60 * 1000 }

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
			await this.host.setPolicy({ repoPath: new URL(repo).pathname, branch, allow })
			const cloned = await this.host.clone(repo, branch)

			if (cloned !== undefined) {
				await this.host.setPolicy({ repoPath: "", branch: "", allow: [] })
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

			// A snapshot still pending would replace one taken before the last push;
			// the stored one is behind the branch, so a new instance clones instead.
			if (record.snapshotPending) {
				this.settle(record, abandonSnapshot(record.run, "A new run started before the snapshot was saved"))
			}

			// Starting a new instance clones again and forgets the conversation.
			const reused = this.host.running && record.replaceInstance !== true
			await this.ensureStarted(record)

			// The group of a task an earlier start left behind is KILLed, so it does
			// not run alongside this one; a process that left the group survives
			// (README, "Known gaps"). One the pid file cannot name is ended with its
			// instance (Copilot C4).
			if (reused) {
				const leftover = leftoverAction(await this.host.readTask(), record.task)

				if (leftover === "replace") {
					await this.host.destroy()
					this.ready = false
					await this.startInstance(record)
				} else if (leftover !== "none") {
					await this.host.signalTask(leftover.kill, "KILL")
				}
			}

			const { sessionId, resume } = conversation(fresh, record.hasConversation, record.sessionId, crypto.randomUUID())
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
				resultLine: undefined,
				taskFileFailures: undefined,
				lastTaskFileFailureAt: undefined,
				overdueAttempts: undefined,
				lastOverdueAttemptAt: undefined,
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
			let record: Record_

			try {
				record = await this.refresh()
			} catch (error) {
				// A failed push or setup must not keep a run from stopping (F1): the
				// stored record says what is left to do, and a pending push is retried.
				console.error(`Workspace refresh before a stop failed: ${messageOf(error)}`)
				record = this.load()
			}

			if (record.repo === undefined) {
				return "missing"
			}

			if (record.state !== "running") {
				return statusOf(record)
			}

			try {
				return await this.stopRunning(record)
			} catch (error) {
				// Once the run has ended, what threw is the push or snapshot: it is retried.
				if (record.state !== "running") throw error

				// A task file the runner did not write: replacing the instance stops the
				// run (F1). Anything else may be a blip, and the task may still be alive,
				// so the caller is told to try again (R1).
				if (!(error instanceof TaskFileError)) {
					console.error(`Workspace stop failed, the run goes on: ${messageOf(error)}`)
					return "still-running"
				}

				await this.endUntrusted(record, "stopped", TASK_FILES_ERROR)
				return statusOf(record)
			}
		})
	}

	// The signals and the reads of a stop. Every probe here can throw (F1, R1).
	private async stopRunning(record: Record_): Promise<Status | "still-running"> {
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

			await this.waitForOutput()
		}

		const exitCode = await this.host.exitCode()
		const taskAlive = exitCode === undefined && task !== undefined && (await this.host.taskAlive(task))
		await this.ingest(record)
		const resultSeen = exitCode !== undefined && record.resultLine !== undefined
		const decision = stopOutcome({ exitCode, pidPresent: task !== undefined, taskAlive, resultSeen })

		if (decision === "still-running") {
			return "still-running"
		}

		if (decision === "finish") {
			await this.finish(record, exitCode as number)
			return statusOf(record)
		}

		// Nothing names the task, which may still start: end it with its instance,
		// stored with the end state only (G5).
		Object.assign(record, {
			state: "stopped",
			hasConversation: conversationAfter("stopped", record.resumed === true, false),
			persistPending: true,
			...(task === undefined ? { replaceInstance: true } : {}),
		})
		this.save(record)
		this.note(record, { notice: "run stopped", run: record.run })
		await this.finishRun(record)
		return statusOf(record)
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

	// Test-only (ALLOW_TEST_ROUTES): destroys the container and leaves storage
	// alone, as a platform replacement would. The next request judges the run.
	replaceInstance(): Promise<Status | "missing"> {
		return this.exclusive(async () => {
			const record = await this.refresh()

			if (record.repo === undefined) {
				return "missing"
			}

			if (this.host.running) {
				await this.host.destroy()
			}

			this.ready = false
			return statusOf(record)
		})
	}

	// Test-only (ALLOW_TEST_ROUTES): runs one command in the clone, as the agent
	// user or, when asked, as root.
	exec(argv: string[], root = false): Promise<CommandResult | "missing"> {
		return this.exclusive(async () => {
			const record = await this.refresh()

			if (record.repo === undefined) {
				return "missing"
			}

			await this.ensureStarted(record)
			return this.host.exec(argv, root)
		})
	}

	// Watches a running run and retries a push and snapshot not yet stored. It
	// re-arms itself whatever happened, while the stored record still needs it.
	async alarm(): Promise<void> {
		await this.exclusive(async () => {
			try {
				const record = await this.refresh(true)

				if (record.state === "running") {
					await this.ingest(record)
				}
			} catch (error) {
				console.error(`Workspace alarm failed: ${messageOf(error)}`)
			} finally {
				const stored = this.load()

				if (needsAlarm(stored.state, stored.persistPending === true, stored.snapshotPending === true)) {
					await this.ctx.storage.setAlarm(Date.now() + runCheckInterval)
				}
			}
		})
	}

	private get host(): Host {
		this.sandbox ??= new ContainerHost(this.ctx.container, (props) => this.ctx.exports.Outbound({ props }))
		return this.sandbox
	}

	// After a run ends or is stopped: push the branch, then snapshot the instance,
	// then replace an instance that may hold an unnamed process. The end state
	// was stored with persistPending, so an interrupted push is retried by the
	// next refresh. The snapshot is tried right after the push and then only by
	// the alarm: each try is bounded by timing.snapshotWait (Copilot C8).
	private async finishRun(record: Record_, retrySnapshot = false): Promise<void> {
		let trySnapshot = retrySnapshot

		if (record.persistPending) {
			const action = persistAction({ pending: true, containerRunning: this.host.running })

			if (action === "abandon" || record.branch === undefined) {
				const { notice, ...fields } = afterAbandon(record.run)
				this.settle(record, { fields, notice })
			} else {
				this.settle(record, afterPush(record.run, await this.host.push(record.branch)))
				trySnapshot = true
			}
		}

		if (record.snapshotPending && !this.host.running) {
			this.settle(record, abandonSnapshot(record.run, "The container stopped before the snapshot was saved"))
		} else if (record.snapshotPending && trySnapshot) {
			const attempt = (record.snapshotAttempts ?? 0) + 1
			record.snapshotAttempts = attempt
			this.save(record)
			this.settle(record, afterSnapshot(record.run, await within(this.host.snapshot(), this.timing.snapshotWait), attempt))
		}

		// Never under a run that is still running: replaceInstance comes with an end state (G5).
		if (record.replaceInstance && record.state !== "running" && !record.persistPending && !record.snapshotPending) {
			if (this.host.running) {
				await this.host.destroy()
				this.ready = false
			}

			record.replaceInstance = false
			this.save(record)
		}
	}

	private settle(record: Record_, after: { fields: Partial<Record_>; notice: unknown }): void {
		Object.assign(record, after.fields)
		this.save(record)
		this.note(record, after.notice)
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
	private async refresh(retrySnapshot = false): Promise<Record_> {
		const record = this.load()

		// After this object restarts, a running container needs its intercepts again.
		if (this.host.running && !this.ready) {
			try {
				await this.setUp(record)
			} catch (error) {
				// A running run keeps its container and the next call retries (G4),
				// until the 60-minute cap: then the run ends lost, its container
				// destroyed, as when the container is gone.
				if (record.state !== "running" || !this.overdue(record) || !this.overdueAttemptFailed(record, error)) throw error
				await this.host.destroy()
				this.ready = false
				await this.endLost(record, MAX_RUN_ERROR, false)
				return record
			}
		}

		if (record.state === "running") {
			await this.check(record)
		}

		if (record.persistPending || record.snapshotPending || record.replaceInstance) {
			await this.finishRun(record, retrySnapshot)
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
		const elapsedMs = Date.now() - record.startedAt
		// Judged before any probe but the exit code, so an overdue run ends whatever
		// the other task files say (F1). A plain failure while ending it is retried,
		// and after OVERDUE_ATTEMPT_LIMIT checks it ends by a path that pushes (G1).
		const overdue = running && this.overdue(record)

		try {
			if (overdue) {
				// A run with an exit code has finished, not overrun (R2). With none, or a
				// read that fails with a plain error, the overdue rule ends it. A
				// TaskFileError goes to the task-file count below.
				const exitCode = await this.host.exitCode().catch((error: unknown) => {
					if (error instanceof TaskFileError) throw error
					return undefined
				})
				return await (exitCode === undefined ? this.endFailed(record, MAX_RUN_ERROR) : this.finish(record, exitCode))
			}

			await this.judge(record, running, elapsedMs)

			if (record.taskFileFailures !== undefined) {
				// Every probe answered: the count starts again.
				Object.assign(record, { taskFileFailures: undefined, lastTaskFileFailureAt: undefined })
				this.save(record)
			}
		} catch (error) {
			// Once the run has ended, what threw is the push or snapshot: it is retried.
			if (record.state !== "running") throw error

			// Only a TaskFileError ends a run with no push. A plain error while ending
			// an overdue run is retried, one counted per check interval, and at the
			// limit the run fails without further probes but its branch is pushed (G1).
			if (overdue && !(error instanceof TaskFileError)) {
				if (this.overdueAttemptFailed(record, error)) return this.endOverdue(record)
				return
			}

			// An exec timeout, a restarting container or a transport error says
			// nothing about the task: the run goes on and the next check retries (R1).
			if (!(error instanceof TaskFileError)) {
				console.error(`Workspace check failed, the run goes on: ${messageOf(error)}`)
				return
			}

			// Status polls can come many times a second: one failure counts per
			// check interval, so the limit means minutes of failing checks (G3).
			const now = Date.now()

			if (!countsNow(record.lastTaskFileFailureAt, now)) {
				console.error(`Workspace found a task file it did not write again within a check interval: ${messageOf(error)}`)
				return
			}

			const taskFileFailures = (record.taskFileFailures ?? 0) + 1
			Object.assign(record, { taskFileFailures, lastTaskFileFailureAt: now })
			this.save(record)
			console.error(`Workspace found a task file it did not write (${taskFileFailures} in a row): ${messageOf(error)}`)

			if (taskFileFailures >= TASK_FILE_FAILURE_LIMIT) {
				return this.endUntrusted(record, "failed", TASK_FILES_ERROR)
			}
		}
	}

	private async judge(record: Record_, running: boolean, elapsedMs: number): Promise<void> {
		let exitCode = running ? await this.host.exitCode() : undefined
		const task = running && exitCode === undefined ? await this.knownTask(record) : undefined
		const taskAlive = task !== undefined && (await this.host.taskAlive(task))

		if (task !== undefined && !taskAlive) {
			// The task can finish after the first read, so read the exit code again.
			exitCode = await this.host.exitCode()
		}

		const outputBytes = running ? await this.host.outputBytes() : undefined
		const verdict = judgeRun({ containerRunning: running, exitCode, taskSeen: task !== undefined, taskAlive, elapsedMs, outputBytes })

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
				return this.endFailed(record, MAX_RUN_ERROR)
			case "output-exceeded":
				return this.endFailed(record, OUTPUT_ERROR)
		}
	}

	// Ends a run whose task files are not what the runner wrote (F1, R1), or an
	// overdue run that could not be ended cleanly. Nothing of the instance is
	// trusted: the stored group gets a best-effort KILL, no file is read, and the
	// instance is replaced without a push or snapshot. A snapshot holds the whole
	// root filesystem and the next run would start from it, so the old one is
	// kept, marked stale, as when the container is gone (Copilot C5).
	private async endUntrusted(record: Record_, state: "failed" | "stopped", error: string): Promise<void> {
		const task = record.task !== undefined && record.task.pid > 1 ? record.task : undefined

		if (task !== undefined && this.host.running) {
			await this.host.signalTask(task, "KILL").catch((killError) => console.error(`Workspace KILL failed: ${messageOf(killError)}`))
		}

		Object.assign(record, {
			state,
			error,
			result: undefined,
			hasConversation: conversationAfter("lost", record.resumed === true, false),
			persistPending: undefined,
			replaceInstance: true,
			...(record.snapshot === undefined ? {} : { snapshotStale: true }),
		})
		this.save(record)
		this.note(record, { notice: "run ended", run: record.run, state, error })
		await this.finishRun(record)
	}

	private overdue(record: Record_): boolean {
		return record.startedAt !== undefined && Date.now() - record.startedAt >= MAX_RUN_MS
	}

	// Counts a plain failure to end or set up an overdue run, at most once per
	// check interval (G1, G4). True once OVERDUE_ATTEMPT_LIMIT have counted.
	private overdueAttemptFailed(record: Record_, error: unknown): boolean {
		const now = Date.now()

		if (!countsNow(record.lastOverdueAttemptAt, now)) {
			console.error(`Workspace could not end an overdue run again within a check interval: ${messageOf(error)}`)
			return false
		}

		const overdueAttempts = (record.overdueAttempts ?? 0) + 1
		Object.assign(record, { overdueAttempts, lastOverdueAttemptAt: now })
		this.save(record)
		console.error(`Workspace could not end an overdue run (${overdueAttempts} tries): ${messageOf(error)}`)
		return overdueAttempts >= OVERDUE_ATTEMPT_LIMIT
	}

	// Ends an overdue run that could not be ended cleanly within
	// OVERDUE_ATTEMPT_LIMIT checks (G1). The stored group gets a best-effort KILL,
	// nothing more is probed, and the run fails with its branch pushed and
	// snapshotted. With no stored group to name, the instance is replaced after.
	private async endOverdue(record: Record_): Promise<void> {
		const task = record.task !== undefined && record.task.pid > 1 ? record.task : undefined

		if (task !== undefined && this.host.running) {
			await this.host.signalTask(task, "KILL").catch((killError) => console.error(`Workspace KILL failed: ${messageOf(killError)}`))
		}

		return this.markFailed(record, MAX_RUN_ERROR, task === undefined)
	}

	// Ends a run the runner cuts short: KILLs its group, reads its output, then
	// pushes and snapshots as after any other run.
	private async endFailed(record: Record_, error: string): Promise<void> {
		const unnamed = await this.endTask(record)
		await this.ingest(record)
		return this.markFailed(record, error, unnamed)
	}

	// replace: no task id names the run's process, so the instance is replaced
	// once persisted, stored with the end state (G5).
	private async markFailed(record: Record_, error: string, replace = false): Promise<void> {
		Object.assign(record, {
			state: "failed",
			error,
			result: undefined,
			hasConversation: conversationAfter("stopped", record.resumed === true, false),
			persistPending: true,
			...(replace ? { replaceInstance: true } : {}),
		})
		this.save(record)
		this.note(record, { notice: "run ended", run: record.run, state: record.state })
		return this.finishRun(record)
	}

	// KILLs the current task's group and waits for its logs to be complete. True
	// when no task id is there to trust: the caller stores replaceInstance with
	// the end state, and the instance is replaced once the run is persisted (G5).
	// Best-effort: a process that left the group (setsid) is not reached.
	private async endTask(record: Record_): Promise<boolean> {
		const task = await this.knownTask(record)

		if (task === undefined) {
			return true
		}

		await this.host.signalTask(task, "KILL")
		await this.waitForOutput()
		return false
	}

	// Up to stopWait for the stdout and stderr copiers to drain what the task wrote.
	private async waitForOutput(): Promise<void> {
		await this.waitFor(this.timing.stopWait, () => this.host.outputDone())
	}

	// A run that ended without an exit code. With the container still up, its
	// output is read and the branch pushed as after any other run.
	// With the container gone, the stored snapshot predates the run: it is kept,
	// marked stale, so the next restore says the run's work was lost (Copilot C5).
	// With no task id known, the instance is replaced after the push (Copilot C4).
	private async endLost(record: Record_, error: string, containerRunning: boolean): Promise<void> {
		const unnamed = containerRunning && (await this.endTask(record))

		if (containerRunning) {
			await this.ingest(record)
		}

		Object.assign(record, {
			state: "lost",
			error,
			hasConversation: conversationAfter("lost", record.resumed === true, false),
			persistPending: containerRunning || undefined,
			...(unnamed ? { replaceInstance: true } : {}),
			...(containerRunning || record.snapshot === undefined ? {} : { snapshotStale: true }),
		})
		this.save(record)
		this.note(record, { notice: "run lost", run: record.run, error })
		if (containerRunning) await this.finishRun(record)
	}

	// The current run's task: the pid file, else the one read earlier (the file
	// can be removed during a run). Stored once seen.
	private async knownTask(record: Record_): Promise<Task | undefined> {
		const file = await this.host.readTask()
		const stored = record.task !== undefined && record.task.pid > 1 ? record.task : undefined
		const task = file === undefined || file === "invalid" ? stored : file

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

	// The leader wrote an exit code. Its group's other members are KILLed before
	// the output is read and the clone pushed (Copilot C6), though a process that
	// left the group can still change the clone; the result is the one
	// ingest kept, not a second read of stdout (Copilot C10).
	private async finish(record: Record_, exitCode: number): Promise<void> {
		const unnamed = await this.endTask(record)
		await this.ingest(record)

		if ((await this.host.outputBytes()) > MAX_OUTPUT_BYTES) {
			return this.markFailed(record, OUTPUT_ERROR, unnamed)
		}

		const results = record.resultLine === undefined ? [] : [record.resultLine]
		const ended = outcome(results, exitCode, await this.host.stderrTail())

		Object.assign(record, {
			state: ended.state,
			result: ended.state === "succeeded" ? ended.result : undefined,
			error: ended.state === "failed" ? ended.error : undefined,
			hasConversation: conversationAfter("finished", record.resumed === true, results.length > 0),
			persistPending: true,
			...(unnamed ? { replaceInstance: true } : {}),
		})
		this.save(record)
		if (ended.state === "succeeded" && ended.truncated) this.note(record, { notice: "result truncated", run: record.run })
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
				// Never read whole, so it cannot say how the run ended (Copilot round 2, E1).
				if (type === "result") record.resultLine = resultSentinel(undefined)
				record.eventsOffset += bytes
				this.save(record)
				continue
			}

			// No await from here to save(): the events and the offset are stored together.
			for (const line of lines) {
				const event = lineEvent(line, parseLine)
				if (!event) continue
				this.eventLog.append(record.run, record.generation, event.type, event.payload)
				if (event.type === "result") {
					const text = new TextDecoder().decode(line)
					record.resultLine = line.byteLength > MAX_PAYLOAD_BYTES ? resultSentinel(text) : text
				}
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
		// An instance that may hold an unnamed process is not reused (Copilot C4).
		if (record.replaceInstance) {
			if (this.host.running) {
				if (record.snapshotPending) {
					this.settle(record, abandonSnapshot(record.run, "The instance was replaced before the snapshot was saved"))
				}

				await this.host.destroy()
				this.ready = false
			}

			record.replaceInstance = false
			this.save(record)
		}

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

		if (path !== "snapshot") await this.host.startFromImage()
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

		const { notice, keepSnapshot, ...fields } = afterRestore(path, {
			generation: record.generation,
			hasConversation: record.hasConversation,
			snapshotError,
			snapshotStale: record.snapshotStale,
		})
		Object.assign(record, fields, { snapshot: keepSnapshot ? record.snapshot : undefined, snapshotStale: undefined })
		this.save(record)
		if (notice) this.note(record, notice)
	}

	private async setUp(record: Record_): Promise<void> {
		this.ready = false

		try {
			await this.host.setPolicy(
				record.repo === undefined
					? { repoPath: "", branch: "", allow: [] }
					: { repoPath: new URL(record.repo).pathname, branch: record.branch ?? "", allow: record.allow },
			)
			await this.host.setInactivityTimeout(inactivityTimeout)
		} catch (error) {
			// Internet is off in the container until the intercepts are registered,
			// so a container without them fails closed. A running run's container is
			// kept: refresh() retries, and the 60-minute cap ends the run (G4).
			if (record.state === "running") throw error

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
