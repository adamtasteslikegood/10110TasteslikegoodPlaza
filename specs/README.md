# specs/

Development-process specifications for **10110 TastesLikegood Plaza** — the *how* and *when*. Files here describe what is being worked on, in what order, against which milestone, and under which rules.

For design-and-reference docs (the *what* and *why*) see [`../docs/`](../docs/README.md).

## What's here

| File | Purpose |
|---|---|
| [`roadmap.md`](roadmap.md) | **The work plan.** M1 → M8 milestones with effort estimates and GDScript dependencies. The critical path is **M1 → M4 → M8**. |
| [`task-tracker.md`](task-tracker.md) | Working checklist across all phases. `[ ]` todo, `[~]` in progress, `[x]` done. Mirrors Jira where possible. |
| [`branching-strategy.md`](branching-strategy.md) | Branch protection rules, required status checks, CODEOWNERS gating. Intended policy — some referenced workflows don't exist yet. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the everyday flow. |

## Critical path

The proof-of-concept hinges on three milestones — if a change risks any of these, it should be flagged:

- **M1** — Godot 4 project + player can navigate the world.
- **M4** — Proximity-triggered dialogue panel populated from `AgentRegistry`.
- **M8** — Player question → WebSocket bridge → real `claude @agent-name` invocation → response rendered with a typewriter effect.

Everything else is deferrable. Details in [`roadmap.md`](roadmap.md).

## When to add a file here

Add a file under `specs/` if it describes **active or upcoming work** — something a developer or agent picks up, executes, and marks done. Examples:

- A per-milestone spec when a milestone gets large enough to warrant its own file (e.g. `specs/milestones/M3.md`).
- A test plan tied to a specific PR or sprint.
- A migration spec for a one-off task.
- A new ADR's *implementation* checklist, when separate from the ADR itself (the ADR belongs in `docs/`).

If the doc is reference material that doesn't expire when the work ships — put it in [`../docs/`](../docs/README.md) instead.

## Conventions

- Track status inline with `[ ]` / `[~]` / `[x]` checkboxes so the file is grep-friendly.
- Cross-link Jira issues with the full key (`TO-27`, not `27`). The integration scripts at the repo root (`generate_report.py`, `post_to_confluence.py`) pull these.
- Date-stamp the bottom of each file with `*Last updated: <month> <year>*`.
- When a milestone is done, leave the spec in place as historical record — don't delete it. Mark it `[x] Done`.

*Last updated: May 2026*
