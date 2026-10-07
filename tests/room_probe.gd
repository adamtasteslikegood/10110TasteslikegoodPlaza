extends Node

## Headless probe: prints what the running office declares, and judges nothing.
##
##     godot --headless tests/room_probe.tscn
##
## `scripts/sprint_6_gate.py` reads the three PROBE lines and compares them with
## the room list in `specs/sprint-6-loop-plan.json`. Keeping the judgement there
## means this file holds no second copy of that list to drift from it.
##
## The contract a room, doorway or locked corridor has to meet to be seen:
## be in the group named below, and carry a `room_id` metadata string. A
## doorway's `room_id` is the room it leads INTO. Node names and types are free.
## A locked corridor is reported only while `GameState.is_unlocked(room_id)` is
## false; whether it physically stops a body is the smoke test's to show.
##
## The scene goes into the tree before anything is read, for the reason
## smoke_test.gd gives: instantiate() alone never fires _ready(), and the office
## builds its geometry there.

const GROUPS := ["rooms", "doorways", "locked_corridors"]


func _ready() -> void:
	var main: PackedScene = load("res://scenes/main.tscn")
	if main == null:
		printerr("PROBE FAILED: res://scenes/main.tscn failed to load")
		get_tree().quit(1)
		return

	var instance: Node = main.instantiate()
	get_tree().root.add_child.call_deferred(instance)
	await get_tree().process_frame

	for group in GROUPS:
		var ids: Array[String] = []
		for node in get_tree().get_nodes_in_group(group):
			var room_id := str(node.get_meta("room_id", ""))
			if room_id == "" or ids.has(room_id):
				continue
			# A corridor is locked only while GameState says its room is. One
			# that declares itself locked and leads somewhere open is a label.
			if group == "locked_corridors" and GameState.is_unlocked(room_id):
				continue
			ids.append(room_id)
		ids.sort()
		print("PROBE %s: %s" % [group, ",".join(ids)])

	instance.queue_free()
	get_tree().quit(0)
