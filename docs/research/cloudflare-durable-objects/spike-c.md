# Spike C: Claude Code in a Cloudflare Sandbox container (M14 stage 1 deploy)

Run on 2026-11-15 against the development deploy of `cloud-runner/` (PLZG-310).
**Research evidence**, not a product decision. Design:
[2026-11-14-m14-cloudflare-runner-design.md](../../superpowers/specs/2026-11-14-m14-cloudflare-runner-design.md) §7–§9.

## What was deployed

- Worker `plaza-cloud-runner-dev` at `https://plaza-cloud-runner-dev.adamschoen3.workers.dev`,
  from branch `feature/m14-cloudflare-runner-design` at ad8d318 (runner code as of 424662b).
  Acceptance ran on version `60c801fe-cf10-42ef-b931-f423a64f967f`. The redeploy test made
  version `6b2f1b8a-d7b7-4e94-885c-5593922e6fd9` (same code, same image). Review fix round 1 set
  `preview_urls: false` and redeployed once: version `374b2faf-a019-4a19-b52d-86b814d14029` is live
  (same runner code and image; the image push was skipped). Its checks ran on that version.
- One container application, `plaza-cloud-runner-dev-workspace` (class `Workspace`, `durable_object`
  scheduling, instance `standard-1`, Internet off), image built from `cloud-runner/Dockerfile`:
  `node:24-trixie-slim`, git, ripgrep, `@anthropic-ai/claude-code@2.1.308`, the sandbox shim 1.0.3.
- wrangler 4.162.0, `@cloudflare/sandbox` 1.0.3, model `claude-sonnet-5-5` through AI Gateway
  `my-cf-agent-gateway` (BYOK Anthropic key, alias `default`).
- Test repository `adamtasteslikegood/ArtazZen-recipes-TanStack-showcase`, branch
  `cloud-runner/acceptance` (made from `main` at 80f5ccb). No run touched `main`: `git ls-remote <repo>
  refs/heads/main` gave `80f5ccb8968eacd2f6d68740e1990d2076671c10` before and after the round 1 runs (log 3).

## Acceptance output

Each block is a log file kept in the owner's checkout under `cloud-runner/.dev/`, pasted unchanged. The script's own
redaction applies (no credential appears in any of them). Command:
`TEST_REPO=... TEST_BRANCH=cloud-runner/acceptance [ONLY=...] node scripts/acceptance.mjs <url>`.

**Log 1, `acc1.log`: the full suite, first run** (version 60c801fe). Check 3 failed here on its first DNS criterion,
and the script exited 1.

