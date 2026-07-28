---
name: grill-with-specs
description: Stress-test a plan against this repo's governed doc set — the tier ladder in specs/meta/META-SPEC.md and the D-nnn decision register — using the grill-with-docs interview discipline. Use when asked to grill, interrogate, or pressure-test a plan or design here, or when a change touches specs/meta/, the decision register, or a LOCKED decision. Redirects grill-with-docs away from the CONTEXT.md + docs/adr/ layout this repo does not use.
---

# Grill with Specs

Run the `grill-with-docs` interview discipline against **this repo's governed doc set**
instead of the generic `CONTEXT.md` + `docs/adr/` layout it assumes.

## Read the upstream skill first

Read `grill-with-docs:grill-with-docs` for the interview itself — one question per turn,
a recommended answer with every question, explore the codebase rather than asking what
the codebase already answers, sharpen fuzzy terms, stress-test with concrete scenarios.

Everything below overrides its **paths, formats, and pre-flight**. Nothing below changes
how the interview runs.

## Path map

| `grill-with-docs` assumes | This repo uses |
|---|---|
| `CONTEXT.md` — one glossary file | No single glossary. Governance vocabulary is `specs/meta/META-SPEC.md` §2 (tier ladder, the `authority` values); concept terms and the scene ids `SB-01`–`SB-18` are `specs/meta/concept-driver.md` §3; per-document metadata is `specs/meta/doc-registry.json`. |
| `docs/adr/NNNN-slug.md` — one file per decision | `specs/meta/decision-register.md` — one file, tables of `D-nnn` rows, grouped by originating authority. |
| `context_md_linter.py`, `adr_scanner.py`, `glossary_code_consistency.py` | `python3 scripts/validate_specs.py` |

**Do not create `CONTEXT.md` or `docs/adr/`.** The upstream skill says to create them
lazily when the first term or decision lands; here that would fork the truth away from
`specs/meta/`, which is exactly what the register was built to stop. The three upstream
validators parse formats this repo does not use — running them produces noise, not signal.

## Pre-flight, before the first question

1. `python3 scripts/validate_specs.py` — stdlib only, and the same check CI runs as
   `Validate Specs`. It must pass first; grilling a plan against a doc set that does not
   validate wastes the session.
2. Read `specs/meta/spec-drivers-v0.2.5.md` §4, the open-conflict register. Entries there
   are *known* disagreements with a recorded resolution. Do not re-ask them as if fresh.
3. Read the plan's own citations. A plan that cites no `doc_id` fails binding rule §5.2
   before the interview starts — say so and ask for the authorising document.

## Questions this repo earns, on top of the upstream set

Ask these when the plan touches governed documents:

1. **Which tier owns this?** META-SPEC §2. Lower tier wins. A plan changing a tier-2
   design because a tier-3 roadmap disagrees has it backwards.
2. **Which `doc_id` is entitled to originate it?** §5.2 — uncited decisions are
   unauthorised, and the register's Origin column is where that gets stated.
3. **Does it contradict a `LOCKED` `D-nnn`?** If so the change is a reversal, not an
   edit, and needs its own justification.
4. **Does it change a `STORYBOARD-W1` beat?** §5.3 — adding structure is allowed,
   changing a beat needs explicit human sign-off. Never quietly.
5. **Does it risk M1 → M4 → M8?** §5.5 — say so explicitly and prominently if it does.
6. **Does it survive the swap test?** §5.1, citing `D-005`. If replacing the Godot frontend
   with a CLI harness would require a bridge change, the boundary is broken.

## Recording a decision

Nygard's three criteria still gate it — hard to reverse, surprising without context, the
result of a real trade-off. If any is missing, no register row. On top of those:

- Append a row to the section of `specs/meta/decision-register.md` matching the
  originating authority. Take the next free `D-nnn`; ids are never reused or renumbered.
- Fill **Origin** with a `doc_id` licensed to originate at the right tier. Only
  `constitution`, `concept`, `implementation`, and `taxonomy` may originate anything —
  `scripts/validate_specs.py` hard-fails a `decides:` list on a `derived`, `summary`,
  `research`, or `historical` document. A decision whose only origin is tier 4 is
  `PROPOSED`, not `LOCKED`.
- Status is one of `LOCKED` · `PROPOSED` · `DEFERRED` · `SUPERSEDED`.
- Bump `doc_set_version` and `last_updated` on every governed doc you touched, then
  re-run the validator.

That authority check is a coarse gate by design: it says whether an authority *may*
originate, never whether this particular decision falls inside its subject matter. A
tier-0 document deciding about documents is fine; deciding the product's architecture is
not, and no validator catches it. That is the interview's job — `D-005` sat mis-originated
in `META-SPEC` §5.1 through two green releases.

## Terminology edits

There is no `CONTEXT.md` to update inline, so a sharpened term goes to the document that
owns its axis: concept terms to `docs/storyboard-week1.md` (beats need sign-off),
implementation terms to `docs/designs/`, governance vocabulary to `specs/meta/META-SPEC.md`.
`README.md` reconciles and never decides.

## When two documents disagree

Follow META-SPEC §4 — **never silently reconcile.** Higher tier on the relevant axis wins;
patch the loser in the same change and say so in the commit body. Same tier, or the axis is
ambiguous: stop, add an entry to the open-conflict register with both sides stated fairly,
and raise it. An agent may never pick a side unilaterally.

## Closing

Re-run `python3 scripts/validate_specs.py`. Summarise: terms sharpened and where they
landed, `D-nnn` rows added with their origins, conflicts registered, and what is still open.
