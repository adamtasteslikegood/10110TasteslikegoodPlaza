# Plaza cloud runner

A Cloudflare Worker that runs Claude Code on one GitHub branch inside a
Sandbox container, one container per workspace (M14 stage 1). Callers drive it
over HTTP with `Authorization: Bearer <RUNNER_CALLER_SECRET>`; the `Workspace`
Durable Object clones the branch, starts runs in the background, keeps their
stream-json output as numbered events, and reports `running`, `succeeded`,
`failed`, `stopped` or `lost`. The container has no Internet access of its
own: every request goes through the `Outbound` entrypoint, which adds the
credentials, so none enters the container.

## What survives an instance

After every run that ends or is stopped, the object pushes the clone's `HEAD`
to the branch and then takes a container snapshot (`snapshotContainer`). The
status keeps the last pushed commit (`pushed`) or the end of git's stderr
(`pushError`); neither changes the run's own state. A new instance starts from
the stored snapshot, with the files and Claude Code's session (`restored:
"snapshot"`). With no snapshot, or one that does not start, it clones the
branch again, starts a new conversation and says so (`restored: "branch"`,
`uncommittedLost: true` after an earlier instance). A failed snapshot drops the
stored one, so a later instance never restores files older than the pushed
branch. Every replacing instance appends a `runner` event naming its path.

Snapshots are in public beta. The Durable Object Container API has no method
to delete a snapshot, so `DELETE /workspaces/:name` only forgets the stored id;
the snapshot itself expires 30 days after it was taken or last restored.

## Test-only routes (development deploy only)

Two routes exist only when the Worker var `ALLOW_TEST_ROUTES` is `"1"`, which
only the git-ignored `wrangler.dev.jsonc` sets; `wrangler.jsonc` does not, and
without it both answer 404. They sit behind the same bearer check as every
other route.

**While they are on, anyone holding the caller secret can run any command in a
workspace's container from the public URL.** That includes reading the clone and
acting with whatever the container can reach. To turn them off, remove
`ALLOW_TEST_ROUTES` from `vars` in `wrangler.dev.jsonc` and redeploy (see
"Deploy or redeploy"). Both routes then answer 404.

- `POST /workspaces/:name/replace-instance` destroys the container and leaves
  the object's storage alone, as a platform replacement would. A run in progress
  is then reported `lost`, and the next request starts a new instance from the
  snapshot or the branch.
- `POST /workspaces/:name/exec` with `{ "argv": ["cmd", "arg", ...] }` runs that
  command (no shell unless `argv` names one) in `/workspace/repo` with the
  container trust env and `GIT_TERMINAL_PROMPT=0`, and no credential, for at most
  30 s. It answers `{ exitCode, stdout, stderr }`, each stream cut at 64 KiB.

Why: the acceptance checks (`scripts/acceptance.mjs`) must look inside the
container (egress, credentials, files of two workspaces) and replace an instance
on demand, without a model call and without `docker exec`, which a deployed
container does not offer. Running arbitrary commands is not something a caller of
a production runner should be able to do, so these routes stay off there.

## Local check

Run on 2026-11-14 with Docker 29.9.2, from `cloud-runner/`. `.dev.vars`
(git-ignored) held throwaway values only:

```
RUNNER_CALLER_SECRET=dev-secret
AI_GATEWAY_TOKEN=invalid
GITHUB_TOKEN=
```

```sh
npx wrangler dev --local --ip 127.0.0.1 --port 8787 --var AI_GATEWAY_ACCOUNT_ID:local
c() { curl -sS -X "$1" -H 'Authorization: Bearer dev-secret' -H 'content-type: application/json' ${3:+--data "$3"} "http://127.0.0.1:8787$2"; }
```

wrangler dev built the image and ran it without a Cloudflare login. An empty
`GITHUB_TOKEN` in `.dev.vars` satisfied `secrets.required`.

| Request | Answer |
|---|---|
| `c PUT /workspaces/plain '{"repo":"https://github.com/octocat/Hello-World","branch":"master"}'` | 200 `{"state":"idle","run":0,"generation":1,"repo":"https://github.com/octocat/Hello-World","branch":"master"}` (about 2.5 s) |
| the same PUT again | 200, the same status |
| the same name with `{"repo":"https://github.com/octocat/Spoon-Knife","branch":"main"}` | 409 `The workspace exists with another repo or branch` |
| `c PUT /workspaces/check '{"repo":"https://github.com/octocat/Hello-World","branch":"no-such-branch"}'` | 502 `{"state":"none","run":0,"generation":1,"cloneError":"Cloning into '/workspace/repo'...\nfatal: Remote branch no-such-branch not found in upstream origin\n"}`; then GET answers `state: "none"`, and a PUT with `master` answers 200 with `generation: 1` (the same container) |
| `c GET '/workspaces/plain/events?after=0'` | 200 `{"events":[],"next":0}` |
| `c POST /workspaces/plain/runs '{"prompt":"Say hello in one word.","maxTurns":2}'` | 202 `{"run":1}` |
| a second POST runs during it | 409 `A run is already active` |
| `c GET /workspaces/plain` after the run ended (about 3 min of retries) | 200 `{"state":"failed","run":1,...,"error":"Failed to authenticate. API Error: 401 Unauthorized"}` |
| the next POST runs | 202 `{"run":2}`, started with `--resume <run 1's session id>` |
| a run on workspace `alarm` with no request for 290 s, then `events?after=0` | the `run ended` runner event (`state: failed`) is stamped 08:01:12, 50 s before the request at 08:02:02: the 60 s alarm finished the run |
| on workspace `check`: a run that fails with the 401, then a run without `fresh`, both left to end | both end `failed` with the 401; run 2's `system`/`init` event carries the same `session_id` as run 1's (`--resume` found the session) |
| `docker kill` of the container during run 2, then `c GET /workspaces/plain` | 200 `{"state":"lost","run":2,"generation":1,...,"error":"The container stopped before the run ended"}` |
| the next POST runs | 202 `{"run":3}`; status shows `generation: 2`, the branch was cloned again and the run started with a new `--session-id` |
| `c POST /workspaces/hello/stop` six seconds into a run | 200 `{"state":"stopped",...}` in 0.25 s; the task's exit code was 143 (TERM) |
| (2026-11-15) `c POST /workspaces/stopnow/stop` right after `c POST .../runs` | 200 `{"state":"stopped","run":1,...}` in 0.5 s; exit code 143, and no process but `sleep infinity` left in the container |
| the next POST runs, left to end | 202 `{"run":2}`; it ends `failed` with the 401 from its own `result` event, not run 1's 143 |
| on workspace `nopid`: the pid file moved aside (`docker exec ... mv`) right after the run started, then `c POST /workspaces/nopid/stop` | 409 `The run could not be stopped: its task is still running. Try again.` after 28 s (5 s waiting for the pid file, 10 s after TERM, 10 s after KILL); status stays `running`, a new run answers 409, the task is alive |
| the pid file moved back, then the stop again | 200 `{"state":"stopped",...}` at once; exit code 143, the task gone |
| `c GET /workspaces/hello/diff` after editing `README` and adding `NEW.txt` in the clone | 200, a `git diff` showing both, the new file included |
| `c GET /workspaces/never`, `c GET /workspaces/never/diff` | 200 `{"state":"none","run":0,"generation":0}`; 404 `No such workspace: create it with PUT first` |
| `c DELETE /workspaces/hello`, then `c GET '/workspaces/hello/events?after=0'` | 204; 404, and the container is gone |

