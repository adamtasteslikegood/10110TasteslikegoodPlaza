# M12 — Project bootstrap, memory and domain execution implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run real agent work in one configured project's dedicated worktree,
with native project memory, Chief Architect setup and usable background work.

**Architecture:** A project service owns inspection/bootstrap and routes setup
interactions; separate workspace, lease and memory components enforce their own
boundaries. A single SDK owner task runs each domain, behind mandatory readiness
checks, while per-connection transport keeps NPC calls responsive. Godot consumes
workspace/domain snapshots through its existing BridgeClient and a separate HUD.

**Tech Stack:** Python 3.11+, Git, POSIX `fcntl`, existing standard-library storage
patterns; `claude-agent-sdk==0.2.136`, `anthropic==0.121.0`, `websockets==17.0.1`,
`pytest==9.1.1`, `pytest-asyncio==1.4.0`; Godot 4.7.1 and GDScript. Add no service,
database, dependency, autoload or container provider. Record the actual CLI version
in live evidence; SDK version alone does not identify its tool-hook behavior.

**Spec:** [M12-DOMAIN-EXECUTION-DESIGN](../specs/2026-10-21-m12-domain-execution-design.md),
written version at `57b631f` approved by the owner on 2026-10-21.
`D-038`/`D-039` ratify the approved policy in doc set 0.2.17.

**Status:** Owner approved this plan and subagent-driven execution on 2026-10-21.
Implementation is in progress; runtime checkboxes change only with observed
evidence. Plan approval does not establish M12 acceptance. Baseline
is `origin/dev` at `142b17a`, plus approved design commits; fetch/status again at
execution start and reconcile any intervening product changes before editing.

## Global Constraints

- Preserve `D-005`/`D-020` client independence, `D-033` synchronous NPC timing,
  `D-034` asynchronous domains and `D-037` SDK default/explicit API compatibility.
- `WORKSPACE_ROOT_DIR` defaults to JSON `null`; `PLAZA_WORKSPACE_ROOT_DIR` is a raw
  nonempty path override. Precedence remains built-ins → selected JSON → env.
  Relative paths use the selected config directory, never launch CWD.
- One configured project per bridge/game session. No client-supplied filesystem
  paths or project switching; reconnect to a restarted bridge to change projects.
- Create/reuse `<project-parent>/.plaza-worktrees/<project-name>-<project-key>/execution`
  and branch `plaza/workspace-<project-key>`; persist full identity and location.
  Source/runtime and execution trees are disjoint after canonicalization.
- Empty/non-Git/unborn projects need the existing `systems-architect` agent's
  exact-proposal approval for `main` and a reviewed seed commit. Other NPCs refer
  the player; only a submitted Chief Architect interaction starts review.
  Its approval suffices; no extra human dialog, remote, push or blanket staging.
- Start reserves the worktree until confirmed Stop cleanup, including idle,
  completion, background and socket loss. One SDK domain session per initial
  worktree; no hidden query queue. Preserve edits on all outcomes.
- The SDK owner performs connect/query/receive/disconnect in one task/context.
  A catch-all `PreToolUse` hook checks actual Git/worktree/lease/memory state.
  Do not enable a tool path until pinned-CLI denial/failure behavior is verified.
- Three canonical memory files under `<git-common-dir>/plaza/session-memory/`:
  TODO ≤16 KiB/64 items; HANDOFF ≤16 KiB; PROGRESS ≤32 KiB/12 recent entries plus
  a bounded recap. Count full UTF-8 file bytes, including metadata and newlines.
- Memory is project data and prior context, not instruction authority, an
  automatic task queue, complete history or SDK recovery. No hidden model calls
  for summaries; optional deltas come from the same response, otherwise excerpts.
- Identifiers ≤128 UTF-8 bytes; task/draft ≤64 KiB. Domain IDs use ASCII
  letters/digits/hyphen/underscore. Run/background/refocus/Stop/replay require expected generation; Start obtains it.
- Server retains ≤256 terminals/4 MiB output per generation, ≤256 KiB per output,
  ≤10 domain IDs and ≤2 generations per domain. Truncation/history gaps are explicit.
  Client retains ≤200 entries/1 MiB per domain including generations and drafts.
- Existing query caps remain 20 domain turns/USD 1 by default; use configured
  values. Keep NPC deadline/output/history limits, independent of memory bounds.
- Unsupported locking platforms fail domain setup; never use a PID/timeout as a
  substitute for exclusion or evidence that abandoned execution is safe to reuse.
- Worktrees/hooks are not a host/network sandbox. No automatic reset, cleanup,
  merge, daemon termination claim or substitution of output delay for real work.
- `data/agents.json` is generated. Preserve the four autoloads, Main/HUD paths,
  existing NPC signal arities, M11 behavior and frozen historical evidence.

## Review Focus

1. A valid newer memory revision from an unrelated NPC must not block a running
   domain; re-read it rather than compare against Start's revision (Tasks 3/4/9).
2. An unborn repo's old index and a file changed between review/staging must not
   broaden the seed commit; preserve the index and verify the final tree (Task 2).
3. Stop during slow connect, repeated cancellation and lost acceptance delivery
   must neither orphan an SDK worker nor duplicate execution (Tasks 4/5/6).
4. Both existing world NPCs are `core`: test a distinct engineering domain as well
   as unrelated core NPC chat, and move the actual player for proximity (Tasks 7–9).
5. Reconnect/project change and interleaved replay must not revive old drafts,
   steal focus, hide fresh output or auto-resubmit uncertain work (Tasks 5/7/9).

## File map and task dependencies

| Task | Main production files | Responsibility |
|---|---|---|
| 1 | `bridge/config.py`, `bridge/config.json`, new `project_files.py`, `workspace.py`, `workspace_lease.py` | Project selection, existing-repo bootstrap and reservation |
| 2 | new `bridge/repository_setup.py` | Bounded initialization proposal and exact approved seed commit |
| 3 | new `bridge/project_memory.py` | Three-file grammar, merge/checkpoint, run ownership and continuity |
| 4 | new `bridge/readiness.py`, `domain_sdk.py` | Mandatory tool readiness and one-task SDK lifecycle |
| 5 | `bridge/domain_session.py`, `domain_manager.py`, new `domain_protocol.py` | Admission, generation, lifecycle, terminal/replay contract |
| 6 | new `bridge/project_service.py`, `connection.py`; `server.py`, `conversation.py`, `conversation_backend.py`, `conversation_sdk.py`, `conversation_api.py`, `bridge.py` | Setup routing, contextual NPC turns and responsive socket delivery |
| 7 | new `scenes/bridge/domain_store.gd`; `ws_client.gd`, `autoload/GameEvents.gd` | Client state and domain/workspace transport |
| 8 | new `scenes/hud/domain_panel.gd/.tscn`; `scenes/main.tscn` | Explicit controls, proximity, status and rendered results |
| 9 | new bridge/Godot integration fixtures; `scripts/run_headless.py`, `package.json`, `.github/workflows/ci.yml` | Complete deterministic flow and regression gates |
| 10 | new live runner/probe and evidence tests; `QUICKSTART.md`, `bridge/PROTOCOL.md`, status docs | Real SDK/tool evidence, operation and completion review |

