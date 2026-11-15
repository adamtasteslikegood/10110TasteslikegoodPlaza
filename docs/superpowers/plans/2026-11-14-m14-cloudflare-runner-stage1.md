# M14 Cloudflare Runner, Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Worker on Cloudflare that runs Claude Code on one GitHub branch inside a
sandbox container, drivable with `curl`, with no change to the bridge.

**Architecture:** A Worker authenticates the caller and routes to one Durable Object per
workspace. The object owns a container (clone of one repository), a numbered event log
in its own SQLite, and a snapshot id. Every outbound request from the container goes
through a Worker entrypoint that allows or refuses it and adds credentials.

**Tech Stack:** TypeScript, Wrangler 4, `@cloudflare/sandbox` 1.0.x (`Files`), Durable
Objects with SQLite storage, Containers (`durable_object` scheduling policy), zod,
vitest with `@cloudflare/vitest-pool-workers`, Claude Code CLI pinned in the image.

**Spec:** `docs/superpowers/specs/2026-11-14-m14-cloudflare-runner-design.md` (approved
2026-11-14). Stage 2 (§6.7) is out of scope here.

**Reference implementation:** Cloudflare's guide
`developers.cloudflare.com/sandbox/get-started/build-a-coding-agent-runner/` and
`/sandbox/coding-agents/claude-code/`. Start from its `Dockerfile`, `wrangler.jsonc`,
`Outbound` and `AgentSandbox` code; this plan states only what differs. Where a method
name here disagrees with the installed 1.0.x types, the types win.

## Global Constraints

- No credential inside the container: not in env, files, clone URL or arguments.
- The container starts with Internet access off. HTTPS only; plain HTTP is refused.
- No file under `bridge/` or `scripts/` changes. All code lives in `cloud-runner/`.
- The admin Cloudflare credential is used only for `wrangler` commands from this
  session. It is never written into the Worker, a file in the repo, or a prompt.
- Secrets are never printed. Local secret files live in `cloud-runner/.dev/` (git-ignored).
- Worker name `plaza-cloud-runner-dev`; `workers_dev: true`; development only.
- AI Gateway: the existing `my-cf-agent-gateway` (authenticated, spend limits of $10
  and $15 a day already set). Do not change its settings. It has response caching on
  (300 s), so the Worker sends `cf-aig-skip-cache: true` on every model request.
