---
doc_id: M12-CHARACTER-DOMAIN-AMENDMENT
title: M12 amendment — Working characters, shared context and permission control
tier: 2
authority: implementation
status: ACTIVE
doc_set_version: 0.2.18
last_updated: 2026-10
owner: adamtasteslikegood
derives_from: [STORYBOARD-W1, AGENT-DIRECTORY, DESIGN-25D, PLATFORM-DECISIONS, M12-DOMAIN-EXECUTION-DESIGN]
supersedes: []
enforcement: intended
gates: [Validate Specs:live]
weakest_claim: The amendment is implemented with offline and Linux API-key cloud guard/live evidence; owner laptop/native OAuth/desktop acceptance remains open, and amendment merge is not claimed.
---

# M12 amendment — Working characters, shared context and permission control

**Talking to a working character is the player's interface to real domain work.**

## 1. Owner intent and approval state

The owner clarified that the Systems Architect is a working representative of the
Core domain. Approaching that character must retain the NPC dialogue interface,
backed by domain execution. The owner selected this interface explicitly and
authorized contextual Start/Run controls: the intended experience is a character
conversation in a classic 2D RPG, in the spirit of older Final Fantasy or Zelda.
This changes the interaction, not the existing narrative beats or art direction.

The owner identified the source of drift: synchronous versus asynchronous is an
execution property, not a classification of NPCs. Every named **agent** NPC belongs
to a department domain. Department membership and its color come from the Agent
Directory and the categories in the Claude-Code-Tresor submodule. A department is
represented by a room now and may later occupy a floor or group of rooms. Each
department owns one execution worktree within the selected project.

The conversation engine remains useful and capable. It serves story/onboarding
characters outside the working-agent domains. They can remain in the world after
their introduction, aware of the Plaza and project, without joining active work.
They may have names; membership in the agent catalog, not having a character name,
distinguishes a working agent. Personality and intelligence do not depend on tools.

Storyboard, map and tutorial progression should grow with the bridge's real
managed-agent capabilities. The first additional department behind a locked door
must obtain its own working environment before its agents perform work. Later concurrency and
sandbox capabilities can support later tutorials, rooms and floors.

The owner also requested two categories of injected context: game/storyboard
awareness and work/project awareness, including orientation before Git exists.
One user owns one installation and its settings/environment. One main repository
defines a project; monorepos and their submodules do not become separate project
bindings. The existing three memory files remain scoped to that project.

The owner permits Claude Code's permission bypass behind a boolean JSON setting
with an environment override. Explicit Start/Run, walking-away backgrounding,
Chief Architect bootstrap, dedicated worktrees and memory checks remain.

**Owner-approved, 2026-10-22:** the owner approved the revised written specification
at `eadb0b4` with “ok, build it”. This ratifies the detailed design and authorizes
implementation; it does not establish runtime completion or acceptance.

