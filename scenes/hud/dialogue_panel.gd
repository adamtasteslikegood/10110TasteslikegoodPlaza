extends CanvasLayer

## The dialogue panel. Listens to GameEvents and renders whatever agent record it
## is handed -- it never looks an agent up itself and never special-cases one.
##
## D-007 locks the typewriter: reveal the full response character by character in
## the frontend rather than streaming it from the bridge.
##
## M8 integration: player types a question into the LineEdit, BridgeClient sends
## it to the bridge, and the response renders with the same typewriter effect.
##
## D-012: one generic silhouette, tinted per department. No per-agent portraits.

const CHARS_PER_SECOND := 55.0

var _full_text := ""
var _revealed := 0.0
var _current_agent_id := ""
var _waiting := false

@onready var _panel: Panel = $Panel
@onready var _portrait: ColorRect = $Panel/Margin/Rows/Header/Portrait
@onready var _name_label: Label = $Panel/Margin/Rows/Header/Titles/NameLabel
@onready var _role_label: Label = $Panel/Margin/Rows/Header/Titles/RoleLabel
@onready var _body_label: Label = $Panel/Margin/Rows/BodyLabel
@onready var _input: LineEdit = $Panel/Margin/Rows/InputRow/QuestionInput
@onready var _input_row: HBoxContainer = $Panel/Margin/Rows/InputRow
@onready var _status_label: Label = $Panel/Margin/Rows/StatusLabel


func _ready() -> void:
	GameEvents.npc_approached.connect(_on_npc_approached)
	GameEvents.npc_left.connect(_on_npc_left)
	GameEvents.agent_response_received.connect(_on_response)
	GameEvents.agent_query_failed.connect(_on_query_failed)
	_input.text_submitted.connect(_on_question_submitted)
	_panel.hide()


func _process(delta: float) -> void:
	if not _panel.visible:
		return
	if _revealed >= float(_full_text.length()):
		return
	_revealed = minf(_revealed + CHARS_PER_SECOND * delta, float(_full_text.length()))
	_body_label.visible_characters = int(_revealed)


func _on_npc_approached(agent_id: String, agent_data: Dictionary) -> void:
	_current_agent_id = agent_id
	_waiting = false

	if agent_data.is_empty():
		_name_label.text = agent_id
		_role_label.text = "not in the registry"
		_set_body("")
		_portrait.color = Color.WHITE
		_show_input(false)
		_panel.show()
		return

	_name_label.text = agent_data.get("name", agent_id)
	_role_label.text = _subtitle(agent_data)
	_portrait.color = _tint(agent_data.get("color", ""))
	_set_body(agent_data.get("description", ""))
	_show_input(true)
	_panel.show()


func _on_npc_left(_agent_id: String) -> void:
	_current_agent_id = ""
	_waiting = false
	_panel.hide()


func _on_question_submitted(text: String) -> void:
	if text.strip_edges().is_empty():
		return
	if _current_agent_id.is_empty():
		return
	if _waiting:
		return

	_waiting = true
	_input.editable = false
	_status_label.text = "Thinking..."
	_status_label.show()
	_set_body("")
	BridgeClient.send_query(_current_agent_id, text)


func _on_response(agent_id: String, response: String) -> void:
	if agent_id != _current_agent_id:
		return
	_waiting = false
	_input.editable = true
	_input.text = ""
	_status_label.hide()
	_set_body(response)


func _on_query_failed(agent_id: String, error_type: String, message: String) -> void:
	if agent_id != _current_agent_id:
		return
	_waiting = false
	_input.editable = true
	_status_label.text = "Error: %s" % message
	_status_label.show()


func _set_body(text: String) -> void:
	_full_text = text
	_body_label.text = text
	_body_label.visible_characters = 0
	_revealed = 0.0


func _show_input(visible: bool) -> void:
	_input_row.visible = visible
	_status_label.hide()
	if visible:
		_input.text = ""
		_input.editable = true


## "Architecture · engineering", or just "Core" when the two would repeat.
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
