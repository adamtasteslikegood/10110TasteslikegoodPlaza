import { describe, expect, it } from "vitest"
import worker, { CreateBody, RunBody, authorized, parseRoute } from "../src/index"
import type { Env } from "../src/types"

const SECRET = "s3cret-value"

type Call = { method: string; args: unknown[] }

// A fake namespace: records which Workspace method the router called.
function fakeEnv(calls: Call[] = []): Env {
  const record = (method: string, result: unknown) => async (...args: unknown[]) => {
    calls.push({ method, args })
    return result
  }
  const stub = {
    create: record("create", { state: "idle", run: 0, generation: 1 }),
    status: record("status", { state: "none", run: 0, generation: 0 }),
    startRun: record("startRun", { run: 1 }),
    events: record("events", { events: [], next: 0 }),
    stop: record("stop", { state: "stopped", run: 1, generation: 1 }),
    diff: record("diff", "diff text"),
    destroyWorkspace: record("destroyWorkspace", undefined),
  }
  return {
    WORKSPACE: { getByName: () => stub },
    RUNNER_CALLER_SECRET: SECRET,
    AI_GATEWAY_TOKEN: "t",
    GITHUB_TOKEN: "g",
    AI_GATEWAY_ACCOUNT_ID: "acct",
    AI_GATEWAY_ID: "gw",
    MODEL: "claude-sonnet-5-5",
  } as unknown as Env
}

function req(method: string, path: string, opts: { body?: unknown; raw?: string; auth?: string | null } = {}): Request {
  const headers = new Headers()
  const auth = opts.auth === undefined ? `Bearer ${SECRET}` : opts.auth
  if (auth !== null) headers.set("authorization", auth)
  const body = opts.raw ?? (opts.body === undefined ? undefined : JSON.stringify(opts.body))
  return new Request(`https://runner.example${path}`, { method, headers, body })
}

const call = (r: Request, calls: Call[] = []) => worker.fetch(r, fakeEnv(calls))

describe("authorized", () => {
  it("accepts only the exact bearer value", () => {
    expect(authorized(req("GET", "/"), SECRET)).toBe(true)
    expect(authorized(req("GET", "/", { auth: "bearer " + SECRET }), SECRET)).toBe(true)
    expect(authorized(req("GET", "/", { auth: null }), SECRET)).toBe(false)
    expect(authorized(req("GET", "/", { auth: "Bearer x" }), SECRET)).toBe(false)
    expect(authorized(req("GET", "/", { auth: "Bearer " + SECRET + "x" }), SECRET)).toBe(false)
    expect(authorized(req("GET", "/", { auth: "Bearer " + SECRET.slice(0, -1) }), SECRET)).toBe(false)
    expect(authorized(req("GET", "/", { auth: SECRET }), SECRET)).toBe(false)
    expect(authorized(req("GET", "/", { auth: "Basic " + SECRET }), SECRET)).toBe(false)
  })

  it("never authorizes when the secret is empty", () => {
    expect(authorized(req("GET", "/", { auth: "Bearer " }), "")).toBe(false)
  })
})

describe("fetch auth", () => {
  it("refuses a missing or wrong bearer with 401", async () => {
    for (const auth of [null, "Bearer x", "Bearer " + SECRET + "-longer"]) {
      const res = await call(req("GET", "/workspaces/a", { auth }))
      expect(res.status).toBe(401)
    }
  })

  it("checks auth before routing", async () => {
    expect((await call(req("GET", "/nowhere", { auth: null }))).status).toBe(401)
  })
})

