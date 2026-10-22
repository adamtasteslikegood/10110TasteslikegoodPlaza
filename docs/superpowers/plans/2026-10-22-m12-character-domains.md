---
doc_id: M12-CHARACTER-DOMAIN-PLAN
title: M12 department domains and character work implementation plan
tier: 3
authority: implementation
status: ACTIVE
doc_set_version: 0.2.18
last_updated: 2026-10
owner: adamtasteslikegood
derives_from: [M12-CHARACTER-DOMAIN-AMENDMENT]
supersedes: []
enforcement: intended
gates: [Validate Specs:live]
weakest_claim: This plan records authorized work, not completed runtime acceptance.
---

# M12 department domains and character work implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make working NPC dialogue use its department's managed execution session, with department worktrees, shared project context and explicit work controls.

**Architecture:** Keep the existing domain lifecycle and display store. Separate project preparation/memory from department workspace readiness, resolve character bindings from committed canonical metadata, and compose bounded game/work context at every model admission. Story extras retain the conversation engine.

**Tech Stack:** Python 3.11+, asyncio/AnyIO, pinned Claude Agent SDK, Git worktrees, Godot 4/GDScript and pytest.

**Spec:** [Approved M12 amendment](../specs/2026-10-22-m12-character-domain-amendment.md), approved at `eadb0b4` by the owner's “ok, build it” instruction on 2026-10-22. The owner already selected subagent-driven implementation and fresh review per task. That instruction authorizes executing this plan without another approval round.

This plan records authorized work, not completed runtime acceptance.

## Global Constraints

- One configured project/main repo per bridge session; `WORKSPACE_ROOT_DIR` and `PLAZA_WORKSPACE_ROOT_DIR` retain startup snapshot semantics.
- Every catalog agent is working; its canonical category is its domain. Extras cannot shadow catalog IDs. Generated `data/agents.json` is never hand-edited; runtime never reads the submodule.
- One worktree per `(project_id, domain_id)`; preserve valid legacy Core worktree identity/path/branch/commits/edits through migration. Uncertain ownership blocks reuse.
- TODO/HANDOFF/PROGRESS remain one project-scoped set under the common Git directory. Serialize writes and attribute domain/agent/workspace.
- Approach/status makes no provider or provisioning call. Start reserves/prepares only; Send is explicit Run; leaving backgrounds; Stop remains available while ownership persists, including idle/background.
- Chief-approved initialization uses `main`, exact inspected proposal/allowlist, no second human prompt; tools remain unavailable before readiness.
- `INSTALL_CONTEXT_DIR` defaults to `../.local/plaza-context`; optional `GAME_CONTEXT.md`/`WORK_CONTEXT.md`. `PROJECT_GUIDANCE_FILE` defaults to `PLAZA_AGENTS.md`. Both support `PLAZA_` overrides.
- Shipped game/work briefs and each installation file: 8 KiB each; project guidance: 32 KiB; runtime facts: 4 KiB. Refresh per admitted turn; diagnostic metadata contains revisions/identities, not instruction bodies.
- `DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS` defaults to strict boolean `false`; `PLAZA_DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS=true|false` overrides. False is `dontAsk`, true is `bypassPermissions`. Read/Edit/Bash inventory and mandatory guards remain.
- Do not invent story beats, deliver the second playable department, add queues, claim concurrency, or introduce sandboxes. Preserve SB-08 arrival and SB-09 first delegation; capability is an additional prerequisite to earned unlocks.
- Keep source/runtime/mode-bound real guard acceptance; no hash-only refresh, production bypass, or automatic paid retries. Desktop/OAuth owner acceptance remains separate from cloud API-key evidence.

## Review Focus

- A dirty legacy Core checkout plus an incomplete migration must never be replaced or adopted by another department (Task 3).
- Status received after walking away/reconnecting must not activate, submit or steal foreground state (Task 7).
- Instructions changed between Runs, or replaced with a symlink/oversized file, must refresh or fail visibly instead of silently losing guidance (Task 4).
- A stopped idle session, failed startup, or uncertain cleanup must release or retain both capacity and the correct workspace consistently (Task 3).
- A working-agent legacy request before repository readiness must still expose reachable Chief setup and never fall back to tools-disabled conversation (Task 5).

