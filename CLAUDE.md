# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo is **a running Godot prototype**. `project.godot` exists and `godot .` opens a walkable office:

- Three autoloads in `autoload/`, registered in `project.godot`, plus `scenes/` for the world, player, NPC and dialogue panel — see the two architecture sections below.
- `data/agents.json` — **132 agents**, generated from the submodule by `scripts/generate_agents_json.py` (`D-024`). Never hand-edit it; regenerate.
- A working CI pipeline (`.github/workflows/ci.yml`) — four jobs, all of them real gates since v0.2.8.
- Two Atlassian integration scripts (`generate_report.py`, `post_to_confluence.py`). For which Jira project and Confluence space they target, see § Atlassian coordinates.
- The upstream agent directory wired in as a git submodule at `./claude-code-tresor` (relative URL, not initialized in fresh checkouts — see below).
- A consolidated documentation layout: `docs/` for design and reference, `specs/` for development-process files. Each folder has its own `README.md` describing what belongs there. The active design is `docs/designs/2.5D-RPG-Prototype.md`; the active work plan is `specs/roadmap.md`.

**M1, M3 and M4 are done** (`specs/task-tracker.md` is the status of record — check it rather than this line). The next code milestone is the bridge, M5–M8.

## Commands

Every row below was executed against a real checkout. The rule this table exists to enforce is **don't hand anyone a command you haven't run** — which is not the same as "this ecosystem is absent", and earlier versions of this file confused the two by declaring Node absent. `package.json` now exists.

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

`npm test` is real too — but read `package.json` before assuming what that buys you. **There is no JavaScript in this repo.** `package.json` is a task-runner facade over the same gates: `npm start` → `godot .`; `npm test` → `validate` → `import` → `smoke`, the order CI uses; `npm run validate` / `import` / `smoke` → the single rows above; `npm run agents:check` → the generator check, deliberately left out of `npm test` so a fresh checkout without the submodule or `pyyaml` still goes green. There are no dependencies, no `node_modules`, no build step, and nothing to `npm install`. Treat a failure as a failure of the underlying Python or Godot gate, and debug it there.

CI does not use these scripts. `.github/workflows/ci.yml` calls the same tools directly, so the facade can never become the only path to a gate.

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

This has now been got wrong at both ends of the ladder. `README.md` reconciles, it does not decide — yet it declared `authority: derived` while being named as the origin of eight decisions, and the set validated green for two releases before anyone noticed (fixed v0.2.7). `D-005` was the mirror image: it named tier-0 `META-SPEC` §5.1 as its origin, while §2 of that same document says tier 0 originates rules about documents and **never product decisions** (fixed v0.2.9). Both sets now live in `docs/designs/platform-decisions.md`, which owns nine.

The validator fails a build when a doc declares `decides:` without an authority licensed to originate — so never add `decides:` to a `derived`, `summary`, `research` or `historical` doc. But note what it cannot do: that gate asks whether an authority may originate *something*, never whether a given decision falls inside its subject matter. Both violations were caught by a human reading the ladder, not by CI.

Every governed doc declares `doc_id`/`tier`/`authority`/`status` in YAML frontmatter, validated against `specs/meta/spec-frontmatter.schema.json` and indexed in `specs/meta/doc-registry.json`. Run `python3 scripts/validate_specs.py` (stdlib only) before pushing; it runs in CI as `Validate Specs`.

`specs/aligned-spec-v0.2.5.md` is **no longer the source of truth** — it is a tier-4 research input (`status: SUPERSEDED`). Its normative content was promoted into `specs/meta/`; its §01.3 fabricated a 14-scene spine that contradicts the real storyboard. Cite it for findings and rationale, not as law.

Legacy 3D first-person node names (CharacterBody3D, CSGBox3D, Area3D, NavigationRegion3D) survive inside `specs/roadmap.md` and `specs/task-tracker.md`; read them as their 2D equivalents, and note the milestone structure itself still stands. `docs/storyboard-week1.md` is **authoritative** (tier 1, `authority: concept`) even where a beat is described in stylistically legacy 3D terms — adding structure is fine, changing a beat needs human sign-off.

