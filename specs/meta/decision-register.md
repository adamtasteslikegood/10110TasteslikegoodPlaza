---
doc_id: DECISION-REGISTER
title: Decision Register — every locked decision, with a citable id
tier: 0
authority: constitution
status: ACTIVE
doc_set_version: 0.2.11
last_updated: 2026-08
owner: adamtasteslikegood
derives_from: [META-SPEC]
supersedes: []
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: 19 of the 24 orchestration commands
---

# Decision Register

> **One line:** when [`META-SPEC.md`](META-SPEC.md) §5.2 says "cite the authorising
> document," this is what you cite.

Every locked decision gets a stable `D-nnn`. Ids are never reused and never
renumbered. Before this file existed, the same decisions lived in three places at
once — `README.md` "Key Design Decisions", `ALIGNED-SPEC-025` §00.5, and the scope
table in `DESIGN-25D` — with no way to tell which copy was current.

**Origin** names the `doc_id` that was *entitled* to make the call, per the tier
ladder. A decision whose only origin is a tier-4 document is not locked, however
sensible it reads — it is `PROPOSED` until ratified at the right tier.

**Status:** `LOCKED` · `PROPOSED` (needs ratification) · `DEFERRED` · `SUPERSEDED`.

---

## Concept — origin `STORYBOARD-W1` (tier 1)

| Id | Decision | Choice | Rationale | Status |
|---|---|---|---|---|
| `D-002` | Player framing | Co-founder / tech lead, dead centre of the spectrum | Empowering but guided. Not a solo founder in an empty office, not a new hire catching up. They have keys and walk in before anyone else. | `LOCKED` |
| `D-008` | Tutorial and onboarding | The same thing | Bootstrapping the fictional startup *is* real agent setup. This is the product thesis; if it stops being true the project is a game. | `LOCKED` |
| `D-009` | Unlock mechanic | Completed tasks gate rooms and floors | Onboarding completion equals world expansion. Unlocks are earned, never handed over. | `LOCKED` |
| `D-010` | In-world assistant | Scripted navigation guide — **not** an agent NPC | Always-on companion, distinct from the agent characters. Blurring the two breaks the "characters are the agents" premise. | `LOCKED` |
| `D-019` | Week 1 scene spine | The 14 numbered scenes plus four Days 4–5 beats, indexed `SB-01`–`SB-18` | Reconciled against the `ALIGNED-SPEC-025` §01.3 reconstruction, which was invented. See [`concept-driver.md`](concept-driver.md) §4. | `LOCKED` |

## Implementation — origin `DESIGN-25D` (tier 2, promoted 2026-04-27)

| Id | Decision | Choice | Rationale | Status |
|---|---|---|---|---|
| `D-001` | Rendering | 2.5D top-down (Godot 2D), Pokémon / Stardew Valley register | The UI *organisation* is the value, not fidelity. Removes the art, navmesh, and physics bottlenecks in one move. | `LOCKED` |
| `D-004` | 3D first-person world | Deferred to v2.0–3.0 | Scope discipline — the "10x check". Not cancelled; not pulled forward. | `DEFERRED` |
| `D-006` | Bridge execution model | Synchronous, with timeout protection | True streaming is too brittle for a prototype bridge. Simplicity now; streaming deferred. | `LOCKED` |
| `D-007` | Streaming feel | Typewriter effect over the full JSON response, **rendered entirely in the frontend** | Batch output feels dead; the typewriter buys the feel without the fragility. Being a frontend-only concern is what keeps `D-005` intact. | `LOCKED` |
| `D-011` | Agent sprite | One generic sprite, tinted per department colour | Eliminates the art bottleneck immediately. Unique sprites for all 133 roles deferred. | `LOCKED` |
| `D-012` | Dialogue portrait | One generic silhouette | Same reasoning as `D-011`. | `LOCKED` |
| `D-013` | Long-task UX | "Wait or delegate" — short tasks block, long tasks run in the background | Models real office dynamics, and it is the honest UI for a synchronous bridge with a timeout. | `LOCKED` |
| `D-014` | Bridge formality | Conceptual boundary in prose; no versioned API contract until after M8 | Freezing a contract pre-M8 ossifies decisions before anything has been learned about what the messages need to carry. **Reversal threshold:** a multi-frontend need arriving before v2.0 — a web demo for fundraising, say — promotes the message shape to a versioned contract. Nothing else does. Ratified in v0.2.6. | `LOCKED` |
| `D-020` | Layer 2 naming | "The current frontend, which happens to be 2.5D Godot" — not "the Godot engine" | `D-005` and the swap test are only meaningful if the frontend is structurally a slot. Naming Layer 2 after one implementation makes the rule read as aspiration. Carries the frontend-swap matrix. Ratified in v0.2.6. | `LOCKED` |
| `D-025` | GDScript file layout | Scene scripts live beside their `.tscn` under `scenes/`; the three autoloads stay in `autoload/` | `CLAUDE.md` originally put GDScript in `scripts/`, written before that directory filled with the Python tooling CI invokes by path (`validate_specs.py`, `generate_agents_json.py`). Mixing two languages and two runtimes there hides which files CI depends on. Script-beside-scene is also ordinary Godot practice. Recorded rather than silently applied because it contradicts a written layout, and an undocumented deviation is what a later agent "corrects" back. Registered in v0.2.8. | `LOCKED` |

