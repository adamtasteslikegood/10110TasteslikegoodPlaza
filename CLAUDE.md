# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Sync the environment before anything else

**Run `git fetch origin && git status` before reading state, planning, or editing — in every checkout, worktree and sandbox.** Nothing below this line is trustworthy from a stale tree, and this repo's whole failure mode is confident claims about state that was true somewhere else.

This is not hypothetical. A `/cs:grill-pm` session on 2026-07-30 planned a "sundown Jira TO" sprint from a checkout **31 commits behind `origin/dev`** and produced three findings that were already fixed upstream — including "`generate_report.py` hardcodes `project = "TO"`", which had already been changed to read `ATLASSIAN_JIRA_PROJECT_KEY`. The board was stale in the other direction: tickets still open for work already merged. Three states had diverged — local tree, `origin/dev`, and the Jira board — and each looked authoritative on its own.

The general rule, which generalises the one `docs/delivery-coordinates.md` earned about boards: **verify the state you are about to assert, against the system that owns it.** A checkout does not own upstream state; a ticket does not own whether code is fixed.

## Repository state

This repo is **a running Godot prototype**. `project.godot` exists and `godot .` opens a walkable office. Three autoloads in `autoload/` plus `scenes/` for world, player, NPC and dialogue panel; `data/agents.json` carrying **132 agents** generated from the submodule by `scripts/generate_agents_json.py` (`D-024`) — never hand-edit it, regenerate; a CI pipeline whose four jobs have all been real gates since v0.2.8; two Atlassian scripts (see § Atlassian coordinates for what they target); and the agent directory as a git submodule at `./claude-code-tresor`, **empty in fresh checkouts**.

Docs split `docs/` (design and reference) from `specs/` (development process), each with its own `README.md` index. Active design is `docs/designs/2.5D-RPG-Prototype.md`; active work plan is `specs/roadmap.md`.

**M1, M3 and M4 are done** — but `specs/task-tracker.md` is the status of record, so check it rather than this line. The next code milestone is the bridge, M5–M8.

## Commands

Every row below was executed against a real checkout. The rule this table exists to enforce is **don't hand anyone a command you haven't run** — which is not the same as "this ecosystem is absent", and earlier versions of this file confused the two by declaring Node absent. `package.json` now exists.

| Command | What it does |
|---|---|
| `scripts/check_sync.sh` | **Run first, every session** — a `SessionStart` hook already does. Fetches and prints ahead/behind vs the branch you integrate into. Warns and exits 0 by design; `--strict` exits 1 when behind, for CI. Equivalent to `git fetch origin && git rev-list --left-right --count HEAD...origin/dev`. |
| `git submodule update --init --recursive` | Populates `claude-code-tresor/`. Empty in fresh checkouts; the generator needs it. |
| `godot .` | Opens the prototype — lobby, corridor, server room; arrows or WASD. |
| `godot --headless --import` | Imports assets. Needed once on a fresh clone before the headless test. |
| `godot --headless tests/smoke_test.tscn` | The build gate. Exits 1 on failure. Run it before pushing Godot changes. |
| `python3 scripts/validate_specs.py` | Governed-document validator. Stdlib only, no install step. Run it before pushing doc changes. |
| `python3 scripts/generate_agents_json.py --check` | Fails if `data/agents.json` drifted from the submodule. Drop `--check` to regenerate. Needs `pyyaml`. |
| `black --check .` | Formatting gate. **Hard-fails CI** — run `black .` before pushing Python. |
| `flake8 . --select=E9,F63,F7,F82` | Syntax errors and undefined names. Also hard-fails; the wider `--max-complexity` pass is advisory. |

`npm test` is real too, but **there is no JavaScript in this repo** — `package.json` is a task-runner facade over the same gates (`npm start` → `godot .`; `npm test` → validate → import → smoke, the order CI uses; `npm run agents:check` left out of `npm test` so a fresh checkout without the submodule or `pyyaml` still goes green). No dependencies, no `node_modules`, nothing to `npm install`. Treat a failure as a failure of the underlying Python or Godot gate and debug it there. CI calls those tools directly, so the facade can never become the only path to a gate.

## Critical architectural reframe (read this before trusting the legacy reference docs)

`docs/designs/2.5D-RPG-Prototype.md` (`PROMOTED`, 2026-04-27) **pivots the prototype from 3D first-person to 2.5D top-down** under a "10x check" scope reduction. Accepted: 2.5D top-down in Godot 2D; one generic agent sprite colour-tinted per department and one silhouette portrait; a Python WebSocket bridge that is **synchronous with timeout protection**, not streaming; a typewriter effect in the UI faking streaming over a full JSON response; and "wait or delegate" UX where short tasks block and long ones become background delegations.

