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
- After the Copilot review fixes (2026-11-15) the Worker was redeployed from the branch at 330bea3 with a new
  image (tini as PID 1): version `d63bf26b-17a7-45f8-aa05-0e1ee1af5e00`, on which log 6 ran. The redeploy check
  (log 7) then made version `2aad8fcd-30fd-42df-a66e-d4a09bc07b4f` (same code and image).
- For the non-root agent (PLZG-311, 2026-11-15) the Worker was redeployed from `dev` at b5687c7 with a new image
  (an `agent` user, layout mark `2`): version `71ae6191-736a-4052-b2eb-63243f22d95e`, on which log 8 ran. The
  redeploy check (log 9) then made version `b2ecfa8e-a7a8-4f78-a6b9-dafbd8844962` (same code and image).
- For the sweep of the agent's processes and the small fixes (PLZG-311, 2026-11-17) the Worker was redeployed
  from `dev` at 7fc2982, code only (the image push was skipped), by the redeploy check itself (log 12): version
  `eb2cf0ed-f8f2-4ac7-9618-b06266788cca`, which is live. Logs 13 and 14 ran on it.
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
| e | longest run exercised | about 160 s then; 1,204 s on 2026-11-17, with the idle stop seen as well (log 14) |
| 8 | measured cost of a ten-minute run and an idle hour (design §8 item 8) | **NOT MEASURED:** no ten-minute run was made; the idle hour is computed from published rates; the dashboard's billed figures are owed by the owner. Short runs are measured under Cost |

In check (d), a run of `sleep 150` started. 20 s in, `wrangler deploy` made a new version in 11 s. Nothing had
changed, and wrangler printed "Image already exists remotely, skipping push". The status stayed `running` at
generation 1, the same instance. The run ended `succeeded` after 154 s, with `/workspace/task/exit-code` = `0`,
then `pushed` and `snapshot saved`.

The first PUT after a deploy answered 200 every time (seven workspaces), so the one-time 500 seen under
`wrangler dev` did not appear here.

**Log 6, `acc-r2.log`: the full suite after the Copilot review fixes** (branch at 330bea3, version d63bf26b,
new image with tini as PID 1). Same outcome as log 1 with its corrected check 3: checks 1 to 7 and T pass, H fails
because `--max-turns` is not in `--help`, and the script exited 1 for that alone. Check 1's push went through the
new push guard (`src/pushguard.ts`); the commit the runner reported is the one `ls-remote` shows.

```
NOTE workspaces acc-84b8ce-a and acc-84b8ce-b, branch cloud-runner/acceptance
NOTE ls-remote main before the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE PUT acc-84b8ce-a: generation 1, state idle
NOTE claude --version: 2.1.308 (Claude Code)
NOTE claude -p --max-turns 1 </dev/null: exit 1 Error: Input must be provided either through stdin or as a prompt argument when using --print
NOTE claude -p --no-such-flag-xyz </dev/null: exit 1 error: unknown option '--no-such-flag-xyz'
FAIL H claude --help in the image lists --session-id, --resume, --max-turns: not in --help: --max-turns
NOTE cost check 1 run 1: events span 17.152 s; result duration_ms=9129 num_turns=4 input=6 output=575 cache_read=32961 cache_write=16994 total_cost_usd=0.0515431 model=claude-sonnet-5-5
NOTE pushed.commit 5b25bc970402ea72d2e50d1b4ac37713e2b41745; ls-remote 5b25bc970402ea72d2e50d1b4ac37713e2b41745
PASS 1 a prompt runs to completion, writes and pushes NOTES.md
NOTE cost check T run 2: events span 8.557 s; result duration_ms=3002 num_turns=2 input=2 output=47 cache_read=16994 cache_write=258 total_cost_usd=0.0543615 model=claude-sonnet-5-5
NOTE check T: state failed, error "error_max_turns", result subtype error_max_turns, is_error true, num_turns 2, tool calls 1
PASS T maxTurns 1 stops a run that needs two tool calls (result subtype error_max_turns)
NOTE cost check 2 run 3: events span 55.219 s; result duration_ms=49933 num_turns=2 input=4 output=145 cache_read=34657 cache_write=334 total_cost_usd=0.0601202 model=claude-sonnet-5-5
NOTE check 2: 15 events read incrementally, same as one full read; run ended succeeded
PASS 2 events read twice agree, after=next never repeats, a second start answers 409
NOTE http://example.com: 403
NOTE https://registry.npmjs.org/left-pad: 200; http://registry.npmjs.org/left-pad: 403
NOTE push to octocat/Hello-World: exit 128, fatal: unable to access 'https://github.com/octocat/Hello-World/': The requested URL returned error: 403
NOTE raw TCP 1.1.1.1:53: timeout
NOTE raw TCP 1.1.1.1:22: timeout
NOTE raw TCP 1.1.1.1:25: timeout
NOTE raw TCP 1.1.1.1:8080: timeout
NOTE UDP DNS example.com via 8.8.8.8: answered 11.9.0.1
NOTE /etc/resolv.conf: "nameserver 1.1.1.1\nnameserver 9.9.9.9\nnameserver 2606:4700:4700::1111"
NOTE UDP DNS example.com via 1.1.1.1: answered 11.9.0.1; via 192.0.2.1 (TEST-NET): answered 11.9.0.1; nx-84b8ce.example.invalid via 1.1.1.1: answered 11.9.0.1
NOTE UDP NTP to 162.159.200.1:123: no reply
NOTE UDP to 1.1.1.1:9999: no reply
NOTE system resolver for example.com: resolved fd00::119:1
PASS 3 egress: unlisted host 403, plain HTTP refused, push elsewhere refused, own repository reachable, no raw TCP, no direct UDP (DNS name leakage not tested)
NOTE scanned 1343 bytes of container output, the environ of 3 processes (1302 bytes) and 38 events (check 1's: 15)
PASS 4 no credential in env, any process's environ, .git/config, ~/.gitconfig, home, /workspace or the workspace's events
NOTE right after both starts: acc-84b8ce-a running, acc-84b8ce-b running
NOTE cost check 5 a run 4: events span 8.743 s; result duration_ms=2598 num_turns=1 input=2 output=4 cache_read=17586 cache_write=48 total_cost_usd=0.0620428 model=claude-sonnet-5-5
NOTE cost check 5 b run 1: events span 8.999 s; result duration_ms=1687 num_turns=1 input=2 output=4 cache_read=12565 cache_write=3801 total_cost_usd=0.010803 model=claude-sonnet-5-5
PASS 5 two workspaces run at once and do not see each other's files
NOTE scratch.txt before replacement: "42"; pushError none
NOTE run 5 runner notices: run started, run ended, pushed, snapshot saved
NOTE cost check 6 run 6: events span 15.055 s; result duration_ms=2452 num_turns=1 input=2 output=28 cache_read=18516 cache_write=267 total_cost_usd=0.07827630000000001 model=claude-sonnet-5-5
NOTE check 6: restored=snapshot uncommittedLost=false instance note={"notice":"instance started","generation":2,"from":"snapshot"}; session same (a8ac3dbb-686a-4bd6-9f9f-662586f5fa9a); reports 42: true; reports heliotrope: true; state succeeded
NOTE check 6 answer: "The word is **heliotrope**, and `scratch.txt` contains `42`."
PASS 6 after replace-instance the snapshot restores an uncommitted file
NOTE stop answered stopped in 3.532 s
NOTE after replace-instance mid-run: lost (The container stopped before the run ended), pushError none
NOTE run after lost: generation 3, restored snapshot, uncommittedLost true
PASS 7 stop interrupts a run; a replaced instance mid-run reports lost; both accept the next run
NOTE ls-remote main after the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE DELETE acc-84b8ce-a: 204; then GET 200 {"state":"none","run":0,"generation":0}
NOTE DELETE acc-84b8ce-b: 204; then GET 200 {"state":"none","run":0,"generation":0}
exit=1
```

