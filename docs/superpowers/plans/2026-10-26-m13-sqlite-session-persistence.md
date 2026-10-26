# M13 SQLite Session Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore bounded project-scoped application sessions and conversation continuity across bridge restarts, without restarting agent work implicitly.

**Architecture:** A worker-owned in-memory SQLite connection commits serialized database images through anchored atomic file operations. An asynchronous coordinator publishes committed replay views to the event loop; application sessions outlive separately fenced execution instances. Protocol v2 and both Godot work surfaces distinguish Stop, End, restored history and unsaved results.

**Tech Stack:** Existing Python stdlib SQLite/asyncio, pytest/pytest-asyncio, existing Godot/GDScript and pinned CI engine; no new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-10-26-m13-sqlite-session-persistence-design.md`, approved by Adam October 26, 2026, with direction to prepare the implementation plan and handoff. Adam approved this plan and selected subagent-driven development October 26, 2026.

## Global Constraints

- One configured repository; state at `<common-git-dir>/plaza/application-state/state.sqlite3`; stable `writer.lock` and initialization manifest. Paths derive from validated project facts, never client input.
- SQLite schema v1, stdlib serialize/deserialize required; no WAL/journal sidecars, JSONL fallback, automatic memory fallback or silent database recreation.
- Image at most 64 MiB; at most 128 sessions and 10 domains. Atomic replacement can consume old plus new images (128 MiB) and failed temporary remnants; this is not a total disk quota.
- Replay: 256 terminals / 4 MiB output-text UTF-8 per session; output 256 KiB, task 64 KiB, UTF-8 terminal JSON 2 MiB. Admission reserves 2 MiB logical completion allowance; physical failures remain possible.
- One unfinished accepted Run per domain; global execution capacity remains one. Completed duplicate recognition expires with retained terminals; unfinished requests do not expire.
- Stop preserves application identity; End persists attribution and requires confirmed orderly cleanup. Game/bridge exit and crash do not End. Reconnect/status/replay never starts SDK/model/tools.
- Fresh execution UUID per explicit Start; persisted decimal-string domain revision fences Start/End. Stable application UUID is not an SDK resume token.
- Recap: latest four completed task/result pairs, chronological; task excerpt 1 KiB, answer 2 KiB, total rendered text including labels/notice 16 KiB UTF-8. Deterministic, no model summarizer; once on the first Run of each execution.
- Project notes, diagnostic archives, application state and future shared PR ledger remain separate. Preserve D-005/D-020/D-037/D-038/D-039 and both authentication paths; no remote backend/sandbox work here.
- Never restamp historical guard reports. New execution-authorizing code joins the guarded-source inventory and receives fresh actual evidence before acceptance.

## Review Focus

- A crash after creating initialization intent must block silent empty recreation, including manifest-without-image and image-before-ready (Tasks 1–2).
- Cancellation during rename/fsync must leave owned work draining and admission closed until the committed revision is reconciled (Tasks 3, 6).
- Delayed controls from an older SDK execution must not Stop or Run the newly activated execution, even when the application UUID matches (Tasks 4, 8).
- Control characters and multibyte text must obey packet/image/recap bounds independently of output-text retention (Tasks 2, 7).
- A fresh game process, an ended-only history and switching explicitly between memory/SQLite must display their actual continuity without automatically starting work (Tasks 4, 8–9).

---

## File structure and shared interfaces

New modules have one responsibility; keep existing `MemoryStore` synchronous and its original contract tests intact.

| File | Responsibility |
|---|---|
| `bridge/application_state.py` | Frozen records, repository protocol, typed storage errors and limits; no I/O |
| `bridge/sqlite_state.py` | Worker-thread-only schema, validation, transactions, trimming and image serialization |
| `bridge/state_image.py` | Anchored image/manifest/lock lifecycle and durable replacement |
| `bridge/state_coordinator.py` | Owned single worker, serialized async commands and committed event-loop views |
| `bridge/session_recovery.py` | Startup request classification and safe deferred Markdown reconciliation |
| `bridge/session_recap.py` | Pure bounded recap rendering |
| `scripts/domain_state.py` | Offline lock-respecting export/delete operator CLI |
| Existing manager/session/server/config/protocol/context and Godot files | Lifecycle, admission, wiring and client changes described below |

Shared types in `application_state.py` (all frozen dataclasses; nested packets copied at boundaries):

- `StateError(code: str, *, uncertain: bool = False)`; codes include `state_store_busy`, `state_store_invalid`, `state_store_unsupported`, `state_store_quota`, `state_store_failed`, `state_store_uncertain`. Public messages exclude SQL, task text and filesystem internals.
- `StateView(project_id: str, instance_id: str, revision: int, domains: tuple[DomainRecord, ...], sessions: tuple[SessionRecord, ...], executions: tuple[ExecutionRecord, ...], requests: tuple[RequestRecord, ...], terminals: tuple[TerminalRecord, ...])`.
- `DomainRecord(domain_id: str, current_session_id: str | None, domain_revision: int)`; absent domain revision is 0.
- `SessionRecord(session_id: str, domain_id: str, created_at: str, ended_at: str | None, ended_by: str | None, high_water_mark: int)`.
- `ExecutionRecord(execution_id: str, session_id: str, boot_id: str, started_at: str, stopped_at: str | None, outcome: str | None)`.
- `RequestRecord(session_id: str, request_id: str, execution_id: str, agent_id: str, task: str, task_digest: str, turn_id: str, memory_revision: int, disposition: str, allowance_bytes: int)`; dispositions `accepted`, `dispatched`, `terminal`, `recovered`.
- `TerminalRecord(session_id: str, request_id: str, output_id: int, packet: dict, output_bytes: int)`; frozen packet is a defensive copy, not a reference to a mutable caller dictionary.
- `StateCommand(kind: str, payload: dict)`; closed command kinds `start`, `accept`, `dispatch`, `terminal`, `stop`, `end`, `recover`, `delete_ended`. Payloads below are internal validated records, not raw client dictionaries.
- `StateCommit(view: StateView, result: dict)`; result contains generated UUIDs, updated domain revision or saved terminal as appropriate.
- `StateRepository` worker-only methods `load() -> StateView | None`, `apply(command: StateCommand) -> StateCommit`, `close() -> None`.

`SQLiteStateRepository` implements this contract. `VolatileStateRepository` implements the same application lifecycle in memory; it is distinct from the existing terminal-only `MemoryStore`. Replay views preserve loaded numeric IDs/highwater without re-appending restored packets to allocate replacement IDs.

## Task 1: Safe image ownership and initialization

**Files:** Create `bridge/application_state.py`, `bridge/state_image.py`, `bridge/tests/test_state_image.py`; consume existing `bridge/project_files.py` without weakening its safeguards.

**Interfaces:** `StateImage.open(common_git_dir: Path, project_id: str, *, initialize: bool = False, initial_image: Callable[[str], bytes] | None = None) -> StateImage | None`; `read() -> bytes`; `replace(data: bytes) -> None`; `close() -> None`. The returned object holds a validated stable `FileLock` until close, checks its inode before commits, and exposes `instance_id: str`. Missing both artifacts with initialize=False returns None without creating directories/locks. Explicit initialization requires initial_image(instance_id) from Task 2’s schema factory (Task 1 tests use a stdlib-generated SQLite fixture); generate the instance UUID once and pass it to that callback and the manifest. Initialization never invents the schema itself. Define the shared records/protocol from the interface map in this task so later modules can import them. Manifest filename is `manifest.json`, with version1, project_id, instance_id and state `initializing`/`ready`.

- [x] Write tests `test_missing_read_does_not_initialize`, `test_second_writer_busy`, `test_manifest_without_image_blocks`, `test_image_before_ready_blocks`, `test_missing_after_ready_blocks`, `test_orphan_image_blocks`, `test_unsafe_inode_rejected`. Assert no implicit recreation and original bytes preserved; cover symlink/hardlink/parent swaps, lock inode replacement, regular mode0600 files in mode0700 directories.
- [x] Run `python -m pytest bridge/tests/test_state_image.py -q`; require RED for the absent implementation.
- [x] Implement anchored reads/replacement and OS-lock ownership. Initialization writes initializing manifest, valid image, then ready manifest, each durably; interrupted initialization always requires explicit inspection. Require serialize/deserialize support before initialization. On failed/uncertain writes retain evidence, never unlink lock files or unknown remnants.
- [x] Run the new suite plus `bridge/tests/test_project_files.py` if present; otherwise locate and run existing project-files coverage by `rg -l 'FileLock|atomic_replace' bridge/tests`. Require GREEN including both initialization crash points.
- [x] Commit `feat(PLZG-290): add safe application state image ownership`.

## Task 2: SQLite records, bounds and replay contracts

**Files:** Create `bridge/sqlite_state.py`, `bridge/tests/test_sqlite_state.py`; extend `bridge/tests/test_domain_store.py` only with reusable contract fixtures, preserving original expectations.

**Interfaces:** Task 1 image handle; `SQLiteStateRepository(image: StateImage)` implements StateRepository; `initial_image(project_id: str, instance_id: str) -> bytes` creates its valid empty v1 image. The manifest/image instance UUID is generated once before initialization and supplied to both. `start` consumes domain_id, expected_domain_revision, boot_id, execution_id, timestamp; reuses open session else creates UUID. `accept` consumes RequestRecord; `dispatch` consumes session_id/request_id. `terminal` consumes session_id/request_id/packet, assigns next output_id and expires retained completed records with trimmed terminals. `stop` consumes execution_id/outcome/timestamp; `end` consumes session_id/expected_domain_revision/actor/timestamp and refuses unfinished execution. `recover` settles explicitly classified requests. `delete_ended` consumes session_ids and rejects any open session. Lifecycle/recovery changes increment domain revision. Every successful mutation increments durable revision.

- [x] Write `test_sqlite_reopen_exact_replay`, `test_trim_empty_preserves_highwater`, `test_duplicate_window_and_conflict`, `test_limits_before_admission`, `test_packet_escaping_limit`, `test_load_rejects_foreign_or_corrupt_image`, `test_delete_compacts_image`. Assert IDs1,2 survive reload; 258 outputs retain IDs3..258; 4MiB counts output UTF-8 only; bool/negative cursor rejected; packet JSON uses ensure_ascii=False and escaped control characters count toward2MiB; 128 sessions/10domains/64MiB/unfinished allowance caps enforced with no silent deletion.
- [x] Run `python -m pytest bridge/tests/test_sqlite_state.py bridge/tests/test_domain_store.py -q`; require RED from missing new implementation, not changed original contracts.
- [x] Implement schema version1, constraints/indexes, parameterized SQL, extension loading disabled and trusted_schema=OFF. Load only bounded bytes, validate integrity, exact allowed schema objects, foreign keys, UUID/project/manifest identity, row limits and terminal/request consistency before publishing. Reject corrupt/newer formats without migration guesses. Stage each candidate separately; serialize/size-check, replace durably, then return commit. Failed candidates never become the published state. Compact after deletion before image-size validation. Persist no provider tokens/credentials/raw runtime objects.
- [x] Run both suites; require GREEN including nested defensive copies, retained conflicting task/agent rejection and inability to evict unfinished requests. Add exact-boundary tests without allocating unbounded fixtures.
- [x] Commit `feat(PLZG-290): persist bounded session records in SQLite images`.

## Task 3: Async coordinator and explicit backend wiring

**Files:** Create `bridge/state_coordinator.py`, `bridge/tests/test_state_coordinator.py`; modify `bridge/config.py`, `bridge/config.json`, `bridge/server.py`, `bridge/tests/test_config.py`, `bridge/tests/test_runtime_wiring.py`.

**Interfaces:** `StateCoordinator(repository_factory: Callable[[], StateRepository])`; `async open() -> None`; `async commit(command: StateCommand) -> StateCommit`; `snapshot() -> StateView | None`; `replay(session_id: str, cursor: int) -> ReplayWindow`; `find_request(session_id: str, request_id: str) -> RequestRecord | None`; `async close() -> None`. All repository creation/use/close happens on one owned worker thread; synchronous view reads deep-copy committed data. Coordinator tracks admission health independently of readable prior state. Add startup `DOMAIN_STATE_BACKEND='sqlite'`, override `PLAZA_DOMAIN_STATE_BACKEND`, accepted values sqlite/memory only.

- [x] Write `test_commit_publishes_only_after_fsync`, `test_cancelled_caller_does_not_cancel_writer`, `test_uncertain_commit_closes_admission`, `test_heartbeat_and_replay_during_slow_write`, `test_backend_switch_is_not_migration`. Block real worker via deterministic barriers; assert heartbeat/replay progress, close waits, prior view stays unchanged on failure, no automatic retry. Config precedence/types/unknown values must follow current validation.
- [x] Run `python -m pytest bridge/tests/test_state_coordinator.py bridge/tests/test_config.py bridge/tests/test_runtime_wiring.py -q`; require RED for missing behavior.
- [x] Implement worker queue and tracked/drained cancellation-safe ownership following existing owned-I/O patterns. Serialize commands and carry transaction IDs through uncertain acknowledgements; reconcile image revisions under the same lock before admitting any new work. Server opens existing validated state when project ready, initializes only on explicit Start, drains worker before clean recorder closure. Memory backend never reads/writes prior SQLite image and advertises non-durability/discontinuity.
- [x] Run the suites; require GREEN with failed fsync, disk-full/read-only errors, pending-close cancellation and a second bridge unable to write. Assert no database/model call for refresh on an unprepared or new project.
- [x] Commit `feat(PLZG-290): coordinate durable state without blocking the event loop`.

## Task 4: Stable application lifecycle and protocol-v2 fences

**Files:** Modify `bridge/domain_protocol.py`, `bridge/domain_manager.py`, `bridge/domain_session.py`, `bridge/server.py`, `bridge/tests/test_domain_manager.py`, `bridge/tests/test_protocol.py`; create `bridge/tests/test_domain_lifecycle_v2.py`.

**Interfaces:** DomainSession receives application session_id, execution_id and coordinator; manager owns saved-session catalog independently of active SDK objects. All domain commands carry `protocol_version: 2`; advertise it in workspace/status capabilities. Query/background/refocus/deactivate require execution_id; activate requires expected_domain_revision; End requires session_id plus expected_domain_revision. Resume requires only application ID/cursor, never execution authority. Status returns execution_id nullable, domain_revision decimal string, bounded saved_sessions metadata and state-store health. No replacement session is created by End/status.

- [x] Write `test_stop_restart_preserves_app_id`, `test_end_then_start_new_app_id`, `test_stale_execution_rejected`, `test_stale_start_and_end_revision_rejected`, `test_old_client_upgrade_required`, `test_ended_replay_without_sdk`. Assert distinct execution UUID after every explicit activation, domain revision monotonic across reboot, correct bridge-derived actor, failed cleanup/End retains open ID and ownership.
- [x] Run `python -m pytest bridge/tests/test_domain_lifecycle_v2.py bridge/tests/test_domain_manager.py bridge/tests/test_protocol.py -q`; require relevant RED. Update old protocol fixtures deliberately; preserve behavior assertions except approved identity/control changes.
- [x] Implement durable Start before advertising activation; failed SDK activation records its actual stopped/failed outcome. Stop drains SDK/metadata/worker before releasing worktree/capacity and preserves app session. End orderly-stops then commits end marker; uncertainty never acknowledges End. Maintain saved histories up to quota rather than the old two-generation eviction rule. Add clear upgrade_required, stale_execution, stale_domain_revision and storage errors; unknown versions fail before side effects.
- [x] Run suites; require GREEN including concurrent duplicate activation/End, decimal validation (bool/negative/oversized values), old delayed terminal unable to overwrite new lifecycle, game exit not ending the application session.
- [x] Commit `feat(PLZG-290): separate saved sessions from fenced executions`.

## Task 5: Durable Run admission and terminal publication

**Files:** Modify `bridge/domain_session.py`, `bridge/domain_manager.py`; create `bridge/tests/test_domain_persistence.py`; retain existing domain/store/session integration coverage.

**Interfaces:** Task 2 accept/dispatch/terminal commits; extend `_Run` with execution_id, turn_id/memory_revision and durable disposition. The in-flight fence is installed before the first await. Retained duplicate comparison uses original agent/task digest and cannot restart work.

- [ ] Write `test_accept_before_ack_and_dispatch_before_execute`, `test_notes_before_terminal_before_delivery`, `test_accept_failure_never_executes`, `test_terminal_failure_is_uncommitted`, `test_duplicate_during_commit_executes_once`. Use ordered event spies and real repositories; assert domain_accepted occurs after durable acceptance, SDK entry after durable dispatch, saved memory outcome before terminal commit, delivery after published revision, no fake output_id on failed persistence.
- [ ] Run `python -m pytest bridge/tests/test_domain_persistence.py -q`; require RED at ordering expectations.
- [ ] Implement design §6 order exactly. Carry exact Markdown turn identity/revision; settle not-executed intents safely on rejected acceptance. Terminal commit atomically assigns highwater, disposition and trimming; clear pending after commit publication. If persistence fails after tools, send bounded explicitly uncommitted text/error with no durable output_id, close admission and preserve uncertainty. Do not present it as saved history. Preserve memory-save-failed facts frozen in committed packets.
- [ ] Run new suite plus `bridge/tests/test_domain_store_session.py`, `bridge/tests/test_domain_session.py`, `bridge/tests/test_m12_integration.py`; require GREEN. Add failures before/after each await and oversized terminal metadata; no weakened readiness or duplicate checks.
- [ ] Commit `feat(PLZG-290): durably fence accepted work and saved results`.

## Task 6: Crash recovery and shutdown ownership

**Files:** Create `bridge/session_recovery.py`, `bridge/tests/test_session_recovery.py`, `bridge/tests/test_state_crash.py`; modify `bridge/domain_session.py`, `bridge/server.py` and narrowly scoped `bridge/readiness.py` / `bridge/project_memory.py` reconciliation hooks if needed.

**Interfaces:** `classify_recovery(view: StateView, boot_id: str) -> tuple[StateCommand, ...]` is pure; coordinator durably applies recovery before publishing recovered state. `async reconcile_memory(service, request: RequestRecord, terminal: TerminalRecord) -> dict` uses validated ownership/readiness and exact existing turn identity; unavailable/mismatched/already-completed notes are surfaced, never overwritten blindly.

- [ ] Write subprocess tests killing at: initializing manifest; image-before-ready; notes-pending-before-accept; accepted-before-dispatch; dispatch-before-SDK; notes-complete-before-terminal; terminal-commit-before-delivery. Assert no automatic SDK/tool call; accepted-only produces one not-executed terminal, dispatched produces one interrupted/unknown terminal, committed delivery replays identically; repeat restart adds no second recovery result.
- [ ] Run `python -m pytest bridge/tests/test_state_crash.py bridge/tests/test_session_recovery.py -q`; require RED for recovery absent. Use real child-process exit/kill and on-disk image validation, not only exceptions in mocks.
- [ ] Implement classification and idempotent durable recovery. Existing unclean markers remain untouched and block tools while committed history remains readable. Preserve already-completed Markdown outcome even when SQLite interruption is conservative; record discrepancy visibly. Never infer process liveness from old execution records.
- [ ] Add barrier-driven shutdown tests during SDK work, metadata I/O, image replacement and uncertain fsync; assert Stop/close cannot abandon worker or release lock/lease prematurely, End stays unsuccessful when undurable, clean exit waits for all owned work. Run suites plus existing shutdown/cleanup coverage; require GREEN.
- [ ] Commit `feat(PLZG-290): recover interrupted runs without retrying tools`.

## Task 7: Bounded recap at fresh execution entry

**Files:** Create `bridge/session_recap.py`, `bridge/tests/test_session_recap.py`; modify `bridge/context.py`, `bridge/domain_session.py`, `bridge/tests/test_context.py`.

**Interfaces:** `Recap(text: str, source_high_water: int, source_output_ids: tuple[int, ...])`; `build_recap(view: StateView, session_id: str, *, exclude_request_id: str) -> Recap`. Context packet gains a separately labeled quoted continuity section, never a system-authority replacement. Track supplied source metadata on the execution's first SDK query only.

- [ ] Write `test_latest_four_chronological`, `test_unicode_and_escaping_caps`, `test_first_run_only_per_execution`, `test_new_session_no_old_recap`, `test_pending_excluded_and_instructions_quoted`. Assert each task≤1024 UTF-8 bytes, each answer≤2048, whole recap≤16384 including representative/outcome/ID labels and one bounded interruption notice. Empty/trimmed history is honest, omitted content labeled, no extra provider call.
- [ ] Run `python -m pytest bridge/tests/test_session_recap.py bridge/tests/test_context.py -q`; require RED for missing recap integration.
- [ ] Implement deterministic Unicode-safe extract from committed records only; include latest four completed pairs, interruption notice if present, current pending excluded. First attempted SDK invocation gets recap; subsequent queries in that same runtime do not resend. Untrusted/unreadable state fails Run visibly. Fresh project/game guidance and actual current facts remain distinct and authoritative; restored data is not a task queue.
- [ ] Run suites and `bridge/tests/test_domain_persistence.py`; require GREEN including representative changes, malicious quoted old instructions, no cross-project/post-End recap, restart of same application gets recap again.
- [ ] Commit `feat(PLZG-290): restore bounded conversation context for fresh executions`.

## Task 8: Godot restored history and separate End controls

**Files:** Modify `scenes/bridge/domain_store.gd`, `scenes/bridge/domain_surface.gd`, `scenes/bridge/ws_client.gd`, `scenes/hud/domain_panel.gd`, `scenes/hud/domain_panel.tscn`, `scenes/hud/dialogue_panel.gd`, `scenes/hud/dialogue_panel.tscn`; modify `tests/domain_store_test.gd`, `tests/domain_transport_test.gd`, `tests/domain_panel_test.gd`, `tests/character_domain_test.gd`, fixtures and Python Godot integration tests.

**Interfaces:** Both surfaces consume v2 status/execution/revision/saved_sessions; all controls include current fences. Resume cursor is per application session, separate from execution epoch. End button calls end_domain_session, Stop calls deactivate_domain. Restore open session else latest ended; users can select bounded older saved sessions read-only; Start remains explicit.

- [ ] Add failing checks for a fresh game restoring open history, ended-only history, a disconnected client returning after another execution, stale revision refresh, failed End preserving draft/history and uncommitted answer labeled unsaved. Assert no activation/model call on approach/status/reconnect, exact terminal IDs, no duplicate rendered results.
- [ ] Run `npm run test:m12` with CI-pinned Godot; require relevant RED, not engine-version failures.
- [ ] Implement shared client state/transport first, then both UI surfaces. Display stopped/restored, ended, interrupted/unknown, persistence failure and memory-backend discontinuity explicitly. Reject old execution lifecycle updates while accepting their historical terminals. Preserve Copy/Select All/context menu, scroll and focus behavior, representative attribution, explicit Start/Run.
- [ ] Run `npm run test:m11`, `npm run test:m12`, `npm run test:m12-integration`; require GREEN with pinned engine. Add real bridge+Godot fresh-process reopen test and ended-session replay test, alongside existing reconnect tests.
- [ ] Commit `feat(PLZG-290): restore saved domain sessions in both work surfaces`.

## Task 9: Offline maintenance and aligned operator documentation

**Files:** Create `scripts/domain_state.py`, `tests/test_domain_state_cli.py`; modify `QUICKSTART.md`, `CLAUDE.md`, `CHANGELOG.md`, `docs/designs/platform-decisions.md`, `specs/roadmap.md`, historical M12 design only with explicit successor notice, and add `docs/m13-session-persistence.md`; update registry and governed version/enforcement metadata exactly as META-SPEC requires.

**Interfaces:** `python scripts/domain_state.py --workspace PATH export --session UUID --output PATH`; `... delete-ended --session UUID --backup PATH`. CLI acquires same project writer lock. Export writes bounded versioned UTF-8 JSON with session records/retained terminals and hash metadata through safe exclusive output creation; cannot overwrite existing paths. Delete requires successful durable backup before commit, supports ended sessions only, preserves instance/project identity and highwaters of retained sessions.

- [ ] Write `test_cli_refuses_live_writer`, `test_delete_requires_ended_and_backup`, `test_export_rejects_unsafe_or_existing_path`, `test_delete_reopen_preserves_other_sessions`. Assert backup failure leaves image unchanged; no model/SDK calls; compaction produces a valid bounded image.
- [ ] Run `python -m pytest tests/test_domain_state_cli.py -q`; require RED, then implement CLI using existing repository/lock primitives, not a separate direct database editor. Require GREEN.
- [ ] Document startup config/env precedence, memory/SQLite switching, cleartext content and diagnostic-log distinction, quotas/transient disk usage, supported runtime/OS errors, busy/corrupt/missing/uncertain recovery, backup/export/delete and Stop versus End. Do not offer a destructive generic reset as repair.
- [ ] Align entitled platform/M12/roadmap/protocol/config sources with the approved lifecycle before final delivery; preserve historical contracts/evidence and locked unrelated decisions. Record any genuinely new unresolved governance conflict in `M13_DECISIONS_AND_QUESTIONS.md` rather than inventing owner answers. Run `python scripts/validate_specs.py` and authored `git diff --check`; require GREEN.
- [ ] Commit `docs(PLZG-290): document durable sessions and safe offline maintenance`.

## Task 10: Evidence campaign, performance and delivery handoff

**Files:** Create `scripts/m13_state_probe.py`, `tests/test_m13_state_probe.py`, `docs/m13-live-acceptance.md`; update `bridge/tool_guard_evidence.py` source inventory and its real acceptance campaign, this plan and working queue. Do not overwrite historical M12 evidence.

- [ ] Add probe tests verifying report binding to exact source hashes, dependency/SDK/CLI/OS/engine versions, backend/mode and test completeness; missing cases or stale sources must reject acceptance. The live guide must specify shell commands, expected states and private report locations for Stop/restart/End/recap/crash/failed-storage recovery, with no private transcripts committed.
- [ ] Implement local persistence performance probe with representative and 64MiB boundary images, repeated commits, peak RSS/image size/commit latency/event-loop heartbeat. Report old+new transient disk and process overhead separately. Use a deliberately blocked writer test requiring heartbeat/replay progress before unblock; actual latency results are reviewed, not invented performance guarantees.
- [ ] Run full `PLAZA_REQUIRE_GODOT=1 python -m pytest bridge/tests tests -q`, `npm test` with committed CI-pinned Godot, `black --check .`, `flake8 . --select=E9,F63,F7,F82`, `python scripts/validate_specs.py`, `git diff --check`. Record exact counts/versions and any failures; no skipped required Godot gate counted as pass.
- [ ] Enumerate all changed/new execution-authorizing sources, include them in guarded inventory and update real campaigns to exercise the new admission path. Collect fresh guards for dontAsk and bypassPermissions and run their actual acceptance validator at final source/runtime. Changed sources require new reports, never hash substitution. Keep OAuth/API authentication coverage explicit; fake integrations are not live provider acceptance.
- [ ] Obtain fresh whole-branch review against approved design, including filesystem/crash/ownership and client control fencing. Resolve findings with regressions; rerun affected evidence after source changes. Record laptop acceptance separately from container tests and paid SDK guard probes; acceptance not yet obtained remains pending.
- [ ] Commit final evidence summary and working handoff. Open a reviewed PR to dev under the repo's lifecycle gate; attach it to the task, reread all review surfaces and resolve findings before D-031 merge. Update #380/PLZG-290 with actual completion boundaries; do not mark all M13–M15 complete for this increment. Preserve branch/worktree evidence and never publish private run logs by default.

## Execution order and handoff

Tasks execute 1→10. Each task gets RED→GREEN, a scoped commit and the selected review gate. Task 9's governed-source alignment must be complete before implementation is presented for delivery; preliminary documentation amendments can accompany Tasks 3–4 where their behavior changes. Do not deploy speculative cloud resources.

**Recommended method:** subagent-driven, with a fresh implementer and fresh reviewer per task, followed by a whole-branch review. The durable write ownership, crash recovery and execution fencing are consequential enough to justify independent reviews at their boundaries. Existing phase-1 native execution was a separate decision; Adam selected this method after reviewing the plan.

**Execution starting point:** this branch, `docs/PLZG-290-sqlite-persistence-design`, based on dev `1bb3a19`. Fetch dev and inspect the clean worktree before execution; integrate intervening changes without rebasing published history or changing the unrelated `work` checkout. Record actual base/head and dependencies; earlier phase-1 test results do not certify new dependencies or persistence behavior.

**Tracking:** GitHub #380 and Jira PLZG-290 (In Progress). #373 is already delivered/closed. Shared PR-ledger tooling is independent and does not block local persistence.

**Assertion anchors:** tests use the production interfaces above; test fixtures may supply clocks, UUID factories, I/O barriers and real temporary Git repositories. At minimum pin these literal assertions in their owning test steps:

```python
# Task 1: interrupted initialization is not a new empty store.
with pytest.raises(StateError) as error:
    StateImage.open(common_git_dir, project_id, initialize=True, initial_image=lambda instance_id: seed)
