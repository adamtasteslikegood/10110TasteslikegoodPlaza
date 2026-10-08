extends Node

## Headless smoke test. Run by CI and runnable locally:
##
##     godot --headless tests/smoke_test.tscn
##
## Exits 0 when every assertion holds, 1 otherwise, so it works as a build gate.
## META-SPEC section 5.8 requires acceptance criteria to be machine-checkable; this
## is what makes "the office loads and knows who works there" one of them.
##
## Before this existed the `Export Godot 4 Prototype` job echoed a string and went
## green, which is indistinguishable from a passing build right up until it isn't.
##
## It also walks the office (Sprint 6 Gate A, PLZG-260) and says what it found on
## two lines that `scripts/sprint_6_gate.py t4` reads:
##
##     SMOKE corridors_blocked: <room ids whose locked corridor stopped the player>
##     SMOKE rooms_reachable: <room ids the player's body ended up inside>
##
## The gate compares those with the plan's room list, so the walk holds no list
## of rooms to fall out of step with it. The one list in this file is
## DAY_ONE_ROOMS, and it is not scene state: it is the storyboard's statement of
## what is open before anything is earned, and it changes only when that does. A room that exists but is walled shut, or
## a corridor that is locked in name only, changes a line and turns the gate red.

## D-024 fixes the count: 133 source files, three colliding slugs curated down to 132.
const EXPECTED_AGENT_COUNT := 132

## Core department, gold (D-017). SB-05 and SB-06 put both of these in the server room.
const CORE_DEPT := "core"
const CORE_COLOR := "#FFD700"

## Feel values are PLAYTESTED, NOT FIXED. 48px proximity and 55 chars/sec were both
## confirmed good in-engine on 2026-07-26 and are expected to be fine-tuned again.
##
## So these assert a BAND, never an equality. An `== 48.0` check would turn every
## future tuning pass into a red build, which teaches people to delete the check.
## A band leaves tuning free and catches only the two things that are actually
## broken rather than merely different.
##
## Both bounds below are DERIVED from the scene and re-derived at runtime, so
## moving an NPC moves the bound instead of quietly invalidating it. That matters
## more than it sounds: a hand-written constant here would be a second copy of
## scene state, which is the failure mode branching-strategy.md section 9 now has
## five entries for.
##
## The .tscn is also why this lives in a test and not a comment. `radius = 48.0`
## sits in agent_npc.tscn, and Godot rewrites .tscn files wholesale on save --
## any warning comment placed next to it disappears the first time the scene is
## opened in the editor. A test survives.

## The rooms the storyboard has open before anything is earned. A concept fact
## (SB-04, SB-05, SB-07), not a copy of scene state.
const DAY_ONE_ROOMS: Array[String] = ["lobby", "server-room", "player-office"]

## How far the walker moves per sweep. Smaller than any wall is thick, though
## move_and_collide sweeps the whole motion and would not tunnel anyway.
const WALK_STEP := 8.0

var _failures: Array[String] = []


func _ready() -> void:
	_check_autoloads()
	_check_registry()
	_check_core_agents()
	await _check_scene_tree()

	if _failures.is_empty():
		print("smoke_test: OK — %d agents, all checks passed." % AgentRegistry.count())
		get_tree().quit(0)
		return

	printerr("smoke_test: %d FAILURE(S)" % _failures.size())
	for failure in _failures:
		printerr("  - %s" % failure)
	get_tree().quit(1)


func _fail(message: String) -> void:
	_failures.append(message)


func _check_autoloads() -> void:
	for name in ["AgentRegistry", "GameEvents", "GameState", "BridgeClient"]:
		if not get_tree().root.has_node(name):
			_fail("autoload %s did not resolve" % name)


func _check_registry() -> void:
	if not AgentRegistry.is_loaded():
		_fail("AgentRegistry failed to load data/agents.json")
		return
	if AgentRegistry.count() != EXPECTED_AGENT_COUNT:
		_fail(
			(
				"expected %d agents, got %d — regenerate with scripts/generate_agents_json.py"
				% [EXPECTED_AGENT_COUNT, AgentRegistry.count()]
			)
		)


