# Plaza cloud runner

A Cloudflare Worker that runs Claude Code on one GitHub branch inside a
Sandbox container, one container per workspace (M14 stage 1). Callers drive it
over HTTP with `Authorization: Bearer <RUNNER_CALLER_SECRET>`; the `Workspace`
Durable Object clones the branch, starts runs in the background, keeps their
stream-json output as numbered events, and reports `running`, `succeeded`,
`failed`, `stopped` or `lost`. The container has no Internet access of its
own: every request goes through the `Outbound` entrypoint, which adds the
credentials, so none enters the container.

## Who runs what in the container

The agent is not root (PLZG-311, the owner's decision of 2026-11-15). The image
has a user `agent`, and Claude Code runs as it, with no-new-privs, so a setuid
binary gives nothing back. The clone (`/workspace/repo`) and `/home/agent`,
where Claude Code keeps its conversations, are the agent's. Everything the
runner trusts about a run is root's: the task's session leader, the two
processes that copy its output, and `/workspace/task` (mode 700) with the pid
file, the exit code and the logs. `/workspace` itself is root's, so the agent
cannot move those directories aside. The agent holds only the two pipes its
output goes into.

The runner's own commands are root's, with one rule: **git in the clone always
runs as the agent** (clone, the fetch and fast-forward before a run, push, diff,
the check after a restore). The clone's
config, hooks and diff drivers are the agent's to write, so root must never run
them. The image carries a layout mark (`/etc/plaza-runner-layout`, `imageLayout`
in `src/container.ts`); change both when who owns what changes.

**Nothing of the agent's is left running after a run.** When a run ends, right
after the KILL of its process group, then before its push, before each snapshot
try, and before the next run starts both before and after the branch sync (and
after a sync that refuses the start), the runner ends every process of the `agent`
user: a process of that user sends KILL to every process it may signal, and root
then checks that none is left. This reaches a process that left the task's
process group with `setsid`, which the group KILL does not, and one that a git
hook or diff driver started. An instance that still has such a process gets no
further run: it is replaced once the run is pushed and snapshotted, and a
`runner` event says `agent processes left`. If the check cannot run at all, the
end of a run treats it the same way, and the start of a run fails and is to be
tried again, with nothing replaced. A process left after the sync before a run
fails that start too, and the next start replaces the instance. The runner never does this while a run is
running, since it would end the run's agent.

`npm run test:container` shows all of this in a container built from the
Dockerfile (it needs Docker; `npm test` runs in the Workers runtime and has
no containers).

## What survives an instance

After every run that ends or is stopped, the object pushes the clone's `HEAD`
to the branch and then takes a container snapshot (`snapshotContainer`). The
status keeps the last pushed commit (`pushed`) or the end of git's stderr
(`pushError`); neither changes the run's own state. A new instance starts from
the stored snapshot, with the files and Claude Code's session (`restored:
"snapshot"`). With no snapshot, or one that does not start, it clones the
branch again, starts a new conversation and says so (`restored: "branch"`,
`uncommittedLost: true` after an earlier instance). The push is stored before
the snapshot is taken, and each snapshot try is cut off after 3 minutes; one
that times out is tried again by the alarm, at most 3 times. A snapshot that
fails, times out 3 times or can no longer be taken (the container is gone)
drops the stored one, so a later instance never restores files older than the
pushed branch. A run lost with its container already gone pushes nothing: the
stored snapshot is then the best copy there is, so it is kept but marked stale,
and the next restore from it reports `uncommittedLost: true` and starts a new
conversation. Every replacing instance appends a `runner` event naming its path.
A snapshot holds the whole root filesystem, so one whose layout mark is not the
current image's (for example one taken while the agent was still root) is not
restored either: the instance clones the branch, and its event says why.

A run's stdout is kept up to 64 MiB; a run that writes more is ended `failed`
with `run output exceeded 64 MiB`. Only the last 1 MiB of its stderr is kept.

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
  The command runs as the agent user; add `"root": true` to run it as root, to
  look at what the agent cannot (the task directory, root's processes).

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
| `c POST /workspaces/fix2/runs ...` and `c POST /workspaces/fix2/stop` at once | 200 `stopped` in 2.2 s; exit code 143; no live process in the container but `sleep infinity` (the task's processes are zombies: PID 1 does not reap; measured before tini became PID 1, 9cb4a90) |
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
that allowed `example.com` could reach it. No fallback was needed. Since the
push guard (f8c9d0a) the props are `{ repoPath, branch, allow }`; the check
below shows `branch` reaching the intercept too.

After the Copilot fixes (2026-11-15), same setup, with the image rebuilt (tini
as PID 1), Hello-World `master`, an empty `GITHUB_TOKEN` and `ALLOW_TEST_ROUTES`
on, workspaces `t1` to `t4`. Commands inside the container ran through the
`exec` test route.

| Step | Answer |
|---|---|
| the first `c PUT` of each of `t1`–`t4`, each a fresh instance from the image | 200 `generation: 1` at the first try, in about 1.3–1.5 s, 4 of 4. Only `t1`'s was the first PUT after the image build, the case that answered 500 before: 1 of 1 |
| `/proc/1/comm` and `/proc/1/cmdline`, fresh and after a restore | `tini`; `/usr/bin/tini -- sleep infinity` |
| `/bin/sh` | dash; every run's task script ran under it |
| `t1`: a run left to end, then `ps` | `failed` with the 401, `push failed`, `snapshot saved` (1,194,738,763 bytes); only `tini`, `sleep` and the exec's `sh` left, no zombie |
| `t2`: `c POST .../runs` and `c POST .../stop` at once | 200 `stopped` in 2.2 s; nothing left but `tini` and `sleep` |
| `t2`: the container removed by hand (`docker rm -f`), then the next request | 200 at the first try, `generation: 2`, `restored: "snapshot"` |
| `t4`: a fake `mv` that removes itself, so the pid file never appears while `claude` runs | after 60 s `lost`, `The agent did not write its pid file within 60 seconds`; events `run lost`, `push failed`, `snapshot saved`; the container was then destroyed, the next request restored from the snapshot (`generation: 2`) and only `tini`, `sh` and `sleep` ran (no leftover `claude`) |
| `t3` (no `allow`): `https://example.com/` from the container | 403 `example.com is not reachable from this sandbox` |
| `t3`: a hand-built `git-receive-pack` POST updating `refs/heads/master` | forwarded; GitHub answered 401 `No anonymous write access.` |
| the same POST updating `refs/heads/other` | 403 `github.com refused this push: only the workspace branch may be pushed` |
| `t3`: 70 MB of lines written to the run's stdout | the writer got SIGPIPE (exit 141); `stdout.log` 67,108,865 bytes; the run ended `failed`, `run output exceeded 64 MiB`; no process left |
| `t3`: 3 MB written to stderr | `stderr.log` exactly 1,048,576 bytes |

After the agent stopped being root (2026-11-15, PLZG-311), same setup on port
8797, workspace `nr1` (Hello-World, `master`), the image rebuilt with the `agent`
user. The image has no `ps`, so processes were read from `/proc`.

| Step | Answer |
|---|---|
| `c PUT /workspaces/nr1 ...` | 200 `generation: 1` in 1.5 s; `/workspace` is `root 755`, `/workspace/repo` and its `.git` are `agent 755`, the layout mark reads `2` |
| an exec (no `root`): `id`, `$HOME`, `NoNewPrivs`, the CA file, `git status`, `touch /workspace/planted` | `uid=1001(agent)`, `/home/agent`, `NoNewPrivs: 1`, the CA file is readable, `## master...origin/master`; the `touch` is refused (`Permission denied`) |
| the same exec with `"root": true` | `root` |
| `c POST .../runs`, then the processes from `/proc` | the leader (`sh -c trap : TERM ...`), both copier shells, `head` and `tail` are uid 0; `claude --print ...` is uid 1001 with `NoNewPrivs: 1`, in the leader's group and session |
| during the run, `stat` of `/workspace/task` and its files | `/workspace/task root 700`; `pid`, `stdout.log`, `stderr.log` `root 644`; both fifos `root 600` |
| during the run, as the agent: `echo 0 >/workspace/task/exit-code`, `ls /workspace/task`, `kill -KILL <leader>` | all three refused (`Permission denied`, `Operation not permitted`) |
| as the agent: `kill -TERM -<group>` | allowed for the agent's own process only: `claude` ended, the leader lived and wrote `143`, and the run ended `failed`, `claude exited with 143`, then `push failed` and `snapshot saved` |
| run 2 left to end | the agent reached the gateway (`api_retry`, `authentication_failed`), then `failed` with `Failed to authenticate. API Error: 401 Unauthorized`; `exit-code` holds `1` and is `root 644`; `push failed` (`could not read Username`, as before: git ran, as the agent), `snapshot saved` (1,194,902,309 bytes); the conversations are under `/home/agent/.claude`, none under `/root` |
| `c GET /workspaces/nr1/diff` after editing `README` and adding `NEW.txt` as the agent | 200, both in the diff |
| `c POST .../runs` and `c POST .../stop` at once | 200 `stopped` in 1.6 s; only `tini`, `sleep` and the exec's shell left |
| `replace-instance`, then the diff and the status | the diff still shows both files; `generation: 2`, `restored: "snapshot"`, `uncommittedLost: false`; the same owners and layout mark as before |
| the next run on the restored instance | started with `--resume <run 2's session id>`, and its `system`/`init` event carries that id: the conversation in the agent's home survived the snapshot |
| the layout mark overwritten with `1` (as root), a run stopped so a snapshot is taken, `replace-instance`, then the diff | 200, an empty diff; `generation: 3`, `restored: "branch"`, `uncommittedLost: true`; event `{"notice":"instance started","from":"branch","snapshotError":"The snapshot's image layout is \"1\", not \"2\": it is from another version of the image"}`; the new instance's mark reads `2` |
| `c DELETE /workspaces/nr1`, then `c GET` | 204; `state: "none"` |

After the sweep of the agent's processes (2026-11-15, the code at 435873e), same setup with `ALLOW_TEST_ROUTES` on,
workspace `sw2` (Hello-World, `master`):

| Step | Answer |
|---|---|
| `c PUT /workspaces/sw2 ...`, then the same with `"allow":["example.com"]` | 200 `generation: 1`; 409 `The workspace exists with another repo, branch or host list` |
| an exec: `fetch("https://registry.npmjs.org")`, the same with a final slash, and `fetch("https://example.com")` | 200, 200 and 403: the bare root of an allowed host is reachable, and one of a host not allowed is still refused |
| an exec `setsid -f sleep 86001` as the agent, then `c POST .../runs` | the sleep was running before the run and gone right after the run started |
| an exec `setsid -f sleep 86002` during the run | running during the run as uid 1001, next to `claude`, outside the task's group |
| the run left to end (`failed`, 401, as before) | the sleep is gone; only `tini` and `sleep infinity` are left; `generation` still 1; notices `run started`, `run ended`, `push failed`, `snapshot saved`, and no `agent processes left` |

Not shown by this check: a push that succeeds and a run that ends `succeeded`
(both need real credentials). The acceptance suite on the deploy shows both
(spike C, log 8). Under local Docker, root has no `CAP_SYS_PTRACE`,
so root cannot read the `environ` of the agent's processes; the agent can read
its own. `scripts/acceptance.mjs` check 4 therefore scans as both users.

One slip during this check: `t1`'s container was looked up by `hostname`,
which matched its proxy sidecar's id, so the sidecar was removed instead of
the agent container. `t1`'s next requests then answered 500 after about 119 s
(`The new instance did not answer after 120 attempts`) and a later GET showed
`generation: 3`. That is the local Docker setup broken by hand, not a runner
path. The removal and restore were repeated on `t2`, whose container was found
by a marker file; `t4`'s restore followed the runner's own destroy after the
lost run.

## The development deploy

Up since 2026-11-15: Worker `plaza-cloud-runner-dev` at
`https://plaza-cloud-runner-dev.adamschoen3.workers.dev`, with test routes on (see "Test-only routes"
for what that allows and how to turn it off). Preview URLs are off (`preview_urls: false`).
Evidence and the acceptance output are in
[spike-c.md](../docs/research/cloudflare-durable-objects/spike-c.md).

**The deploy runs the code and image with the Copilot review fixes** (redeployed 2026-11-15 from the branch at
330bea3: tini, the push guard, bounded snapshots and output, lost-run settling, the task-file rules). The full
acceptance suite and the redeploy check were re-run on it (spike C, logs 6 and 7): same outcome as before the fixes.
The fixes' own failure paths (an unreadable task file, a snapshot that times out, an oversized result) were not
provoked on the deploy; they rest on the unit tests and the `wrangler dev` checks.

**The deploy runs the non-root agent** (PLZG-311): redeployed 2026-11-15 from `dev` at b5687c7 with the new image
(the `agent` user, layout mark `2`), by the owner's go-ahead. The full acceptance suite ran on it (spike C, log 8):
same outcome as before, and the new check `U` passes. Check 1 is the first run that ended `succeeded` and pushed as
the non-root agent. The redeploy check passed as well (log 9).

**The deploy runs the sweep of the agent's processes and the small fixes** (PLZG-311): redeployed 2026-11-17 from
`dev` at 7fc2982, code only, by the owner's go-ahead. The redeploy check was that deploy and passed (spike C,
log 12); the version was `eb2cf0ed`, and the image and its layout mark `2` are unchanged. The acceptance suite ran
on it (log 13). Check `R` passes: the bare root of an allowed host answers 200. Check `S` passes: a process started
as the agent outside any task was gone after the next run, on the same instance, with no `agent processes left`
event. `S` first failed in its own setup and was corrected (59daae9; see "Notes on the evidence itself"). Check H
fails as before (the hidden `--max-turns`).

