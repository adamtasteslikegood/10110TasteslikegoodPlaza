# M13 first increment — extract the in-memory domain store (#373)

Status: owner-approved 2026-10-26; bounded #373 implementation authorized.
Execution: [implementation plan](../plans/2026-10-26-m13-memory-store-extraction.md).

## Scope and dependencies

Continue Plaza from `plaza/workspace-integration`. The separate shared gate
issue `codex-pr-review-gate-cc#29` is useful tooling, not a technical dependency
of this increment. No UUID service, DO deployment or central gate ledger is
required to move the current in-memory buffer behind a store boundary.

Use the first phase of the existing store/backend proposal: `DomainSessionStore`
and `MemoryStore` in `bridge/domain_store.py`, preserving current behavior.
Follow with durable local storage in a separate phase; remote execution and
relay remain later work. This design selects no new provider or D-number.

## Existing behavior to preserve

The inspected `bridge/domain_session.py` owns a deque, a UTF-8 output-byte total
and a monotonic terminal-output high-water mark. It uses that buffer for both
replay and duplicate-request lookup. The extraction must preserve both paths.

- Output IDs start at 1, are dense per session and appear as decimal strings on
  the wire. Trimming never reduces or reuses the high-water mark.
- Retain at most 256 terminal entries and 4 MiB of **output text UTF-8 bytes**.
  Do not change the byte cap to JSON packet size. Per-result truncation remains
  the existing 256 KiB logic in `DomainSession`.
- Replay selects retained results with `cursor < output_id <= highwater`, then
  appends the existing session-derived `resume_complete` packet. Keep its exact
  string high-water/earliest IDs, null earliest value for an empty buffer and
  `history_gap = cursor < earliest - 1` semantics.
- Reject invalid cursors exactly as today, including bool/non-int and negatives.
- Replay returns independent packet copies; clients cannot mutate retained data.
- A retained duplicate request returns its existing result; conflicting agent or
  task content is rejected. Do not accidentally extend duplicate detection past
  the existing retention window.
- Admission, checkpoint/result ordering, `_inflight` handling, memory warnings,
  cleanup, reservation ownership and explicit Start/Run/Stop remain unchanged.

## Boundary and approach

Extract a narrow per-session store protocol plus the existing in-memory
implementation. The store owns terminal append/ID allocation, retention,
lookup and replay-data reads. `DomainSession` owns identity, admission, provider
execution, memory saves, session snapshots and packet delivery. It constructs
the final resume packet from the store's replay metadata and current snapshot.

Implementation choice for this increment: keep in-memory operations synchronous,
matching today's no-await buffer mutation and synchronous `replay()` API.
The older proposal's async sketches are not a reason to add suspension points
to a behavior-preserving extraction. A later persistence design must explicitly
reconcile durable I/O with admission/ownership and caller contracts; this phase
does not claim that an async network store is already a drop-in replacement.

Alternative: start with a durable/remote-ready store and change caller APIs now.
That would combine persistence, I/O failures and recovery with an extraction,
so it is deferred. Leaving the deque in `DomainSession` avoids an abstraction
but does not deliver #373's requested store boundary.

## Acceptance

Add a reusable contract-test factory for MemoryStore, with append order, cursor
edges, UTF-8 byte/count trimming, empty-after-trim high-water behavior, defensive
copying, request lookup and independent store/session isolation. A new memory
store starts empty; do not call this bridge-restart persistence.

Keep existing replay/admission/session-manager tests and their expected packets
unchanged. Run the complete bridge Python suite, formatting/fatal lint and
affected existing protocol/Godot integration gates. Verify the reviewed code
does not alter any of the twelve guard sources or fixed acceptance records;
check actual runtime verification without rewriting evidence. Historical paid
live reports remain bound to the versions they executed, not this new code.

No Godot/protocol/config/dependency/provider changes are in scope. No persistent
SQLite store, recovered SDK process, session End behavior, host identity,
concurrent department execution or sandbox claim is made in this increment.

## Following increments

After this extraction is accepted: design the SQLite store and explicit
restart/end/recovery contract; then the backend seam; then authenticated relay
and second-host execution; then the cloud execution feasibility work. Existing
owner answers (SQLite, resume unless intentionally ended, both auth paths,
Hetzner in B) remain inputs, not questions to ask again. Resolve the remaining
details through Adam's working queue and entitled governing documents before
changing those behaviors. Shared gate #29 may proceed independently and inform B.
