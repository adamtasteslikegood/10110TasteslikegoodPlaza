# Plaza cloud runner

A Cloudflare Worker that runs Claude Code on one GitHub branch inside a
Sandbox container, one container per workspace (M14 stage 1). Callers drive it
over HTTP with `Authorization: Bearer <RUNNER_CALLER_SECRET>`; the `Workspace`
Durable Object clones the branch, starts runs in the background, keeps their
stream-json output as numbered events, and reports `running`, `succeeded`,
`failed`, `stopped` or `lost`. The container has no Internet access of its
own: every request goes through the `Outbound` entrypoint, which adds the
credentials, so none enters the container.

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
| `c GET '/workspaces/plain/events?after=0'` | 200 `{"events":[],"next":0}` |
| `c POST /workspaces/plain/runs '{"prompt":"Say hello in one word.","maxTurns":2}'` | 202 `{"run":1}` |
| a second POST runs during it | 409 `A run is already active` |
| `c GET /workspaces/plain` after the run ended (about 3 min of retries) | 200 `{"state":"failed","run":1,...,"error":"Failed to authenticate. API Error: 401 Unauthorized"}` |
| the next POST runs | 202 `{"run":2}`, started with `--resume <run 1's session id>` |
| a run on workspace `alarm` with no request for 290 s, then `events?after=0` | the `run ended` runner event (`state: failed`) is stamped 08:01:12, 50 s before the request at 08:02:02: the 60 s alarm finished the run |
| `docker kill` of the container during run 2, then `c GET /workspaces/plain` | 200 `{"state":"lost","run":2,"generation":1,...,"error":"The container stopped before the run ended"}` |
| the next POST runs | 202 `{"run":3}`; status shows `generation: 2`, the branch was cloned again and the run started with a new `--session-id` |
| `c POST /workspaces/hello/stop` six seconds into a run | 200 `{"state":"stopped",...}` in 0.25 s; the task's exit code was 143 (TERM) |
| `c GET /workspaces/hello/diff` after editing `README` and adding `NEW.txt` in the clone | 200, a `git diff` showing both, the new file included |
| `c GET /workspaces/never`, `c GET /workspaces/never/diff` | 200 `{"state":"none","run":0,"generation":0}`; 404 `No such workspace: create it with PUT first` |
| `c DELETE /workspaces/hello`, then `c GET '/workspaces/hello/events?after=0'` | 204; 404, and the container is gone |

Egress, checked with `docker exec <container> node -e "fetch(...)"` and
`NODE_EXTRA_CA_CERTS=/etc/cloudflare/certs/cloudflare-containers-ca.crt`, not
through any route of the Worker:

- Workspace `plain` (no `allow`): `https://example.com/` and `http://example.com/`
  answer 403 `example.com is not reachable from this sandbox`.
- Workspace `hello` (`"allow": ["example.com"]`): `https://example.com/` answers
  200, `https://example.org/` 403, and `github.com/octocat/Spoon-Knife` (another
  repository) 403.
- The container's environment holds no token, secret or `Authorization`, and
  the clone's remote is the plain `https://github.com/octocat/Hello-World`.

The props passed with `ctx.exports.Outbound({ props: { repoPath, allow } })`
reach the intercept under wrangler dev: the clone of the workspace's own
repository passed, another repository was refused, and only the workspace
that allowed `example.com` could reach it. No fallback was needed.