Dependency graph: 1 → {2,3}; {1,3} → 4 → 5;
{1,2,3,4,5} → 6 → 7 → 8 → 9 → 10.
Use that order for the first execution. Tasks 2/3 can use independent workers only
once Task 1's interfaces are reviewed; avoid simultaneous edits to shared files.
These are connected parts of one M12 contract, not independently shippable services.
Each task gets its own focused tests and commit before the dependent task starts.

### Task 1: Configure, prepare and reserve an existing project's worktree

**Files:** Modify `bridge/config.py`, `bridge/config.json`, `bridge/tests/test_config.py`.
Create `bridge/project_files.py`, `bridge/workspace.py`, `bridge/workspace_lease.py`,
`bridge/tests/test_workspace.py`, `bridge/tests/test_workspace_lease.py`.
Read `bridge/log_storage.py` and its tests for patterns; do not refactor diagnostics.

**Interfaces:**
- `BridgeConfig.workspace_root_dir: Path | None`; `effective_settings()` emits a
  path string or JSON null. Existing imports/default constructors remain usable.
- `project_files.FileLock.acquire(path: Path) -> FileLock`, `.close() -> None`;
  `read_regular(path: Path, *, max_bytes: int) -> bytes`,
  `atomic_replace(path: Path, data: bytes) -> None`, `durable_unlink(path: Path) -> None`.
- Frozen `ProjectInspection(root: Path, root_identity: tuple[int,int],
  common_git_dir: Path|None, project_id: str|None, head_commit: str|None,
  source_branch: str|None)` and `ExecutionWorkspace(project_id: str,
  workspace_id: str, project_root: Path, common_git_dir: Path, worktree_path: Path,
  git_dir: Path, branch: str, initial_commit: str,
  source_identity: tuple[int,int])` live in `workspace.py`. The source identity
  freezes this bridge binding; it is not one project-global source checkout lock.
- `inspect_project(root: Path) -> ProjectInspection`;
  `prepare_worktree(project: ProjectInspection, *, runtime_root: Path) -> ExecutionWorkspace`;
  `validate_workspace(workspace: ExecutionWorkspace, *, runtime_root: Path) -> None`.
- `WorkspaceError(code: str, message: str)` exposes safe error codes.
- `WorkspaceLease.acquire(workspace: ExecutionWorkspace, *, domain_id: str,
  domain_session_id: str) -> WorkspaceLease`; `.validate() -> None`;
  `.release(*, cleanup_confirmed: bool) -> None`. It exposes `.workspace`,
  `.domain_id`, `.domain_session_id` and `.held: bool` for subsequent tasks.

- [x] **Step 1 — Add failing configuration, real-Git and subprocess-lock tests.**
  Name cases `test_workspace_env_is_raw_and_config_relative`,
  `test_bootstrap_reuses_dirty_worktree`, `test_distinct_clones_do_not_share_project`,
  `test_invalid_workspace_never_falls_back`, `test_session_lease_blocks_other_process`,
  `test_marker_fsync_failure_prevents_acquisition`, and `test_killed_owner_blocks_reuse`.
  Pin the important assertions, with temporary fixture repos and source sentinels:

  ```python
  assert load_config(config_path, environ={"PLAZA_WORKSPACE_ROOT_DIR": "../repo"}).workspace_root_dir == repo.resolve()
  assert default_config().workspace_root_dir is None
  assert again.worktree_path == first.worktree_path
  assert (again.worktree_path / "retained.txt").read_text() == "unsaved work"
  assert source_head_after == source_head_before and source_status_after == source_status_before
  assert other_process_error == "workspace_busy"
  assert lock_inode_after == lock_inode_before
  assert crash_restart_error == "cleanup_failed"
  ```

  Parametrize empty/invalid/file paths, booleans, null env text as a literal path,
  symlinks, nested/overlapping trees, detached/source branch conflicts, foreign
  registration, stale/occupied location, concurrent bootstrap and interrupted setup.
- [x] **Step 2 — Run the tests red.**
  `python -m pytest bridge/tests/test_config.py bridge/tests/test_workspace.py bridge/tests/test_workspace_lease.py -q`.
  New imports/contracts should fail; preserve the existing config tests.
- [x] **Step 3 — Implement the interfaces and local ownership format.**
  Special-case nullable workspace JSON and raw env parsing; do not put it blindly
  in `_TEXT_KEYS`. Derive project key from SHA-256 of canonical common-directory
  bytes (first 16 hex chars), then compare full identity on every reuse. Sanitize
  basename for display/path only. Persist a UUID workspace ID, schema version,
  common directory, recorded execution path/branch and initial commit in
  `<common>/plaza/workspace.json`; record incomplete bootstrap before invoking Git.
  Use Git argument arrays, finite timeouts and sanitized Git override variables.
  Inspection timeout is 5s; bootstrap command timeout is 30s; run blocking work off
  the event loop. Use directory-FD/O_NOFOLLOW anchors and reject nonregular or
  multiply linked managed files. `atomic_replace` fsyncs file then directory.
  Fixed bootstrap/memory/execution lock inodes are never unlinked. Acquisition
  writes the durable unclean marker before returning permission to start SDK;
  failed/uncertain cleanup retains ownership/marker. No reset, fetch or cleanup.
- [x] **Step 4 — Run the targeted suites green.**
  Run Step 2 plus `python -m pytest bridge/tests/test_log_storage.py -q`; expect all
  pass and unchanged diagnostic behavior. Verify both cooperating processes cannot
  bootstrap two worktrees and the losing process did not mutate the source.
- [x] **Step 5 — Commit only Task 1 files.**
  `git commit -m "feat(bridge): prepare and reserve project worktrees (PLZG-289)"`.

### Task 2: Apply only the Chief Architect's exact initialization proposal

**Files:** Create `bridge/repository_setup.py`, `bridge/tests/test_repository_setup.py`.
**Consumes:** Task 1 file/Git helpers and `ProjectInspection`.
**Produces:** frozen `SeedFile(relative_path: str, mode: int, size: int, sha256: str)`,
`RepoInitProposal(proposal_id: str, digest: str, root: Path,
root_identity: tuple[int,int], unborn: bool, initial_branch: str,
seed_files: tuple[SeedFile,...])`, and
`RepoInitApproval(proposal_id: str, digest: str, approved: bool, reason: str)`.
Functions: `build_init_proposal(root: Path) -> RepoInitProposal`,
`parse_init_approval(proposal: RepoInitProposal, payload: object) -> RepoInitApproval`,
`initialize_repository(proposal: RepoInitProposal, approval: RepoInitApproval) -> ProjectInspection`.
The model call belongs to Task 6; this module never calls a provider.

- [x] **Step 1 — Write failing exact-tree initialization tests.**
  Cover `test_empty_approved_repo_starts_on_main`,
  `test_populated_repo_commits_only_reviewed_seed`,
  `test_unborn_prior_index_survives_without_entering_commit`,
  `test_final_tree_change_invalidates_approval`, and
  `test_denial_stale_digest_competing_init_and_partial_failure`.

  ```python
  assert branch == "main" and initial_commit_exists
  assert committed_paths == approved_paths
  assert original_unborn_index_bytes == index_after
  assert "unapproved-staged.txt" not in committed_paths
  assert (root / ".env").read_bytes() == original_secret_fixture
  assert not hook_sentinel.exists() and not filter_sentinel.exists()
  assert remote_names == [] and source_file_bytes_after == source_file_bytes_before
  ```

  Include unchanged-directory identity but changed file bytes, renamed/replaced
  root, symlink seeds, conflicting `main`, ignored/generated files and two processes.
