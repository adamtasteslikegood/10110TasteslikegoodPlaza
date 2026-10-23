# Durable Objects + Workers Python + Agents SDK: fit for bridge domain sessions

Status: Proposed (analysis only, no decision taken). Evidence: files in `raw/` (fetched 2026-10-22) and the repo
(`bridge/domain_manager.py`, `workspace_lease.py`, `project_memory.py`, 2026-08-12 domain-architecture spec).
Items marked UNVERIFIED are not stated in the captured pages.

## Question
Can Cloudflare Durable Objects (DO), Python Workers and the Agents SDK host the bridge's domain-scoped parallel sessions?

## What the bridge does today
- One local Python process on ws://localhost:8765 (D-015). Godot is the only client.
- A domain session drives Claude Code through the Agent SDK against a git worktree the domain owns (lease, immutable branch,
  execution_capacity 1, dontAsk permission mode).
- Domain clients and output buffers are process-local (the spec says so). Durable state is only project memory in `.git/plaza/session-memory`.
- The unmet need is "walk away and come back": a durable identity, event log and output buffer per domain session.

## Mapping
| Bridge concept | Cloudflare primitive | Fit |
|---|---|---|
| Domain session identity / single writer | DO addressed by ID, single-threaded | Strong |
| Output buffer, event log, project memory | DO SQLite storage (10 GB per object, `05-limits.md`) | Strong |
| Reconnecting client | WebSocket with hibernation (`06-pricing.md` notes billing differs when hibernated) | Strong |
| Background/scheduled work | DO alarms; Agents SDK scheduling | Good |
| Workspace lease / reservation | DO as lock owner | Good, but the lease guards a local filesystem |
| Running Claude Code in a git worktree | Needs a Linux process and filesystem: Sandbox SDK / Containers only | DO and Workers cannot do this |

## Findings
1. **Python Workers are the wrong host for the execution plane.** Python needs the `python_workers` flag and pywrangler
   (`07-workers-python.md`). Worker CPU is 30 s default, configurable to 5 min (`05-limits.md`). The Agent SDK launching the Claude Code CLI as a
   subprocess is UNVERIFIED against Workers but is very unlikely to work there. I did not find Python DO class support in the captured pages (UNVERIFIED either way).
2. **The Agents SDK is a durable-state layer, not a code-execution layer.** It gives identity, SQL state, WebSockets, scheduling and recovery
   (`09-agents-sdk.md`). Code execution is delegated to Sandbox. It is aimed at agents running inside Cloudflare, not at wrapping a local Claude Code.
3. **Sandbox SDK + Containers is the only in-Cloudflare route to the current execution model.** `10-sandbox-sdk.md` lists Claude Code as a
   supported workload, one sandbox per task, with a DO providing identity and coordination. The DO scheduling policy for containers is public beta.
4. **Cost is probably not the constraint.** DO: 1M requests and 400k GB-s per month included, then $0.15/M requests and $12.50/M GB-s. Duration is
   billed on 128 MB regardless of use while the object is active and not hibernatable (`06-pricing.md`). Container/sandbox cost not yet analysed.
5. **The real blockers are non-technical.** (a) Auth: D-037 makes Claude Code via Agent SDK with subscription-native auth the default. A cloud
   container would need credentials placed in it; whether subscription OAuth is permitted there is UNVERIFIED and needs a policy check. (b) Security:
   today's tool guard is Git-ownership checks, "not filesystem, network or process containment". A remote bridge needs real authn/TLS and moves
   the threat model from localhost to the internet. (c) D-015 and D-005 assume a local Godot client.

## Options
| Option | Description | Pros | Cons |
|---|---|---|---|
| A. Stay local | Keep the bridge as is; add a durable store locally (SQLite) | No new trust boundary, smallest change | Sessions die with the laptop |
| B. Hybrid | Local bridge keeps execution. A DO per domain session is the durable relay and log; the bridge dials out over WebSocket | Fixes walk-away/return and multi-device, keeps credentials and worktrees local, small cloud surface | Two stores to reconcile; new authn; cloud bill and ops |
| C. Full cloud | DO/Agents SDK coordinator plus Sandbox containers running Claude Code | Always-on, scales out | Auth/policy questions, beta dependency, largest security change, rewrites workspace/lease code |

## Owner goal update (2026-10-23)
Adam's plan: build A, then A+B, spike-test, and treat C (Workers + Durable Objects + Sandbox) as the real end goal. The bridge
should be able to switch between A, A+B and C once all exist. A Hetzner VPS is an optional always-on stepping stone. This
supersedes "do not migrate" as the long-term direction; the near-term sequencing below still holds. The implementation plan is
`docs/superpowers/plans/2026-10-23-domain-session-store-execution-backend.md`. C feasibility (Claude Code in a Sandbox, cloud
auth policy, container beta status and cost) remains UNVERIFIED and is the subject of that plan's phase 5 spike.

## Recommendation
Do not migrate yet. Take option A's first step, designed for B and C:
1. Extract a `DomainSessionStore` interface (append event, read since cursor, get/set lease, get/set memory) behind `domain_manager`, with a local SQLite
   implementation. This is cheap structure, matching the owner's "weight toward structure" rule.
2. Make the output buffer a cursor-addressed event log, so reconnect = replay from cursor. The DO model is the same, so a later DO implementation is a drop-in.
3. Only then run a time-boxed spike of B: one TypeScript DO as a relay for one domain, local bridge dialling out. Python Workers and option C are not recommended spikes.

## Success criteria for the spike
- A client disconnects mid-run and reconnects to the full output with no loss and no duplicates.
- No Claude credentials or worktree contents leave the laptop.
- Added latency per streamed chunk is measured and acceptable for the typewriter UI.

## Open questions (for Adam)
- Is the goal multi-device/always-on, or only reconnect on one laptop? If only the latter, A suffices.
- Is cloud-hosted Claude Code on subscription auth acceptable, or API-key only?
- Should security-auditor review the outbound-relay threat model before the spike?