**Log 7, `redeploy-r2.log`: check (d) again, by the committed `scripts/redeploy.mjs`** (its first run as committed).
The deploy made version 2aad8fcd from the same code and image; the run stayed on generation 1 and ended
`succeeded` with exit code 0, then `pushed` and `snapshot saved`.

```
1s version before d63bf26b-17a7-45f8-aa05-0e1ee1af5e00
1s PUT 200
3s run 202 {"run":1}
24s before redeploy running generation 1
36s redeploy ok version after 2aad8fcd-30fd-42df-a66e-d4a09bc07b4f image unchanged
37s after redeploy running generation 1
168s ended succeeded generation 1
169s task exit-code file: "0"
runner notices: run started, run ended, pushed, snapshot saved
result: duration_ms 155375 turns 2 total_cost_usd 0.0134998
169s DELETE 204 then state none
PASS d the run survived the redeploy on the same instance and wrote exit code 0
exit=0
```

After both, `git ls-remote <repo> refs/heads/main` still gave `80f5ccb8968eacd2f6d68740e1990d2076671c10`.

**Log 8, `acc-311.log`: the full suite with the non-root agent (PLZG-311)** (`dev` at b5687c7, version 71ae6191,
new image with the `agent` user and layout mark `2`; started 23:45:26Z). Same outcome as log 6: checks 1 to 7 and T
pass, H fails because `--max-turns` is not in `--help`, and the script exited 1 for that alone. Check `U` is new and
passes: an exec runs as uid 1001 with no-new-privs, the agent cannot list, write or move the task directory, and
`/workspace` and `/workspace/task` are root's. Check 1 is the first run to end `succeeded` and push as the non-root
agent; `ls-remote` shows the commit the runner reported. Check 4 scanned the environ of 4 processes, as root and as
the agent.

```
NOTE workspaces acc-80197f-a and acc-80197f-b, branch cloud-runner/acceptance
NOTE ls-remote main before the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE PUT acc-80197f-a: generation 1, state idle
NOTE claude --version: 2.1.308 (Claude Code)
NOTE claude -p --max-turns 1 </dev/null: exit 1 Error: Input must be provided either through stdin or as a prompt argument when using --print
NOTE claude -p --no-such-flag-xyz </dev/null: exit 1 error: unknown option '--no-such-flag-xyz'
FAIL H claude --help in the image lists --session-id, --resume, --max-turns: not in --help: --max-turns
NOTE cost check 1 run 1: events span 16.794 s; result duration_ms=7471 num_turns=4 input=6 output=462 cache_read=43657 cache_write=6285 total_cost_usd=0.0247102 model=claude-sonnet-5-5
NOTE pushed.commit 0c3c7d2e9c39a8c4b3fa14199282395e3b14408f; ls-remote 0c3c7d2e9c39a8c4b3fa14199282395e3b14408f
PASS 1 a prompt runs to completion, writes and pushes NOTES.md
NOTE an exec as the agent: uid 1001 (agent), NoNewPrivs:	1
NOTE owners: /workspace root 755; /workspace/task root 700; /workspace/task/exit-code root 644; /workspace/repo agent 755
PASS U the agent is not root, and /workspace and the task directory are out of its reach (PLZG-311)
NOTE cost check T run 2: events span 8.408 s; result duration_ms=2691 num_turns=2 input=2 output=47 cache_read=16985 cache_write=197 total_cost_usd=0.027375200000000002 model=claude-sonnet-5-5
NOTE check T: state failed, error "error_max_turns", result subtype error_max_turns, is_error true, num_turns 2, tool calls 1
PASS T maxTurns 1 stops a run that needs two tool calls (result subtype error_max_turns)
NOTE cost check 2 run 3: events span 55.682 s; result duration_ms=50198 num_turns=2 input=4 output=199 cache_read=34517 cache_write=388 total_cost_usd=0.0337949 model=claude-sonnet-5-5
NOTE check 2: 15 events read incrementally, same as one full read; run ended succeeded
PASS 2 events read twice agree, after=next never repeats, a second start answers 409
NOTE http://example.com: 403
NOTE https://registry.npmjs.org/left-pad: 200; http://registry.npmjs.org/left-pad: 403
NOTE push to octocat/Hello-World: exit 128, fatal: unable to access 'https://github.com/octocat/Hello-World/': The requested URL returned error: 403
NOTE raw TCP 1.1.1.1:53: timeout
NOTE raw TCP 1.1.1.1:22: timeout
NOTE raw TCP 1.1.1.1:25: timeout
NOTE raw TCP 1.1.1.1:8080: timeout
NOTE UDP DNS example.com via 8.8.8.8: answered 11.9.0.1
NOTE /etc/resolv.conf: "nameserver 1.1.1.1\nnameserver 9.9.9.9\nnameserver 2606:4700:4700::1111"
NOTE UDP DNS example.com via 1.1.1.1: answered 11.9.0.1; via 192.0.2.1 (TEST-NET): answered 11.9.0.1; nx-80197f.example.invalid via 1.1.1.1: answered 11.9.0.1
NOTE UDP NTP to 162.159.200.1:123: no reply
NOTE UDP to 1.1.1.1:9999: no reply
NOTE system resolver for example.com: resolved fd00::119:1
PASS 3 egress: unlisted host 403, plain HTTP refused, push elsewhere refused, own repository reachable, no raw TCP, no direct UDP (DNS name leakage not tested)
NOTE scanned 1392 bytes of container output, the environ of 4 processes (1696 bytes) and 37 events (check 1's: 14)
PASS 4 no credential in env, any process's environ, .git/config, ~/.gitconfig, home, /workspace or the workspace's events
NOTE right after both starts: acc-80197f-a running, acc-80197f-b running
NOTE cost check 5 a run 4: events span 9.154 s; result duration_ms=2613 num_turns=1 input=2 output=4 cache_read=17570 cache_write=48 total_cost_usd=0.0357159 model=claude-sonnet-5-5
NOTE cost check 5 b run 1: events span 8.851 s; result duration_ms=2241 num_turns=1 input=2 output=4 cache_read=12568 cache_write=3796 total_cost_usd=0.0107908 model=claude-sonnet-5-5
PASS 5 two workspaces run at once and do not see each other's files
NOTE scratch.txt before replacement: "42"; pushError none
NOTE run 5 runner notices: run started, run ended, pushed, snapshot saved
NOTE cost check 6 run 6: events span 10.158 s; result duration_ms=2790 num_turns=1 input=2 output=59 cache_read=18366 cache_write=360 total_cost_usd=0.050724500000000006 model=claude-sonnet-5-5
NOTE check 6: restored=snapshot uncommittedLost=false instance note={"notice":"instance started","generation":2,"from":"snapshot"}; session same (3a6ad0ea-bc15-44dd-b55e-0aab5380e2fa); reports 42: true; reports heliotrope: true; state succeeded
NOTE check 6 answer: "You asked me to remember the word **heliotrope**. `scratch.txt` contains `42`. I wrote that file myself earlier in this conversation and haven't re-read it since."
PASS 6 after replace-instance the snapshot restores an uncommitted file
NOTE stop answered stopped in 6.57 s
NOTE after replace-instance mid-run: lost (The container stopped before the run ended), pushError none
NOTE run after lost: generation 3, restored snapshot, uncommittedLost true
PASS 7 stop interrupts a run; a replaced instance mid-run reports lost; both accept the next run
NOTE ls-remote main after the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE DELETE acc-80197f-a: 204; then GET 200 {"state":"none","run":0,"generation":0}
NOTE DELETE acc-80197f-b: 204; then GET 200 {"state":"none","run":0,"generation":0}
exit=1
```

