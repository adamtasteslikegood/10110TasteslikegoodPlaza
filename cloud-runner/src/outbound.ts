import { WorkerEntrypoint } from "cloudflare:workers"
import { decide, isContainerCredentialHeader, type Credential, type Policy } from "./egress"
import type { Env } from "./types"

// Set by the workspace when it registers the intercept.
export type OutboundProps = { repoPath: string; allow: string[] }

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

function policyFor(props: Partial<OutboundProps> | undefined, env: Env): Policy {
	return {
		gatewayPath: `/v1/${env.AI_GATEWAY_ACCOUNT_ID}/${env.AI_GATEWAY_ID}`,
		// With no props the policy has no repository and no extra hosts.
		repoPath: typeof props?.repoPath === "string" ? props.repoPath : "",
		allow: Array.isArray(props?.allow) ? props.allow.map((host) => host.toLowerCase().replace(/\.$/, "")) : [],
	}
}

export class Outbound extends WorkerEntrypoint<Env, OutboundProps> {
	async fetch(request: Request): Promise<Response> {
		const decision = decide(request.method, request.url, policyFor(this.ctx.props, this.env))

		if (!decision.allow) {
			return refusal(request.url)
		}

		return fetch(withCredential(request, decision.credential, this.env))
	}
}
