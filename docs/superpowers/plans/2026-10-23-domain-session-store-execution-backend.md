# DomainSessionStore + ExecutionBackend plan (A, then A+B, C as end goal)

> **Current scope (PLZG-290 / #373):** the separately approved
> [bounded in-memory design](../specs/2026-10-25-m13-memory-store-extraction-design.md)
> and [execution record](2026-10-26-m13-memory-store-extraction.md) govern phase 1,
> which is implemented on `plaza/workspace-integration` pending dev delivery.
> Phases 2–6 below remain proposals requiring their bounded designs and owner
> review. Recorded owner answers are incorporated below; unresolved product
> choices remain in [M13 decisions/questions](../../../M13_DECISIONS_AND_QUESTIONS.md).
> This document originates no locked decision or provider selection.

**Status:** Proposed. Plan only; no code changed. Written 2026-10-23 by systems-architect from
`docs/research/cloudflare-durable-objects/ANALYSIS.md` and the code at `73f5c03`.
Owner goal (Adam, 2026-10-23): build A and A+B first, spike-test, then C. The bridge should be able to switch
between A, A+B and C once all exist. The owner requires a Hetzner execution host alongside the laptop in B; it is not an optional phase-5 baseline. Items marked UNVERIFIED
are not established by evidence in the repo or the captured research.

## Modes

| Mode | Where state lives | Where Claude Code runs | New trust boundary |
|---|---|---|---|
| A | Local store (SQLite) | Local worktree | None |
| A+B | Local store, mirrored to one Durable Object per domain | Local worktree | Outbound WebSocket to the DO |
| C | Durable Object (Agents SDK) | Sandbox container (or Hetzner VPS as a stand-in) | Credentials and code in the cloud |

The mode is a bridge configuration value (`EXECUTION_MODE`: `local`, `relay`, `cloud`), resolved at startup by the
same precedence as other config (built-ins, selected JSON, env). It is not switched mid-run.

## What exists today (verified in the repo)

- `DomainSession` keeps output in a process-local `deque` (`_entries`), capped by `MAX_ENTRIES` and `MAX_TOTAL_OUTPUT_BYTES`.
  Entries are terminal `domain_result` packets with a monotonic `output_id` (`_highwater`).
- `DomainSession.replay(cursor)` already returns entries after a cursor plus a `resume_complete` packet carrying
  `high_water_mark`, `earliest_output_id` and `history_gap`. So the cursor protocol exists; only its storage is volatile.
- `DomainManager` holds sessions in a dict (max 10 domains, 2 generations each). Durable state is only project memory
  (`project_memory.py`, `.git/plaza/session-memory`) and the workspace lease (`workspace_lease.py`).
- `domain_sdk.py` runs Claude Code through the Agent SDK against the owned worktree.

Consequence: the store interface is mostly an extraction of what `DomainSession` already does, not a new protocol.
Godot-facing packets must not change in phase 1 (D-005/D-020 client independence).

## Historical interface sketch (superseded for phase 1)

The async sketch below is retained as proposal history. The approved bounded
extraction instead uses synchronous `append`, `find_request` and `replay` with
`ReplayWindow`; see `bridge/domain_store.py`. It does not include leases or
project memory in the store. Durable I/O requires a separate caller/ownership design.

Names are proposals. Place in `bridge/domain_store.py` and `bridge/execution_backend.py`.

```python
class DomainSessionStore(Protocol):
    async def append(self, domain_id: str, session_id: str, packet: dict) -> int: ...      # returns output_id
    async def read_since(self, domain_id: str, session_id: str, cursor: int) -> ReplayResult: ...
    async def high_water(self, domain_id: str, session_id: str) -> int: ...
    async def trim(self, domain_id: str, session_id: str, *, max_entries: int, max_bytes: int) -> None: ...
```

`ReplayResult` carries `packets`, `high_water_mark`, `earliest_output_id`, `history_gap`, i.e. what `replay()` builds today.
Leases and project memory stay behind their existing classes for now; they guard a local filesystem and are not moved
until phase 4 (see risks).

```python
class ExecutionBackend(Protocol):
    async def run(self, command: RunCommand, emit: Emit) -> RunOutcome: ...   # wraps domain_sdk
    async def cancel(self, request_id: str) -> None: ...
    def describe(self) -> BackendFacts: ...    # kind, tools, permission_mode; feeds bridge runtime facts
```

`BackendFacts` feeds the "Bridge runtime facts" block, so tool and permission reporting stays authoritative per backend.

Rules: `append` is the only writer of `output_id`; ids are dense and monotonic per session; `read_since` is idempotent;
an event is durable before it is emitted to any client (so replay never misses an emitted packet).

## Phases

Each phase ends with passing tests and its own commit. Do not start a phase before the previous one is merged.

### Phase 1: extract the store (mode A, in-memory)
- [x] Add `domain_store.py` with `DomainSessionStore` and `MemoryStore` reproducing today's deque, caps and `replay()` semantics.
- [x] Add a store contract test suite parametrised over implementations (append order, cursor edges, gap flag, trimming, fresh-instance isolation; no restart durability).
- [x] Make `DomainSession` use the store instead of `_entries/_output_bytes/_highwater`. Existing packet/execution-count expectations pass; two private-deque reads migrated to public replay.
- [x] Verify: `pytest bridge/tests` green; wire packets byte-identical for the existing replay tests.

### Phase 2: durable local store (mode A)
- [ ] Add `SqliteStore` (stdlib `sqlite3`, WAL, one file under `.git/plaza/`, no new dependency). SQLite is already accepted by Adam; no JSONL fallback or repeat approval question. WAL/file location remain proposed details to settle in the bounded persistence design. The M12 no-database statement limits M12, not later work.
- [ ] Design the recorded requirement: resume application session identity across restarts unless intentionally ended by user or bridge; persist end state and attribution. Settle Stop versus End, generation/cursor and interrupted-execution semantics before implementation. No automatic SDK recovery or tool execution on reconnect is authorized.
- [ ] Contract suite passes for both stores. Add a crash test: kill after append, before emit; replay shows the event.

### Phase 3: ExecutionBackend seam (mode A)
- [ ] Add `ExecutionBackend`, and `LocalSdkBackend` wrapping the existing `domain_sdk` call path with no behaviour change.
- [ ] `DomainSession._run` calls the backend; `describe()` feeds runtime facts.
- [ ] Verify affected guard sources and actual runtime/mode bindings. If extraction changes guarded fingerprints, collect fresh bounded evidence; never rehash or restamp historical observations to make existing acceptance pass.

### Phase 4: relay (mode B), time-boxed spike then build
- [ ] Spike (1 day): a TypeScript Durable Object relay with SQLite storage and hibernating WebSocket. Stable object keys, writer/lease authority and replica reconciliation are unresolved design questions (Q03/Q06), not a settled per-domain versus per-session choice. Execution hosts dial out and push approved relay data. Build laptop and Hetzner host support together in B, with host identity, affinity and explicit unavailable-host behavior. Wrangler dev only; no deploy until step 3.
- [ ] `RelayStore` = local store plus asynchronous mirror to the DO. Local store stays the source of truth; the DO is a replica clients can read. Reconcile by cursor (DO reports its high water; bridge resends the tail).
- [ ] Authn/TLS: per-bridge token, rotatable, never in the repo; the secret handling rule from the earlier credential incident applies.
- [ ] Security-auditor reviews the outbound-relay threat model before any deploy.
- [ ] Success criteria (from ANALYSIS.md): client reconnects mid-run with no loss or duplicates; Claude credentials and worktrees remain on their assigned execution hosts; define exactly which data may reach the relay (Q06). Measure terminal-append/replay latency; this does not authorize provider streaming.

### Phase 5: cloud feasibility spike (mode C), one day, no commitment
Questions to answer with evidence, each logged in `docs/research/cloudflare-durable-objects/spike-c.md`:
- [ ] Can Claude Code run in a Sandbox container with the Agent SDK? (UNVERIFIED)
- [ ] Verify both requested subscription OAuth and API-key paths in a cloud container, including applicable provider policy, injection and secret lifecycle (UNVERIFIED remotely). D-037 selects Claude Code via Agent SDK by default, not an OAuth-only credential rule. No automatic auth/backend fallback.
- [ ] Container scheduling policy status (beta) and per-run cost.
- [ ] Worktree story: clone per run vs persistent volume; how results return to the git remote.
Hetzner execution is required in phase 4/B, per the recorded owner answer; it is not an optional step in this Cloudflare feasibility spike.
- [ ] Decision gate: write an ADR (go / no-go / VPS-only) with measured numbers.

### Phase 6: mode switch
- [ ] `EXECUTION_MODE` config, backend and store factories, startup validation that fails closed (e.g. `cloud` without credentials refuses to start).
- [ ] Runtime facts report the active mode truthfully; Godot needs no change unless it must display the mode (separate ticket).
- [ ] Documented switching procedure and a smoke test per mode.

## Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Store extraction changes replay packets and breaks Godot | Low | High | Phase 1 keeps packets byte-identical; contract tests; no protocol change |
| Two stores diverge in A+B | Medium | Medium | Local store is the single source of truth; DO is a replica reconciled by cursor |
| Subscription OAuth not allowed in cloud (C) | Medium | High | Verify requested auth paths and policy in phase 5; unsupported paths require an explicit design disposition, not automatic fallback |
| Container scheduling is beta (C) | Medium | Medium | ADR gate; the VPS backend proves the seam without it |
| Remote bridge widens the threat model (localhost to internet) | High | High | Security-auditor review before any deploy; fail-closed startup; no secrets in repo |
| Lease and worktree guards depend on their execution host filesystem (D-038) | High | Medium | Leave leases local through phase 4; redesign for C only after the spike |
| Abstraction built before a second implementation exists | Medium | Low | Contract tests and the SQLite store in phase 2 are the second implementation |

## Remaining design questions

The four original owner questions were answered on 2026-10-23; their verbatim
answers are retained below. Do not ask them again. The remaining choices are
Stop/End and restart execution semantics; stable project/domain/session/host and
DO keys; writer/lease and split-brain behavior; relay data/retention/auth policy;
and containment guarantees/sequencing. These remain in Q02–Q06/Q11 and must be
settled in the appropriate future bounded design, not by phase-1 extraction.

## Scope and ordering

Phases 1 to 3 are the "A" work and can proceed without any cloud account. Phase 4 needs a Cloudflare account and the
security review. Phase 5 is a spike and produces an ADR, not code to ship. Phase 6 closes the loop.
Suggested ticket split: one ticket per phase, each created with its open questions as comments (repo convention).
This plan does not alter any decision record; ratifying the plan and any new D-numbers is the owner's call.

## Owner answers (Adam, 2026-10-23) - supersede the open questions above

1. **SQLite: accepted.** M12 policy ("no database") will be updated by the owner; phase 2 uses stdlib `sqlite3`, no JSONL fallback. The policy edit is a separate owner-directed change, not part of this plan.
2. **Session id: resume across bridge restarts**, unless the user or the bridge intentionally ended the session. Phase 2 must persist the id, an explicit `ended` marker and who ended it (user or bridge). Crash or restart is not an end. Needs a spec note against the M12 generation rules (new uuid per generation today).
3. **Auth: both subscription OAuth and API key**, same as the local runtime; sign-in/token injection is the same for either path. A keyless federated option exists but is not available on the account (UNVERIFIED as a sub-option). Phase 5 still verifies that credential injection works inside a container and records what the policy permits; it no longer assumes API-key-only.
4. **Hetzner is a second machine, part of B, built at the same time.** B now means a relay with two execution hosts: the laptop and the VPS. `ExecutionBackend` therefore needs a host identity, and the store/relay must handle sessions bound to a host. Phase 5's VPS baseline moves into phase 4; phase 5 keeps only the Cloudflare Sandbox questions.

Consequences to design in phase 3/4: a session records its `host_id`; a resumed session routes to the same host or reports it unavailable; worktrees and credentials live per host; the DO relay is the shared index of sessions across hosts.
