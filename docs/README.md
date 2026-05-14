# docs/

Design and reference material for **10110 TastesLikegood Plaza** — the *what* and *why* of the project. Files here change slowly and describe what we're building, not how the work is sequenced.

For work-in-flight (milestones, task tracking, branching policy) see [`../specs/`](../specs/README.md).

## What's here

| File | Purpose |
|---|---|
| [`designs/2.5D-RPG-Prototype.md`](designs/2.5D-RPG-Prototype.md) | **Active design.** Promoted CEO plan (2026-04-27) pivoting the prototype from 3D first-person to 2.5D top-down. |
| [`storyboard-week1.md`](storyboard-week1.md) | Day 0 / Day 1 / Day 2 tutorial narrative beats. Dual-purpose: game story = real onboarding. |
| [`quick-reference.md`](quick-reference.md) | One-page summary: build order, autoload list, department table, key decisions. |
| [`agent-directory.md`](agent-directory.md) | Taxonomy of the 137+ agent roles across nine departments. Source-of-truth for the department/color mapping (mirrored in the top-level `README.md`). |
| [`assets/`](assets/) | `plaza_build_steps.html` and `plaza_godot_architecture.svg`. |

## When to add a file here

Add a file under `docs/` if it answers **"what is this project"** or **"how is this piece designed"** — and you expect it to stay roughly stable for weeks or months. Examples:

- A new ADR (Architecture Decision Record).
- A design doc for a feature whose shape is locked.
- A reference table or taxonomy.

If the doc instead tracks **active work**, lives or dies with a milestone, or changes every sprint — put it in [`../specs/`](../specs/README.md) instead.

## Conventions

- Drop numeric prefixes from filenames. Folder structure should convey order; lexicographic ordering is brittle.
- End each long doc with a `*Last updated: <month> <year>*` line so reviewers can spot stale material.
- Cross-link freely. Use relative paths so links survive directory moves.
- Don't propagate the `{{rolels}}` / `{{charactors}}` template placeholders left over from the upstream fork — clean them up locally when editing the section they're in.

*Last updated: May 2026*