## Files and responsibilities

- `bridge/agent_bindings.py`, generated committed bindings and `bridge/sync.py`: canonical working/extra membership; definitions remain in the bridge store.
- `bridge/workspace.py`, `workspace_lease.py`, `project_service.py`, `readiness.py`, `project_memory.py`: department ownership and project-wide continuity.
- `bridge/context.py` and shipped brief files: bounded source loading and packet composition, independent of UI.
- `bridge/interaction_protocol.py`, `server.py`, `domain_manager.py`, `domain_session.py`: typed status/setup, admission and representative attribution.
- `bridge/config.py`, `domain_sdk.py`, `tool_guard_evidence.py`, probe scripts: permission mode and evidence enforcement.
- Existing Godot bridge/domain store/panels: one shared session view with contextual NPC controls; small shared view/controller helpers are allowed instead of duplicating lifecycle code.
- Existing tests and live runners: update changed contracts while retaining regression coverage, with explicit extras fixtures.

## Task 1: Ratify the approved amendment

**Files:** Modify entitled design/decision docs, original M12 spec, `specs/roadmap.md`, `specs/meta/doc-registry.json`, `specs/meta/spec-drivers-v0.2.5.md`, indexes, `CLAUDE.md`, `README.md`, `CHANGELOG.md`; bump all governed frontmatter together to `0.2.18`.

**Interfaces:** Consumes approval at `eadb0b4`; produces ACTIVE amendment and reconciled D-033/D-034/D-038. D-006 stays superseded; D-039 stays project-scoped.

- [x] Record approval and exact changed execution/workspace scope in entitled documents. Update original M12's explicitly amended sections and roadmap dependency boundaries; distinguish design approval from implementation/acceptance.
- [x] Register this plan, close pending conflict §4.15 with the owner ruling, reconcile current summaries, and bump the governed doc set per META-SPEC §8.
- [x] Run `python3 scripts/validate_specs.py` and `git diff --check`; expect zero errors. No product test for prose-only ratification.
- [x] Commit `docs(PLZG-289): ratify department execution amendment`.

## Task 2: Canonical working-agent and extra bindings

**Files:** Create `bridge/agent_bindings.py`, committed binding metadata, explicit extra definition store/registry; modify `bridge/agents.py`, `bridge/sync.py`, generation/check integration and `bridge/tests/test_agents.py`; add `bridge/tests/test_agent_bindings.py`.

**Interfaces:** `AgentBinding(agent_id: str, execution_kind: str, domain_id: str | None)`; `resolve_binding(agent_id: str) -> AgentBinding`; `require_working_binding(agent_id: str, domain_id: str) -> AgentBinding`. Fail with stable `invalid_binding`; valid extra definitions are loaded without shadowing catalog entries. No production story character is invented solely for tests; injected explicit extra fixtures are supported.

- [x] Write failing tests: Architect/Auditor resolve to working/Core; every generated catalog entry matches committed metadata and has its curated definition; extra collision and mismatched/unknown domains fail; bridge resolution works with the submodule absent.
- [x] Run focused tests and confirm missing functionality fails. Generate bindings and synchronize curated definitions using the same canonical rename/exclusion rules as presentation generation, without hand-editing generated data.
- [x] Implement the resolver and explicit extras registry. Wire drift checks into the existing generation/sync check; default all catalog entries to working only through validated metadata, never silently on malformed input.
- [x] Run focused tests, generator `--check`, Black and Flake8 syntax checks for changed Python; expect pass.
- [x] Commit `feat(PLZG-289): bind catalog agents to department domains`.

## Task 3: Department worktrees, project memory and session capacity

**Files:** Modify `bridge/workspace.py`, `workspace_lease.py`, `project_memory.py`, `readiness.py`, `project_service.py`, `domain_session.py`, `domain_manager.py`, `domain_protocol.py` and their tests/harnesses. A focused workspace migration helper may be extracted.

