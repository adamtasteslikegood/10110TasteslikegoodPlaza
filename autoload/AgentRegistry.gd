extends Node

## Loads the generated agent directory and hands it out by id.
##
## `data/agents.json` is generated from the claude-code-tresor submodule by
## scripts/generate_agents_json.py and is never hand-edited (D-016, D-024). This
## script is read-only over that file: if an agent looks wrong, fix the generator
## or the submodule, not the JSON and not here.

const DATA_PATH := "res://data/agents.json"

var _agents: Dictionary = {}
var _loaded := false


func _ready() -> void:
	_load()


func _load() -> void:
	if not FileAccess.file_exists(DATA_PATH):
		push_error(
			"AgentRegistry: %s is missing. Run `python3 scripts/generate_agents_json.py`."
			% DATA_PATH
		)
		return

	var file := FileAccess.open(DATA_PATH, FileAccess.READ)
	if file == null:
		push_error(
			"AgentRegistry: could not open %s (error %d)." % [DATA_PATH, FileAccess.get_open_error()]
		)
		return

	var text := file.get_as_text()
	file.close()

	var parsed: Variant = JSON.parse_string(text)
	# parse_string returns null on malformed JSON. Without this branch the registry
	# would come up empty and the office would simply have no NPCs in it -- which
	# reads as a content problem rather than a broken build.
	if parsed == null:
		push_error("AgentRegistry: %s is not valid JSON." % DATA_PATH)
		return
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error(
			"AgentRegistry: expected %s to hold an object keyed by agent id, got %s."
			% [DATA_PATH, type_string(typeof(parsed))]
		)
		return

	_agents = parsed
	_loaded = true
	print("AgentRegistry: loaded %d agents from %s" % [_agents.size(), DATA_PATH])


## The agent record for `id`, or an empty Dictionary if there is no such agent.
func get_agent(id: String) -> Dictionary:
	return _agents.get(id, {})


func has_agent(id: String) -> bool:
	return _agents.has(id)


## Every agent record whose `dept` matches, sorted by id for a stable order.
func agents_in_dept(dept: String) -> Array[Dictionary]:
	var result: Array[Dictionary] = []
	for id in _sorted_ids():
		var agent: Dictionary = _agents[id]
		if agent.get("dept", "") == dept:
			result.append(agent)
	return result


func ids_in_dept(dept: String) -> Array[String]:
	var result: Array[String] = []
	for id in _sorted_ids():
		if (_agents[id] as Dictionary).get("dept", "") == dept:
			result.append(id)
	return result


func count() -> int:
	return _agents.size()


func is_loaded() -> bool:
	return _loaded


func _sorted_ids() -> Array:
	var ids := _agents.keys()
	ids.sort()
	return ids
