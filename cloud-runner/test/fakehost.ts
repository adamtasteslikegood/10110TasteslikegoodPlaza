import type { CommandResult } from "../src/container"
import type { Host, Signal, Task } from "../src/host"
import type { OutboundProps } from "../src/outbound"
import type { Pushed, Saved } from "../src/persist"

type Group = { alive: boolean; ignoresTerm: boolean }
type Probe = "push" | "exitCode" | "readTask" | "readOutput" | "outputBytes" | "outputDone"

// A container in memory, behind the Workspace's one seam. It models what the
// rules depend on: the pid file, the task's process groups, the exit code the
// session leader writes, stdout.log, and pushes and snapshots. `calls` logs every
// action in order. Every input is bounded: nothing here can grow without end.
export class FakeHost implements Host {
	running = false
	calls: string[] = []
	boot = "boot-1"
	nextPid = 100
	task?: Task // what the pid file holds
	groups = new Map<number, Group>()
	exit?: number
	stdout: Uint8Array = new Uint8Array()
	// The size stdout.log reports, when a test sets one larger than stdout.
	outputSize?: number
	pidInvalid = false // the pid file exists but does not parse
	snapshots = 0
	// A snapshot that answers this many ms late (bounded), or fails.
	snapshotDelayMs = 0
	snapshotError?: string
	// How many image starts fail before one answers.
	imageFailures = 0
	execResult: CommandResult = { exitCode: 0, stdout: "", stderr: "" }

	// How the next startTask behaves.
	startMode: "spawn" | "spawn-then-throw" | "throw" | "no-pid" = "spawn"
	ignoresTerm = false
	// One error to throw at the next call of a method, then gone.
	failOnce: Partial<Record<Probe, Error>> = {}
	// Probes that throw on every call, as a task file the agent replaced with a
	// directory or a FIFO would make them (F1).
	broken = new Set<Probe>()

	private fail(name: Probe): void {
		if (this.broken.has(name)) throw new Error(`${name} could not read the task files`)
		const error = this.failOnce[name]

		if (error) {
			delete this.failOnce[name]
			throw error
		}
	}

	count(call: string): number {
		return this.calls.filter((c) => c === call).length
	}

	// The running task's leader ends on its own, after writing these stdout
	// lines. With background set, a member of its group outlives it.
	finishTask(exitCode: number, lines: string[], background = false): void {
		const group = this.task && this.groups.get(this.task.pid)
		if (group && !background) group.alive = false
		this.exit = exitCode
		this.stdout = new TextEncoder().encode(lines.map((line) => `${line}\n`).join(""))
	}

	async startFromImage(): Promise<void> {
		this.calls.push("startFromImage")

		if (this.imageFailures > 0) {
			this.imageFailures -= 1
			throw new Error("The new instance did not answer")
		}

		this.running = true
		this.calls.push("image ready")
	}

	async startFromSnapshot(id: string): Promise<string | undefined> {
		this.calls.push(`startFromSnapshot ${id}`)
		this.running = true
		return undefined
	}

	async destroy(): Promise<void> {
		this.calls.push("destroy")
		this.running = false
	}

	// Every policy set, in order (Copilot C11 checks the branch in each).
	policies: OutboundProps[] = []

	async setPolicy(props: OutboundProps): Promise<void> {
		this.calls.push(`setPolicy ${props.repoPath}`)
		this.policies.push(props)
	}

	async setInactivityTimeout(): Promise<void> {}

	// What clone() answers: undefined for success, or the clone error.
	cloneError: string | undefined = undefined

	async clone(_repo: string, branch: string): Promise<string | undefined> {
		this.calls.push(`clone ${branch}`)
		return this.cloneError
	}

	async push(branch: string): Promise<Pushed> {
		this.calls.push(`push ${branch}`)
		this.fail("push")
		return { commit: `commit-${this.count(`push ${branch}`)}` }
	}

	async snapshot(): Promise<Saved> {
		this.calls.push("snapshot")
		this.snapshots += 1
		const id = `snap-${this.snapshots}`
		if (this.snapshotDelayMs > 0) await new Promise((resolve) => setTimeout(resolve, this.snapshotDelayMs))
		return this.snapshotError === undefined ? { id, size: 1 } : { error: this.snapshotError }
	}

	async diff(): Promise<{ ok: boolean; text: string }> {
		return { ok: true, text: "" }
	}

	async resetTask(): Promise<void> {
		this.calls.push("resetTask")
		this.task = undefined
		this.pidInvalid = false
		this.exit = undefined
		this.stdout = new Uint8Array()
		this.outputSize = undefined
	}

	async startTask(): Promise<void> {
		this.calls.push("startTask")

		if (this.startMode === "throw") {
			throw new Error("exec failed before the task started")
		}

		const pid = this.nextPid++
		this.groups.set(pid, { alive: true, ignoresTerm: this.ignoresTerm })

		if (this.startMode !== "no-pid") {
			this.task = { pid, boot: this.boot }
		}

		if (this.startMode === "spawn-then-throw") {
			throw new Error("exec failed after the task started")
		}
	}

	async readTask(): Promise<Task | "invalid" | undefined> {
		this.fail("readTask")
		return this.pidInvalid ? "invalid" : this.task
	}

	async taskAlive(task: Task): Promise<boolean> {
		return task.boot === this.boot && this.groups.get(task.pid)?.alive === true
	}

	async signalTask(task: Task, signal: Signal): Promise<void> {
		this.calls.push(`signal ${task.pid} ${signal}`)
		const group = this.groups.get(task.pid)

		if (!group?.alive || task.boot !== this.boot) {
			return
		}

		if (signal === "KILL") {
			group.alive = false // the leader dies too: no exit code
		} else if (!group.ignoresTerm) {
			group.alive = false
			if (this.task?.pid === task.pid) this.exit = 143 // the leader writes it
		}
	}

	async exitCode(): Promise<number | undefined> {
		this.fail("exitCode")
		return this.exit
	}

	async readOutput(offset: number, max: number): Promise<Uint8Array> {
		this.fail("readOutput")
		return this.stdout.slice(offset, offset + max)
	}

	async lineLength(): Promise<{ bytes: number; ended: boolean }> {
		return { bytes: 0, ended: false }
	}

	async outputBytes(): Promise<number> {
		this.fail("outputBytes")
		return this.outputSize ?? this.stdout.byteLength
	}

	async outputDone(): Promise<boolean> {
		this.fail("outputDone")
		return true
	}

	async exec(argv: string[]): Promise<CommandResult> {
		this.calls.push(`exec ${argv.join(" ")}`)
		return this.execResult
	}

	async stderrTail(): Promise<string> {
		return ""
	}
}
