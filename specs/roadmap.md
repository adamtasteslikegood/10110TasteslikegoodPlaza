---
doc_id: ROADMAP
title: 10110 TastesLike Plaza — Bridge-First Platform Roadmap
tier: 3
authority: derived
status: ACTIVE
doc_set_version: 0.2.17
last_updated: 2026-10
owner: adamtasteslikegood
derives_from: [PROJECT-OVERVIEW, DESIGN-25D, SPEC-DRIVERS-025, BRIDGE-PLATFORM-DESIGN]
enforcement: asserted
gates: [Validate Specs:live, Export Godot 4 Prototype:live]
weakest_claim: M9 is complete; M10/M11 are implemented and locally accepted by the owner; M12 is in design; M13–M15 remain planned.
---

# 10110 TastesLike Plaza — Bridge-First Platform Roadmap

> Engine: **Godot 4** (free, MIT license, ~80MB download)
> Language: **GDScript** (reads like Python — approachable without game dev background)
> Target: A UI-agnostic agent platform, exercised through the existing 2.5D Godot office
> Design: [`docs/designs/2.5D-RPG-Prototype.md`](../docs/designs/2.5D-RPG-Prototype.md) (`PROMOTED`, 2026-04-27)
> Post-M8 direction: [`BRIDGE-PLATFORM-DESIGN`](../docs/superpowers/specs/2026-10-18-bridge-first-platform-design.md) (`ACTIVE`, owner-approved 2026-10-18)

---

## Post-M8 sequence — approved bridge-first platform work

M1–M4, M7 and M8 retain their completed status and evidence below. M5 (the
separate scripted assistant overlay) and M6 (unlock progression and building map)
remain deferred frontend milestones. M11 improves NPC conversation; it does not
complete or replace M5 or M6.

The owner approved the written bridge-first design and M10 plan on 2026-10-18.
M9 is complete; M10/M11 are implemented and locally accepted by the owner; M12 is in design; M13–M15 remain planned.
M10 acceptance covers offline configuration, archive/lifecycle and loopback service
tests; it does not establish later UI features or durable application recovery.
`D-033` supersedes broad `D-006` with scoped synchronous NPC calls; `D-034`
authorizes asynchronous buffered domains. M10 policies are `D-035`/`D-036`.
`D-037` is implemented: normal execution, including NPCs, defaults to Claude Code
through Agent SDK; Messages API is explicit API-key-only compatibility, with no
automatic fallback. [Quick start](../QUICKSTART.md) records fresh cloud SDK recall
and its limits separately from the historical direct API proof below.

| Milestone | Scope | Status |
|---|---|---|
| **M9** | Align the design, protocol documentation and roadmap around the bridge-first platform direction; review the written spec | Complete — owner written-spec approval 2026-10-18 |
| **M10** | Validated central configuration, JSONL run/agent transcripts and standard debug logs with quotas and retention | Implemented and locally accepted by owner 2026-10-21 |
| **M11** | Godot NPC conversation history, late responses, mouse window resizing and basic keyboard/scroll controls | Implemented and locally accepted by owner 2026-10-21 |
| **M12** | Configured project/worktree bootstrap, native three-file memory and domain execution through clients | Written spec approved 2026-10-21; implementation plan approved; execution underway |
| **M13** | Durable local user/project/domain application state in SQLite, with explicit restart semantics | Planned after M12 |
| **M14** | Independent execution workspaces beyond M12's minimum | Planned; sequencing with M13 to be reviewed |
| **M15** | Authenticated hosted durable state; hosted provider remains unselected | Planned after M14 |

The detailed scope and acceptance contract live in `BRIDGE-PLATFORM-DESIGN`;
this tier-3 roadmap owns the sequence. These milestones preserve the `D-005`
boundary: replacing Godot with another client must not require a bridge change.

---

## Proof-of-concept critical path (completed)

Milestone 1 → Milestone 4 → Milestone 8

M1 → M4 → M8 proved the concept: walk through a lobby, approach an NPC, and get a
real agent response back in a dialogue panel. That path is complete. M9–M15
sequence the next platform work; M5 and M6 remain deferred.