```
NOTE workspaces acc-a49ef1-a and acc-a49ef1-b, branch cloud-runner/acceptance
NOTE PUT acc-a49ef1-a: generation 1, state idle
NOTE claude --version: 2.1.308 (Claude Code)
FAIL H claude --help in the image lists --session-id, --resume, --max-turns: not in --help: --max-turns
NOTE cost check 1 run 1: events span 15.361 s; result duration_ms=7507 num_turns=2 input=4 output=418 cache_read=16402 cache_write=16620 total_cost_usd=0.047378199999999995 model=claude-sonnet-5-5
NOTE pushed.commit ffb08a24fc8ade937112242390f3ef3a90151973; ls-remote ffb08a24fc8ade937112242390f3ef3a90151973
PASS 1 a prompt runs to completion, writes and pushes NOTES.md
NOTE cost check 2 run 2: events span 55.114 s; result duration_ms=49146 num_turns=2 input=4 output=54 cache_read=33531 cache_write=381 total_cost_usd=0.0522318 model=claude-sonnet-5-5
NOTE check 2: 12 events read incrementally, same as one full read; run ended succeeded
PASS 2 events read twice agree, after=next never repeats, a second start answers 409
NOTE http://example.com: 403
NOTE push to octocat/Hello-World: exit 128, fatal: unable to access 'https://github.com/octocat/Hello-World/': The requested URL returned error: 403
NOTE raw TCP 1.1.1.1:53: timeout
NOTE raw TCP 1.1.1.1:22: timeout
NOTE raw TCP 1.1.1.1:25: timeout
NOTE raw TCP 1.1.1.1:8080: timeout
NOTE UDP DNS to 1.1.1.1: answered 1
FAIL 3 egress: unlisted host 403, push elsewhere refused, own repository reachable, no raw TCP or UDP: a DNS query over UDP to 1.1.1.1 was answered
NOTE scanned 1343 bytes of container output and 12 events
PASS 4 no credential in env, .git/config, ~/.gitconfig, home, /workspace or check 1's events
NOTE right after both starts: acc-a49ef1-a running, acc-a49ef1-b running
NOTE cost check 5 a run 3: events span 8.637 s; result duration_ms=1962 num_turns=1 input=2 output=4 cache_read=17001 cache_write=48 total_cost_usd=0.0540959 model=claude-sonnet-5-5
NOTE cost check 5 b run 1: events span 8.897 s; result duration_ms=2272 num_turns=1 input=2 output=4 cache_read=12565 cache_write=3808 total_cost_usd=0.0108205 model=claude-sonnet-5-5
PASS 5 two workspaces run at once and do not see each other's files
NOTE scratch.txt before replacement: "42"; pushError none
NOTE run 4 runner notices: run started, run ended, pushed, snapshot saved
NOTE cost check 6 run 5: events span 9.017 s; result duration_ms=2117 num_turns=1 input=2 output=52 cache_read=17892 cache_write=271 total_cost_usd=0.0702005 model=claude-sonnet-5-5
NOTE check 6: restored=snapshot uncommittedLost=false instance note={"notice":"instance started","generation":2,"from":"snapshot"}; session same (d35eb7cf-8ba1-4dec-8ea2-4f7c24058f21); reports 42: true; reports heliotrope: true; state succeeded
NOTE check 6 answer: "You asked me to remember **heliotrope**. `scratch.txt` contains `42`. I wrote that myself earlier and haven't re-read the file since."
PASS 6 after replace-instance the snapshot restores an uncommitted file
NOTE stop answered stopped in 3.956 s
NOTE after replace-instance mid-run: lost (The container stopped before the run ended), pushError none
NOTE run after lost: generation 3, restored snapshot, uncommittedLost false
PASS 7 stop interrupts a run; a replaced instance mid-run reports lost; both accept the next run
NOTE DELETE acc-a49ef1-a: 204; then GET 200 {"state":"none","run":0,"generation":0}
NOTE DELETE acc-a49ef1-b: 204; then GET 200 {"state":"none","run":0,"generation":0}
script exit 1
```

**Log 2, `acc3.log`: check 3 re-run (`ONLY=3`) after its DNS criterion was corrected in ad8d318** (see Surprises).

```
NOTE workspaces acc-fe08d4-a and acc-fe08d4-b, branch cloud-runner/acceptance
NOTE PUT acc-fe08d4-a: generation 1, state idle
NOTE http://example.com: 403
NOTE push to octocat/Hello-World: exit 128, fatal: unable to access 'https://github.com/octocat/Hello-World/': The requested URL returned error: 403
NOTE raw TCP 1.1.1.1:53: timeout
NOTE raw TCP 1.1.1.1:22: timeout
NOTE raw TCP 1.1.1.1:25: timeout
NOTE raw TCP 1.1.1.1:8080: timeout
NOTE UDP DNS example.com via 1.1.1.1: answered 11.9.0.1; via 192.0.2.1 (TEST-NET): answered 11.9.0.1; nx-fe08d4.example.invalid via 1.1.1.1: answered 11.9.0.1
NOTE UDP NTP to 162.159.200.1:123: no reply
NOTE system resolver for example.com: resolved fd00::119:1
PASS 3 egress: unlisted host 403, push elsewhere refused, own repository reachable, no raw TCP or UDP
NOTE DELETE acc-fe08d4-a: 204; then GET 200 {"state":"none","run":0,"generation":0}
NOTE DELETE acc-fe08d4-b: 204; then GET 200 {"state":"none","run":0,"generation":0}
script exit 0
```

