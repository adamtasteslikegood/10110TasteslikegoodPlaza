# Spike C: Claude Code in a Cloudflare Sandbox container (M14 stage 1 deploy)

Run on 2026-11-15 against the development deploy of `cloud-runner/` (PLZG-310).
**Research evidence**, not a product decision. Design:
[2026-11-14-m14-cloudflare-runner-design.md](../../superpowers/specs/2026-11-14-m14-cloudflare-runner-design.md) §7–§9.

## What was deployed

- Worker `plaza-cloud-runner-dev` at `https://plaza-cloud-runner-dev.adamschoen3.workers.dev`,
  from branch `feature/m14-cloudflare-runner-design` at ad8d318 (runner code as of 424662b).
  Acceptance ran on version `60c801fe-cf10-42ef-b931-f423a64f967f`. The redeploy test made
  version `6b2f1b8a-d7b7-4e94-885c-5593922e6fd9`, which is the live version (same code, same image).
- One container application, `plaza-cloud-runner-dev-workspace` (class `Workspace`, `durable_object`
  scheduling, instance `standard-1`, Internet off), image built from `cloud-runner/Dockerfile`:
  `node:24-trixie-slim`, git, ripgrep, `@anthropic-ai/claude-code@2.1.308`, the sandbox shim 1.0.3.
- wrangler 4.162.0, `@cloudflare/sandbox` 1.0.3, model `claude-sonnet-5-5` through AI Gateway
  `my-cf-agent-gateway` (BYOK Anthropic key, alias `default`).
- Test repository `adamtasteslikegood/ArtazZen-recipes-TanStack-showcase`, branch
  `cloud-runner/acceptance` (made from `main` at 80f5ccb). No run touched `main`.

## Acceptance output

`node scripts/acceptance.mjs <url>` (full run; check 3 re-run after its DNS criterion was corrected, see
Surprises). Cleanup lines are trimmed.

```
FAIL H claude --help in the image lists --session-id, --resume, --max-turns: not in --help: --max-turns
NOTE cost check 1 run 1: events span 15.361 s; result duration_ms=7507 num_turns=2 input=4 output=418 cache_read=16402 cache_write=16620 total_cost_usd=0.0474 model=claude-sonnet-5-5
NOTE pushed.commit ffb08a24fc8ade937112242390f3ef3a90151973; ls-remote ffb08a24fc8ade937112242390f3ef3a90151973
PASS 1 a prompt runs to completion, writes and pushes NOTES.md
NOTE cost check 2 run 2: events span 55.114 s; result duration_ms=49146 num_turns=2 input=4 output=54 cache_read=33531 cache_write=381 total_cost_usd=0.0522 model=claude-sonnet-5-5
NOTE check 2: 12 events read incrementally, same as one full read; run ended succeeded
PASS 2 events read twice agree, after=next never repeats, a second start answers 409
NOTE http://example.com: 403
NOTE push to octocat/Hello-World: exit 128, fatal: unable to access 'https://github.com/octocat/Hello-World/': The requested URL returned error: 403
NOTE raw TCP 1.1.1.1:53: timeout   (also :22, :25, :8080: timeout)
NOTE UDP DNS example.com via 1.1.1.1: answered 11.9.0.1; via 192.0.2.1 (TEST-NET): answered 11.9.0.1; nx-fe08d4.example.invalid via 1.1.1.1: answered 11.9.0.1
NOTE UDP NTP to 162.159.200.1:123: no reply
NOTE system resolver for example.com: resolved fd00::119:1
PASS 3 egress: unlisted host 403, push elsewhere refused, own repository reachable, no raw TCP or UDP
NOTE scanned 1343 bytes of container output and 12 events
PASS 4 no credential in env, .git/config, ~/.gitconfig, home, /workspace or check 1's events
NOTE right after both starts: acc-a49ef1-a running, acc-a49ef1-b running
NOTE cost check 5 a run 3: events span 8.637 s; ... total_cost_usd=0.0541
NOTE cost check 5 b run 1: events span 8.897 s; ... total_cost_usd=0.0108
PASS 5 two workspaces run at once and do not see each other's files
NOTE scratch.txt before replacement: "42"; pushError none
NOTE run 4 runner notices: run started, run ended, pushed, snapshot saved
NOTE cost check 6 run 5: events span 9.017 s; ... total_cost_usd=0.0702
NOTE check 6: restored=snapshot uncommittedLost=false instance note={"notice":"instance started","generation":2,"from":"snapshot"}; session same (d35eb7cf-...); reports 42: true; reports heliotrope: true; state succeeded
PASS 6 after replace-instance the snapshot restores an uncommitted file
NOTE stop answered stopped in 3.956 s
NOTE after replace-instance mid-run: lost (The container stopped before the run ended), pushError none
NOTE run after lost: generation 3, restored snapshot, uncommittedLost false
PASS 7 stop interrupts a run; a replaced instance mid-run reports lost; both accept the next run
NOTE DELETE acc-a49ef1-a: 204; then GET 200 {"state":"none","run":0,"generation":0}
```