## Architecture and platform

| Id | Decision | Choice | Rationale | Origin | Status |
|---|---|---|---|---|---|
| `D-003` | Game engine | Godot 4 | Free, MIT, GDScript reads like Python, strong 2D/TileMap support. Chosen over Three.js and Unity. | `PLATFORM-DECISIONS` | `LOCKED` |
| `D-005` | Bridge UI-awareness | Zero. The bridge never knows the UI exists | Enables a CLI, a web UI, or a future 3D frontend to swap in with no bridge change. Enforced by the swap test as a hard review gate. Origin moved from `META-SPEC` §5.1 in v0.2.9 — tier 0 may not originate a product decision; §5.1 now cites this rather than making it. Issue #18, option (a). | `PLATFORM-DECISIONS` | `LOCKED` |
| `D-015` | Bridge transport | Python WebSocket server, local, `ws://localhost:8765` | Local process, no deployment needed for the prototype. | `PLATFORM-DECISIONS` | `LOCKED` |
| `D-016` | Agent data layer | `data/agents.json` generated from the `claude-code-tresor` submodule; never hand-edited | The submodule is the canonical agent layer. Hand-editing forks the truth. Minimum fields: `{name, role, dept, colour, tools, description}`. | `PLATFORM-DECISIONS` | `LOCKED` |
| `D-017` | Department taxonomy | Nine departments plus Core, each with a fixed floor/zone and hex tint | The office layout derives from the taxonomy; the taxonomy derives from the submodule. | `AGENT-DIRECTORY` | `LOCKED` |
| `D-018` | Licence | MIT, © 2026 Adam Schoen | Matches the attribution the project already carries and the upstream `claude-code-tresor` licensing. Resolves the Apache-2.0 `LICENSE` file versus MIT documentation conflict in favour of the documentation. | `PLATFORM-DECISIONS` | `LOCKED` |
| `D-021` | Submodule tracking branch | The `claude-code-tresor` gitlink tracks **`10110TLGP/dev`** | Confirmed by the owner and by `origin/HEAD`, which points at it — it is the fork's default branch. Bumps fast-forward the pin to that branch's head. Recorded because "is the pin stale?" is unanswerable without knowing the target branch, and the answer previously lived only in someone's head. | `PLATFORM-DECISIONS` | `LOCKED` |
| `D-022` | Fork's `10110TLGP/main` | **Reserved as the fork's release branch.** Not abandoned, not a pin target — dormant until the fork has a `release.yml` and tagged GitHub releases | The submodule mirrors this repo's own model: `dev` integrates, `main` releases. Once release tooling exists, the fork cuts `dev` → `main`, tags it, and back-syncs `main` → `dev`. Until then the pin follows `dev` (`D-021`) and `main` is left alone. Recorded so nobody prunes it as a stale branch or pins to it expecting the newer commit. | `PLATFORM-DECISIONS` | `LOCKED` |
| `D-024` | Agent data source and curation | Generate `data/agents.json` from `subagents/` only; curate the three upstream id collisions in code | Upstream v2.7.0 made `subagents/` PRIMARY and `agents/` a backward-compat shim — 8 symlinks plus 8 stale pre-v2.7.0 flat files still carrying `category: engineering` / `color: blue` for the core eight. Separately, the 133 files hold only **130 distinct slugs**: `infrastructure-maintainer` is one role filed twice (operations copy **removed**), while `customer-support` and `tutorial-engineer` are genuinely different jobs sharing a name (renamed `support-ticket-handler`, `educational-content-writer`). Result: **132 entries**. Curation tables are keyed by *source path*, so an upstream move fails the build instead of mis-applying; a new collision is a hard error, never an auto-suffix, because "one role or two" needs a human reading both. **Before renaming or removing an agent, grep `commands/`** — 19 of the 24 orchestration commands reference agents by id, covering 26 of the 132. `D-016` holds: the curation is code in the diff, and the JSON stays a pure function of submodule + tables. | `PLATFORM-DECISIONS` | `LOCKED` |
| `D-023` | Merge strategy | **Merge commits.** Squash and rebase merging are disabled in repository settings (verified 2026-07-26) | Deliberate, not a default. The squash-only rule was inherited from `alirezarezvani/claude-code-tresor` and was never chosen for this project; squash merging has caused the owner real problems on other repositories. Merge commits keep a PR's commit series intact and bisectable. Consequences: `dev` is not linear and "Require linear history" must stay off (it would block every merge), and reverting a merged PR needs `git revert -m 1`. **Do not switch to squash on a linter's or bot's suggestion** — that is how the wrong rule arrived. | `PLATFORM-DECISIONS` | `LOCKED` |
| `D-026` | Delivery coordinates authority | **`DELIVERY-COORDINATES` is the single origin of every Atlassian identifier** — Jira keys, Confluence space and page ids. `CLAUDE.md` and every guide cite it rather than restating it. **The table is now the only copy in the tree** — since `PLZG-109` (2026-07-31) both Python scripts read their coordinates from the environment and hold none. *Historical, and retained deliberately: this clause once read "the two Python scripts are the only other legitimate copy, because they execute the values", which was true while they hardcoded them.* | Recorded because the absence of this rule caused real, shipped drift in both directions. `post_to_confluence.py` published Plaza status reports into `TLG`, a sibling product's space, behind a silent fallback. Then `CLAUDE.md` came to hold, simultaneously, a rule forbidding copies of the project key into that file and a table copying the project key into that file — two agent-authored statements, each defensible alone, in direct contradiction. A reference mapping needs an entitled home, not a convention, which is the same reasoning as `D-017`. Placed at tier 2 `taxonomy` deliberately: a board key is a reference mapping, not a rule about documents, so tier 0 may not originate it — the trap `D-005` fell into and v0.2.9 fixed. ***Retired 2026-08-03, kept as history:*** *"When a script and the table disagree, the script is the fact and the table is the bug."* That tie-break settled a disagreement that can no longer happen — neither script holds a coordinate since `PLZG-109`, so there is nothing left to arbitrate and the table is simply the fact. **Kept rather than deleted because it is *why* the coordinates were centralised, and a future hardcoded coordinate is the failure it was written against** — delete the reasoning and the next agent re-adds the hardcoding without knowing what it cost. The DECISION is untouched and stays `LOCKED`: `DELIVERY-COORDINATES` is still the single origin. Only part of the rationale aged out. Raised on GitHub #96 (2026-07-31), which recommended option (2) but explicitly left the call open — *"it is a register edit, so it is the owner's call."* The ruling that selected it is recorded in `specs/sprint-3-loop-plan.json`, T7's note, dated 2026-08-01; applied in `PLZG-137`. The register has no status for "the decision holds, part of its reasoning is now historical" — that gap is raised in [GitHub discussion #95](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/discussions/95), *"Meta-spec review, 2026-07-31: the doc set validates green and still ships false claims"* -- a DISCUSSION, not an issue; there is no issue #95, and a bare `#95` resolves to nothing. | `DELIVERY-COORDINATES` | `LOCKED` |

