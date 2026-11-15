import { DurableObject } from "cloudflare:workers"
import type { Env } from "./types"

// Stub: Task 5 fills in the container, runs, alarm, push and snapshot. The
// method names are the ones the router in index.ts calls.
export class Workspace extends DurableObject<Env> {
	async create(_repo: string, _branch: string, _allow: string[]): Promise<unknown> {
		throw new Error("not implemented")
	}

	async status(): Promise<unknown> {
		throw new Error("not implemented")
	}

	async startRun(_prompt: string, _fresh: boolean, _maxTurns: number): Promise<unknown> {
		throw new Error("not implemented")
	}

	async events(_after: number): Promise<unknown> {
		throw new Error("not implemented")
	}

	async stop(): Promise<unknown> {
		throw new Error("not implemented")
	}

	async diff(): Promise<unknown> {
		throw new Error("not implemented")
	}

	async destroyWorkspace(): Promise<unknown> {
		throw new Error("not implemented")
	}
}
