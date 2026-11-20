import type { Env } from "./types"

// The GitHub token for a repository ("https://github.com/OWNER/REPO" or a
// bare path "/OWNER/REPO"). GITHUB_TOKENS, a JSON object from "owner/repo" in
// lower case to a token, wins when set; an unset or empty one means stage 1:
// GITHUB_TOKEN, which may be "" (no credential, a public repository). Once the
// map is set there is no fallback: a repository it does not list, a map that is
// not an object and a value that is not a non-empty string all find no token
// (undefined). The token is returned to the caller and goes nowhere else.
export function tokenFor(env: Pick<Env, "GITHUB_TOKEN" | "GITHUB_TOKENS">, repo: string): string | undefined {
	const raw = env.GITHUB_TOKENS

	if (raw === undefined || raw === "") {
		return env.GITHUB_TOKEN
	}

	let map: unknown

	try {
		map = JSON.parse(raw)
	} catch {
		return undefined
	}

	if (typeof map !== "object" || map === null || Array.isArray(map)) {
		return undefined
	}

	let path = ""

	try {
		path = new URL(repo, "https://github.com").pathname
	} catch {
		return undefined
	}

	const key = path.replace(/^\/+/, "").toLowerCase()
	const token = Object.hasOwn(map, key) ? (map as Record<string, unknown>)[key] : undefined

	return typeof token === "string" && token !== "" ? token : undefined
}
