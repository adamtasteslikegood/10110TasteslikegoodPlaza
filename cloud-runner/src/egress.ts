// The allow/refuse decision for one request leaving a sandbox container. Pure:
// no network, no environment. Everything that decides lives here; outbound.ts
// only applies the answer.

export type Policy = { gatewayPath: string; repoPath: string; allow: string[] } // repoPath "/owner/repo"

export type Credential = "gateway" | "github" | "none"

export type Decision = { allow: true; credential: Credential } | { allow: false; reason: string }

const GATEWAY_HOST = "gateway.ai.cloudflare.com"
const GITHUB_HOST = "github.com"
const PACKAGE_HOSTS = ["registry.npmjs.org", "pypi.org", "files.pythonhosted.org"]
const READ_ONLY = ["GET", "HEAD"]

const refuse = (reason: string): Decision => ({ allow: false, reason })

// The path as the sender wrote it: between the authority and the first "?" or
// "#". new URL() folds ".." and "." away, so the check has to read the raw text.
function rawPathOf(rawUrl: string): string {
	const rest = rawUrl.slice(rawUrl.indexOf("://") + 3)
	const start = rest.search(/[/?#]/)

	if (start === -1) {
		return "/"
	}

	const path = rest.slice(start).split(/[?#]/, 1)[0]

	return path === "" ? "/" : path
}

// Dot segments, empty segments, encoded dots or slashes, and backslashes (which
// URL parsing treats as slashes) all let a path say something other than what
// a plain string comparison sees.
const UNSAFE_PATH = /(^|\/)\.{1,2}(\/|$)|\/\/|%2e|%2f|%5c|\\/i

export function decide(method: string, rawUrl: string, policy: Policy): Decision {
	let url: URL

	try {
		url = new URL(rawUrl)
	} catch {
		return refuse("the request URL cannot be parsed")
	}

	if (url.protocol !== "https:") {
		return refuse("only HTTPS is allowed")
	}

	if (url.port !== "") {
		return refuse("only port 443 is allowed")
	}

	if (url.username !== "" || url.password !== "") {
		return refuse("a URL with credentials is not allowed")
	}

	const host = url.hostname.toLowerCase().replace(/\.$/, "")
	const path = rawPathOf(rawUrl)
	const verb = method.toUpperCase()

	if (host === GATEWAY_HOST) {
		// Only the Anthropic route of our own gateway. The gateway has Unified
		// Billing on, so any wider rule would let the container call other
		// providers on the owner's account.
		if (!UNSAFE_PATH.test(path) && path.startsWith(`${policy.gatewayPath}/anthropic/`)) {
			return { allow: true, credential: "gateway" }
		}

		return refuse("only the Anthropic route of the workspace gateway is allowed")
	}

	if (host === GITHUB_HOST && policy.repoPath !== "") {
		const repo = policy.repoPath
		const ours = path === repo || path === `${repo}.git` || path.startsWith(`${repo}/`) || path.startsWith(`${repo}.git/`)

		if (!UNSAFE_PATH.test(path) && ours) {
			return { allow: true, credential: "github" }
		}
	}

	if (PACKAGE_HOSTS.includes(host) || policy.allow.includes(host)) {
		// A host here is never given a credential, even when it is github.com
		// or the gateway host: those two are decided above or refused below.
		return READ_ONLY.includes(verb) ? { allow: true, credential: "none" } : refuse("only GET and HEAD are allowed on this host")
	}

	return refuse("this host is not allowed")
}