What had never been tried on the deploy was tried the same day (spike C, log 14):

- A run of 1,204 s, longer than the 15-minute idle timeout, with no request from outside while it ran. It ended
  `succeeded` on the same instance, pushed and snapshotted. By Cloudflare's lifetime page it is the object's
  alarm, once a minute, that keeps the instance up; the run did not tell that apart from other causes.
- The idle stop. An instance nobody asked anything of was stopped, and the next request started a new one: from
  the snapshot with its uncommitted file where a run had ended, and from the branch without it where no run had
  ever taken a snapshot. On that version the stops came 18.5 and 25.5 minutes after the last request, not 15;
  since the next redeploy they come after about 15 (below).
- An unreadable task file: `stdout.log` replaced with a directory during a run. The run ended `failed` with
  `the run's task files could not be read` at the third check, nothing was pushed, and the instance was replaced.
- An oversized result line, written into a run's output by root: over one 4 MiB chunk the run ends `failed` with
  `the run's result was over 256 KiB and could not be read`; from 256 KiB to 4 MiB with `is_error: false` it ends
  `succeeded` with an empty result and a `result truncated` event. Both runs were pushed and snapshotted.
- Four containers ran at once.

**The deploy runs the two fixes those tests led to** (c258fc4 and cf868b2): the stdout copier that no longer
buffers, and the exec timeout whose timer ends with the command. It was redeployed again on 2026-11-17 from `dev`
at a190791, code only, by the owner's go-ahead. The redeploy check was that deploy and passed (spike C, log 15);
the version is `d1e6e606`, and the image is unchanged. On it (logs 16 and 17):

