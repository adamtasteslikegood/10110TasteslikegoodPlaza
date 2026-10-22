---
doc_id: M12-CHARACTER-DOMAIN-AMENDMENT
title: M12 amendment — Working characters, shared context and permission control
tier: 2
authority: implementation
status: DRAFT
doc_set_version: 0.2.17
last_updated: 2026-10
owner: adamtasteslikegood
derives_from: [STORYBOARD-W1, DESIGN-25D, PLATFORM-DECISIONS, M12-DOMAIN-EXECUTION-DESIGN]
supersedes: []
enforcement: intended
gates: [Validate Specs:live]
weakest_claim: This amendment has no runtime implementation or completed acceptance evidence.
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

The conversation engine remains useful and capable. It serves gameplay extras,
with awareness of the Plaza and the selected project. A character's intelligence
or personality must not be inferred from whether it has filesystem tools.

The owner also requested two categories of injected context: game/storyboard
awareness and work/project awareness, including orientation before Git exists.
One user owns one installation and its settings/environment. One main repository
defines a project; monorepos and their submodules do not become separate project
bindings. The existing three memory files remain scoped to that project.

The owner permits Claude Code's permission bypass behind a boolean JSON setting
with an environment override. Explicit Start/Run, walking-away backgrounding,
Chief Architect bootstrap, the dedicated worktree and memory checks remain.

**Written-spec review is pending.** The interface choice and requirements above
are owner directions; the detailed design below is proposed for review.

This amendment has no runtime implementation or completed acceptance evidence.
Implementation planning follows written-spec approval. Tracking remains
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

This amendment covers routing, contextual dialogue controls, shared context and
the permission switch. M13 still owns richer local application persistence;
M14 owns independent concurrent workspaces and stronger execution isolation;
M15 owns hosted durability/ownership, with no provider selected. Their order may
still be reconsidered. This work does not add queues or concurrent worktrees.

## 4. Player interaction

Keep the existing dialogue panel, character identity, portrait, text history,
draft editing, scrolling and keyboard focus behavior. Work actions appear as
contextual dialogue choices, without requiring players to select an engine.
The labels below define behavior; they fit the current visual style.

| State | Dialogue behavior and available action |
|---|---|
| Approach a character | Open its view and obtain status. Approach alone starts no model task. |
| Project needs preparation | Other characters refer the player to the Chief Architect. The Chief offers **Prepare this project**. |
| Ready working domain, inactive | **Let's work** explicitly starts/reserves the domain. Show the existing draft; Start does not submit it. |
| Working domain active and idle | **Send** submits the typed message as an explicit Run. Questions and executable tasks use the same working session. **Stop work** releases the reserved session even after its last task has finished. |
| Work running | Show the character's working state; preserve draft editing, disable duplicate submission, offer **Stop work**. |
| Player walks away | Close the local dialogue and background already-started work. Do not stop or restart it. |
| Player returns | Refocus, show unread results once, and allow continuation in the same domain session. |
| Stop requested | Show stopping/uncertain state until workspace release is confirmed. |
| Gameplay extra | Ordinary contextual character conversation, without domain-work controls or tools. |

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

The bridge owns a UI-independent agent binding resolved from its committed agent
store. Existing directory agents default to `execution_kind: working`; their
validated category supplies the domain. Gameplay extras require an explicit
`execution_kind: extra` declaration and have no executable domain binding.
This is runtime metadata, separate from the definition's narrative tool claims.

A typed `agent_status` operation takes `agent_id` and `request_id`, returning
the resolved execution kind, domain ID where applicable, actual capabilities
and project readiness. It makes no provider call. Godot and plain clients use
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

M12 still has one reserved execution workspace and one in-flight Run. Another
domain reports `workspace_busy` until the owner domain releases it. A second Run
in the same domain reports `domain_busy`; it is not queued. Extras can converse
while work runs. Separate per-agent SDK contexts and simultaneous domains are
not introduced by this amendment.

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
prompt is added. New repositories use `main`, then enter normal worktree/memory
preparation. Domain Start becomes available after readiness succeeds.

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
SB-06 and SB-14: the player's role, the office premise, character relationships,
Chief preparation and the work/return loop. Do not invent new story beats.
Combine that brief with the selected character role and current semantic
interaction state. Extras receive this awareness too; no model downgrade is
part of this amendment.