- [x] **Step 2 — Run red:**
  `python -m pytest bridge/tests/test_repository_setup.py -q`.
- [x] **Step 3 — Implement proposal validation and controlled Git initialization.**
  `initial_branch` is always `main`. Bound review inventory to 256 regular files,
  8 MiB total seed bytes and 64 KiB serialized proposal; refuse broader inventory
  with an actionable narrowing reason. Use Git ignore matching through disposable
  metadata outside the selected directory; do not create its `.git` before approval.
  Exclude `.env` variants, credential/private-key files, ignored/generated files,
  symlinks and nested repositories; keep excluded contents out of model prompts.
  Hash the canonical sorted proposal including directory device/inode and seed
  paths/modes/sizes/hashes. Require boolean approval plus exact proposal ID/digest.
  Revalidate under the canonical-directory bootstrap lock. Use an empty temporary
  index, raw `hash-object --no-filters --stdin`, explicit index entries, `write-tree`,
  `commit-tree` and compare-and-swap creation of `refs/heads/main`. Compare final
  tree blobs/types/paths to the manifest before committing. Disable hooks/templates,
  filters and signing; identify author as `Plaza Bridge <plaza-bridge@localhost>`
  per command. Preserve an unborn repo's index/config; for a newly initialized
  repo with no old index install the reviewed index. Retain partial setup for
  inspection rather than deleting it or replaying stale approval.
- [x] **Step 4 — Run red command green**, plus Task 1 suites. Expect exact allowlist
  commits and retained source/index sentinels for every failure path.
- [x] **Step 5 — Commit:**
  `git commit -m "feat(bridge): validate architect-approved repository setup (PLZG-289)"`.

### Task 3: Maintain bounded repository-scoped Markdown memory

**Files:** Create `bridge/project_memory.py`, `bridge/tests/test_project_memory.py`.
**Consumes:** Task 1 descriptor, secure file operations and locks.
**Produces:** `TurnIntent(turn_id: str, request_id: str, owner_run_id: str,
agent_id: str, domain_id: str|None, domain_session_id: str|None, task: str)`;
`MemorySnapshot(project_id: str, revision: int, todo: str, handoff: str, progress: str)`
with `.as_context() -> str`; `MemorySaveResult(saved: bool, revision: int|None,
error_type: str|None)`; `MemoryError(code: str, message: str)`.
`ProjectMemoryStore(workspace: ExecutionWorkspace)` methods:
`initialize() -> MemorySnapshot`, `load() -> MemorySnapshot`,
`attach_run(owner_run_id: str) -> FileLock`,
`detach_run(owner_run_id: str) -> None`,
`begin_turn(turn: TurnIntent) -> MemorySnapshot`,
`finish_turn(turn_id: str, *, outcome: str, output: str,
delta: dict|None) -> MemorySaveResult`,
`checkpoint_lifecycle(*, domain_id: str, domain_session_id: str, event: str) -> MemorySaveResult`.
`turn_id` is a bridge UUID, distinct from caller request IDs.

- [x] **Step 1 — Write failing file/restart/concurrency tests.**
  Include `test_initialize_reads_existing_and_repairs_only_missing`,
  `test_utf8_full_file_and_entry_bounds`, `test_other_clone_has_no_prior_context`,
  `test_two_process_checkpoint_merge`, `test_partial_revision_is_not_reinitialized`,
  `test_invalid_delta_uses_excerpts_without_model_call`, and
  `test_other_live_run_is_not_marked_interrupted`.

  ```python
  assert set(p.name for p in memory_dir.glob("*.md")) == {"TODO.md", "HANDOFF.md", "PROGRESS.md"}
  assert todo_bytes <= 16 * 1024 and todo_items <= 64
  assert handoff_bytes <= 16 * 1024 and progress_bytes <= 32 * 1024
  assert recent_entries <= 12 and all_three_revisions_match
  assert new_revision > old_revision and both_concurrent_turns_are_present
  assert old_existing_file_bytes == bytes_after_missing_neighbor_repair
  assert provider_call_count == 0
  ```

  Test per-file cap and one-byte-over boundaries, multi-byte Unicode, EACCES/ENOSPC,
  fsync/replace failures, foreign IDs, invalid UTF-8, symlink/hardlink targets,
  torn three-file checkpoint and duplicate terminal updates.
- [x] **Step 2 — Run red:**
  `python -m pytest bridge/tests/test_project_memory.py -q`.
- [x] **Step 3 — Implement a fixed Markdown grammar and serialized merge.**
  First line is `<!-- plaza-memory:v1 {"project_id":"...","revision":1,"kind":"todo"} -->`;
  parse its JSON with stdlib. TODO uses checkboxes plus per-item JSON comments
  containing stable item/turn/request/run identity and pending/success/error/
  cancelled/interrupted state. HANDOFF has Goal, Active work, Decisions, Evidence,
  Blockers and Next action headings. PROGRESS has UTC/entry-ID headings, outcome
  metadata comments, a brief summary and an Older recap section. Define/render/
  parse this grammar here; never maintain a fourth canonical state file.
  Missing-file repair retains existing bytes/revision and marks its own gap;
  inconsistent existing revisions fail instead of being normalized silently.
  Acquire the short memory lock, reload latest state, merge and replace all three
  files with one next revision; mismatches after interruption are visible failures.
  An optional delta has `summary` (≤2048 UTF-8 bytes), `next_action` (≤1024),
  `todo_updates` (≤16 id/text/done proposals, text ≤512), `decisions` and `evidence`
  (≤8 strings each, ≤512 bytes each). Reject invalid deltas as a whole; use labeled
  bounded excerpts and observed outcomes. Model proposals cannot complete another
  active turn or fabricate verified evidence. Trim old completed items/entries
  into a bounded recap; retain explicit omitted counts and active ownership.
  If active entries alone exceed the cap, reject new admission, not active state.
  Run ownership uses a unique per-run operational lock under `<common>/plaza/runs/`;
  only lock-free/missing owners can become interrupted/unknown. Clean exit calls `detach_run` to remove its separate unique run marker only
  after its execution turns settle, then closes the stable run lock; never reuse
  run IDs or unlink lock files. A memory operation has a cooperative 1s budget
  checked before/after bounded stages and nonblocking lock admission; no provider
  call holds its lock. Callers offload IO and retain ownership until its worker
  settles, including cancellation. A kernel IO call may exceed that budget; report
  elapsed-budget failure and never admit a model call from a late pending save.
  Register failures as unavailable/unsaved, not empty history.
- [x] **Step 4 — Run Task 3 and storage suites green.**
  Assert saved files survive new store instances and no process imports another
  repository's notes. Confirm a normal later revision remains loadable.
- [x] **Step 5 — Commit:**
  `git commit -m "feat(bridge): persist bounded project memory (PLZG-289)"`.

### Task 4: Guard tools and retain the SDK in one owning task