**Log 9, `redeploy-311.log`: check (d) with the non-root agent**, by `scripts/redeploy.mjs` (it now reads the
exit-code file as root). The deploy made version b2ecfa8e from the same code and image, which is live; the run
stayed on generation 1 and ended `succeeded` with exit code 0, then `pushed` and `snapshot saved`.

```
2s version before 71ae6191-736a-4052-b2eb-63243f22d95e
2s PUT 200
4s run 202 {"run":1}
25s before redeploy running generation 1
40s redeploy ok version after b2ecfa8e-a7a8-4f78-a6b9-dafbd8844962 image unchanged
40s after redeploy running generation 1
166s ended succeeded generation 1
166s task exit-code file: "0"
runner notices: run started, run ended, pushed, snapshot saved
result: duration_ms 154704 turns 2 total_cost_usd 0.0134874
166s DELETE 204 then state none
PASS d the run survived the redeploy on the same instance and wrote exit code 0
exit=0
```

**Log 10, `mig-before.log`, `mig-after.log` and `probe-1.log`: a workspace taken across the redeploy that changed
the image layout.** A one-off script, not committed. Before the deploy (version 2aad8fcd, the image in which the
agent is root) it made workspace `mig-311a`, planted an uncommitted file, ran one run so a snapshot was saved, and
dropped the instance with `replace-instance`. `wrangler containers list` then showed 0 live instances. The deploy
returned at 23:43:42Z (version 71ae6191 created 23:43:40Z).

```
PUT mig-311a: 200 {"state":"idle","run":0,"generation":1,"repo":"https://github.com/adamtasteslikegood/ArtazZen-recipes-TanStack-showcase","branch":"cloud-runner/acceptance"}
old image, id -u: 200 exit 0 out "0" err ""
old image, layout mark: 200 exit 1 out "" err "cat: /etc/plaza-runner-layout: No such file or directory"
old image, plant uncommitted file: 200 exit 0 out "-rw-r--r-- 1 root root 18 Nov 15 23:41 /workspace/repo/mig.txt" err ""
POST runs: 202 {"run":1}
run on the old image ended: {"state":"succeeded","generation":1,"result":"ok"}
runner event: {"notice":"run started","run":1}
runner event: {"notice":"run ended","run":1,"state":"succeeded"}
runner event: {"notice":"pushed","run":1,"commit":"5b25bc970402ea72d2e50d1b4ac37713e2b41745"}
runner event: {"notice":"snapshot saved","run":1,"bytes":277124}
replace-instance: 200 {"state":"succeeded","run":1,"generation":1,"repo":"https://github.com/adamtasteslikegood/ArtazZen-recipes-TanStack-showcase","branch":"cloud-runner/acceptance","result":"ok","pushed":{"commit":"5b25b
status now: {"state":"succeeded","generation":1,"result":"ok"}
```

After the deploy the workspace was started again. The intent was to see the new code refuse the old snapshot
(`restored: "branch"`, a `snapshotError` in the `instance started` event). **That is not what happened**: these
requests, the last of them at 23:44:15Z, were answered by the old code. It restored the snapshot into a new
instance, and an exec with no `root` flag ran as uid 0. The missing layout mark and the root-owned clone say
nothing about the image, since a restored snapshot is the whole root filesystem.

```
status before the first start on the new image: {"state":"succeeded","generation":1,"result":"ok"}
POST runs: 202 {"run":2}
run on the new image ended: {"state":"succeeded","generation":2,"restored":"snapshot","uncommittedLost":false,"result":"ok"}
instance started event: {"notice":"instance started","generation":2,"from":"snapshot"}
new image, id -u: 200 exit 0 out "0" err ""
new image, layout mark (root): 200 exit 1 out "" err "cat: /etc/plaza-runner-layout: No such file or directory"
new image, mig.txt in the clone: 200 exit 0 out "before-the-deploy" err ""
new image, owners (root): 200 exit 0 out "/workspace root 755\n/workspace/task root 755\n/workspace/repo root 755" err ""
DELETE mig-311a: 204; then GET 200 {"state":"none","run":0,"generation":0}
```

