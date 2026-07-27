---
doc_id: DOCS-INDEX
title: docs/ — design and reference index
tier: 4
authority: summary
status: ACTIVE
doc_set_version: 0.2.7
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [META-SPEC]
---

# docs/

Design and reference material for **10110 TastesLikegood Plaza** — the *what* and *why* of the project. Files here change slowly and describe what we're building, not how the work is sequenced.

For work-in-flight (milestones, task tracking, branching policy) see [`../specs/`](../specs/README.md).

**Which document wins?** [`../specs/meta/META-SPEC.md`](../specs/meta/META-SPEC.md)
answers that. Everything in this folder declares a tier and an authority in its
frontmatter; `docs/storyboard-week1.md` is the sole origin of concept decisions and
`docs/designs/` is authoritative for how to build.

## What's here

| File | Purpose |
|---|---|
| [`designs/2.5D-RPG-Prototype.md`](designs/2.5D-RPG-Prototype.md) | **Active design.** Promoted CEO plan (2026-04-27) pivoting the prototype from 3D first-person to 2.5D top-down. |
| [`designs/platform-decisions.md`](designs/platform-decisions.md) | **Platform authority.** The decisions that outlive the current frontend — engine, bridge transport, agent data layer, licence, submodule and merge policy. Scope test: would it survive replacing the whole frontend? |
| [`storyboard-week1.md`](storyboard-week1.md) | **The concept source of truth.** Week 1 tutorial narrative beats, Day 0 through Days 4–5, dual-purpose: game story = real onboarding. Scenes are citable as `SB-01`–`SB-18`; the contract and index live in [`../specs/meta/concept-driver.md`](../specs/meta/concept-driver.md). Edits are concept changes and need human sign-off. |
| [`quick-reference.md`](quick-reference.md) | One-page summary: build order, autoload list, department table, key decisions. |
| [`agent-directory.md`](agent-directory.md) | Taxonomy of the 133 agent roles across nine departments plus Core. Source-of-truth for the department/color mapping (mirrored in the top-level `README.md`). |
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
