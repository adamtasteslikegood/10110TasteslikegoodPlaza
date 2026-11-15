import { WorkerEntrypoint } from "cloudflare:workers"
import { decide, isContainerCredentialHeader, type Credential, type Policy } from "./egress"
import { checkPush, MAX_COMMAND_BYTES, MAX_PUSH_BYTES } from "./pushguard"
import type { Env } from "./types"

// Set by the workspace when it registers the intercept. branch is the only ref
// a push may update ("" for none).
export type OutboundProps = { repoPath: string; branch: string; allow: string[] }

export function withCredential(request: Request, credential: Credential, env: Env): Request {
	const headers = new Headers(request.headers)

	// Whatever the host, the container sets no credential of its own: the
	// gateway reads cf-aig-* as instructions (cost, logging, cache, key alias)
	// and Authorization or x-api-key as a provider key, and an allowed host could
	// be handed a key it should never see. Names are collected first, then deleted.
	const controlled = [...headers.keys()].filter(isContainerCredentialHeader)
	for (const name of controlled) headers.delete(name)

	if (credential === "gateway") {
		headers.set("cf-aig-authorization", `Bearer ${env.AI_GATEWAY_TOKEN}`)
		// The gateway caches responses for 300 s; a run must never get another's.
		headers.set("cf-aig-skip-cache", "true")
	} else if (credential === "github" && env.GITHUB_TOKEN !== "") {
		// With no token (local runs on a public repository) the request goes
		// out with no credential at all.
		headers.set("Authorization", `Basic ${btoa(`x-access-token:${env.GITHUB_TOKEN}`)}`)
	}

	// Never follow a redirect here: the Worker would not re-decide it and would
	// carry the credential along. The container follows it and each hop comes
	// back through Outbound.
	return new Request(request, { headers, redirect: "manual" })
}

// Names the host only: the path and query can carry a secret.
export function refusal(rawUrl: string): Response {
	let host = "this host"

	try {
		host = new URL(rawUrl).hostname
	} catch {
		// keep the generic name
	}

	return new Response(`${host} is not reachable from this sandbox\n`, { status: 403 })
}

export function policyFor(props: Partial<OutboundProps> | undefined, env: Env): Policy {
	return {
		gatewayPath: `/v1/${env.AI_GATEWAY_ACCOUNT_ID}/${env.AI_GATEWAY_ID}`,
		// With no props the policy has no repository, no branch and no extra hosts.
		repoPath: typeof props?.repoPath === "string" ? props.repoPath : "",
		branch: typeof props?.branch === "string" ? props.branch : "",
		allow: Array.isArray(props?.allow) ? props.allow.map((host) => host.toLowerCase().replace(/\.$/, "")) : [],
	}
}

const pushRefused = (reason: string) => new Response(`github.com refused this push: ${reason}\n`, { status: 403 })

// New head bytes between two checks (F2): checkPush parses from offset 0, so a
// check per chunk is quadratic for a body sent in tiny chunks.
const CHECK_STEP_BYTES = 4 * 1024

// Reads a git-receive-pack body only as far as its command list and asks
// checkPush whether every ref it updates is the workspace branch (Copilot C11).
// What is held before the decision: the chunks read so far, by reference and
// uncopied, to send on unchanged; and a copy of at most MAX_COMMAND_BYTES of
// their start, which is all the parser sees (Copilot E5). The copy is one
// buffer filled in place, checked once per CHECK_STEP_BYTES of new bytes, when
// it is full and at the end of the body (F2). checkPush decides by the time
// the copy is full, so reading stops there. Allowed, the request goes
// on with the held chunks, then the rest of the stream as it arrives. Refused,
// nothing is fetched and the container gets 403. `check` is a seam for tests.
export async function inspectPush(request: Request, branch: string, check: typeof checkPush = checkPush): Promise<Request | Response> {
	if (request.headers.has("content-encoding")) {
		return pushRefused("a compressed push cannot be inspected")
	}

	const stated = request.headers.get("content-length")

	// FixedLengthStream throws on an absurd length (F3), so only a safe integer up to the cap is kept.
	if (stated !== null && (!/^\d+$/.test(stated) || !Number.isSafeInteger(Number(stated)) || Number(stated) > MAX_PUSH_BYTES)) {
		return pushRefused("the Content-Length is not valid")
	}

	if (request.body === null) {
		return pushRefused("the push has no body")
	}

	const reader = request.body.getReader()
	const held: Uint8Array[] = []
	const head = new Uint8Array(MAX_COMMAND_BYTES)
	let filled = 0
	let checked = 0 // filled at the last check
	let ended = false
	let verdict = check(head.subarray(0, 0), branch, ended)

	while (verdict === "more") {
		if (checked >= MAX_COMMAND_BYTES) {
			// checkPush never asks for more past the cap; refuse rather than read on.
			verdict = { allow: false, reason: "the push command list is over 64 KiB" }
			break
		}

		const chunk = await reader.read()

		if (chunk.done) {
			ended = true
		} else if (chunk.value.length > 0) {
			held.push(chunk.value)
			const taken = chunk.value.subarray(0, MAX_COMMAND_BYTES - filled)
			head.set(taken, filled)
			filled += taken.length
		}

		if (ended || filled >= MAX_COMMAND_BYTES || filled - checked >= CHECK_STEP_BYTES) {
			checked = filled
			verdict = check(head.subarray(0, filled), branch, ended)
		}
	}

	if (!verdict.allow) {
		await reader.cancel().catch(() => {})
		return pushRefused(verdict.reason)
	}

	let rest: ReadableStream<Uint8Array> = new ReadableStream<Uint8Array>({
		start(controller) {
			for (const chunk of held) controller.enqueue(chunk)
			held.length = 0
			if (ended) controller.close()
		},
		async pull(controller) {
			const chunk = await reader.read()
			if (chunk.done) controller.close()
			else controller.enqueue(chunk.value)
		},
		cancel(reason) {
			return reader.cancel(reason)
		},
	})

	if (stated !== null) {
		// Keeps the length git stated; a body of another length fails the fetch.
		const fixed = new FixedLengthStream(Number(stated))
		rest.pipeTo(fixed.writable).catch(() => {})
		rest = fixed.readable
	}

	return new Request(request, { body: rest })
}

export class Outbound extends WorkerEntrypoint<Env, OutboundProps> {
	async fetch(request: Request): Promise<Response> {
		const policy = policyFor(this.ctx.props, this.env)
		const decision = decide(request.method, request.url, policy)

		if (!decision.allow) {
			return refusal(request.url)
		}

		if (decision.push) {
			const inspected = await inspectPush(request, policy.branch)
			if (inspected instanceof Response) return inspected
			return fetch(withCredential(inspected, decision.credential, this.env))
		}

		return fetch(withCredential(request, decision.credential, this.env))
	}
}