Deferred: true WebSocket streaming, unique sprites per agent, 3D first-person.

## Which document wins — read `specs/meta/` first

`specs/meta/` is the layer above the specs and answers this authoritatively — don't re-derive it from prose here. `META-SPEC.md` is the constitution (tier ladder, `authority` vocabulary, conflict protocol, binding rules for agents). `concept-driver.md` makes `docs/storyboard-week1.md` the **sole origin** of concept and narrative, citable as `SB-01`–`SB-18`. `decision-register.md` holds every locked `D-nnn` — cite these. `spec-drivers-v0.2.5.md` carries the **open-conflict register**; check its §4 before assuming a contradiction is yours to fix.

Short version: tier 0 `specs/meta/` governs · tier 1 `docs/storyboard-week1.md` owns concept · tier 2 `docs/designs/*` owns implementation and `README.md` reconciles both · tier 3 `specs/roadmap.md` + `specs/task-tracker.md` sequence · tier 4 summaries and research are authoritative over nothing. **Lower tier wins.** Never silently reconcile two disagreeing docs — record it in the open-conflict register and raise it.

This has been got wrong at **both** ends of the ladder, and neither was caught by CI. `README.md` declared `authority: derived` while being named as the origin of eight decisions (fixed v0.2.7); `D-005` named tier-0 `META-SPEC` as its origin, though tier 0 never originates product decisions (fixed v0.2.9). Both sets now live in `docs/designs/platform-decisions.md`, which owns nine. The validator only asks whether an authority may originate *something* — never whether a given decision falls inside its subject matter. A human reading the ladder is still the check.

Every governed doc declares `doc_id`/`tier`/`authority`/`status` in YAML frontmatter, indexed in `specs/meta/doc-registry.json`. Run `python3 scripts/validate_specs.py` before pushing; CI runs it as `Validate Specs`. Never add `decides:` to a `derived`, `summary`, `research` or `historical` doc.

`specs/aligned-spec-v0.2.5.md` is **not** the source of truth — tier-4 research, `SUPERSEDED`; its §01.3 fabricated a 14-scene spine contradicting the real storyboard. Cite it for findings, never as law. Legacy 3D node names (CharacterBody3D, Area3D, …) survive inside `specs/roadmap.md` and `specs/task-tracker.md` — read them as their 2D equivalents; the milestone structure still stands. `docs/storyboard-week1.md` stays authoritative even where a beat is written in legacy 3D terms: adding structure is fine, changing a beat needs human sign-off.

## Architecture: the 4 layers

Every planning doc assumes this model, regardless of 2D/3D:

```
Layer 4 — Real agent execution  (EXISTS)   claude-code, gemini-cli, MCP, SSH
Layer 3 — UI-agnostic bridge    (TODO M5–M8) Python WebSocket → agent CLI, sync w/ timeout
Layer 2 — Current frontend      (PARTIAL)  2.5D Godot; one of several swappable frontends
Layer 1 — Data + config         (EXISTS)   submodule → agent .md files → agents.json
```

Layer 2 is named for the **role, not the implementation** (`D-020`) — a CLI harness, a web UI or the eventual 3D world are peers of 2.5D Godot, not replacements for the layer. That is what makes `D-005`, the bridge having zero UI awareness, architecture rather than aspiration. **Swap test:** if replacing Godot with the CLI harness would require any bridge change, the boundary is broken and the change fails review.

## Architecture: the three Godot autoloads

`AgentRegistry` (loads `data/agents.json`), `GameEvents` (global signal bus), `GameState` (unlocks and completed tasks) — all registered in `project.godot` under `[autoload]`. New code plugs into them rather than introducing parallel state. **`.claude/godot-conventions.md` has the table and the interaction pattern.**

## Critical path

The proof-of-concept milestones are **M1 → M4 → M8**. The 2.5D pivot changed M1's *visuals*, not the structure. **M1 done** — `CharacterBody2D`, 8-direction, arrows plus WASD. **M4 done** — proximity-triggered dialogue panel populated from `AgentRegistry`. **M8 next** — player question → WebSocket bridge → real `claude @agent-name` invocation → response rendered with the typewriter effect.

