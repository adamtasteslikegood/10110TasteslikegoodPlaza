---
doc_id: SPECS-INDEX
title: specs/ — development process index
tier: 4
authority: summary
status: ACTIVE
last_updated: 2026-10
owner: adamtasteslikegood
governed: false  # exempt in specs/meta/doc-registry.json since PLZG-232; the keys above describe the file, nothing validates them
---

# specs/

Development-process specifications for **10110 TastesLikegood Plaza** — the *how* and *when*. Files here describe what is being worked on, in what order, against which milestone, and under which rules.

For design-and-reference docs (the *what* and *why*) see [`../docs/`](../docs/README.md).

## What's here

| File | Purpose |
|---|---|
| [`meta/`](meta/README.md) | **Start here.** The layer above the specs: which document wins, who may decide what, every locked decision, and the CI gate that enforces it. |
| [`aligned-spec-v0.2.5.md`](aligned-spec-v0.2.5.md) | Research input, `status: SUPERSEDED`. Its normative content was promoted into [`meta/`](meta/README.md); its §01.3 scene spine was a reconstruction that contradicts the real storyboard. Retained for findings, the Document A bridge architecture, the Document B taxonomy, and rationale worth citing. |
| [`roadmap.md`](roadmap.md) | Work plan. Preserves the **M1 → M4 → M8** prototype proof and sequences approved bridge-first **M9–M15** work. M9 is complete; M10/M11 are implemented with deterministic coverage; M11 desktop acceptance was recorded 2026-10-21; baseline M12 has deterministic/Linux evidence with desktop acceptance open. The 2026-10-22 character/domain correction is approved and ratified in 0.2.18; implementation has offline coverage, while fresh final-source guard/live and owner desktop acceptance remain pending. M13–M15 remain planned. M5/M6 remain deferred frontend milestones. |
| [`task-tracker.md`](task-tracker.md) | `HISTORICAL` — reference checklist from early planning. Progress state lives in `CLAUDE.md` and git history. |
| [`evidence/`](evidence/) | Machine-read evidence a sprint gate checks against the live board or tree — not governed documents and not narrative. `sprint-5-triage.json` is the Sprint 5 T2 record: the pre-triage baseline and one reviewed row per ticket, read by `scripts/sprint_5_gate.py t2`. `sprint-6-live-transcript.json` is Sprint 6's Gate B record, rewritten by every run of `scripts/sprint_6_live.py` that gets as far as asking the clients — a run that exits 2 (no credential, no dependencies, port in use, bridge not started, no Godot) leaves the previous file in place: the nonce, both clients' two turns, and every try. Its `owner_read` flag is the owner's to set. |
| [`branching-strategy.md`](branching-strategy.md) | Branch protection rules, required status checks, CODEOWNERS gating. Intended policy — some referenced workflows don't exist yet. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the everyday flow. |

The [2026-10-22 amendment offline verification](evidence/m12-character-offline-2026-10-22.json) records required-Godot Python/headless checks and exact tested source hashes. It explicitly records zero provider calls and stale production guard evidence; it is not runtime acceptance. Final fixes/reviews and fresh paid/owner evidence remain pending.

## Critical path

The completed proof-of-concept depends on three milestones — if a change risks any of these, it should be flagged:

- **M1** — Godot 4 project + player can navigate the world.
- **M4** — Proximity-triggered dialogue panel populated from `AgentRegistry`.
- **M8** — Historical completion: player question → WebSocket bridge → real Claude Messages API invocation → response rendered with a typewriter effect.

Current runtime follows `D-037`: Claude Code through Agent SDK by default, explicit
API-key-only Messages API compatibility, no automatic fallback. The separate
[cloud SDK recall evidence](evidence/npc-sdk-live-2026-10-18.json) does not advance
M11 desktop acceptance or M12–M15.

The next acceptance boundary is M11 desktop conversation controls, followed by
planned domain execution and durable workspace state.
See the [roadmap](roadmap.md) and the written
[bridge-first design](../docs/superpowers/specs/2026-10-18-bridge-first-platform-design.md)
for approved milestones and their implementation status.

## Before you add or edit anything here

Read [`meta/META-SPEC.md`](meta/META-SPEC.md). Every document in this folder
declares a tier and an authority in its frontmatter, and
`python3 scripts/validate_specs.py` (the `Validate Specs` CI job) fails the build
if a document is unregistered, mis-declared, or links to a file that does not
exist. `META-SPEC.md` §8 is the four-step checklist.

## When to add a file here

Add a file under `specs/` if it describes **active or upcoming work** — something a developer or agent picks up, executes, and marks done. Examples:

- A per-milestone spec when a milestone gets large enough to warrant its own file (e.g. `specs/milestones/M3.md`).
- A test plan tied to a specific PR or sprint.
- A migration spec for a one-off task.
- A new ADR's *implementation* checklist, when separate from the ADR itself (the ADR belongs in `docs/`).

If the doc is reference material that doesn't expire when the work ships — put it in [`../docs/`](../docs/README.md) instead.

## Conventions

- Track status inline with `[ ]` / `[~]` / `[x]` checkboxes so the file is grep-friendly.
- Cross-link Jira issues with the full key (`PLZG-27`, not `27`). `PLZG` is the delivery board — the older key it replaced is deprecated and must not be filed into. [`docs/delivery-coordinates.md`](../docs/delivery-coordinates.md) (`D-026`) owns every Atlassian identifier this repo uses; cite it rather than restating one here.
- Date-stamp the bottom of each file with `*Last updated: <month> <year>*`.
- When a milestone is done, leave the spec in place as historical record — don't delete it. Mark it `[x] Done`.

*Last updated: October 2026*
