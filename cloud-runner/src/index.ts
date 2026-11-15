import { CreateBody, ExecBody, MAX_BODY_BYTES, MAX_PROMPT_BYTES, RunBody, authorized, parseRoute } from "./router"
import type { Env } from "./types"

export { Workspace } from "./workspace"
export { Outbound } from "./outbound"
export type { Env } from "./types"

const missing = "No such workspace: create it with PUT first"

const text = (body: string, status: number) => new Response(`${body}\n`, { status, headers: { "content-type": "text/plain" } })

// Reads the body as text, stopping as soon as it passes MAX_BODY_BYTES, so a
// body with no content-length is never buffered whole. Answers undefined when too large.
async function readCapped(request: Request): Promise<string | undefined> {
	if (request.body === null) {
		return ""
	}

	const reader = request.body.getReader()
	const chunks: Uint8Array[] = []
	let size = 0

	for (;;) {
		const { done, value } = await reader.read()

		if (done) {
			break
		}

		size += value.byteLength

		if (size > MAX_BODY_BYTES) {
			await reader.cancel()
			return undefined
		}

		chunks.push(value)
	}

	const bytes = new Uint8Array(size)
	let offset = 0

	for (const chunk of chunks) {
		bytes.set(chunk, offset)
		offset += chunk.byteLength
	}

	return new TextDecoder().decode(bytes)
}

// Reads a JSON body. Answers a Response when the body is too large or is not JSON.
async function readJson(request: Request): Promise<{ value: unknown } | { response: Response }> {
	const declared = Number(request.headers.get("content-length"))

	if (declared > MAX_BODY_BYTES) {
		return { response: text("The request body is too large", 413) }
	}

	const raw = await readCapped(request)

	if (raw === undefined) {
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
		const route = parseRoute(request.method, url.pathname, env.ALLOW_TEST_ROUTES === "1")

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

					const created = await workspace.create(body.data.repo, body.data.branch, body.data.allow)

					if (created === "conflict") {
						return text("The workspace exists with another repo or branch", 409)
					}

					if (created.cloneError !== undefined) {
						return Response.json({ ...created.status, cloneError: created.cloneError }, { status: 502 })
					}

					return Response.json(created.status)
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

					const started = await workspace.startRun(body.data.prompt, body.data.fresh, body.data.maxTurns)

					if (started === "busy") {
						return text("A run is already active", 409)
					}

					if (started === "missing") {
						return text(missing, 404)
					}

					return Response.json(started, { status: 202 })
				}

				case "events": {
					const after = afterParam(url)

					if (after === undefined) {
						return text("after must be a non-negative integer", 400)
					}

					const events = await workspace.events(after)

					return events === "missing" ? text(missing, 404) : Response.json(events)
				}

				case "status":
					return Response.json(await workspace.status())

				case "stop": {
					const status = await workspace.stop()

					if (status === "still-running") {
						return text("The run could not be stopped: its task is still running. Try again.", 409)
					}

					return status === "missing" ? text(missing, 404) : Response.json(status)
				}

				case "diff": {
					const diff = await workspace.diff()

					if (diff === "missing") {
						return text(missing, 404)
					}

					return new Response(diff.text, { status: diff.ok ? 200 : 502, headers: { "content-type": "text/plain" } })
				}

				case "delete":
					await workspace.destroyWorkspace()
					return new Response(null, { status: 204 })

				case "replace-instance": {
					const status = await workspace.replaceInstance()
					return status === "missing" ? text(missing, 404) : Response.json(status)
				}

				case "exec": {
					const read = await readJson(request)

					if ("response" in read) {
						return read.response
					}

					const body = ExecBody.safeParse(read.value)

					if (!body.success) {
						return text('Send {"argv": ["command", "arg"]}', 400)
					}

					const result = await workspace.exec(body.data.argv)
					return result === "missing" ? text(missing, 404) : Response.json(result)
				}
			}
		} catch (error) {
			console.error("Workspace request failed", error)
			return text("Workspace request failed", 500)
		}
	},
} satisfies ExportedHandler<Env>
