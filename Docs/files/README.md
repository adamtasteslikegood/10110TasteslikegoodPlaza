---
doc_id: LEGACY-SIGNPOST
title: Docs/files — relocation signpost
tier: 4
authority: historical
status: HISTORICAL
doc_set_version: 0.2.10
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: []
---

# Important - about these files: 

## Not for Spec-Deriven Development - refecnce for concpets only..

These files are legacy first run planning.. Story board and the concept still mostly unchanged. Tast tracker and 3-d references are
deprociated for a 2.5-D UI and UI agnostic agent bridge layer.

---

**Where the files actually live now** (they were relocated in PR #5; this directory was left with only this note as a signpost):

| Original path | New path |
|---|---|
| `Docs/files/00_PROJECT_OVERVIEW.md` | folded into the top-level [`README.md`](../../README.md) |
| `Docs/files/01_WEEK1_STORYBOARD.md` | [`docs/storyboard-week1.md`](../../docs/storyboard-week1.md) — **still authoritative for narrative/concept** |
| `Docs/files/02_PROTOTYPE_ROADMAP.md` | [`specs/roadmap.md`](../../specs/roadmap.md) — **deprecated for 3D specifics** |
| `Docs/files/03_PM_TASK_TRACKER.md` | [`specs/task-tracker.md`](../../specs/task-tracker.md) — **deprecated for 3D specifics** |
| `Docs/files/04_QUICK_REFERENCE.md` | [`docs/quick-reference.md`](../../docs/quick-reference.md) |

**Where to go now:** [`specs/meta/`](../../specs/meta/README.md) is the layer that
decides which document wins — start at
[`META-SPEC.md`](../../specs/meta/META-SPEC.md).

`specs/aligned-spec-v0.2.5.md` was briefly described here as the source-of-truth
for spec details. It is now a **research input** (`status: SUPERSEDED`): its
normative content was promoted into `specs/meta/`, and its §01.3 scene spine was a
reconstruction that contradicts the real storyboard. See
[`specs/meta/concept-driver.md`](../../specs/meta/concept-driver.md) §4.