- The full acceptance suite passes eleven of twelve checks, check `S` among them in the full run. Check H fails
  as before.
- A running run's output is in the log at once. Nine seconds into a run, with the agent in its `sleep`,
  `stdout.log` held 3,627 bytes, less than one 4 KiB block, and the event log had the tool call that started the
  sleep. A line of 41 bytes written into the run's output was in `stdout.log` in the same exec and in the event
  log a second later.
- The idle stop comes about 15 minutes after the last request: 15.1 to 15.6 minutes for a workspace that had
  only been cloned, and 15.9 to 16.3 for one whose run had ended. Each case was measured once.

A redeploy that changes the image layout is meant to leave a workspace from before it working, with its first new
instance cloning the branch (`restored: "branch"`, `uncommittedLost: true`) because its snapshot has the old layout
and is refused. On this redeploy that was seen only for a stand-in: a snapshot of a current instance whose layout
mark had been removed was refused that way (spike C, log 11). The one workspace really taken across the redeploy
was started while the old code still answered, and got its old snapshot back (see the known gaps). A run that is in
progress during such a redeploy may lose its unpushed work, so redeploy with no run active.

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
| `PUT /workspaces/:name` `{repo, branch, allow?}` | create (clone) or confirm the workspace; 422 `No GitHub token is configured for this repository` when `GITHUB_TOKENS` lists none for it |
| `GET /workspaces/:name` | status |
| `POST /workspaces/:name/runs` `{prompt, fresh?, maxTurns?, conversation?}` | start a run, 202 `{run}`; 409 while one is active. The clone is first fast-forwarded to the branch on GitHub: 412 when it cannot be (a commit on each side, an uncommitted file in the way, or a stale lock), 502 when the branch cannot be fetched. No run starts in either case: the run's state, number, key and session are unchanged, but the instance may have been started or replaced on the way, and a pending snapshot is kept unless it was replaced. The 412 and 502 bodies are fixed texts; the `run refused` event carries git's reason. A 412 repeats on every start until the clone changes, and today the only way out is `DELETE`, which loses what the clone holds (see Known gaps). `conversation` is the caller's key, 1 to 128 letters, digits or hyphens (`[A-Za-z0-9-]{1,128}`): the same key resumes the conversation, another starts a new one; a run that starts a new conversation without a key clears the stored key; the status carries the key a later run would resume |
| `GET /workspaces/:name/events?after=N` | events after `seq` N, and `next` |
| `POST /workspaces/:name/stop` | stop the run |
| `GET /workspaces/:name/diff` | `git diff` of the clone, new files included |
| `DELETE /workspaces/:name` | destroy the container and forget the workspace (204) |
| `POST /workspaces/:name/replace-instance`, `POST /workspaces/:name/exec` | test-only, see above |

