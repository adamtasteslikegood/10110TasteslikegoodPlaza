import { describe, expect, it } from "vitest"
import worker from "../src/index"
import { CreateBody, ExecBody, MAX_EXEC_ARGS, RunBody, authorized, parseRoute } from "../src/router"
import type { Env } from "../src/types"

const SECRET = "s3cret-value"

type Call = { method: string; args: unknown[] }

type Results = Partial<Record<"create" | "status" | "startRun" | "events" | "stop" | "diff" | "destroyWorkspace" | "replaceInstance" | "exec", unknown>>

// A fake namespace: records which Workspace method the router called, and
// answers with `results` where given.
function fakeEnv(calls: Call[] = [], results: Results = {}, vars: Partial<Env> = {}): Env {
  const record = (method: keyof Results, result: unknown) => async (...args: unknown[]) => {
    calls.push({ method, args })
    return method in results ? results[method] : result
  }
  const stub = {
    create: record("create", { status: { state: "idle", run: 0, generation: 1 } }),
    status: record("status", { state: "none", run: 0, generation: 0 }),
    startRun: record("startRun", { run: 1 }),
    events: record("events", { events: [], next: 0 }),
    stop: record("stop", { state: "stopped", run: 1, generation: 1 }),
    diff: record("diff", { ok: true, text: "diff text" }),
    destroyWorkspace: record("destroyWorkspace", undefined),
    replaceInstance: record("replaceInstance", { state: "idle", run: 0, generation: 1 }),
    exec: record("exec", { exitCode: 0, stdout: "out", stderr: "" }),
  }
  return {
    WORKSPACE: { getByName: () => stub },
    RUNNER_CALLER_SECRET: SECRET,
    AI_GATEWAY_TOKEN: "t",
    GITHUB_TOKEN: "g",
    AI_GATEWAY_ACCOUNT_ID: "acct",
    AI_GATEWAY_ID: "gw",
    MODEL: "claude-sonnet-5-5",
    ...vars,
  } as unknown as Env
}

function req(method: string, path: string, opts: { body?: unknown; raw?: string; auth?: string | null } = {}): Request {
  const headers = new Headers()
  const auth = opts.auth === undefined ? `Bearer ${SECRET}` : opts.auth
  if (auth !== null) headers.set("authorization", auth)
  const body = opts.raw ?? (opts.body === undefined ? undefined : JSON.stringify(opts.body))
  return new Request(`https://runner.example${path}`, { method, headers, body })
}

