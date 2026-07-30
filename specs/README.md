---
doc_id: SPECS-INDEX
title: specs/ — development process index
tier: 4
authority: summary
status: ACTIVE
doc_set_version: 0.2.9
last_updated: 2026-05
owner: adamtasteslikegood
derives_from: [META-SPEC]
---

# specs/

Development-process specifications for **10110 TastesLikegood Plaza** — the *how* and *when*. Files here describe what is being worked on, in what order, against which milestone, and under which rules.

For design-and-reference docs (the *what* and *why*) see [`../docs/`](../docs/README.md).

## What's here

| File | Purpose |
|---|---|
| [`meta/`](meta/README.md) | **Start here.** The layer above the specs: which document wins, who may decide what, every locked decision, and the CI gate that enforces it. |
| [`aligned-spec-v0.2.5.md`](aligned-spec-v0.2.5.md) | Research input, `status: SUPERSEDED`. Its normative content was promoted into [`meta/`](meta/README.md); its §01.3 scene spine was a reconstruction that contradicts the real storyboard. Retained for findings, the Document A bridge architecture, the Document B taxonomy, and rationale worth citing. |
| [`roadmap.md`](roadmap.md) | Work plan. M1 → M8 milestones. The **structure** (critical path **M1 → M4 → M8**) is still authoritative; the **3D-specific node names in milestone bodies are deprecated** — see the promoted 2.5D design for current implementation details. |
| [`task-tracker.md`](task-tracker.md) | Working checklist across all phases. `[ ]` todo, `[~]` in progress, `[x]` done. Same deprecation caveat as `roadmap.md` for 3D-specific task wording. |
| [`branching-strategy.md`](branching-strategy.md) | Branch protection rules, required status checks, CODEOWNERS gating. Intended policy — some referenced workflows don't exist yet. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the everyday flow. |

## Critical path

The proof-of-concept hinges on three milestones — if a change risks any of these, it should be flagged:

- **M1** — Godot 4 project + player can navigate the world.
- **M4** — Proximity-triggered dialogue panel populated from `AgentRegistry`.
- **M8** — Player question → WebSocket bridge → real `claude @agent-name` invocation → response rendered with a typewriter effect.

Everything else is deferrable. Details in [`roadmap.md`](roadmap.md).

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

*Last updated: May 2026*