describe("parseRoute", () => {
  const table: [string, string, string][] = [
    ["PUT", "/workspaces/ws1", "create"],
    ["GET", "/workspaces/ws1", "status"],
    ["POST", "/workspaces/ws1/runs", "run"],
    ["GET", "/workspaces/ws1/events", "events"],
    ["POST", "/workspaces/ws1/stop", "stop"],
    ["GET", "/workspaces/ws1/diff", "diff"],
    ["DELETE", "/workspaces/ws1", "delete"],
  ]
  it.each(table)("routes %s %s to %s", (method, path, action) => {
    expect(parseRoute(method, path)).toEqual({ name: "ws1", action })
  })

  it("rejects a bad workspace name with 400", () => {
    for (const name of ["A", "-a", "a-", "a_b", "a".repeat(64), "a%2Fb"]) {
      expect(parseRoute("GET", `/workspaces/${name}`)).toEqual({ error: 400 })
    }
    expect(parseRoute("GET", `/workspaces/${"a".repeat(63)}`)).toEqual({ name: "a".repeat(63), action: "status" })
    expect(parseRoute("GET", "/workspaces/a")).toEqual({ name: "a", action: "status" })
  })

  it("answers 404 for unknown paths and 405 for wrong methods", () => {
    for (const path of ["/", "/workspaces", "/workspaces/", "/workspaces/a/nope", "/workspaces/a/runs/1", "/other/a", "/workspaces/a/"]) {
      expect(parseRoute("GET", path)).toEqual({ error: 404 })
    }
    expect(parseRoute("POST", "/workspaces/a")).toEqual({ error: 405 })
    expect(parseRoute("GET", "/workspaces/a/runs")).toEqual({ error: 405 })
    expect(parseRoute("PUT", "/workspaces/a/events")).toEqual({ error: 405 })
    expect(parseRoute("GET", "/workspaces/a/stop")).toEqual({ error: 405 })
    expect(parseRoute("POST", "/workspaces/a/diff")).toEqual({ error: 405 })
  })

  it("answers 404 and 405 through fetch", async () => {
    expect((await call(req("GET", "/nope"))).status).toBe(404)
    expect((await call(req("POST", "/workspaces/a"))).status).toBe(405)
    expect((await call(req("GET", "/workspaces/A"))).status).toBe(400)
  })
})

describe("CreateBody", () => {
  const good = { repo: "https://github.com/owner/repo", branch: "feature/x" }

  it("accepts a valid body and defaults allow", () => {
    const parsed = CreateBody.parse(good)
    expect(parsed.repo).toBe(good.repo)
    expect(parsed.branch).toBe(good.branch)
    expect(CreateBody.parse({ ...good, allow: ["registry.npmjs.org"] }).allow).toEqual(["registry.npmjs.org"])
  })

  it("rejects each bad body", () => {
    const bad: unknown[] = [
      { ...good, repo: "http://github.com/owner/repo" },
      { ...good, repo: "https://gitlab.com/owner/repo" },
      { ...good, repo: "https://github.com/owner/repo.git" },
      { ...good, repo: "https://github.com/owner/repo?x=1" },
      { ...good, repo: "https://github.com/owner/repo/" },
      { ...good, repo: "https://github.com/owner" },
      { ...good, repo: "https://github.com/owner/repo/extra" },
      { ...good, repo: "https://github.com/owner/.." },
      { ...good, repo: "https://user@github.com/owner/repo" },
      { ...good, branch: "-x" },
      { ...good, branch: "" },
      { ...good, branch: "a".repeat(201) },
      { ...good, branch: "has space" },
      { ...good, branch: "semi;colon" },
      { ...good, allow: Array.from({ length: 21 }, (_, i) => `h${i}.example.com`) },
      { ...good, allow: ["https://example.com"] },
      { ...good, allow: ["example.com/path"] },
      { ...good, allow: ["example.com:443"] },
      { ...good, allow: ["*.example.com"] },
      { ...good, allow: [""] },
      { ...good, allow: "example.com" },
      { branch: "main" },
      { repo: good.repo },
      null,
      "text",
    ]
    for (const body of bad) expect(CreateBody.safeParse(body).success, JSON.stringify(body)).toBe(false)
  })

  it("accepts the limits: 200-char branch and 20 hosts", () => {
    expect(CreateBody.safeParse({ ...good, branch: "a".repeat(200) }).success).toBe(true)
    expect(CreateBody.safeParse({ ...good, allow: Array.from({ length: 20 }, (_, i) => `h${i}.example.com`) }).success).toBe(true)
  })

  it("is enforced through fetch with 400, and good input reaches the Workspace", async () => {
    expect((await call(req("PUT", "/workspaces/a", { body: { ...good, repo: "http://github.com/o/r" } }))).status).toBe(400)
    expect((await call(req("PUT", "/workspaces/a", { raw: "{not json" }))).status).toBe(400)
    const calls: Call[] = []
    const res = await call(req("PUT", "/workspaces/a", { body: good }), calls)
    expect(res.status).toBe(200)
    expect(calls).toEqual([{ method: "create", args: [good.repo, good.branch, []] }])
  })
})

