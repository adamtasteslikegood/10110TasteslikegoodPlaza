# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo is **a running Godot prototype**. `project.godot` exists and `godot .` opens a walkable office:

- Three autoloads in `autoload/`, registered in `project.godot`, plus `scenes/` for the world, player, NPC and dialogue panel — see the two architecture sections below.
- `data/agents.json` — **132 agents**, generated from the submodule by `scripts/generate_agents_json.py` (`D-024`). Never hand-edit it; regenerate.
- A working CI pipeline (`.github/workflows/ci.yml`) — four jobs, all of them real gates since v0.2.8.
- Two Atlassian integration scripts (`generate_report.py`, `post_to_confluence.py`) wired to a Jira project keyed `TO` and a Confluence parent page.
- The upstream agent directory wired in as a git submodule at `./claude-code-tresor` (relative URL, not initialized in fresh checkouts — see below).
- A consolidated documentation layout: `docs/` for design and reference, `specs/` for development-process files. Each folder has its own `README.md` describing what belongs there. The active design is `docs/designs/2.5D-RPG-Prototype.md`; the active work plan is `specs/roadmap.md`.

**M1, M3 and M4 are done** (`specs/task-tracker.md` is the status of record — check it rather than this line). The next code milestone is the bridge, M5–M8.

## Commands

Godot commands are real. Node/npm infrastructure does not exist — never invent `npm test`, `npm run build`, or a `package.json` script. This table is everything that actually runs:

| Command | What it does |
|---|---|
| `git submodule update --init --recursive` | Populates `claude-code-tresor/`. Empty in fresh checkouts; the generator needs it. |
| `godot .` | Opens the prototype — lobby, corridor, server room; arrows or WASD. |
| `godot --headless --import` | Imports assets. Needed once on a fresh clone before the headless test. |
| `godot --headless tests/smoke_test.tscn` | The build gate. Exits 1 on failure. Run it before pushing Godot changes. |
| `python3 scripts/validate_specs.py` | Governed-document validator. Stdlib only, no install step. Run it before pushing doc changes. |
| `python3 scripts/generate_agents_json.py --check` | Fails if `data/agents.json` drifted from the submodule. Drop `--check` to regenerate. Needs `pyyaml`. |
| `black --check .` | Formatting gate. **Hard-fails CI** — run `black .` before pushing Python. |
| `flake8 . --select=E9,F63,F7,F82` | Syntax errors and undefined names. Also hard-fails; the wider `--max-complexity` pass is advisory. |

## Critical architectural reframe (read this before trusting the legacy reference docs)

`docs/designs/2.5D-RPG-Prototype.md` has status `PROMOTED` and a `/plan-ceo-review` header dated 2026-04-27. It **pivots the prototype from 3D first-person to 2.5D top-down** (Pokemon / Stardew Valley style) under a "10x check" scope reduction. Accepted scope from that plan:

- 2.5D top-down (Godot 2D), not first-person 3D.
- One generic agent sprite, color-tinted per department; one generic silhouette portrait for dialogue.
- Python WebSocket bridge enforces **synchronous execution with timeout protection** (not streaming).
- Godot UI fakes streaming with a typewriter effect over a full JSON response.
- "Wait or delegate" UX — short tasks block, long tasks become background delegations.

Deferred: true WebSocket streaming, unique sprites per agent, 3D first-person.

## Which document wins — read `specs/meta/` first

`specs/meta/` is the layer above the specs and answers this authoritatively. Don't re-derive it from prose here:

- `specs/meta/META-SPEC.md` — the constitution. Tier ladder, the `authority` vocabulary, the conflict protocol, and the binding rules for agents (bridge UI-agnosticism, cite-the-source-doc, don't-invent-infrastructure).
- `specs/meta/concept-driver.md` — `docs/storyboard-week1.md` is the **sole origin** of concept and narrative decisions. Scenes are citable as `SB-01`–`SB-18`.
- `specs/meta/decision-register.md` — every locked decision as `D-nnn`. Cite these.
- `specs/meta/spec-drivers-v0.2.5.md` — what v0.2.5 delivers, the traceability chain, and the **open-conflict register**. Check §4 before assuming a contradiction is yours to fix.

Short version: tier 0 `specs/meta/` governs · tier 1 `docs/storyboard-week1.md` owns concept · tier 2 `docs/designs/*` owns implementation and `README.md` reconciles both · tier 3 `specs/roadmap.md` + `specs/task-tracker.md` sequence · tier 4 summaries and research are authoritative over nothing. **Lower tier wins.** Never silently reconcile two disagreeing docs — record it in the open-conflict register and raise it.

`README.md` reconciles; it does not decide. It declared `authority: derived` while being named as the origin of eight decisions, and the set validated green for two releases before anyone noticed. Fixed in v0.2.7 — the eight moved to `docs/designs/platform-decisions.md`, and the validator now fails the build when a document declares `decides:` without an authority licensed to originate. Don't add a `decides:` list to a `derived`, `summary`, `research`, or `historical` document; it will not pass CI.

`D-005` joined them in v0.2.9 for the mirror-image reason at the other end of the ladder: it named tier-0 `META-SPEC` §5.1 as its origin, and §2 of that same document says tier 0 originates rules about documents and **never product decisions**. `platform-decisions.md` now owns nine. Note what this class costs — no validator catches it. The §4.8 gate asks whether an authority may originate *something*; it cannot ask whether a given decision falls inside that authority's subject matter. Both were found by a human reading the ladder, not by CI.

Every governed doc declares `doc_id`/`tier`/`authority`/`status` in YAML frontmatter, validated against `specs/meta/spec-frontmatter.schema.json` and indexed in `specs/meta/doc-registry.json`. Run `python3 scripts/validate_specs.py` (stdlib only) before pushing; it runs in CI as `Validate Specs`.

`specs/aligned-spec-v0.2.5.md` is **no longer the source of truth** — it is a tier-4 research input (`status: SUPERSEDED`). Its normative content was promoted into `specs/meta/`; its §01.3 fabricated a 14-scene spine that contradicts the real storyboard. Cite it for findings and rationale, not as law.

The older reference docs still contain 3D first-person specifics:
- `specs/roadmap.md`, `specs/task-tracker.md` — 3D-specific node names (CharacterBody3D, FPS demo, CSGBox3D, Area3D, NavigationRegion3D) are deprecated. Treat as 2D equivalents (CharacterBody2D, TileMap, Area2D, NavigationRegion2D). Milestone structure (M1/M4/M8) still stands.
- `docs/quick-reference.md` — pitch line updated; the rest still directionally correct.
- `docs/storyboard-week1.md` — the storyboard/concept is **authoritative** (tier 1, `authority: concept`); only occasional visual descriptions (e.g. a "3D flyover" beat) are stylistic legacy. Adding structure is fine; changing a beat is a concept change needing human sign-off.
- `README.md` pitch has been rewritten to 2.5D-first.

## Architecture: the 4 layers

Every planning doc assumes this model, regardless of 2D/3D:

```
Layer 4 — Real agent execution    (EXISTS) claude-code, gemini-cli, MCP, SSH
Layer 3 — UI-agnostic bridge       (TODO, Phase 2) Python WebSocket → spawns agent CLI, synchronous w/ timeout
Layer 2 — Current frontend         (TODO, Phase 1) — today 2.5D Godot; one of several swappable frontends
Layer 1 — Data + config            (EXISTS upstream as submodule) 133 agent .md files → agents.json
```

Layer 2 is deliberately named for the **role, not the implementation** (`D-020`). A CLI harness, a web UI, or the eventual 3D world are peers of 2.5D Godot, not replacements for the layer. That is what makes `D-005` — the bridge has zero UI awareness — architecture rather than aspiration. **Swap test:** if replacing Godot with the CLI harness would require any bridge change, the boundary is broken and the change fails review.

## Architecture: the three Godot autoloads

All three exist and are registered in `project.godot` under `[autoload]`. New code plugs into them rather than introducing parallel state:

| Autoload | File | Role |
|---|---|---|
| `AgentRegistry` | `autoload/AgentRegistry.gd` | Loads `data/agents.json` at startup; `get_agent(id)` returns the dict |
| `GameEvents` | `autoload/GameEvents.gd` | Global signal bus: `npc_approached`, `npc_left`, `task_completed`, `floor_unlocked` |
| `GameState` | `autoload/GameState.gd` | Tracks `unlocked_floors`, `completed_tasks`, `player_config`; gates doors via `is_unlocked()` |

Interaction pattern: NPC `Area` (or `Area2D` under the 2.5D plan) fires `GameEvents.npc_approached` → HUD listens → populates dialogue panel from `AgentRegistry.get_agent(agent_id)`. Door triggers consult `GameState.is_unlocked(floor_id)`. Completing tutorial tasks calls `GameState.complete_task(id)`, which checks an unlock-gate table and emits `floor_unlocked`.

## Critical path

The proof-of-concept milestones from the roadmap are **M1 → M4 → M8**. The 2.5D pivot changes the *visuals* of M1 (top-down sprite instead of FPS controller) but not the milestone structure:

- **M1 — done (v0.2.8).** Godot 4 project + player navigates the world. `scenes/player/player.gd`, `CharacterBody2D`, 8-direction, arrows plus WASD.
- **M4 — done (v0.2.8).** Proximity-triggered dialogue panel populated from `AgentRegistry`. `scenes/npc/agent_npc.gd` fires the signal, `scenes/hud/dialogue_panel.gd` renders it.
- **M8 — next.** Player question → WebSocket bridge → real `claude @agent-name` CLI invocation → response rendered in dialogue panel (typewriter effect over the full JSON, per the promoted plan).

Two of the three legs are standing, so the risk profile has shifted: the thing to protect now is **regression**, not just arrival. `tests/smoke_test.tscn` is what protects it — if a change makes that test harder to keep honest, flag it.

## The `claude-code-tresor` submodule

`.gitmodules` registers `claude-code-tresor` pointing at `https://github.com/adamtasteslikegood/claude-code-tresor.git`, pinned to commit `b7ec149…` (head of the fork's `10110TLGP/dev`, which is its default branch). **It is empty in fresh checkouts** — initialize it before reading the agent `.md` files:

```bash
git submodule update --init --recursive
```

This fork is the **agent layer for this project** — treat it as the canonical source, not as a derivative of `alirezarezvani/claude-code-tresor`. Don't add an `upstream` remote pointing at the parent project inside the submodule; this project's agent definitions evolve independently. Bumps to the pinned commit happen by working in the fork directly, pushing to its `origin`, then back in the parent repo:

```bash
cd claude-code-tresor
# work on the fork as its own repo — branch, commit, push to origin
cd .. && git add claude-code-tresor && git commit -m "build: bump claude-code-tresor submodule"
```

This submodule is the source of truth for the agent definitions that need to become `data/agents.json` for M3. Don't duplicate that data into this repo's tree. Layout inside the submodule:

- `subagents/` — 133 agent definitions nested `<dept>/<subcat>/<name>/agent.md` across ten categories (`engineering/`, `design/`, `marketing/`, `product/`, `leadership/`, `operations/`, `research/`, `ai-automation/`, `account-customer-success/`, `core/`), plus an `AGENT-INDEX.md`.
- `agents/` — the same 8 core roles (`systems-architect`, `config-safety-reviewer`, `root-cause-analyzer`, `security-auditor`, `test-engineer`, `performance-tuner`, `refactor-expert`, `docs-writer`) in Claude Code's **runtime** format, not 8 additional roles.

**141 files = 8 + 133, spanning 133 distinct roles.** Both numbers are right; say which you mean. Upstream v2.7.0 made `subagents/` PRIMARY and left `agents/` as a backward-compat shim (symlinks plus stale pre-v2.7.0 flat files), so the generator reads `subagents/` only. Separately, those 133 files carry just **130 distinct slugs** — three cross-department collisions, curated in `scripts/generate_agents_json.py`, leaving **132 entries** in `data/agents.json`. See `docs/agent-directory.md` § Agent counts.

## CI workflows

`.github/workflows/ci.yml` runs on push/PR to `main` and `dev`. Four jobs:

The workflow declares `permissions: contents: read` at the top level — every job only reads the repo, and without it `GITHUB_TOKEN` inherits the repository default (CodeQL flags this as `actions/missing-workflow-permissions`, one alert per job). A job that later needs more should declare its own block rather than widening the top-level one. `claude-review.yml` declares permissions per job instead.

- **`Validate Agent Data`** — runs `python3 scripts/generate_agents_json.py --check`. Needs the submodule (`submodules: recursive`) and `pyyaml`. Fails if `data/agents.json` has drifted from the submodule.
- **`Validate Specs`** — runs `python3 scripts/validate_specs.py`. Stdlib only, no `pip install` step by design. Hard-fails when a governed doc is missing frontmatter, is unregistered in `specs/meta/doc-registry.json`, declares an authority the registry doesn't grant, links to a file that doesn't exist, disagrees about `doc_set_version`, or indexes a scene id the storyboard doesn't carry.
- **`Lint Python Bridge`** — installs `flake8 black websockets`, then:
  - `black --check .` — **hard fail.** The step carries no `continue-on-error` and no `|| true`, so unformatted Python reddens the build. Run `black .` before pushing.
  - `flake8 . --select=E9,F63,F7,F82` (hard fail on syntax errors / undefined names)
  - `flake8 . --exit-zero --max-complexity=10 --max-line-length=127` (advisory)
  This job does **not** check out the submodule, so it only ever sees this repo's own Python. New Python here has to pass both hard gates.
- **`Export Godot 4 Prototype`** — despite the name, it does not export. It installs Godot 4.7.1 from the `godotengine/godot` GitHub release, runs `godot --headless --import`, then runs `tests/smoke_test.tscn`, which asserts the 132 agents loaded, the Core eight are gold, `tools` is still a list, and `main.tscn` runs. "Runs" is load-bearing: the test adds the scene to the tree so `_ready()` actually fires, because `instantiate()` alone leaves `@onready` paths unresolved and sails past renamed nodes and runtime errors. It also guards the two playtested feel values (NPC proximity radius, typewriter rate) as **bands derived from the scene at runtime**, never as equalities — an `== 48.0` check would redden every future tuning pass, which is how a check gets deleted. No export templates are downloaded — a web export would pull ~1GB per run for an artifact nothing consumes yet. It echoed a string and passed vacuously until v0.2.8.

`.github/workflows/claude-review.yml` is the one independent reviewer wired into PRs. It is advisory (`continue-on-error`) and never a required check. Read its `on:` block for when it fires rather than assuming — that is the only copy of that fact. **It cannot review changes to itself** — `claude-code-action` refuses to run when the workflow differs from the copy on the default branch, and still reports a fast green, so read the job log rather than the check mark on any PR that edits it.

The `gemini-*.yml` suite that used to sit here was removed on 2026-07-28. It never completed a single review on this repo: it hung during the code-review extension install and was killed by its own timeout on every run. Recovering it from git history is not a starting point — start fresh.

## Python scripts (Atlassian glue)

Both top-level Python scripts depend on a `.env` file (gitignored) with:

```
ATLASSIAN_API_TOKEN_BASE64_USEREMAIL=<base64(email:token)>
ATLASSIAN_URL=<host, no scheme>
```

- `generate_report.py` — queries Jira project `TO` for issues updated in the last 7 days, buckets them by status (done / in progress / blocked / todo), and writes `report.md`.
- `post_to_confluence.py` — converts `report.md` to HTML and posts it as a child of Confluence page `15925249` (fallback `15695959`).

These read `./.env` directly (no python-dotenv); they'll crash with a `KeyError` if either var is missing. The lint job tolerates them as-is.

## Doc layout — what's where

Top level holds the entry-point docs every contributor (human or agent) is expected to read first:

- `README.md` — project pitch, 4-layer architecture, department/color table, attribution. The canonical project overview.
- `QUICKSTART.md` — clone, init the submodule, set up `.env`, run the Atlassian scripts, where to go from there.
- `CONTRIBUTING.md` — branching flow, Conventional Commits, PR workflow. Points at `specs/branching-strategy.md` for the full policy.
- `CHANGELOG.md` — project changelog in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Add entries under `## [Unreleased]` as work lands; promote to a versioned section at release time.
- `CLAUDE.md` — this file. Agent-facing repo guide.
- `LICENSE` — MIT.

`docs/` — design and reference (the *what* and *why*, slow-changing). See `docs/README.md` for the folder index.

- `docs/designs/2.5D-RPG-Prototype.md` — **active design.** The 2.5D top-down pivot.
- `docs/designs/platform-decisions.md` — **platform authority.** Engine, bridge transport, agent data layer, licence, submodule and merge policy (`D-003`, `D-005`, `D-015`, `D-016`, `D-018`, `D-021`–`D-024` — nine as of v0.2.9). Scope test: would the decision survive replacing the whole frontend? If it dies with the 2.5D prototype it belongs in the design doc instead.
- `docs/storyboard-week1.md` — Day 0 / Day 1 / Day 2 tutorial narrative beats.
- `docs/quick-reference.md` — one-page summary: build order, autoloads, department table.
- `docs/agent-directory.md` — taxonomy of the 133 agent roles across nine departments plus Core. **Taxonomy authority (`D-017`)** — every other count in the repo derives from here.
- `docs/assets/` — `plaza_build_steps.html`, `plaza_godot_architecture.svg`.

`specs/` — development process (the *how* and *when*, action-oriented). See `specs/README.md` for the folder index.

- `specs/meta/` — **start here.** The constitution, the frontmatter schema, the doc registry, the concept driver, the decision register, and the v0.2.5 driver doc. See the section above.
- `specs/aligned-spec-v0.2.5.md` — tier-4 research input, `SUPERSEDED`. Retained for its findings, the Document A bridge architecture, and the Document B taxonomy.
- `specs/roadmap.md` — M1 → M8 milestone structure (still authoritative); 3D-specific node names inside milestone bodies are deprecated.
- `specs/task-tracker.md` — working checklist across all phases; same 3D-deprecation caveat as `roadmap.md`.
- `specs/branching-strategy.md` — branch protection, status checks, CODEOWNERS gating. Still says "ClaudeForge" and references workflows that don't exist here; treat as intended policy until those land.

`Docs/` — **capital D, a different directory.** On a case-sensitive filesystem `docs/` and `Docs/` coexist and an agent will conflate them. `Docs/files/` holds the first-run planning material as a tier-4 `HISTORICAL` signpost; the storyboard and concept there are largely unchanged, but its task tracker and 3D references are superseded. `scripts/validate_specs.py` governs `docs/`, `specs/`, `Docs/` and the root `README.md` — so anything you add under `Docs/` still needs frontmatter and a registry entry.

`.claude/` — agent configuration, deliberately **not** a governed tree (the validator does not scan it, so no frontmatter needed). Read `.claude/README.md` before touching it; it records why only a small, justified set of skill plugins is enabled and which two are excluded on purpose. `.claude/skills/review-specs/` is a project-local skill: the governed-document review pass to use when reviewing a PR or branch here.

Other top-level artifacts:

- `report.md` — generated output of `generate_report.py`; commit it only deliberately.
- `docs/.gdignore` — keeps Godot from importing the documentation tree as game assets. Don't delete it; a new docs subfolder full of `.html`/`.svg` will otherwise show up in the resource filesystem.

## Department / color scheme

Nine departments map to nine office floors (now "rooms" in 2.5D), each with a fixed hex color. The mapping is canonical and appears in two places (`README.md` and `docs/agent-directory.md`). If you change a color or floor assignment, update both to keep them in sync.

## Document conventions

- Most reference and process docs (under `docs/` and `specs/`) end with `*Last updated: <month> 2026*`. Update that line when editing them.
- `docs/agent-directory.md` contains unresolved template artifacts (`{{rolels}}`, `{{charactors}}`, `{{roles}}`, etc.) left over from the upstream fork. Don't propagate them into new text; clean up the section you're editing.
- Attribution: the project is an MIT-licensed adaptation of [alirezarezvani/claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor), via the [adamtasteslikegood/claude-code-tresor](https://github.com/adamtasteslikegood/claude-code-tresor) fork. Preserve the attribution block at the bottom of `README.md` and `docs/agent-directory.md`.

## Branching

The intended flow is `feature/* | fix/* | hotfix/* → dev → main` with Conventional Commits and squash merges. What's actually in the remote right now:

- `main` — production line; has the Atlassian scripts, CI, and the submodule.
- `dev` — **integration branch**, caught up to `main` via PR #3. New work targets `dev`; `dev` → `main` on release.
- `feature/TO-1-prototype-initialization` — long-lived feature branch with extensive `scripts/` and `scripts/scripts-bakup/` shell/Python tooling (Jira PM daemon, ahead-behind scripts, etc.).
- Task-assigned working branches (e.g. `claude/...`) — develop here, commit, push, open a draft PR. The session-assigned branch is specified in the system prompt.

`specs/branching-strategy.md` describes branch protection rules, required status checks, and CODEOWNERS gating — but the doc still says "ClaudeForge" throughout and references workflows (`pr-into-dev.yml`, `dev-to-main.yml`, `release.yml`) that **don't exist in this repo**. Treat it as intended policy for once code lands, not active rules. The Conventional Commits format (`type(scope): subject`, lowercase, imperative, no trailing period) is worth following now — see `CONTRIBUTING.md` for the everyday flow.

## When you're asked to add Godot code

The layout below is what exists (except `bridge/`, which is still `TODO`). Extend it rather than inventing a new one:

```
project.godot           # [autoload] block registers all three singletons
data/agents.json
autoload/
  AgentRegistry.gd      # + .uid — Godot 4.4+ writes a .uid beside every script; commit it
  GameEvents.gd
  GameState.gd
scenes/                 # each .tscn with its .gd beside it (D-025)
  main.tscn             # run/main_scene — what `godot .` opens
  world/office.tscn     # lobby, corridor, server room
  player/player.tscn    # CharacterBody2D, 8-direction, arrows + WASD
  npc/agent_npc.tscn    # stores an agent_id and nothing else
  hud/dialogue_panel.tscn
tests/
  smoke_test.tscn       # headless build gate — see the CI section
scripts/                # Python tooling only (validate_specs.py, generate_agents_json.py)
bridge/                 # TODO (M5–M8)
  bridge.py             # Python WebSocket server (ws://localhost:8765), synchronous-with-timeout per the 2.5D plan
```

Godot rewrites `.tscn` files wholesale when a scene is saved in the editor, so a comment placed next to a tuned value there does not survive the next time anyone opens it. Put the constraint in `tests/smoke_test.gd` instead — that is why the feel values are asserted rather than annotated.

`data/agents.json` already exists — 132 agents, generated by `scripts/generate_agents_json.py` (M3, `D-024`). Never hand-edit it and never type agent facts into a `.tscn`: an NPC scene stores an `agent_id` and nothing else, and everything shown comes from `AgentRegistry` at runtime. That is what `D-016` protects.

The next code task is the bridge (M5–M8). `D-005` is the hard gate there: the bridge must not learn that Godot, scenes, or dialogue panels exist. If swapping the frontend for a CLI harness would require a bridge change, the boundary is broken.

Note that there is already a `scripts/` directory worth of bash/Python tooling on the `feature/TO-1-prototype-initialization` branch. Before adding new `scripts/` files on `main`, check whether something equivalent already exists on that branch.

## Behavioral Guidelines

Four working principles, each with the form it takes in this repo:

- **Think before coding.** Find the entitled document before writing anything — `specs/meta/` says which one wins. Cite the `D-nnn` or `SB-nn` you're acting on.
- **Simplicity first.** Don't invent infrastructure. There is no `npm test` here; the Commands table above is the complete list of what runs. A command that isn't in it needs to be verified, not assumed.
- **Surgical changes.** Never silently reconcile two disagreeing documents — record it in the open-conflict register and raise it. Don't duplicate state: agent facts live in `data/agents.json`, feel values live in the scene, and the test derives its bounds from the scene rather than copying them.
- **Goal-driven execution.** M8 is the goal; `tests/smoke_test.tscn` is the evidence. `META-SPEC` §5.8 requires acceptance criteria to be machine-checkable, so "done" means a gate went green, not that the work looked finished.

If the user-level `karpathy-guidelines` skill is installed (`~/.claude/skills/karpathy-guidelines/SKILL.md`) it expands on these; it is a per-machine convenience, not a dependency of this repo.
