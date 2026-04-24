# 10110 TastesLike Plaza — Project Overview

> **One-line pitch:** A first-person 3D office world that is a graphical interface for a real AI agent workspace — the tutorial *is* the onboarding, and the characters *are* the agents.

---

## Concept

TastesLike Plaza is a navigable 3D office environment built on top of an existing AI agent directory (claude-code-tresor / `10110_TastesLikePlaza`). The game world is not a game — it is an alternative GUI skin over 137+ real AI agent roles organized into 9 departments.

**The player** is a co-founder/tech lead transitioning their startup from remote-first pizza-and-laptop sessions into a real office space. The office is new. The team is moving in. The player already knows most of these people — they've just never been in the same physical space.

**The characters** are not fictional NPCs. Each one is a personified AI agent role — a composite of a game persona and a real agent definition from the employee directory. Talking to them, delegating tasks, and receiving output *is* using the underlying agent.

**The tutorial** is real onboarding. Bootstrapping the fictional startup teaches the player project management and coding. Completing tutorial tasks configures and activates real agent capabilities. The game and the tool are the same thing.

---

## The Address

`10110 TastesLike Plaza` is the name/address of one user's instance of the office world. Each user/profile gets one office building. The "10110" and "TastesLike" components are part of the naming convention for the tech park concept the project is inspired by.

---

## System Architecture (4 Layers)

```
Layer 4 — Real agent execution
  claude-code, gemini-cli, MCP servers, SSH, tty
  STATUS: Already exists. Not built by this project.

Layer 3 — I/O bridge  [Phase 2]
  WebSocket server / named pipe
  Connects Godot game engine to CLI agent processes
  stdin / stdout / stderr routing

Layer 2 — Godot 4 engine  [Phase 1 — prototype target]
  World / map       → rooms, floors, navigation
  NPC system        → characters + agent roles
  Player + HUD      → first-person controller, UI overlays
  Event bus         → tasks, unlocks, chat notifications

Layer 1 — Data + config  [Exists now]
  Employee directory  → 137+ roles as JSON (from .md files)
  Scene / story data  → dialogue, unlock gates, tutorial flow
  Player profile      → progress, preferences, config
```

**Critical insight:** Layer 1 and Layer 4 already exist. The prototype is Layers 2 and 3 only, built in that order.

---

## The 9 Departments (Office Floors/Wings)

| # | Dept | Color | Roles | Floor |
|---|------|-------|-------|-------|
| 1 | Engineering | Blue `#3B82F6` | 60+ | Floor 2 |
| 2 | Design | Pink `#EC4899` | 10 | Floor 3 |
| 3 | Marketing | Green `#10B981` | 15+ | Floor 3 |
| 4 | Product | Purple `#8B5CF6` | 10+ | Floor 2 |
| 5 | Leadership & Strategy | Gold `#F59E0B` | 15+ | Floor 4 (exec) |
| 6 | Operations | Teal `#14B8A6` | 10+ | Floor 1 |
| 7 | Research | Orange `#F97316` | 10+ | Floor 2 |
| 8 | AI & Automation | Indigo `#6366F1` | 10+ | Basement / server |
| 9 | Account & Customer Success | Cyan `#06B6D4` | 8+ | Floor 1 |
| — | Core Agents | Star | 8 (production-ready) | Server room |

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
| Game engine | Godot 4 | Free, MIT, first-person built-in, GDScript ≈ Python |
| I/O method (Phase 2) | WebSocket bridge (Python) | Local process, no deployment needed for prototype |
| Unlock mechanic | Completed tasks gate floors | Onboarding completion = world expansion |
| In-world assistant | Scripted nav guide (not agent) | Separate from NPCs; always-on companion |

---

## Source / Attribution

Built on top of [claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor/) by Alireza Rezvani (MIT License), forked and adapted at [adamtasteslikegood/claude-code-tresor](https://github.com/adamtasteslikegood/claude-code-tresor).

Original contributions and changes © 2026 Adam Schoen. MIT License.

---

*Last updated: April 2026*