| # | Check | Result |
|---|---|---|
| H | `claude --help` lists `--session-id`, `--resume`, `--max-turns` | FAIL: `--max-turns` is hidden (accepted, not listed) |
| 1 | prompt runs, writes NOTES.md, push lands (checked with `git ls-remote`) | PASS |
| 2 | event reads are stable, `after=next` never repeats, second start 409 | PASS |
| 3 | egress: 403 off-list (HTTPS and HTTP), other repo refused, own repo works, no raw TCP/UDP | PASS (criterion corrected, see below) |
| 4 | no credential in env, git config, home, `/workspace` or events | PASS |
| 5 | two containers at once, isolated files | PASS |
| 6 | replace-instance: snapshot restores an uncommitted file and the conversation | PASS |
| 7 | stop; lost after a mid-run replacement; next run accepted | PASS |
| d | detached task survives a Worker redeploy mid-run (by hand) | PASS |
| e | longest run exercised | about 160 s; the 15-minute idle timeout was **not exercised** |

Redeploy check (d), with `node redeploy.mjs` from a scratch directory: a run of `sleep 150` started; 20 s in, `wrangler deploy`
(nothing changed, "Image already exists remotely, skipping push") made a new version in 11 s. The status stayed
`running`, generation 1 (the same instance). The run ended `succeeded` after 154 s with `/workspace/task/exit-code` = `0`,
then `pushed` and `snapshot saved`.

The first PUT after the deploy answered 200 every time (five workspaces), so the one-time 500 seen under `wrangler dev`
did not appear here.

## The four questions

1. **Does Claude Code run in a Sandbox container?** Yes. 2.1.308 runs headless (`--print --output-format
   stream-json --verbose`) as a detached task, writes files, commits, and the Worker pushes. Turn limits work through
   the hidden `--max-turns`. `--session-id` and `--resume` are listed.
2. **Which login path?** No Anthropic credential enters the container. The CLI gets `ANTHROPIC_API_KEY=provided-by-worker`
   (a placeholder) and `ANTHROPIC_BASE_URL` set to the gateway's provider-native route
   `https://gateway.ai.cloudflare.com/v1/<account>/my-cf-agent-gateway/anthropic`. The `Outbound` entrypoint drops the
   placeholder `x-api-key`, then adds `cf-aig-authorization: Bearer <AI_GATEWAY_TOKEN>` and `cf-aig-skip-cache`. The
   gateway serves the request with the stored BYOK key (no `cf-aig-byok-alias` header is needed). The gateway accepted
   `claude-sonnet-5-5`, and every run's `modelUsage` named it. GitHub smart-HTTP is the only git traffic let through,
   with Basic `x-access-token` added at the same entrypoint.
3. **Does the conversation resume after the instance is replaced?** Yes, from the snapshot. After `replace-instance`
   the new instance (generation 2) came from the snapshot, `scratch.txt` (uncommitted) was there, and the next run's
   `system`/`init` event carried the same `session_id`. The model recalled a word given only in the earlier run. After a
   mid-run replacement, the run is `lost`, and the next run starts from the last snapshot (generation 3, `restored:
   snapshot`).
