extends CanvasLayer

## The dialogue panel. Listens to GameEvents and renders whatever agent record it
## is handed -- it never looks an agent up itself and never special-cases one.
##
## D-007 locks the typewriter: reveal the full response character by character in
## the frontend rather than streaming it from the bridge. There is no bridge yet,
## so the payload is the agent's own description. That is deliberate -- it means the
## reveal mechanism is working and watchable a full milestone before M8 depends on
## it, instead of being written blind on the day the bridge lands.
##
## D-012: one generic silhouette, tinted per department. No per-agent portraits.

const CHARS_PER_SECOND := 55.0

var _full_text := ""
var _revealed := 0.0

@onready var _panel: Panel = $Panel
@onready var _portrait: ColorRect = $Panel/Margin/Rows/Header/Portrait
@onready var _name_label: Label = $Panel/Margin/Rows/Header/Titles/NameLabel
@onready var _role_label: Label = $Panel/Margin/Rows/Header/Titles/RoleLabel
@onready var _body_label: Label = $Panel/Margin/Rows/BodyLabel


func _ready() -> void:
	GameEvents.npc_approached.connect(_on_npc_approached)
	GameEvents.npc_left.connect(_on_npc_left)
	_panel.hide()


func _process(delta: float) -> void:
	if not _panel.visible:
		return
	if _revealed >= float(_full_text.length()):
		return
	_revealed = minf(_revealed + CHARS_PER_SECOND * delta, float(_full_text.length()))
	_body_label.visible_characters = int(_revealed)


func _on_npc_approached(agent_id: String, agent_data: Dictionary) -> void:
	if agent_data.is_empty():
		_name_label.text = agent_id
		_role_label.text = "not in the registry"
		_set_body("")
		_portrait.color = Color.WHITE
		_panel.show()
		return

	_name_label.text = agent_data.get("name", agent_id)
	_role_label.text = _subtitle(agent_data)
	_portrait.color = _tint(agent_data.get("color", ""))
	_set_body(agent_data.get("description", ""))
	_panel.show()


func _on_npc_left(_agent_id: String) -> void:
	_panel.hide()


func _set_body(text: String) -> void:
	_full_text = text
	_body_label.text = text
	_body_label.visible_characters = 0
	_revealed = 0.0


## "Architecture · engineering", or just "Core" when the two would repeat.
##
## The generator derives `role` from an agent's subcategory and falls back to its
## department when there isn't one. All eight Core agents have no subcategory, so
## they arrive as role "Core" in dept "core" and a naive join renders "Core · core".
## That is the data being honest, not wrong -- so it is fixed here, in presentation,
## rather than by teaching the generator to invent a subcategory that upstream
## does not have.
func _subtitle(agent_data: Dictionary) -> String:
	var role: String = agent_data.get("role", "")
	var dept: String = agent_data.get("dept", "")
	if role.is_empty():
		return dept
	if dept.is_empty() or role.to_lower() == dept.to_lower():
		return role
	return "%s · %s" % [role, dept]


func _tint(hex: String) -> Color:
	if hex.is_empty() or not Color.html_is_valid(hex):
		return Color.WHITE
	return Color.html(hex)