## Architecture: the 4 layers

Every planning doc assumes this model, regardless of 2D/3D:

```
Layer 4 — Real agent execution    (EXISTS) claude-code, gemini-cli, MCP, SSH
Layer 3 — UI-agnostic bridge      (TODO, M5–M8) Python WebSocket → spawns agent CLI, synchronous w/ timeout
Layer 2 — Current frontend        (PARTIAL) 2.5D Godot walkable, M1+M4 done; one of several swappable frontends
Layer 1 — Data + config           (EXISTS) submodule → 133 agent .md files → agents.json
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

`.gitmodules` registers `claude-code-tresor` against the `adamtasteslikegood` fork, pinned to a commit on its default branch `10110TLGP/dev`. **It is empty in fresh checkouts** — `git submodule update --init --recursive` before reading any agent `.md`.

This fork is the **agent layer for this project** — canonical, not a derivative of `alirezarezvani/claude-code-tresor`. Don't add an `upstream` remote inside it; these definitions evolve independently. Bump the pin by working in the fork directly, pushing to its `origin`, then in the parent repo:

```bash
cd claude-code-tresor
# work on the fork as its own repo — branch, commit, push to origin
cd .. && git add claude-code-tresor && git commit -m "build: bump claude-code-tresor submodule"
```

It is the source of truth for the agent definitions behind `data/agents.json`. Don't copy that data into this repo's tree. Inside: `subagents/` holds 133 definitions nested `<dept>/<subcat>/<name>/agent.md` across ten categories, and `agents/` holds the same 8 core roles in Claude Code's **runtime** format — not 8 extra roles.

**141 files = 8 + 133, spanning 133 distinct roles.** Both numbers are right; say which you mean. Upstream v2.7.0 made `subagents/` PRIMARY and left `agents/` a backward-compat shim, so the generator reads `subagents/` only. Those 133 files carry just **130 distinct slugs** — three cross-department collisions, curated in the generator, leaving **132 entries** in `data/agents.json`. `docs/agent-directory.md` § Agent counts is the authority; don't re-derive these numbers here.

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

`generate_report.py` queries Jira for the last 7 days, buckets by status, and writes `report.md`; `post_to_confluence.py` converts that to HTML and posts it under a parent page. Both read `./.env` directly (no python-dotenv) for `ATLASSIAN_API_TOKEN_BASE64_USEREMAIL` (base64 of `email:token`) and `ATLASSIAN_URL` (host, no scheme), and `KeyError` out if either is missing.

```
ATLASSIAN_API_TOKEN_BASE64_USEREMAIL=<base64(email:token)>
ATLASSIAN_URL=<host, no scheme>
```

**Which project and space each script targets is stated once, in § Atlassian coordinates — read that, or read the scripts. Do not add a third copy here.** What belongs in this section is behaviour, not coordinates:

- `generate_report.py` — buckets the last 7 days of Jira issues by status (done / in progress / blocked / todo) and writes `report.md`. **Its Jira target is stale and will break.** It still queries the deprecated board, so the committed `report.md` is headed "Status Report - 10110 Tasteslikegood Plaza" while every line under it is a Vegangenius Chef daily status. Retargeting is pending the `PLZG` audit — a naive switch to `project = "PLZG"` would pull in the seven security alerts filed there for unrelated repos (`gbrain`, `gstack`, `alirez-claude-skills`).
- `post_to_confluence.py` — converts `report.md` to HTML and posts it as a child of the space home page. No fallback: if that page is unreachable the script exits 1 rather than writing somewhere else. The removed fallback used to write into a sibling product's space, which is how reports ended up there.

`report.md` is generated output carrying raw Jira issue titles, so committing it publishes whatever those titles say — a disclosure decision, not a formatting one. See § Atlassian coordinates for why it is no longer tracked.

## Doc layout — what's where

Root holds the entry points: `README.md` (pitch, 4-layer architecture, department/color table, attribution), `QUICKSTART.md`, `CONTRIBUTING.md`, `CHANGELOG.md` ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — add under `## [Unreleased]`), `LICENSE` (MIT), and this file.