describe("RunBody", () => {
  it("defaults maxTurns to 20 and fresh to false, and bounds maxTurns to 1-100", () => {
    expect(RunBody.parse({ prompt: "hi" })).toMatchObject({ prompt: "hi", maxTurns: 20, fresh: false })
    expect(RunBody.safeParse({ prompt: "hi", maxTurns: 1 }).success).toBe(true)
    expect(RunBody.safeParse({ prompt: "hi", maxTurns: 100 }).success).toBe(true)
    for (const maxTurns of [0, 101, 1.5, -1, "5"]) {
      expect(RunBody.safeParse({ prompt: "hi", maxTurns }).success, String(maxTurns)).toBe(false)
    }
    expect(RunBody.safeParse({ prompt: "hi", fresh: "yes" }).success).toBe(false)
  })
})

describe("run requests", () => {
  const run = (body: unknown, calls: Call[] = []) => call(req("POST", "/workspaces/a/runs", { body }), calls)

  it("answers 400 for an empty or blank prompt", async () => {
    for (const prompt of ["", "   \n\t", undefined, 5]) {
      expect((await run({ prompt })).status, String(prompt)).toBe(400)
    }
    expect((await call(req("POST", "/workspaces/a/runs", { raw: "nope" }))).status).toBe(400)
  })

  it("answers 413 at 131072 bytes and passes 131071", async () => {
    const calls: Call[] = []
    const ok = await run({ prompt: "a".repeat(131071) }, calls)
    expect(ok.status).toBe(202)
    expect(calls).toHaveLength(1)
    expect((await run({ prompt: "a".repeat(131072) })).status).toBe(413)
  })

  it("counts UTF-8 bytes, not characters", async () => {
    // "é" is 2 bytes: 65536 of them is 131072 bytes, 65535 plus "a" is 131071.
    expect((await run({ prompt: "é".repeat(65536) })).status).toBe(413)
    expect((await run({ prompt: "é".repeat(65535) + "a" })).status).toBe(202)
  })

  it("passes prompt, fresh and maxTurns to startRun", async () => {
    const calls: Call[] = []
    const res = await run({ prompt: "do it", fresh: true, maxTurns: 7 }, calls)
    expect(res.status).toBe(202)
    expect(await res.json()).toEqual({ run: 1 })
    expect(calls).toEqual([{ method: "startRun", args: ["do it", true, 7] }])
  })

  it("answers 413 for a body over the 1 MiB request cap", async () => {
    expect((await run({ prompt: "a", pad: "x".repeat(1024 * 1024) })).status).toBe(413)
  })
})

describe("events requests", () => {
  const events = (query: string, calls: Call[] = []) => call(req("GET", `/workspaces/a/events${query}`), calls)

  it("defaults after to 0 and passes a valid one through", async () => {
    const calls: Call[] = []
    expect((await events("", calls)).status).toBe(200)
    expect((await events("?after=12", calls)).status).toBe(200)
    expect(calls.map((c) => c.args)).toEqual([[0], [12]])
  })

  it("rejects a non-integer or negative after with 400", async () => {
    for (const q of ["?after=-1", "?after=1.5", "?after=abc", "?after=", "?after=1e3", "?after=0x10", "?after=99999999999999999999"]) {
      expect((await events(q)).status, q).toBe(400)
    }
  })
})

describe("routing to Workspace methods", () => {
  it("maps each action to its method", async () => {
    const cases: [string, string, string, number][] = [
      ["GET", "/workspaces/a", "status", 200],
      ["POST", "/workspaces/a/stop", "stop", 200],
      ["GET", "/workspaces/a/diff", "diff", 200],
      ["DELETE", "/workspaces/a", "destroyWorkspace", 204],
    ]
    for (const [method, path, expected, status] of cases) {
      const calls: Call[] = []
      const res = await call(req(method, path), calls)
      expect(res.status, path).toBe(status)
      expect(calls.map((c) => c.method)).toEqual([expected])
    }
  })

  it("serves the diff as text/plain", async () => {
    const res = await call(req("GET", "/workspaces/a/diff"))
    expect(res.headers.get("content-type")).toContain("text/plain")
    expect(await res.text()).toBe("diff text")
  })
})
