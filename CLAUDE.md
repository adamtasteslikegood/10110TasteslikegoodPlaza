# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo sits **between planning and prototype**. There is no Godot project yet and no `agents.json`, but there is:

- A working CI pipeline (`.github/workflows/ci.yml`) that already lints Python on every push/PR.
- Two Atlassian integration scripts (`generate_report.py`, `post_to_confluence.py`) wired to a Jira project keyed `TO` and a Confluence parent page.
- The upstream agent directory wired in as a git submodule at `./claude-code-tresor` (relative URL, not initialized in fresh checkouts — see below).
- Two parallel docs trees that say slightly different things: `Docs/` (capital D) is the original 3D-first-person planning set; `docs/designs/` (lowercase d) is the newer scope-reduction plan that supersedes it.
- A bunch of `gemini-*` workflows and matching `.toml` command files driving an autonomous triage/review bot.

Don't invent commands like "npm test" or "godot --headless" — Node and Godot infrastructure don't exist yet. What's actually runnable is described below.

## Critical architectural reframe (read this before trusting `Docs/files/`)

`docs/designs/2.5D-RPG-Prototype.md` has status `PROMOTED` and a `/plan-ceo-review` header dated 2026-04-27. It **pivots the prototype from 3D first-person to 2.5D top-down** (Pokemon / Stardew Valley style) under a "10x check" scope reduction. Accepted scope from that plan:

- 2.5D top-down (Godot 2D), not first-person 3D.
- One generic agent sprite, color-tinted per department; one generic silhouette portrait for dialogue.
- Python WebSocket bridge enforces **synchronous execution with timeout protection** (not streaming).
- Godot UI fakes streaming with a typewriter effect over a full JSON response.
- "Wait or delegate" UX — short tasks block, long tasks become background delegations.

Deferred: true WebSocket streaming, unique sprites per agent, 3D first-person.

The older `Docs/files/00–04_*.md` set still describes the 3D first-person vision in detail. Treat it as historical context for the *concept* (4-layer architecture, autoloads, M1/M4/M8 milestones still apply directionally) but defer to the 2.5D plan for *implementation* decisions. If you edit either set, note the inconsistency rather than silently aligning them — that's a question for the user.

## Architecture: the 4 layers

Every planning doc assumes this model, regardless of 2D/3D:

```
Layer 4 — Real agent execution    (EXISTS) claude-code, gemini-cli, MCP, SSH
Layer 3 — I/O bridge               (TODO, Phase 2) Python WebSocket → spawns agent CLI, synchronous w/ timeout
Layer 2 — Godot 4 engine           (TODO, Phase 1) — now 2.5D, per the promoted plan
Layer 1 — Data + config            (EXISTS upstream as submodule) 137+ agent .md files → agents.json
```

## Architecture: the three Godot autoloads

When Godot code arrives, it's expected to plug into three global singletons (`Project → Autoload`) rather than introduce parallel state:

| Autoload | File | Role |
|---|---|---|
| `AgentRegistry` | `autoload/AgentRegistry.gd` | Loads `data/agents.json` at startup; `get_agent(id)` returns the dict |
| `GameEvents` | `autoload/GameEvents.gd` | Global signal bus: `npc_approached`, `npc_left`, `task_completed`, `floor_unlocked` |
| `GameState` | `autoload/GameState.gd` | Tracks `unlocked_floors`, `completed_tasks`, `player_config`; gates doors via `is_unlocked()` |

Interaction pattern: NPC `Area` (or `Area2D` under the 2.5D plan) fires `GameEvents.npc_approached` → HUD listens → populates dialogue panel from `AgentRegistry.get_agent(agent_id)`. Door triggers consult `GameState.is_unlocked(floor_id)`. Completing tutorial tasks calls `GameState.complete_task(id)`, which checks an unlock-gate table and emits `floor_unlocked`.

## Critical path

The proof-of-concept milestones from the roadmap are **M1 → M4 → M8**. The 2.5D pivot changes the *visuals* of M1 (top-down sprite instead of FPS controller) but not the milestone structure:

- **M1** — Godot 4 project + player can navigate the world
- **M4** — Proximity-triggered dialogue panel populated from `AgentRegistry`
- **M8** — Player question → WebSocket bridge → real `claude @agent-name` CLI invocation → response rendered in dialogue panel (typewriter effect over the full JSON, per the promoted plan)

If a change risks one of these, flag it.

## The `claude-code-tresor` submodule

`.gitmodules` registers `claude-code-tresor` pointing at the maintainer's fork (`https://github.com/adamtasteslikegood/claude-code-tresor.git`), pinned to commit `acfb923…`. **It is empty in fresh checkouts** — initialize it before reading the upstream agent `.md` files:

```bash
git submodule update --init --recursive
```

This is the source of truth for the agent definitions that need to become `data/agents.json` for M3. Don't duplicate that data into this repo's tree. Layout inside the submodule:

- `subagents/` — 137+ specialized agent definitions organized by department (`engineering/`, `design/`, `marketing/`, `product/`, `leadership/`, `operations/`, `research/`, `ai-automation/`, `account-customer-success/`, `core/`), plus an `AGENT-INDEX.md`.
- `agents/` — the 8 production-ready core agents (`systems-architect`, `config-safety-reviewer`, `root-cause-analyzer`, `security-auditor`, `test-engineer`, `performance-tuner`, `refactor-expert`, `docs-writer`).

### Pulling upstream updates

The submodule's `origin` is the maintainer's fork so PRs/issues/CI stay isolated. To pull updates from the parent project (`alirezarezvani/claude-code-tresor`), add it as `upstream` **inside the submodule** (this is per-clone — `.git/config` only, not propagated):

```bash
cd claude-code-tresor
git remote add upstream https://github.com/alirezarezvani/claude-code-tresor.git
git fetch upstream
# merge or rebase upstream/main into your fork's main, then push to origin,
# then back in the parent repo:
cd .. && git add claude-code-tresor && git commit -m "build: bump claude-code-tresor submodule"
```

## CI workflows

`.github/workflows/ci.yml` runs on push/PR to `main` and `dev`. Two jobs:

- **`Lint Python Bridge`** — installs `flake8 black websockets`, then:
  - `black --check .` (warnings only — failures are echoed but don't fail the build)
  - `flake8 . --select=E9,F63,F7,F82` (hard fail on syntax errors / undefined names)
  - `flake8 . --exit-zero --max-complexity=10 --max-line-length=127` (advisory)
  Any new Python here needs to at least pass the strict flake8 subset.
- **`Export Godot 4 Prototype`** — currently a stub `echo "Godot project not initialized yet"`. Don't wire it up to a real Godot export until `project.godot` exists.

Separately, the `gemini-*.yml` workflows + `.gemini/commands/` + `.github/commands/` files implement a gemini-cli-driven triage/review/plan-execute bot triggered by `@gemini-cli` mentions and a schedule. Don't edit those files without understanding the dispatch flow in `gemini-dispatch.yml` — they orchestrate one another.

## Python scripts (Atlassian glue)

Both top-level Python scripts depend on a `.env` file (gitignored) with:

```
ATLASSIAN_API_TOKEN_BASE64_USEREMAIL=<base64(email:token)>
ATLASSIAN_URL=<host, no scheme>
```

- `generate_report.py` — queries Jira project `TO` for issues updated in the last 7 days, buckets them by status (done / in progress / blocked / todo), and writes `report.md`.
- `post_to_confluence.py` — converts `report.md` to HTML and posts it as a child of Confluence page `15925249` (fallback `15695959`).

These read `./.env` directly (no python-dotenv); they'll crash with a `KeyError` if either var is missing. The lint job tolerates them as-is.

## Two doc trees — what's where

- `Docs/` (capital D) — the original 3D first-person planning set. Spine: `Docs/files/00_PROJECT_OVERVIEW.md` (concept) → `02_PROTOTYPE_ROADMAP.md` (milestones) → `03_PM_TASK_TRACKER.md` (checklist). `01_WEEK1_STORYBOARD.md` is the narrative/tutorial design; `04_QUICK_REFERENCE.md` is the one-page summary. `BRANCHING_STRATEGY.md` is inherited verbatim from upstream (see "Branching" below). `10110_TastesLikePlaza_DIRECTORY.md` taxonomizes the 137+ agent roles.
- `docs/designs/` (lowercase d) — promoted `/plan-ceo-review` outputs. Currently just `2.5D-RPG-Prototype.md`. **This is the active design.**
- `report.md` — generated output of `generate_report.py`; commit it only deliberately.
- `CHANGELOG.md` — currently contains `@googleworkspace/cli`'s changelog, not this project's. Looks like an accidental import. Don't extend it; flag to the user before rewriting.

## Department / color scheme

Nine departments map to nine office floors (now "rooms" in 2.5D), each with a fixed hex color. The mapping is canonical and appears in three places (`README.md`, `Docs/10110_TastesLikePlaza_DIRECTORY.md`, `Docs/files/00_PROJECT_OVERVIEW.md`). If you change a color or floor assignment, update all three to keep them in sync.

## Document conventions

- Planning files in `Docs/files/` end with `*Last updated: <month> 2026*`. Update that line when editing them.
- `Docs/10110_TastesLikePlaza_DIRECTORY.md` contains unresolved template artifacts (`{{rolels}}`, `{{charactors}}`, `{{roles}}`, etc.) left over from the upstream fork. Don't propagate them into new text; clean up the section you're editing.
- Attribution: the project is an MIT-licensed adaptation of [alirezarezvani/claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor), via the [adamtasteslikegood/claude-code-tresor](https://github.com/adamtasteslikegood/claude-code-tresor) fork. Preserve the attribution block at the bottom of `README.md` and the directory doc.

## Branching

The intended flow is `feature/* | fix/* | hotfix/* → dev → main` with Conventional Commits and squash merges. What's actually in the remote right now:

- `main` — current default; has the Atlassian scripts, CI, submodule, gemini workflows.
- `dev` — **behind `main`**; missing CHANGELOG, LICENSE, `docs/designs/`, the gemini workflows, the submodule. Don't treat it as the integration branch yet.
- `sync-main-to-dev` — identical to `main`; presumably the staging point for a future `dev` catch-up merge.
- `feature/TO-1-prototype-initialization` — long-lived feature branch with extensive `scripts/` and `scripts/scripts-bakup/` shell/Python tooling (Jira PM daemon, ahead-behind scripts, etc.).
- Task-assigned working branches (e.g. `claude/...`) — develop here, commit, push, open a draft PR. The session-assigned branch is specified in the system prompt.

`Docs/BRANCHING_STRATEGY.md` describes branch protection rules, required status checks, and CODEOWNERS gating — but the doc still says "ClaudeForge" throughout and references workflows (`pr-into-dev.yml`, `dev-to-main.yml`, `release.yml`) that **don't exist in this repo**. Treat it as intended policy for once code lands, not active rules. The Conventional Commits format (`type(scope): subject`, lowercase, imperative, no trailing period) is worth following now.

## When you're asked to add Godot code

The docs prescribe a specific structure once the Godot project is created. Follow it instead of inventing a new layout:

```
project.godot
data/agents.json
autoload/
  AgentRegistry.gd
  GameEvents.gd
  GameState.gd
scenes/        # rooms, NPCs, HUD
scripts/       # npc.gd, door.gd, assistant_overlay.gd, ws_client.gd
bridge/
  bridge.py    # Phase 2 Python WebSocket server (ws://localhost:8765), synchronous-with-timeout per the 2.5D plan
```

The first real code task is generating `data/agents.json` from the `claude-code-tresor` submodule's 137+ agent `.md` files, keyed by agent id, with at minimum `{name, role, dept, color, tools, description}`. M3 on the roadmap depends on this. Don't fabricate this JSON by hand — derive it from the submodule (init it first).

Note that there is already a `scripts/` directory worth of bash/Python tooling on the `feature/TO-1-prototype-initialization` branch. Before adding new `scripts/` files on `main`, check whether something equivalent already exists on that branch.
