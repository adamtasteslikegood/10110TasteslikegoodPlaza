extends CharacterBody2D

## One agent, standing in the office.
##
## Everything shown here comes from AgentRegistry at runtime -- the scene stores an
## `agent_id` and nothing else. Typing a name or a colour into a .tscn would fork
## the truth away from the generated directory, which is exactly what D-016 forbids.
##
## D-011: one generic body, tinted per department. There is no per-agent art and
## there is not meant to be until well after v1.0.

@export var agent_id: String = "systems-architect"

var agent_data: Dictionary = {}

@onready var _body: Polygon2D = $Body
@onready var _name_tag: Label = $NameTag
@onready var _proximity: Area2D = $Proximity


func _ready() -> void:
	_proximity.body_entered.connect(_on_body_entered)
	_proximity.body_exited.connect(_on_body_exited)

	agent_data = AgentRegistry.get_agent(agent_id)
	if agent_data.is_empty():
		# Loud, and still standing there: an unnamed grey figure is a far better
		# bug report than an NPC that silently fails to spawn.
		push_warning("AgentNPC: '%s' is not in the agent registry." % agent_id)
		_name_tag.text = "%s (missing)" % agent_id
		return

	_name_tag.text = agent_data.get("name", agent_id)
	_body.color = _dept_color()


func _dept_color() -> Color:
	var hex: String = agent_data.get("color", "")
	# The colour is the department taxonomy (D-017), carried through the generator.
	# An unparseable value means upstream drift, not a mistake in this scene.
	if hex.is_empty() or not Color.html_is_valid(hex):
		push_warning("AgentNPC '%s': unusable colour %s" % [agent_id, hex])
		return Color.WHITE
	return Color.html(hex)


func _on_body_entered(body: Node2D) -> void:
	if body.is_in_group("player"):
		GameEvents.npc_approached.emit(agent_id, agent_data)


func _on_body_exited(body: Node2D) -> void:
	if body.is_in_group("player"):
		GameEvents.npc_left.emit(agent_id)
