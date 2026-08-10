---
doc_id: META-SPEC
title: Meta-Spec — how the Plaza doc set governs itself
tier: 0
authority: constitution
status: ACTIVE
doc_set_version: 0.2.12
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: []
supersedes: []
decides: [D-027, D-028]
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: `enforced` is **empty on day one**
---

# Meta-Spec — how the Plaza doc set governs itself

> **One line:** this file is the answer to "which document wins."
> It decides nothing about the product. It decides who is allowed to decide.

Read this before editing any spec, and before acting on one. Everything else in
the set is either governed by this file or is this file's enforcement.

| The meta layer | What it is |
|---|---|
| `META-SPEC.md` (this file) | The constitution. Tiers, authority, conflict protocol, binding rules. |
| [`spec-frontmatter.schema.json`](spec-frontmatter.schema.json) | The technical schema. What every governed document must declare. |
| [`doc-registry.json`](doc-registry.json) | The index. Every governed document and its declared authority. |
| [`concept-driver.md`](concept-driver.md) | Drives the concept axis. Scene contract + `SB-nn` index. |
| [`decision-register.md`](decision-register.md) | Every locked decision, with a stable `D-nnn` id. |
| [`spec-drivers-v0.2.5.md`](spec-drivers-v0.2.5.md) | Drives v0.2.5. Deliverables, traceability, open conflicts. |
| [`../../scripts/validate_specs.py`](../../scripts/validate_specs.py) | The gate. Runs in CI; fails the build on drift. |

---

## 1. The founding bet

Planning quality is not a precondition of AI output quality — it *is* AI output
quality. Coding agents were built by software engineers, dropped into a world of
specs and boards and sprints, and are correspondingly excellent there. So the
highest-leverage work on this project is not code; it is the quality, hierarchy,
and consistency of these documents.

Rigor in service of play. The office metaphor is a serious UX thesis — the
socialised mental model humans already have for delegating work — not decoration.
Documents may be playful in tone. They must be rigorous in structure. A spec that
is fun to read and ambiguous to an agent has failed.

## 2. The tier ladder

Every governed document declares a `tier`. **Lower tier wins.**

| Tier | Contains | May originate |
|---|---|---|
| **0** | This meta layer | Rules about documents. Never product decisions. |
| **1** | Concept source of truth | Concept and narrative decisions. |
| **2** | Implementation designs, canonical reference | How to build; reference mappings. |
| **3** | Derived plans — roadmap, tracker, policy | Sequencing and task breakdown only. |
| **4** | Summaries, research, history | Nothing. Restates what tiers 0–2 decided. |

Alongside `tier`, each document declares an `authority` — what it is licensed to
decide:

| `authority` | Licensed to decide | May declare `decides:` |
|---|---|---|
| `constitution` | How documents are written, read, and reconciled. | Yes |
| `concept` | The story, the player, the world, the fiction. **Exactly one document holds this.** | Yes |
| `implementation` | Engine, architecture, scope, technical approach. | Yes |
| `taxonomy` | One specific reference mapping (departments, floors, colours). | Yes |
| `delivery` | Time-boxed operational policy that expires with its artifact — WIP limits, retry budgets, review gates, forecast blackouts. Licensed at tier 3. | Yes |
| `derived` | Nothing new. Sequences and applies decisions made above it. | **No** |
| `summary` | Nothing. Regenerable from its sources; if it disagrees, it is wrong. | **No** |
| `research` | Nothing. Background, findings, and rationale to cite. | **No** |
| `historical` | Nothing. Retained so old links and old context still land. | **No** |

The right-hand column is enforced, not advisory: it is published in
[`spec-frontmatter.schema.json`](spec-frontmatter.schema.json) as
`authority.x-may-originate` and `scripts/validate_specs.py` fails the build on a
`decides:` list that violates it. It went in after `PROJECT-OVERVIEW` originated
eight decisions while declaring `derived`, and the set validated green for two
releases — see [`spec-drivers-v0.2.5.md`](spec-drivers-v0.2.5.md) §4.8.

**What the gate does not check:** whether a given decision falls inside its
authority's *subject matter*. A `constitution` document deciding about documents is
correct; the same document deciding about the product is not, and both look
identical to the validator. That judgement stays with review, and it works: §4.9
was found by a human asking what the new check deliberately could not see, and is
now resolved — the one instance it caught was in §5.1 of this very file.

**Two axes, one reconciliation.** Concept flows down from tier 1; implementation
flows down from tier 2. They are independent — a promoted design may override how
a scene is *built* without touching what the scene *is*.
[`README.md`](../../README.md) (`PROJECT-OVERVIEW`) is where the two axes are
reconciled into one public statement.

### 2.1 The `enforcement` axis — `D-027`

`tier` says which document wins. `authority` says what it may decide. Neither says
whether what it *asserts about the world* is still true. Every governed document
therefore also declares `enforcement`:

| `enforcement` | Meaning |
|---|---|
| `enforced` | A named CI gate re-derives every state claim on every run. |
| `asserted` | Verified by a human at a stated date. Nothing re-checks. |
| `intended` | Aspiration. Explicitly not yet true. |
| `n/a` | The document makes no claims about state. Off the scale, not on its bottom rung. |

Four rules govern the value, each chosen against a stated alternative:

1. **Per document, not per claim.** A per-claim marker is more precise and
   unenforceable — it asks a validator to parse prose. Per-document is greppable,
   and an agent learns the trust level before reading a word.
2. **A document's value is its weakest claim.** The consequence is accepted
   knowingly: `enforced` is **empty on day one**. `CLAUDE.md` is proven on
   `npm test` and unproven on the ~200-line budget; `AGENT-DIRECTORY`'s counts are
   gate-backed but its template artifacts are not; §2 of this file is enforced and
   §6 is not. That emptiness is the finding, not a defect in the axis —
   *no governed document in this set is fully machine-backed* is true today and
   currently invisible. `enforced` is a rung to earn.
3. **State claims only.** `authority` governs decisions; `enforcement` governs
   claims about the repository, the board, the running system and the tooling.
   Without this scoping the axis is a category error — weakest-claim would stamp
   `intended` on `STORYBOARD-W1` and `DECISION-REGISTER`, the two documents that
   define canon. **An `intended` value restricts nothing about originating
   decisions:** `STORYBOARD-W1` keeps `D-002` regardless.
4. **A snapshot gate is not enforcement.** `gates:` entries are typed `live` (the
   gate re-derives the fact from the system that owns it) or `snapshot` (it reads
   committed data). **`enforced` requires at least one `live` gate; snapshot-only
   caps at `asserted`.** This falls out of the definitions — `asserted` *is* "a
   human verified it at a stated date, nothing re-checks," which is exactly what a
   committed snapshot is. Wrapping it in a CI job re-reads; it does not re-check.

**The only consequence of `intended`:** that document's factual assertions may not
be relied on as current — re-verify against the owning system before acting. There
are no others.

**What this gate cannot check:** whether the declared `weakest_claim` is genuinely
the weakest. The validator proves the quote is *real*, never that it is the
*worst*. This is the third instance of the same limit — `authority` cannot check
subject matter, `constitution` cannot check whether a decision is product-shaped,
and now `enforcement` cannot rank claims. Review is still the check.

### 2.2 The `delivery` authority — `D-028`

The ladder models what the product is (tiers 1–2) and what order it is built in
(tier 3), with no authority for *how work is governed while it is built*. Sprint
charters set WIP limits, retry budgets, review gates and forecast blackouts that
nothing else sets, while declaring `derived` — licensed to originate nothing.

`delivery` closes that gap: it is licensed at tier 3 to originate **time-boxed
operational policy that expires with its artifact**. When the sprint ends, so does
the policy; nothing needs retiring because nothing was permanent. It was chosen
over an expiring `P-nnn` policy class on the evidence that most such parameters
expire unexercised, and permanent ids for those are a register of things that did
not happen. `delivery` reuses machinery that already exists — one enum value,
enforced by the same `x-may-originate` check — rather than opening a second
register.

## 3. The direction of truth

```
tier 0   META-SPEC ─ CONCEPT-DRIVER ─ DECISION-REGISTER ─ SPEC-DRIVERS-025
             │ governs everything below; originates no product decision
             ▼
tier 1   STORYBOARD-W1        ← concept & narrative originate HERE, nowhere else
             │
tier 2   DESIGN-25D (how to build)   AGENT-DIRECTORY (taxonomy)
         PLATFORM-DECISIONS (engine, transport, licence, repo policy)
             └──────────┬───────────┘
                        ▼
             PROJECT-OVERVIEW  ← reconciles both axes for public consumption
                        │
tier 3   ROADMAP → TASK-TRACKER → Jira TO
                        │
tier 4   QUICK-REFERENCE · ALIGNED-SPEC-025 · indexes · history
```

Decisions flow one direction only. A tier-3 task may not invent a rule that a
tier-1 or tier-2 document never authorised. If work needs a decision that does not
exist, the decision is made at the correct tier first, registered in
[`decision-register.md`](decision-register.md), and only then executed.

## 4. Conflict protocol

**Never silently reconcile.** When two documents disagree:

1. If one is higher tier **on the relevant axis**, it wins. Patch the lower one in
   the same change, and say so in the commit body.
2. If they are the same tier, or the axis is ambiguous, **stop.** Record it in the
   open-conflict register in [`spec-drivers-v0.2.5.md`](spec-drivers-v0.2.5.md)
   with both sides stated fairly, and raise it with the human owner. For a conflict
   that needs discussion or will outlive the current round, open a GitHub issue and
   link it from the register entry — the register stays the index, the issue is
   where it gets settled.