func _check_core_agents() -> void:
	# The two agents the storyboard actually names. If the generator renames or
	# drops either, the office loses its only two inhabitants and this says so.
	for agent_id in ["systems-architect", "security-auditor"]:
		var agent := AgentRegistry.get_agent(agent_id)
		if agent.is_empty():
			_fail("'%s' is missing from the registry (SB-05/SB-06 depend on it)" % agent_id)
			continue
		if agent.get("dept", "") != CORE_DEPT:
			_fail("'%s' dept is %s, expected %s" % [agent_id, agent.get("dept"), CORE_DEPT])
		if agent.get("color", "") != CORE_COLOR:
			_fail("'%s' colour is %s, expected %s" % [agent_id, agent.get("color"), CORE_COLOR])
		if not (agent.get("tools", []) is Array):
			# 83 upstream agents write `tools:` as a bare comma string, which YAML
			# reads as a str. The generator normalises all three syntaxes; if that
			# ever regresses, the dialogue panel would iterate characters.
			_fail("'%s' tools is not an Array — generator normalisation regressed" % agent_id)

	var core_ids := AgentRegistry.ids_in_dept(CORE_DEPT)
	if core_ids.size() != 8:
		_fail("expected 8 core agents, got %d" % core_ids.size())


func _check_scene_tree() -> void:
	# The main scene is what `godot .` actually runs.
	#
	# This check used to call instantiate() and stop there, which was close to
	# useless: instantiate() never fires _ready(), so @onready node paths stayed
	# unresolved and nothing in any script actually executed. A renamed node in
	# dialogue_panel.tscn or a runtime error while building the office walls would
	# have sailed straight through a green smoke test and only shown up when a
	# human ran `godot .`. Found by Codex review on PR #19.
	#
	# So: put it in the tree, let _ready() run everywhere, and assert on effects
	# that only exist if it ran correctly.
	var main: PackedScene = load("res://scenes/main.tscn")
	if main == null:
		_fail("res://scenes/main.tscn failed to load")
		return

	var instance: Node = main.instantiate()
	# Deferred because adding to root while this node's own _ready() is still
	# running would fight the scene tree's setup pass.
	get_tree().root.add_child.call_deferred(instance)
	await get_tree().process_frame

	for path in ["Office", "Player", "HUD"]:
		if not instance.has_node(path):
			_fail("main.tscn is missing node '%s'" % path)

	_check_npc_ready(instance)
	_check_office_built(instance)
	_check_hud_ready(instance)
	_check_feel_bands(instance)
	await _check_walk(instance)

	instance.queue_free()