**Files:** Create `bridge/readiness.py`, `bridge/domain_sdk.py`,
`bridge/tests/test_readiness.py`, `bridge/tests/test_domain_sdk.py`,
`bridge/guarded_transport.py`, `bridge/tests/test_guarded_transport.py`,
`scripts/m12_tool_guard_probe.py`, `tests/test_m12_tool_guard_probe.py`,
`bridge/tool_guard_acceptance.json`, `bridge/tool_guard_evidence.py`.
Add `decode_project_reply(output: str) -> tuple[str, dict|None]` to
`bridge/conversation_backend.py` here because DomainSDKOwner consumes it; Task 6
will reuse the same decoder for both NPC adapters. The Task 6 envelope contract
applies verbatim (answer string plus optional memory_delta, plain-text fallback).
Modify `bridge/tests/test_conversation_backends.py` only to share/preserve its
harmless-child cancellation pattern, not to change NPC behavior.
**Consumes:** Tasks 1/3; existing `BridgeConfig` and SDK result types.
**Produces:** `ReadinessService(workspace: ExecutionWorkspace,
lease_runtime_root: Path, memory: ProjectMemoryStore)` with
`async prepare_turn(turn: TurnIntent) -> MemorySnapshot`,
`async check_tool(lease: WorkspaceLease, *, cwd: str, tool_name: str,
tool_use_id: str) -> MemorySnapshot`, and
`pre_tool_hook(lease: WorkspaceLease) -> HookCallback` (SDK type).
`SDKOutcome(output: str, status: str, reason: str, provider_session_id: str|None,
memory_delta: dict|None)`; `CleanupOutcome(clean: bool, error_type: str|None)`.
`DomainSDKOwner(config: BridgeConfig, workspace: ExecutionWorkspace,
lease: WorkspaceLease, readiness: ReadinessService, *, client_factory=ClaudeSDKClient)`:
`async start() -> None`, `async execute(*, agent_id: str, definition: str,
task: str, prior_project_notes: str) -> SDKOutcome`, `async stop() -> CleanupOutcome`.

- [x] **Step 1 — Write failing task-identity, gate and cleanup tests.**
  `test_sdk_calls_have_one_owner_task`, `test_stop_preempts_connect`,
  `test_repeated_cancellation_drains_cleanup`, `test_tool_gate_denies_invalid_state`,
  `test_newer_npc_memory_revision_is_ready`, `test_sdk_terminal_errors_keep_partial_text`.

  ```python
  assert connect_task is query_task is receive_task is disconnect_task
  assert sdk_cwd == str(workspace.worktree_path)
  assert rejected_hook["hookSpecificOutput"]["permissionDecision"] == "deny"
  assert ready_hook == {}  # ordinary SDK permissions still decide
  assert after_npc_revision > start_revision and tool_was_allowed_by_readiness
  assert result.status == "error" and result.output == "partial"
  assert no_child_left and cleanup.clean
  ```

  Exercise idle Stop, query Stop, disconnect failure, SDK cap, EOF without terminal,
  and hook exceptions/timeouts. Fake clients must record lifecycle task identity.
  Add probe-runner tests with harmless fake child/tool sentinels: any tool execution
  despite denial, a missing case or incomplete evidence must fail the probe.
- [x] **Step 2 — Run red:**
  `python -m pytest bridge/tests/test_readiness.py bridge/tests/test_domain_sdk.py tests/test_m12_tool_guard_probe.py -q`.
- [x] **Step 3 — Implement mandatory hooks and the bounded owner mailbox.**
  Hook callbacks run direct bridge checks with a 5s deadline, before the SDK hook's
  10s timeout; catch failures and return explicit denial. Reload current consistent
  memory; do not demand equality with Start's revision. Cover every enabled built-in,
  MCP and delegated tool; never substitute `can_use_tool` alone or optional-hook
  ordering. The pinned CLI can convert SDK callback error replies into an empty
  successful hook. Add a transport adapter around the pinned subprocess transport:
  track inbound PreToolUse control IDs, normalize their error/malformed replies to
  explicit deny, and fail closed on unserviceable control traffic. Keep this state
  bounded and remove settled IDs. Preserve other SDK messages and normal permissions.
  Callback wrapper errors and transport control errors are distinct probe cases;
  a broken channel requires owned-CLI shutdown, not a fabricated successful check.
  Restrict available built-ins and delegated tool lists to verified paths; omit
  EndConversation and special/deferred paths that bypass normal hook dispatch.
  Build domain options separately from tools-disabled NPC options.
  Start one worker that enters the SDK context, consumes a one-command mailbox,
  queries/receives and disconnects within its own AnyIO cancellation scope. Caller
  cancellation signals that scope and awaits shielded cleanup; no SDK calls from
  the manager/caller and no raw cancellation that crosses ownership. Stop wakes
  an idle mailbox and can interrupt connect. Distinguish execution outcome from
  cleanup outcome; broken transport rejects further queries until clean restart.
  Interpret actual SDK result subtypes/caps as error terminals, preserving partial
  text. Never retry or reconnect a tool task automatically.
  Implement a bounded probe using these real hooks and harmless Read/Edit/Bash,
  MCP and delegated-agent sentinels. Force readiness denial, internal checker
  exception and checker timeout; record actual tool execution and CLI/SDK versions.
  Missing coverage or a tool that executes despite denial fails acceptance. Probe
  fixtures use disposable projects and explicit test-only injection, with no
  production bypass setting. See Task 10 for evidence retention and final rerun.
- [x] **Step 4 — Run green**, including the existing installed-transport harmless
  child reaping and guarded-transport tests. Run `python3 scripts/m12_tool_guard_probe.py --output
  /tmp/m12-tool-guard.json` against the actual pinned CLI before advancing to
  tool-enabled use; inspect every case. If runtime/auth is unavailable, other
  fake-only implementation may continue, but record this gate as open and do not
  enable product tools. A bypass requires an adapter/runtime fix, then a rerun;
  fake callbacks alone cannot establish enforcement.
  Retain sanitized acceptance with verified SDK/CLI versions, tool inventory,
  complete required cases and hashes of the enforcement sources. Production fails
  tools closed if that evidence is missing, invalid or stale; source changes need
  fresh probe evidence, never a hash-only update.
- [x] **Step 5 — Commit:**
  `git commit -m "feat(bridge): guard tools and own domain sdk lifecycle (PLZG-289)"`.

### Task 5: Make domain admission, generations and replay deterministic

**Files:** Modify `bridge/domain_session.py`, `bridge/domain_manager.py`,
`bridge/tests/test_domain_session.py`, `bridge/tests/test_domain_manager.py`,
`bridge/tests/test_protocol.py`; create `bridge/domain_protocol.py`.
**Consumes:** Task 4 owner/readiness, Task 3 turns/save results, Task 1 lease.
**Produces:** `validate_domain_command(payload: object) -> dict[str, object]`;
`DomainSink = Callable[[dict], Awaitable[None]]`;
`DomainManager(config: BridgeConfig, project_service: ProjectService, *,
recorder: BridgeRecorder|None = None)` with
`async handle(command: dict, *, context: RequestContext, emit: DomainSink) -> None`,
`async shutdown() -> None`. `RequestContext` remains the existing observability type.
`DomainSession(domain_id: str, domain_session_id: str, *, config: BridgeConfig,
project_service: ProjectService, recorder: BridgeRecorder|None = None)` owns one
generation; methods `async start() -> dict`,
`async admit_query(command: dict, *, context: RequestContext, emit: DomainSink) -> None`,
`background() -> dict`, `refocus() -> dict`, `async stop() -> dict`,
`replay(cursor: int) -> list[dict]`. The service interface consumed here is declared in
Task 6; use a fake implementing it until real integration, not a second service.

