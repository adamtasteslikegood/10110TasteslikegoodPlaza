# M13 Memory Store Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract #373's bounded in-memory terminal store without changing domain behavior.

**Architecture:** A synchronous per-session `DomainSessionStore` protocol owns append/ID allocation, retention, lookup and replay metadata. `MemoryStore` implements it; `DomainSession` retains execution, checkpointing, identity, snapshots and delivery. No suspension point is added to admission or terminal mutation.

**Tech Stack:** Python stdlib typing/dataclasses/deque; existing pytest/pytest-asyncio; existing Godot integration gates.

**Spec:** `docs/superpowers/specs/2026-10-25-m13-memory-store-extraction-design.md`, approved by Adam 2026-10-26 with authorization to proceed through planning and implementation.

## Global Constraints

- Output IDs start at 1, are dense per session and appear as decimal strings on the wire. Trimming never reduces or reuses the high-water mark.
- Retain at most 256 terminal entries and 4 MiB of **output text UTF-8 bytes**.
- Per-result truncation remains the existing 256 KiB logic in `DomainSession`.
- Reject invalid cursors exactly as today, including bool/non-int and negatives.
- No Godot/protocol/config/dependency/provider changes are in scope.
- No SQLite, persistence, recovered SDK process, session End behavior, host identity, concurrent department execution or sandbox claim.
- Existing retained packet expectations remain unchanged. Two integration tests inspect the removed private deque; migrate only those accesses to `replay(0)[:-1]`, avoiding a test-only compatibility property.

## Review Focus

- Metadata-heavy terminal packets must not consume the output-text byte allowance (Task 1).
- UTF-8 multibyte output at the exact 4 MiB boundary must be retained until the next byte crosses it (Task 1).
- Trimming all entries must preserve highwater and the gap even with no earliest retained ID (Task 1).
- Caller mutation of append, lookup or replay packets must never mutate retained state (Task 1).
- Duplicate-request lookup must stop recognizing IDs when retention trims them, while session conflicts remain rejected (Tasks 1–2).

### Task 1: Store contract and MemoryStore

**Files:** Create `bridge/domain_store.py`, `bridge/tests/test_domain_store.py`.

**Interfaces:**
- `ReplayWindow` frozen dataclass: `entries: list[dict]`, `high_water_mark: int`, `earliest_output_id: int | None`, `history_gap: bool`.
- `DomainSessionStore` protocol: synchronous `append(terminal: dict) -> dict`, `find_request(request_id: str) -> dict | None`, `replay(cursor: int) -> ReplayWindow`.
- `MemoryStore()` uses fixed existing caps; no persistence or runtime configuration. `append` copies input, assigns its next output ID and returns an independent terminal, even if retention drops it. Lookup returns the oldest retained matching ID, matching the old scan. Replay raises existing `DomainCommandError` for invalid cursor types/values.

- [x] Write factory-parametrized contract tests for: empty store `(entries=[], highwater=0, earliest=None, gap=False)`; append IDs `1,2`; cursors `0,1,2,99`; invalid `True,False,-1,1.0,'1',None`; count trim after 258 outputs `(256 entries, earliest=3, highwater=258)`; exact 4 MiB Unicode output then overflow; large metadata ignored by byte accounting; oversized output trimming to empty with highwater 1 and gap at cursor 0; retained lookup eviction; defensive nested copies; independent stores and fresh empty instances.
- [x] Run `python -m pytest bridge/tests/test_domain_store.py -q`; expect failure because the store implementation is absent.
- [x] Implement the protocol, replay metadata and deque store. Retain output-byte accounting and highwater independently of trimming.
- [x] Run the contract suite; expect all cases pass. Run Black on new Python files.
- [x] Commit `refactor(PLZG-290): extract bounded in-memory domain store`.

### Task 2: Route DomainSession through the store

**Files:** Modify `bridge/domain_session.py`; add `bridge/tests/test_domain_store_session.py`; migrate private reads in `bridge/tests/test_m12_integration.py` and `bridge/tests/test_godot_domain_integration.py`.

**Interfaces:** Consume Task 1's synchronous protocol. Add optional keyword-only `store: DomainSessionStore | None = None` to `DomainSession`; default to a new `MemoryStore` for every session. Retain all existing constructor callers and `replay(cursor) -> list[dict]` packets.

- [ ] Write a real-store session test using existing setup/fakes: inject MemoryStore, run a real domain task, assert delivered terminal equals stored result and public replay packet, duplicate is not reexecuted, conflict rejects; a second session remains empty. Expect initial failure for unsupported `store` constructor argument.
- [ ] Run `python -m pytest bridge/tests/test_domain_store_session.py -q`; expect the above failure.
- [ ] Replace deque/highwater/byte ownership with the store; lookup before inflight checks; append after `_save` and before clearing inflight; compose unchanged resume packet from replay metadata and current snapshot. Keep truncation, recording and delivery order untouched.
- [ ] Replace only the two integration tests' private deque accesses with public replay results. Preserve their packet equality and execution-count assertions.
- [ ] Run `python -m pytest bridge/tests/test_domain_store.py bridge/tests/test_domain_store_session.py bridge/tests/test_domain_session.py bridge/tests/test_m12_integration.py -q`; expect all pass, including original count/byte trimming, retained duplicates and immutable replay tests.
- [ ] Commit `refactor(PLZG-290): delegate domain terminal retention to store`.

### Task 3: Regression verification and handoff

**Files:** Update this plan's execution record, approved design status, `M13_DECISIONS_AND_QUESTIONS.md`, `CHANGELOG.md`; index this plan in `specs/meta/doc-registry.json` as a derived execution artifact.

- [ ] Run full `python -m pytest bridge/tests -q` and `npm test` using available Godot; report the exact tested engine version and any difference from CI's pinned engine. Expect no failures or skipped required Godot integration.
- [ ] Run `black --check .`, `flake8 . --select=E9,F63,F7,F82`, `python scripts/validate_specs.py`, `git diff --check`; expect success.
- [ ] Compare all twelve `GUARD_SOURCES` and fixed guard acceptance evidence to the approved starting commit; expect unchanged. Run `_verify_runtime` for `dontAsk` and `bypassPermissions`; expect success without rewriting evidence.
- [ ] Obtain fresh whole-change review against the approved design; address correctness findings with regression tests. Commit final verification/handoff and push the integration target without altering dev. Broader canon questions remain in the owner queue; no phase 2 begins here.

## Execution record

- Design approved; planning and implementation authorized together. Native execution chosen for this tightly coupled two-component extraction, with one fresh final review.
- Pre-flight Task 1 → Task 2: protocol signatures and replay metadata match; no interface conflicts.
- Existing integration tests' private-deque reads require the explicit migration above; no packet expectations change.
- Skill task-helper scripts are not accessible through the installed cloud resource; record progress here rather than inventing successful helper runs.

- Task 1 complete: absent-module RED; contract suite GREEN, 19 passed; new files Black-clean.
