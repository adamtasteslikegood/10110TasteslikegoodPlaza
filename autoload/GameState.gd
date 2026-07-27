extends Node

## Progression state: what is unlocked, what has been completed, who the player is.
##
## D-009 locks the mechanic: completed tasks gate rooms and floors, and unlocks are
## earned rather than handed over. This node owns that state so doors, the HUD and
## the eventual save system all read one source instead of each tracking their own.
##
## Round 3 scope: only `lobby` and `server-room` exist, and only the server-room
## door consults `is_unlocked()`. The gate table below is where later rooms attach.

## Rooms open from the start. SB-04 has the player arriving alone in the lobby and
## exploring freely, so neither Day 1 space is gated -- the door logic is exercised
## by wiring, not by locking the player out of the one thing there is to see.
const INITIALLY_UNLOCKED: Array[String] = ["lobby", "server-room"]

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