- [x] **Step 1 — Write failing lifecycle/correlation/replay tests.**
  `test_activation_exposes_generation_before_connect`,
  `test_admission_precedes_immediate_terminal`, `test_duplicate_run_is_not_reexecuted`,
  `test_stale_generation_cannot_mutate`, `test_replay_highwater_and_history_gap`,
  `test_memory_save_failure_does_not_retry_completed_task`.

  ```python
  assert types[:2] == ["domain_accepted", "domain_result"]
  assert execution_count == terminal_count == 1
  assert stale_reply["error_type"] == "session_unavailable"
  assert empty_replay[-1]["type"] == "resume_complete"
  assert retained_entries <= 256 and retained_output_bytes <= 4 * 1024 * 1024
  assert max_entry_bytes <= 256 * 1024 and truncated_entry["truncated"] is True
  assert successful_terminal["status"] == "success" and successful_terminal["memory"]["saved"] is False
  ```

  Include 128/129-byte IDs, 64 KiB/+1 task, Unicode/digit cursors, bool-as-cursor,
  10/11 domains, 2/3 generations, pending/completed duplicates and repeat Stop.
- [x] **Step 2 — Run red:**
  `python -m pytest bridge/tests/test_domain_session.py bridge/tests/test_domain_manager.py bridge/tests/test_protocol.py -q`.
- [x] **Step 3 — Implement coordinator-owned admission and terminal storage.**
  Canonical commands: describe_workspace/domain_status/activate_domain/domain_query/
  background_domain/refocus_domain/deactivate_domain/resume. All require nonempty
  request_id; domain commands require domain_id; Run/background/refocus/Stop/replay
  require domain_session_id. Start obtains its new generation without requiring
  a previous one; repeated Start reports the existing generation without replacing it. Replay cursor is an ASCII decimal string ("0" before first output),
  parsed as a nonnegative integer; output IDs are increasing decimal strings per
  generation. Keep known NPC validation separate. State packets use `domain_state`
  with state activating/active/background/stopping/inactive/cleanup_failed and
  execution_state idle/running/stopping/cleanup_failed. The spec's other names are
  literal packet types. Include project/session/workspace IDs and request correlation.
  Errors use `domain_error`, safe error_type/message and known identities.
  Separate the in-flight request record from retained terminal entries. Key Run
  deduplication by (generation,request_id); reject conflicting reuse of that ID.
  Checkpoint intent before acceptance, emit acceptance, then release execution;
  failed delivery after admission does not undo it. Store exactly one terminal
  before push; include agent/task, status/output/reason, truncation and memory save
  status. Lease spans the generation's connected SDK lifetime. Replay snapshots a
  high-water mark and completes even when empty; pruned history reports the earliest
  retained ID/history_gap. Evict only clean inactive old generations, never a live
  lease; reject excess active identities. No automatic Run retry after retention.
- [x] **Step 4 — Run green**, preserving recording/source-correlation tests in
  `bridge/tests/test_runtime_wiring.py`. Assert failed delivery never changes a
  stored success and replay never writes a second execution record.
  Verify this task at the manager/session boundary using the declared fake
  ProjectService. Task 6 owns migration of the old server API and must restore
  the full bridge/runtime suite before client integration. Preserve every recording
  assertion; do not add a second legacy domain protocol for intermediate commits.
- [x] **Step 5 — Commit:**
  `git commit -m "feat(bridge): correlate domain lifecycle and replay (PLZG-289)"`.

### Task 6: Route project setup and NPC turns through responsive connections

**Files:** Create `bridge/project_service.py`, `bridge/connection.py`,
`bridge/tests/test_project_service.py`, `bridge/tests/test_connection.py`.
Modify `bridge/server.py`, `bridge/conversation.py`, `bridge/conversation_backend.py`,
`bridge/conversation_sdk.py`, `bridge/conversation_api.py`, `bridge/bridge.py`,
`bridge/tests/test_server.py`,
`bridge/tests/test_conversation.py`, `bridge/tests/test_conversation_backends.py`,
`bridge/tests/test_runtime_wiring.py` and `bridge/PROTOCOL.md`. Add read-only
workspace/reservation observation in `bridge/workspace.py` and
`bridge/workspace_lease.py`, with covering tests in their existing test files.

**Interfaces:**
- `ProjectService(config: BridgeConfig, *, runtime_root: Path, owner_run_id: str,
  reviewer: Callable[[RepoInitProposal], Awaitable[object]])` exposes
  `async start() -> None` (schedules bootstrap), `snapshot() -> dict`,
  `async interact_setup(agent_id: str, request_id: str) -> str|None`,
  `require_workspace() -> ExecutionWorkspace`, `require_memory() -> ProjectMemoryStore`,
  `require_readiness() -> ReadinessService`, `async close() -> None`.
  The `require_*` methods raise a safe workspace_not_ready/memory_unavailable error;
  they never select another directory. A None setup response permits ordinary chat.
  It also exposes read-only `owner_run_id`,
  `publish_reservation(lease: WorkspaceLease) -> None`,
  `publish_cleanup(lease: WorkspaceLease, *, clean: bool) -> None`,
  `publish_memory(result: MemorySnapshot|MemorySaveResult) -> None`, and
  `async refresh_snapshot() -> dict`. Publications update cached observation only;
  DomainSession still acquires/releases its lease. Publish reservation before
  activating, and clear only the same lease after confirmed successful release.
  Save failure preserves the last confirmed revision plus explicit unsaved status.
  Snapshot refresh performs bounded read-only IO off the event loop; the ordinary
  snapshot getter stays cheap. Discovery adds request correlation to a copy.
  Snapshot wire type is `workspace_state`, correlated with request_id; fields are
  `project_id` (nullable before identity), `stage`, `reason`, `architect_decision`,
  `workspace_id`, `project_path`, `worktree_path`, `branch`, `changed_files`,
  `reservation`, and `memory`. Missing ready-only values are null. Reservation is
  null or `{domain_id, domain_session_id, cleanup_failed}`; memory is
  `{path, status, revision, error_type}` with status unavailable/saved/unsaved.
  Changed files exposes counts/truncation, never file contents. Discovery only
  observes setup; it cannot initialize Git or start a model call.
- `ConversationEngine.handle_request(request, history=None, *, metadata=None,
  prior_project_notes: str = "")` keeps its existing response shape. Add the same
  optional keyword to `ConversationBackend.complete()` and both adapters; extend
  existing `ExecutionMetadata` with `memory_delta: dict|None = None`. Reuse Task 4
  `decode_project_reply(output: str) -> tuple[str, dict|None]` from
  `conversation_backend.py` in both NPC adapters; DomainSDKOwner already uses it.
  For configured project context, request one JSON object with `answer: str` and
  optional `memory_delta: object`; a valid answer survives an invalid delta. Plain
  text remains valid fallback output. Unconfigured conversations bypass parsing.
- `ConnectionState` owns `connection_id`, NPC histories/task, ordinary-control
  admission and one serialized sender: `async send(packet: dict) -> None`,
  `async close() -> None`. Extend `BridgeServer.dispatch(data: dict, histories=None,
  *, connection_id: str|None = None, emit: DomainSink|None = None) -> list[dict]`
  and `dispatch_raw(raw_message: str, histories=None, *, connection_id: str|None = None,
  emit: DomainSink|None = None) -> list[dict]`. With a sink, emit replies and return
  an empty list; without one, collect immediate ack/rejection replies for direct
  tests. Later terminals remain in the domain store and can be read by replay.

