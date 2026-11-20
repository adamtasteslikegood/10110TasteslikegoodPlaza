import { describe, expect, it } from "vitest"
import { tokenFor } from "../src/tokens"

describe("tokenFor", () => {
	const one = { GITHUB_TOKEN: "old", GITHUB_TOKENS: '{"owner/repo":"new"}' }

	it("picks the token of the repository, whatever the case", () => {
		expect(tokenFor(one, "https://github.com/Owner/Repo")).toBe("new")
	})

	it("has no fallback to GITHUB_TOKEN once the map is set", () => {
		expect(tokenFor(one, "https://github.com/owner/other")).toBeUndefined()
	})

	it("uses GITHUB_TOKEN when the map is unset or empty (stage 1)", () => {
		expect(tokenFor({ GITHUB_TOKEN: "old" }, "https://github.com/a/b")).toBe("old")
		expect(tokenFor({ GITHUB_TOKEN: "old", GITHUB_TOKENS: "" }, "https://github.com/a/b")).toBe("old")
	})

	it("returns the empty GITHUB_TOKEN as is: no credential, not a refusal", () => {
		expect(tokenFor({ GITHUB_TOKEN: "" }, "https://github.com/a/b")).toBe("")
	})

	it("finds no token when the map is not a JSON object", () => {
		expect(tokenFor({ GITHUB_TOKEN: "old", GITHUB_TOKENS: "not json" }, "https://github.com/a/b")).toBeUndefined()
		expect(tokenFor({ GITHUB_TOKEN: "old", GITHUB_TOKENS: '["a/b"]' }, "https://github.com/a/b")).toBeUndefined()
		expect(tokenFor({ GITHUB_TOKEN: "old", GITHUB_TOKENS: "null" }, "https://github.com/a/b")).toBeUndefined()
	})

	it("finds no token when the value is not a non-empty string", () => {
		expect(tokenFor({ GITHUB_TOKEN: "old", GITHUB_TOKENS: '{"a/b":7}' }, "https://github.com/a/b")).toBeUndefined()
		expect(tokenFor({ GITHUB_TOKEN: "old", GITHUB_TOKENS: '{"a/b":""}' }, "https://github.com/a/b")).toBeUndefined()
	})

	it("does not read inherited properties of the map", () => {
		expect(tokenFor({ GITHUB_TOKEN: "old", GITHUB_TOKENS: "{}" }, "https://github.com/constructor/x")).toBeUndefined()
		expect(tokenFor(one, "https://github.com/__proto__")).toBeUndefined()
	})
})
