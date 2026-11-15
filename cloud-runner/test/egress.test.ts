import { describe, expect, it } from "vitest"
import { decide, isContainerCredentialHeader, type Policy } from "../src/egress"

const policy: Policy = { gatewayPath: "/v1/acct/gw", repoPath: "/acme/app", allow: ["example.org"] }

const allowed: [string, string, string][] = [
	["POST", "https://gateway.ai.cloudflare.com/v1/acct/gw/anthropic/v1/messages", "gateway"],
	["GET", "https://github.com/acme/app.git/info/refs?service=git-upload-pack", "github"],
	["POST", "https://github.com/acme/app/git-receive-pack", "github"],
	["POST", "https://github.com/acme/app.git/git-upload-pack", "github"],
	["GET", "https://github.com/acme/app/info/refs?service=git-upload-pack", "github"],
	["GET", "https://github.com/acme/app/info/refs?service=git-receive-pack", "github"],
	["POST", "https://github.com/acme/app/git-upload-pack", "github"],
	["POST", "https://github.com/acme/app.git/git-receive-pack", "github"],
	["GET", "https://GitHub.com./acme/app/info/refs?service=git-upload-pack", "github"],
	["GET", "https://registry.npmjs.org/zod", "none"],
	["GET", "https://registry.npmjs.org/@types%2fnode", "none"],
	["GET", "https://pypi.org/simple/requests/", "none"],
	["GET", "https://files.pythonhosted.org/packages/x", "none"],
	["HEAD", "https://example.org/x", "none"],
	["GET", "https://Example.ORG/x", "none"],
]

const refused: [string, string][] = [
	// only git's smart-HTTP requests reach github.com (final review m5)
	["GET", "https://github.com/acme/app"],
	["GET", "https://github.com/acme/app.git"],
	["GET", "https://GitHub.com./acme/app"],
	["GET", "https://github.com/acme/app/info/refs"],
	["GET", "https://github.com/acme/app/info/refs?service=git-other"],
	["GET", "https://github.com/acme/app/info/refs?service=git-upload-pack&x=1"],
	["GET", "https://github.com/acme/app/info/refs?x=1&service=git-upload-pack"],
	["GET", "https://github.com/acme/app/info/refs?"],
	["POST", "https://github.com/acme/app/info/refs?service=git-upload-pack"],
	["HEAD", "https://github.com/acme/app/info/refs?service=git-upload-pack"],
	["GET", "https://github.com/acme/app/git-upload-pack"],
	["PUT", "https://github.com/acme/app/git-receive-pack"],
	["POST", "https://github.com/acme/app/git-upload-pack?x=1"],
	["POST", "https://github.com/acme/app/git-receive-pack/x"],
	["POST", "https://github.com/acme/app/info/lfs/objects/batch"],
	["GET", "https://github.com/acme/app/archive/refs/heads/main.zip"],
	["GET", "https://github.com/acme/app/raw/main/README.md"],
	["POST", "https://github.com/acme/app/issues"],
	["GET", "https://github.com/acme/app.git/info/refs?service=git-upload-pack&x=a//b..c%2f"],
	["POST", "https://github.com/acme/app-other/git-upload-pack"],
	["POST", "https://github.com/acme/App/git-upload-pack"],
	["GET", "http://github.com/acme/app"],
	["GET", "https://github.com:8443/acme/app"],
	["GET", "https://github.com/acme/app-other"],
	["GET", "https://github.com/acme/app.gitx"],
	["GET", "https://github.com/acme/app/../other"],
	["GET", "https://github.com/acme/app/%2e%2e/other"],
	["GET", "https://github.com/acme/app/%2E%2E/other"],
	["GET", "https://github.com/acme/app/.%2e/other"],
	["GET", "https://github.com/acme/app/./x"],
	["GET", "https://github.com/acme/app%2fother"],
	["GET", "https://github.com/acme/app%2Fother"],
	["GET", "https://github.com/acme/app//x"],
	["GET", "https://github.com//acme/app"],
	["GET", "https://github.com/acme/app\\..\\other"],
	["GET", "https://github.com/Acme/App"],
	["GET", "https://github.com/acme/App"],
	["GET", "https://github.com/"],
	["GET", "https://github.com/acme"],
	["GET", "https://user@github.com/acme/app"],
	["GET", "https://" + ["user", "pw"].join(":") + "@github.com/acme/app"],
	["GET", "https://github.com@evil.test/acme/app"],
	["GET", "https://gateway.ai.cloudflare.com/v1/acct/gw2/anthropic/x"],
	["POST", "https://gateway.ai.cloudflare.com/v1/acct/gw/openai/v1/chat/completions"],
	["POST", "https://gateway.ai.cloudflare.com/v1/acct/gw/anthropicx/v1/messages"],
	["POST", "https://gateway.ai.cloudflare.com/v1/acct/gw/anthropic"],
	["GET", "https://gateway.ai.cloudflare.com/v1/acct/gw"],
	["GET", "https://gateway.ai.cloudflare.com/v1/other/gw/anthropic/x"],
	["POST", "https://gateway.ai.cloudflare.com/v1/acct/gw/anthropic/../openai/x"],
	["POST", "https://gateway.ai.cloudflare.com/v1/acct/gw/anthropic/%2e%2e/openai/x"],
	["POST", "https://gateway.ai.cloudflare.com/v1/acct/gw/anthropic//v1/messages"],
	["POST", "http://gateway.ai.cloudflare.com/v1/acct/gw/anthropic/v1/messages"],
	["POST", "https://registry.npmjs.org/zod"],
	["PUT", "https://registry.npmjs.org/zod"],
	["POST", "https://example.org/x"],
	["DELETE", "https://example.org/x"],
	["GET", "https://api.github.com/user"],
	["GET", "https://raw.githubusercontent.com/acme/app/main/x"],
	["GET", "https://evil.test/"],
	["GET", "https://evil.test/acme/app"],
	["GET", "https://github.com.evil.test/acme/app"],
	["GET", "ftp://github.com/acme/app"],
	["GET", "not a url"],
	["GET", ""],
	["GET", "//github.com/acme/app"],
	// the parser moves these to another path or host (review round 1)
	["GET", "https://github.com\\..\\x/acme/app"],
	["GET", "https://github.com/acme/app/.\t./other"],
	["GET", "https://github.com/acme/app/.\n./other/repo"],
	["POST", "https://gateway.ai.cloudflare.com/v1/acct/gw/anthropic/.\t./openai/x"],
	["GET", "https:github.com/acme/app"],
	["GET", "https://github.com\t/acme/app"],
]