Push, snapshot and restore (2026-11-15, Task 6), on workspace `persist`
(Hello-World, `master`, empty `GITHUB_TOKEN`). Snapshots work under
`wrangler dev --local`: each is a local Docker image named
`workerd-container-snap-<id>` (about 1.19 GB here).

| Step | Answer |
|---|---|
| `c PUT ...`, then `c GET '/workspaces/persist/events?after=0'` | 200 `generation: 1`, no `restored`; `{"events":[],"next":0}` |
| `c POST /workspaces/persist/runs ...`; `docker exec <container> sh -c 'echo local > /workspace/repo/LOCAL.txt'`; the run left to end (401) | status `failed`, `"pushError":"fatal: could not read Username for 'https://github.com': terminal prompts disabled\n"`; runner events `run ended`, `push failed` (same text), `snapshot saved` (`bytes: 1193260641`) |
| `docker rm -f <container>`, then `c GET /workspaces/persist/diff` | the first try answered 500 `Network connection lost` (workerd reset the object while the removed container went away; generation 2 was used up); the retry answered 200 with `LOCAL.txt` in the diff |
| `c GET /workspaces/persist`, events after 17 | `generation: 3`, `restored: "snapshot"`, `uncommittedLost: false`; one event `{"notice":"instance started","generation":3,"from":"snapshot"}` |
| `docker rm -f <container>` and `docker rmi -f workerd-container-snap-<id>` (the snapshot gone), then `c GET /workspaces/persist/diff` | 200, empty diff (`LOCAL.txt` gone) |
| `c GET /workspaces/persist`, events after 18 | `generation: 4`, `restored: "branch"`, `uncommittedLost: true`; `{"notice":"instance started","generation":4,"from":"branch","snapshotError":"exec() requires a running container."}` |
| `c POST .../runs`, then `c POST .../stop` six seconds in | 200 `stopped`, `pushError` as above; events `run stopped`, `push failed`, `snapshot saved`; run 2's `system`/`init` carries a new `session_id` (the clone forgot run 1's conversation) |