> **Owner ruling, 2026-10-06 — the milestones serve the prototype.** Where this
> list and the working game disagree, this list is what changes. Sprint 6
> ([`sprint-6-charter.md`](sprint-6-charter.md) §1.1) is the first use of it: M2
> loses its navigation mesh, and M8 below says what proves it rather than only
> that it is done.

---

## Phase 1 — Godot prototype

The time estimates retained under M1–M8 are historical planning estimates, not
current forecasts or delivery commitments.

---

### Milestone 1 — Godot setup + 2.5D player controller ✅ v0.2.8

**Scene tree:**
```
CharacterBody2D   ← player body (scenes/player/player.gd)
  Polygon2D       ← placeholder body shape
  CollisionShape2D ← prevents walking through walls
```

Top-down 8-direction movement, arrows + WASD. ~15 lines of GDScript.

---

### Milestone 2 — Grey-box the office layout ✅

**Time estimate:** 4–6 hours
**GDScript required:** Minimal (door trigger logic only)
**Status:** done in Sprint 6 (`PLZG-258`–`PLZG-260`). Five rooms are grey-boxed in
`scenes/world/office.gd`: the lobby, the server room, the player's office, the
engineering floor and the war room. Each of the four rooms off the lobby has a
doorway trigger, and the corridors to the engineering floor and the war room are
barred until `GameState` unlocks them. What proves it: `godot --headless
tests/smoke_test.tscn` walks the player's body at both barred corridors and is
stopped, opens them through `GameState`, and ends up inside every room;
`python3 scripts/sprint_6_gate.py t4` checks what it reports against the plan.
Nothing in play unlocks a room yet — that progression is M6.

**What "grey-boxing" means:**
Standard game dev practice — build the entire space with plain grey/white geometry boxes before spending any time on textures, lighting, or art. Walk through it. Does the lobby feel right? Are the corridors the right width? Is the server room in a sensible place? Validate the space before investing in visuals.

**Godot tools used:**
```
TileMap / StaticBody2D  ← walls, floors (2.5D top-down)
Area2D                  ← doorway trigger zones (detects when player enters)
```

A `NavigationRegion2D` pathfinding mesh was part of this milestone and is **no
longer** (owner ruling 2026-10-06): no NPC walks yet, so nothing would consume
it. It is scheduled by no milestone until one needs it.