### Where the secrets live

- Worker secrets `AI_GATEWAY_TOKEN`, `GITHUB_TOKEN` and `RUNNER_CALLER_SECRET`, on Cloudflare only. `GITHUB_TOKENS`, a JSON object from
  `owner/repo` (lower case) to a token, replaces `GITHUB_TOKEN` once set: a repository it does not list is refused with 422,
  and so is a re-`PUT` of an existing workspace whose repository it no longer lists. It holds tokens, so it must be a
  secret, put as the others are, and never a `vars` entry in a wrangler config.
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
printf %s "$GITHUB_TOKENS" | npx wrangler secret put GITHUB_TOKENS -c wrangler.dev.jsonc  # when the map is used
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
- A run longer than the 15-minute idle timeout was not exercised then; the longest run was about 160 s. On
  2026-11-17 a run of 1,204 s ended `succeeded` (spike C, log 14).
- Four containers ran at once (2026-11-17).

## Known gaps to close before stage 2

From the whole-branch review and its re-review (2026-11-15), reconciled with the Copilot fixes the same day. None
blocks the development deploy. Closed since, and so removed: the leftover agent and pid 0 or 1 (762df32, b5df279),
the stale snapshot after a lost run (b5df279), `finish()` leaving the task's group (b5df279), PID 1 not reaping
(9cb4a90), the first PUT answering 500 (b5df279), and unbounded run output (b5df279). Closed on 2026-11-15 by
PLZG-311: the agent could write the run's control files (it ran as root). It now runs as the `agent` user and the
files are root's; see "Who runs what in the container" and the local check. The development deploy runs it since
the same day, and the acceptance suite's check `U` shows it there (spike C, log 8).