A workspace made at 23:45:00Z got the new code and the new image:

```
2026-11-15T23:45:00.424Z
PUT probe-311a: 200 {"state":"idle","run":0,"generation":1,"repo":"https://github.com/adamtasteslikegood/ArtazZen-recipes-TanStack-showcase","branch":"cloud-runner/acceptance"}
id -u (no root flag): 200 exit 0 out "1001" err ""
id -u (root: true): 200 exit 0 out "0" err ""
layout mark (root: true): 200 exit 0 out "2" err ""
agent user in the image (root: true): 200 exit 0 out "uid=1001(agent) gid=1001(agent) groups=1001(agent)" err ""
DELETE probe-311a: 204; then GET 200 {"state":"none","run":0,"generation":0}
```

So no snapshot really built from the earlier image was refused on the deploy, and the old image is gone, so this
cannot be repeated as it was. What it did show is in Surprises: the old code can answer after the deploy returns.

**Log 11, `nomark-311.log`: a snapshot with no layout mark is refused** (version b2ecfa8e). A stand-in for log 10,
by another one-off script: in a new workspace the layout mark was removed as root, which is how a snapshot from the
earlier image looks to the check, and an uncommitted file was written as the agent. A one-word run saved a snapshot,
`replace-instance` dropped the instance, and a diff (no model call) started the next one. The new code refused the
snapshot and cloned the branch: `restored: "branch"`, `uncommittedLost: true`, an empty diff, and a `snapshotError`
in the `instance started` event. The new instance has the mark again.

```
2026-11-15T23:56:39.076Z
PUT nomark-311a: 200 {"state":"idle","run":0,"generation":1,"repo":"https://github.com/adamtasteslikegood/ArtazZen-recipes-TanStack-showcase","branch":"cloud-runner/acceptance"}
id -u (no root flag): 200 exit 0 out "1001" err ""
layout mark before (root): 200 exit 0 out "2" err ""
uncommitted file, as the agent: 200 exit 0 out "-rw-r--r-- 1 agent agent 24 Nov 15 23:56 nomark.txt" err ""
remove the mark (root): 200 exit 0 out "" err ""
POST runs: 202 {"run":1}
run ended: {"state":"succeeded","generation":1}
runner notices: run started, run ended, pushed, snapshot saved
replace-instance: 200
GET diff (starts a new instance): 200, 0 bytes, names nomark.txt: false
status: {"state":"succeeded","generation":2,"restored":"branch","uncommittedLost":true}
event: {"notice":"instance started","generation":2,"from":"branch","snapshotError":"The snapshot's image layout is none, not \"2\": it is from another version of the image"}
layout mark in the new instance (root): 200 exit 0 out "2" err ""
id -u in the new instance (no root flag): 200 exit 0 out "1001" err ""
DELETE nomark-311a: 204; then GET 200 {"state":"none","run":0,"generation":0}
```

After all four, `git ls-remote <repo> refs/heads/main` still gave `80f5ccb8968eacd2f6d68740e1990d2076671c10`, and
`refs/heads/cloud-runner/acceptance` was at check 1's commit, `0c3c7d2e9c39a8c4b3fa14199282395e3b14408f`.

**Log 12, `redeploy-311c.log`: check (d) as the deploy of the sweep code** (2026-11-17, `dev` at 7fc2982), by
`scripts/redeploy.mjs`. This run was the one approved redeploy: the script's own `wrangler deploy` made version
eb2cf0ed from the new code and the unchanged image, 32 s into a run that then ended on generation 1 with exit
code 0. It does not show the sweep: a clean sweep leaves no trace, and which code ended the run is not known (the
old code has answered for a while after a deploy before, log 10).

```
2026-11-17T12:51:04Z
7fc298271f3b3068b36dee3cd4055f9cf3a5dd87
2s version before b2ecfa8e-a7a8-4f78-a6b9-dafbd8844962
2s PUT 200
12s run 202 {"run":1}
32s before redeploy running generation 1
45s redeploy ok version after eb2cf0ed-f8f2-4ac7-9618-b06266788cca image unchanged
45s after redeploy running generation 1
175s ended succeeded generation 1
175s task exit-code file: "0"
runner notices: run started, run ended, pushed, snapshot saved
result: duration_ms 154602 turns 2 total_cost_usd 0.043650600000000005
176s DELETE 204 then state none
PASS d the run survived the redeploy on the same instance and wrote exit code 0
exit 0
2026-11-17T12:54:00Z
```

After it (the script ended at 12:54:00), a second PUT of a workspace with another host list answered `The
workspace exists with another repo, branch or host list`, the new text, three times at 20 s intervals between
12:54:08 and 12:55:16.

**Log 13, `acc-311c.log` and `acc-311c-s.log`: the full suite on the sweep code** (version eb2cf0ed). Ten of
twelve checks pass. Check H fails as in every run (the hidden `--max-turns`). Check `R` (new) passes: the bare root
of `registry.npmjs.org` answers 200. Check `S` (new) failed in its own setup: the exec that plants the process
answered 500. The cause is in the check, not in the sweep (see Surprises, and the probe in log 14): the detached
`sleep` kept the exec's output pipes open, so the exec ran into its 30 s timeout. 59daae9 plants it with its three
streams on `/dev/null`, and `S` then passed alone (`ONLY=S`, second block): the process was gone after the run, the
generation stayed 1, and no `agent processes left` notice was written. The failed plant of the first block very
likely left its `sleep` running in workspace A, as the same exec did in the probe of log 14; nobody looked. The
runs after it on A started and ended normally.

