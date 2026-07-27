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

## D-024 fixes the count: 133 source files, three colliding slugs curated down to 132.
const EXPECTED_AGENT_COUNT := 132

## Core department, gold (D-017). SB-05 and SB-06 put both of these in the server room.
const CORE_DEPT := "core"
const CORE_COLOR := "#FFD700"

var _failures: Array[String] = []


func _ready() -> void:
	_check_autoloads()
	_check_registry()
	_check_core_agents()
	await _check_scene_tree()
	_check_unlock_gate()

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
	for name in ["AgentRegistry", "GameEvents", "GameState"]:
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

	instance.queue_free()


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
	# 3 floors + 12 walls + 1 door built in _ready(), plus the 2 NPCs already in
	# the .tscn. A low count means wall generation errored partway.
	var built := office.get_child_count()
	if built < 16:
		_fail("Office has %d children, expected >= 16 — geometry build did not finish" % built)


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

	var body_label: Label = hud.get_node_or_null("Panel/Margin/Rows/BodyLabel")
	if body_label == null:
		_fail("dialogue panel: BodyLabel path does not resolve")
	elif body_label.text != agent.get("description", ""):
		_fail("dialogue panel body text was not populated from the agent record")
	elif body_label.visible_characters != 0:
		# D-007: the reveal starts at zero and is driven by _process.
		_fail("typewriter did not reset — visible_characters is %d, expected 0" % body_label.visible_characters)

	GameEvents.npc_left.emit("systems-architect")
	if panel.visible:
		_fail("panel did not close on GameEvents.npc_left")


func _check_unlock_gate() -> void:
	if not GameState.is_unlocked("server-room"):
		_fail("server-room should be unlocked on Day 1 (SB-04 is free exploration)")
	if GameState.is_unlocked("engineering"):
		_fail("engineering should NOT be unlocked yet — the gate is not gating")