Closed on 2026-11-15 by a second PLZG-311 change, deployed on 2026-11-17: the refused bare root of an
allowed host (`https://host` is now judged as `https://host/`; acceptance check `R` asks for it and passes on the deploy), the
gateway's older header names (`cf-skip-cache` and `cf-cache-ttl`, which its documentation says still work, are now
dropped like every `cf-aig-` header), and the 409 for a changed host list, which now reads `The workspace exists with
another repo, branch or host list`. A diff or a test exec no longer replaces an instance whose snapshot is still
pending (it used to drop the snapshot and clone the branch, so a read could discard uncommitted files). The
best-effort group KILL, the instance with an old layout and the untested shell scripts are narrowed below.

- **An instance that is live when the image changes keeps its old layout** until it is replaced. With the code on
  the deploy, a run started on it fails (the `agent` user is missing, so `setpriv` exits 1) and its pushes fail the
  same way. With the sweep (deployed 2026-11-17), the next run's start finds no `agent` user, replaces the instance and
  clones the branch; its event reads `agent processes left`, which is not the reason. That follows from the code and
  was not tried on an instance from an old image. A diff or a push on such an instance still fails, and nothing
  checks the layout of a running instance as such.
- **The old Worker code can still answer for a short while after `wrangler deploy` returns**, and an instance it
  starts then has the old layout. Seen on the 2026-11-15 redeploy (spike C, log 10): requests to a workspace made two
  minutes before the deploy were still answered by the old code 33 s after the deploy returned, and that code
  restored the workspace's old snapshot into a new instance (`restored: "snapshot"`, an exec as uid 0, no layout
  mark). A workspace made 78 s after the deploy got the new code and image. Such an instance is in the state of
  the entry above once the new code takes over. Whether the delay belongs to that workspace's object or to the
  whole Worker was not told apart. How long the delay can last is not known. After a deploy that changes the
  layout, check a workspace before trusting it: an exec with no `root` flag must print a non-zero uid, and
  `cat /etc/plaza-runner-layout` as root must print the current mark. If either is wrong, replace its instance.

- **Routes can still wait behind a slow push and snapshot.** Each snapshot try is now cut off after 3 minutes and
  tried at most 3 times, one try per alarm, but a route queued behind the alarm can still wait for the push (up to
  5 minutes) and one snapshot try. A timed-out snapshot is not cancelled; its late result is ignored. What
  `snapshotContainer` answers to the retry while the first call is still in flight is not known; an error answer is
  final and drops the stored snapshot.
- **A finished run's unsaved work is destroyed if the intercepts cannot be registered after the object restarts**
  (independent read, 2026-11-15). When the object restarts while a run's push or snapshot is still pending and one
  registration of the intercepts then fails, `setUp` destroys the container, because no run is running. The pending
  push is then given up (`The container stopped before the branch was pushed`), or the pending snapshot is dropped
  and the next instance clones the branch. A running run in the same spot keeps its container and is retried. How
  often a registration fails is not known. Not fixed: keeping the container needs a rule for when to stop retrying.