```
2026-11-17T12:55:22Z
NOTE workspaces acc-851d6f-a and acc-851d6f-b, branch cloud-runner/acceptance
NOTE ls-remote main before the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE PUT acc-851d6f-a: generation 1, state idle
NOTE claude --version: 2.1.308 (Claude Code)
NOTE claude -p --max-turns 1 </dev/null: exit 1 Error: Input must be provided either through stdin or as a prompt argument when using --print
NOTE claude -p --no-such-flag-xyz </dev/null: exit 1 error: unknown option '--no-such-flag-xyz'
FAIL H claude --help in the image lists --session-id, --resume, --max-turns: not in --help: --max-turns
NOTE cost check 1 run 1: events span 9.12 s; result duration_ms=4716 num_turns=3 input=6 output=366 cache_read=45809 cache_write=4569 total_cost_usd=0.0196754 model=claude-sonnet-5-5
NOTE pushed.commit 261006466bee10506a01d6065f3a4906d5b57f66; ls-remote 261006466bee10506a01d6065f3a4906d5b57f66
PASS 1 a prompt runs to completion, writes and pushes NOTES.md
NOTE an exec as the agent: uid 1001 (agent), NoNewPrivs:	1
NOTE owners: /workspace root 755; /workspace/task root 700; /workspace/task/exit-code root 644; /workspace/repo agent 755
PASS U the agent is not root, and /workspace and the task directory are out of its reach (PLZG-311)
NOTE cost check T run 2: events span 8.439 s; result duration_ms=1738 num_turns=2 input=2 output=47 cache_read=17137 cache_write=174 total_cost_usd=0.022298099999999998 model=claude-sonnet-5-5
NOTE check T: state failed, error "error_max_turns", result subtype error_max_turns, is_error true, num_turns 2, tool calls 1
PASS T maxTurns 1 stops a run that needs two tool calls (result subtype error_max_turns)
NOTE cost check 2 run 3: events span 53.844 s; result duration_ms=48234 num_turns=2 input=4 output=164 cache_read=34775 cache_write=353 total_cost_usd=0.0283061 model=claude-sonnet-5-5
NOTE check 2: 15 events read incrementally, same as one full read; run ended succeeded
PASS 2 events read twice agree, after=next never repeats, a second start answers 409
NOTE http://example.com: 403
NOTE https://registry.npmjs.org/left-pad: 200; http://registry.npmjs.org/left-pad: 403
NOTE push to octocat/Hello-World: exit 128, fatal: unable to access 'https://github.com/octocat/Hello-World/': The requested URL returned error: 403
NOTE raw TCP 1.1.1.1:53: timeout
NOTE raw TCP 1.1.1.1:22: timeout
NOTE raw TCP 1.1.1.1:25: timeout
NOTE raw TCP 1.1.1.1:8080: timeout
NOTE UDP DNS example.com via 8.8.8.8: answered 11.9.0.1
NOTE /etc/resolv.conf: "nameserver 1.1.1.1\nnameserver 9.9.9.9\nnameserver 2606:4700:4700::1111"
NOTE UDP DNS example.com via 1.1.1.1: answered 11.9.0.1; via 192.0.2.1 (TEST-NET): answered 11.9.0.1; nx-851d6f.example.invalid via 1.1.1.1: answered 11.9.0.1
NOTE UDP NTP to 162.159.200.1:123: no reply
NOTE UDP to 1.1.1.1:9999: no reply
NOTE system resolver for example.com: resolved fd00::119:1
PASS 3 egress: unlisted host 403, plain HTTP refused, push elsewhere refused, own repository reachable, no raw TCP, no direct UDP (DNS name leakage not tested)
NOTE https://registry.npmjs.org (bare root): 200
PASS R the bare root of an allowed host is reachable (PLZG-311)
FAIL S a process the agent left outside any task is ended before the next run, on the same instance (PLZG-311): exec setsid answered 500 Workspace request failed

NOTE scanned 1392 bytes of container output, the environ of 6 processes (2484 bytes) and 35 events (check 1's: 12)
PASS 4 no credential in env, any process's environ, .git/config, ~/.gitconfig, home, /workspace or the workspace's events
NOTE right after both starts: acc-851d6f-a running, acc-851d6f-b running
NOTE cost check 5 a run 4: events span 8.411 s; result duration_ms=1756 num_turns=1 input=2 output=4 cache_read=17664 cache_write=48 total_cost_usd=0.0302365 model=claude-sonnet-5-5
NOTE cost check 5 b run 1: events span 8.56 s; result duration_ms=1273 num_turns=1 input=2 output=4 cache_read=12568 cache_write=3778 total_cost_usd=0.0107458 model=claude-sonnet-5-5
PASS 5 two workspaces run at once and do not see each other's files
NOTE scratch.txt before replacement: "42"; pushError none
NOTE run 5 runner notices: run started, run ended, pushed, snapshot saved
NOTE cost check 6 run 6: events span 9.23 s; result duration_ms=1459 num_turns=1 input=2 output=28 cache_read=17926 cache_write=120 total_cost_usd=0.0382449 model=claude-sonnet-5-5
NOTE check 6: restored=snapshot uncommittedLost=false instance note={"notice":"instance started","generation":2,"from":"snapshot"}; session same (5a402473-3815-49fb-afd1-bd641958b91f); reports 42: true; reports heliotrope: true; state succeeded
NOTE check 6 answer: "The word is **heliotrope**, and `scratch.txt` contains `42`."
PASS 6 after replace-instance the snapshot restores an uncommitted file
NOTE stop answered stopped in 3.563 s
NOTE after replace-instance mid-run: lost (The container stopped before the run ended), pushError none
NOTE run after lost: generation 3, restored snapshot, uncommittedLost true
PASS 7 stop interrupts a run; a replaced instance mid-run reports lost; both accept the next run
NOTE ls-remote main after the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE DELETE acc-851d6f-a: 204; then GET 200 {"state":"none","run":0,"generation":0}
NOTE DELETE acc-851d6f-b: 204; then GET 200 {"state":"none","run":0,"generation":0}
exit 1
2026-11-17T12:59:06Z
```

```
2026-11-17T13:01:23Z
NOTE workspaces acc-dd4da0-a and acc-dd4da0-b, branch cloud-runner/acceptance
NOTE ls-remote main before the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE PUT acc-dd4da0-a: generation 1, state idle
NOTE cost check S run 1: events span 8.181 s; result duration_ms=1542 num_turns=1 input=2 output=4 cache_read=12568 cache_write=3770 total_cost_usd=0.010725799999999999 model=claude-sonnet-5-5
NOTE check S: sleep 86282 planted as the agent; after run 1 (succeeded) 0 left; generation 1 then 1; notices ["run started","run ended","pushed","snapshot saved"]
PASS S a process the agent left outside any task is ended before the next run, on the same instance (PLZG-311)
NOTE ls-remote main after the checks: 80f5ccb8968eacd2f6d68740e1990d2076671c10
NOTE DELETE acc-dd4da0-a: 204; then GET 200 {"state":"none","run":0,"generation":0}
NOTE DELETE acc-dd4da0-b: 204; then GET 200 {"state":"none","run":0,"generation":0}
exit 0
2026-11-17T13:01:35Z
```

**Log 14, `live-311c*.log`: what had never been tried on the deploy** (version eb2cf0ed, 2026-11-17), by a one-off
script that is not in the repository. Every workspace used the test branch. The process listings the script printed
are left out, and long lines are cut at `[…]`. Times are UTC.