A successful push (`pushed.commit`) needs a real token on a test repository: Task 7.

After the review fixes (2026-11-15), same setup, workspaces `fix1`, `fix2` and
`nopid` (Hello-World, `master`):

| Step | Answer |
|---|---|
| the first `c PUT /workspaces/fix1 ...` after wrangler built the image | 500 `Workspace request failed` after 5.7 s: the clone's first exec found the new instance not running yet (generation 1 used up). The PUT again answered 200, `generation: 2`. Later workspaces answered 200 at once (about 1.5 s) |
| the same name with the same repo and branch and `"allow":["example.com"]` | 409 `The workspace exists with another repo or branch` (the host list now counts) |
| `c POST .../runs`, a second POST during it | 202 `{"run":1}`; 409 `A run is already active` |
| `c GET /workspaces/fix1/diff` during the run, after editing `README` and adding `NEW.txt` | 200 in 0.18 s, both in the diff |
| a 2 MB `BIG.txt` added, the diff again, during and after the run | 200, 1,048,521 bytes of diff cut at a line, then `[The diff is longer than 1 MiB and was cut here.]`; `.git/index` unchanged (same md5), no temp file left |
| the run left to end | `failed` with the 401, `pushError` as above |
| `c POST /workspaces/fix2/runs ...` and `c POST /workspaces/fix2/stop` at once | 200 `stopped` in 2.2 s; exit code 143; no live process in the container but `sleep infinity` (the task's processes are zombies: PID 1 does not reap) |
| run 2 on `fix2`; three seconds in, `kill -KILL` of the task's session leader (`sh`), `claude` still alive in its group | status stays `running`; when `claude` ended, `lost` with `The agent process ended without writing an exit code`; its `assistant` and `result` events were read in, then `push failed` and `snapshot saved` |
| on `nopid`: the pid file moved aside right after the start, then `c POST /workspaces/nopid/stop` | 409 `The run could not be stopped: its task is still running. Try again.` after 5.6 s (no task to signal, so no TERM and KILL waits); status `running`, a new run 409, the task alive |
| the pid file moved back, then the stop again | 200 `stopped` in 1.8 s; exit code 143, the group gone |

Egress after the fixes, with the same `docker exec ... fetch`:

- `fix1` (no `allow`): `https://example.com/` 403; `https://github.com/octocat/Hello-World`
  (a page, not git) 403; `https://api.github.com/repos/octocat/Hello-World` 403;
  `.../Hello-World/info/refs?service=git-upload-pack` 200; the same path on
  `octocat/Spoon-Knife` 403.
- `fix2` (`"allow": ["example.com"]`): `https://example.com/` 200,
  `https://example.org/` and `http://example.org/` 403.

Egress, checked with `docker exec <container> node -e "fetch(...)"` and
`NODE_EXTRA_CA_CERTS=/etc/cloudflare/certs/cloudflare-containers-ca.crt`, not
through any route of the Worker:

- Workspace `plain` (no `allow`): `https://example.com/` and `http://example.com/`
  answer 403 `example.com is not reachable from this sandbox`.
- Workspace `hello` (`"allow": ["example.com"]`): `https://example.com/` answers
  200, `https://example.org/` 403, and `github.com/octocat/Spoon-Knife` (another
  repository) 403.
- The running claude process's environment (`/proc/<pid>/environ`, pid from
  `/workspace/task/pid`) holds no token, secret or `Authorization`: the only
  match is the placeholder `ANTHROPIC_API_KEY=provided-by-worker`. The clone's
  remote is the plain `https://github.com/octocat/Hello-World`.

The props passed with `ctx.exports.Outbound({ props: { repoPath, allow } })`
reach the intercept under wrangler dev: the clone of the workspace's own
repository passed, another repository was refused, and only the workspace
that allowed `example.com` could reach it. No fallback was needed.

## The development deploy

Up since 2026-11-15: Worker `plaza-cloud-runner-dev` at
`https://plaza-cloud-runner-dev.adamschoen3.workers.dev`, with test routes on (see "Test-only routes"
for what that allows and how to turn it off). Preview URLs are off (`preview_urls: false`).
Evidence and the acceptance output are in
[spike-c.md](../docs/research/cloudflare-durable-objects/spike-c.md).