- **A snapshot that fails drops the stored one even when nothing was pushed** (independent read, 2026-11-15). The
  rule is there so a later instance never restores files older than the pushed branch. But when a run's push was
  refused and its snapshot fails, or a new run starts before a pending snapshot is saved, the dropped snapshot was
  the only copy of the earlier commits: once the instance goes away, the next one clones the branch and they are
  gone. This is how the code is written and tested, so it needs the owner's ruling, not a fix by default.
- **The Worker holds the whole output of some commands the agent can influence** (independent read, 2026-11-15):
  what a git hook prints during a push (up to 5 minutes), the diff's stderr, and a test exec's output, which is cut
  to 64 KiB only after it was read whole. What the platform does when that outgrows the object's memory was not
  established. A pending push runs again on every refresh.
- **A timed-out exec may keep running in the container**, and `diff` can leave its temp index lock behind. One that
  runs as the agent (git in the clone) is ended by the next sweep of the agent's processes; one that runs as root
  is not. Seen on the deploy (spike C, log 14): an exec of `setsid -f sleep N` answered 500 after 30 s because the
  detached process kept the exec's output pipes open, and the process ran on.
- **The log of a running run trailed its output by up to 4 KiB.** Closed (c258fc4) and deployed 2026-11-17. The
  stdout copier was `head -c`, which writes through stdio, so the last events of a running task reached
  `stdout.log`, and with it the event log, only once more output came or the task ended. A tool call showed in the
  event log a minute or more late. The copier is now `stdbuf -o0 head -c`, and a container test reads a line
  while its task still sleeps. Nothing was lost before the fix: the buffer is written when the task ends. On the
  deploy since, a line written during a run's sleep was in the log in the same exec (spike C, log 17). Stage 2
  reads these events live.
- **The idle stop came later than 15 minutes after the last request.** Closed (cf868b2) and deployed
  2026-11-17. The 15-minute timeout starts only when the Durable Object has left memory, and each exec left a
  timer pending for its whole timeout (10 minutes for a clone, 5 for a push), which kept the object there. Seen
  twice (spike C, log 14): 25.5 minutes after the last request to a workspace that had only been cloned, and 18.5
  minutes after the last request to one whose run had ended. Each is 15 minutes after such a timer ran out, to
  within a minute. The cost was up to 10 minutes more of an idle instance per stop. The cause is inferred from
  those two stops and Cloudflare's lifecycle page. With the fix deployed, a workspace that was only cloned and one
  whose run had ended stopped 15.1 to 15.6 and 15.9 to 16.3 minutes after the last request (log 17), once each,
  which fits that cause.
- **A branch that moves during a run still ends in a push error** (PLZG-312). Every run ends with a push of the
  clone's HEAD. A branch that moved before the run is now picked up: a run starts with `git fetch` and a
  fast-forward (`git merge --ff-only`), and is refused (412 diverged, 502 fetch failed) when that cannot be done.
  One that moves while the run is going is refused by git (`fetch first`) at the closing push: the status carries
  `pushError`, although the run `succeeded` and had nothing to push. Seen on the deploy (spike C, log 17). The
  fast-forward and the container test (`test-container/sync.ctest.ts`) were not tried on the deploy.
- **A 412 has no way out but `DELETE`.** A clone with a commit on each side, an uncommitted file in the way of the
  fast-forward or a stale `.git/index.lock` answers 412 on every start, and each new instance restores the same
  clone from its snapshot. In stage 1 a run still started, so a prompt could tell the agent to rebase; now none
  does. The only exit today is `DELETE /workspaces/:name`, which destroys the unpushed commits, the uncommitted
  files and the conversation. `GET .../diff` shows the uncommitted changes but not the unpushed commits. The
  `run refused` event carries git's reason. A route that resets the clone is a separate follow-up. The bridge (`bridge/cloud_owner.py`) shows a 412 as
  `cloud_sync_failed` and a 409 as `cloud_run_active`, and has no way out of a 412 either.
- **A workspace that never ran has no snapshot.** Its files outside a commit are gone after the idle stop (seen in
  log 14: `restored: "branch"`, `uncommittedLost: true`). That is how it is built: a snapshot is taken when a run
  ends. Listed because a caller that writes files through the test exec route, or a later route, would lose them.
- **`--max-turns` is a hidden flag** of Claude Code 2.1.308. It is accepted and enforced (spike C, check T), but it is
  not in `--help`, so a later version could drop it without notice. Check T in `scripts/acceptance.mjs` would catch that.
