---
doc_id: SPEC-DRIVERS-025
title: Spec Drivers v0.2.5 — what this doc-set version must produce
tier: 0
authority: constitution
status: ACTIVE
doc_set_version: 0.2.6
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [META-SPEC]
supersedes: []
---

# Spec Drivers v0.2.5

> **One line:** v0.2.5 exists to make the doc set *self-governing* before any Godot
> code is written — so that when code arrives, there is exactly one thing to build
> against.

Version semantics: `0` = pre-prototype · `.2` = second aligned concept revision ·
`.5` = the alignment patch that resolves the split between the two doc trees.

---

> **Filename note.** This file still carries `v0.2.5` in its name while holding live
> v0.2.6 content — the open-conflict register is the working copy, not a frozen
> record. Splitting it (or renaming to an unversioned `spec-drivers.md`) is worth
> doing at v0.3; renaming a `doc_id` one PR after shipping it costs more than it
> saves.

## 1a. Delivered in v0.2.5

The meta layer itself — constitution, schema, registry, concept driver with
`SB-01`–`SB-18`, decision register, and `scripts/validate_specs.py` in CI. The six
rows below were the acceptance criteria and all passed.

## 1b. Delivering in v0.2.6

Closing every conflict v0.2.5 left open (§4): the real agent count landed in the
taxonomy authority, `D-020` and `D-014` ratified into `DESIGN-25D`, and
`branching-strategy.md` rewritten to describe this repository. Two new decisions
means the set version moves — `META-SPEC` §8.4.

**Done when:** §4.2–4.5 all read RESOLVED, no decision sits in "Not yet authorised"
without a reason, and `Validate Specs` is green at `doc_set_version: 0.2.6`.

## 1. What v0.2.5 delivered

| # | Deliverable | Done when |
|---|---|---|
| 1 | A meta layer that answers "which document wins" | [`META-SPEC.md`](META-SPEC.md) exists, is `ACTIVE`, and every governed doc declares a tier and an authority. |
| 2 | Machine-readable authority | Every governed doc validates against `spec-frontmatter.schema.json` and is listed in `doc-registry.json`. |
| 3 | One concept origin | Exactly one document holds `authority: concept`. Every scene is citable as `SB-nn`. |
| 4 | One decision list | [`decision-register.md`](decision-register.md) holds every locked decision with a `D-nnn` and a named origin. |
| 5 | Enforcement, not intention | `scripts/validate_specs.py` runs in CI and fails the build on drift. |
| 6 | Honest conflicts | Every known contradiction is either resolved with a record, or listed open in §4 with both sides stated. |

**Definition of done for v0.2.5:** all six rows true, `Validate Specs` green on
`dev`, and no document claiming an authority the registry does not grant it.

## 2. The traceability chain

Every piece of work traces upward. A task that cannot name its decision is
unauthorised work — it is proposing something, and the proposal belongs at the
entitled tier first.

```
D-nnn  (decision-register.md — who decided, and why)
  └─▶ SB-nn  (concept-driver.md — which beat of the story it serves)
        └─▶ M1..M8  (specs/roadmap.md — which milestone proves it)
              └─▶ TO-nnn  (Jira / specs/task-tracker.md — the unit of work)
```

Not every task touches a scene — bridge and tooling work often traces
`D-nnn → M-n → TO-nnn` with no `SB-nn`. That is fine and expected. What is never
fine is a task with no `D-nnn`.

**Task template** — each task carries:

`Title | Decision (D-nnn) | Scene (SB-nn or —) | Milestone | Acceptance criteria (machine-checkable) | Bridge UI-awareness risk? (Y/N)`

**Definition of done, project-wide.** A task is done when: its acceptance criteria
pass; no bridge UI-awareness was introduced (`D-005`, swap test); the change is
reflected upward in the correct document at the correct tier; and
`doc_set_version` is bumped across the set if a locked decision changed.

## 3. Stage plan

Rounds 1 and 2 are done. Later rounds are named so tasks can be filed against them
now; neither is started.

