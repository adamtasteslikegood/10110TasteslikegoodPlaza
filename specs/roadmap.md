---
doc_id: ROADMAP
title: 10110 TastesLike Plaza — Prototype Build Roadmap
tier: 3
authority: derived
status: ACTIVE
doc_set_version: 0.2.5
last_updated: 2026-04
owner: adamtasteslikegood
derives_from: [PROJECT-OVERVIEW, DESIGN-25D, SPEC-DRIVERS-025]
---

# 10110 TastesLike Plaza — Prototype Build Roadmap

> ⚠️ **Superseded in part by [`aligned-spec-v0.2.5.md`](aligned-spec-v0.2.5.md).**
> The **milestone structure** (M1 → M8, critical path M1 → M4 → M8) is still correct.
> The **3D first-person specifics below** (CharacterBody3D, FPS demo, CSGBox3D, Area3D, NavigationRegion3D) are **deprecated**. The prototype is now 2.5D top-down per [`../docs/designs/2.5D-RPG-Prototype.md`](../docs/designs/2.5D-RPG-Prototype.md) (status `PROMOTED`, 2026-04-27). Read node names as their 2D equivalents (CharacterBody2D, TileMap, Area2D, NavigationRegion2D). 3D first-person is deferred to v2.0–3.0.

> Engine: **Godot 4** (free, MIT license, ~80MB download)
> Language: **GDScript** (reads like Python — approachable without game dev background)
> Target: Working 2.5D top-down office world with NPC interaction and live agent output

---

## Critical path (minimum viable prototype)

Milestone 1 → Milestone 4 → Milestone 8

Everything else can be deferred. If you can walk through a lobby, approach an NPC, and get a real agent response back in a dialogue panel — the concept is proven.

---

## Phase 1 — Godot prototype (weeks 1–3)

---

### Milestone 1 — Install Godot 4 + first-person template

**Time estimate:** ~1 hour
**GDScript required:** Zero to start

