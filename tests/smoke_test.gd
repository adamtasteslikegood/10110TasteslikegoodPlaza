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
	_check_scene_tree()
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
	# The main scene is what `godot .` actually runs; loading it here catches a
	# broken instance or a renamed node path without needing a display.
	var main: PackedScene = load("res://scenes/main.tscn")
	if main == null:
		_fail("res://scenes/main.tscn failed to load")
		return
	var instance := main.instantiate()
	for path in ["Office", "Player", "HUD"]:
		if not instance.has_node(path):
			_fail("main.tscn is missing node '%s'" % path)
	if not instance.has_node("Office/SystemsArchitect"):
		_fail("office.tscn is missing the SB-05 NPC")
	instance.queue_free()


func _check_unlock_gate() -> void:
	if not GameState.is_unlocked("server-room"):
		_fail("server-room should be unlocked on Day 1 (SB-04 is free exploration)")
	if GameState.is_unlocked("engineering"):
		_fail("engineering should NOT be unlocked yet — the gate is not gating")
