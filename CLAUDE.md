# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo is **design/planning only** right now. There is no source code, no build system, no tests, and no `agents.json`. The contents are:

- `README.md` — project pitch and 4-layer architecture (same text as `Docs/files/00_PROJECT_OVERVIEW.md`)
- `Docs/10110_TastesLikePlaza_DIRECTORY.md` — taxonomy of the 137+ agent roles the game wraps
- `Docs/BRANCHING_STRATEGY.md` — inherited from upstream (ClaudeForge); see "Branching" caveat below
- `Docs/plaza_build_steps.html`, `Docs/plaza_godot_architecture.svg` — visual versions of the roadmap
- `Docs/files/00–04_*.md` — the working planning set: overview, week 1 storyboard, prototype roadmap, PM task tracker, quick reference

Do not invent commands like "npm test" or "godot --headless" — none of that infrastructure exists yet. If asked to "build" or "run" something, the honest answer is that the prototype hasn't been started; the next concrete step is Milestone 1 in `Docs/files/02_PROTOTYPE_ROADMAP.md` (install Godot 4 and import the FPS demo).

## What the project is (one paragraph)

TastesLike Plaza is a planned **first-person 3D office in Godot 4** that acts as a GUI skin over a real Claude Code agent workspace. The 137+ agent definitions from the upstream `claude-code-tresor` directory become NPCs in 9 department floors; walking up to an NPC and asking a question is supposed to invoke the underlying agent CLI and pipe its stdout back into a dialogue panel. "The game *is* the tool" — the tutorial doubles as real onboarding for the agent stack.

## Architecture: the 4 layers

This is the model every planning doc assumes. Internalize it before editing any of them.

```
Layer 4 — Real agent execution    (EXISTS) claude-code, gemini-cli, MCP, SSH
Layer 3 — I/O bridge               (TODO, Phase 2) Python WebSocket → spawns agent CLI
Layer 2 — Godot 4 engine           (TODO, Phase 1, prototype target)
Layer 1 — Data + config            (EXISTS upstream) 137+ agent .md files → agents.json
```

Phase 1 builds Layer 2 only. Phase 2 adds Layer 3. Layers 1 and 4 are inherited from `claude-code-tresor` and are not built here.

## Architecture: the three Godot autoloads

Whenever the docs talk about Godot scripting, they assume three global singletons registered via `Project → Autoload`. New Godot code should plug into these rather than introduce parallel state:

| Autoload | File | Role |
|---|---|---|
| `AgentRegistry` | `autoload/AgentRegistry.gd` | Loads `data/agents.json` at startup; `get_agent(id)` returns the dict |
| `GameEvents` | `autoload/GameEvents.gd` | Global signal bus: `npc_approached`, `npc_left`, `task_completed`, `floor_unlocked` |
| `GameState` | `autoload/GameState.gd` | Tracks `unlocked_floors`, `completed_tasks`, `player_config`; gates doors via `is_unlocked()` |

The interaction pattern is: NPC `Area3D` fires `GameEvents.npc_approached` → HUD listens → populates dialogue panel from `AgentRegistry.get_agent(agent_id)`. Door triggers ask `GameState.is_unlocked(floor_id)`. Completing tutorial tasks calls `GameState.complete_task(id)`, which checks an unlock-gate table and emits `floor_unlocked`.

## Critical path

The planning docs are explicit about which milestones prove the concept: **M1 → M4 → M8**. If a change risks one of these, flag it.

- **M1** — Godot 4 + FPS template, player walks around
- **M4** — Proximity-triggered dialogue panel populated from `AgentRegistry`
- **M8** — Player question → WebSocket bridge → real `claude @agent-name` CLI invocation → response in the dialogue panel

Everything else in the roadmap is supporting scaffolding (grey-box rooms, assistant overlay, unlock gates) or post-prototype polish.

## Department / color scheme

Nine departments map to nine office floors, each with a fixed hex color. The mapping is canonical and appears in three places (`README.md`, `Docs/10110_TastesLikePlaza_DIRECTORY.md`, `Docs/files/00_PROJECT_OVERVIEW.md`). If you change a color or floor assignment, update all three to keep them in sync.

## Document conventions

- The planning docs cross-reference each other; the "spine" is `Docs/files/00_PROJECT_OVERVIEW.md` (concept) → `02_PROTOTYPE_ROADMAP.md` (milestones) → `03_PM_TASK_TRACKER.md` (checklist). `01_WEEK1_STORYBOARD.md` is the narrative/tutorial design; `04_QUICK_REFERENCE.md` is the one-page summary.
- Each planning file ends with `*Last updated: <month> 2026*`. Update that line when editing.
- `Docs/10110_TastesLikePlaza_DIRECTORY.md` contains unresolved template artifacts (`{{rolels}}`, `{{charactors}}`, `{{roles}}`, etc.) left over from the upstream fork. Don't propagate them into new text; if you edit a section, clean up the artifacts in that section.
- Attribution: the project is an MIT-licensed adaptation of [alirezarezvani/claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor), via the [adamtasteslikegood/claude-code-tresor](https://github.com/adamtasteslikegood/claude-code-tresor) fork. Preserve the attribution block at the bottom of `README.md` and the directory doc.

## Branching and commits

`Docs/BRANCHING_STRATEGY.md` describes a `feature/* | fix/* | hotfix/* → dev → main` flow with Conventional Commits and squash merges — but it was carried over verbatim from ClaudeForge and **does not match this repo's current reality**. There is no `dev` branch, no CI, no quality gates, and the doc still says "ClaudeForge" throughout. Treat it as the *intended* policy for once code lands, not an active rule set, and don't assume the workflows it references exist.

What is real right now:
- Default branch is `main`.
- The task-assigned working branch for this session is specified in the system instructions (currently `claude/add-claude-documentation-IlFF5`). Develop, commit, and push there; open a draft PR.
- Use Conventional Commits format for messages (`type(scope): subject`, lowercase, imperative, no trailing period) — that part of the strategy doc is worth following even before CI exists.

## When you're asked to add code

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
  bridge.py    # Phase 2 Python WebSocket server (ws://localhost:8765)
```

The first real code task is converting the upstream 137+ agent `.md` files into a single `data/agents.json` keyed by agent id, with at minimum `{name, role, dept, color, tools, description}`. M3 in the roadmap depends on this.