**Interfaces:** Add `ExecutionWorkspace.domain_id`; `load_workspace(project, *, domain_id="core", runtime_root)` and `prepare_worktree(project, *, domain_id="core", runtime_root)` preserve old Core caller compatibility. `ProjectService.snapshot()` describes project/shared memory; `workspace_snapshot(domain_id)` is read-only; `await prepare_domain(domain_id)` prepares only the selected domain; `require_workspace(domain_id="core")` and `require_readiness(domain_id="core")` are scoped; `require_memory()` is project-only. DomainSession passes its ID everywhere. Add `workspace_id` to attributed turn data with backward-compatible old memory reads.

- [x] Write failing tests for two departments' distinct paths/branches/records, restart reuse, same-domain exclusion, wrong-domain lease/readiness denial, dirty Core legacy adoption, partial/live-owner migration rejection, unchanged three-file memory, capacity refusal and idle/failed/uncertain cleanup.
- [x] Confirm tests fail before implementation. Decouple project memory from a particular execution checkout; project startup/setup initializes project memory without eager department provisioning. Maintain owned/drained filesystem work.
- [x] Implement per-domain records/paths/branches and locked in-place Core adoption. Use both the short common provisioning lock and existing execution reservation during migration; tombstone old metadata so old clients reject reuse. Preserve uncertain markers and all edits.
- [x] Integrate explicit Start preparation and a single execution capacity slot distinct from workspace locks. Retain both through cleanup; a second department gets `capacity_limit`, never borrows Core. Share serialized memory and preserve generation/terminal/checkpoint ownership.
- [x] Run workspace/lease/memory/readiness/project/session/manager tests, including existing cancellation and bootstrap cases; expect pass. Format/lint changed Python.
- [x] Commit `feat(PLZG-289): isolate department execution worktrees`.

## Task 4: Bounded game and project context

**Files:** Create `bridge/context.py` and shipped game/work briefs; modify `bridge/config.py`, `bridge/config.json`, `.env.example`, conversation engine/backends as needed, `project_service.py`, `domain_session.py`, `domain_sdk.py`, observability metadata and focused tests.

**Interfaces:** `ContextPacket` contains rendered game/work text and source metadata; `compose_context(config, *, agent_id, execution_kind, domain_id, project, workspace, tools, permission_mode, interaction) -> ContextPacket` performs bounded synchronous reads inside `owned_io`. Add optional `context_packet` keyword to conversation admission and SDK execute; callers supply a fresh packet per admitted turn. Chief review receives the same composer plus exact proposal constraints and explicit setup intent. Missing/invalid context raises `context_unavailable` before provider work.

- [x] Write failing tests for config-relative install directory/env overrides, main-root guidance before Git, absent optional defaults, explicit missing alternative, traversal/symlink/nonregular/invalid UTF-8/oversize failures, exact 8/32/4 KiB limits, revision refresh and project isolation.
- [x] Confirm failure; implement labeled game/work sources with runtime capabilities overriding narrative tool claims. Keep memory as prior data, source root separate from execution CWD, and no ambient settings/hooks or parent/submodule crawling.
- [x] Inject into extras, domain turns and Chief review, including pre-repo states and current representative. Capture only source identities/revisions in diagnostics. Test all three entry points with recording fake adapters and no provider calls.
- [x] Run context/config/conversation/project/domain/observability tests; format/lint changed Python; expect pass.
- [x] Commit `feat(PLZG-289): orient agents with scoped game and project context`.

## Task 5: Typed character status/setup and routing

**Files:** Create `bridge/interaction_protocol.py`; modify `bridge/server.py`, `protocol.py`, `domain_protocol.py`, `domain_manager.py`, `domain_session.py`, `project_service.py`, `bridge/PROTOCOL.md` and corresponding tests/fakes.