4. **What does it cost?** See below.

## Cost (check 8)

**Measured** (from `result` events, Claude Code's own `total_cost_usd`, computed by the CLI from the token counts at
list price, not a gateway invoice):

| Run | Wall (event timestamps) | Turns | Output tokens | Cache read / write | USD |
|---|---|---|---|---|---|
| check 1 (write, commit) | 15 s | 2 | 418 | 16,402 / 16,620 | 0.047 |
| check 2 (`sleep 45`) | 55 s | 2 | 54 | 33,531 / 381 | 0.052 |
| check 5 a / b ("ok") | 9 s / 9 s | 1 / 1 | 4 / 4 | 17,001 / 48 and 12,565 / 3,808 | 0.054 / 0.011 |
| check 6 run 5 (recall) | 9 s | 1 | 52 | 17,892 / 271 | 0.070 |
| redeploy (`sleep 150`) | 160 s | 2 | — | — | 0.014 |

The six runs with a result total about **$0.25**. The remaining runs (check 6 run 4, and check 7's three runs, which were
stopped or lost) wrote no `result` event, so their cost is not measured. Even a one-word reply reads about 12–18k
cached tokens of system prompt, so model cost per run has a floor of roughly 1–7 cents, depending on cache writes.

**Computed** from design §9 (a `standard-1` instance costs about $0.04/h idle and up to about $0.075/h at full CPU;
snapshots are free in beta):

- a 15 s run: about $0.0002–0.0003 of container time; the 160 s run: about $0.0018–0.0033;
- an instance left to the 15-minute idle stop after a run: about $0.01 more;
- an hour of continuous agent work: about $0.04–0.075 for the container, which is small next to the model cost.

The Cloudflare dashboard's billed figures (Containers, AI Gateway logs) are left for the owner to read.

## Surprises

- **DNS answers come from a local stub.** Every UDP/53 query is answered with the same synthetic address
  (11.9.0.1), whatever the destination (1.1.1.1, 8.8.8.8, unroutable 192.0.2.1) and whatever the name, a `.invalid`
  one included. `/etc/resolv.conf` lists 1.1.1.1 and 9.9.9.9. UDP to other ports (NTP 123, 9999) gets no reply, and raw
  TCP times out on 22, 25, 53 and 8080. This is how the platform routes hostnames to the HTTP intercept. The first
  version of check 3 counted any DNS answer as a leak and failed; the check now fails only on signs of a real
  resolver (an NXDOMAIN, or 1.1.1.1 answering differently from TEST-NET). The probe cannot rule out the stub
  forwarding query names upstream; that would be a DNS exfiltration channel to keep in mind.
- **`--max-turns` is a hidden flag** in Claude Code 2.1.308: it is accepted (an unknown flag gives "unknown option";
  this one does not) but not listed in `--help`. Check H was left strict and fails.
- **npm skips claude-code's postinstall** (`install.cjs`) under its allow-scripts policy during the image build. The CLI
  still works: the wrapper finds `bin/claude.exe`.
- **The deploy needs a working Docker credential store.** Here the configured `pass` store was empty, so `docker
  login` to `registry.cloudflare.com` failed. The deploy ran with a throwaway `DOCKER_CONFIG` (empty `{}`) and
  `DOCKER_HOST` set to the Docker Desktop socket, then that directory was deleted.
- **A 401 on `containers/image-preparations`** came after a 3-minute first image push, although the OAuth token has
  `containers:write`. The retry, with the layers already uploaded, succeeded. The likely cause is an access token that
  expired during the push.
- **`wrangler secret put` creates the Worker** when none exists. In a non-interactive shell it answers its own
  "create a new Worker?" prompt with yes.
- **Snapshots pile up.** Every ended run takes one. Ten `rootfs-snapshot-*` images were left in the registry after
  these checks. They cannot be deleted through the API and expire 30 days after they were taken or last restored.
- **`stop` took about 4 s** on the deploy, against 0.25–2 s locally.
