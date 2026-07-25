---
doc_id: SPEC-DRIVERS-025
title: Spec Drivers v0.2.5 — what this doc-set version must produce
tier: 0
authority: constitution
status: ACTIVE
doc_set_version: 0.2.5
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

## 1. What v0.2.5 delivers

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

Round 1 is this change. Later rounds are named so tasks can be filed against them
now; none of them are started.

| Stage | Scope | Advance when |
|---|---|---|
| **Round 1 — Govern** (this change) | Meta layer, schema, registry, validator, CI gate, conflict register | `Validate Specs` green; §1 all true |
| **Round 2 — Data (M3)** | `agents.json` generator over the submodule, its schema, count validation against `D-017` | Generated file validates; counts reconcile §4.2 |
| **Round 3 — Frontend (M1, M4)** | Godot 4 project, the three autoloads, 2.5D navigation, proximity dialogue | Dialogue panel renders live from `AgentRegistry` for one department |
| **Round 4 — Bridge (M5–M8)** | Synchronous WebSocket bridge, intent/result shape, wait-or-delegate, end-to-end | M8 demonstrable in-engine |

## 4. Open-conflict register

Per [`META-SPEC.md`](META-SPEC.md) §4, conflicts are recorded rather than silently
resolved. Two are closed here; four are open and need the human owner.

### 4.1 `ALIGNED-SPEC-025` §01.3 versus `STORYBOARD-W1` — **RESOLVED**

§01.3 invented a 14-scene spine that contradicts the real storyboard on Day 0, the
assistant's introduction, player configuration, and the coding lesson, and pulled a
deferred RA/QM department into the tutorial. Storyboard wins on the concept axis
(tier 1 beats tier 4). Full side-by-side in
[`concept-driver.md`](concept-driver.md) §4. `ALIGNED-SPEC-025` is now
`authority: research`, `status: SUPERSEDED`.

### 4.2 Agent counts disagree across four documents — **OPEN**

| Source | Claim |
|---|---|
| [`../../README.md`](../../README.md) | "137+ real AI agent roles", Engineering "60+" |
| [`../../CLAUDE.md`](../../CLAUDE.md) | "137+ agent `.md` files" |
| [`../../docs/agent-directory.md`](../../docs/agent-directory.md) | "137+ agent roles across nine departments" |
| `ALIGNED-SPEC-025` §4 / Doc B | 133 across ten categories under the v2.7.0 unified structure; Engineering 54 |

Not resolvable from this repo — the `claude-code-tresor` submodule is a gitlink and
is empty in fresh checkouts. **Owner action:** initialise the submodule, count, and
let the count land in `AGENT-DIRECTORY` (the taxonomy authority) with every other
mention derived from it. Blocks Round 2. Until then, prose should say "130+" rather
than pick a precise number it cannot support.

### 4.3 Layer 2 is described two different ways — **OPEN**

`README.md`, `CLAUDE.md`, and `docs/quick-reference.md` all name Layer 2 "the Godot
4 engine". `ALIGNED-SPEC-025` §00.4 deliberately reframes it as "**the current
frontend, which happens to be 2.5D Godot**", to leave room for CLI, web, and future
3D frontends without touching Layers 3–4.

This is not cosmetic: the reframing is what makes `D-005` and the swap test read as
architecture rather than aspiration. But the reframing originates in a tier-4
research doc and so is not authorised. **Owner action:** ratify the "Layer 2 =
current frontend" wording into `DESIGN-25D` or a new promoted design, then patch the
three describing documents.

### 4.4 `D-014` bridge formality is unauthorised — **OPEN**

"Conceptual boundary, no versioned API contract until post-M8" is proposed only by
a tier-4 document. See [`decision-register.md`](decision-register.md) §"Not yet
authorised". **Owner action:** ratify into a promoted design, or drop it. The
threshold that would change the answer: a multi-frontend need arriving before v2.0
— a web demo for fundraising, say — at which point the message shape should be
promoted to a versioned contract, but not before.

### 4.5 `branching-strategy.md` describes a repo that does not exist — **OPEN**

[`../branching-strategy.md`](../branching-strategy.md) says "ClaudeForge" throughout
and requires status checks from `pr-into-dev.yml`, `dev-to-main.yml`, and
`release.yml` — none of which exist in `.github/workflows/`. It is marked
`status: DRAFT` in the registry to reflect that it is intended policy, not active
rules. **Owner action:** either write the workflows or rewrite the doc to describe
the two jobs that actually run. Until then
[`../../CONTRIBUTING.md`](../../CONTRIBUTING.md) is the operative guide.

### 4.6 `LICENSE` was Apache-2.0 while the docs said MIT — **RESOLVED**

Resolved in favour of the documentation and the upstream attribution:
[`../../LICENSE`](../../LICENSE) is now MIT, © 2026 Adam Schoen. Registered as
`D-018`.

## 5. Exit criteria to v1.0.0

`1.0.0` is cut when **M8 is demonstrable in-engine** — a player question travels
through the bridge to a real `claude @agent-name` invocation and the response
renders in the dialogue panel. That is the repo's own stated first-tag trigger and
this version does not move it.

Between here and there, each round closes with the same check: the register has no
conflict that has been open longer than the round that discovered it.

*Doc set version: 0.2.5 · Last updated: July 2026*