**Interfaces:** Strict status request `{type:"agent_status",agent_id,request_id}`. Response has the same type/IDs plus `execution_kind`, nullable `domain_id`, `capabilities`, `project`, nullable `workspace`, nullable `domain_state`. Strict setup request `{type:"project_setup",agent_id,request_id,intent}` with bounded nonempty UTF-8 intent up to 64 KiB. Response has type/IDs, `status`, `output`, `project`, `architect_decision`, and `error_type` on failure. Capabilities include `can_start`, `can_run`, `can_prepare_project`, `tools`, `execution_capacity`, `reason`. Errors remain correlated. Unknown typed operations fail explicitly.

- [x] Write failing tests: status does no model/provisioning work; Chief setup reaches main+memory before a domain exists; other characters refer Chief; working legacy request returns `domain_required`/binding/required action with zero provider/history/checkpoint mutation; every Run validates agent membership; extras still converse while Core runs.
- [x] Confirm failure; dispatch service commands before legacy parsing and apply bindings before any legacy conversation admission, including unconfigured projects. Forward explicit setup intent without enlarging the proposal allowlist.
- [x] Report domain-specific readiness and capacity, retaining no automatic retries/fallback. Preserve legacy conversation protocol only for explicit extras. Adapt affected server/protocol/integration fixtures deliberately; do not relabel Core catalog agents.
- [x] Run protocol/server/request-correlation/domain/project and provider-free integration tests; format/lint; expect pass.
- [x] Commit `feat(PLZG-289): route working characters through domain controls`.

## Task 6: Permission switch and mode-bound guard evidence

**Files:** Modify config/defaults/env docs, `bridge/domain_sdk.py`, `tool_guard_evidence.py`, `scripts/m12_tool_guard_probe.py`, guard/config/SDK tests and probe tests.

**Interfaces:** Strict boolean setting and env override from Global Constraints. `domain_options` chooses only `dontAsk` or `bypassPermissions`. Evidence validation binds explicit `permission_mode`; the product acceptance artifact retains independently verified entries for both modes. Runtime selects its matching entry and rejects stale/missing/wrong-mode evidence. Probe mode is an explicit required option, not inherited from environment.

- [x] Write failing tests for false/true and invalid config/env values, exact SDK mode/no duplicate CLI flags, unchanged tools/hooks/budget/cwd, wrong-mode/stale evidence rejection, and independently retained mode records.
- [x] Confirm failure; implement mode selection and evidence schema/probe selection. Preserve actual denial/nonexecution observations, error/timeout handling and owned cancellation. Keep the production acceptance gate fail-closed until Task 8 records fresh evidence.
- [x] Run config/domain SDK/guard/probe/evidence tests without providers; format/lint; expect pass. Tests must use explicit synthetic fixtures, never rewrite production acceptance hashes as proof.
- [x] Commit `feat(PLZG-289): control domain permission mode with verified guards`.

## Task 7: NPC dialogue as the shared domain interface

**Files:** Modify `scenes/bridge/ws_client.gd`, `domain_store.gd`, `autoload/GameEvents.gd`, dialogue/domain panels and scenes; add focused shared view/controller helpers if needed; update Godot test scenes, Python real-client fake-provider fixtures and `scripts/run_headless.py` if adding a gate.

**Interfaces:** Consume Task 5's exact status/setup packets through correlated request helpers; reuse existing domain APIs and store. One domain draft/generation/pending request/results/read cursor; one visible composer. Extras continue using conversation store. Shared view state belongs to the domain store, not copied conversation histories.

- [x] Add failing real-tree Godot tests for approach-only status, Prepare/Let's work/Send/Stop states, Enter never starting implicitly, editable pending draft, one Run across pane switches, result attribution after switching Core representatives, return/replay once, idle/background Stop and Escape backgrounding.
- [x] Confirm missing behavior fails; implement contextual controls in existing dialogue style. Resolve bindings from bridge status, never scene/dept inference. Share lifecycle view coordination rather than duplicating deferred background/refocus races.
- [x] Handle status/setup reconnect/late/error packets and project changes without stealing focus or admitting stale work. Preserve scrolling, geometry, keyboard selection, movement, unsaved memory and uncertain-outcome recovery. Use an explicit extra fixture for independent conversation.
- [x] Run Godot import, all existing headless scenes, and real Godot/Python fake-provider integrations; require positive nonzero check markers and no script/load errors. Run affected Python tests; expect pass.
- [x] Commit `feat(PLZG-289): run department work from character dialogue`.