**Rooms to block out (Week 1 scope):**
- [x] Lobby / entrance
- [x] Player's office
- [x] Server room (Core agents)
- [x] Engineering floor (open plan)
- [x] War room / meeting room
- [x] 2–3 locked corridors — two, to the engineering floor and the war room, which open later in the week (`SB-08`, `SB-12`); corridors to floors that do not exist yet arrive with those floors. The owner confirmed that reading on 2026-10-07 (issue #306)

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

### Milestone 3 — Load employee directory as game data ✅

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

### Milestone 4 — First NPC + proximity dialogue ✅

**Time estimate:** ~3 hours
**GDScript required:** NPC script + HUD listener

**What this proves:** The core loop. Walk up to a character → dialogue panel appears → populated from agent JSON definition. This is the interaction template all future NPC scenes follow.

**NPC scene tree:**
```
CharacterBody2D  (agent_npc.gd)
  Polygon2D      ← placeholder body shape, colour-tinted per department
  Area2D         ← proximity trigger
    CollisionShape2D
  Label          ← floating name tag above NPC
```

**agent_npc.gd:**
```gdscript
extends CharacterBody2D

@export var agent_id: String = "systems-architect"
var agent_data: Dictionary

func _ready():
    agent_data = AgentRegistry.get_agent(agent_id)
    $Label.text = agent_data.get("name", agent_id)

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

**Status:** deferred. This is a separate assistant surface, not the NPC
conversation window scheduled under M11.

**Time estimate:** ~4 hours
**GDScript required:** Chat panel script

**What this is:** A CanvasLayer (always-on-top 2D layer) containing a chat panel.
Player toggles it with a key (e.g. Tab or `~`). The planned first version returns
scripted/hardcoded responses; connecting it to a real API is a later upgrade.

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

**Later upgrade:** Replace `_get_scripted_response()` with an HTTP request to your agent API or WebSocket bridge. No milestone currently schedules that upgrade.

---

### Milestone 6 — Unlock gate system + building map

**Status:** deferred. The room barriers verified under M2 are built; the gameplay
progression and building-map UI described here remain separate work.

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

## Phase 2 — I/O bridge

---

### Milestone 7 — Python WebSocket bridge ✅

**Time estimate:** ~1 day
**Languages:** Python (bridge) + GDScript (Godot side)

**What this is:** A small Python process that runs alongside the game on the same
machine. The original M7/M8 NPC proof sent requests over a local WebSocket to
the direct Claude Messages API and returned a complete JSON response. Current
NPC execution instead defaults to Claude Code through Agent SDK under `D-037`,
with native CLI authentication and a separately selected API-key-only compatibility
adapter. The domain-session path also uses Agent SDK; connecting that lifecycle
and execution to the frontend with live verification is planned under M12. The
owner-approved execution scopes
are synchronous NPC calls with timeout (`D-033`, superseding `D-006`) and
asynchronous buffered domains (`D-034`).

> **The two code blocks below are the original sketch, kept for the shape of the idea.**
> The shipped code is `bridge/server.py`, `bridge/conversation.py` and
> `scenes/bridge/ws_client.gd` (autoload `BridgeClient`); the wire format is
> `bridge/PROTOCOL.md`. The sketch shells out to a CLI and sends `{"agent", "task"}`;
> the shipped bridge uses a different wire shape and invokes Claude Code through
> Agent SDK rather than the sketch's manual CLI subprocess.

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

### Milestone 8 — First live agent output in-world ✅

**Time estimate:** 2–4 hours (integration + testing)

**What happens:**
1. Player walks up to Systems Architect
2. Proximity trigger fires → dialogue panel opens
3. Player types a real question or selects a task
4. Godot sends request to WebSocket bridge
5. Bridge loads the agent definition from its own store and calls the Claude API
6. Response JSON returns to Godot
7. Output appears in dialogue panel

Logging the response to an inbox was step 8 of this list. It is **not part of M8 and
is not built** — deferred until the game is ready for an inbox (owner ruling
2026-10-06, `PLZG-247`). The inbox itself is introduced by `SB-11` and used by
`SB-14`; no milestone here schedules it yet.

**What proves it.** The ✅ above records that the path was built and exercised by
hand in Sprint 4. Until Sprint 6 no command proved it: `tests/smoke_test.gd`
emits the response signal with a literal string and opens no socket. From
Sprint 6 the proof is `python3 scripts/sprint_6_gate.py live` — two real turns
through the bridge, from Godot and from a client with no Godot in it, where the
second reply has to return a value only the first turn carried. It needs a
credential, so it is a local gate, not a CI job (`PLZG-261`). It first passed on
2026-10-07 PDT (`PLZG-262`), after two changes: the bridge now keeps a history
per connection and agent, without which every run failed on the second turn;
and the runner asks its question as a project name, because asked for a "code
word" the agent declined to repeat it about one try in three.

**This is the milestone where the game becomes the tool.**

M8 proves live conversation. The next sequence builds configuration and
observability, a usable NPC conversation window, domain execution, durable state
and execution isolation. Streaming, world expansion and additional frontend
surfaces remain outside that sequence unless a later design schedules them.

---

## Phase 3 — Bridge-first platform (approved M9–M15)

> **Scope update, 2026-10-21:** the owner accepted M10/M11 laptop operation
> and approved the M12 direction with a dedicated execution Git worktree now.
> The bridge creates/reuses that worktree and three project-scoped memory files;
> non-Git projects first require Chief Architect confirmation to initialize `main`.
> The [detailed M12 spec](../docs/superpowers/specs/2026-10-21-m12-domain-execution-design.md)
> is ACTIVE, with written approval recorded 2026-10-21. The
> [implementation plan](../docs/superpowers/plans/2026-10-21-m12-project-execution.md)
> is owner-approved for subagent-driven execution. M12 implementation is not complete. M13/M14
> sequencing may change or combine state and isolation; M15's provider remains
> unselected. See the owner update in `BRIDGE-PLATFORM-DESIGN`.

The following milestones derive from `BRIDGE-PLATFORM-DESIGN` (`ACTIVE`,
owner-approved 2026-10-18). M9's documentation approval is complete. M10 has
implemented settings/recording and deterministic acceptance coverage. M11 has
implemented history/controls and automated coverage, with owner laptop acceptance
recorded 2026-10-21. M12–M15 acceptance criteria describe future verification.
Existing M8 conversation behavior remains the regression baseline.

### Milestone 9 — Align and review the platform direction

**Status:** complete, owner-approved 2026-10-18. The written design, protocol
documentation and roadmap distinguish the prototype from planned platform work.
The owner resolved execution scope (`SPEC-DRIVERS-025` §4.13); `D-006` is superseded by scoped NPC
`D-033`, with domains separately authorized in `D-034`. M10 policy ratification
(`D-035`/`D-036`) authorizes implementation; it selects no hosted provider and
ships no product code.

### Milestone 10 — Configuration and observability

**Status:** implemented and deterministically tested under the owner-approved
[M10 implementation plan](../docs/superpowers/plans/2026-10-18-m10-config-observability.md).
`bridge/tests/` covers validation, Linux writer ownership/crash release, quota/age
retention, redaction and engine lifecycle. Real loopback integration tests use
fake providers and real temporary archives to verify independent connections and
agents, unchanged replies/context, disk truncation, rotation/pruning, recording
failure/recovery and disabled transcripts. These tests make no live model calls.

A validated central configuration contract is shared by bridge entry points.
JSONL run/agent transcripts and standard debug logs have explicit quota and
retention behavior. Invalid configuration failures, correlated run/agent records
and bounded retention are covered by the checks defined in the design.
These records support inspection and debugging; they are separate from the durable
application state introduced in M13.

### Milestone 11 — Usable Godot NPC conversation window

**Status:** implemented with deterministic store, transport and actual-panel
headless coverage plus a real Godot-client/Python-bridge fake-provider integration
for delayed responses, per-agent failure, pending disconnect and fresh reconnect.
Display limits include all retained generations and drafts; provider context and
disk quotas remain independent. Existing smoke is preserved. On 2026-10-21 the
owner accepted M10/M11 operation on the laptop
([PLZG-284](https://tasteslikegood.atlassian.net/browse/PLZG-284));
this is owner-reported milestone acceptance; no itemized desktop test log was supplied.
The earlier direct Messages API recall smoke
is historical compatibility evidence only. A separate real Claude Code/Agent SDK
smoke passed at 2026-10-18 22:32:53 UTC: two-turn recall from Godot and Python,
first attempt each, cloud API key inherited by CLI, four distinct observed SDK
session IDs. [Fresh evidence](evidence/npc-sdk-live-2026-10-18.json) records its
limits. The owner separately confirmed laptop Claude subscription and API-token
authentication on 2026-10-21; the output cap was a setting. The runner's open
manifest remains insufficient graceful-shutdown proof. M12 is in design.

Retain history for each NPC conversation across closing and reopening its panel,
including responses that arrive after dismissal. Add mouse resizing with the
window bounded to the viewport and its input/history layout usable at supported
sizes. Provide mouse-wheel and scrollbar history navigation, Page Up/Page Down,
input focus, Enter to send, Escape to release chat focus while preserving draft
input and pending requests, and basic Ctrl+Home/Ctrl+End
navigation with the focus behavior specified in the design. Verify history
restoration, late-response routing, resize limits and the input/focus bindings.

The frontend owns window geometry and keyboard behavior. The bridge continues
to exchange UI-agnostic requests and responses (`D-005`). This milestone neither
builds M5's scripted assistant nor M6's unlock/map system. Any history recovery
across process restarts must follow the explicit state contract in M13.

### Milestone 12 — Domain lifecycle and live execution

The owner now requires one configured project per bridge/game session, with
`WORKSPACE_ROOT_DIR` overridden by `PLAZA_WORKSPACE_ROOT_DIR`. The bridge
creates/reuses its dedicated execution worktree and three repository-isolated
memory files (TODO, handoff and turn summaries). Empty/non-Git projects require
Chief Architect confirmation before repository creation with `main`.
Other NPCs refer the player to the Chief Architect when setup is needed; its
interaction and affirmative decision unlock initialization without another human
prompt. A common bridge gate verifies Git/worktree/memory readiness before tools.
The [M12 written design](../docs/superpowers/specs/2026-10-21-m12-domain-execution-design.md)
defines approved bootstrap, memory, reservation, lifecycle and client contracts
(`D-038`/`D-039`). The
[implementation plan](../docs/superpowers/plans/2026-10-21-m12-project-execution.md)
is owner-approved for subagent-driven execution.

Connect domain lifecycle and execution to the frontend through the UI-agnostic
bridge contract. Verify the complete path with a live Agent SDK run, including
the lifecycle transitions and failures named by the design. Existing backend
scaffolding or a successful NPC conversation through either SDK or Messages API
alone does not complete this milestone or establish domain/background execution.
Keep the completed M8 conversation proof distinct from this new
execution proof. Preserve synchronous NPC calls with timeout (`D-033`) and
asynchronous buffered domain execution with existing caps (`D-034`).

### Milestone 13 — Durable local application state

Extend M12's bounded Markdown project notes with structured local user, project
and domain application state in SQLite. Define and
verify which records survive a restart, how clients recover them, and how
interrupted or non-resumable work is represented. Application-state recovery
must not imply that a prior SDK process continues or resumes automatically.
JSONL transcripts and debug logs from M10 remain diagnostic records rather than
the application's state store.

### Milestone 14 — Independent execution workspaces

Extend M12's minimum dedicated worktree to independently assigned workspaces.
Its order relative to M13 may change or combine persistence and isolation in a
provider-specific design. Isolate execution under the design's ownership,
lifecycle and cleanup contract. Verify that concurrent or failed runs cannot
silently alter another run's checkout or the user's primary checkout, and that
retained work and cleanup outcomes remain inspectable.

### Milestone 15 — Authenticated hosted durable state

Extend the durable-state boundary to authenticated hosted use, with explicit
user/project access controls and recovery behavior. Verify authentication,
authorisation and durable recovery against the chosen provider before claiming
hosted readiness. **The provider is unselected**; this milestone records the
capability and its position in the sequence, not a vendor commitment.

---

## Quick reference: Godot concepts

| Concept | What it is | When you use it |
|---------|-----------|-----------------|
| `Node2D` | Base for anything in 2D space | Rooms, props, NPCs |
| `CharacterBody2D` | Physics body you control via code | Player, NPCs |
| `Area2D` | Zone that detects when bodies enter/exit | Proximity triggers |
| `CanvasLayer` | 2D layer that renders on top of the scene | HUD, chat panels, maps |
| `Autoload` | Singleton — runs always, accessible anywhere | GameState, AgentRegistry, GameEvents |
| `Signal` | Event system — emit once, many things can listen | The glue between systems |
| `@export` | Expose a variable in the Godot editor | Set agent_id per NPC without code |
| `Resource` | Saved data object | Player profiles, save games |

---

## Install checklist

- [x] Download Godot 4 from godotengine.org
- [x] Create Godot project with autoloads
- [x] Player controller (CharacterBody2D, 8-direction)
- [x] Convert agent .md files to a single agents.json
- [x] Create AgentRegistry, GameEvents, GameState autoloads
- [x] Place first NPC (Systems Architect) in server room
- [x] Test proximity trigger → dialogue panel
- [x] Block out lobby with StaticBody2D
- [x] Run bridge.py and test WebSocket connection from Godot
- [x] Invoke first real agent through the game

---

*Last updated: October 2026*