### Parts

- The Worker (`src/index.ts`): bearer check, routes, and the `Outbound`
  entrypoint that adds credentials to the container's HTTP(S).
- The `Workspace` Durable Object (SQLite storage), one per workspace name.
- The container application `plaza-cloud-runner-dev-workspace`, image from
  `Dockerfile`, one `standard-1` instance per workspace, Internet off.
- AI Gateway `my-cf-agent-gateway` (not managed here: its BYOK key and
  settings belong to the owner).

### Routes

All need `Authorization: Bearer <RUNNER_CALLER_SECRET>`.

| Route | Does |
|---|---|
| `PUT /workspaces/:name` `{repo, branch, allow?}` | create (clone) or confirm the workspace |
| `GET /workspaces/:name` | status |
| `POST /workspaces/:name/runs` `{prompt, fresh?, maxTurns?}` | start a run, 202 `{run}`; 409 while one is active |
| `GET /workspaces/:name/events?after=N` | events after `seq` N, and `next` |
| `POST /workspaces/:name/stop` | stop the run |
| `GET /workspaces/:name/diff` | `git diff` of the clone, new files included |
| `DELETE /workspaces/:name` | destroy the container and forget the workspace (204) |
| `POST /workspaces/:name/replace-instance`, `POST /workspaces/:name/exec` | test-only, see above |

### Where the secrets live

- Worker secrets `AI_GATEWAY_TOKEN`, `GITHUB_TOKEN` and `RUNNER_CALLER_SECRET`, on Cloudflare only.
- Locally, in the owner's checkout and git-ignored: `.dev/deploy.env` (the two tokens) and `.dev/caller.env`
  (the caller secret, 32 random bytes in hex). Both are mode 600.
- `wrangler.dev.jsonc` (git-ignored) is `wrangler.jsonc` plus `AI_GATEWAY_ACCOUNT_ID` and `ALLOW_TEST_ROUTES: "1"`.

### Deploy or redeploy

From `cloud-runner/`, logged in with `npx wrangler login`, with Docker running:

```sh
# once, or to rotate a secret (each read from stdin, never from argv)
set -a; . .dev/deploy.env; . .dev/caller.env; set +a
printf %s "$AI_GATEWAY_TOKEN" | npx wrangler secret put AI_GATEWAY_TOKEN -c wrangler.dev.jsonc
printf %s "$GITHUB_TOKEN" | npx wrangler secret put GITHUB_TOKEN -c wrangler.dev.jsonc
printf %s "$RUNNER_CALLER_SECRET" | npx wrangler secret put RUNNER_CALLER_SECRET -c wrangler.dev.jsonc

npx wrangler deploy -c wrangler.dev.jsonc --dry-run
systemd-run --user --scope -q -p MemoryMax=10G -p MemorySwapMax=0 -- npx wrangler deploy -c wrangler.dev.jsonc
```

If `docker login` to `registry.cloudflare.com` fails because the configured
credential store does not work, run the deploy with a throwaway
`DOCKER_CONFIG` holding `{}` (and `DOCKER_HOST` set to the daemon's socket if
a Docker context was in use), then delete that directory: it ends up holding
the registry login in plain text. A redeploy with an unchanged image skips the
push and does not disturb a running task (spike C, check d). To repeat that check, run
`node scripts/redeploy.mjs <url>` with `RUNNER_CALLER_SECRET`, `TEST_REPO` and `TEST_BRANCH` set. It starts a
`sleep 150` run, redeploys 20 s in, waits for the run to end, checks the exit code and deletes its workspace.
Each run of it makes a new Worker version.

Acceptance, against the deploy (pushes go to the test branch only; the script refuses `main` and `master`):

```sh
set -a; . .dev/deploy.env; . .dev/caller.env; set +a
TEST_REPO=https://github.com/OWNER/REPO TEST_BRANCH=cloud-runner/acceptance \
  node scripts/acceptance.mjs https://plaza-cloud-runner-dev.adamschoen3.workers.dev
```

### Delete a workspace

`DELETE /workspaces/:name` destroys its container and forgets its storage. It answers 204, and a GET then answers
`state: "none"`. Its snapshots stay in the registry until they expire (30 days). Check that no instance is left with
`npx wrangler containers list` (the `LIVE INSTANCES` column).

### Remove the deploy

`npx wrangler delete -c wrangler.dev.jsonc` removes the Worker and its Durable Objects. Its help does not say it removes
the container application, so check `npx wrangler containers list` afterwards and remove
`plaza-cloud-runner-dev-workspace` with `npx wrangler containers delete <ID>` if it is still there. The images and snapshots in `registry.cloudflare.com` are listed by `npx wrangler containers images list`;
remove the image with `npx wrangler containers images delete`. The snapshots expire on their own. Only the owner removes
the deploy.

