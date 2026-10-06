---
doc_id: PROJECT-OVERVIEW
title: 10110 TastesLike Plaza — Project Overview
tier: 2
authority: derived
status: ACTIVE
doc_set_version: 0.2.13
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [STORYBOARD-W1, DESIGN-25D, PLATFORM-DECISIONS]
enforcement: asserted
gates: [Validate Specs:live, Validate Agent Data:live]
weakest_claim: 133 roles as JSON (from .md files)
---

# 10110 TastesLike Plaza — Project Overview

> **One-line pitch:** A 2.5D top-down office world (Pokémon / Stardew Valley register) that is a graphical interface for a real AI agent workspace — the tutorial *is* the onboarding, and the characters *are* the agents.

---

## Concept

TastesLike Plaza is a navigable 2.5D top-down office environment built on top of an existing AI agent directory (claude-code-tresor / `10110_TastesLikePlaza`). The game world is not a game — it is an alternative GUI skin over 133 real AI agent roles organized into 9 departments plus a Core team.

**The player** is a co-founder/tech lead transitioning their startup from remote-first pizza-and-laptop sessions into a real office space. The office is new. The team is moving in. The player already knows most of these people — they've just never been in the same physical space.

**The characters** are not fictional NPCs. Each one is a personified AI agent role — a composite of a game persona and a real agent definition from the employee directory. Talking to them, delegating tasks, and receiving output *is* using the underlying agent.

**The tutorial** is real onboarding. Bootstrapping the fictional startup teaches the player project management and coding. Completing tutorial tasks configures and activates real agent capabilities. The game and the tool are the same thing.

---

## The Address

`10110 TastesLike Plaza` is the name/address of one user's instance of the office world. Each user/profile gets one office building. The "10110" and "TastesLike" components are part of the naming convention for the tech park concept the project is inspired by.

---

## System Architecture (4 Layers)

```
Layer 4 — Real agent execution  (EXISTS)
  claude-code, gemini-cli, MCP servers, SSH, tty
  Not built by this project.

Layer 3 — UI-agnostic bridge  (EXISTS — M7+M8)
  Python WebSocket server on ws://localhost:8765
  Conversation engine (Messages API) + domain sessions (Agent SDK)
  Requires an Anthropic API key (ANTHROPIC_API_KEY)
  Synchronous with timeout (D-005, D-006) — zero UI awareness

Layer 2 — Current frontend  (PARTIAL)
  Today: 2.5D Godot. CLI, web, and a future 3D world are peers, not replacements.
  World / map       → 2.5D top-down rooms and floors (TileMap)
  NPC system        → characters + agent roles
  Player + HUD      → CharacterBody2D top-down controller, UI overlays
  Event bus         → tasks, unlocks, chat notifications

Layer 1 — Data + config  (EXISTS)
  Employee directory  → 133 roles as JSON (from .md files)
  Scene / story data  → dialogue, unlock gates, tutorial flow
  Player profile      → progress, preferences, config
```

**Critical insight:** Layers 1, 3 and 4 all exist. The proof pipe is complete:
walk up to an NPC, type a question, get a real Claude response. See
[`QUICKSTART.md`](QUICKSTART.md) for how to run it.

---

## The 9 Departments (Office Floors/Wings)

| # | Dept | Color | Roles | Floor |
|---|------|-------|-------|-------|
| 1 | Engineering | Blue `#3B82F6` | 54 | Floor 2 |
| 2 | Design | Pink `#EC4899` | 7 | Floor 3 |
| 3 | Marketing | Green `#10B981` | 11 | Floor 3 |
| 4 | Product | Purple `#8B5CF6` | 9 | Floor 2 |
| 5 | Leadership & Strategy | Gold `#F59E0B` | 14 | Floor 4 (exec) |
| 6 | Operations | Teal `#14B8A6` | 5 | Floor 1 |
| 7 | Research | Orange `#F97316` | 7 | Floor 2 |
| 8 | AI & Automation | Indigo `#6366F1` | 9 | Basement / server |
| 9 | Account & Customer Success | Cyan `#06B6D4` | 8 | Floor 1 |
| — | Core Agents | Star | 8 (production-ready) | Server room |
| | | | **132 total** | |

These are the counts in **`data/agents.json`** — what the office actually renders,
generated from the submodule (`D-024`) and verified in CI.

Upstream ships **133 agent files** under `subagents/`, carrying only **130 distinct
name slugs**: three roles appear in two departments each. One (`infrastructure-maintainer`)
is a genuine duplicate and is dropped; the other two are different jobs sharing a name
and are renamed. Hence 132. There are a further 8 files under `agents/`, a
backward-compatible shim upstream left behind at v2.7.0 — symlinks plus stale copies,
not additional roles.

Full method, per-department figures, and the curation table are in
[`docs/agent-directory.md`](docs/agent-directory.md), the taxonomy authority (`D-017`).

---

## Player Character Framing

**Spectrum:**
- Left extreme: Solo founder — empty office, hand-pick every hire. Slowest, most powerful.
- Right extreme: New hire — established company, catch up fast.
- **TastesLike Plaza:** Dead center. Co-founder / tech lead. Company is real and growing. Moving from remote-first into first physical office.

**Day 0 context:** Player has been coding with the team over pizza sessions and remote calls. The office is an upgrade — a sign the product is gaining traction. They have keys. They get to walk in this weekend before anyone else arrives.

---

## Key Design Decisions (locked)

| Decision | Choice | Reason |
|----------|--------|--------|
| Tutorial = onboarding? | Yes — same thing | The fictional startup bootstrap IS real agent setup |
| Player framing | Co-founder, mid-spectrum | Empowering but guided; not overwhelming |
| Game engine | Godot 4 | Free, MIT, strong 2D/TileMap support, GDScript ≈ Python |
| I/O method (Phase 2) | WebSocket bridge (Python) | Local process, no deployment needed for prototype |
| Unlock mechanic | Completed tasks gate floors | Onboarding completion = world expansion |
| In-world assistant | Scripted nav guide (not agent) | Separate from NPCs; always-on companion |

---

## Source / Attribution

Built on top of [claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor/) by Alireza Rezvani (MIT License), forked and adapted at [adamtasteslikegood/claude-code-tresor](https://github.com/adamtasteslikegood/claude-code-tresor).

Original contributions and changes © 2026 Adam Schoen. MIT License.

---

*Last updated: August 2026*