### Work/project awareness

Compose these distinct layers, labeled by source and scope:

1. Installation workflow baseline and the single owner's optional preferences.
   These exist before any repository has been prepared.
2. Optional guidance from the selected project's main root: purpose,
   architecture, build/test commands, conventions and source-of-truth documents.
3. Bridge-observed facts: configured source root, actual execution worktree/CWD,
   branch, readiness stage, active domain/representative, tool inventory and
   effective permission mode. Never infer these from an agent definition.
4. The current player message and, when ready, the latest bounded
   TODO/HANDOFF/PROGRESS snapshot as prior continuity data.

Prior memory is not instruction authority or an automatic task queue. Current
runtime capabilities override generic claims in role templates. Neither guidance
nor narrative text can bypass bridge-enforced setup/readiness/ownership rules.
The current player message defines the requested work within those capabilities.

### Sources, configuration and scope

| Proposed key | Default | Behavior |
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
  and transitions to ready without requiring a domain session first.
- Domain manager/SDK owner: retains lifecycle, lease and request ownership;
  validates agent binding and captures the representative/context per Run.
- Godot interaction controller: chooses extras or working presentation from
  `agent_status`, and lets dialogue/domain pane share the existing domain store.

Working flow: approach → agent status → preparation if required → explicit Start
→ explicit Send/Run → ready/context snapshot → SDK execution in worktree → one
correlated terminal and memory checkpoint → shared display/replay. Leaving only
changes foreground/background state. Extras use status/context followed by the
existing bounded conversation call. A CLI can exercise all service operations
without rendering concepts in the bridge.

## 10. Failure behavior and acceptance

Retain existing connection-generation checks, uncertain-outcome handling,
bounded replay, unsaved-memory state, cancellation ownership and confirmed
release. Surface a missing project, busy domain/workspace, invalid binding,
context failure or provider failure in the active character interface. Do not
automatically retry a task or silently route it to another engine. Explicit player
retries remain available after the prior outcome is settled. Preserve usable malformed
model text for diagnosis, while showing that it is not verified tool output.

Required checks for implementation:

- Real Godot dialogue and plain-client flow both route working agents to domain;
  extras remain contextual, tools-disabled and responsive during work.
  Use an explicitly declared test extra when the production scene has none;
  do not relabel either existing Core working character to satisfy this check.
- Approach/Start do not execute a queued draft. One Send from either surface
  produces exactly one Run, terminal and memory checkpoint. Return/replay never
  executes. Scroll, focus, Escape and input controls remain usable.
  Stop from idle/background dialogue releases the workspace after confirmation,
  allowing another domain to start without opening the secondary pane.
- Architect and Auditor share Core state, validate membership, retain per-result
  attribution and cannot change an in-flight task's representative.
- Empty/non-Git setup remains reachable through the Chief dialogue and equivalent
  plain-client operation, producing `main`, worktree and memory before work.
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

## 11. Ratification and delivery

On written approval, update the entitled documents together before implementing:
D-033's synchronous NPC scope becomes extras conversation; D-034 owns working
character execution regardless of presentation. Amend original M12 sections on
NPC tool availability, independent conversations, frontend controls and ordinary
permission denials. Preserve D-038 readiness/bootstrap and D-039 project memory.
Register this amendment as active only at that point; retain the original spec
as historical implementation context with clear amended sections.

The pending reconciliation is indexed in `SPEC-DRIVERS-025` §4.15. This draft
does not silently rewrite ratified policy, change storyboard beats, or authorize
implementation by itself. After written-spec approval, produce the implementation
plan for review and execution-method selection through the Superpowers workflow.

*Last updated: October 2026*