Two of three legs stand, so the risk profile has shifted: protect against **regression**, not just arrival. `tests/smoke_test.tscn` is what protects it — if a change makes that test harder to keep honest, flag it.

## The `claude-code-tresor` submodule

`.gitmodules` registers `claude-code-tresor` against the `adamtasteslikegood` fork, pinned to a commit on its default branch `10110TLGP/dev`. **It is empty in fresh checkouts** — `git submodule update --init --recursive` before reading any agent `.md`.

This fork is the **agent layer for this project** — canonical, not a derivative of `alirezarezvani/claude-code-tresor`. Don't add an `upstream` remote inside it. Bump the pin by working in the fork as its own repo, pushing to its `origin`, then `git add claude-code-tresor` in the parent and committing.

It is the source of truth behind `data/agents.json`; don't copy that data into this tree. `subagents/` holds 133 definitions across ten categories; `agents/` holds the same 8 core roles in Claude Code's **runtime** format — a backward-compat shim, not 8 extra roles. The generator reads `subagents/` only.

**`docs/agent-directory.md` § Agent counts is the authority (`D-017`) — cite it, don't re-derive.** In brief: 141 files = 8 + 133, spanning 133 distinct roles but only 130 distinct slugs (three cross-department collisions), leaving **132 entries** in `data/agents.json`. All those numbers are right; say which you mean.

## CI workflows

`.github/workflows/ci.yml` runs on push/PR to `main` and `dev`. Four jobs:

Top-level `permissions: contents: read`; a job needing more declares its own block rather than widening that one.

- **`Validate Agent Data`** — `generate_agents_json.py --check`. Needs the submodule and `pyyaml`.
- **`Validate Specs`** — `validate_specs.py`. Stdlib only by design.
- **`Lint Python Bridge`** — `black --check .` and `flake8 --select=E9,F63,F7,F82` both **hard-fail**; the wider `--max-complexity` pass is advisory. Run `black .` before pushing. Does *not* check out the submodule.
- **`Export Godot 4 Prototype`** — despite the name it does not export. Installs Godot 4.7.1, imports, and runs `tests/smoke_test.tscn`. "Runs" is load-bearing: the test adds the scene to the tree so `_ready()` fires, because `instantiate()` alone leaves `@onready` paths unresolved and sails past renamed nodes. Feel values are asserted as **bands derived from the scene at runtime**, never equalities — an `== 48.0` check would redden every tuning pass, which is how a check gets deleted. It passed vacuously until v0.2.8.

`.github/workflows/claude-review.yml` is the one independent reviewer on PRs — advisory (`continue-on-error`), never required. Read its `on:` block rather than assuming, and note **it cannot review changes to itself**: `claude-code-action` refuses when the workflow differs from the default branch's copy *and still reports a fast green*, so read the job log, not the check mark.

The `gemini-*.yml` suite was removed 2026-07-28 having never completed a review — it hung installing the code-review extension and timed out every run. Don't recover it from history; start fresh.

## Python scripts (Atlassian glue)

`generate_report.py` queries Jira for the last 7 days, buckets by status, and writes `report.md`; `post_to_confluence.py` converts that to HTML and posts it under a parent page. Both read `./.env` directly (no python-dotenv). **`.env.example` documents every variable they read and which ones nothing reads — copy it, don't retype it here.** Neither raises `KeyError` any more: since 2026-07-28 both name the missing variables and exit 1.

**Which project and space each script targets is stated once, in § Atlassian coordinates — read that. Do not add a third copy here.** **Neither script hardcodes a coordinate any more:** `generate_report.py` reads `ATLASSIAN_JIRA_PROJECT_KEY` and builds `project = "<key>" AND updated >= -7d`; since `PLZG-109` `post_to_confluence.py` reads `ATLASSIAN_CONFLUENCE_PARENT_PAGE_ID` and resolves the space from that page. The target is whatever the environment says, so a wrong report means checking the environment, not the source. There is **no fallback** — an unreachable parent exits 1; the removed fallback used to write into a sibling product's space, which is how reports ended up there.

The committed `report.md` is still headed "Status Report - 10110 Tasteslikegood Plaza" over Vegangenius Chef rows, because it was generated before that change. It carries raw Jira issue titles, so committing it is a disclosure decision, not a formatting one — see § Atlassian coordinates for why it is untracked.

## Doc layout — what's where

Root holds the entry points: `README.md` (pitch, 4-layer architecture, department/color table, attribution), `QUICKSTART.md`, `CONTRIBUTING.md`, `CHANGELOG.md` ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — add under `## [Unreleased]`), `LICENSE` (MIT), and this file.