const call = (r: Request, calls: Call[] = [], results: Results = {}) => worker.fetch(r, fakeEnv(calls, results))

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

  it("answers 405 for a method named like an Object.prototype key", () => {
    for (const method of ["constructor", "toString", "__proto__", "hasOwnProperty", "valueOf"]) {
      expect(parseRoute(method, "/workspaces/a"), method).toEqual({ error: 405 })
      expect(parseRoute(method, "/workspaces/a/runs"), method).toEqual({ error: 405 })
    }
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
      // IP literals and single-label names (final review m2)
      { ...good, allow: ["127.0.0.1"] },
      { ...good, allow: ["169.254.169.254"] },
      { ...good, allow: ["10.0.0.1"] },
      { ...good, allow: ["0x7f.1"] },
      { ...good, allow: ["example.0x10"] },
      { ...good, allow: ["example.123"] },
      { ...good, allow: ["::1"] },
      { ...good, allow: ["[::1]"] },
      { ...good, allow: ["[fd00::1]"] },
      { ...good, allow: ["localhost"] },
      { ...good, allow: ["LOCALHOST"] },
      { ...good, allow: ["internal"] },
      { branch: "main" },
      { repo: good.repo },
      null,
      "text",
    ]
    for (const body of bad) expect(CreateBody.safeParse(body).success, JSON.stringify(body)).toBe(false)
  })

  it("accepts dotted names, a leading digit in a label included", () => {
    for (const host of ["example.com", "a.b.example.org", "1password.com", "xn--bcher-kva.example", "x1.io"]) {
      expect(CreateBody.safeParse({ ...good, allow: [host] }).success, host).toBe(true)
    }
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
  it("takes an optional conversation key of letters, digits and dashes, 1 to 128 long", () => {
    expect(RunBody.parse({ prompt: "p" }).conversation).toBeUndefined()
    for (const conversation of ["a", "Abc-123", "x".repeat(128)]) {
      expect(RunBody.safeParse({ prompt: "p", conversation }).success, conversation).toBe(true)
    }
    for (const conversation of ["bad key!", "", "x".repeat(129), "a_b", "a/b", 1]) {
      expect(RunBody.safeParse({ prompt: "p", conversation }).success, String(conversation)).toBe(false)
    }
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

  it("passes prompt, fresh, maxTurns and the conversation key to startRun", async () => {
    const calls: Call[] = []
    const res = await run({ prompt: "do it", fresh: true, maxTurns: 7 }, calls)
    expect(res.status).toBe(202)
    expect(await res.json()).toEqual({ run: 1 })
    expect(calls).toEqual([{ method: "startRun", args: ["do it", true, 7, undefined] }])

    const keyed: Call[] = []
    await run({ prompt: "do it", conversation: "k-1" }, keyed)
    expect(keyed).toEqual([{ method: "startRun", args: ["do it", false, 20, "k-1"] }])
  })

  it("answers 413 for a body over the 1 MiB request cap", async () => {
    expect((await run({ prompt: "a", pad: "x".repeat(1024 * 1024) })).status).toBe(413)
  })

  it("answers 400 for a prompt with a NUL", async () => {
    const calls: Call[] = []
    expect((await run({ prompt: "before\u0000after" }, calls)).status).toBe(400)
    expect(calls).toEqual([])
    expect(RunBody.safeParse({ prompt: "a\0" }).success).toBe(false)
  })

  it("stops reading a body with no content-length at the cap", async () => {
    // FINITE on purpose: 64 chunks of 64 KiB (4 MiB). An endless stream here once grew the
    // test runner to 23 GB and took the machine down while the cap was not yet implemented.
    let pulled = 0
    const oversized = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulled += 1
        if (pulled > 64) return controller.close()
        controller.enqueue(new Uint8Array(64 * 1024).fill(0x20))
      },
    })
    const request = new Request("https://runner.example/workspaces/a/runs", {
      method: "POST",
      headers: { authorization: `Bearer ${SECRET}` },
      body: oversized,
    })
    expect(request.headers.get("content-length")).toBeNull()
    expect((await call(request)).status).toBe(413)
    expect(pulled).toBeLessThan(40)
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

describe("Workspace answers", () => {
  const good = { repo: "https://github.com/owner/repo", branch: "main" }
  const status = { state: "idle", run: 0, generation: 1, repo: good.repo, branch: good.branch }

  it("create: 200 with the Status, 409 on conflict, 502 with cloneError when the clone fails", async () => {
    const ok = await call(req("PUT", "/workspaces/a", { body: good }), [], { create: { status } })
    expect(ok.status).toBe(200)
    expect(await ok.json()).toEqual(status)

    const conflict = await call(req("PUT", "/workspaces/a", { body: good }), [], { create: "conflict" })
    expect(conflict.status).toBe(409)
    expect(await conflict.text()).toBe("The workspace exists with another repo, branch or host list\n")

    const none = { state: "none", run: 0, generation: 1 }
    const failed = await call(req("PUT", "/workspaces/a", { body: good }), [], { create: { status: none, cloneError: "fatal: not found" } })
    expect(failed.status).toBe(502)
    expect(await failed.json()).toEqual({ ...none, cloneError: "fatal: not found" })
  })

  it("create: 422 and no workspace when no GitHub token is configured for the repository", async () => {
    const calls: Call[] = []
    const env = fakeEnv(calls, {}, { GITHUB_TOKENS: '{"other/repo":"secret-token-value"}' })
    const res = await worker.fetch(req("PUT", "/workspaces/a", { body: good }), env)
    expect(res.status).toBe(422)
    const text = await res.text()
    expect(text).toBe("No GitHub token is configured for this repository\n")
    expect(text).not.toContain("secret-token-value")
    expect(calls).toEqual([])

    const mapped = fakeEnv(calls, { create: { status } }, { GITHUB_TOKENS: '{"owner/repo":"t"}' })
    expect((await worker.fetch(req("PUT", "/workspaces/a", { body: good }), mapped)).status).toBe(200)
    expect(calls).toHaveLength(1)
  })

  it("create: an empty GITHUB_TOKEN is no token to send, not a refusal", async () => {
    const calls: Call[] = []
    const res = await worker.fetch(req("PUT", "/workspaces/a", { body: good }), fakeEnv(calls, {}, { GITHUB_TOKEN: "" }))
    expect(res.status).toBe(200)
    expect(calls).toHaveLength(1)
  })

  it("run: 202 with the run number, 409 when busy, 404 when the workspace is missing", async () => {
    const run = (result: unknown) => call(req("POST", "/workspaces/a/runs", { body: { prompt: "hi" } }), [], { startRun: result })
    const started = await run({ run: 3 })
    expect(started.status).toBe(202)
    expect(await started.json()).toEqual({ run: 3 })
    expect((await run("busy")).status).toBe(409)
    expect((await run("missing")).status).toBe(404)
    const diverged = await run("diverged")
    expect(diverged.status).toBe(412)
    expect(await diverged.text()).toBe("The clone cannot be fast-forwarded to the branch on GitHub\n")
    const unfetched = await run({ fetchError: "could not read from remote" })
    expect(unfetched.status).toBe(502)
    expect(await unfetched.text()).not.toContain("could not read")
  })

  it("status of a workspace never created: 200 with state none", async () => {
    const res = await call(req("GET", "/workspaces/a"), [], { status: { state: "none", run: 0, generation: 0 } })
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ state: "none", run: 0, generation: 0 })
  })

  it("events, stop and diff of a workspace never created: 404", async () => {
    expect((await call(req("GET", "/workspaces/a/events?after=0"), [], { events: "missing" })).status).toBe(404)
    expect((await call(req("POST", "/workspaces/a/stop"), [], { stop: "missing" })).status).toBe(404)
    expect((await call(req("GET", "/workspaces/a/diff"), [], { diff: "missing" })).status).toBe(404)
  })

  it("stop: 409 with a clear message when the task could not be stopped", async () => {
    const res = await call(req("POST", "/workspaces/a/stop"), [], { stop: "still-running" })
    expect(res.status).toBe(409)
    expect(await res.text()).toContain("could not be stopped")
  })

  it("diff: 502 with the error text when git fails", async () => {
    const res = await call(req("GET", "/workspaces/a/diff"), [], { diff: { ok: false, text: "fatal: not a git repository" } })
    expect(res.status).toBe(502)
    expect(res.headers.get("content-type")).toContain("text/plain")
    expect(await res.text()).toBe("fatal: not a git repository")
  })

  it("an error thrown by the Workspace answers 500", async () => {
    const env = fakeEnv()
    const stub = env.WORKSPACE.getByName("a") as unknown as { status: () => Promise<unknown> }
    stub.status = async () => {
      throw new Error("boom")
    }
    expect((await worker.fetch(req("GET", "/workspaces/a"), env)).status).toBe(500)
  })
})

describe("test-only routes", () => {
  const enabled = { ALLOW_TEST_ROUTES: "1" }
  const callWith = (r: Request, vars: Partial<Env>, calls: Call[] = [], results: Results = {}) => worker.fetch(r, fakeEnv(calls, results, vars))

  it("parseRoute knows them only when enabled", () => {
    expect(parseRoute("POST", "/workspaces/a/replace-instance")).toEqual({ error: 404 })
    expect(parseRoute("POST", "/workspaces/a/exec")).toEqual({ error: 404 })
    expect(parseRoute("POST", "/workspaces/a/replace-instance", true)).toEqual({ name: "a", action: "replace-instance" })
    expect(parseRoute("POST", "/workspaces/a/exec", true)).toEqual({ name: "a", action: "exec" })
    expect(parseRoute("GET", "/workspaces/a/exec", true)).toEqual({ error: 405 })
  })

  it("answer 404 when ALLOW_TEST_ROUTES is unset or not \"1\", and reach no Workspace method", async () => {
    for (const vars of [{}, { ALLOW_TEST_ROUTES: "" }, { ALLOW_TEST_ROUTES: "true" }, { ALLOW_TEST_ROUTES: "0" }]) {
      const calls: Call[] = []
      expect((await callWith(req("POST", "/workspaces/a/replace-instance"), vars, calls)).status).toBe(404)
      expect((await callWith(req("POST", "/workspaces/a/exec", { body: { argv: ["true"] } }), vars, calls)).status).toBe(404)
      expect(calls).toEqual([])
    }
  })

  it("still need the bearer when enabled", async () => {
    expect((await callWith(req("POST", "/workspaces/a/exec", { body: { argv: ["true"] }, auth: null }), enabled)).status).toBe(401)
    expect((await callWith(req("POST", "/workspaces/a/replace-instance", { auth: "Bearer x" }), enabled)).status).toBe(401)
  })

  it("replace-instance: 200 with the Status, 404 for a missing workspace", async () => {
    const calls: Call[] = []
    const res = await callWith(req("POST", "/workspaces/a/replace-instance"), enabled, calls)
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ state: "idle", run: 0, generation: 1 })
    expect(calls).toEqual([{ method: "replaceInstance", args: [] }])
    expect((await callWith(req("POST", "/workspaces/a/replace-instance"), enabled, [], { replaceInstance: "missing" })).status).toBe(404)
  })

  it("exec: passes argv, answers the result, 404 for a missing workspace", async () => {
    const calls: Call[] = []
    const res = await callWith(req("POST", "/workspaces/a/exec", { body: { argv: ["git", "status"] } }), enabled, calls)
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ exitCode: 0, stdout: "out", stderr: "" })
    expect(calls).toEqual([{ method: "exec", args: [["git", "status"], false] }])
    expect((await callWith(req("POST", "/workspaces/a/exec", { body: { argv: ["true"] } }), enabled, [], { exec: "missing" })).status).toBe(404)
  })

  it("exec: runs as root only when the body says so (PLZG-311)", async () => {
    const calls: Call[] = []
    expect((await callWith(req("POST", "/workspaces/a/exec", { body: { argv: ["id"], root: true } }), enabled, calls)).status).toBe(200)
    expect((await callWith(req("POST", "/workspaces/a/exec", { body: { argv: ["id"], root: false } }), enabled, calls)).status).toBe(200)
    expect(calls).toEqual([
      { method: "exec", args: [["id"], true] },
      { method: "exec", args: [["id"], false] },
    ])
  })

  it("exec: answers 400 for a bad argv", async () => {
    for (const body of [{}, { argv: [] }, { argv: "ls" }, { argv: [1] }, { argv: ["a\0b"] }, { argv: Array(MAX_EXEC_ARGS + 1).fill("x") }, { argv: ["id"], root: "yes" }]) {
      const calls: Call[] = []
      expect((await callWith(req("POST", "/workspaces/a/exec", { body }), enabled, calls)).status, JSON.stringify(body).slice(0, 40)).toBe(400)
      expect(calls).toEqual([])
    }
    expect(ExecBody.safeParse({ argv: Array(MAX_EXEC_ARGS).fill("x") }).success).toBe(true)
    expect(ExecBody.safeParse({ argv: ["x".repeat(128 * 1024)] }).success).toBe(false)
  })
})