| Stage | Scope | Advance when |
|---|---|---|
| **Round 1 — Govern** ✅ v0.2.5 | Meta layer, schema, registry, validator, CI gate, conflict register | `Validate Specs` green; §1 all true |
| **Round 1b — Reconcile** ✅ v0.2.6 | Close §4.2–4.5: real agent count, `D-020` and `D-014` ratified, branching policy corrected | Six of seven conflicts RESOLVED |
| **Round 2 — Data (M3)** | `agents.json` generator over the submodule, its schema, count validation against `D-017` | Generated file validates; 133 entries, core-eight collision resolved per §4.2 |
| **Round 3 — Frontend (M1, M4)** | Godot 4 project, the three autoloads, 2.5D navigation, proximity dialogue | Dialogue panel renders live from `AgentRegistry` for one department |
| **Round 4 — Bridge (M5–M8)** | Synchronous WebSocket bridge, intent/result shape, wait-or-delegate, end-to-end | M8 demonstrable in-engine |

## 4. Open-conflict register

Per [`META-SPEC.md`](META-SPEC.md) §4, conflicts are recorded rather than silently
resolved. **Seven resolved, one open (§4.8)** as of v0.2.6. Resolved entries are kept, not
deleted — the record of *how* a conflict was settled is what stops it reopening.

### 4.1 `ALIGNED-SPEC-025` §01.3 versus `STORYBOARD-W1` — **RESOLVED**

§01.3 invented a 14-scene spine that contradicts the real storyboard on Day 0, the
assistant's introduction, player configuration, and the coding lesson, and pulled a
deferred RA/QM department into the tutorial. Storyboard wins on the concept axis
(tier 1 beats tier 4). Full side-by-side in
[`concept-driver.md`](concept-driver.md) §4. `ALIGNED-SPEC-025` is now
`authority: research`, `status: SUPERSEDED`.

### 4.2 Agent counts disagreed across four documents — **RESOLVED**

The submodule was initialised and counted on 2026-07-25. **141 agent files = 8 core
+ 133 subagents, spanning 133 distinct roles.** Verified identical at `acfb923`,
at `bcfe30c` (`10110TLGP/main`), and — after the pin moved on 2026-07-26 — at
**`b7ec149`**, the current pin. The bump was docs-only: `subagents/` and `agents/`
are byte-identical across `acfb923` and `b7ec149`.

Both numbers are correct and measure different things: `agents/*.md` (8) holds the
same eight roles as `subagents/core/` in Claude Code's runtime format rather than
the catalog format, so the files are distinct but the roles are not. The "137+"
that appeared in `README.md`, `CLAUDE.md`, and `AGENT-DIRECTORY` was wrong on both
counts.

Method, per-category figures, and the format comparison are in
[`../../docs/agent-directory.md`](../../docs/agent-directory.md) § Agent counts —
the taxonomy authority (`D-017`). Every other mention now derives from there.

**Follow-on, not a conflict:** `data/agents.json` is keyed by agent id (`D-016`),
so the core eight collide. Recorded as an M3 hazard with a recommendation (prefer
the catalog format) but deliberately not locked — decide it when the generator
exists and the data shape is visible.

### 4.3 Layer 2 was described two different ways — **RESOLVED**

`README.md`, `CLAUDE.md`, and `docs/quick-reference.md` all name Layer 2 "the Godot
4 engine". `ALIGNED-SPEC-025` §00.4 deliberately reframes it as "**the current
frontend, which happens to be 2.5D Godot**", to leave room for CLI, web, and future
3D frontends without touching Layers 3–4.

This was not cosmetic: the reframing is what makes `D-005` and the swap test read
as architecture rather than aspiration. Ratified into `DESIGN-25D` in v0.2.6 as
**`D-020`**, carrying the frontend-swap matrix; `README.md`, `CLAUDE.md`, and
`docs/quick-reference.md` now describe Layer 2 as the current frontend.

### 4.4 `D-014` bridge formality was unauthorised — **RESOLVED**

"Conceptual boundary, no versioned API contract until post-M8" was proposed only by
a tier-4 document. Ratified into `DESIGN-25D` in v0.2.6 and flipped to `LOCKED`,
carrying its reversal threshold: a multi-frontend need arriving before v2.0 — a web
demo for fundraising, say — promotes the message shape to a versioned contract.
Nothing else does.

### 4.5 `branching-strategy.md` described a repo that does not exist — **RESOLVED**

[`../branching-strategy.md`](../branching-strategy.md) said "ClaudeForge"
throughout, linked to the upstream project's issue tracker, and required status
checks from `pr-into-dev.yml`, `dev-to-main.yml`, and `release.yml` — none of which
exist in `.github/workflows/`.

Rewritten in v0.2.6, **806 lines → 181**. The owner confirmed the document was
copied from the upstream fork intending to modify it, and that accuracy about this
repository matters more than anything the inherited text says — so the upstream
content was dropped rather than preserved and fenced.

