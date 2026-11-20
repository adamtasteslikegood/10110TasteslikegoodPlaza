import type { Workspace } from "./workspace"

export type RunState = "none" | "idle" | "running" | "succeeded" | "failed" | "stopped" | "lost"

export type Status = {
	state: RunState
	run: number // 0 before the first run
	generation: number // +1 each time a container instance is started
	repo?: string
	branch?: string
	result?: string
	error?: string
	pushed?: { commit: string } // head of branch after the last successful push
	pushError?: string
	restored?: "snapshot" | "branch" // how the current instance got its files
	uncommittedLost?: boolean // true when restored from branch after a previous instance
}

export type Event = {
	seq: number
	run: number
	generation: number
	at: string // ISO 8601
	type: string // Claude Code's event `type`, or "runner" for runner notices
	payload: unknown // the parsed line; { truncated: true, bytes } when over the cap
}

export type Env = {
	WORKSPACE: DurableObjectNamespace<Workspace>
	RUNNER_CALLER_SECRET: string
	AI_GATEWAY_TOKEN: string
	GITHUB_TOKEN: string
	// Optional JSON object from "owner/repo" (lower case) to a token; when set, it replaces GITHUB_TOKEN.
	GITHUB_TOKENS?: string
	AI_GATEWAY_ACCOUNT_ID: string
	AI_GATEWAY_ID: string
	MODEL: string
	// "1" only in the git-ignored wrangler.dev.jsonc: turns on the test-only routes.
	ALLOW_TEST_ROUTES?: string
}