- [x] **Step 1 — Write failing setup, memory and socket-routing tests.**
  `test_other_npc_refers_without_reviewer_or_tools`,
  `test_chief_submission_confirms_once_without_human_prompt`,
  `test_preflight_memory_failure_prevents_provider_call`,
  `test_notes_are_separate_from_npc_history_in_both_backends`,
  `test_pending_npc_does_not_block_stop_or_discovery`,
  `test_new_connection_cannot_steal_domain_output`.

  ```python
  assert "Chief Architect" in other_npc_reply["output"]
  assert reviewer_calls == 0 and git_mutations == 0
  assert repeated_chief_reviewer_calls == 1
  assert denied_provider_calls == 0
  assert original_history == history_after_injecting_notes
  assert terminal_received_by == originating_connection_id
  assert disconnected_domain_is_still_running
  ```

  Assert pre-ready discovery, idle Start preemption, slow/broken sender isolation,
  no global socket, setup failure reason, same-client request correlation and
  successful task/failed memory save separation. Preserve the existing NPC
  `output`/`status` response fields and successful-history commit behavior.
- [x] **Step 2 — Run red:**
  `python -m pytest bridge/tests/test_project_service.py bridge/tests/test_connection.py bridge/tests/test_server.py bridge/tests/test_conversation.py bridge/tests/test_conversation_backends.py -q`.
- [x] **Step 3 — Implement composition, setup interaction and bounded transport.**
  Listen while service bootstrap runs. Snapshot stages exactly unconfigured/
  needs_architect/preparing/reviewing/initializing/ready/failed. Existing Git
  bootstrap is automatic. Add `load_workspace(project, *, runtime_root)` that
  reads/validates existing ready ownership without creation or idle acquisition,
  and a safe read-only reservation observer using existing lock/marker files.
  A healthy foreign live holder permits discovery and NPC memory; Start still
  returns workspace_busy. A lock-free unclean marker blocks reuse and never
  authorizes recovery. External observations are advisory; a held marker without
  a known cleanup-failure indication does not prove successful teardown. Do not
  create lock files during discovery. Use `git_without_filters` for changed-file
  counts with bounded subprocess output; never plain Git status that can execute
  clean filters. Non-Git review starts only for a submitted
  systems-architect request. Other agents receive the spec's setup referral.
  The reviewer uses a fresh tools-disabled conversation backend, the existing NPC
  deadline/caps and an exact JSON approval schema, without ordinary project-memory
  preflight before memory exists. Call Task 2 only after valid approval, then Task 1
  bootstrap and Task 3 initialize/attach_run. Repeated interactions report the
  current review; failure needs a new explicit Chief submission, not automatic retry.
  Ordinary turns get a UUID turn_id, load/checkpoint intent, invoke once with labeled
  notes outside history, then finish memory with validated optional delta. Carry
  optional structured answer/delta metadata through `decode_project_reply`;
  absent/invalid delta uses excerpts while preserving the visible answer. After
  repository creation, checkpoint the exact approval, seed/exclusion summary and
  initial commit into memory before reporting ready.
  Add a narrow trusted setup-checkpoint method in `project_memory.py`, with
  covering memory tests, because ordinary turn excerpts truncate the exact
  approval. Keep the three-file grammar/caps and verify bounded round-trip
  retention before ready; checkpoint failure preserves the initialized repo
  and reports unsaved/failed without automatically repeating initialization.
  Bound Chief responses by the configured NPC deadline too: after valid in-budget
  approval, return approved/initializing progress if service-owned setup outlasts
  the caller budget. Keep initialization tracked, domain execution blocked until
  ready, and no automatic retries. Review timeout still authorizes no Git mutation.
  Keep the configured NPC deadline across preflight/model/reply; bounded cleanup
  follows the existing pattern. An unconfigured bridge retains current NPC behavior.
  Reader dispatches without awaiting NPC work. Bound each connection to one NPC
  operation and one ordinary domain control; return correlated busy errors for
  excess work. Release ordinary control at ack/reject, not terminal. Stop/discovery
  can preempt activation; allow one Stop and one discovery slot per connection,
  returning correlated busy errors when either is occupied.
  Serialized sends have a 2s deadline and ≤32 queued packets; closed/slow sinks
  detach delivery without cancelling domain ownership. Closing a connection drains
  its NPC work and history only. Shutdown drains domains, then project/run ownership using `detach_run` after
  owned turns settle; retain operational evidence if cleanup cannot be confirmed.
  Document packet examples, replay/busy/identity rules and setup/memory status now.
- [x] **Step 4 — Run green** plus all existing bridge unit tests and recording
  integration. Verify the tools-disabled Chief path cannot mutate before the
  bridge has accepted its exact structured decision.
  Migrate the existing real M11 integration fixtures (Godot test script and
  Python driver) to assert correlated busy for a second concurrent NPC request,
  then explicitly submit it after the first completes. Preserve all prior
  history/failure/reconnect checks; no implicit queue or frozen evidence edits.
- [x] **Step 5 — Commit:**
  `git commit -m "feat(bridge): route project setup and concurrent client work (PLZG-289)"`.

### Task 7: Add pure domain state and workspace/domain transport to Godot

**Files:** Create `scenes/bridge/domain_store.gd`,
`tests/domain_store_test.gd/.tscn`, `tests/domain_transport_test.gd/.tscn`,
`tests/domain_transport_fixture.gd`; modify `scenes/bridge/ws_client.gd`,
`autoload/GameEvents.gd`, `scripts/run_headless.py` and existing transport fixtures
only where automatic discovery would violate their NPC-only assumptions.

**Interfaces:** `DomainStore` is a RefCounted pure state object:
`apply_packet(packet: Dictionary) -> Dictionary`,
`admit_command(packet: Dictionary) -> bool`, `disconnect_connection() -> void`,
`bind_project(project_id: String) -> void`, `snapshot(domain_id: String) -> Dictionary`,
`set_draft(domain_id: String, text: String) -> bool`,
`mark_read(domain_id: String, output_id: String) -> void`.
`BridgeClient` adds `workspace_snapshot()`, `domain_snapshot(domain_id)` returning
Dictionary; `describe_workspace()`, `domain_status(domain_id)`,
`activate_domain(domain_id)`, `send_domain_query(domain_id, agent_id, task)`,
`background_domain(domain_id)`, `refocus_domain(domain_id)`,
`deactivate_domain(domain_id)`, `resume_domain(domain_id)` returning String request
IDs (empty on local rejection); and
`set_domain_draft(domain_id: String, text: String) -> bool`,
`mark_domain_read(domain_id: String, output_id: String) -> void`. All parameters above are String unless stated.
Domain snapshot keys are `project_id`, `domain_id`, `domain_session_id`,
`workspace_id`, `state`, `execution_state`, `pending_query`, `pending_control`,
`draft`, `results`, `received_cursor`, `consumed_cursor`, `omitted_count`,
`uncertain`, `error`, and `memory`. Cursor values are decimal strings; compare them
by numeric decimal-string order without signed-64-bit narrowing; reject invalid
or over-128-byte identifiers without cursor advancement. Results keep the full
terminal wire shape. A replay completion advances `received_cursor` only through
a contiguous observed prefix or an explicit history gap; interleaved live output
must not skip unseen replay. `mark_read(domain_id, output_id)` targets only the
current generation and cannot pass its confirmed received prefix. Replay results
retain their original Run request IDs; only `resume_complete` carries the Resume
request ID. Correlate completion with that replay and connection, and treat its
lifecycle/execution fields as captured observations: they must not overwrite
newer live state. Fresh status discovery resolves remaining lifecycle uncertainty.
Add only GameEvents `workspace_changed(reason, request_id)` and
`domain_changed(domain_id, reason, request_id)` with String parameters.