*A run longer than the idle timeout, and the idle stop.* Two workspaces were made at 13:00:06. In `live-311c-long`
the agent ran `sleep 590` twice. No request was sent to it between 13:00:32 and 13:22:16, so only the object's own
alarm touched the container. The run ended `succeeded` after 1,204 s on generation 1, pushed and snapshotted. The
run does not show what kept the instance up; Cloudflare's lifetime page says a running alarm counts as activity
and that nothing inside the instance does.
`live-311c-idle` got one exec at 13:00:06 and no request after it.

```
13:00:04 remote head: 261006466bee10506a01d6065f3a4906d5b57f66
13:00:06 PUT live-311c-long: 200 {"state":"idle","run":0,"generation":1,"repo":"https://github.com/adamtasteslikegood/ArtazZen-recipes-TanStack-showcase","branch":"cloud-runner/acceptance"} (1590 ms)
13:00:06 PUT live-311c-idle: 200 {"state":"idle","run":0,"generation":1,"repo":"https://github.com/adamtasteslikegood/ArtazZen-recipes-TanStack-showcase","branch":"cloud-runner/acceptance"} (2115 ms)
13:00:06 idle: marker written as the agent: 13:00:06
13:00:06 idle: last request to it is now; it is not touched again until its instance is gone
13:00:06 long: marker written as the agent, outside the clone: long-marker
13:00:06 POST live-311c-long/runs: 202 {"run":1}
13:00:32 long: status 25 s in (the last request to it until the run is over): {"state":"running","run":1,"generation":1}
13:22:16 long: status: {"state":"succeeded","run":1,"generation":1,"result":"done","pushed":{"commit":"261006466bee10506a01d6065f3a4906d5b57f66"}}
13:22:17 long: run facts: {"first":"2026-11-17T13:00:06.825Z","last":"2026-11-17T13:20:11.100Z","wallSeconds":1204.275,"duration_ms":1185077,"num_turns":3,"subtype":"success","total_cost_usd":0.0350124}
13:22:17 long: runner notices: [{"at":"13:00:06","notice":"run started","run":1},{"at":"13:20:07","notice":"run ended","run":1,"state":"succeeded"},{"at":"13:20:08","notice":"pushed","run":1,"commit":"261006466bee10506a01d6065f3a4906d5b57f66"},{"at":"13:20:11","notice":"snapshot saved","run":1,"bytes":318064}]
13:22:17 long: tool calls: [{"at":"13:02:06","command":"sleep 590","timeout":600000},{"at":"13:12:07","command":"sleep 590","timeout":600000}]
13:22:17 long: tool results at: ["13:12:07","13:20:07"]
13:22:17 remote head: 261006466bee10506a01d6065f3a4906d5b57f66
13:50:15 idle: status (first request since the marker): {"state":"idle","run":0,"generation":1}
13:50:16 idle: marker and clone after the wake: {"code":0,"out":"cat: /home/agent/live-marker: No such file or directory\n261006466bee10506a01d6065f3a4906d5b57f66","err":""}
13:50:16 idle: status after the wake: {"state":"idle","run":0,"generation":2,"restored":"branch","uncommittedLost":true}
13:50:16 idle: runner notices: [{"at":"13:50:16","notice":"instance started","generation":2,"from":"branch"}]
13:50:17 long: status (first request since the run's end was read): {"state":"succeeded","run":1,"generation":1,"result":"done","pushed":{"commit":"261006466bee10506a01d6065f3a4906d5b57f66"}}
13:50:24 long: marker and clone after the wake: {"code":0,"out":"long-marker\n261006466bee10506a01d6065f3a4906d5b57f66","err":""}
13:50:24 long: status after the wake: {"state":"succeeded","run":1,"generation":2,"result":"done","pushed":{"commit":"261006466bee10506a01d6065f3a4906d5b57f66"},"restored":"snapshot","uncommittedLost":false}
13:50:24 long: runner notices: [{"at":"13:00:06","notice":"run started","run":1},{"at":"13:20:07","notice":"run ended","run":1,"state":"succeeded"},{"at":"13:20:08","notice":"pushed","run":1,"commit":"261006466bee10506a01d6065f3a4906d5b57f66"},{"at":"13:20:11","notice":"snapshot saved","run":1,"bytes":318064},{"at":"13:50:24","n […]
13:50:25 DELETE live-311c-idle: 204; then state none
13:50:25 DELETE live-311c-long: 204; then state none
```

The count of live instances (`wrangler containers info`, once a minute; the other test workspaces of this log come
and go in it):

```
13:00:36 {"active":2,"starting":0}
13:01:33 {"active":2,"starting":0}
13:02:30 {"active":4,"starting":0}
13:05:20 {"active":4,"starting":0}
13:06:17 {"active":3,"starting":0}
13:16:43 {"active":3,"starting":0}
13:17:39 {"active":2,"starting":0}
13:25:14 {"active":2,"starting":0}
13:26:11 {"active":1,"starting":0}
13:40:22 {"active":1,"starting":0}
13:41:19 {"active":0,"starting":0}
13:49:51 {"active":0,"starting":0}
```

Read with the deletes below: 2 after the two starts, 4 with the two failure tests, 3 after `live-311c-tf` was
deleted (13:05:06), 2 after `live-311c-big` was deleted (13:16:55). The idle workspace's instance was gone between
13:25:14 and 13:26:11, about 25 minutes after its last request and not 15. The long workspace's instance was gone
between 13:40:22 and 13:41:19, about 18.5 minutes after its last request (13:22:17). Both times are 15 minutes
after the last exec's timeout would have run out: the clone's 10 minutes from 13:00:05, and the push's 5 minutes
from 13:20:08 (see Surprises). On the next request the idle workspace, which never ran and so had no snapshot,
came back from the branch without its marker file (`restored: "branch"`, `uncommittedLost: true`); the long one
came back from its snapshot with its marker file.

*An unreadable task file.* During a run in its `sleep`, a commit was made in the clone as the agent, and root
replaced `stdout.log` with a directory. The object's alarm counted a task-file failure once a minute. At the third
(180 s after the start) the run ended `failed` with `the run's task files could not be read`. No `pushed` and no
snapshot notice was written, the branch on GitHub did not move, and the next request got a new instance cloned
from the branch, without the commit.