func _check_feel_bands(instance: Node) -> void:
	var a: Node2D = instance.get_node_or_null("Office/SystemsArchitect")
	var b: Node2D = instance.get_node_or_null("Office/SecurityAuditor")
	if a == null or b == null:
		# Already reported by _check_npc_ready; nothing to derive a bound from.
		return

	var shape: CollisionShape2D = a.get_node_or_null("Proximity/ProximityShape")
	if shape == null:
		_fail("AgentNPC has no Proximity/ProximityShape — the whole M4 trigger is gone")
		return
	if not (shape.shape is CircleShape2D):
		_fail("proximity shape is %s, expected CircleShape2D" % [shape.shape])
		return
	var radius: float = (shape.shape as CircleShape2D).radius

	# Floor: the NPC's own body blocks you, so a radius inside it can never be
	# entered -- you collide with the agent before you trigger them.
	#
	# Read from the scene, NOT from a constant here. The first version of this
	# check hardcoded Vector2(28, 32) while the comment above claimed both bounds
	# were scene-derived -- a second copy of scene state in the very commit that
	# argued against second copies of scene state. Caught by the independent
	# Claude review on PR #20 (#21).
	var body: CollisionShape2D = a.get_node_or_null("Collision")
	if body == null or not (body.shape is RectangleShape2D):
		_fail("AgentNPC has no RectangleShape2D 'Collision' — cannot derive the proximity floor")
		return
	var floor_px: float = (body.shape as RectangleShape2D).size.length() * 0.5
	if radius <= floor_px:
		_fail(
			(
				"proximity radius %.1f is inside the NPC's own %.1fpx collision body — unreachable"
				% [radius, floor_px]
			)
		)

	# Ceiling: half the gap between the two server-room agents. Past that the
	# circles overlap, you stand in both, and the panel shows whichever signal
	# arrived last rather than who you walked up to.
	var ceiling_px := a.position.distance_to(b.position) * 0.5
	if radius >= ceiling_px:
		_fail(
			(
				"proximity radius %.1f >= %.1f (half the SB-05/SB-06 gap) — both NPCs fire at once"
				% [radius, ceiling_px]
			)
		)

	# D-007 locks the typewriter itself, not its speed. A rate high enough to
	# finish inside one frame is indistinguishable from having removed it, which
	# is a LOCKED decision quietly reverting rather than a tuning choice.
	var hud: Node = instance.get_node_or_null("HUD")
	if hud == null:
		return
	var consts: Dictionary = hud.get_script().get_script_constant_map()
	if not consts.has("CHARS_PER_SECOND"):
		_fail("dialogue_panel.gd no longer defines CHARS_PER_SECOND — D-007 has no rate")
		return
	var cps: float = consts["CHARS_PER_SECOND"]
	# 60fps, so >600 reveals a 10-char line instantly. Under 10 an average
	# description outlasts anyone's patience and the panel reads as hung.
	if cps < 10.0 or cps > 600.0:
		_fail("CHARS_PER_SECOND is %.1f — outside the readable 10..600 band (D-007)" % cps)


func _check_npc_ready(instance: Node) -> void:
	var npc: Node = instance.get_node_or_null("Office/SystemsArchitect")
	if npc == null:
		_fail("office.tscn is missing the SB-05 NPC")
		return
	# agent_data is only populated in _ready(), and only from AgentRegistry.
	if npc.agent_data.is_empty():
		_fail("SystemsArchitect._ready() did not populate agent_data")
		return
	var tag: Label = npc.get_node_or_null("NameTag")
	if tag == null:
		_fail("AgentNPC has no NameTag node — agent_npc.gd's @onready path is broken")
	elif tag.text != "Systems Architect":
		_fail("NameTag reads %s, expected 'Systems Architect'" % [tag.text])


func _check_office_built(instance: Node) -> void:
	var office: Node = instance.get_node_or_null("Office")
	if office == null:
		return
	# One child per entry in each of office.gd's geometry tables, plus whatever
	# the .tscn already holds. Counted from the tables themselves, so adding a
	# room raises the bar instead of leaving a stale number here. A low count
	# means the build in _ready() errored partway.
	var consts: Dictionary = office.get_script().get_script_constant_map()
	var expected := 0
	for table in ["FLOORS", "WALLS", "ROOMS", "DOORWAYS"]:
		if not (consts.get(table) is Array):
			_fail("office.gd no longer defines the %s table" % table)
			return
		expected += (consts[table] as Array).size()
	var built := office.get_child_count()
	if built < expected:
		_fail(
			(
				"Office has %d children, its tables describe %d — geometry build did not finish"
				% [built, expected]
			)
		)