- [x] **Step 1 — Write failing pure-store and real-loopback transport scenes.**
  Assert copies cannot mutate store state; stale-generation replies cannot settle
  newer commands; domain packets never settle NPC requests; 200-entry/1 MiB bounds
  include drafts and retained generations; disconnect preserves uncertain work.
  Use core and engineering IDs for distinct-domain tests. Pin assertions:

  ```gdscript
  assert(execution_count == 1 and rendered_output_ids.size() == 1)
  assert(snapshot["omitted_count"] > 0)
  assert(snapshot["received_cursor"] != snapshot["consumed_cursor"])
  assert(store.snapshot("core")["draft"] == draft_after_busy)
  assert(last_command["domain_session_id"] == current_session)
  assert(npc_pending_count == npc_pending_before_domain_packet)
  ```

  Include live/replay interleaving, empty resume_complete, 64 KiB/+1 drafts,
  project switch, reconnect discovery, activating-generation Stop and corrupt data.
- [x] **Step 2 — Register positive-marker aliases and run red:**
  `python3 scripts/run_headless.py domain_store domain_transport`.
  Markers are `domain_store_test: OK — N checks passed.` and analogous transport,
  with N>0. Preserve the existing timeout/error detection.
- [x] **Step 3 — Implement demultiplexing and bounded snapshots.**
  Route workspace/domain types before NPC validation. Keep NPC maps/context
  untouched. Store project/session/workspace IDs, lifecycle/execution, pending
  query/control, draft, results, replay and consumed cursors, omitted count,
  uncertainty and error separately. Capture expected generation in wrappers;
  UI never supplies paths. Register pending state before send. A terminal clears
  the query, an ack clears its control; acceptance does not complete the query.
  A matching activating reply exposes generation immediately for Stop. Refresh
  workspace after connect/turn/lifecycle results; poll every 2s only during
  preparing/reviewing/initializing. Rebinding a different project clears NPC and
  domain cached display/drafts before presenting new project state. Reconnect to
  the same project discovers and explicitly replays without Run retry.
- [x] **Step 4 — Run new scenes green** plus the existing transport/conversation
  store gates, checking existing signal arities and both kinds of pending request.
- [x] **Step 5 — Commit:**
  `git commit -m "feat(godot): track workspace and domain sessions (PLZG-289)"`.

### Task 8: Render explicit controls and preserve physical NPC interaction

**Files:** Create `scenes/hud/domain_panel.gd/.tscn`,
`tests/domain_panel_test.gd/.tscn`; modify `scenes/main.tscn`, `scripts/run_headless.py`.
Read existing dialogue/player/NPC scripts; modify them only if a tested integration
requires it. Keep Main/HUD paths intact and mount a separate Main/DomainHUD.
**Consumes:** Task 7 BridgeClient/GameEvents; existing AgentRegistry and proximity.
**Produces:** one panel with Start, Run, Refocus, Background/Close, Stop, task input,
results label and passive global status. Local state: nearby/anchor agent ID,
selected domain ID and anchored-versus-remote mode. No new autoload.

- [x] **Step 1 — Write failing real-scene panel tests.**
  Cover explicit Start/Run, idle Stop-to-release copy, disabled busy controls,
  draft retention, rendered result/status, viewport focus, unrelated NPC departure,
  matching anchor departure, remote detach and return-to-anchor replay sequencing.

  ```gdscript
  assert(start_count == 0) # proximity alone
  assert(run_count == 1) # one native text submission
  assert(background_count == 1 and not panel.visible)
  assert(refocus_ack_precedes_resume)
  assert(not input.has_focus()) # incoming output never steals it
  assert(player_can_move_after_escape and running_task_unchanged)
  ```

  Chief referrals use normal NPC text_submitted; approaching it never starts review.
  Test Tab/Shift+Tab, Escape and resizing against actual enabled controls.
- [x] **Step 2 — Register `domain_panel` marker and run red:**
  `python3 scripts/run_headless.py domain_panel`.
- [x] **Step 3 — Implement the panel and minimal scene wiring.**
  Derive domain ID from AgentRegistry department. Explicit NPC-domain action
  captures its anchor; only that NPC's departure backgrounds/closes. Returning
  refocuses then resumes after acknowledgment; never starts/submits. Global Refocus
  detaches proximity; explicit NPC-domain action reattaches. Background/Close
  releases focus, Escape releases only keyboard focus. Render workspace/branch,
  setup stage, saved/unsaved memory, lifecycle/execution, unread/omitted counts and
  `Stop to release workspace`. Incoming packets update data without opening a
  panel or replacing NPC output. Keep Chief interaction in the existing NPC panel.
- [x] **Step 4 — Run panel and existing dialogue/smoke gates green.**
  Use `python3 scripts/run_headless.py domain_panel dialogue_panel smoke` after
  import; preserve production world/agent taxonomy.
- [x] **Step 5 — Commit:**
  `git commit -m "feat(godot): control and revisit background domain work (PLZG-289)"`.

### Task 9: Prove the complete deterministic flow and wire required gates

**Files:** Create `bridge/tests/test_godot_domain_integration.py`,
`bridge/tests/test_m12_integration.py`, `tests/godot_domain_integration.gd/.tscn`.
Modify `package.json`, `.github/workflows/ci.yml`; preserve current M11 harness and
its current 38-check marker. Reuse its real websocket/Godot subprocess pattern.
**Consumes:** Tasks 1–8 real services, fake SDK synchronization and real temporary Git.
**Produces:** deterministic end-to-end proof and `test:m12` / M12 integration gates.

- [x] **Step 1 — Write failing complete-flow fixtures.**
  Empty directory: submit to ordinary NPC, observe referral/no review; move player
  to Chief and submit, approve with fake reviewer, inspect main/worktree/memory.
  Start/Run A; move actual Main/Player beyond the anchor's ProximityShape radius,
  await physics frames/background ack, submit unrelated NPC chat, then release
  fake SDK latch. Return physically and read the rendered result label. Add an
  engineering NPC only in fixture if a distinct domain is needed (world NPCs share
  core). Drive native controls, not manually emitted proximity or store-only output.

  ```python
  assert main_branch == "main" and memory_file_count == 3
  assert sdk_write_time > background_ack_time and sdk_write_time > npc_chat_complete_time
  assert observed_sdk_cwd == execution_worktree
  assert sdk_runs == stored_terminals == rendered_unique_results == 1
  assert plain_client_result_id == godot_result_id
  assert source_status_after == post_bootstrap_source_status
  ```

  Include two sockets/closed origin, Stop during connect, crash marker refusal,
  new-generation stale commands, memory-save failure, restart context and second
  repo isolation. Keep ordinary NPC and domain history assertions separate.
- [x] **Step 2 — Run red:**
  `PLAZA_REQUIRE_GODOT=1 python -m pytest bridge/tests/test_godot_domain_integration.py bridge/tests/test_m12_integration.py -q -s`.