**Log 3, `acc-r1.log`: review fix round 1, `ONLY=H,T,3,4`** (version 374b2faf). Check T (new) and check 4 (now
scanning every process's environ) passed. Check 3 failed on a new probe: the bare root of an allowed host is refused
(see Surprises), so the probe now asks for `/left-pad`.

```
NOTE workspaces acc-864a85-a and acc-864a85-b, branch cloud-runner/acceptance
NOTE ls-remote main before the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE PUT acc-864a85-a: generation 1, state idle
NOTE claude --version: 2.1.308 (Claude Code)
NOTE claude --max-turns 1 --version: exit 0 2.1.308 (Claude Code)
NOTE claude --no-such-flag-xyz --version: exit 0 2.1.308 (Claude Code)
FAIL H claude --help in the image lists --session-id, --resume, --max-turns: not in --help: --max-turns
NOTE cost check T run 1: events span 14.028 s; result duration_ms=9499 num_turns=2 input=2 output=47 cache_read=0 cache_write=16401 total_cost_usd=0.0414765 model=claude-sonnet-5-5
NOTE check T: state failed, error "error_max_turns", result subtype error_max_turns, is_error true, num_turns 2, tool calls 1
PASS T maxTurns 1 stops a run that needs two tool calls (result subtype error_max_turns)
NOTE http://example.com: 403
NOTE https://registry.npmjs.org/: 403; http://registry.npmjs.org/: 403
FAIL 3 egress: unlisted host 403, plain HTTP refused, push elsewhere refused, own repository reachable, no raw TCP, no direct UDP (DNS name leakage not tested): https://registry.npmjs.org answered 403: the allowed host is not reachable, so the HTTP refusal proves nothing
NOTE scanned 1343 bytes of container output, the environ of 3 processes (880 bytes) and 8 events (check 1's: 0)
PASS 4 no credential in env, any process's environ, .git/config, ~/.gitconfig, home, /workspace or the workspace's events
NOTE ls-remote main after the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE DELETE acc-864a85-a: 204; then GET 200 {"state":"none","run":0,"generation":0}
NOTE DELETE acc-864a85-b: 204; then GET 200 {"state":"none","run":0,"generation":0}
```

**Log 4, `acc-r1b.log`: round 1, `ONLY=H,3`, with the corrected probes.** No model call. It also keeps the output of
the ad hoc probes behind Surprises (8.8.8.8, UDP 9999, `/etc/resolv.conf`, an unknown flag).

```
NOTE workspaces acc-7bc536-a and acc-7bc536-b, branch cloud-runner/acceptance
NOTE ls-remote main before the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE PUT acc-7bc536-a: generation 1, state idle
NOTE claude --version: 2.1.308 (Claude Code)
NOTE claude -p --max-turns 1 </dev/null: exit 1 Error: Input must be provided either through stdin or as a prompt argument when using --print
NOTE claude -p --no-such-flag-xyz </dev/null: exit 1 error: unknown option '--no-such-flag-xyz'
FAIL H claude --help in the image lists --session-id, --resume, --max-turns: not in --help: --max-turns
NOTE http://example.com: 403
NOTE https://registry.npmjs.org/left-pad: 200; http://registry.npmjs.org/left-pad: 403
NOTE push to octocat/Hello-World: exit 128, fatal: unable to access 'https://github.com/octocat/Hello-World/': The requested URL returned error: 403
NOTE raw TCP 1.1.1.1:53: timeout
NOTE raw TCP 1.1.1.1:22: timeout
NOTE raw TCP 1.1.1.1:25: timeout
NOTE raw TCP 1.1.1.1:8080: timeout
NOTE UDP DNS example.com via 8.8.8.8: answered 11.9.0.1
NOTE /etc/resolv.conf: "nameserver 1.1.1.1\nnameserver 9.9.9.9\nnameserver 2606:4700:4700::1111"
NOTE UDP DNS example.com via 1.1.1.1: answered 11.9.0.1; via 192.0.2.1 (TEST-NET): answered 11.9.0.1; nx-7bc536.example.invalid via 1.1.1.1: answered 11.9.0.1
NOTE UDP NTP to 162.159.200.1:123: no reply
NOTE UDP to 1.1.1.1:9999: no reply
NOTE system resolver for example.com: resolved fd00::119:1
PASS 3 egress: unlisted host 403, plain HTTP refused, push elsewhere refused, own repository reachable, no raw TCP, no direct UDP (DNS name leakage not tested)
NOTE ls-remote main after the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE DELETE acc-7bc536-a: 204; then GET 200 {"state":"none","run":0,"generation":0}
NOTE DELETE acc-7bc536-b: 204; then GET 200 {"state":"none","run":0,"generation":0}
```

**Log 5, `redeploy.log`: check (d)**, then run by hand; it is now `cloud-runner/scripts/redeploy.mjs`.

```
0s PUT 200
2s run {"run":1}
23s before redeploy running gen 1
34s redeploy 0 version 6b2f1b8a-d7b7-4e94-885c-5593922e6fd9 image unchanged
34s after redeploy running gen 1
165s ended succeeded gen 1 result "done"
166s task files: "0\n\ntotal 20\ndrwxr-xr-x 1 root root   64 Nov 15 16:48 .\ndrwxr-xr-x 1 root root   16 Nov 15 16:46 ..\n-rw-r--r-- 1 root root    2 Nov 15 16:48 exit-code\n-rw-r--r-- 1 root root   40 Nov 15 16:46 pid\n-rw-r--r-- 1 root root    0 Nov 15 16:46 stderr.log\n-rw-r--r-- 1 root root 8372 Nov 15 16:48 stdout.log\n"
notices: run started, run ended, pushed, snapshot saved
result: duration_ms 154387 turns 2 cost 0.013517999999999999
166s DELETE 204
```

| # | Check | Result |
|---|---|---|
| H | `claude --help` lists `--session-id`, `--resume`, `--max-turns` | FAIL: `--max-turns` is hidden. It is accepted, and an unknown flag is refused (log 4) |
| 1 | prompt runs, writes NOTES.md, push lands (checked with `git ls-remote`) | PASS |
| T | `maxTurns: 1` on a prompt that needs two tool calls | PASS: result subtype `error_max_turns`, state `failed` after 1 tool call (log 3) |
| 2 | event reads are stable, `after=next` never repeats, second start 409 | PASS |
| 3 | egress: 403 off-list, plain HTTP refused (also to an allowed host), other repo refused, own repo works, no raw TCP, no direct UDP | **PASS (direct UDP); DNS name leakage unverified.** It failed on its first criterion (log 1) and passed after the correction (logs 2, 4) |
| 4 | no credential in env, any process's `/proc/*/environ`, git config, home, `/workspace` or events | PASS (logs 1, 3) |
| 5 | two containers at once, isolated files | PASS |
| 6 | replace-instance: snapshot restores an uncommitted file and the conversation | PASS |
| 7 | stop; lost after a mid-run replacement; next run accepted | PASS |
| d | detached task survives a Worker redeploy mid-run | PASS (log 5) |
| e | longest run exercised | about 160 s; the 15-minute idle timeout was **not exercised** |
| 8 | measured cost of a ten-minute run and an idle hour (design §8 item 8) | **NOT MEASURED:** no ten-minute run was made; the idle hour is computed from published rates; the dashboard's billed figures are owed by the owner. Short runs are measured under Cost |

In check (d), a run of `sleep 150` started. 20 s in, `wrangler deploy` made a new version in 11 s. Nothing had
changed, and wrangler printed "Image already exists remotely, skipping push". The status stayed `running` at
generation 1, the same instance. The run ended `succeeded` after 154 s, with `/workspace/task/exit-code` = `0`,
then `pushed` and `snapshot saved`.

The first PUT after a deploy answered 200 every time (seven workspaces), so the one-time 500 seen under
`wrangler dev` did not appear here.

### Owed: does a query name leave the platform?

Check 3 shows that no UDP packet from the container reaches a real resolver directly. Every UDP/53 query gets the
same synthetic answer, whatever the destination or the name. It does **not** show that query names stay inside
Cloudflare. If the stub logs or forwards names upstream, DNS is an exfiltration channel: a process could encode data
in the labels of the names it looks up. The test that settles it:

1. In the container, resolve a fresh random label under a zone the owner controls, for example
   `<random>.probe.<owner-zone>`.
2. Look for that label in the zone's authoritative query log.

If the label appears, names leak. This test needs an owner-controlled zone with query logging and was not run.

## The four questions

1. **Does Claude Code run in a Sandbox container?** Yes. 2.1.308 runs headless (`--print --output-format
   stream-json --verbose`) as a detached task, writes files, commits, and the Worker pushes. The hidden `--max-turns` is
   enforced: with `maxTurns: 1`, a run that needed two tool calls ended `failed` with result subtype
   `error_max_turns` (check T). `--session-id` and `--resume` are listed.
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

**Measured** (from `result` events: Claude Code's own `total_cost_usd`, computed by the CLI from the token counts at
list price, not a gateway invoice). On a resumed session `total_cost_usd` is **cumulative**: workspace `acc-a49ef1-a`
reported 0.047, 0.052, 0.054 and 0.070 over runs 1, 2, 3 and 5. The per-run figure is the difference:

| Run | Wall (event timestamps) | Turns | Output tokens | Cache read / write | Reported (cumulative) | This run |
|---|---|---|---|---|---|---|
| check 1, run 1 (write, commit; fresh session) | 15 s | 2 | 418 | 16,402 / 16,620 | 0.0474 | 0.0474 |
| check 2, run 2 (`sleep 45`, resumed) | 55 s | 2 | 54 | 33,531 / 381 | 0.0522 | 0.0048 |
| check 5 a, run 3 ("ok", resumed) | 9 s | 1 | 4 | 17,001 / 48 | 0.0541 | 0.0019 |
| check 5 b, run 1 ("ok", fresh session) | 9 s | 1 | 4 | 12,565 / 3,808 | 0.0108 | 0.0108 |
| check 6, run 5 (recall, after run 4) | 9 s | 1 | 52 | 17,892 / 271 | 0.0702 | 0.0161 (runs 4 and 5) |
| redeploy (`sleep 150`, separate workspace) | 160 s | 2 | — | — | 0.014 | 0.014 |
| check T, round 1 (`maxTurns: 1`, fresh session) | 14 s | 2 | 47 | 0 / 16,401 | 0.0415 | 0.0415 |

The measured total is about **$0.137**: the last cumulative figure of each session, 0.0702 + 0.0108 + 0.014 for the
first runs and 0.0415 for review fix round 1. Check 7's
three runs were stopped or lost and wrote no `result` event, so their cost is not measured. A fresh session pays to
write about 4–17k tokens of system prompt to the cache (about 1–5 cents for the first run); a resumed one-word run that
reads it back costs about 0.2–0.5 cents.

None of this measures design §8 item 8, a ten-minute run and an idle hour (see the table: NOT MEASURED).

**Computed** from design §9 (a `standard-1` instance costs about $0.04/h idle and up to about $0.075/h at full CPU;
snapshots are free in beta):

- a 15 s run: about $0.0002–0.0003 of container time; the 160 s run: about $0.0018–0.0033;
- an instance left to the 15-minute idle stop after a run: about $0.01 more;
- an hour of continuous agent work: about $0.04–0.075 for the container, which is small next to the model cost.

The Cloudflare dashboard's billed figures (Containers, AI Gateway logs) are left for the owner to read.

## Surprises

- **DNS answers come from a local stub.** Every UDP/53 query gets the same synthetic address (11.9.0.1),
  whatever the destination and the name (logs 2 and 4):
  - destinations 1.1.1.1, 8.8.8.8 and the unroutable 192.0.2.1;
  - names including a `.invalid` one.

  More from logs 2 and 4:
  - `/etc/resolv.conf` lists 1.1.1.1, 9.9.9.9 and 2606:4700:4700::1111.
  - The system resolver gives `fd00::119:1`.
  - Raw TCP times out on 22, 25, 53 and 8080.
  - The evidence for "UDP other than DNS does not leave" is two probes, and neither got a reply: NTP to
    162.159.200.1:123 and a datagram to 1.1.1.1:9999.

  This stub is how the platform routes hostnames to the HTTP intercept. The first version of check 3 counted any DNS
  answer as a leak and failed (log 1). Check 3 now fails only on signs of a real resolver: an NXDOMAIN, or 1.1.1.1
  and TEST-NET answering differently. Whether query names leave the platform is **unverified**; see "Owed" above.
- **`--max-turns` is a hidden flag** in Claude Code 2.1.308. It is not listed in `--help`, but it is accepted:
  `claude -p --max-turns 1 </dev/null` stops on the missing prompt, while `claude -p --no-such-flag-xyz </dev/null`
  says "unknown option" (log 4). It is enforced (check T). Check H was left strict and fails.
- **The bare root of an allowed host is refused.** The intercept hands the Worker `https://registry.npmjs.org`,
  without the slash, for a request to `https://registry.npmjs.org/`. The normal-form rule in `egress.ts` then refuses
  it, while `/left-pad` on the same host passes (log 3 and a probe kept in `.dev/probe-r1.log`). This fails closed, so
  it is not a leak, but a tool that fetches a registry root would get 403.
- **Preview URLs were on by default.** The first deploys enabled them; `preview_urls: false` is now set in
  `wrangler.jsonc` and the dev config.
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
- **Snapshots pile up.** Every ended run takes one. At least eleven `rootfs-snapshot-*` images were left in the registry after
  these checks (ten before review fix round 1, which ended one more run). They cannot be deleted through the API and expire 30 days after they were taken or last restored.
- **`stop` took about 4 s** on the deploy, against 0.25–2 s locally.