## Task 8: Acceptance runners, complete verification and handoff

**Files:** Update `scripts/m12_live.py`, `scripts/m12_stages.py`, corresponding runner/evidence tests, `bridge/tool_guard_acceptance.json`, new bounded evidence artifacts, `QUICKSTART.md`, `bridge/PROTOCOL.md`, indexes/changelog and plan checkboxes.

**Interfaces:** Exercise the same typed operations and real NPC controls as Tasks 3–7. Real probe reports include exact source/runtime/mode/auth/lifecycle; previous failed and successful evidence stays historical. Current desktop checklist distinguishes owner laptop acceptance from automated cloud checks.

- [x] Add/update runner tests for typed Chief setup, explicit Core start, working dialogue, explicit extra conversation, project/shared-memory identity and mode selection. Run them before changing runner code, then implement and pass.
- [x] Run full Python suite, Black/Flake8, canonical data check, spec/delivery validators, Godot import and all headless/integration gates. Investigate regressions; record real counts/output and environment versions.

Offline handoff precedes paid acceptance: settle task, whole-branch and repository
PR/CI review first, including any review changes to bound sources. The controller
then runs the deliberate paid probes and returns artifacts for final evidence/docs.
`READY_FOR_LIVE` means offline readiness only; do not merge with acceptance pending.

Recorded outcomes: corrective offline checks at `6917d73` passed 1,849 tests
plus 118 subtests in 161.85s, with required pinned Godot and zero skips; all eight
headless gates passed. Fresh ten-source guard matrices passed **29/29 in both
modes at `ba5599b`**, after review/CI. The controller validated actual runtime
against both reports before publication and committed unchanged evidence at
`a582f11`. The selected **`dontAsk` Linux API-key Godot/plain-client flow passed
at clean `a582f11`**, with three clean lifetimes, all phase checks true and all
44 executed-source hashes verified. The [guard ledger](../../../specs/evidence/m12-character-guard-attempts-2026-10-22.json)
and [live ledger](../../../specs/evidence/m12-character-live-attempts-2026-10-22.json)
preserve every attempt, including the earlier failed live proof, historical 58
guard passes and old activation object. Neither prior proof nor source hashes
were restamped. Owner laptop/native OAuth/desktop checks remain open.

- [x] Run one deliberate bounded real guard probe for each permission mode against final source, recording all outcomes. No automatic paid retries. Publish acceptance only from passing mode-bound observations; if blocked, preserve fail-closed behavior and report the precise blocker.
- [x] Run bounded real Godot/plain-client acceptance against final code if guard evidence passes; retain source/runtime/auth limits and failures. Do not claim local laptop/OAuth/UI feel acceptance from cloud runs.
- [x] Update the owner checklist and completion claims to recorded cloud scope; retain unchecked laptop/native OAuth/desktop items.
- [x] After final review and controller probes, record actual outcomes and commit final evidence/docs. No paid provider invocation occurs in the recording worker.
- [ ] Controller pushes the final evidence/docs after fresh review and completes repository delivery. No push or merge is claimed by the local evidence commit.

## Review and delivery

Each task receives a fresh specification/code-quality reviewer before dependent implementation. Keep task briefs, reports, diff packages and a progress ledger in ignored `.superpowers/sdd/m12-character-domains/`. Use existing pinned `/workspace/10110TasteslikegoodPlaza/.venv/bin/python` in this execution environment; commands in product docs stay environment-neutral.

After tasks, review the whole branch, fix material findings, verify covering gates and open a PR into `dev` linked to PLZG-289. Follow the repository review policy; do not merge unresolved failures or claim M12 laptop acceptance. Apply the normal D-031 dev PR checks, review and agent merge policy; the D-037 owner exception covered the historical 2026-10-18 runtime-path correction. Owner laptop/native OAuth/desktop acceptance remains open; recorded cloud acceptance does not close those checks or claim merge/milestone completion.