The amendment is implemented with offline and Linux API-key cloud guard/live evidence; owner laptop/native OAuth/desktop acceptance remains open, and amendment merge is not claimed.
Recorded cloud evidence shows fresh ten-source guards passing 29/29 in both modes at `ba5599b` and the
selected `dontAsk` Linux API-key Godot/plain-client flow passing at clean
`a582f11`; see the [guard and live records](../../../QUICKSTART.md#m12-live-evidence-and-desktop-checks).
This observational status does not change the design or the historical approval
fact above. The implementation plan is registered and authorized for execution. Tracking remains
[PLZG-289](https://tasteslikegood.atlassian.net/browse/PLZG-289).

## 2. Verified baseline and evidence limits

Baseline: `origin/dev` at `267d73b87da0235f8f6d37deb957f6c48baacab7`, inspected
2026-10-22 UTC. M12 implementation was merged in PR #357. Its existing spec and
plan describe the implementation already delivered; this document amends it.

- Every current NPC dialogue submits the legacy conversation request. The
  separate domain pane submits typed domain commands. Conversation deliberately
  enables no tools; domain execution enables Read, Edit and Bash.
- Systems Architect and Security Auditor both belong to Core. Existing domain
  sessions are keyed by domain, and each Run can supply a different agent
  definition. Agent-to-domain membership is not currently checked by the bridge.
- Current workspace preparation uses one project-global execution worktree and
  ownership record. That is an implementation limitation to change: one worktree
  must belong to each department, rather than departments borrowing one another's.
- Chief setup currently enters through the NPC conversation handler. Domain
  Start itself requires a ready project. Routing changes must preserve a setup
  path that works before a domain can start.
- Ready-project turns receive TODO/HANDOFF/PROGRESS. No common storyboard,
  installation-guidance or project-instruction loader exists. SDK filesystem
  settings are disabled; native authentication does not enable instruction files.
- Domain permissions currently use `dontAsk`. The installed SDK supports
  `bypassPermissions`, which emits `--permission-mode bypassPermissions`, the
  SDK equivalent of `--dangerously-skip-permissions`.

The owner reported local API-key and OAuth operation. The separately uploaded
[PR #361 diagnostic archive](https://tasteslikegood.atlassian.net/wiki/spaces/PLZA/pages/101908482)
records the malformed listing reply as a **conversation** response, includes
failed domain controls, and has `WORKSPACE_ROOT_DIR=null` in its latest manifest.
The committed config snapshot had `../`; editing the file while the bridge was
running explains how those states can differ, but is not independently proven
as the cause of every failure. Configuration is read at startup. These snapshots
do not establish a successful domain tool invocation or completed acceptance.

## 3. Chosen approach and boundaries

Use the existing asynchronous domain lifecycle and store behind NPC dialogue.
The domain pane remains a secondary view of the same state. This preserves the
character interaction while retaining M12's request correlation and replay.

Two alternatives were considered: making the separate domain pane the main
interaction was declined by the owner; adding tools to synchronous conversation
would create a second work lifecycle with different ownership and cancellation.
Neither is the selected design.

This amendment covers department/domain identity, ownership of worktrees by
department, routing, contextual dialogue controls, shared context and the
permission switch. The first playable slice remains Core. The per-department
ownership model is required now so introducing the second color does not require
replacing a project-global workspace model.

M13 still owns richer local application persistence. M14 owns verified parallel
execution capacity and stronger isolation beyond Git worktrees; M15 owns hosted
durability/ownership, with no provider selected. Minimal per-department worktree
provisioning is part of this M12 correction. Their sequencing may be coordinated
with the next department unlock; this amendment does not announce a released second
department, queue, sandbox or concurrent-agent capability.

## 4. Player interaction

Keep the existing dialogue panel, character identity, portrait, text history,
draft editing, scrolling and keyboard focus behavior. Work actions appear as
contextual dialogue choices, without requiring players to select an engine.
The labels below define behavior; they fit the current visual style.

| State | Dialogue behavior and available action |
|---|---|
| Approach a character | Open its view and obtain status. Approach alone starts no model task. |
| Project needs preparation | Other characters refer the player to the Chief Architect. The Chief offers **Prepare this project**. |
| Project ready, working domain inactive | **Let's work** explicitly prepares its worktree if needed and starts/reserves the domain. Show the existing draft; Start does not submit it. |
| Working domain active and idle | **Send** submits the typed message as an explicit Run. Questions and executable tasks use the same working session. **Stop work** releases the reserved session even after its last task has finished. |
| Work running | Show the character's working state; preserve draft editing, disable duplicate submission, offer **Stop work**. |
| Player walks away | Close the local dialogue and background already-started work. Do not stop or restart it. |
| Player returns | Refocus, show unread results once, and allow continuation in the same domain session. |
| Stop requested | Show stopping/uncertain state until workspace release is confirmed. |
| Conversation-backed story/tutorial character outside agent domains | Ordinary contextual character conversation, without domain-work controls or tools; remains available after its introduction. |

Keyboard submission follows the currently displayed Send action. It must not
silently activate an inactive domain. Escape closes/backgrounds the interaction;
it does not mean Stop. The UI should explain blocked actions in character-facing
language, with technical details available in diagnostic status.

Stop/release remains available whenever a session owns the workspace, including
idle and background states; it is not conditional on an in-flight task. Uncertain
ownership exposes the existing status/refocus recovery and Stop controls. Closing
the dialogue never releases the reservation, and the secondary pane is not
required to free an idle workspace.

The dialogue and domain pane share one generation, draft, pending request,
results and read cursor in the existing domain store. They never copy a result
into a separate conversation history or independently submit the same Run.
Showing one surface hides the competing composer. Replay does not execute work.

## 5. Agent routing, roles and domain ownership

### Department identity is the domain identity

The canonical relationship is:

```text
Selected project / main repository
  Core department/domain — canonical color — room(s) — Core worktree
    Systems Architect, Security Auditor, other Core agents
  Next department/domain — its color — unlocked room(s) — its own worktree
    Agents assigned to that category in the Agent Directory
  Conversation-backed story/tutorial characters — no department worktree
```

Use stable category/department IDs for bindings and worktree ownership, not raw
hex colors or room names. Colors and locations are the player's representation
of the taxonomy. Existing D-017 categories and colors remain canonical; examples
of job titles do not silently create or rename departments. A character can walk
outside its department's room without changing its domain or worktree. More rooms
or a floor for one department do not create additional domains/worktrees.

The bridge owns a UI-independent binding resolved from its committed store. Every
agent-catalog member has `execution_kind: working` and its validated category as
domain. Conversation-backed story/tutorial characters are registered outside that catalog
with `execution_kind: extra` and no executable domain binding. They cannot shadow
an agent ID or reclassify a catalog agent as an extra. Build/sync checks reconcile
the bridge's committed metadata and generated presentation data with the canonical
submodule/category curation, without reading the submodule at runtime (D-029).
Narrative tool claims do not determine routing.

A typed `agent_status` operation takes `agent_id` and `request_id`, returning
the resolved execution kind, domain ID where applicable, actual capabilities,
project readiness and that domain's workspace state. It makes no provider call
or provisioning change. Godot and plain clients use
this binding; NPC scenes continue storing only `agent_id` under D-016. Generated
agent presentation data remains generated, with consistency checks against the
bridge binding rather than a second hand-maintained routing table.

The server validates the selected agent's membership for every domain Run.
Legacy conversation requests for working agents return a correlated
`domain_required` response with the binding and required action. They must not
silently execute through conversation. Extras retain the conversation protocol.
Missing/invalid bindings fail explicitly; engine fallback is not recovery.

Ownership remains **per domain**, not per rendered character. Architect and
Security Auditor share Core's domain context. At idle, the player can address
either representative; the next Run captures its agent ID and role definition.
Every task/result retains its originating representative so the UI never
attributes the Architect's unfinished task to the Auditor. An in-flight role
does not change because another character was approached. The shared history is
shown as Core work with speaker attribution; it is not private per-agent memory.

### One worktree per project and department

Key execution-workspace identity, ownership records and reservations by
`(project_id, domain_id)`. Prepare a department's worktree when it is enabled and
first explicitly started; reuse its valid worktree on later sessions. Different
departments never borrow the same execution path, branch or reservation. Agents
within one department share its worktree and serialize work there. A second Run
in the same domain returns `domain_busy`; no implicit queue is added.

Use the existing per-project managed-worktree parent, with new department paths
`<managed-project-parent>/<domain_id>/execution` and branches
`plaza/workspace-<project_id>-<domain_id>`. Store validated ownership under
`<git-common-dir>/plaza/workspaces/<domain_id>.json`. Directory names alone never
establish ownership. Perform provisioning/metadata changes under a short common
project lock; hold execution reservations per worktree for the session lifetime.

For an existing valid M12 worktree, adopt it as Core's worktree in place after
confirming there is no live or uncertain owner and acquiring its existing
reservation for the migration. Preserve its legacy path, branch,
workspace identity, commits and uncommitted edits in the versioned Core record;
do not move, reset or recreate it just to match the new naming convention. Record
the legacy metadata as migrated so old single-worktree clients reject reuse.
Ambiguous, incomplete or conflicting adoption requires explicit recovery; it
never silently selects a different tree. Do not migrate a running session.

Project guidance and TODO/HANDOFF/PROGRESS remain **one project-scoped set**,
shared through the existing serialized memory store. Include domain, agent and
workspace identity in turn records; a department is not a separate project and
must not receive a forked copy of project memory.

The initial Core-only release may retain a single execution-capacity limit.
Report a capacity limit separately from a worktree conflict; it must not mean
another department owns Core's worktree. Before enabling a second department,
prove its own provisioning, readiness, identity, reservations and result routing.
Parallel execution is advertised only when tested at the supported capacity.
Per-agent private SDK sessions and finer sandbox allocations remain later work;
the department worktree boundary does not decide those future session models.

### Progression follows supported work

The bridge reports supported domain capabilities and per-domain readiness using
neutral status data. Godot maps that information plus earned tutorial/task
completion to the relevant door or room; the bridge performs no map/rendering or
door-unlock logic. Plain clients use the same execution contract.

D-009's earned unlocks remain: execution capability is an additional prerequisite,
not an automatic reward. The existing first department expansion is Engineering
at SB-08. Preserve its arrival/access introduction and SB-09's subsequent first
task-delegation beat. Verify that Engineering can actually execute in its own
worktree before releasing its access; the player need not perform a new delegation
inside SB-08. A supported department with an unprepared worktree can unlock:
its first explicit Start prepares the worktree before any Run. Do not require a
worktree that can only be prepared by approaching a character behind that door.
Later story/map expansion can introduce tested persistence, concurrent sessions
or stronger sandboxes as they become available. No invented release dates or new
narrative beats are implied. Story/tutorial characters remain available for
orientation alongside that work without entering the work queue.

## 6. Chief Architect before repository readiness

Extract the existing preparation interaction from the conversation-only entry
point. A typed `project_setup` operation carries `agent_id`, `request_id` and the
player's setup intent. Non-Chief agents return the existing referral. The Chief
reviews the exact inspected proposal using the existing tools-disabled reviewer;
the bridge applies only the approved initialization operations.

Expose setup progress, denial and readiness through the same NPC dialogue.
Record this as setup activity, not an ordinary extras conversation or a completed
domain task. The player's intent informs orientation but cannot enlarge the
approved file allowlist. Chief confirmation remains sufficient: no second owner
prompt is added. New repositories use `main`, then follow the same preparation
rules as existing repositories. Project readiness covers the configured repository
and shared memory; each domain additionally requires its own validated execution
worktree and reservation before work. Explicit Start prepares/reuses that domain's
worktree and establishes its readiness before admitting a Run. Chief setup does
not eagerly create worktrees for every catalog department.

No selected root produces clear configuration guidance. No Git/worktree/memory
yet is an explicit onboarding state, not fictitious empty project history.
Declined or failed setup requires a new explicit preparation action, with no
automatic retry. All model tool entry points retain readiness enforcement.

## 7. Two categories of context

A shared bridge context composer supplies NPC extras, working-domain turns and
Chief setup. It treats narrative text as application context and never reads
Godot scenes, nodes or HUD state. Plain clients use the same contract under
D-005. The exact enabled tools and readiness facts come from runtime state.

### Game/storyboard awareness

Ship a concise Plaza brief derived from `STORYBOARD-W1`, particularly SB-05,
SB-06, SB-08 and SB-14: the player's role, the office premise, character
relationships, Chief preparation, department progression and the work/return
loop. Do not invent new story beats. Combine that brief with the selected
character role, canonical department membership where applicable and current
semantic interaction state. Descriptive color/location context can come from
the committed narrative brief; execution and unlock eligibility use stable
domain IDs and verified capabilities, never inferred scenery. Extras receive
this awareness too; no model downgrade is part of this amendment. D-010's
scripted navigation assistant remains scripted; adding model-backed story
characters does not silently convert every tutorial entity into an LLM session.

### Work/project awareness

Compose these distinct layers, labeled by source and scope:

1. Installation workflow baseline and the single owner's optional preferences.
   These exist before any repository has been prepared.
2. Optional guidance from the selected project's main root: purpose,
   architecture, build/test commands, conventions and source-of-truth documents.
3. Bridge-observed facts: configured source root, selected domain's actual
   execution worktree/CWD and branch (or explicitly not yet prepared), project
   and domain readiness, active representative, supported execution capacity,
   tool inventory and effective permission mode. Never infer these from an
   agent definition or substitute another department's workspace.
4. The current player message and, when ready, the latest bounded
   TODO/HANDOFF/PROGRESS snapshot as prior continuity data.

Prior memory is not instruction authority or an automatic task queue. Current
runtime capabilities override generic claims in role templates. Neither guidance
nor narrative text can bypass bridge-enforced setup/readiness/ownership rules.
The current player message defines the requested work within those capabilities.

### Sources, configuration and scope

| Configuration key | Default | Behavior |
|---|---|---|
| `INSTALL_CONTEXT_DIR` | `../.local/plaza-context` | Selected-config-relative directory containing optional `GAME_CONTEXT.md` and `WORK_CONTEXT.md` for this installation's owner. |
| `PROJECT_GUIDANCE_FILE` | `PLAZA_AGENTS.md` | Relative path inside the configured main project root. The owner may explicitly select `AGENTS.md`, `CLAUDE.md` or `CLAUDE.local.md` instead. |

Both use the existing `PLAZA_` environment override convention and restart-based
configuration snapshots. Do not concatenate every instruction-file convention or
enable ambient Claude settings/hooks/plugins to obtain guidance text. Keep SDK
settings isolation. No instruction files are automatically written into projects.

Read project guidance from the configured main root even before Git exists;
identify that source separately from the execution worktree. Do not search parent
directories, submodules or unrelated repositories for alternative guidance.
Reject absolute/traversing guidance paths and symlinks/nonregular files. Missing
default `PLAZA_AGENTS.md` means optional guidance is absent; a missing explicitly
selected alternative, or an unreadable/invalid present file, returns
`context_unavailable` for that turn instead of silently dropping instructions.
Missing optional installation files use the shipped baseline. Nothing creates
global project memory or copies another project's instructions.

Bound shipped game/work briefs and each optional installation file to 8 KiB
UTF-8 each, and project guidance to 32 KiB: at most 64 KiB of these guidance
sources. Bound runtime-fact serialization to 4 KiB. Existing role/history/memory
bounds remain separate. Oversized or malformed files produce a specific context
error without overwriting them. Read files afresh per admitted turn and mark the
current source revisions; a connected domain must not treat an earlier packet
as the current capability or guidance snapshot.

Record source identities, revisions, readiness and permission mode in diagnostic
metadata, not complete instruction-file bodies. Keep existing transcript
privacy/retention behavior. One main repo defines the project; submodules stay
inside its guidance and memory boundary.

## 8. Owner-controlled permission bypass

Add `DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS`, a strict JSON boolean defaulting to
`false`. `PLAZA_DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS=true` or `false` overrides the
selected JSON. Invalid types fail configuration; truthy strings are not accepted.
The effective value is included in the run manifest and changes after restart.

| Value | Domain SDK permission mode |
|---|---|
| `false` | `dontAsk`: retain preapproved-tool behavior; other permissions are denied without interactive prompts. |
| `true` | `bypassPermissions`: use the SDK equivalent of `--dangerously-skip-permissions`. |

Do not pass conflicting duplicate CLI flags. The switch changes ordinary Claude
permission handling, not tool inventory. Domains still expose Read/Edit/Bash;
extras and the Chief proposal reviewer remain tools-disabled. No extra user
confirmation is added when the owner has selected the setting.

Keep the mandatory PreToolUse readiness hook, guarded transport, worktree CWD,
workspace reservation, memory checks, and configured turn/budget caps in both
modes. The SDK documents PreToolUse as the appropriate gate when bypass mode
skips `can_use_tool`; acceptance must still demonstrate real nonexecution when
that hook denies or fails. The hook must not turn an error into an allow.

`domain_sdk.py` is fingerprinted by the existing runtime acceptance mechanism.
Its old manifest cannot certify changed source or a newly enabled mode. Extend
the evidence schema/validator to bind permission mode explicitly and retain
verified results for both modes. Probe configuration must select its mode
explicitly instead of silently inheriting operator overrides. Actual CLI
coverage must include successful approved work, denied-tool nonexecution,
hook-error/timeout handling and clean cancellation in each mode. Keep the
existing deliberate-run/no-automatic-paid-retry policy.

## 9. Components and request flow

- Agent binding resolver: validates role kind/domain and reports capabilities;
  consumes committed agent metadata, independent of the frontend.
- Context composer: supplies the two context categories and explicit source
  revisions to extras, setup and domains; consumes config, readiness and memory.
- Project preparation route: reuses the existing inspected proposal/reviewer
  and establishes project readiness without requiring a domain session first.
- Department workspace registry: resolves `(project_id, domain_id)`, provisions
  or adopts a worktree under the appropriate locks, and reports per-domain
  readiness. Project memory remains shared; session reservations remain local
  to each execution worktree. Capacity is a separate admission constraint.
- Domain manager/SDK owner: retains lifecycle, lease and request ownership;
  validates agent binding and captures the representative/context per Run.
- Godot interaction controller: chooses extras or working presentation from
  `agent_status`, and lets dialogue/domain pane share the existing domain store.
  The progression controller combines earned tasks with reported department
  capabilities/readiness when the corresponding unlock slice is delivered.

Working flow: approach → agent status → project preparation if required → explicit
Start with department worktree preparation/reservation → explicit Send/Run →
ready/context snapshot → SDK execution in that department's worktree → one
correlated terminal and project-memory checkpoint → shared display/replay. Leaving
only changes foreground/background state. Extras use status/context followed by the
existing bounded conversation call. A CLI can exercise all service operations
without rendering concepts in the bridge.

## 10. Failure behavior and acceptance

Retain existing connection-generation checks, uncertain-outcome handling,
bounded replay, unsaved-memory state, cancellation ownership and confirmed
release. Surface a missing project, busy domain/workspace, capacity limit,
invalid binding, context failure or provider failure in the active character
interface. Do not automatically retry a task or silently route it to another
engine. Explicit player retries remain available after the prior outcome is
settled. Preserve usable malformed model text for diagnosis, while showing that
it is not verified tool output.

Required checks for implementation:

- Real Godot dialogue and plain-client flow both route working agents to domain;
  extras remain contextual, tools-disabled and responsive during work.
  Use an explicitly declared test extra when the production scene has none;
  do not relabel either existing Core working character to satisfy this check.
- Approach/Start do not execute a queued draft. One Send from either surface
  produces exactly one Run, terminal and memory checkpoint. Return/replay never
  executes. Scroll, focus, Escape and input controls remain usable.
  Stop from idle/background dialogue releases the workspace after confirmation,
  freeing that domain's reservation and its capacity slot without opening the
  secondary pane. Another department always starts in its own worktree.
- Architect and Auditor share Core state, validate membership, retain per-result
  attribution and cannot change an in-flight task's representative.
- Catalog/category bindings agree across committed bridge metadata and generated
  presentation data. Story extras cannot shadow catalog IDs. Moving a character
  between rooms does not change its department, worktree or session.
- A two-department service fixture proves distinct paths, branches, ownership
  records and reservations, with reuse on restart. Sequential execution at
  capacity one is sufficient for this foundation check; a capacity refusal must
  be distinct from workspace contention. Same-department work stays serialized;
  wrong-department readiness cannot authorize a tool call. No live concurrency
  or in-game second-department delivery is claimed by this fixture.
- Legacy Core adoption preserves dirty files, commits, branch, identity and all
  three project notes. Live/uncertain owners and partial migrations block safely;
  an old singleton client cannot claim the migrated worktree. Department turns
  write attributed checkpoints to the same serialized project memory store.
- Empty/non-Git setup remains reachable through the Chief dialogue and equivalent
  plain-client operation, producing `main` and project memory, followed by the
  selected department's worktree/readiness on explicit Start before work.
- Both context categories appear for extras, work and pre-repo Chief review;
  actual capabilities override template claims. Optional/missing/invalid guidance,
  revision refresh and project A/B isolation behave as specified.
- Boolean config/environment precedence, startup snapshots, actual SDK arguments,
  and mode-bound live guard evidence are verified for both permission values.
- Laptop acceptance starts with a fresh manifest showing the intended workspace,
  then proves an actual domain tool result in the dedicated worktree. Record
  tested source/runtime, auth category and lifecycle outcome; keep earlier owner
  observations and archived diagnostic failures separate.

No new acceptance pass is claimed by this document. The remaining original M12
desktop checks continue, with working-character checks using the domain engine
and the independent-conversation check explicitly using an extra.

Before shipping the second department's playable unlock, additionally demonstrate
Engineering execution in its own worktree and verify that earned progression and
execution capability are both required. Neither a reported capability alone nor
an earned task with an unsupported runtime opens the door. An unprepared worktree
must remain preparable through Start after access; it must not create an unlock
deadlock. Keep SB-08's introduction and SB-09's delegation order. These are release
dependencies for that M6/story slice, not claims that M5/M6 are delivered by this
amendment. Any advertised parallel capacity requires its own concurrent evidence.

## 11. Ratification and delivery

Ratified in doc set 0.2.18 following owner approval of `eadb0b4` on 2026-10-22
(“ok, build it”). `DESIGN-25D` D-033 now scopes synchronous conversation to extras;
`PLATFORM-DECISIONS` D-034 covers every catalog working character regardless of
presentation. D-038 now owns department worktrees within one configured project,
with safe legacy Core adoption, unchanged bootstrap/readiness and reservations.
D-006 remains superseded; D-039 remains one shared project-memory set.

The original M12 specification explicitly identifies amended sections; the roadmap
keeps M13 persistence, M14 broader concurrency/isolation and M15 hosted durability
separate. M6's Engineering unlock requires tested execution support without
changing SB-08 arrival or SB-09 delegation. No second playable department, sandbox,
concurrent capacity, runtime implementation or acceptance is delivered by ratification.

`SPEC-DRIVERS-025` §4.15 records the owner resolution. The registered
[implementation plan](../plans/2026-10-22-m12-character-domains.md) carries the
execution and verification breakdown; implementation and owner desktop/OAuth
acceptance remain separate from prior cloud API-key evidence.

*Last updated: October 2026*
