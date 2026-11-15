import { z } from "zod"

// Route parsing, caller auth and request bodies. Kept out of index.ts: the
// main module may export only handlers and classes, or workerd refuses to start.
const workspaceName = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/

// Linux rejects a command argument of 128 KiB or more, including its NUL byte.
export const MAX_PROMPT_BYTES = 128 * 1024 - 1

// A JSON body carries a prompt of up to MAX_PROMPT_BYTES, which JSON escaping
// can grow to six times that ("\u0001"). Anything over this is refused unread.
export const MAX_BODY_BYTES = 1024 * 1024

export type Action = "create" | "status" | "run" | "events" | "stop" | "diff" | "delete" | "replace-instance" | "exec"
export type Route = { name: string; action: Action }

const methods: Record<string, Partial<Record<string, Action>>> = {
	"": { PUT: "create", GET: "status", DELETE: "delete" },
	runs: { POST: "run" },
	events: { GET: "events" },
	stop: { POST: "stop" },
	diff: { GET: "diff" },
	"replace-instance": { POST: "replace-instance" },
	exec: { POST: "exec" },
}

// Routes for the acceptance checks on the development deploy only: they do not
// exist (404) unless the caller passes testRoutes, set from ALLOW_TEST_ROUTES.
const testResources = new Set(["replace-instance", "exec"])

export function parseRoute(method: string, pathname: string, testRoutes = false): Route | { error: 404 | 405 | 400 } {
	const match = /^\/workspaces\/([^/]+)(?:\/(runs|events|stop|diff|replace-instance|exec))?$/.exec(pathname)

	if (!match) {
		return { error: 404 }
	}

	const [, name, resource = ""] = match

	if (testResources.has(resource) && !testRoutes) {
		return { error: 404 }
	}

	if (!workspaceName.test(name)) {
		return { error: 400 }
	}

	// Own keys only: "constructor" or "__proto__" must not reach Object.prototype.
	const action = Object.hasOwn(methods[resource], method) ? methods[resource][method] : undefined

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
	.regex(/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/i)
	// A name, not an address: at least two labels, and a last label that is not a
	// number or hex, so 127.0.0.1, 0x7f.1 and single-label names like localhost fail.
	.refine((host) => {
		const last = host.slice(host.lastIndexOf(".") + 1)
		return /[a-z]/i.test(last) && !/^0x[0-9a-f]*$/i.test(last)
	})
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
		// A command argument cannot carry a NUL; it would cut the prompt short.
		.refine((prompt) => !prompt.includes("\0"))
		.refine((prompt) => new TextEncoder().encode(prompt).byteLength <= MAX_PROMPT_BYTES),
	fresh: z.boolean().default(false),
	maxTurns: z.number().int().min(1).max(100).default(20),
})

export const MAX_EXEC_ARGS = 64

// The test-only exec route's body: a command and its arguments, run with no shell
// unless argv names one. Bounded like a prompt: no NUL, under 128 KiB in all.
// It runs as the agent user; root: true runs it as root, to look at what the
// agent cannot (the task directory, another user's processes).
export const ExecBody = z.object({
	root: z.boolean().default(false),
	argv: z
		.array(z.string().refine((arg) => !arg.includes("\0")))
		.min(1)
		.max(MAX_EXEC_ARGS)
		.refine((argv) => argv[0] !== "")
		.refine((argv) => new TextEncoder().encode(argv.join("\0")).byteLength <= MAX_PROMPT_BYTES),
})
