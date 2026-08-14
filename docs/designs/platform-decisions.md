---
doc_id: PLATFORM-DECISIONS
title: Platform Decisions — engine, transport, data layer, licence, repo policy
tier: 2
authority: implementation
status: ACTIVE
doc_set_version: 0.2.12
last_updated: 2026-08
owner: adamtasteslikegood
derives_from: [META-SPEC]
supersedes: []
decides: [D-003, D-005, D-015, D-016, D-018, D-021, D-022, D-023, D-024, D-029, D-030]
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: Nine of these were already made, already evidenced,
---

# Platform Decisions

> **One line:** the ten project-level decisions that are neither concept nor
> prototype design — engine, bridge boundary, transport, data layer, licence, and
> repository policy — and the document entitled to originate them.

This document exists because those decisions previously had no entitled home.
[`../../README.md`](../../README.md) (`PROJECT-OVERVIEW`) was named as the origin of
eight of them while declaring `authority: derived`, which
[`../../specs/meta/META-SPEC.md`](../../specs/meta/META-SPEC.md) §2 licenses to
decide *nothing new*. The layer contradicted itself. Recorded as open conflict §4.8
in [`../../specs/meta/spec-drivers-v0.2.5.md`](../../specs/meta/spec-drivers-v0.2.5.md),
tracked as [issue #11](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/11),
and closed by creating this file.

`D-005` joined them in v0.2.9 for the same reason at the opposite end of the ladder:
its origin was tier-0 `META-SPEC`, which §2 forbids to originate product decisions
at all. Open conflict §4.9, [issue #18](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/18).
Twice now the entitlement error has been found by reading the authority column
rather than the decision — the decisions themselves were never in doubt.

**Nine of these were already made, already evidenced,
and already being acted on.** What changed is which document is entitled to hold
them — `PROJECT-OVERVIEW` goes back to being purely the reconciliation of the two
axes, which is what `META-SPEC` §2 already said it was, and `META-SPEC` goes back to
deciding only about documents. `D-029` is the exception: it is a new decision,
registered here in v0.2.12 because it passes the scope test in §1 (the bridge
agent store survives replacing the frontend).

## 1. Scope — what belongs in this document

| Belongs here | Belongs elsewhere |
|---|---|
| Engine, language, and runtime choices | How a scene is built → [`2.5D-RPG-Prototype.md`](2.5D-RPG-Prototype.md) |
| Transport and process boundaries for the bridge | What the player experiences → [`../storyboard-week1.md`](../storyboard-week1.md) |
| Where canonical data comes from and how it is derived | The department/floor/colour mapping → [`../agent-directory.md`](../agent-directory.md) |
| Licence and attribution | Sequencing and task breakdown → [`../../specs/roadmap.md`](../../specs/roadmap.md) |
| Repository and submodule policy | How documents govern each other → `META-SPEC` |

The test: **would this decision survive replacing the entire frontend?** If yes it
is a platform decision and lives here. If it dies with the 2.5D prototype, it
belongs in the promoted design. `D-003` (Godot 4) sits deliberately on the line —
it is here because the engine choice predates the 2.5D pivot and outlives it; the
pivot decided *2D rather than 3D within Godot*, which is `D-001` and lives there.

## 2. Platform

### `D-003` — Engine: Godot 4

Free, MIT-licensed, GDScript reads like Python, strong 2D and TileMap support.
Chosen over Three.js and Unity. The MIT licensing matters beyond cost: it is what
lets `D-018` hold without a licence-compatibility argument.

### `D-005` — Bridge UI-awareness: zero

The bridge never knows the UI exists. It exchanges intents and results; no
document, task, or line of code may make Layer 3 aware of Godot, scenes, sprites,
HUD, rooms, or any rendering concept.

**Swap test:** if replacing Godot with a CLI harness would require a bridge
change, the boundary is broken and the change fails review.

This is what makes `D-020` — Layer 2 named for the role, not the implementation —
architecture rather than aspiration. A CLI harness, a web UI, and the eventual 3D
world are peers of 2.5D Godot, not replacements for the layer.

*Originated here as of v0.2.9.* It was previously attributed to `META-SPEC` §5.1,
which is tier 0 and licensed to decide about documents, never about the product —
so a genuine architecture constraint was being originated by the one document
forbidden to originate it. Recorded as open conflict §4.9, settled by the owner as
option (a) on [issue #18](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/18).
`META-SPEC` §5.1 still **states** the rule and still binds agents to it — it now
cites this decision rather than making it. The rule did not change; only the
question of who was entitled to make it.

Scope note: it passes this document's own test. Replace the entire frontend and
`D-005` is not merely unaffected — it is the decision that makes the replacement
possible at all.

### `D-015` — Bridge transport: Python WebSocket, `ws://localhost:8765`

A local process, so the prototype needs no deployment story. Pairs with `D-006`
(synchronous with timeout) in the promoted design. **This decision names a
transport, not a UI** — `D-005` still holds, and a change here that leaks a
rendering concept into the bridge fails the swap test regardless of what this
document says.

### `D-016` — Agent data layer: generated, never hand-written

`data/agents.json` is generated from the `claude-code-tresor` submodule by
[`../../scripts/generate_agents_json.py`](../../scripts/generate_agents_json.py).
The submodule is the canonical agent layer; hand-editing the JSON forks the truth.
Minimum fields per agent: `{name, role, dept, colour, tools, description}`.
Enforced in CI by `Validate Agent Data`, which regenerates and diffs.

### `D-024` — Agent data source and curation

The generator reads `subagents/` only — upstream v2.7.0 made it PRIMARY and left
`agents/` a backward-compat shim. The 133 source files carry 130 distinct slugs, so
three collisions are curated in code: `infrastructure-maintainer` is one role filed
twice (operations copy removed), while `customer-support` and `tutorial-engineer`
are different jobs sharing a label (renamed `support-ticket-handler` and
`educational-content-writer`). Result: **132 entries**.

Curation tables are keyed by *source path*, so an upstream move fails the build
rather than mis-applying a rename to the wrong agent. A new collision is a hard
error and never an auto-suffix — deciding "one role or two" means reading both
files, which is a human's call. A curation key matching nothing is also an error,
so the tables cannot rot in place.

**Before renaming or removing an agent, grep `commands/`** — 19 of the 24
orchestration commands reference agents by id, covering 26 of the 132.

### `D-018` — Licence: MIT, © 2026 Adam Schoen

Matches the attribution the project already carries and the upstream
`claude-code-tresor` licensing. Resolves the former Apache-2.0 `LICENSE` file
versus MIT-in-documentation conflict in favour of the documentation.

## 3. Repository policy

### `D-021` — The submodule gitlink tracks `10110TLGP/dev`

Confirmed by the owner and by `origin/HEAD`, which points at it — that branch is
the fork's default. Bumps fast-forward the pin to its head. Recorded because "is
the pin stale?" is unanswerable without knowing the target branch, and the answer
previously lived only in someone's head.

### `D-022` — The fork's `10110TLGP/main` is reserved as its release branch

Not abandoned, not a pin target — dormant until the fork has a `release.yml` and
tagged releases, at which point it follows the same model as this repo: cut
`dev` → `main`, tag, back-sync. Until then the pin follows `dev` (`D-021`).
Recorded so nobody prunes it as stale or pins to it expecting the newer commit.

### `D-023` — Merge commits, not squash

Squash and rebase merging are **disabled in repository settings** (verified
2026-07-26). Deliberate, not a default: the squash-only rule was inherited from
`alirezarezvani/claude-code-tresor`, was never chosen for this project, and squash
merging has caused the owner real problems on other repositories. Merge commits
keep a PR's commit series intact and bisectable.

Consequences: `dev` is not linear, so "Require linear history" must stay off — it
would block every merge — and reverting a merged PR needs `git revert -m 1`.
**Do not switch to squash on a linter's or a bot's suggestion.** That is precisely
how the wrong rule arrived; see
[`../../specs/branching-strategy.md`](../../specs/branching-strategy.md) §9.

### `D-029` — Bridge agent store

The bridge maintains its own copy of agent definitions at runtime, decoupled from
the `claude-code-tresor` submodule. A sync module copies from
`claude-code-tresor/subagents/` into `bridge/agents/`; at runtime the bridge reads
only from its own store. Store format is initially `.md` files, with an upgrade
path to a structured store (database, wikilink markdown, gbrain-style index).

Passes the §1 scope test: replacing the frontend changes nothing about how the
bridge loads agent definitions. Registered in Sprint 4 (`specs/sprint-4-charter.md`
§1.4); implementation is T3a/T3b.

### `D-030` — PR review round bounds

Minimum 2 rounds of reading and replying to bot/human review comments before
merge. Maximum 3 rounds before deciding: merge, close PR, or revert to draft
and elevate to the owner.

**Security findings, branch-protection failures and ticket-linked blockers are
exempt from the max** — they run until resolved or elevated. Everything else
(cosmetic, informational, contested governance) follows the bounds.

The escalation path on round 3 is a three-way choice, not a default:

1. **Merge** — all actionable findings addressed, remaining items are cosmetic
   or accepted risk.
2. **Close PR** — the approach is wrong; start over.
3. **Revert to draft and elevate** — unresolved disagreement needs the owner's
   call. File a ticket if one doesn't exist.

Origin: PLZG-199 review, where one round of reading missed a fixable finding
(symlink-follow in `/tmp` cache rebutted instead of fixed). The code was
bridge-bound and bots re-flag it every push — rebutting cost more than fixing.

Passes the §1 scope test: review process is frontend-agnostic.

## 4. Adding a decision here

Same procedure as any entitled document —
[`../../specs/meta/META-SPEC.md`](../../specs/meta/META-SPEC.md) §8 — plus one
scope check: run the frontend-replacement test in §1 first. A decision that dies
with the 2.5D prototype belongs in [`2.5D-RPG-Prototype.md`](2.5D-RPG-Prototype.md),
not here. Add the `D-nnn` to this file's `decides:` list and to
[`../../specs/meta/decision-register.md`](../../specs/meta/decision-register.md);
`scripts/validate_specs.py` fails the build if the two disagree, and now also fails
if a document declares `decides:` without an authority licensed to originate.

*Doc set version: 0.2.12 · Last updated: August 2026*