```
13:01:45 remote head before: 261006466bee10506a01d6065f3a4906d5b57f66
13:01:47 PUT live-311c-tf: 200 {"state":"idle","run":0,"generation":1,"repo":"https://github.com/adamtasteslikegood/ArtazZen-recipes-TanStack-showcase","branch":"cloud-runner/acceptance"} (1825 ms)
13:01:47 POST live-311c-tf/runs: 202 {"run":1}
13:01:54 the agent is in its sleep; status: {"state":"running","run":1,"generation":1}
13:01:54 a commit made in the clone as the agent: {"code":0,"out":"8225168dda28ac0bea2a9f1bc4e68c7f55b730c4","err":""}
13:01:54 stdout.log replaced with a directory, as root: {"code":0,"out":"total 4\ndrwx------ 1 root root 90 Nov 17 13:01 .\ndrwxr-xr-x 1 root root 16 Nov 17 13:01 ..\n-rw-r--r-- 1 root root 40 Nov 17 13:01 pid\nprw------- 1 root root  0 Nov 17 13:01 stderr.fifo\n-rw-r--r-- 1 root root  0 Nov 17 13:01 stderr.log\nprw------- 1 roo […]
13:02:54 status 60 s after the plant: {"state":"running","run":1,"generation":1}
13:03:55 status 121 s after the plant: {"state":"running","run":1,"generation":1}
13:04:55 status 181 s after the plant: {"state":"failed","run":1,"generation":1,"error":"the run's task files could not be read"}
13:04:55 runner notices: [{"at":"13:01:47","notice":"run started","run":1},{"at":"13:04:47","notice":"run ended","run":1,"state":"failed","error":"the run's task files could not be read"}]
13:04:55 run facts: {"first":"2026-11-17T13:01:47.125Z","last":"2026-11-17T13:04:47.293Z","wallSeconds":180.168}
13:04:55 remote head after: 261006466bee10506a01d6065f3a4906d5b57f66 (unchanged)
13:04:57 the clone and task directory on the next exec: {"code":0,"out":"ls: cannot access '/workspace/task': No such file or directory","err":"fatal: detected dubious ownership in repository at '/workspace/repo'\nTo add an exception for this directory, call:\n\n\tgit config --global --add safe.directory /workspace/repo"}
13:04:57 status after that exec: {"state":"failed","run":1,"generation":2,"error":"the run's task files could not be read","restored":"branch","uncommittedLost":true}
exit 0
13:05:06 the clone on the new instance, as the agent:
13:05:06 DELETE live-311c-tf 204
```

*An oversized result line.* During a run in its `sleep`, root wrote one line that starts `{"type":"result"` into
the task's stdout fifo, then KILLed the agent process (the leader's child) so that this line was the run's last
result. The leader wrote exit code 137 and the run ended through the usual path. A 5 MB line (over one 4 MiB
chunk, never read whole) ended the run `failed` with `the run's result was over 256 KiB and could not be read`. A
1 MB line with `is_error: false` ended it `succeeded` with an empty result and a `result truncated` notice. Both
were pushed and snapshotted. The lines came from root, not from Claude Code. In the 5 MB case the script waited
135 s (two alarm ticks) before the KILL, and the line was not in the event log until the run ended (see Surprises).

```
13:13:11 PUT live-311c-big: 200 {"state":"succeeded","run":2,"generation":1,"repo":"https://github.com/adamtasteslikegood/ArtazZen-recipes-TanStack-showcase","branch":"cloud-runner/acceptance","result":"done","pushed":{"commit":"261006466bee10506a01d6065f3a4906d5b57f66"}} (322 ms)
13:13:12 remote head before: 261006466bee10506a01d6065f3a4906d5b57f66
13:13:12 --- a result line of about 5 MB (over one 4 MiB chunk)
13:13:12 POST live-311c-big/runs: 202 {"run":3}
13:13:18 task leader pid: 2093
13:13:19 line written into the task's stdout fifo as root; stdout.log bytes: {"code":0,"out":"5001216","err":""}
13:13:22 status with the line in the log, agent still running: {"state":"running","run":3,"generation":1,"pushed":{"commit":"261006466bee10506a01d6065f3a4906d5b57f66"}}
13:15:39 result events 135 s after the write (this read is the first that ingests on request): []
13:15:39 the agent process (the leader's child) KILLed as root: {"code":0,"out":"KILLed 1","err":""}
13:15:43 status at the end: {"state":"failed","run":3,"generation":1,"error":"the run's result was over 256 KiB and could not be read","pushed":{"commit":"261006466bee10506a01d6065f3a4906d5b57f66"}}
13:15:43 result events of this run: [{"at":"13:15:40","payload":"{\"truncated\":true,\"bytes\":5000066}"}]
13:15:43 runner notices of this run: [{"at":"13:13:12","notice":"run started","run":3},{"at":"13:15:40","notice":"run ended","run":3,"state":"failed"},{"at":"13:15:40","notice":"pushed","run":3,"commit":"261006466bee10506a01d6065f3a4906d5b57f66"},{"at":"13:15:43","notice":"snapshot saved","run":3,"bytes":543000}]
13:15:43 exit-code file: 137
13:15:44 runner notices once settled: [{"at":"13:13:12","notice":"run started","run":3},{"at":"13:15:40","notice":"run ended","run":3,"state":"failed"},{"at":"13:15:40","notice":"pushed","run":3,"commit":"261006466bee10506a01d6065f3a4906d5b57f66"},{"at":"13:15:43","notice":"snapshot saved","run":3,"bytes":543000}]
13:15:44 --- a result line of about 1 MB (over 256 KiB, under one 4 MiB chunk), is_error false
13:15:44 POST live-311c-big/runs: 202 {"run":4}
13:15:47 task leader pid: 2453
13:15:48 line written into the task's stdout fifo as root; stdout.log bytes: {"code":0,"out":"999424","err":""}
13:15:51 status with the line in the log, agent still running: {"state":"running","run":4,"generation":1,"pushed":{"commit":"261006466bee10506a01d6065f3a4906d5b57f66"}}
13:15:51 the agent process (the leader's child) KILLed as root: {"code":0,"out":"KILLed 1","err":""}
13:15:54 status at the end: {"state":"succeeded","run":4,"generation":1,"result":"","pushed":{"commit":"261006466bee10506a01d6065f3a4906d5b57f66"}}
13:15:54 result events of this run: [{"at":"13:15:51","payload":"{\"truncated\":true,\"bytes\":1000066}"}]
13:15:54 runner notices of this run: [{"at":"13:15:44","notice":"run started","run":4},{"at":"13:15:51","notice":"result truncated","run":4},{"at":"13:15:51","notice":"run ended","run":4,"state":"succeeded"},{"at":"13:15:52","notice":"pushed","run":4,"commit":"261006466bee10506a01d6065f3a4906d5b57f66"},{"at":"13:15:54","notice": […]
13:15:54 exit-code file: 137
13:15:55 runner notices once settled: [{"at":"13:15:44","notice":"run started","run":4},{"at":"13:15:51","notice":"result truncated","run":4},{"at":"13:15:51","notice":"run ended","run":4,"state":"succeeded"},{"at":"13:15:52","notice":"pushed","run":4,"commit":"261006466bee10506a01d6065f3a4906d5b57f66"},{"at":"13:15:54","notice" […]
13:15:55 remote head after: 261006466bee10506a01d6065f3a4906d5b57f66
13:15:55 status: {"state":"succeeded","run":4,"generation":1,"result":"","pushed":{"commit":"261006466bee10506a01d6065f3a4906d5b57f66"}}
exit 0
13:16:55 DELETE live-311c-big 204
```