`docs/` is design and reference; `specs/` is development process. Both carry their own `README.md` folder index — use those instead of maintaining a third inventory here. What those indexes won't tell you:

| File | Why it matters |
|---|---|
| `docs/designs/2.5D-RPG-Prototype.md` | **Active design** — the 2.5D pivot. |
| `docs/designs/platform-decisions.md` | **Platform authority**, ten decisions (`D-003`, `D-005`, `D-015`, `D-016`, `D-018`, `D-021`–`D-024`, `D-029`). Scope test: would it survive replacing the whole frontend? If it dies with the 2.5D prototype it belongs in the design doc. |
| `docs/agent-directory.md` | **Taxonomy authority (`D-017`)** — every agent count derives from here. |
| `docs/delivery-coordinates.md` | **Atlassian taxonomy authority (`D-026`)** — every Jira key, board role, space and page id. |
| `specs/meta/` | **Start here.** See the section above. |
| `specs/roadmap.md`, `specs/task-tracker.md` | Milestone structure is authoritative; the 3D node names inside are deprecated. |
| `specs/aligned-spec-v0.2.5.md` | Tier-4 research, `SUPERSEDED`. Cite for findings, never as law. |
| `specs/branching-strategy.md` | Intended policy only — says "ClaudeForge", names workflows this repo lacks. |

`Docs/` — **capital D, a different directory** that an agent will conflate with `docs/` on a case-sensitive filesystem. It holds first-run planning material as a tier-4 `HISTORICAL` signpost; its task tracker and 3D references are superseded.

**`validate_specs.py` governs `docs/`, `specs/`, `Docs/` and the root `README.md` — and nothing else.** So anything added under `Docs/` still needs frontmatter and a registry entry, while `.claude/` needs neither. `.claude/` holds agent configuration: `settings.json` (marketplace, project-scope plugins, the `SessionStart` sync hook), `skills/`, plus `gbrain.md`, `godot-conventions.md` and `pr-workflow.md` — the reference material split out of this file under `PLZG-107`. `.claude/README.md` describes the set.

Also: `report.md` is generated output of `generate_report.py` — commit it only deliberately. `docs/.gdignore` keeps Godot from importing the docs tree as game assets; don't delete it.

## The two project-local skills

Both live in `.claude/skills/` because they encode how *this* repo breaks, which is not what a generic skill knows.

- **`review-specs`** — the review pass for a PR or branch here, and the interactive counterpart to `claude-review.yml`. Its highest-yield check is repository-state claims, because that is the defect class this document set actually produces.
- **`grill-with-specs`** — points the `grill-with-docs` plugin at this repo. Upstream it is anchored on a `CONTEXT.md` glossary and `docs/adr/`, and **creates both lazily when missing**. Neither exists here and neither should — the equivalents are `META-SPEC.md` §2 and `decision-register.md`. Unredirected, the plugin would start a second decision store beside `specs/meta/`: the exact fork the register prevents.

Adapt a plugin from inside `.claude/skills/`, never by editing the plugin. Plugins live in `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` and are replaced wholesale on version bump, so an edit there is silently lost.

## Document conventions

- **Department / colour scheme:** nine departments map to nine office floors (now "rooms" in 2.5D), each with a fixed hex colour. The mapping is canonical and lives in **two** places — `README.md` and `docs/agent-directory.md`. Change a colour or floor assignment in one and you must change the other.

