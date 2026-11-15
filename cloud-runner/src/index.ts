import { z } from "zod"
import type { Env } from "./types"

export { Workspace } from "./workspace"
export type { Env } from "./types"

const workspaceName = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/

// Linux rejects a command argument of 128 KiB or more, including its NUL byte.
export const MAX_PROMPT_BYTES = 128 * 1024 - 1

// A JSON body carries a prompt of up to MAX_PROMPT_BYTES, which JSON escaping
// can grow to six times that ("\u0001"). Anything over this is refused unread.
const MAX_BODY_BYTES = 1024 * 1024

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

const text = (body: string, status: number) => new Response(`${body}\n`, { status, headers: { "content-type": "text/plain" } })

// Reads a JSON body. Answers a Response when the body is too large or is not JSON.
async function readJson(request: Request): Promise<{ value: unknown } | { response: Response }> {
	const declared = Number(request.headers.get("content-length"))

	if (declared > MAX_BODY_BYTES) {
		return { response: text("The request body is too large", 413) }
	}

	const raw = await request.text()

	if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
		return { response: text("The request body is too large", 413) }
	}

	try {
		return { value: JSON.parse(raw) }
	} catch {
		return { response: text("Send a JSON body", 400) }
	}
}

function afterParam(url: URL): number | undefined {
	const raw = url.searchParams.get("after")

	if (raw === null) {
		return 0
	}

	const after = /^\d+$/.test(raw) ? Number(raw) : NaN

	return Number.isSafeInteger(after) ? after : undefined
}

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		if (!authorized(request, env.RUNNER_CALLER_SECRET)) {
			return text("Unauthorized", 401)
		}

		const url = new URL(request.url)
		const route = parseRoute(request.method, url.pathname)

		if ("error" in route) {
			const messages = { 400: "Bad workspace name", 404: "Not found", 405: "Method not allowed" }
			return text(messages[route.error], route.error)
		}

		const workspace = env.WORKSPACE.getByName(route.name)

		try {
			switch (route.action) {
				case "create": {
					const read = await readJson(request)

					if ("response" in read) {
						return read.response
					}

					const body = CreateBody.safeParse(read.value)

					if (!body.success) {
						return text('Send {"repo": "https://github.com/OWNER/REPO", "branch": "BRANCH", "allow": ["host"]}', 400)
					}

					return Response.json(await workspace.create(body.data.repo, body.data.branch, body.data.allow))
				}

				case "run": {
					const read = await readJson(request)

					if ("response" in read) {
						return read.response
					}

					const prompt = (read.value as { prompt?: unknown } | null)?.prompt

					if (typeof prompt === "string" && new TextEncoder().encode(prompt).byteLength > MAX_PROMPT_BYTES) {
						return text("Send a prompt smaller than 128 KiB", 413)
					}

					const body = RunBody.safeParse(read.value)

					if (!body.success) {
						return text('Send {"prompt": "...", "fresh": false, "maxTurns": 20}, with maxTurns from 1 to 100', 400)
					}

					return Response.json(await workspace.startRun(body.data.prompt, body.data.fresh, body.data.maxTurns), { status: 202 })
				}

				case "events": {
					const after = afterParam(url)

					if (after === undefined) {
						return text("after must be a non-negative integer", 400)
					}

					return Response.json(await workspace.events(after))
				}

				case "status":
					return Response.json(await workspace.status())

				case "stop":
					return Response.json(await workspace.stop())

				case "diff":
					return new Response(String(await workspace.diff()), { headers: { "content-type": "text/plain" } })

				case "delete":
					await workspace.destroyWorkspace()
					return new Response(null, { status: 204 })
			}
		} catch (error) {
			console.error("Workspace request failed", error)
			return text("Workspace request failed", 500)
		}
	},
} satisfies ExportedHandler<Env>
