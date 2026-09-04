---
doc_id: META-INDEX
title: specs/meta — the layer above the specs
tier: 0
authority: summary
status: ACTIVE
doc_set_version: 0.2.13
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [META-SPEC]
supersedes: []
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: This folder governs every other document in the repo.
---

# `specs/meta/` — the layer above the specs

**Start here.** This folder governs every other document in the repo. It contains
no product decisions of its own — it decides who is allowed to decide, and makes
that answer machine-checkable.

## The files

| File | Read it when |
|---|---|
| [`META-SPEC.md`](META-SPEC.md) | You need to know **which document wins**, or you are about to edit a spec. The constitution: tiers, authority, conflict protocol, binding rules for agents. |
| [`concept-driver.md`](concept-driver.md) | You are touching story, characters, the world, or a tutorial beat. Names the sole concept origin and indexes every scene as `SB-nn`. |
| [`decision-register.md`](decision-register.md) | You need to cite why something is the way it is. Every locked decision, keyed `D-nnn`. |
| [`spec-drivers-v0.2.5.md`](spec-drivers-v0.2.5.md) | You want to know what this version must deliver, how work traces upward, or what is still in conflict. |
| [`spec-frontmatter.schema.json`](spec-frontmatter.schema.json) | You are adding a document and need the frontmatter contract. |
| [`doc-registry.json`](doc-registry.json) | You want the full list of governed documents and their declared authority. |

## The short version

```
tier 0  this folder            governs the doc set; decides nothing about the product
tier 1  docs/storyboard-week1  the ONLY origin of concept and narrative decisions
tier 2  docs/designs/*         how to build   ·   docs/agent-directory  taxonomy
        README.md              reconciles both axes for public consumption
tier 3  specs/roadmap, task-tracker, branching-strategy    sequencing only
tier 4  quick-reference, aligned-spec-v0.2.5, indexes      authoritative over nothing
```

Lower tier wins. Concept flows down from tier 1; implementation flows down from
tier 2; they are independent axes. Conflicts get **recorded**, never silently
reconciled — see [`spec-drivers-v0.2.5.md`](spec-drivers-v0.2.5.md) §4.

## Checking your work

```bash
python3 scripts/validate_specs.py
```

Stdlib only — no `pip install`. It reads its rules from
[`spec-frontmatter.schema.json`](spec-frontmatter.schema.json) and
[`doc-registry.json`](doc-registry.json), so the gate cannot drift from the
contract. It runs in CI as the `Validate Specs` job on every push and PR to `main`
and `dev`.

It will fail the build if a governed document is missing frontmatter, is not
registered, claims an authority the registry does not grant, links to a file that
does not exist, disagrees with the rest of the set about `doc_set_version`, or if a
scene id in the concept driver has no matching scene in the storyboard.

*Doc set version: 0.2.12 · Last updated: August 2026*