- **This file is held to the ~200-line instruction budget** — `META-SPEC` §6 "Conventions for AI-consumable specs", item 6. (Not a `§6.6`; that subsection does not exist, though the mis-citation is propagated in issue #37's title.) It drifted past the budget three times, each for good per-change reasons — which is how a heuristic quietly stops being followed — reaching **374 lines** before `PLZG-107` paid the debt down by moving reference material to `.claude/gbrain.md`, `.claude/godot-conventions.md` and `.claude/pr-workflow.md`. **Nothing in CI enforces this.** If a change would push the file over, cut something or move it behind a pointer; do not raise the budget.
- Most reference and process docs (under `docs/` and `specs/`) end with `*Last updated: <month> 2026*`. Update that line when editing them.
- `docs/agent-directory.md` contains unresolved template artifacts (`{{rolels}}`, `{{charactors}}`, `{{roles}}`, etc.) left over from the upstream fork. Don't propagate them into new text; clean up the section you're editing.
- Attribution: the project is an MIT-licensed adaptation of [alirezarezvani/claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor), via the [adamtasteslikegood/claude-code-tresor](https://github.com/adamtasteslikegood/claude-code-tresor) fork. Preserve the attribution block at the bottom of `README.md` and `docs/agent-directory.md`.

## Branching

`feature/* | fix/* | hotfix/* → dev → main`, Conventional Commits (`type(scope): subject` — lowercase, imperative, no trailing period), **merge commits — squash and rebase are disabled deliberately (`D-023`)**, so reverting needs `git revert -m 1`. New work targets `dev`; `dev` → `main` on release. `CONTRIBUTING.md` has the everyday flow, the commit/push cadence, and the rule that a PR stays yours until it merges. `specs/branching-strategy.md` has branch protection, required checks and CODEOWNERS gating — but it says "ClaudeForge" throughout and names workflows this repo doesn't have, so it is intended policy, not active rules. `feature/TO-1-prototype-initialization` is a long-lived branch carrying shell/Python tooling under `scripts/` — check it before adding a new `scripts/` file, the equivalent may already exist there.

## Working a PR — instructions for you, not for contributors

**`.claude/pr-workflow.md` is the full procedure. Read it before touching a PR.** The
rules that are non-negotiable and most often skipped: every PR title carries a
`PLZG-###` key or the board never sees it — file an issue first, never invent a key;
every review comment gets a fix commit or a concrete technical rebuttal, verified
against the file rather than the comment; replies posted on Adam's behalf are signed
with model and `${CLAUDE_CODE_SESSION_ID:0:7}`; and a PR stays yours until it merges.
Keep a PR to one concern.

## Atlassian coordinates

**`docs/delivery-coordinates.md` is the source of truth** (`D-026`) — Jira keys, board roles, the Confluence space and parent page id, and the keys belonging to the owner's *other* repos. Do not restate a key here or in any guide; cite it. Since `PLZG-109` **neither script holds a coordinate** — both read the environment — so no script is a second source; the deployed value is the environment, then `.env`. Two rules you need too often to look up: every PR title carries a **`PLZG-###`** key or the board never sees it, and `TO` is **deprecated** — read-only until archival, never filed into.

## When you're asked to add Godot code

**`.claude/godot-conventions.md` has the tree layout, the autoload wiring and the
`bridge/` plan.** Two rules that outrank convenience: `data/agents.json` is generated —
never hand-edit it, and an NPC scene stores an `agent_id` and nothing else (`D-016`).
`D-005` is the hard gate on the bridge: it must not learn that Godot, scenes or dialogue
panels exist. Swap test — if replacing the frontend with a CLI harness would require a
bridge change, the boundary is broken.

## Behavioral Guidelines

- **Think before coding.** Find the entitled document first — `specs/meta/` says which wins. Cite the `D-nnn` or `SB-nn` you act on.
- **Simplicity first.** Don't invent infrastructure — run the command before recommending it. Saying "there is no Node here" is also inventing infrastructure, in the negative direction, and it was wrong.
- **Surgical changes.** Never silently reconcile two disagreeing documents — record it in the open-conflict register and raise it. Don't duplicate state: agent facts live in `data/agents.json`, feel values in the scene, project keys in the scripts, and the test derives its bounds from the scene rather than copying them.
- **Know whose rule it is.** Before enforcing a constraint against a request, check who set it. Owner decisions and `D-nnn` bind; an agent's suggestion written up in a repo file is rationale to weigh, not a gate to refuse with.
- **Goal-driven execution.** M8 is the goal, `tests/smoke_test.tscn` the evidence. `META-SPEC` §5.8 requires machine-checkable acceptance, so "done" means a gate went green, not that the work looked finished. The user-level `karpathy-guidelines` skill expands on these principles if installed — a per-machine convenience, not a dependency of this repo.

## GBrain semantic search

**`.claude/gbrain.md` is the whole contract** — coverage, the one-source-per-subtree
rule, and why `report.md` must stay untracked. It is a per-machine index: nothing in CI
touches it and a contributor without it loses no gate. Prefer it over Grep when the
question is semantic; Grep stays right for exact strings and globs.

Two traps worth carrying here: **sync with `--strategy auto`, never `--strategy code`**
(one shared `last_commit` bookmark means a code-only run permanently skips doc edits,
and `/sync-gbrain` issues `code` on its own), and **verify a `D-nnn` by Reading the
register, not from a search hit** — adjacent table rows look near-identical to an
embedding.