func _check_hud_ready(instance: Node) -> void:
	var hud: Node = instance.get_node_or_null("HUD")
	if hud == null:
		return
	var panel: Panel = hud.get_node_or_null("Panel")
	if panel == null:
		_fail("dialogue_panel.tscn has no Panel node")
		return
	if panel.visible:
		_fail("dialogue panel starts visible — it should be hidden until an NPC is approached")

	# Then drive the actual M4 loop. Checking that the panel starts hidden only
	# dereferences ONE of dialogue_panel.gd's @onready paths, so a renamed node
	# anywhere else still passed — confirmed by renaming BodyLabel and watching an
	# earlier version of this test go green. Emitting the signal forces every path
	# to resolve and asserts the text actually arrived.
	var agent := AgentRegistry.get_agent("systems-architect")
	GameEvents.npc_approached.emit("systems-architect", agent)

	if not panel.visible:
		_fail("panel did not open on GameEvents.npc_approached")

	var name_label: Label = hud.get_node_or_null("Panel/Margin/Rows/Header/Titles/NameLabel")
	if name_label == null:
		_fail("dialogue panel: NameLabel path does not resolve")
	elif name_label.text != "Systems Architect":
		_fail("dialogue panel shows %s, expected 'Systems Architect'" % [name_label.text])

	var body_label: RichTextLabel = hud.get_node_or_null("Panel/Margin/Rows/BodyLabel")
	if body_label == null:
		_fail("dialogue panel: BodyLabel path does not resolve")
	elif body_label.text != agent.get("description", ""):
		_fail("dialogue panel body text was not populated from the agent record")
	elif body_label.visible_characters != 0:
		# D-007: the reveal starts at zero and is driven by _process.
		_fail("typewriter did not reset — visible_characters is %d, expected 0" % body_label.visible_characters)
	elif not body_label.scroll_active:
		_fail("BodyLabel scroll_active is false — long responses will overflow")

	# M8 bridge wiring: verify the input row exists and the response path works.
	var input_row: HBoxContainer = hud.get_node_or_null("Panel/Margin/Rows/InputRow")
	if input_row == null:
		_fail("dialogue panel: InputRow path does not resolve — M8 input missing")
	elif not input_row.visible:
		_fail("dialogue panel: InputRow is hidden while NPC is approached")

	var question_input: LineEdit = hud.get_node_or_null("Panel/Margin/Rows/InputRow/QuestionInput")
	if question_input == null:
		_fail("dialogue panel: QuestionInput path does not resolve")

	var status_label: Label = hud.get_node_or_null("Panel/Margin/Rows/StatusLabel")
	if status_label == null:
		_fail("dialogue panel: StatusLabel path does not resolve")

	# Simulate a bridge response and verify the typewriter resets on it.
	GameEvents.agent_response_received.emit("systems-architect", "Hello from the bridge.")
	if body_label.text != "Hello from the bridge.":
		_fail("bridge response was not rendered in BodyLabel")
	elif body_label.visible_characters != 0:
		_fail("typewriter did not reset on bridge response — visible_characters is %d" % body_label.visible_characters)

	GameEvents.npc_left.emit("systems-architect")
	if panel.visible:
		_fail("panel did not close on GameEvents.npc_left")


