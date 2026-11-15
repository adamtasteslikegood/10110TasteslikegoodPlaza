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

// True when the URL parser did not change the string: no dropped tabs or
// newlines, no backslash read as a slash, no folded dot segments, nothing
// added. Scheme and host may differ in case only (the parser lowercases them),
// and a fragment is never sent so it is ignored. Everything after the
// authority must match exactly, so the text we judge is the text that is fetched.
function isSerialized(rawUrl: string, url: URL): boolean {
	const input = rawUrl.split("#", 1)[0]
	const parsed = url.href.split("#", 1)[0]
	const head = `https://${url.host}`

	return input.slice(0, head.length).toLowerCase() === head && input.slice(head.length) === parsed.slice(head.length)
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

	if (!isSerialized(rawUrl, url)) {
		return refuse("the request URL is not in its normal form")
	}

	const host = url.hostname.toLowerCase().replace(/\.$/, "")
	// Safe to use: the URL is in serialized form, so this is the path as sent.
	const path = url.pathname
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