### Results of the former "to verify on the deploy" list

- With Internet off, raw TCP (22, 25, 53 and 8080) does not leave the container.
- Neither UDP probe got a reply: NTP to 162.159.200.1:123 and a datagram to 1.1.1.1:9999. That is all the evidence for
  UDP other than DNS.
- DNS is answered by a local platform stub with one synthetic address, whatever the destination or the name. So no
  query reaches a real resolver directly, but whether query names leave the platform is **unverified** (see the
  known gaps).
- Plain HTTP is refused, also to an allowed host.
- `maxTurns` is enforced: a run with `maxTurns: 1` that needed two tool calls ended `failed` with `error_max_turns`.
- The detached task survived a Worker redeploy mid-run, and its exit code was written.
- A second start during a run answers 409.
- Two containers ran at once.
- A run longer than the 15-minute idle timeout was **not exercised**; the longest run was about 160 s.

## Known gaps to close before stage 2

From the whole-branch review and its re-review (2026-11-15). None blocks the development deploy.

- **Leftover agent when the pid file never appears or is removed.** The never-started path ends the run as lost
  without a KILL, and `parseTask` accepts pid 0 or 1. Refuse a pid of 1 or less, and before a start either kill
  every non-init process or restart the instance.
- **Stale snapshot after a lost run on a gone container.** `endLost` keeps the pre-run snapshot id, so a later
  restore reports `uncommittedLost: false` for files that are behind the run.
- **`finish()` does not kill the task's group**, so background processes can change the tree during push and snapshot.
- **Every route can wait behind a slow push and snapshot** (up to 5 minutes for the push; the snapshot call has no
  timeout because the SDK offers none). Add a race wrapper.
- **A timed-out exec may keep running in the container**, and `diff` can leave its temp index lock behind.
- **PID 1 is `sleep infinity`**, which never reaps finished processes. Add an init such as tini; this also closes
  process-group id reuse within one boot.
- **The first PUT after an image build answered 500 once** under `wrangler dev`. It did not recur on the deploy
  (every first PUT answered 200), but the cause, an exec before the new instance was running, is not fixed.
- **A run longer than the 15-minute idle timeout** has not been tried on the deploy.
- **`--max-turns` is a hidden flag** of Claude Code 2.1.308. It is accepted and enforced (spike C, check T), but it is
  not in `--help`, so a later version could drop it without notice. Check T in `scripts/acceptance.mjs` would catch that.
- **DNS name leakage is unverified.** Every UDP/53 query gets one synthetic answer from a platform stub, so no packet
  reaches a real resolver directly. If the stub logs or forwards query names upstream, a process could carry data
  out in the labels of the names it looks up. To settle it, resolve a fresh random label under a zone the owner
  controls, then look for it in that zone's authoritative query log. This needs an owner-controlled zone and is owed.
- **The bare root of an allowed host is refused.** The intercept passes `https://host` without its slash, and the
  normal-form rule refuses it; `https://host/path` is allowed. This fails closed.
- **A ten-minute run and an idle hour were not measured** (design §8 item 8). The idle cost is computed from
  published rates only, and the dashboard's billed figures are owed by the owner.
- **Older AI Gateway header names** without the `cf-aig-` prefix (for example `cf-skip-cache`) are not stripped.
  Check the gateway documentation and strip them if the gateway still honours them.
- **Any ref of the workspace repository can be pushed or deleted** with the token. Branch rules on GitHub are the control.
- **Git LFS is refused** by the smart-HTTP-only rule.
- **The 409 text for a changed host list** says "another repo or branch".
- **The shell scripts in `container.ts`** have no automated test; they were checked by hand and under `wrangler dev`.

### Notes on the evidence itself (from the last review, 2026-11-15)

- `scripts/redeploy.mjs` is a rewrite of the scratch script that produced the redeploy log; the committed version
  has not been run. It also does not check that the deploy succeeded, so it can print a pass after a failed deploy.
  Run it under the same memory cap as any deploy.
- The cause given for the refused bare host root (the intercept passing `https://host` without its slash) is inferred
  from the code and a local reproduction, not seen in a log.
- The raw TCP and UDP probes target IPv4 only, although the container's resolver configuration lists an IPv6 server.
- The process-environment scan in check 4 ran while no agent was alive, so the agent process's own environment was
  scanned only in the local check.
- Check 3 now needs the live npm registry to answer.