- **DNS name leakage is unverified.** Every UDP/53 query gets one synthetic answer from a platform stub, so no packet
  reaches a real resolver directly. If the stub logs or forwards query names upstream, a process could carry data
  out in the labels of the names it looks up. To settle it, resolve a fresh random label under a zone the owner
  controls, then look for it in that zone's authoritative query log. This needs an owner-controlled zone and is owed.
- **A ten-minute run and an idle hour were not measured** (design §8 item 8). The idle cost is computed from
  published rates only, and the dashboard's billed figures are owed by the owner.
- **The workspace branch can still be force-pushed.** The push guard (f8c9d0a) lets a push update only
  `refs/heads/<workspace branch>` and never delete it, but it does not check that the update is a fast-forward, and it
  trusts git's wire format as GitHub reads it. GitHub branch rules remain the control for both.
- **Git LFS is refused** by the smart-HTTP-only rule.
- **Some branches of the shell scripts have no automated test.** The container tests (`npm run test:container`) now
  drive every shell script in `container.ts`: the task launcher, the copiers and both output caps, TERM and KILL, the
  alive probe, the sweep of the agent's processes and its refusal of root and of a missing user, the ranged read,
  the long-line probe, the diff and its cut at 1 MiB, and the refusal of a directory, a FIFO or a link in
  `stdout.log`'s place. Not driven: the "cannot read" refusal of `outputBytesScript` and `chunkScript` (the probes
  run as root, which can read any file, so the branch is not reached in the container), the sweep's answer when a
  process is left and its rule that a zombie is no process, the diff's failure paths, and the launcher's path for a
  setup that fails.
- **A process the agent starts in a new session (`setsid`) is ended by a sweep, not by the group KILL.** It leaves
  the task's process group and survives the group KILL. The sweep of the `agent` user's processes ends it when the
  run ends, before the output is read, and again before the push, before each snapshot try and before the next run
  ("Who runs what in the container"). What is left: on a stop, the sweep comes only after the wait for the output
  (up to 10 s, since such a process can hold the task's pipes open). If a sweep leaves a process or cannot run, the
  push and the snapshot still go ahead with it alive, and the instance is replaced after them. A process that a diff
  driver, a hook or the test `exec` route starts while no run is active lives until the next sweep, which is the
  next run's start or snapshot try. A process that a git hook starts during the push itself can change the clone
  while git reads it; it is ended before the snapshot. The sweep ran in a local container and under `wrangler dev`
  ("Local check"), not on the deploy.
- **A process-group id can be reused within one boot** after the group dies, so a late KILL could hit an unrelated
  group. The chance is low.
- **Three counted task-file failures end the run untrusted, and its work is lost on purpose.** Since PLZG-311 the
  agent cannot write the task files, so this is a second line of defence, not something an agent can set off by
  replacing a file. A task-file failure
  (`TaskFileError`) is an answer from the container showing a file is not what the runner wrote: a read of the pid or
  exit-code file that fails with one of a listed set of file-level errors (`EISDIR`, `ENOTDIR`, `ELOOP`, `ENXIO`,
  `EACCES`, `EPERM`), an exit-code file that is not one decimal status from 0 to 255 and a newline (G6), or a
  `stdout.log` probe script that exits with its own refusal code, `TASK_FILE_REFUSED` (64), because the file exists
  but is not a regular file (a directory, a FIFO) or fails its `test -r`. Any other exit of a probe (137, 143, 126,
  127 and the rest) and any other error code (`EIO`, `ENOSPC`, `UNKNOWN`) is a plain error. A check that ends in a
  task-file failure counts at most once per check interval (60 s), however often status is polled, and a check whose
  probes all answer resets the count. At `TASK_FILE_FAILURE_LIMIT` (3) counted failures the run ends `failed` with
  `TASK_FILES_ERROR`; one inside a stop ends it `stopped` at once. Either way the stored group is KILLed, the instance
  is replaced with no push or snapshot, and the stored snapshot is marked stale. Nothing the task wrote is trusted,
  and a snapshot holds the whole root filesystem the next run starts from, so saving it would carry whatever the agent
  planted into later runs. No plain error leads to this end.
- **Every other failure is retried, and the 60-minute cap ends the run.** An exec timeout, a container that is
  stopping or restarting, or a transport error leaves the run `running` and destroys nothing; the next check or alarm
  tries again, and a stop answers 409 "try again" rather than report a task stopped that may be alive. A run that
  exited and hit such a failure while finishing ends normally, pushed, on the retry. An overdue run whose exit code
  can be read is finished as usual. A plain failure while ending an overdue run is retried too, counted at most once
  per check interval; at `OVERDUE_ATTEMPT_LIMIT` (3) the stored group gets a best-effort KILL and the run ends
  `failed` with `MAX_RUN_ERROR` with no further probes, its branch still pushed and snapshotted (G1). After the
  Durable Object restarts, a failure to register the intercepts again keeps a running run's container (with no
  intercepts it has no Internet, so it fails closed) and is retried; once the run is overdue the same count applies,
  and at the limit the container is destroyed and the run ends `lost` with no push, since a push needs the intercepts
  (G4). An agent can still stay `running` until the cap without a task-file failure, for example by starving the
  container so execs time out, or by making a read hang. A failed `stdout.log` read in `events()` answers 500, and one
  in the alarm's ingest while the run is live is logged and re-armed; neither counts toward either limit.