## Constitution — origin `META-SPEC` (tier 0)

Rules about documents, which is the one thing tier 0 is entitled to originate
(`META-SPEC` §2). This section did not exist before v0.2.10: every prior decision
was about the product or its reference mappings, and the one time a tier-0
document held a product decision — `D-005` — it was moved out. These two are the
clean case that `D-005` was not.

| Id | Decision | Choice | Rationale | Origin | Status |
|---|---|---|---|---|---|
| `D-027` | The `enforcement` axis | Every governed document declares `enforcement` — `enforced` · `asserted` · `intended` · `n/a` — alongside `tier` and `authority`. Per document, valued at its **weakest** state claim. `enforced` requires at least one `live` gate; a `snapshot`-typed gate caps at `asserted` | `tier` says which document wins and `authority` says what it may decide; neither says whether what a document asserts about the world is still true, and that is the gap this set's defects keep falling into. Scoped to **state claims only** — claims about the repository, the board, the running system, the tooling — because applying weakest-claim to decisions would stamp `intended` on `STORYBOARD-W1` and this register, the two documents that define canon; an `intended` value restricts nothing about originating decisions. `enforced` is **empty on day one** and that emptiness is the finding, not a defect: *no governed document in this set is fully machine-backed* is true today and invisible. The snapshot rule falls out of the definitions — `asserted` already means "a human verified it at a stated date, nothing re-checks," which is exactly what committed data is; wrapping it in a CI job re-reads without re-checking. **Known limit:** the validator proves a `weakest_claim` quote is real, never that it is the weakest. Registered in v0.2.10. | `META-SPEC` | `LOCKED` |
| `D-028` | The `delivery` authority | Adds `delivery` to the `authority` vocabulary, licensed at tier 3 to originate **time-boxed operational policy that expires with its artifact** — WIP limits, retry budgets, review gates, forecast blackouts | Closes open conflict §4.10 of [`spec-drivers-v0.2.5.md`](spec-drivers-v0.2.5.md), which has stood since 2026-07-30: the ladder models what the product is (tiers 1–2) and what order it is built in (tier 3), with no authority for *how work is governed while it is built*. Sprint charters were setting budgets and gates nothing else set while declaring `derived` — licensed to originate nothing. Chosen over §4.10's other candidate, an expiring `P-nnn` policy class, on the Sprint 2 evidence: of four policies named, only two were ever exercised, and permanent ids plus expiry machinery for parameters that expire unexercised is a register of things that did not happen. `delivery` instead reuses machinery that exists — one enum value, enforced by the same `x-may-originate` check that closed §4.8. No new id space, no second register. Registered in v0.2.10. | `META-SPEC` | `LOCKED` |

