import { describe, expect, it } from "vitest"
import { inspectPush, policyFor, refusal, withCredential } from "../src/outbound"
import { checkPush, MAX_COMMAND_BYTES } from "../src/pushguard"
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

	it("gateway: drops every cf-aig- header and Authorization the container sent", () => {
		const out = withCredential(
			request({
				"cf-aig-custom-cost": '{"per_token_in":0}',
				"cf-aig-collect-log": "false",
				"CF-AIG-Metadata": '{"a":1}',
				"cf-aig-cache-ttl": "9999",
				authorization: "Bearer sk-ant-other-key",
				"anthropic-beta": "kept",
			}),
			"gateway",
			env,
		)

		expect(out.headers.get("cf-aig-custom-cost")).toBeNull()
		expect(out.headers.get("cf-aig-collect-log")).toBeNull()
		expect(out.headers.get("cf-aig-metadata")).toBeNull()
		expect(out.headers.get("cf-aig-cache-ttl")).toBeNull()
		expect(out.headers.get("authorization")).toBeNull()
		expect(out.headers.get("anthropic-beta")).toBe("kept")
		expect([...out.headers.keys()].filter((name) => name.startsWith("cf-aig-")).sort()).toEqual(["cf-aig-authorization", "cf-aig-skip-cache"])
	})

	it("github: sets Basic x-access-token and no gateway headers", () => {
		const out = withCredential(request({ authorization: "Bearer forged" }), "github", env)

		expect(out.headers.get("authorization")).toBe(`Basic ${btoa("x-access-token:gh-token-value")}`)
		expect(out.headers.get("cf-aig-authorization")).toBeNull()
		expect(out.headers.get("cf-aig-skip-cache")).toBeNull()
	})

	it("github: an empty token adds no Authorization and drops the container's", () => {
		const out = withCredential(request({ authorization: "Bearer forged" }), "github", { ...env, GITHUB_TOKEN: "" })

		expect(out.headers.get("authorization")).toBeNull()
		expect(out.headers.get("cf-aig-authorization")).toBeNull()
	})

	it.each(["gateway", "github", "none"] as const)("%s: never follows a redirect", (credential) => {
		expect(withCredential(request(), credential, env).redirect).toBe("manual")
		expect(withCredential(new Request("https://example.test/x", { redirect: "follow" }), credential, env).redirect).toBe("manual")
	})

	it("none: adds no credential header", () => {
		const out = withCredential(request({ accept: "kept" }), "none", env)

		expect(out.headers.get("authorization")).toBeNull()
		expect(out.headers.get("cf-aig-authorization")).toBeNull()
		expect(out.headers.get("cf-aig-skip-cache")).toBeNull()
		expect(out.headers.get("accept")).toBe("kept")
	})

	// Copilot C3: every credential kind drops what the container set before adding its own.
	const forged = {
		authorization: "Bearer forged",
		"Proxy-Authorization": "Basic forged",
		"x-api-key": "forged",
		"cf-aig-authorization": "Bearer forged",
		"CF-AIG-Metadata": '{"a":1}',
		"anthropic-version": "2023-06-01",
	}
	const sent = (out: Request) => Object.fromEntries([...out.headers].filter(([name]) => name !== "content-type"))

	it("gateway: strips every container credential header, then adds only its own", () => {
		expect(sent(withCredential(request(forged), "gateway", env))).toEqual({
			"anthropic-version": "2023-06-01",
			"cf-aig-authorization": "Bearer gw-token-value",
			"cf-aig-skip-cache": "true",
		})
	})

	it("github: strips every container credential header, then adds only its own", () => {
		expect(sent(withCredential(request(forged), "github", env))).toEqual({
			"anthropic-version": "2023-06-01",
			authorization: `Basic ${btoa("x-access-token:gh-token-value")}`,
		})
		expect(sent(withCredential(request(forged), "github", { ...env, GITHUB_TOKEN: "" }))).toEqual({ "anthropic-version": "2023-06-01" })
	})

	it("none: strips every container credential header and adds none", () => {
		expect(sent(withCredential(request(forged), "none", env))).toEqual({ "anthropic-version": "2023-06-01" })
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

// Copilot C11: a receive-pack request is read only as far as its command list,
// then forwarded with every byte it had. Bodies here are a few hundred bytes.
describe("inspectPush", () => {
	const encoder = new TextEncoder()
	const pkt = (payload: string) => (payload.length + 4).toString(16).padStart(4, "0") + payload
	const A = "a".repeat(40)
	const B = "b".repeat(40)
	const pushBody = (ref: string) => encoder.encode(pkt(`${A} ${B} ${ref}\0report-status agent=git/2`) + "0000" + "PACK" + "p".repeat(300))
	const url = "https://github.com/acme/app/git-receive-pack"
	const chunked = (data: Uint8Array, size: number) => {
		let at = 0
		return new ReadableStream<Uint8Array>({
			pull(controller) {
				if (at >= data.length) return controller.close()
				controller.enqueue(data.slice(at, at + size))
				at += size
			},
		})
	}
	const post = (body: BodyInit | null, headers: Record<string, string> = {}) => new Request(url, { method: "POST", body, headers })
	const forwarded = async (out: Request | Response) => {
		expect(out).toBeInstanceOf(Request)
		return new Uint8Array(await (out as Request).arrayBuffer())
	}

	it("forwards a push of the workspace branch with every byte, in order, read in small chunks", async () => {
		const data = pushBody("refs/heads/work")
		for (const size of [1, 7, 64, 1000]) {
			const out = await inspectPush(post(chunked(data, size), { "content-type": "application/x-git-receive-pack-request" }), "work")
			expect(await forwarded(out)).toEqual(data)
			expect((out as Request).headers.get("content-type")).toBe("application/x-git-receive-pack-request")
			expect((out as Request).method).toBe("POST")
		}
	})

	it("keeps a stated Content-Length", async () => {
		const data = pushBody("refs/heads/work")
		const out = await inspectPush(post(chunked(data, 13), { "content-length": String(data.length) }), "work")
		expect(await forwarded(out)).toEqual(data)
	})

	it("forwards git's auth probe, a body of one flush", async () => {
		const out = await inspectPush(post("0000"), "work")
		expect(new TextDecoder().decode(await forwarded(out))).toBe("0000")
	})

	it.each([
		["another branch", "refs/heads/main"],
		["a tag", "refs/tags/v1"],
	])("refuses %s with 403 and does not forward", async (_name, ref) => {
		const out = await inspectPush(post(chunked(pushBody(ref), 16)), "work")
		expect(out).toBeInstanceOf(Response)
		expect((out as Response).status).toBe(403)
		expect(await (out as Response).text()).toContain("workspace branch")
	})

	it("refuses a compressed body, which it cannot read", async () => {
		const out = await inspectPush(post(pushBody("refs/heads/work"), { "content-encoding": "gzip" }), "work")
		expect((out as Response).status).toBe(403)
	})

	it("refuses an invalid Content-Length, a missing body, and a workspace with no branch", async () => {
		for (const length of ["abc", "-1", "1.5", ""]) {
			const request = post(pushBody("refs/heads/work"))
			const headers = new Headers(request.headers)
			headers.set("content-length", length)
			expect(((await inspectPush(new Request(request, { headers }), "work")) as Response).status).toBe(403)
		}
		expect(((await inspectPush(post(null), "work")) as Response).status).toBe(403)
		expect(((await inspectPush(post(pushBody("refs/heads/work")), "")) as Response).status).toBe(403)
	})

	// Copilot round 3, E5: the parser's buffer never grows past the command-section cap,
	// whatever the chunk sizes, and reading stops once the cap is reached.
	describe("bounded head (Copilot E5)", () => {
		// checkPush, recording the length of every head it is asked about.
		const watched = () => {
			const seen: number[] = []
			const check: typeof checkPush = (head, branch, ended) => {
				seen.push(head.length)
				return checkPush(head, branch, ended)
			}
			return { seen, check }
		}
		const PACK_BYTES = 4 * 1024 * 1024
		// Byte-for-byte, compared by length and SHA-256: a deep compare of 4 MiB is too slow.
		const same = async (a: Uint8Array, b: Uint8Array) => {
			const hex = async (x: Uint8Array) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", x))].join(",")
			expect(a.length).toBe(b.length)
			expect(await hex(a)).toBe(await hex(b))
		}
		const withPack = () => {
			const commands = encoder.encode(pkt(`${A} ${B} refs/heads/work\0report-status agent=git/2`) + "0000")
			const data = new Uint8Array(commands.length + PACK_BYTES)
			data.set(commands)
			for (let i = commands.length; i < data.length; i += 1) data[i] = i % 251
			return data
		}
		// A finite stream that counts how many bytes were pulled from it.
		const counted = (data: Uint8Array, size: number) => {
			const pulled = { bytes: 0 }
			let at = 0
			const stream = new ReadableStream<Uint8Array>({
				pull(controller) {
					if (at >= data.length) return controller.close()
					const part = data.slice(at, at + size)
					at += size
					pulled.bytes += part.length
					controller.enqueue(part)
				},
			})
			return { stream, pulled }
		}

		it("forwards one chunk of commands plus several MiB of pack byte for byte, the head kept within the cap", async () => {
			const data = withPack()
			const { seen, check } = watched()
			const out = await inspectPush(post(chunked(data, data.length)), "work", check)
			expect(seen.length).toBeGreaterThan(0)
			expect(Math.max(...seen)).toBeLessThanOrEqual(MAX_COMMAND_BYTES)
			await same(await forwarded(out), data)
		})

		it("keeps the head within the cap for large chunks under a stated Content-Length", async () => {
			const data = withPack()
			const { seen, check } = watched()
			const out = await inspectPush(post(chunked(data, 100_000), { "content-length": String(data.length) }), "work", check)
			expect(seen.length).toBeGreaterThan(0)
			expect(Math.max(...seen)).toBeLessThanOrEqual(MAX_COMMAND_BYTES)
			await same(await forwarded(out), data)
		})

		it("still reads a command list split across many small chunks", async () => {
			const commands = pkt(`${A} ${B} refs/heads/work\0report-status agent=git/2`) + pkt(`${B} ${A} refs/heads/work`)
			const data = encoder.encode(commands + "0000" + "PACK" + "p".repeat(300))
			const { seen, check } = watched()
			const out = await inspectPush(post(chunked(data, 3)), "work", check)
			expect(seen.length).toBeGreaterThan(30)
			expect(await forwarded(out)).toEqual(data)
		})

		it("refuses a command list with no flush within the cap and stops reading there", async () => {
			const line = pkt(`${A} ${B} refs/heads/work`)
			const lines = Math.ceil((MAX_COMMAND_BYTES * 2) / line.length)
			const data = encoder.encode(pkt(`${A} ${B} refs/heads/work\0report-status`) + line.repeat(lines))
			const { stream, pulled } = counted(data, 1000)
			const { seen, check } = watched()
			const out = await inspectPush(post(stream), "work", check)
			expect(out).toBeInstanceOf(Response)
			expect((out as Response).status).toBe(403)
			expect(seen.length).toBeGreaterThan(0)
			expect(Math.max(...seen)).toBeLessThanOrEqual(MAX_COMMAND_BYTES)
			expect(pulled.bytes).toBeLessThan(MAX_COMMAND_BYTES + 2 * 1000)
		})
	})
})

describe("policyFor", () => {
	const policyEnv = { AI_GATEWAY_ACCOUNT_ID: "acct", AI_GATEWAY_ID: "gw" } as Env

	it("reads the workspace branch from props, and has none without it (Copilot C11)", () => {
		expect(policyFor({ repoPath: "/acme/app", branch: "work", allow: [] }, policyEnv)).toEqual({ gatewayPath: "/v1/acct/gw", repoPath: "/acme/app", branch: "work", allow: [] })
		expect(policyFor(undefined, policyEnv)).toEqual({ gatewayPath: "/v1/acct/gw", repoPath: "", branch: "", allow: [] })
		expect(policyFor({ repoPath: "/acme/app", allow: [] }, policyEnv).branch).toBe("")
	})
})