A first attempt (`live-311c-big.log`) used `pkill`, which the image does not have, so the agent was not ended and
its own later result line replaced the written one: both runs ended `succeeded` with `done`. It still showed both
lines in the event log as `{"truncated":true,"bytes":1000066}` and `{"truncated":true,"bytes":5000066}` with the
run going on, and four containers running at once.

*Why check `S`'s plant failed.* In a new workspace:

```
13:00:42 PUT live-311c-probe: 200 {"state":"idle","run":0,"generation":1,"repo":"https://github.com/adamtasteslikegood/ArtazZen-recipes-TanStack-showcase","branch":"cloud-runner/acceptance"} (2106 ms)
13:01:13 exec setsid -f sleep 86001 (its output left attached): 500 Workspace request failed (30080 ms)
13:01:13 sleep 86001 running: 1
13:01:13 exec sh -c 'setsid -f sleep 86002 >/dev/null 2>&1 </dev/null': 200 {"exitCode":0,"stdout":"","stderr":""} (135 ms)
13:01:13 sleep 86002 running: 1
13:01:13 DELETE live-311c-probe: 204
```

After all of it, `refs/heads/main` was still at `80f5ccb8968eacd2f6d68740e1990d2076671c10`, and
`refs/heads/cloud-runner/acceptance` at check 1's commit of log 13, `261006466bee10506a01d6065f3a4906d5b57f66`.
Every workspace was deleted, and the count of live instances was 0.

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

The runs of 2026-11-15 with the non-root agent (logs 8 and 9) add about **$0.075**, counted the same way: the
last cumulative figure of each session, not the sum of every `result` line. Workspace `acc-80197f-a` is one resumed
session whose runs 1, 2, 3, 4 and 6 reported 0.0247, 0.0274, 0.0338, 0.0357 and 0.0507, so it counts as 0.0507;
`acc-80197f-b` counts as 0.0108 and the redeploy run as 0.0135. Adding all seven `result` lines (about $0.197)
would count the first session's earlier runs several times. Check 7's runs, the two one-word runs of log 10 and
the one of log 11 are not in the figure.

The runs of 2026-11-17 (logs 12 to 14) add about **$0.138**, counted the same way: the redeploy run 0.0437,
`acc-851d6f-a` 0.0382 (its last cumulative figure), `acc-851d6f-b` 0.0107, the re-run of check `S` 0.0107, and the
20-minute run 0.0350 (3 turns; its cost is the model's, not the wait's). Not in the figure: check 7's runs, the
task-file run and the two runs whose agent was KILLed (no `result` event of Claude Code's), and the two runs of the
first oversized-line attempt, whose workspace was deleted before their figures were read.

The 20-minute run is the first longer than ten minutes. Its container time is computed, not billed: about
$0.013–0.025 at the rates below. An idle hour was still not measured.

**Computed** from design §9 (a `standard-1` instance costs about $0.04/h idle and up to about $0.075/h at full CPU;
snapshots are free in beta):

- a 15 s run: about $0.0002–0.0003 of container time; the 160 s run: about $0.0018–0.0033;
- an instance left to the 15-minute idle stop after a run: about $0.01 more. On 2026-11-17 the instance of the
  run that had ended was up for about 20.5 minutes after the run's end (log 14), so about $0.014 until the timer
  fix is deployed;
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
- **`stop` took about 4 s** on the deploy, against 0.25–2 s locally. In log 8 it took 6.6 s.
- **The old code answered after `wrangler deploy` had returned** (log 10). A workspace made two minutes before
  the deploy was still served by the old Worker code 33 s after the deploy returned, and that code started a new
  instance from the workspace's old snapshot. A workspace made 78 s after the deploy got the new code and image.
  Whether the delay belongs to a workspace's already-loaded object or to the whole Worker was not told apart.
- **An exec that leaves a process on its output pipes times out.** `setsid -f sleep N` through the test exec route
  answered 500 after 30 s on the deploy, with the process running; with its streams on `/dev/null` the same exec
  answered in 135 ms (log 14). Under `wrangler dev` the first form had returned at once, which is why acceptance
  check `S` passed locally and failed on the deploy (log 13).
- **`stdout.log` trailed a running task by up to a block.** The copier was `head -c`, which writes through stdio:
  a line the task wrote stayed in its buffer until 4 KiB more came or the task ended. On the deploy a 5 MB line
  written into a run's output was not in the event log 135 s later, and the two tool calls of the 20-minute run
  were logged at 13:02:06 and 13:12:07 for calls made at about 13:00:10 and 13:10:00 (log 14; the call times are
  worked out from the run's start and the sleeps' length). The same `head`
  shows it locally, and a container test now fails on it. One point is not explained: in the first oversized-line
  attempt the 5 MB line reached the event log at 13:11:06, four minutes after it was written, with the agent
  still in its `sleep` and no output of its known. Fixed in c258fc4 (`stdbuf -o0 head -c`), **not
  deployed**. `dd` was tried first and is no replacement: on a pipe its `count_bytes` counts short reads as blocks
  and stopped 80 KiB before the cap.
- **The idle stop came 18.5 and 25.5 minutes after the last request, not 15.** The inactivity timeout starts only when the Durable
  Object has left memory, and a pending timer keeps it there (Cloudflare's lifecycle page, for compatibility dates
  from 2026-10-01). Every exec armed `AbortSignal.timeout()`, which cannot be cancelled: 10 minutes for a clone,
  5 for a push. Both stops in log 14 came 15 minutes after such a timer ran out, to within a minute. That is an
  inference from two stops and the documentation; no deploy has run the fix yet. Fixed in cf868b2 (the timer is
  cleared when the command ends), **not deployed**.
- **The image has no `pkill`** (`procps` is not installed). The runner does not use it; a one-off test script did.
- **`wrangler containers list` lags.** Right after a `replace-instance` or a DELETE it still counted the instance
  as live; under a minute later it showed 0.