- Model `claude-sonnet-5-5` (the bridge's `SONNET_MODEL`). Turn limit default 20.
- Instance `standard-1`. Idle stop after 15 minutes. Run check alarm every 60 s.
- Event log: last 10,000 events per workspace, each payload capped at 256 KiB (262144 bytes).
- Code style: keep the formatting of the Cloudflare guide's code. Conventional Commits; end each message with
  `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.

## Owner inputs needed before Task 7 (Tasks 1-6 need none)

1. Docker running on this machine (`docker info` fails today).
2. `npx wrangler login` done in `cloud-runner/`.
3. A gateway token with Run permission for `my-cf-agent-gateway`, and an Anthropic
   provider key stored in that gateway (or Unified Billing credits on it).
4. A GitHub test repository, and a fine-grained token on it with contents read/write.

## Review Focus

1. A request to `github.com` for a path that only starts like the workspace's
   repository (`/owner/repo-other`, `/owner/repo/../x`, different case) must be refused.
   (Task 2)
2. A second run while one is active answers 409 and does not disturb the first. (Task 5)
3. A container that stopped mid-run reports `lost`, and the next run is accepted. (Task 5)
4. `events?after=N` with N at or past the end returns an empty list and `next: N`; N
   older than the trimmed log returns from the oldest kept event. (Task 4)
5. A prompt of 128 KiB or more answers 413; an empty prompt answers 400. (Task 1)

---

## File structure

| File | Responsibility |
|---|---|
| `cloud-runner/package.json`, `tsconfig.json`, `vitest.config.ts`, `.gitignore` | Tooling; `npm test`, `npm run typecheck` |
| `cloud-runner/wrangler.jsonc`, `Dockerfile` | Deploy config and image, from the guide |
| `cloud-runner/src/index.ts` | Caller auth, route parsing, request validation |
| `cloud-runner/src/egress.ts` | Pure allow/refuse decision for one outbound request |
| `cloud-runner/src/outbound.ts` | `Outbound` entrypoint: calls `decide`, adds credentials, fetches |
| `cloud-runner/src/agent.ts` | Pure: Claude Code argv and env, result-event parsing |
| `cloud-runner/src/events.ts` | `EventLog` over the object's SQLite |
| `cloud-runner/src/workspace.ts` | `Workspace` Durable Object: container, runs, alarm, push, snapshot |
| `cloud-runner/test/*.test.ts` | One test file per source file above except `workspace.ts` |
| `cloud-runner/scripts/acceptance.mjs` | The spec §8 checks against a URL |
| `cloud-runner/README.md` | What it is, how to deploy, how to drive it |
| `docs/research/cloudflare-durable-objects/spike-c.md` | Evidence for spec §8 |
| `.github/workflows/ci.yml` | New job `Cloud Runner` running test and typecheck |

`workspace.ts` needs a real container, which the vitest pool does not provide. It is
covered by `wrangler dev` and the acceptance script (Task 7), so its logic that can be
pure is kept in `agent.ts`, `egress.ts` and `events.ts`.

## HTTP contract (all under `Authorization: Bearer <RUNNER_CALLER_SECRET>`)

| Route | Body | Answers |
|---|---|---|
| `PUT /workspaces/:name` | `{ repo, branch, allow?: string[] }` | 200 `Status`; 400 bad input; 409 exists with another repo or branch; 502 clone failed |
| `GET /workspaces/:name` | | 200 `Status` |
| `POST /workspaces/:name/runs` | `{ prompt, fresh?: boolean, maxTurns?: number }` | 202 `{ run }`; 409 busy; 400; 413; 404 no workspace |
| `GET /workspaces/:name/events?after=N` | | 200 `{ events: Event[], next: number }` |
| `POST /workspaces/:name/stop` | | 200 `Status` |
| `GET /workspaces/:name/diff` | | 200 text/plain |
| `DELETE /workspaces/:name` | | 204 |

`:name` matches `/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/`. `repo` is
`https://github.com/<owner>/<repo>` (no `.git`, no query). `branch` is 1-200 chars of
`[A-Za-z0-9._/-]`, not starting with `-`. `allow` entries are bare hostnames, at most 20.

```ts
export type RunState = "none" | "idle" | "running" | "succeeded" | "failed" | "stopped" | "lost"
export type Status = {
  state: RunState
  run: number            // 0 before the first run
  generation: number     // +1 each time a container instance is started
  repo?: string; branch?: string
  result?: string; error?: string
  pushed?: { commit: string }      // head of branch after the last successful push
  pushError?: string
  restored?: "snapshot" | "branch" // how the current instance got its files
  uncommittedLost?: boolean        // true when restored from branch after a previous instance
}
export type Event = {
  seq: number; run: number; generation: number; at: string  // ISO 8601
  type: string           // Claude Code's event `type`, or "runner" for runner notices
  payload: unknown       // the parsed line; { truncated: true, bytes } when over the cap
}
```

---

### Task 1: Scaffold, caller auth and request validation

**Files:**
- Create: `cloud-runner/package.json`, `tsconfig.json`, `vitest.config.ts`, `.gitignore`, `wrangler.jsonc`, `Dockerfile`, `src/index.ts`, `test/index.test.ts`
- Modify: `.github/workflows/ci.yml` (add job `Cloud Runner`: `npm ci`, `npm test`, `npm run typecheck` in `cloud-runner/`, Node 24, actions pinned as the other jobs pin them)

**Interfaces:**
- Produces: `parseRoute(method: string, pathname: string): Route | { error: 404 | 405 | 400 }` where
  `Route = { name: string; action: "create" | "status" | "run" | "events" | "stop" | "diff" | "delete" }`;
  `authorized(request: Request, secret: string): boolean` (constant-time compare of the bearer value);
  `CreateBody`, `RunBody` zod schemas with the limits in the HTTP contract;
  `Env` with `WORKSPACE: DurableObjectNamespace`, `RUNNER_CALLER_SECRET`, `AI_GATEWAY_TOKEN`, `GITHUB_TOKEN`, `AI_GATEWAY_ACCOUNT_ID`, `AI_GATEWAY_ID`, `MODEL`.
- `wrangler.jsonc`: as the guide's, with name `plaza-cloud-runner-dev`, class `Workspace`, binding `WORKSPACE`, `vars.AI_GATEWAY_ID = "my-cf-agent-gateway"`, `vars.MODEL = "claude-sonnet-5-5"`, `secrets.required = ["AI_GATEWAY_TOKEN", "GITHUB_TOKEN", "RUNNER_CALLER_SECRET"]`. `AI_GATEWAY_ACCOUNT_ID` is filled at deploy from a git-ignored `wrangler.dev.jsonc`, not committed.
- `Dockerfile`: the guide's, Claude Code pinned to the version the guide pins on the day of the build.

- [ ] **Step 1: Write failing tests** in `test/index.test.ts`:

```ts
it("refuses a missing or wrong bearer", ...)            // 401 for none, "Bearer x", and a secret of different length
it("routes each contract row", ...)                     // table of method+path -> action
it("rejects a bad workspace name with 400", ...)        // "A", "-a", "a_b", 64 chars
it("answers 404 for unknown paths and 405 for wrong methods", ...)
it("validates the create body", ...)                    // http:// repo, gitlab.com, repo with .git, branch "-x", 21 allow hosts -> all fail
it("answers 400 for an empty prompt and 413 at 131072 bytes", ...) // 131071 passes
```

- [ ] **Step 2:** Run `npm test` in `cloud-runner/`. Expected: FAIL, modules missing.
- [ ] **Step 3:** Implement `src/index.ts` (default export `fetch` that authorizes, parses, validates, and calls the method named for the action on `env.WORKSPACE.getByName(name)`; a stub `Workspace` class is enough for typecheck until Task 5).
- [ ] **Step 4:** `npm test` and `npm run typecheck`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(cloud-runner): scaffold worker with caller auth and request validation`.

### Task 2: Egress policy and the Outbound entrypoint

**Files:**
- Create: `cloud-runner/src/egress.ts`, `src/outbound.ts`, `test/egress.test.ts`

**Interfaces:**
- Produces:

```ts
export type Policy = { gatewayPath: string; repoPath: string; allow: string[] } // repoPath "/owner/repo"
export type Decision =
  | { allow: true; credential: "gateway" | "github" | "none" }
  | { allow: false; reason: string }
export function decide(method: string, url: URL, policy: Policy): Decision
```

- Rules, in order: not `https:` -> refuse. Port other than 443 -> refuse. Host compared
  lowercase with a trailing dot removed.
  `gateway.ai.cloudflare.com` and path equal to `gatewayPath` or under `gatewayPath + "/"` -> gateway.
  `github.com` and normalised path equal to `repoPath`, `repoPath + ".git"`, or under
  either followed by `/` -> github. The path is rejected if it contains `..`, `//`, `%2e`
  or `%2f` in any case; the owner/repo comparison is exact-case.
  `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org`, or a host in `allow` -> none, **GET and HEAD only**.
  Anything else -> refuse.
- `Outbound extends WorkerEntrypoint<Env>`: builds `Policy` from `this.ctx.props`
  (`{ repoPath, allow }`, set by the workspace when it registers the intercept) and env.
  gateway: delete `x-api-key`, set `cf-aig-authorization: Bearer <AI_GATEWAY_TOKEN>` and `cf-aig-skip-cache: true`.
  github: set `Authorization: Basic base64("x-access-token:" + GITHUB_TOKEN)`.
  refuse: 403, body `<host> is not reachable from this sandbox`.
  If the installed runtime gives an entrypoint no `props`, fall back to one intercept
  per allowed host with the policy read from the workspace through a binding; record
  which was used in the README.

- [ ] **Step 1: Write failing tests** in `test/egress.test.ts`, policy `{ gatewayPath: "/v1/acct/gw", repoPath: "/acme/app", allow: ["example.org"] }`:

```ts
// allowed
["POST", "https://gateway.ai.cloudflare.com/v1/acct/gw/anthropic/v1/messages", "gateway"]
["GET",  "https://github.com/acme/app.git/info/refs?service=git-upload-pack", "github"]
["POST", "https://github.com/acme/app/git-receive-pack", "github"]
["GET",  "https://GitHub.com./acme/app", "github"]
["GET",  "https://registry.npmjs.org/zod", "none"]
["HEAD", "https://example.org/x", "none"]
// refused
["GET",  "http://github.com/acme/app"]                       // plain http
["GET",  "https://github.com:8443/acme/app"]                 // port
["GET",  "https://github.com/acme/app-other"]                // prefix only
["GET",  "https://github.com/acme/app/../other"]             // traversal (test the raw string, before URL normalises it, and "%2e%2e")
["GET",  "https://github.com/Acme/App"]                      // case
["GET",  "https://gateway.ai.cloudflare.com/v1/acct/gw2/x"]  // other gateway
["GET",  "https://gateway.ai.cloudflare.com/v1/other/gw/x"]  // other account
["POST", "https://registry.npmjs.org/zod"]                   // write to a registry
["POST", "https://example.org/x"]
["GET",  "https://api.github.com/user"]
["GET",  "https://evil.test/"]
```

- [ ] **Step 2:** `npm test -- egress`. Expected: FAIL.
- [ ] **Step 3:** Implement `decide` (take the raw request URL string as well as the parsed `URL` if needed to see `..` before normalisation; adjust the signature in both this task and Task 5 if so) and `Outbound`.
- [ ] **Step 4:** `npm test` and typecheck. Expected: PASS.
- [ ] **Step 5:** Commit `feat(cloud-runner): refuse outbound requests outside the workspace policy`.

### Task 3: Claude Code command, env and result parsing

**Files:**
- Create: `cloud-runner/src/agent.ts`, `test/agent.test.ts`

**Interfaces:**
- Produces:

```ts
export type RunOptions = { prompt: string; model: string; maxTurns: number; sessionId: string; resume: boolean }
export function agentArgv(o: RunOptions): string[]
export function agentEnv(accountId: string, gatewayId: string): Record<string, string>
export function parseLine(line: string): { type: string; payload: unknown } | undefined  // undefined for blank/non-JSON
export function outcome(lines: Iterable<string>, exitCode: number, stderrTail: string):
  { state: "succeeded"; result: string } | { state: "failed"; error: string }
```

- `agentArgv`: `claude --print --output-format stream-json --verbose --dangerously-skip-permissions --model <model> --max-turns <n>`, then `--session-id <id>` when `resume` is false or `--resume <id>` when true, then `--`, then the prompt. No `--no-session-persistence`.
- `agentEnv`: exactly the guide's four variables, with the gateway URL built from the two ids. No other key.
- `outcome`: the last line that parses as `{ type: "result", is_error, result?, subtype }` decides; none -> failed with `claude exited with <code>: <stderrTail>`.
- Before writing, run the pinned CLI's `--help` in the built image once and confirm `--session-id`, `--resume` and `--max-turns` exist; if a name differs, use the CLI's and note it in the README.

- [ ] **Step 1: Write failing tests**: argv for a first run and a resumed run (exact arrays); a prompt starting with `--` stays after `--`; `agentEnv` key set equals `["ANTHROPIC_API_KEY","ANTHROPIC_BASE_URL","CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC","IS_SANDBOX"]` and `ANTHROPIC_API_KEY === "provided-by-worker"`; `outcome` for success, `is_error: true`, and no result line.
- [ ] **Step 2:** Run, expect FAIL. **Step 3:** Implement. **Step 4:** Run, expect PASS.
- [ ] **Step 5:** Commit `feat(cloud-runner): build the claude code command and read its result`.

### Task 4: Event log

**Files:**
- Create: `cloud-runner/src/events.ts`, `test/events.test.ts` (runs in the workers pool against a test Durable Object with SQLite storage)

**Interfaces:**
- Produces:

```ts
export const MAX_EVENTS = 10_000
export const MAX_PAYLOAD_BYTES = 262_144
export class EventLog {
  constructor(sql: SqlStorage)
  append(run: number, generation: number, type: string, payload: unknown): number  // returns seq, starting at 1
  readAfter(after: number, limit?: number): { events: Event[]; next: number }      // limit default 500, max 1000
  clear(): void
}
```

- `seq` never restarts within a workspace, including after trimming. `next` is the
  highest `seq` returned, or `after` when nothing is returned.
- A payload whose JSON is over the cap is stored as `{ truncated: true, bytes: <n> }`.

- [ ] **Step 1: Write failing tests**: appends return 1, 2, 3; `readAfter(1)` returns 2 and 3 with `next: 3`; `readAfter(3)` and `readAfter(99)` return `[]` with `next` equal to the argument; appending `MAX_EVENTS + 5` keeps exactly `MAX_EVENTS` and the lowest kept `seq` is 6; `readAfter(0)` after trimming starts at 6; a 300,000-byte payload is stored truncated with `bytes: 300000`-ish (assert `truncated === true` and `bytes > MAX_PAYLOAD_BYTES`); `limit` above 1000 is clamped.
- [ ] **Step 2:** Run, expect FAIL. **Step 3:** Implement. **Step 4:** Run, expect PASS.
- [ ] **Step 5:** Commit `feat(cloud-runner): keep a numbered, bounded event log per workspace`.

### Task 5: Workspace object: container, runs, status, stop, diff

**Files:**
- Create: `cloud-runner/src/workspace.ts` (replaces the Task 1 stub)
- Modify: `cloud-runner/src/index.ts` (export `Workspace` and `Outbound`)

**Interfaces:**
- Consumes: `agentArgv`, `agentEnv`, `outcome`, `parseLine` (Task 3); `EventLog` (Task 4); `Outbound` with props `{ repoPath, allow }` (Task 2).
- Produces RPC methods on `Workspace extends DurableObject<Env>`:

```ts
create(repo: string, branch: string, allow: string[]): Promise<{ status: Status; cloneError?: string } | "conflict">
status(): Promise<Status>
startRun(prompt: string, fresh: boolean, maxTurns: number): Promise<{ run: number } | "busy" | "missing">
events(after: number): Promise<{ events: Event[]; next: number }>
stop(): Promise<Status>
diff(): Promise<{ ok: boolean; text: string }>
destroyWorkspace(): Promise<void>
```

- Follow the guide's `AgentSandbox` for: starting the container (`enableInternet: false`, `standard-1`), registering both intercepts, `setInactivityTimeout` (15 min here) in the constructor when already running, the background task script with pid and exit-code files, the running probe, and the alarm that re-arms every 60 s while a run is active.
- Differences from the guide:
  - Stored facts (object storage): `repo`, `branch`, `allow`, `run`, `generation`, `sessionId`, `hasConversation`, `state`, `result`, `error`, `pushed`, `pushError`, `snapshot`, `restored`, `eventsOffset`.
  - `create` clones with `--branch <branch>` and full history (no `--depth`), then sets `user.name "Plaza cloud agent"` and `user.email "plaza-cloud-agent@users.noreply.github.com"` in the clone. Calling `create` again with the same repo and branch is a no-op that returns status; with a different repo or branch it returns `"conflict"`, which the router answers as 409.
  - `startRun`: `fresh` or no conversation yet -> new `crypto.randomUUID()` and `resume: false`; otherwise resume the stored id. Increments `run`. Appends a `runner` event `{ notice: "run started", run }`.
  - `ingest()`: reads `stdout.log` from `eventsOffset`, appends one event per complete line through `EventLog`, advances the offset. Called by `events()`, by the alarm, and once more when a run is seen to have ended.
  - When the alarm or `status()` sees the run ended: `ingest()`, compute `outcome`, store it, then call `finishRun()` (Task 6; a no-op until then).
  - `stop()`: sends TERM to the task's process group, waits up to 10 s for the exit code, then KILL; state `stopped`; appends a `runner` event.
  - A stored `running` state with no running container, or a dead pid with no exit code, becomes `lost`, and `startRun` is then accepted.
  - `diff()`: the guide's command.
  - `destroyWorkspace()`: `container.destroy()`, delete the stored snapshot if the API offers a delete (Task 6), `EventLog.clear()`, `ctx.storage.deleteAll()`.

- [ ] **Step 1:** Implement the class. `npm run typecheck`. Expected: PASS.
- [ ] **Step 2:** With Docker running, `npx wrangler dev` and drive it with `curl` using a public repository and `.dev.vars` holding throwaway values: create answers 200; a second create with the same body answers 200; `events?after=0` answers `{ events: [], next: 0 }`; a run started without a working gateway token ends `failed` with an authentication error, and a second `POST runs` during it answers 409; after it ends, the next run answers 202. Record the commands and answers in `cloud-runner/README.md` under "Local check".
- [ ] **Step 3:** Commit `feat(cloud-runner): run claude code in a per-workspace container`.

If Docker is not available yet, do Step 1, commit, and carry Step 2 into Task 7.

### Task 6: Push, snapshot, restore and generations

**Files:**
- Modify: `cloud-runner/src/workspace.ts`

**Interfaces:**
- Produces (private): `finishRun(): Promise<void>`, `startInstance(): Promise<void>`.
- `finishRun`: `git push origin HEAD:<branch>` in the clone with the trust env. On success store `pushed.commit` from `git rev-parse HEAD` and clear `pushError`; on failure store `pushError` (last 2000 chars of stderr) and leave the run's own state as it was. Then take a container snapshot and store its id; a snapshot failure is stored as a `runner` event, not an error. Appends `runner` events for push and snapshot.
- `startInstance` (used wherever the guide starts the container): increments `generation`. With a stored snapshot, start from it and set `restored: "snapshot"`. If that start fails or no snapshot exists and `repo` is set, start from the image, clone the branch again, set `restored: "branch"`, set `hasConversation: false`, and set `uncommittedLost: true` when `generation > 1`. Appends a `runner` event naming which path was taken.
- Snapshot method and start option names come from the Durable Object Container API page (`/containers/api/durable-object-container/`); read it before writing.

- [ ] **Step 1:** Implement both. `npm run typecheck`. Expected: PASS.
- [ ] **Step 2:** Under `wrangler dev` (snapshots may be unavailable locally; if so, say so in the README and rely on Task 7): after a run, status shows `pushError` naming the refused push (throwaway token), and events include the `runner` notices.
- [ ] **Step 3:** Commit `feat(cloud-runner): push the branch and snapshot the workspace after each run`.

### Task 7: Deploy, acceptance and evidence

Needs the four owner inputs above.

**Files:**
- Create: `cloud-runner/scripts/acceptance.mjs`, `cloud-runner/README.md`, `docs/research/cloudflare-durable-objects/spike-c.md`
- Modify: `specs/meta/doc-registry.json` (entry for `spike-c.md` if the validator requires one), `docs/research/cloudflare-durable-objects/README.md` (link)

**Interfaces:**
- `acceptance.mjs <url>` reads `RUNNER_CALLER_SECRET`, `TEST_REPO`, `TEST_BRANCH` from the environment, uses workspace names `acc-<random>-a` and `-b`, deletes them at the end, prints one line per check (`PASS n <name>` / `FAIL n <name>: <why>`), and exits non-zero on any FAIL. It never prints a secret.

- [ ] **Step 1:** Put the three secrets with `npx wrangler secret put` (the caller secret is 32 random bytes, hex, also saved to `cloud-runner/.dev/caller.env`). Deploy with `npx wrangler deploy -c wrangler.dev.jsonc`. Expected: a `workers.dev` URL.
- [ ] **Step 2:** Write `acceptance.mjs` with these checks, numbered as spec §8:
  1. Prompt "Add a file NOTES.md with one sentence about this repository and commit it." ends `succeeded`; events contain a `result` event; `pushed.commit` is set and `git ls-remote` shows it on the branch.
  2. During a run, read events twice with the same `after`; the two answers have the same `seq` list prefix; reading with `after = next` never repeats a `seq`.
  3. Prompt "Run: curl -sS -o /dev/null -w '%{http_code}' https://example.com ; then run: git push https://github.com/octocat/Hello-World HEAD:refs/heads/x ; report both outputs exactly." The result text contains `403` and the push is reported refused.
  4. Prompt "Run: env ; cat .git/config ; ls -la ~ ; report the outputs exactly." The script asserts none of the three secret values, nor any string matching `ghp_`, `github_pat_` or `sk-ant-`, appears in the events.
  5. Start runs in workspaces a and b within one second; both reach `succeeded`; a prompt in b that lists `/workspace` does not show a file a created.
  6. In a: prompt "Create scratch.txt containing 42 and do not commit it. Remember the word heliotrope." When that run has ended, call the test-only `replace-instance` route from Step 3 (not `DELETE`). Then prompt "What word did I ask you to remember, and what is in scratch.txt?" Record: `restored`, whether `42` is reported, whether `heliotrope` is reported. The check passes when the file survives; the conversation result is recorded either way.
  7. Start a long prompt, `stop` after 20 s, status is `stopped`, and a following run answers 202.
  8. Not automated: read the ten-minute and idle-hour cost from the Cloudflare dashboard and the gateway's log, and write the numbers into `spike-c.md`.
- [ ] **Step 3:** Add the test-only route check 6 needs: `POST /workspaces/:name/replace-instance`, enabled only when `vars.ALLOW_REPLACE_INSTANCE === "1"` (set in `wrangler.dev.jsonc`, absent from `wrangler.jsonc`), which destroys the container and leaves storage alone. Add its test to `test/index.test.ts` (404 when the var is unset).
- [ ] **Step 4:** Run `node scripts/acceptance.mjs <url>`. Fix what fails in the runner; a check that fails because of a platform limit is recorded as such, not hidden.
- [ ] **Step 5:** Write `spike-c.md`: date, deployed version, the script's output, the answers to the roadmap's four unverified questions (Claude Code in a sandbox, the login path used, resume after replacement, cost), and anything that surprised. Write `README.md`: parts, routes, deploy and redeploy steps, where secrets live, how to delete a workspace, the "Local check" notes.
- [ ] **Step 6:** `python3 scripts/validate_specs.py`. Expected: `Spec validation passed`.
- [ ] **Step 7:** Commit `feat(cloud-runner): deploy the development runner and record stage 1 evidence`.

## Done means

- `npm test` and `npm run typecheck` pass in `cloud-runner/`, and the CI job is green.
- `acceptance.mjs` output is in `spike-c.md`, with every FAIL explained.
- Nothing under `bridge/` changed (`git diff --stat origin/dev -- bridge scripts` is empty).
- Adam has the runner URL and can run the `curl` lines in the README.