## Not yet authorised

**Empty as of v0.2.7.** Every registered decision now names an entitled origin.

Two batches got here, and both are worth remembering because the failure mode
repeats:

- `D-014` and `D-020` were proposed only by `ALIGNED-SPEC-025` (tier 4, entitled to
  originate nothing). Ratified into `DESIGN-25D` in v0.2.6 — see its
  `## Ratified in v0.2.6` section.
- `D-003`, `D-015`, `D-016`, `D-018`, `D-021`, `D-022`, `D-023` and `D-024` all named
  `PROJECT-OVERVIEW` as origin while it declared `authority: derived` — licensed by
  `META-SPEC` §2 to decide nothing new. Seven of the eight were marked `LOCKED`
  before anyone noticed. Closed in v0.2.7 by
  [`../../docs/designs/platform-decisions.md`](../../docs/designs/platform-decisions.md),
  a tier-2 `implementation` document created to hold exactly this class of decision.
  Tracked as [issue #11](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/11).
  **No decision changed**; only which document is entitled to hold it.

`scripts/validate_specs.py` now fails the build when a document declares `decides:`
without an authority licensed to originate — the check whose absence let the second
batch through. It is a coarse gate: it asks whether an authority may decide
*something*, not whether a given decision falls inside that authority's subject
matter. That second question is still a human one at review time — §4.9 of
[`spec-drivers-v0.2.5.md`](spec-drivers-v0.2.5.md) recorded the one instance the
gate could not see, `D-005` originated by tier-0 `META-SPEC`, resolved in v0.2.9
(issue #18).

When something lands here again, it stays until an entitled document adopts it.
Reasoning being sound is not the same as being authorised; that distinction is the
point of the tier ladder.

---

## Adding a decision

1. Make it at the entitled tier — concept in `STORYBOARD-W1`, implementation in a
   promoted design, taxonomy in `AGENT-DIRECTORY`.
2. Add a row here with the next free `D-nnn`, the origin `doc_id`, and the
   rationale. The rationale is not optional: without it, the next agent "fixes" the
   constraint instead of respecting it.
3. If the decision changes something already `LOCKED`, mark the old row
   `SUPERSEDED` — do not delete it — and bump `doc_set_version` across the set.
4. Add the `D-nnn` to the origin document's `decides:` frontmatter list.

*Doc set version: 0.2.11 · Last updated: August 2026*
