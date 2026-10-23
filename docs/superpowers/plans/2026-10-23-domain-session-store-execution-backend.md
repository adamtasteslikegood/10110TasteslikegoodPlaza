# DomainSessionStore + ExecutionBackend plan (A, then A+B, C as end goal)

**Status:** Proposed. Plan only; no code changed. Written 2026-10-23 by systems-architect from
`docs/research/cloudflare-durable-objects/ANALYSIS.md` and the code at `73f5c03`.
Owner goal (Adam, 2026-10-23): build A and A+B first, spike-test, then C. The bridge should be able to switch
between A, A+B and C once all exist. A Hetzner VPS is an optional always-on stepping stone. Items marked UNVERIFIED
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

## Interfaces (phase 1)

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
- [ ] Add `domain_store.py` with `DomainSessionStore` and `MemoryStore` reproducing today's deque, caps and `replay()` semantics.
- [ ] Add a store contract test suite parametrised over implementations (append order, cursor edges, gap flag, trimming, restart).
- [ ] Make `DomainSession` use the store instead of `_entries/_output_bytes/_highwater`. Existing bridge tests must pass unchanged.
- [ ] Verify: `pytest bridge/tests` green; wire packets byte-identical for the existing replay tests.

### Phase 2: durable local store (mode A)
- [ ] Add `SqliteStore` (stdlib `sqlite3`, WAL, one file under `.git/plaza/`, no new dependency). Honour the "no service, database, dependency" constraint of M12 by confirming with Adam that stdlib SQLite is acceptable; if not, use an append-only JSONL file with the same contract tests.
- [ ] Define session identity across bridge restarts: today a new `domain_session_id` is a fresh uuid per generation. Decide whether a restarted bridge resumes the prior id or reports `history_gap`. Needs an owner decision (see Open questions).
- [ ] Contract suite passes for both stores. Add a crash test: kill after append, before emit; replay shows the event.

### Phase 3: ExecutionBackend seam (mode A)
- [ ] Add `ExecutionBackend`, and `LocalSdkBackend` wrapping the existing `domain_sdk` call path with no behaviour change.
- [ ] `DomainSession._run` calls the backend; `describe()` feeds runtime facts.
- [ ] Verify: existing tool-guard acceptance evidence (`tool_guard_acceptance.json`) still passes.

### Phase 4: relay (mode B), time-boxed spike then build
- [ ] Spike (1 day): one TypeScript Durable Object per domain with SQLite storage and hibernating WebSocket. The local bridge dials out and pushes appended packets. Wrangler dev only; no deploy until step 3.
- [ ] `RelayStore` = local store plus asynchronous mirror to the DO. Local store stays the source of truth; the DO is a replica clients can read. Reconcile by cursor (DO reports its high water; bridge resends the tail).
- [ ] Authn/TLS: per-bridge token, rotatable, never in the repo; the secret handling rule from the earlier credential incident applies.
- [ ] Security-auditor reviews the outbound-relay threat model before any deploy.
- [ ] Success criteria (from ANALYSIS.md): client reconnects mid-run with no loss or duplicates; no Claude credentials or worktree contents leave the laptop; added per-chunk latency measured and acceptable.

### Phase 5: cloud feasibility spike (mode C), one day, no commitment
Questions to answer with evidence, each logged in `docs/research/cloudflare-durable-objects/spike-c.md`:
- [ ] Can Claude Code run in a Sandbox container with the Agent SDK? (UNVERIFIED)
- [ ] Is subscription OAuth permitted and workable in a cloud container, or API key only? (UNVERIFIED; D-037 default is subscription-native.) Policy check before any credential is placed.
- [ ] Container scheduling policy status (beta) and per-run cost.
- [ ] Worktree story: clone per run vs persistent volume; how results return to the git remote.
- [ ] Optional baseline: the same `ExecutionBackend` on the Hetzner VPS (`RemoteHostBackend` over SSH or a small bridge agent) to prove the seam before Cloudflare. Cheaper, and gives always-on without the beta dependency.
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
| Subscription OAuth not allowed in cloud (C) | Medium | High | Phase 5 policy check first; fall back to API key or VPS-only |
| Container scheduling is beta (C) | Medium | Medium | ADR gate; the VPS backend proves the seam without it |
| Remote bridge widens the threat model (localhost to internet) | High | High | Security-auditor review before any deploy; fail-closed startup; no secrets in repo |
| Lease and worktree guards assume a local filesystem (D-015, D-005) | High | Medium | Leave leases local through phase 4; redesign for C only after the spike |
| Abstraction built before a second implementation exists | Medium | Low | Contract tests and the SQLite store in phase 2 are the second implementation |

## Open questions for Adam

1. Is stdlib SQLite acceptable given M12's "no database" constraint, or should the durable local store be a JSONL file?
2. After a bridge restart, should a domain resume its prior `domain_session_id` (new behaviour) or keep today's fresh id with a `history_gap`?
3. Cloud auth policy for C: subscription OAuth, API key, or neither until checked?
4. Should the Hetzner VPS backend (phase 5 baseline) be pulled ahead of the Cloudflare spike?

## Scope and ordering

Phases 1 to 3 are the "A" work and can proceed without any cloud account. Phase 4 needs a Cloudflare account and the
security review. Phase 5 is a spike and produces an ADR, not code to ship. Phase 6 closes the loop.
Suggested ticket split: one ticket per phase, each created with its open questions as comments (repo convention).
This plan does not alter any decision record; ratifying the plan and any new D-numbers is the owner's call.
