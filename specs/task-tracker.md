---
doc_id: TASK-TRACKER
title: 10110 TastesLike Plaza — PM Task Tracker
tier: 3
authority: derived
status: ACTIVE
doc_set_version: 0.2.7
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [ROADMAP]
---

# 10110 TastesLike Plaza — PM Task Tracker

> ⚠️ **Superseded in part by [`aligned-spec-v0.2.5.md`](aligned-spec-v0.2.5.md).**
> The **checklist structure and unchecked-milestone breakdown** are still useful for tracking.
> The **3D-specific task wording** (Area3D, CharacterBody3D, NavigationRegion3D, FPS demo) is **deprecated**. The prototype is 2.5D top-down; treat those nodes as their 2D equivalents.

> Use this as your working checklist. Copy to Notion, Linear, GitHub Issues, or wherever you track work.
> Status: [ ] todo  [~] in progress  [x] done

---

## Pre-work (before first line of code)

### Concept locked
- [x] Vision defined: 3D office GUI over real agent infrastructure
- [x] Player framing decided: co-founder, mid-spectrum
- [x] Tutorial = onboarding confirmed
- [x] Engine chosen: Godot 4
- [x] I/O bridge approach decided: WebSocket + Python

### Content to define (open items)
- [ ] In-world assistant — name and personality
- [ ] Tutorial startup — company name
- [ ] Player character — name / customization options
- [ ] Day 0 dialogue script — Founder video call (full draft)
- [ ] Day 1 dialogue scripts — Systems Architect, Security Auditor
- [ ] Visual / art direction (even rough direction helps grey-boxing decisions)
- [ ] Sound direction (ambient office sounds? music tone?)

### Data prep
- [ ] Export all 133 agent .md files to a single `agents.json`
- [ ] Verify JSON structure matches planned schema (name, role, dept, color, description, tools)
- [ ] Define scene/dialogue data format (separate JSON or GDScript Resources?)
- [ ] Define player profile save format

---

## Phase 1 — Godot prototype  (target: weeks 1–3)

### M1 — Godot setup
- [ ] Download Godot 4
- [ ] Run First Person Shooter demo — confirm movement works
- [ ] Create new project
- [ ] Import FPS CharacterBody3D controller into new project
- [ ] Confirm player walks, looks around, has collision

### M2 — Grey-box office
- [ ] Block out lobby
- [ ] Block out player office
- [ ] Block out server room
- [ ] Block out engineering floor (open plan)
- [ ] Block out war room / meeting room
- [ ] Add 2–3 locked corridors (future floors)
- [ ] Add Area3D doorway triggers on each room entrance
- [ ] Bake NavigationRegion3D for the full floor
- [ ] Playtest: does it feel right to walk through?

### M3 — Agent data layer
- [ ] Create `data/agents.json` from directory
- [ ] Create `autoload/AgentRegistry.gd`
- [ ] Add AgentRegistry to Project → Autoload
- [ ] Test: `AgentRegistry.get_agent("systems-architect")` returns correct data
- [ ] Create `autoload/GameEvents.gd` with core signals
- [ ] Create `autoload/GameState.gd` with unlock/task tracking

### M4 — First NPC
- [ ] Create NPC scene (CharacterBody3D + Area3D + Label3D)
- [ ] Write `npc.gd` with agent_id export + proximity signal
- [ ] Place Systems Architect NPC in server room
- [ ] Create basic HUD dialogue panel (CanvasLayer)
- [ ] Wire GameEvents.npc_approached → dialogue panel populates from agent data
- [ ] Playtest: walk up to NPC → panel shows → walk away → panel hides

### M5 — Assistant chat UI
- [ ] Create assistant overlay (CanvasLayer)
- [ ] Build chat panel UI (message list + input + send button)
- [ ] Implement toggle keypress (Tab or `~`)
- [ ] Add scripted responses for Day 0/1 context
- [ ] Add basic message history (scroll container)
- [ ] Playtest: toggle chat, send a message, get a response

### M6 — Unlock + map system
- [ ] Implement GameState.complete_task() with gate checks
- [ ] Implement GameState.unlock_floor() + is_unlocked()
- [ ] Wire door triggers to GameState.is_unlocked()
- [ ] Build 2D building map widget in HUD
- [ ] Connect GameEvents.floor_unlocked → map updates color
- [ ] Test: complete a task → door unlocks → map updates

---

## Phase 2 — I/O bridge  (target: weeks 4–6)

### M7 — Python bridge
- [ ] Install Python websockets: `pip install websockets`
- [ ] Write `bridge.py` (WebSocket server + subprocess agent invocation)
- [ ] Test bridge standalone: send it a task via `wscat` or `websocat`, verify agent CLI response returns
- [ ] Write `ws_client.gd` in Godot
- [ ] Test: Godot sends a task → bridge receives it (log to console)
- [ ] Test: bridge returns a response → Godot receives and logs it

### M8 — First live agent output in-world
- [ ] Wire dialogue panel "send" button → ws_client.send_task()
- [ ] Wire ws_client.response_received → dialogue panel updates with output
- [ ] Wire response → also logs to inbox
- [ ] Test end-to-end: walk up to NPC → type question → real agent response appears
- [ ] **MILESTONE: Prototype complete**

---

## Phase 3 — Polish + expansion  (post-prototype)

> Define specifics once M8 is working. Rough ideas:

### World
- [ ] All 9 department floors blocked out
- [ ] Textures / basic materials applied
- [ ] Lighting pass (day/night? warm office lighting?)
- [ ] Ambient sound (HVAC hum, distant typing, coffee machine)

### NPCs
- [ ] All 9 department lead NPCs placed and scripted
- [ ] Core 8 agents placed in server room
- [ ] NPC animations (idle, talking, working)
- [ ] NPC pathfinding (walk between rooms)

### Tutorial
- [ ] Full Day 0 cutscene (Founder call)
- [ ] Day 1–5 scenes scripted and implemented
- [ ] Unlock gates for all 9 departments
- [ ] Tutorial completion state → free play

### Assistant
- [ ] Connect assistant chat to real API (not scripted)
- [ ] Schedule view
- [ ] Inbox with task history
- [ ] Notification system

### I/O visualization
- [ ] Task status indicator while agent is running
- [ ] Streaming output (show response as it arrives)
- [ ] Error handling / failed task display
- [ ] Multi-agent task orchestration visualization

---

## Open questions / decisions needed

| Question | Status | Notes |
|----------|--------|-------|
| Assistant character name | Open | Worth designing intentionally |
| Tutorial company name | Open | Should feel like a real startup |
| Art direction | Open | Even rough moodboard helps |
| Multiplayer scope | Open | Single-user for prototype; define later |
| Web export vs desktop | Open | Godot supports both; decide before M1 |
| How to handle agent errors in-world | Open | NPC "unavailable"? Error message in inbox? |
| Save game format | Open | JSON file vs Godot Resource |
| Platform target (Win/Mac/Linux) | Open | Godot exports all three |

---

## Useful links

- Godot 4 download: https://godotengine.org
- Godot docs: https://docs.godotengine.org/en/stable/
- GDScript reference: https://docs.godotengine.org/en/stable/tutorials/scripting/gdscript/
- Godot FPS tutorial: https://docs.godotengine.org/en/stable/tutorials/3d/fps_tutorial/
- Python websockets: https://websockets.readthedocs.io
- Source repo (fork): https://github.com/adamtasteslikegood/claude-code-tresor

---

*Last updated: April 2026*
