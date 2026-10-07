extends Node

## Progression state: what is unlocked, what has been completed, who the player is.
##
## D-009 locks the mechanic: completed tasks gate rooms and floors, and unlocks are
## earned rather than handed over. This node owns that state so doors, the HUD and
## the eventual save system all read one source instead of each tracking their own.
##
## Every doorway in `scenes/world/office.gd` consults `is_unlocked()`, and a room
## that is not unlocked has a barrier across its corridor until `unlock()` runs.
## The gate table below is where the progression that calls it attaches.

## Rooms open from the start: the three Day 1 spaces. SB-04 has the player
## arriving alone in the lobby and exploring freely, SB-05 meets the Systems
## Architect in the server room, and SB-07 has the player find their own office.
## Everything else starts locked -- the engineering floor opens on Day 2 (SB-08)
## and the war room hosts the Day 3 standup (SB-12).
const INITIALLY_UNLOCKED: Array[String] = ["lobby", "server-room", "player-office"]

## floor_id -> the task_id that opens it. Empty until M5 introduces real tasks;
## complete_task() already reads it so the wiring is proven before it carries load.
const UNLOCK_GATES: Dictionary = {}

var unlocked_floors: Array[String] = []
var completed_tasks: Array[String] = []
var player_config: Dictionary = {}


func _ready() -> void:
	unlocked_floors = INITIALLY_UNLOCKED.duplicate()


func is_unlocked(floor_id: String) -> bool:
	return floor_id in unlocked_floors


func unlock(floor_id: String) -> void:
	if floor_id in unlocked_floors:
		return
	unlocked_floors.append(floor_id)
	GameEvents.floor_unlocked.emit(floor_id)


## Record a completed task and open anything it gates.
func complete_task(task_id: String) -> void:
	if task_id in completed_tasks:
		return
	completed_tasks.append(task_id)
	GameEvents.task_completed.emit(task_id)

	for floor_id in UNLOCK_GATES:
		if UNLOCK_GATES[floor_id] == task_id:
			unlock(floor_id)


func has_completed(task_id: String) -> bool:
	return task_id in completed_tasks
