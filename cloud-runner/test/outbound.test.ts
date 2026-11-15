import { describe, expect, it } from "vitest"
import { refusal, withCredential } from "../src/outbound"
import type { Env } from "../src/types"

const env = { AI_GATEWAY_TOKEN: "gw-token-value", GITHUB_TOKEN: "gh-token-value" } as Env

const request = (headers: Record<string, string> = {}) =>
	new Request("https://example.test/x", { method: "POST", body: "hello", headers })

describe("withCredential", () => {
	it("gateway: removes x-api-key, sets the gateway headers, keeps other headers", async () => {
		const out = withCredential(request({ "x-api-key": "placeholder", "anthropic-version": "2023-06-01" }), "gateway", env)

		expect(out.headers.get("x-api-key")).toBeNull()
		expect(out.headers.get("cf-aig-authorization")).toBe("Bearer gw-token-value")
		expect(out.headers.get("cf-aig-skip-cache")).toBe("true")
		expect(out.headers.get("anthropic-version")).toBe("2023-06-01")
		expect(out.headers.get("authorization")).toBeNull()
		expect(await out.text()).toBe("hello")
	})

	it("gateway: replaces a cf-aig-authorization the container supplied", () => {
		const out = withCredential(request({ "cf-aig-authorization": "Bearer forged", "cf-aig-skip-cache": "false" }), "gateway", env)

		expect(out.headers.get("cf-aig-authorization")).toBe("Bearer gw-token-value")
		expect(out.headers.get("cf-aig-skip-cache")).toBe("true")
	})

	it("github: sets Basic x-access-token and no gateway headers", () => {
		const out = withCredential(request({ authorization: "Bearer forged" }), "github", env)

		expect(out.headers.get("authorization")).toBe(`Basic ${btoa("x-access-token:gh-token-value")}`)
		expect(out.headers.get("cf-aig-authorization")).toBeNull()
		expect(out.headers.get("cf-aig-skip-cache")).toBeNull()
	})

	it.each(["gateway", "github", "none"] as const)("%s: never follows a redirect", (credential) => {
		expect(withCredential(request(), credential, env).redirect).toBe("manual")
		expect(withCredential(new Request("https://example.test/x", { redirect: "follow" }), credential, env).redirect).toBe("manual")
	})

	it("none: adds no credential header", () => {
		const out = withCredential(request({ "x-api-key": "kept" }), "none", env)

		expect(out.headers.get("authorization")).toBeNull()
		expect(out.headers.get("cf-aig-authorization")).toBeNull()
		expect(out.headers.get("cf-aig-skip-cache")).toBeNull()
	})
})

describe("refusal", () => {
	it("answers 403 naming the host only", async () => {
		const response = refusal("https://evil.test/path?token=abc")

		expect(response.status).toBe(403)
		expect(await response.text()).toBe("evil.test is not reachable from this sandbox\n")
	})

	it("does not echo an unparseable URL", async () => {
		const response = refusal("not a url with secrets")

		expect(response.status).toBe(403)
		expect(await response.text()).not.toContain("secrets")
	})
})
