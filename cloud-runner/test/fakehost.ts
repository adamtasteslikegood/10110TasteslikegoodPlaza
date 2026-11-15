import type { Host, Signal, Task } from "../src/host"
import type { OutboundProps } from "../src/outbound"
import type { Pushed, Saved } from "../src/persist"

type Group = { alive: boolean; ignoresTerm: boolean }

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
	results: string[] = []
	snapshots = 0

	// How the next startTask behaves.
	startMode: "spawn" | "spawn-then-throw" | "throw" | "no-pid" = "spawn"
	ignoresTerm = false
	// One error to throw at the next call of a method, then gone.
	failOnce: Partial<Record<"push" | "exitCode" | "readTask", Error>> = {}

	private fail(name: keyof FakeHost["failOnce"]): void {
		const error = this.failOnce[name]

		if (error) {
			delete this.failOnce[name]
			throw error
		}
	}

	count(call: string): number {
		return this.calls.filter((c) => c === call).length
	}

	// The running task ends on its own, after writing these stdout lines.
	finishTask(exitCode: number, lines: string[]): void {
		const group = this.task && this.groups.get(this.task.pid)
		if (group) group.alive = false
		this.exit = exitCode
		this.stdout = new TextEncoder().encode(lines.map((line) => `${line}\n`).join(""))
		this.results = lines.filter((line) => line.includes('"type":"result"'))
	}

	startFromImage(): void {
		this.calls.push("startFromImage")
		this.running = true
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

	async setPolicy(props: OutboundProps): Promise<void> {
		this.calls.push(`setPolicy ${props.repoPath}`)
	}

	async setInactivityTimeout(): Promise<void> {}

	async clone(_repo: string, branch: string): Promise<string | undefined> {
		this.calls.push(`clone ${branch}`)
		return undefined
	}

	async push(branch: string): Promise<Pushed> {
		this.calls.push(`push ${branch}`)
		this.fail("push")
		return { commit: `commit-${this.count(`push ${branch}`)}` }
	}

	async snapshot(): Promise<Saved> {
		this.calls.push("snapshot")
		this.snapshots += 1
		return { id: `snap-${this.snapshots}`, size: 1 }
	}

	async diff(): Promise<{ ok: boolean; text: string }> {
		return { ok: true, text: "" }
	}

	async resetTask(): Promise<void> {
		this.calls.push("resetTask")
		this.task = undefined
		this.exit = undefined
		this.stdout = new Uint8Array()
		this.results = []
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

	async readTask(): Promise<Task | undefined> {
		this.fail("readTask")
		return this.task
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
		return this.stdout.slice(offset, offset + max)
	}

	async lineLength(): Promise<{ bytes: number; ended: boolean }> {
		return { bytes: 0, ended: false }
	}

	async resultLines(): Promise<string[]> {
		return this.results
	}

	async stderrTail(): Promise<string> {
		return ""
	}
}