What it says now is checked against the repo: the real branch list (including the
long-lived `feature/TO-1-prototype-initialization` and its `scripts/` tree), `dev`
as the default branch, the actual CI jobs, the real submodule-bump procedure, and
an honest "no tags cut yet" release section. The branch-protection settings are
labelled as a setup to apply, not as current state, and carry the correct job names.
`status: DRAFT` → `ACTIVE`. A §9 provenance note records where the document came
from so the question does not get re-litigated.

[`../../CONTRIBUTING.md`](../../CONTRIBUTING.md) remains the operative everyday
guide.

### 4.6 `LICENSE` was Apache-2.0 while the docs said MIT — **RESOLVED**

Resolved in favour of the documentation and the upstream attribution:
[`../../LICENSE`](../../LICENSE) is now MIT, © 2026 Adam Schoen. Registered as
`D-018`.

### 4.7 Which submodule branch the project tracks — **RESOLVED**

**Half closed on 2026-07-26.** The pin was bumped `acfb923` → `b7ec149`, the new
head of `10110TLGP/dev` after upstream was merged into it, and the owner confirmed
that branch is the fork's default — as does `origin/HEAD`. Registered as **`D-021`**
in [`decision-register.md`](decision-register.md): **the gitlink tracks
`10110TLGP/dev`**. `CLAUDE.md` names both the commit and the branch.

**Closed on 2026-07-26.** The owner confirmed `10110TLGP/main` is **reserved as the
fork's release branch** — dormant until the fork has a `release.yml` and tagged
GitHub releases, at which point it follows the same model as this repo: cut
`dev` → `main`, tag, back-sync `main` → `dev`. It is not abandoned and not a pin
target. Registered as **`D-022`**.

**One correction to the earlier entry.** This register previously described the two
branches as "diverged, needs reconciling". That overstated it. They diverge in
*history* only — one commit each side of merge-base `4b68050`, because each branch
merged the same upstream state by a different route (`bcfe30c` a direct merge,
`b7ec149` a PR merge). **Their trees are byte-identical**: both resolve to tree
`b7aee19`, and `git diff origin/10110TLGP/main origin/10110TLGP/dev` is empty.

That matters for the first release: `dev` → `main` will not fast-forward, but the
merge is content-free and cannot conflict. Nothing needs reconciling before then.

### 4.8 `PROJECT-OVERVIEW` originates decisions its authority forbids — **OPEN**

Found while registering `D-023`. `README.md` declares `authority: derived`, and
[`META-SPEC.md`](META-SPEC.md) §2 says `derived` may decide "nothing new — sequences
and applies decisions made above it." But the register names `PROJECT-OVERVIEW` as
the origin of **seven** decisions: `D-003` (engine), `D-015` (bridge transport),
`D-016` (agent data layer), `D-018` (licence), `D-021` (submodule tracking branch),
`D-022` (fork's release branch), `D-023` (merge strategy).

So the layer contradicts itself, and the validator does not catch it — it checks
that every `D-nnn` in a `decides:` list exists in the register, but never that the
declaring document's `authority` permits deciding at all.

Neither side is obviously right, which is why this is recorded rather than fixed:

- Those seven are real decisions that needed *somewhere* to live, and none of them
  is concept (tier 1) or a promoted design (tier 2 `implementation`). They are
  project- and process-level: engine, transport, licence, branch policy.
- `README.md` genuinely is a reconciliation document. Giving it origination
  authority weakens the tier ladder's central claim.

**Owner action:** pick one — (a) add a `platform` or `process` authority for
project-level decisions and move these seven to a document that holds it, (b) split
them out into a tier-2 design doc, or (c) accept `PROJECT-OVERVIEW` as a legitimate
origin and soften `derived` in `META-SPEC` §2. Whichever is chosen, the validator
should then gain a check that a document may only `decide` what its `authority`
allows — the gap that let this through.

Nothing is blocked by this: every one of the seven decisions is substantively
correct and independently evidenced. What is wrong is the bookkeeping about who was
entitled to make them.

## 5. Exit criteria to v1.0.0

`1.0.0` is cut when **M8 is demonstrable in-engine** — a player question travels
through the bridge to a real `claude @agent-name` invocation and the response
renders in the dialogue panel. That is the repo's own stated first-tag trigger and
this version does not move it.

Between here and there, each round closes with the same check: the register has no
conflict that has been open longer than the round that discovered it.

*Doc set version: 0.2.6 · Last updated: July 2026*