**Steps:**
1. Download Godot 4 from [godotengine.org](https://godotengine.org) (~80MB, no install, just unzip and run)
2. Open the Asset Library inside Godot → search "First Person"
3. Download the "First Person Shooter" demo
4. Hit Play. Walk around. That is your movement system.

**Scene tree you get for free:**
```
CharacterBody3D   ← your player body
  Camera3D        ← mounted at head height
  CollisionShape3D ← prevents walking through walls
```

**Why this matters:** The FPS controller is the hardest part to write from scratch. Godot gives you a working one in 60 seconds. Everything you build from here is on top of this.

---

### Milestone 2 — Grey-box the office layout

**Time estimate:** 4–6 hours
**GDScript required:** Minimal (door trigger logic only)

**What "grey-boxing" means:**
Standard game dev practice — build the entire space with plain grey/white geometry boxes before spending any time on textures, lighting, or art. Walk through it. Does the lobby feel right? Are the corridors the right width? Is the server room in a sensible place? Validate the space before investing in visuals.

**Godot tools used:**
```
CSGBox3D            ← walls, floors, ceilings (drag to resize)
CSGCombiner3D       ← group rooms together into a building
Area3D              ← doorway trigger zones (detects when player enters)
NavigationRegion3D  ← bake a pathfinding mesh so NPCs can walk around later
```

**Rooms to block out (Week 1 scope):**
- [ ] Lobby / entrance
- [ ] Player's office
- [ ] Server room (Core agents)
- [ ] Engineering floor (open plan)
- [ ] War room / meeting room
- 2–3 locked corridors leading to future floors

**Door lock logic (simple version):**
```gdscript
# door.gd
func _on_player_entered():
    if GameState.is_unlocked(floor_id):
        open()
    else:
        show_message("Not yet accessible")
```

---

### Milestone 3 — Load employee directory as game data

**Time estimate:** ~2 hours
**GDScript required:** One autoload script

**What this does:**
Converts your existing `.md` agent files to JSON and loads them into the game at startup. Each agent becomes a data object the NPC system draws from. This is the bridge between your existing directory and the game world.

**Step 1 — Convert .md files to JSON:**
```json
{
  "systems-architect": {
    "name": "Systems Architect",
    "role": "System design and architecture",
    "dept": "core",
    "color": "#888780",
    "tools": ["Read", "Write", "Edit"],
    "description": "I design how everything connects."
  }
}
```

**Step 2 — GDScript loader (autoload/AgentRegistry.gd):**
```gdscript
extends Node

var agents: Dictionary = {}

func _ready():
    var file = FileAccess.open("res://data/agents.json", FileAccess.READ)
    agents = JSON.parse_string(file.get_as_text())

func get_agent(id: String) -> Dictionary:
    return agents.get(id, {})
```

**Add to Project → Autoload as `AgentRegistry`** so any script can call `AgentRegistry.get_agent("systems-architect")`.

---

### Milestone 4 — First NPC + proximity dialogue

**Time estimate:** ~3 hours
**GDScript required:** NPC script + HUD listener

**What this proves:** The core loop. Walk up to a character → dialogue panel appears → populated from agent JSON definition. This is the interaction template all future NPC scenes follow.

**NPC scene tree:**
```
CharacterBody3D  (npc.gd)
  MeshInstance3D  ← placeholder capsule or box for now
  Area3D          ← proximity trigger (set radius ~2m)
    CollisionShape3D
  Label3D         ← floating name tag above NPC
```

**npc.gd:**
```gdscript
extends CharacterBody3D

@export var agent_id: String = "systems-architect"
var agent_data: Dictionary

func _ready():
    agent_data = AgentRegistry.get_agent(agent_id)
    # Set name tag
    $Label3D.text = agent_data.get("name", agent_id)

func _on_proximity_body_entered(body):
    if body.is_in_group("player"):
        GameEvents.npc_approached.emit(agent_id, agent_data)

func _on_proximity_body_exited(body):
    if body.is_in_group("player"):
        GameEvents.npc_left.emit(agent_id)
```

**GameEvents autoload (global signal bus):**
```gdscript
# autoload/GameEvents.gd
extends Node
signal npc_approached(agent_id: String, agent_data: Dictionary)
signal npc_left(agent_id: String)
signal task_completed(task_id: String)
signal floor_unlocked(floor_id: String)
```

**HUD listens to GameEvents and shows dialogue panel.**

---

### Milestone 5 — Assistant chat UI overlay

**Time estimate:** ~4 hours
**GDScript required:** Chat panel script

**What this is:** A CanvasLayer (always-on-top 2D layer) containing a chat panel. Player toggles it with a key (e.g. Tab or `~`). For now it returns scripted/hardcoded responses. In Phase 2 it routes to a real API call.

This is NOT the same as NPC dialogue. The assistant is always available, always in the corner of the screen, and persists across all scenes.

**Scene tree:**
```
CanvasLayer (assistant_overlay.gd)
  Control
    Panel              ← chat window background
      VBoxContainer
        ScrollContainer
          VBoxContainer  ← message history (add children dynamically)
        HBoxContainer
          LineEdit       ← player input
          Button         ← send
```

**Toggle on keypress:**
```gdscript
func _input(event):
    if event.is_action_pressed("toggle_assistant"):
        $Control.visible = !$Control.visible
```

**Phase 2 upgrade:** Replace `_get_scripted_response()` with an HTTP request to your agent API or WebSocket bridge.

---

### Milestone 6 — Unlock gate system + building map

**Time estimate:** ~5 hours
**GDScript required:** GameState autoload + map UI

**GameState autoload (autoload/GameState.gd):**
```gdscript
extends Node

var unlocked_floors: Array[String] = ["lobby", "server_room"]
var completed_tasks: Array[String] = []
var player_config: Dictionary = {}

func complete_task(task_id: String):
    if task_id not in completed_tasks:
        completed_tasks.append(task_id)
        GameEvents.task_completed.emit(task_id)
        _check_unlock_gates(task_id)

func _check_unlock_gates(task_id: String):
    # Define unlock rules here
    var gates = {
        "first_sprint": "engineering_floor",
        "coding_lesson": "ai_floor",
    }
    if task_id in gates:
        var floor_id = gates[task_id]
        unlock_floor(floor_id)

func unlock_floor(floor_id: String):
    if floor_id not in unlocked_floors:
        unlocked_floors.append(floor_id)
        GameEvents.floor_unlocked.emit(floor_id)

func is_unlocked(floor_id: String) -> bool:
    return floor_id in unlocked_floors

func save():
    # Use ConfigFile or JSON to persist progress
    pass
```

**Building map:** A simple 2D top-down schematic in the HUD. Rooms are colored rects. Locked rooms are grey. Unlocked rooms use their department color. Update by listening to `GameEvents.floor_unlocked`.

---

## Phase 2 — I/O bridge (weeks 4–6)

---

### Milestone 7 — Python WebSocket bridge

**Time estimate:** ~1 day
**Languages:** Python (bridge) + GDScript (Godot side)

**What this is:** A small Python process that runs alongside the game on the same machine. Godot sends task requests over a local WebSocket; the bridge spawns your agent CLI process, captures stdout, and returns the result as JSON. No cloud, no deployment, no auth needed for the prototype.

**bridge.py:**
```python
import asyncio
import websockets
import subprocess
import json

async def handle_connection(websocket):
    async for message in websocket:
        request = json.loads(message)
        agent_id = request.get("agent")
        task = request.get("task")

        # Invoke the actual agent CLI
        result = subprocess.run(
            ["claude", f"@{agent_id}", task],
            capture_output=True,
            text=True,
            timeout=60
        )

        response = {
            "agent": agent_id,
            "task": task,
            "output": result.stdout,
            "error": result.stderr,
            "status": "ok" if result.returncode == 0 else "error"
        }
        await websocket.send(json.dumps(response))

async def main():
    print("Bridge running on ws://localhost:8765")
    async with websockets.serve(handle_connection, "localhost", 8765):
        await asyncio.Future()  # run forever

asyncio.run(main())
```

**Godot side (ws_client.gd):**
```gdscript
extends Node

var socket = WebSocketPeer.new()
signal response_received(data: Dictionary)

func _ready():
    socket.connect_to_url("ws://localhost:8765")

func _process(_delta):
    socket.poll()
    if socket.get_ready_state() == WebSocketPeer.STATE_OPEN:
        while socket.get_available_packet_count():
            var raw = socket.get_packet().get_string_from_utf8()
            var data = JSON.parse_string(raw)
            response_received.emit(data)

func send_task(agent_id: String, task: String):
    var payload = JSON.stringify({ "agent": agent_id, "task": task })
    socket.send_text(payload)
```

---

### Milestone 8 — First live agent output in-world

**Time estimate:** 2–4 hours (integration + testing)

**What happens:**
1. Player walks up to Systems Architect
2. Proximity trigger fires → dialogue panel opens
3. Player types a real question or selects a task
4. Godot sends request to WebSocket bridge
5. Bridge invokes `@systems-architect` via CLI
6. Response JSON returns to Godot
7. Output appears in dialogue panel
8. Response is also logged to the inbox

**This is the milestone where the game becomes the tool.**

Everything after this point is polish, expansion of the world, more NPC characters, better UI, and eventually Phase 3 (streaming output, richer I/O visualization, more agent types).

---

## Quick reference: Godot concepts

| Concept | What it is | When you use it |
|---------|-----------|-----------------|
| `Node3D` | Base for anything in 3D space | Rooms, props, NPCs |
| `CharacterBody3D` | Physics body you control via code | Player, NPCs |
| `Area3D` | Zone that detects when bodies enter/exit | Proximity triggers |
| `CanvasLayer` | 2D layer that renders on top of 3D | HUD, chat panels, maps |
| `Autoload` | Singleton — runs always, accessible anywhere | GameState, AgentRegistry, GameEvents |
| `Signal` | Event system — emit once, many things can listen | The glue between systems |
| `@export` | Expose a variable in the Godot editor | Set agent_id per NPC without code |
| `Resource` | Saved data object | Player profiles, save games |

---

## Install checklist

- [ ] Download Godot 4 from godotengine.org
- [ ] Open First Person Shooter demo and walk around
- [ ] Convert agent .md files to a single agents.json
- [ ] Create new Godot project
- [ ] Copy FPS controller into new project
- [ ] Block out lobby with CSGBox3D tools
- [ ] Create AgentRegistry autoload
- [ ] Create GameEvents autoload
- [ ] Create GameState autoload
- [ ] Place first NPC (Systems Architect) in server room
- [ ] Test proximity trigger → dialogue panel
- [ ] Install Python websockets: `pip install websockets`
- [ ] Run bridge.py and test WebSocket connection from Godot
- [ ] Invoke first real agent through the game

---

*Last updated: April 2026*
