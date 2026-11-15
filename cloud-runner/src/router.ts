import { z } from "zod"

// Route parsing, caller auth and request bodies. Kept out of index.ts: the
// main module may export only handlers and classes, or workerd refuses to start.
const workspaceName = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/

// Linux rejects a command argument of 128 KiB or more, including its NUL byte.
export const MAX_PROMPT_BYTES = 128 * 1024 - 1

// A JSON body carries a prompt of up to MAX_PROMPT_BYTES, which JSON escaping
// can grow to six times that ("\u0001"). Anything over this is refused unread.
export const MAX_BODY_BYTES = 1024 * 1024

export type Action = "create" | "status" | "run" | "events" | "stop" | "diff" | "delete"
export type Route = { name: string; action: Action }

const methods: Record<string, Partial<Record<string, Action>>> = {
	"": { PUT: "create", GET: "status", DELETE: "delete" },
	runs: { POST: "run" },
	events: { GET: "events" },
	stop: { POST: "stop" },
	diff: { GET: "diff" },
}

export function parseRoute(method: string, pathname: string): Route | { error: 404 | 405 | 400 } {
	const match = /^\/workspaces\/([^/]+)(?:\/(runs|events|stop|diff))?$/.exec(pathname)

	if (!match) {
		return { error: 404 }
	}

	const [, name, resource = ""] = match

	if (!workspaceName.test(name)) {
		return { error: 400 }
	}

	const action = methods[resource][method]

	return action === undefined ? { error: 405 } : { name, action }
}

// Compares in time that depends on the longer input only, not on where the
// first difference is. An empty secret never matches.
function sameBytes(left: string, right: string): boolean {
	const encoder = new TextEncoder()
	const a = encoder.encode(left)
	const b = encoder.encode(right)
	let difference = a.length ^ b.length

	for (let i = 0; i < Math.max(a.length, b.length); i++) {
		difference |= (a[i] ?? 0) ^ (b[i] ?? 0)
	}

	return difference === 0
}

export function authorized(request: Request, secret: string): boolean {
	if (secret === "") {
		return false
	}

	const match = /^Bearer (.*)$/i.exec(request.headers.get("authorization") ?? "")

	return match !== null && sameBytes(match[1], secret) && match[1] !== ""
}

const hostname = z
	.string()
	.max(253)
	.regex(/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$/i)
	.transform((host) => host.toLowerCase())

export const CreateBody = z.object({
	// https://github.com/<owner>/<repo>: no .git, no query, no trailing path.
	repo: z
		.string()
		.regex(/^https:\/\/github\.com\/[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/)
		.refine((repo) => !repo.endsWith(".git") && !/\/\.{1,2}$/.test(repo)),
	branch: z.string().min(1).max(200).regex(/^[A-Za-z0-9._/][A-Za-z0-9._/-]*$/),
	allow: z.array(hostname).max(20).default([]),
})

export const RunBody = z.object({
	prompt: z
		.string()
		.refine((prompt) => prompt.trim() !== "")
		.refine((prompt) => new TextEncoder().encode(prompt).byteLength <= MAX_PROMPT_BYTES),
	fresh: z.boolean().default(false),
	maxTurns: z.number().int().min(1).max(100).default(20),
})
