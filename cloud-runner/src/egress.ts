// The allow/refuse decision for one request leaving a sandbox container. Pure:
// no network, no environment. Everything that decides lives here; outbound.ts
// only applies the answer.

// repoPath "/owner/repo"; branch is the workspace branch, the only ref a push
// may update, or "" for none.
export type Policy = { gatewayPath: string; repoPath: string; branch: string; allow: string[] }

export type Credential = "gateway" | "github" | "none"

// push: the request is a git-receive-pack POST. outbound.ts reads its command
// list (pushguard.ts) before it forwards anything (Copilot C11).
export type Decision = { allow: true; credential: Credential; push?: true } | { allow: false; reason: string }

const GATEWAY_HOST = "gateway.ai.cloudflare.com"
const GITHUB_HOST = "github.com"
const PACKAGE_HOSTS = ["registry.npmjs.org", "pypi.org", "files.pythonhosted.org"]
const READ_ONLY = ["GET", "HEAD"]

const refuse = (reason: string): Decision => ({ allow: false, reason })

// Headers that carry a credential or instruct the gateway. The container never
// sets them for any host: outbound.ts drops them all before adding the one
// header the Worker owns for the chosen credential.
const CREDENTIAL_HEADERS = ["authorization", "proxy-authorization", "x-api-key"]

// The gateway's cache headers under their older names. Its documentation calls
// them deprecated but says they still work, so they are instructions too.
const OLDER_GATEWAY_HEADERS = ["cf-skip-cache", "cf-cache-ttl"]

export function isContainerCredentialHeader(name: string): boolean {
	const lower = name.toLowerCase()
	return CREDENTIAL_HEADERS.includes(lower) || OLDER_GATEWAY_HEADERS.includes(lower) || lower.startsWith("cf-aig-")
}

// True when the URL parser did not change the string: no dropped tabs or
// newlines, no backslash read as a slash, no folded dot segments, nothing
// added. Scheme and host may differ in case only (the parser lowercases them),
// and a fragment is never sent so it is ignored. Everything after the
// authority must match exactly, so the text we judge is the text that is fetched.
// One exception: a URL that ends at its host is that host's "/", since a
// request for the bare root can arrive without the slash.
function isSerialized(rawUrl: string, url: URL): boolean {
	const input = rawUrl.split("#", 1)[0]
	const parsed = url.href.split("#", 1)[0]
	const head = `https://${url.host}`
	const rest = input.slice(head.length)

	return input.slice(0, head.length).toLowerCase() === head && (rest === "" ? "/" : rest) === parsed.slice(head.length)
}

// Dot segments, empty segments, encoded dots or slashes, and backslashes (which
// URL parsing treats as slashes) all let a path say something other than what
// a plain string comparison sees.
const UNSAFE_PATH = /(^|\/)\.{1,2}(\/|$)|\/\/|%2e|%2f|%5c|\\/i

const SERVICES = ["git-upload-pack", "git-receive-pack"]

// GET <repo>[.git]/info/refs?service=<service>, or POST <repo>[.git]/<service>
// with no query. The query must be exactly the one git sends.
function isSmartHttp(verb: string, path: string, search: string, repo: string): boolean {
	const rest = path.startsWith(`${repo}.git/`) ? path.slice(repo.length + 4) : path.startsWith(`${repo}/`) ? path.slice(repo.length) : undefined

	if (rest === "/info/refs") {
		return verb === "GET" && SERVICES.some((service) => search === `?service=${service}`)
	}

	return verb === "POST" && search === "" && SERVICES.some((service) => rest === `/${service}`)
}

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

	if (host === GITHUB_HOST) {
		// Only git's smart-HTTP requests for this workspace's repository: the ref
		// advertisement and the pack exchange, for fetch and push. The token goes
		// nowhere else on github.com, and nothing else there is reachable, even
		// when the workspace's own hosts name github.com.
		if (policy.repoPath !== "" && !UNSAFE_PATH.test(path) && isSmartHttp(verb, path, url.search, policy.repoPath)) {
			if (verb !== "POST" || !path.endsWith("/git-receive-pack")) {
				return { allow: true, credential: "github" }
			}

			// A push: allowed only for the workspace branch, which outbound.ts
			// checks in the body. With no branch nothing may be pushed.
			return policy.branch === "" ? refuse("a push needs the workspace branch") : { allow: true, credential: "github", push: true }
		}

		return refuse("only git fetch and push of the workspace repository are allowed on github.com")
	}

	if (PACKAGE_HOSTS.includes(host) || policy.allow.includes(host)) {
		// A host here is never given a credential: github.com and the gateway
		// host are decided above.
		return READ_ONLY.includes(verb) ? { allow: true, credential: "none" } : refuse("only GET and HEAD are allowed on this host")
	}

	return refuse("this host is not allowed")
}