`docs/` is design and reference; `specs/` is development process. Both carry their own `README.md` folder index — use those instead of maintaining a third inventory here. What those indexes won't tell you:

- `docs/designs/2.5D-RPG-Prototype.md` — **active design**, the 2.5D pivot.
- `docs/designs/platform-decisions.md` — **platform authority**, nine decisions as of v0.2.9 (`D-003`, `D-005`, `D-015`, `D-016`, `D-018`, `D-021`–`D-024`). Scope test: would the decision survive replacing the whole frontend? If it dies with the 2.5D prototype it belongs in the design doc instead.
- `docs/agent-directory.md` — **taxonomy authority (`D-017`)**; every other agent count in the repo derives from here.
- `specs/meta/` — **start here**, see the section above.
- `specs/roadmap.md`, `specs/task-tracker.md` — the milestone structure is authoritative; the 3D node names inside milestone bodies are deprecated.
- `specs/aligned-spec-v0.2.5.md` — tier-4 research, `SUPERSEDED`. Cite for findings, never as law.
- `specs/branching-strategy.md` — intended policy only; still says "ClaudeForge" and names workflows this repo doesn't have.

`Docs/` — **capital D, a different directory.** On a case-sensitive filesystem `docs/` and `Docs/` coexist and an agent will conflate them. `Docs/files/` holds the first-run planning material as a tier-4 `HISTORICAL` signpost; the storyboard and concept there are largely unchanged, but its task tracker and 3D references are superseded. `scripts/validate_specs.py` governs `docs/`, `specs/`, `Docs/` and the root `README.md` — so anything you add under `Docs/` still needs frontmatter and a registry entry.

`.claude/` — agent configuration. **Not a governed tree** — `scripts/validate_specs.py` only scans `docs/`, `specs/`, `Docs/` and the root `README.md`, so nothing here needs frontmatter or a `doc-registry.json` entry.

- `.claude/settings.json` — declares the `alirezarezvani/claude-skills` marketplace and enables plugins at project scope. `.claude/README.md` describes the set; read it there rather than restating it here.
- `.claude/skills/` — project-local skills committed to the repo, described below.

Other top-level artifacts:

- `report.md` — generated output of `generate_report.py`; commit it only deliberately.
- `docs/.gdignore` — keeps Godot from importing the documentation tree as game assets. Don't delete it; a new docs subfolder full of `.html`/`.svg` will otherwise show up in the resource filesystem.

## The two project-local skills

Both live in `.claude/skills/` because they encode how *this* repo breaks, which is not what a generic skill knows.

- **`review-specs`** — the review pass for a PR or branch here, and the interactive counterpart to `.github/workflows/claude-review.yml`. Its highest-yield check is repository-state claims, because that is the defect class this document set actually produces.
- **`grill-with-specs`** — the adapter that points the `grill-with-docs` plugin at this repo. The upstream skill is anchored on a `CONTEXT.md` glossary and one ADR file per decision under `docs/adr/`, and it **creates both lazily when they are missing**. Neither exists here and neither should: the equivalents are `specs/meta/META-SPEC.md` §2 for vocabulary and `specs/meta/decision-register.md` for `D-nnn` decisions. Left unredirected the plugin would start a second glossary and a second decision store beside `specs/meta/` — the exact fork the register exists to prevent. The adapter also swaps the plugin's three validators for `scripts/validate_specs.py`, which parse formats this repo does not use.

Adapt a plugin from inside `.claude/skills/` rather than editing the plugin itself. Plugins live in `~/.claude/plugins/cache/<name>/<version>/` and are replaced wholesale on the next version bump, so an edit there is silently lost.

## Department / color scheme

Nine departments map to nine office floors (now "rooms" in 2.5D), each with a fixed hex color. The mapping is canonical and appears in two places (`README.md` and `docs/agent-directory.md`). If you change a color or floor assignment, update both to keep them in sync.