assert error.value.code == "state_store_invalid"
# Task 2: reopen preserves allocation even when retention has trimmed everything.
assert coordinator.replay(session_id, 0).high_water_mark == 1
assert coordinator.replay(session_id, 0).entries == []
assert coordinator.replay(session_id, 0).history_gap is True
# Task 4: Stop/Start identity and execution fences.
assert second["domain_session_id"] == first["domain_session_id"]
assert second["execution_id"] != first["execution_id"]
assert int(second["domain_revision"]) > int(first["domain_revision"])
# Task 5: durable publication order, captured at the actual boundaries.
assert events == ["notes_pending", "accept_commit", "accepted", "dispatch_commit",
                  "sdk_execute", "notes_saved", "terminal_commit", "published", "delivered"]
# Task 7: the entire rendered string includes labels and notices in its byte cap.
assert len(recap.text.encode("utf-8")) <= 16 * 1024
assert len(recap.source_output_ids) <= 4
```

**Plan self-review:** all ten spec sections mapped: files/ownership/initialization→1; schema/limits/retention→2; worker/config/publication→3; lifecycle/fencing→4; cross-store Run order→5; crash/shutdown→6; recap→7; real client→8; maintenance/governance→9; independent acceptance/performance/guards→10. All five Review Focus conditions have named owning tests. No runtime code or new dependency is introduced by writing this plan.

## Execution receipts

- Task1 complete: `23c4dc3`, fix `0f4209e`; independent review approved after RecursionError fix. 60 image tests pass locally and on actual Python3.11. Existing broad contention-test sleep-patch flake remains explicitly tracked for final verification; broad gate was389pass/1fail, not green.

- Task2 complete: `b6f4cf6`, review fix `77a1b96`; independent review approved. 121 focused schema/image/replay tests pass on Python3.12 and Python3.11. Real compaction, preserved highwater, exact bounds, malformed-image handling and committed-success recovery are covered. New packet-bound check runs before decoding. Runtime wiring remains Task3 onward.

- Task3 complete: `f080420`, review fix `0742fff`; independent Astra review approved. 799 covering tests pass on Python3.12/3.11. Coalesced reconciliation and anchored durability confirmation cover both review findings; worker/server ownership and backend discontinuity covered. New guarded inventory requires genuinely fresh Task10 evidence; old reports untouched.

- Task4 complete: `98df428`, review fix `9c9efdb`; independent Astra review approved. 516 pre-fix covering tests and 258 affected post-fix tests pass on Python3.12/3.11. Cancelled shutdown now drains owned lifecycle operations and every owner before propagating cancellation. Production durable Run pipeline/combined replay remains Task5; no shipped persistence claim.