describe("decide", () => {
	it.each(allowed)("allows %s %s with credential %s", (method, url, credential) => {
		expect(decide(method, url, policy)).toEqual({ allow: true, credential })
	})

	it.each(refused)("refuses %s %s", (method, url) => {
		const decision = decide(method, url, policy)
		expect(decision.allow).toBe(false)
		expect(decision).toHaveProperty("reason")
	})

	it("names the reason for key refusals", () => {
		expect(decide("GET", "http://github.com/acme/app", policy)).toMatchObject({ reason: expect.stringContaining("HTTPS") })
		expect(decide("GET", "https://github.com:8443/acme/app", policy)).toMatchObject({ reason: expect.stringContaining("443") })
		expect(decide("POST", "https://registry.npmjs.org/zod", policy)).toMatchObject({ reason: expect.stringContaining("GET") })
		expect(decide("GET", "https://evil.test/", policy)).toMatchObject({ reason: expect.stringContaining("not allowed") })
	})

	it("ignores a fragment", () => {
		expect(decide("GET", "https://github.com/acme/app/info/refs?service=git-upload-pack#frag", policy)).toEqual({ allow: true, credential: "github" })
	})

	it("matches the method case-insensitively", () => {
		expect(decide("get", "https://registry.npmjs.org/zod", policy)).toEqual({ allow: true, credential: "none" })
		expect(decide("post", "https://registry.npmjs.org/zod", policy).allow).toBe(false)
	})

	it("judges traversal on the path only, and allows only the exact service query", () => {
		expect(decide("GET", "https://github.com/acme/app.git/info/refs?service=git-receive-pack", policy)).toEqual({ allow: true, credential: "github" })
		expect(decide("GET", "https://github.com/acme/app.git/info/refs?service=git-upload-pack&x=a//b..c%2f", policy).allow).toBe(false)
	})

	it("refuses every GitHub path when the policy names no repository", () => {
		expect(decide("GET", "https://github.com/acme/app", { ...policy, repoPath: "" }).allow).toBe(false)
		expect(decide("GET", "https://github.com/", { ...policy, repoPath: "" }).allow).toBe(false)
	})

	it("never opens a credential host through the policy's own hosts", () => {
		const wide: Policy = { ...policy, allow: ["github.com", "gateway.ai.cloudflare.com"] }
		expect(decide("GET", "https://github.com/other/repo", wide).allow).toBe(false)
		expect(decide("GET", "https://github.com/acme/app", wide).allow).toBe(false)
		expect(decide("POST", "https://github.com/other/repo", wide).allow).toBe(false)
		expect(decide("GET", "https://gateway.ai.cloudflare.com/v1/acct/gw2/anthropic/x", wide).allow).toBe(false)
		expect(decide("POST", "https://github.com/acme/app/git-upload-pack", wide)).toEqual({ allow: true, credential: "github" })
	})
})

describe("isContainerCredentialHeader", () => {
	it("names the headers the container may not set, in any case (Copilot C3)", () => {
		for (const name of ["authorization", "Authorization", "proxy-authorization", "Proxy-Authorization", "x-api-key", "X-Api-Key", "cf-aig-authorization", "CF-AIG-Metadata", "cf-aig-"])
			expect(isContainerCredentialHeader(name), name).toBe(true)
	})
	it("leaves other headers alone", () => {
		for (const name of ["anthropic-version", "content-type", "x-api-key-id", "cf-ray", "aig-authorization", "user-agent"])
			expect(isContainerCredentialHeader(name), name).toBe(false)
	})
})