- [x] **Step 3 — Close integration gaps and wire CI.**
  Add `test:m12` invoking the three new headless aliases and a separate real-client
  integration command; include them in npm test and CI's Godot job. Require Godot
  via PLAZA_REQUIRE_GODOT=1, positive assertions/marker and nonzero failure on load
  errors. Keep network/provider stubs under the existing autouse prohibition.
  Update current tests whose dispatch assumptions intentionally changed, retaining
  their behavior assertions rather than deleting them to get green.
- [x] **Step 4 — Run the full deterministic gate once green:**
  `python -m pytest bridge/tests/ tests/ -q`, `godot --headless --import`, `npm test`,
  `black --check .`, `flake8 . --select=E9,F63,F7,F82`,
  `python3 scripts/validate_specs.py`, `python3 scripts/validate_delivery_coordinates.py`.
  Resolve failures; do not re-stamp frozen sprint evidence. Record exact commands
  and results, separating environment skips from executed proof.
- [x] **Step 5 — Commit:**
  `git commit -m "test(m12): verify project setup and background execution (PLZG-289)"`.

### Task 10: Verify the actual CLI guard and record live M12 acceptance

**Files:** Create `scripts/m12_live.py`, `tests/test_m12_live.py`; reuse Task 4
`scripts/m12_tool_guard_probe.py` and `tests/test_m12_tool_guard_probe.py`. Add a live-mode driver
in `tests/godot_domain_integration.gd` without weakening fake-mode assertions.
Modify `QUICKSTART.md`, `bridge/PROTOCOL.md`, `CHANGELOG.md`, current status/index
prose, this plan and Jira only as evidence warrants. New evidence target:
`specs/evidence/m12-live-2026-10-21.json` (use actual run date if later).
**Consumes:** Full M12 implementation, configured SDK auth, real Godot and disposable projects.
**Produces:** reproducible probes, sanitized evidence and an honest milestone state.

- [x] **Step 1 — Write failing evidence-runner tests with fake children/providers.**
  Assert missing/malformed/partial evidence cannot report pass; no API key/token
  enters artifacts; nonce file absence is checked before release; the harness never
  writes the claimed agent-created result; nonzero children/cleanup fail acceptance.
  Preserve Task 4 hook-probe tests that reject a tool invoked despite denial.
- [x] **Step 2 — Run red:**
  `python -m pytest tests/test_m12_live.py tests/test_m12_tool_guard_probe.py -q`.
- [x] **Step 3 — Implement bounded runners and operator instructions.**
  Probe harmless Read/Edit/Bash, MCP and delegated-agent paths under the pinned CLI;
  instrument whether tools really ran. Force readiness denial and hook exception/
  timeout; successful callbacks alone cannot pass the probe. If any path bypasses
  enforcement, keep it disabled, fix the adapter/runtime integration and rerun the
  affected probe before tool-enabled product use. Do not reinterpret a failing
  required path as supported. Record SDK/CLI versions and tested paths.
  Live runner selects an empty disposable project through configuration, exercises
  ordinary-NPC referral and a real Chief approval, records initialized main/seed,
  worktree/memory and post-bootstrap baseline, then starts one capped SDK tool task.
  Keep a release file/nonce unavailable until actual Godot background acknowledgment
  and unrelated NPC completion. The SDK reads the release and creates the result;
  verify absent-before, tool-action timing, content/path and one rendered result.
  Plain client retrieves the same output; clean Stop/restart must load notes into
  a fresh invocation without rerunning the completed task. A second repo receives
  none of its notes/nonce. Use per-process deadlines and configured model caps;
  no automatic paid retries. Evidence includes commit/versions/auth mode (not
  secrets), IDs, paths, UTC ordering, outcomes, source/runtime status/HEAD/hashes,
  memory revision/readback and teardown. Reject open manifests as clean shutdown.
  Document config/env examples, sibling WT and Git-memory locations, Chief loop,
  retained edits, recovery inspection and unsupported-platform behavior. Never
  prescribe blanket lock/marker deletion as a recovery command.
- [ ] **Step 4 — Run fake tests green, then real probes and acceptance.**
  Commands: `python3 scripts/m12_tool_guard_probe.py --output /tmp/m12-tool-guard.json`
  and `python3 scripts/m12_live.py --output /tmp/m12-live.json`.
  Both must exit 0 with per-case evidence; inspect it before copying sanitized
  accepted evidence into the repo. If credentials/display/runtime are unavailable,
  record that exact limit and keep acceptance open. Obtain desktop acceptance for
  focus, controls, physical referral/background/refocus and visible unsaved state.
  Run final regression checks appropriate to any corrections, then whole-branch
  review. Do not claim M12 complete merely because the runner exists.
- [ ] **Step 5 — Commit and follow repository delivery policy.**
  `git commit -m "test(m12): record guarded sdk execution acceptance (PLZG-289)"` only
  when the evidence exists; use a runner-only message otherwise. Open/update scoped
  PRs against dev, attach them, satisfy required checks and all review surfaces
  under `.claude/pr-workflow.md`. Close PLZG-289 only after implementation merges,
  deterministic/live evidence passes and desktop acceptance is recorded.


**Observed Task 10 progress, 2026-10-21:** runner/test/scene code is committed
through `c128b543d73864099002247c7f32854e2b020c3f`. Fresh
[guard evidence](../../../specs/evidence/m12-guard-2026-10-21.json) passed all
29 cases; the [actual Linux live report](../../../specs/evidence/m12-live-2026-10-21.json)
exited 0 and passed real Chief approval, causal SDK result creation, exact raw
Godot/plain output parity, clean restart/readback and independent-repository
isolation. Actual three bridge manifests closed, five SDK CLIs exited 0, leases
released and memory-run markers detached. The [attempt ledger](../../../specs/evidence/m12-live-attempts-2026-10-21.json)
preserves four failed reports and concrete corrections. Step 4 stays open for
owner desktop/laptop-binary acceptance and final review; Step 5 stays open for
external delivery/merge and milestone acceptance. No M12/Jira closure is implied.

**Final correction evidence, 2026-10-21:** commits `54883c0` and `73fcfc5`
address the eight whole-branch review findings. The full deterministic gate passed
1,674 Python tests plus 118 subtests and pinned Godot/npm gates; the subsequent
output-checkpoint correction passed 361 covering tests. The
[final guard matrix](../../../specs/evidence/m12-guard-final-2026-10-21.json)
passed all 29 cases and now supplies the exact fixed activation manifest. Its
[attempt ledger](../../../specs/evidence/m12-guard-final-attempts-2026-10-21.json)
preserves the prior max-turns failure and the deliberate unchanged-source second
attempt. All historical live reports remain unchanged. Desktop/laptop acceptance
and milestone closure are still open; these observations do not mark Steps 4–5
complete.

## Controller handoff

Recommended execution: **subagent-driven**, with one builder and fresh review per
completed task, because workspace ownership, cancellation and persistence failures
cross several interfaces and can affect real project files. Keep shared-file edits
sequential; use isolated worktrees for independently assigned implementation work.
The authoring worktree under `.claude/worktrees/` is not a valid runtime execution
worktree. A plan checkbox changes only with observed evidence, not a worker claim.

The owner approved this written plan and selected subagent-driven execution on
2026-10-21. Use that Superpowers execution skill without repeating either approval. This planning document is not the
three-file project memory feature it describes.
