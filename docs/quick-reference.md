---
doc_id: QUICK-REFERENCE
title: 10110 TastesLike Plaza — Quick Reference
tier: 4
authority: summary
status: ACTIVE
doc_set_version: 0.2.8
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [PROJECT-OVERVIEW, STORYBOARD-W1, ROADMAP]
---

# 10110 TastesLike Plaza — Quick Reference

> One page. Keep this open while working.

---

## What this project is

A 2.5D top-down office world (Pokémon / Stardew Valley register) that is a real GUI for a real AI agent workspace.
The game = the tool. The tutorial = the onboarding. The characters = the agents.

The concept originally described a first-person 3D world; that was scoped down to 2.5D in `docs/designs/2.5D-RPG-Prototype.md` (status `PROMOTED`, 2026-04-27) and ratified by `specs/aligned-spec-v0.2.5.md`. 3D first-person is deferred to v2.0–3.0.

---

## The build order

```
NOW        → Data prep (agents.json from .md files)
Week 1     → Godot setup + grey-box office
Week 2     → First NPC + dialogue system
Week 3     → Assistant chat UI + unlock gates
Weeks 4–6  → Python WebSocket bridge + live agent output
After M8   → Polish, more floors, more NPCs, art pass
```

---

## The 4 layers

```
Layer 4  Real agents        ← already exists (claude-code, MCP, CLI)
Layer 3  UI-agnostic bridge ← Phase 2  (Python WebSocket) — never knows the UI exists
Layer 2  Current frontend   ← Phase 1  (today: 2.5D Godot; CLI / web / 3D are peers)
Layer 1  Data + config      ← exists now (133 roles from .md files → JSON)
```

---

## The 3 autoloads (Godot global singletons)

| Name | File | Does |
|------|------|------|
| `AgentRegistry` | `autoload/AgentRegistry.gd` | Loads agents.json, returns agent data by ID |
| `GameEvents` | `autoload/GameEvents.gd` | Global signal bus — npc_approached, task_completed, floor_unlocked |
| `GameState` | `autoload/GameState.gd` | Tracks unlocked floors, completed tasks, player config |

---

## The critical path

**M1 → M4 → M8**

M1: Walk around the office.
M4: Walk up to an NPC and see their agent info.
M8: Get a real agent response through the game.

Everything else is built on top of those three.

---

## Open items (most important)

1. Assistant character — name + personality
2. Tutorial company name
3. Art direction (even one moodboard)
4. Convert agents.json (required before M3)

---

## 9 departments → 9 floors/wings

| Dept | Color | Floor | Gate |
|------|-------|-------|------|
| Engineering | Blue | 2 | Day 2 (arrives Monday) |
| Design | Pink | 3 | Complete 1 task |
| Marketing | Green | 3 | Complete first sprint |
| Product | Purple | 2 | Day 2 (drops by office) |
| Leadership | Gold | 4 (exec) | End of tutorial |
| Operations | Teal | 1 | Day 2 |
| Research | Orange | 2 | Day 4 (time-based) |
| AI/Automation | Indigo | Basement | Complete coding lesson |
| Account/CS | Cyan | 1 | Day 3 |
| Core Agents | — | Server room | Day 1 (present on arrival) |

---

## Week 1 story in one line per day

- **Day 0 (Fri eve):** Founder video call. Meet the assistant. Building preview.
- **Day 1 (Sat):** Arrive solo. Meet 2 Core agents. Set up your office.
- **Day 2 (Mon):** Engineering + PM + Design arrive. First task delegation.
- **Day 3 (Tue):** First sprint standup. First coding lesson. First agent output.
- **Days 4–5:** Remaining floors unlock. Founder check-in. Tutorial complete.

---

*Last updated: April 2026*