## Document conventions

- **This file is held to `META-SPEC` §6.6's ~200-line instruction budget.** It has drifted past it twice, each time for good per-change reasons — which is how a heuristic quietly stops being followed. If a change would push it well over, cut something or move it behind a pointer instead. Nothing in CI enforces this.
- Most reference and process docs (under `docs/` and `specs/`) end with `*Last updated: <month> 2026*`. Update that line when editing them.
- `docs/agent-directory.md` contains unresolved template artifacts (`{{rolels}}`, `{{charactors}}`, `{{roles}}`, etc.) left over from the upstream fork. Don't propagate them into new text; clean up the section you're editing.
- Attribution: the project is an MIT-licensed adaptation of [alirezarezvani/claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor), via the [adamtasteslikegood/claude-code-tresor](https://github.com/adamtasteslikegood/claude-code-tresor) fork. Preserve the attribution block at the bottom of `README.md` and `docs/agent-directory.md`.

## Branching

`feature/* | fix/* | hotfix/* → dev → main`, Conventional Commits (`type(scope): subject` — lowercase, imperative, no trailing period), **merge commits — squash and rebase are disabled deliberately (`D-023`)**, so reverting needs `git revert -m 1`. New work targets `dev`; `dev` → `main` on release. `CONTRIBUTING.md` has the everyday flow, the commit/push cadence, and the rule that a PR stays yours until it merges. `specs/branching-strategy.md` has branch protection, required checks and CODEOWNERS gating — but it says "ClaudeForge" throughout and names workflows this repo doesn't have, so it is intended policy, not active rules.

`feature/TO-1-prototype-initialization` is a long-lived branch carrying a lot of shell/Python tooling under `scripts/`. Check it before adding a new `scripts/` file — the equivalent may already exist there.

**Keep a PR to one concern.** A branch that carries a skill, a task-runner, a policy change and a bug fix together gets reviewed as four things at once, and the reviewable third drowns in the arguable ones. Split before pushing, not after the review sprawls.

## Atlassian coordinates

**`docs/delivery-coordinates.md` is the source of truth** — Jira keys, board roles, the Confluence space and parent page id, and the keys that belong to the owner's *other* repos. `D-026` designates it. Do not restate a key here or in any guide; cite it. The two Python scripts are the only other legitimate copy, because they execute the values, and when a script and the table disagree the script is the fact.

Two things you need often enough to state as rules rather than lookups: every PR title carries a **`PLZG-###`** key, or the board never sees it; and `TO` is **deprecated** — read-only until archival, never filed into.

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

## Behavioral Guidelines

Working principles, each with the form it takes in this repo:

- **Think before coding.** Find the entitled document before writing anything — `specs/meta/` says which one wins. Cite the `D-nnn` or `SB-nn` you're acting on.
- **Simplicity first.** Don't invent infrastructure — run the command before you recommend it. Note the shape of the failure this replaces: saying "there is no Node here" is also inventing infrastructure, just in the negative direction, and it was wrong.
- **Surgical changes.** Never silently reconcile two disagreeing documents — record it in the open-conflict register and raise it. Don't duplicate state: agent facts live in `data/agents.json`, feel values live in the scene, project keys live in the scripts, and the test derives its bounds from the scene rather than copying them.
- **Know whose rule it is.** Before enforcing a constraint against a request, check who set it. Owner decisions and `D-nnn` bind; an agent's suggestion written up in a repo file is rationale to weigh, not a gate to refuse with.
- **Goal-driven execution.** M8 is the goal; `tests/smoke_test.tscn` is the evidence. `META-SPEC` §5.8 requires acceptance criteria to be machine-checkable, so "done" means a gate went green, not that the work looked finished.

If the user-level `karpathy-guidelines` skill is installed (`~/.claude/skills/karpathy-guidelines/SKILL.md`) it expands on these; it is a per-machine convenience, not a dependency of this repo.