## Walk the player's own body through the running office.
##
## Everything here is read from the scene: rooms and doorways from their groups,
## positions from the nodes, the start from the room no doorway leads into. Node
## existence proves nothing about a floor plan -- a wall collider across a
## doorway leaves every node in place (charter risk R4) -- so "reachable" means
## the room's Area2D reports the body inside it after the body was moved there
## by collision-checked motion.
func _check_walk(instance: Node) -> void:
	var player := instance.get_node_or_null("Player") as CharacterBody2D
	if player == null:
		_fail("Player is not a CharacterBody2D — nothing to walk the office with")
		return
	await get_tree().physics_frame

	var rooms := _by_room_id("rooms")
	var doorways := _by_room_id("doorways")
	var starts: Array[String] = []
	for room_id in rooms:
		if not doorways.has(room_id):
			starts.append(room_id)
	if starts.size() != 1:
		_fail("expected exactly one room no doorway leads into, found %s" % [starts])
		return
	var start: Vector2 = (rooms[starts[0]] as Node2D).global_position

	var reached: Array[String] = []
	if await _is_inside(player, start, rooms[starts[0]]):
		reached.append(starts[0])
	else:
		_fail("the player cannot stand in the start room '%s'" % starts[0])

	# Day 1 is free exploration: SB-04 is the lobby, SB-05 the server room, SB-07
	# the player's office. Asserted before the walk because the walk alone would
	# not notice one of them starting locked -- it would find the barrier, see it
	# hold, unlock it and walk in, all green.
	for room_id in DAY_ONE_ROOMS:
		if not rooms.has(room_id):
			_fail("Day 1 room '%s' is not in the office" % room_id)
		elif not GameState.is_unlocked(room_id):
			_fail("'%s' should be open on Day 1 (SB-04, SB-05, SB-07)" % room_id)

	# Locked corridors first, while they are locked.
	var blocked: Array[String] = []
	var locked := _by_room_id("locked_corridors")
	for room_id in locked:
		if GameState.is_unlocked(room_id):
			_fail("corridor to '%s' is in locked_corridors but GameState has it open" % room_id)
			continue
		if not rooms.has(room_id) or not doorways.has(room_id):
			_fail("locked corridor names '%s', which has no room or no doorway" % room_id)
			continue
		var stopped_by: Object = _walk(player, [start, doorways[room_id], rooms[room_id]])
		if await _is_inside(player, player.global_position, rooms[room_id]):
			_fail("locked corridor to '%s' did not stop the player" % room_id)
		elif stopped_by != locked[room_id]:
			_fail("the walk to locked '%s' was stopped by %s, not its corridor" % [room_id, stopped_by])
		else:
			blocked.append(room_id)
	# A room GameState holds locked has to be locked in the world too. Without
	# this, deleting every barrier leaves nothing above to fail: no corridor
	# declares itself locked, so none is found wanting.
	for room_id in rooms:
		if not GameState.is_unlocked(room_id) and not blocked.has(room_id):
			_fail("GameState has '%s' locked but no corridor stopped the player" % room_id)
	print("SMOKE corridors_blocked: %s" % ",".join(blocked))

	# Then open them the way the game will -- through GameState -- and walk in.
	for room_id in locked:
		GameState.unlock(room_id)
	await get_tree().physics_frame
	for room_id in locked:
		if is_instance_valid(locked[room_id]) and locked[room_id].is_in_group("locked_corridors"):
			_fail("corridor to '%s' is still locked after GameState.unlock" % room_id)

	for room_id in doorways:
		if not rooms.has(room_id):
			_fail("a doorway leads into '%s', which is not a room" % room_id)
			continue
		_walk(player, [start, doorways[room_id], rooms[room_id]])
		if await _is_inside(player, player.global_position, rooms[room_id]):
			reached.append(room_id)
		else:
			_fail("room '%s' is not reachable from '%s'" % [room_id, starts[0]])
	reached.sort()
	print("SMOKE rooms_reachable: %s" % ",".join(reached))


## room_id -> node, for one of the three groups office.gd fills.
func _by_room_id(group: String) -> Dictionary:
	var found: Dictionary = {}
	for node in get_tree().get_nodes_in_group(group):
		var room_id := str(node.get_meta("room_id", ""))
		if room_id != "" and node is Node2D:
			found[room_id] = node
	return found


## Move the body along `route` (a start position, then nodes to head for) and
## return whatever stopped it, or null if it got to the end.
func _walk(player: CharacterBody2D, route: Array) -> Object:
	player.global_position = route[0]
	for target_node in route.slice(1):
		var target: Vector2 = (target_node as Node2D).global_position
		# Twice the straight-line distance: enough to arrive, never an endless loop.
		var sweeps := int(player.global_position.distance_to(target) / WALK_STEP) * 2 + 2
		for _i in sweeps:
			var to := target - player.global_position
			if to.length() <= WALK_STEP:
				break
			var hit := player.move_and_collide(to.normalized() * WALK_STEP)
			if hit != null:
				return hit.get_collider()
	return null


## Put the body at `at` and ask the room's own Area2D whether it is inside.
func _is_inside(player: CharacterBody2D, at: Vector2, room: Node) -> bool:
	player.global_position = at
	# Area overlaps are settled by the physics step, not at the moment of the move.
	await get_tree().physics_frame
	await get_tree().physics_frame
	return (room as Area2D).overlaps_body(player)