- **One of the fixes' failure paths was not provoked on the deploy: a snapshot that times out.** It rests on the
  unit tests. An unreadable task file and an oversized result were provoked on 2026-11-17 and ended as written
  above (spike C, log 14). The oversized lines were written by root into the task's output, and the agent was then
  KILLed so that the line was the last result; Claude Code itself never produced such a line.

### Notes on the evidence itself (from the last review, 2026-11-15)

- The refusal of a snapshot with another layout (PLZG-311) was shown on changed copies of a current instance:
  locally with the layout mark overwritten with `1`, and on the deploy with the mark removed, which is how a
  snapshot from the earlier image looks to the check (spike C, log 11). No snapshot really built from the earlier
  image was refused by the new code. One attempt was made at the 2026-11-15 redeploy: a workspace with a snapshot
  from the old image was left with no instance, and started again after the deploy. The old code answered that
  start (see the known gaps), so it restored the snapshot and showed nothing about the refusal. The old image is no
  longer deployed, so the attempt cannot be repeated as it was.

- `scripts/redeploy.mjs` is a rewrite of the scratch script that produced the first redeploy log (spike C, log 5).
  The committed version produced logs 7 and 9. Run it under the same memory cap as any deploy.
- The cause given for the refused bare host root (the intercept passing `https://host` without its slash) is inferred
  from the code and a local reproduction, not seen in a log. The fix rests on that cause and on unit tests of
  `decide`; a bare root has not been fetched on the deploy since. Acceptance check `R` now fetches
  `https://registry.npmjs.org` and fails if the answer is not 200.
- The sweep of the agent's processes is shown in a local container (`test-container/task-end.ctest.ts`): a
  `setsid` child survives the group KILL and is gone after the sweep, root's processes are untouched, and a sweep
  with no group KILL before it makes the leader record 137. On the deploy, acceptance check `S` shows the sweep
  before a run's start twice (spike C, logs 13 and 16). A sweep that leaves a process could not be produced in a container
  or on the deploy; that path rests on unit tests with a fake host.
- Acceptance check `S` was wrong as first written: it planted its process with the exec's output attached, which
  returned at once under `wrangler dev` and timed out on the deploy. The check passed locally and failed on its
  first run against the deploy, in its setup. It was corrected, passed alone, and then passed in the full suite on
  the next deploy (spike C, log 16).
- The account of the buffered copier has one point it does not explain: in a first attempt a 5 MB line reached
  the event log four minutes after it was written, with the agent still asleep (spike C, Surprises). The local
  reproduction and the container test carry the mechanism.
- The live tests of 2026-11-17 (spike C, log 14) were run once each, by a one-off script that is not in the
  repository. The instance counts come from `wrangler containers info`, read once a minute, so each stop is known
  to within a minute. The checks of the two fixes on the deploy (log 17) were run once each as well, with the
  count read every half minute. The count rose about 50 s after an instance started, so a stop may show that
  much late; the earlier figures were read the same way. Which of the two instances stopped first is taken from
  the order of their last requests, since the count does not name them.
- The two 409 rows in "Local check" quote the text as it was on the day of each check.
- The six areas Copilot's review summaries named without a finding (PLZG-311, review coverage) were read once on
  2026-11-15 by a separate Claude session that was given the code and the area names, not by a person. Push size
  and the task's validation showed no defect. The others are the three entries above marked "independent read", the
  diff that replaced an instance (fixed), the missing result line behind a process that holds the pipes (fixed by
  the sweep), and what was already listed. Each was checked against the code before it was written here; only the
  two fixed ones have a test that fails without the fix.
- The raw TCP and UDP probes target IPv4 only, although the container's resolver configuration lists an IPv6 server.
- The process-environment scan in check 4 ran while no agent was alive, so the agent process's own environment was
  scanned only in the local check.
- Check 3 now needs the live npm registry to answer.
