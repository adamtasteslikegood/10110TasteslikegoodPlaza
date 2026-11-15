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

## To verify on the deploy

Task 7 checks these on the development deploy. `wrangler dev --local` cannot
show most of them; the 409 is checked here too, but the deploy must answer it
as well:

- With Internet off, raw TCP, DNS and ports other than 80/443 do not leave the
  container.
- The detached task survives an object restart or a redeploy, and its exit code
  is still written.
- A run longer than the 15-minute idle timeout stays alive.
- A second start during a run answers 409.
- Two containers can run at once (`wrangler.jsonc` sets no instance limit).