3. An agent may never pick a side unilaterally, and may never edit one document to
   match another as a drive-by.

The register exists because unresolved conflict is a normal, honest state. A
conflict written down is cheap; a conflict silently resolved the wrong way is
found six weeks later in code.

## 5. Binding rules for agents

These are hard gates, not preferences. A change that breaks one fails review.

1. **The bridge never knows the UI exists** — `D-005`, originated by
   [`PLATFORM-DECISIONS`](../../docs/designs/platform-decisions.md). No document,
   task, or line of code may make the agent bridge (Layer 3) aware of Godot,
   scenes, sprites, HUD, rooms, or any rendering concept. It exchanges intents and
   results only. *Swap test:* if replacing Godot with a CLI would require a bridge
   change, the boundary is broken. See `ALIGNED-SPEC-025` Document A for the
   conceptual message flow.

   This rule **cites** `D-005`; it does not make it. Until v0.2.9 the register
   named this section as the decision's origin, which put a product decision in
   the one tier §2 forbids to originate them — the constitution deciding
   architecture. Settled as option (a) on issue #18. The rule binds exactly as
   hard as it did before; what changed is which document is entitled to say it.
2. **Cite the authorising document.** State the `doc_id` (and `D-nnn` where one
   exists) that permitted a decision. Uncited decisions are unauthorised.
3. **The Storyboard is protected.** Edits to `STORYBOARD-W1` are concept changes
   and need explicit human sign-off. Adding structure — stable ids, contract
   fields — is an alignment edit and is allowed; changing a beat is not.
4. **Don't invent infrastructure — and don't hard-code the inventory here.** State
   what is runnable today, and check before asserting something does *not* exist.
   [`CLAUDE.md`](../../CLAUDE.md) is the answer; this rule points at it rather than
   listing it, because the list it used to carry ("there is no Godot project, no
   `agents.json`, no `npm test`, no `godot --headless`") stayed in place through
   `agents.json` shipping in v0.2.7 and the Godot project in v0.2.8, contradicting
   the repo from tier 0 — where it outranked the corrected prose below it. A
   constitution that names today's file inventory dates faster than anything it
   governs.
5. **Respect the critical path.** M1 → M4 → M8. If a change puts one at risk, say
   so explicitly and prominently. See [`../roadmap.md`](../roadmap.md).
6. **2.5D is the ceiling for v0.x and v1.x.** Any 3D proposal is filed as Future,
   never pulled forward.
7. **Deterministic over generative.** Where a gate or tool can be scripted, script
   it. The validator is stdlib-only and reads its rules from the schema for exactly
   this reason.
8. **Acceptance criteria must be machine-checkable.** Playful tone is welcome in
   narrative fields and forbidden in acceptance criteria.

## 6. Conventions for AI-consumable specs

1. **BLUF.** Open with a one-line pitch and, where decisions are locked, a table.
2. **Small, addressable sections.** Hierarchical numbering so an agent can be
   pointed at §4 without loading the file.
3. **Decision tables over prose.** Locked decisions live in the register, keyed by
   `D-nnn`, not scattered in paragraphs.
4. **Every requirement carries its rationale** — so an agent regenerating the work
   respects the constraint instead of "fixing" it.
5. **The rebuild test.** A fresh session, given only the specs, should be able to
   regenerate the intended artifact. If it cannot, the spec is under-specified.
6. **Instruction budget — the ~200-line rule.** Keep binding instructions in any one
   working context lean; prefer pointers to documents over one monolith. This is a
   practitioner heuristic (Garry Tan's account of trimming a `CLAUDE.md` from
   ~20,000 lines to ~200 after attention degraded), not a measured limit — but the
   underlying effect is real: success at following simultaneous instructions decays
   multiplicatively. `CLAUDE.md` and the meta docs are held to it.

## 7. Versioning

- The doc **set** carries one semantic version. This release is **0.2.12**. Files do
  not version independently; each declares `doc_set_version` and the validator
  requires them all to agree.
- `1.0.0` is cut when M8 is demonstrable in-engine.
- 3D world work is v2.0–v3.0 scope and appears in v0.x/v1.x documents only under a
  clearly-labelled Future or Deferred heading.
- `status` is one of `ACTIVE`, `DRAFT`, `SUPERSEDED`, `HISTORICAL`.

## 8. Adding or changing a governed document

1. Add the frontmatter block. It must validate against
   [`spec-frontmatter.schema.json`](spec-frontmatter.schema.json).
2. Register it in [`doc-registry.json`](doc-registry.json) — under `documents` if it
   carries authority, under `exempt` with a reason if it deliberately does not.
   Unregistered markdown in the governed tree fails CI.
3. Run `python3 scripts/validate_specs.py`. It must exit 0.
4. If a locked decision changed, update
   [`decision-register.md`](decision-register.md) and bump `doc_set_version`
   everywhere in the same commit.

*Doc set version: 0.2.12 · Last updated: August 2026*
