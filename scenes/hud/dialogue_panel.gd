extends CanvasLayer

## Display snapshots are authoritative; only the selected agent's new reply
## animates. Nothing here owns model context or request lifecycle.
const CHARS_PER_SECOND := 55.0
const Geometry := preload("res://scenes/hud/dialogue_geometry.gd")
const MINIMUM := Vector2(480, 260)
const GRIP := 8.0

var _full_text := ""
var _revealed := 0.0
var _reveal_end := 0
var _current_agent_id := ""
var _agent_data: Dictionary = {}
var _waiting := false
var _assistant_span: Dictionary = {"start": 0, "length": 0, "request_id": ""}
var _follow := true
var _scroll_guard := false
var _layout_revision := 0
var _layout_anchor: Dictionary = {}
var _desired_rect := Rect2()
var _drag_edges := 0
var _drag_origin := Vector2.ZERO
var _drag_rect := Rect2()

@onready var _panel: Panel = $Panel
@onready var _portrait: ColorRect = $Panel/Margin/Rows/Header/Portrait
@onready var _name_label: Label = $Panel/Margin/Rows/Header/Titles/NameLabel
@onready var _role_label: Label = $Panel/Margin/Rows/Header/Titles/RoleLabel
@onready var _body_label: RichTextLabel = $Panel/Margin/Rows/BodyLabel
@onready var _question_input: LineEdit = $Panel/Margin/Rows/InputRow/QuestionInput
@onready var _input_row: HBoxContainer = $Panel/Margin/Rows/InputRow
@onready var _status_label: Label = $Panel/Margin/Rows/StatusLabel

func _ready() -> void:
	GameEvents.npc_approached.connect(_on_npc_approached)
	GameEvents.npc_left.connect(_on_npc_left)
	GameEvents.conversation_changed.connect(_on_conversation_changed)
	GameEvents.agent_query_failed.connect(_on_query_failed)
	_question_input.text_submitted.connect(_on_question_submitted)
	_question_input.text_changed.connect(_on_draft_changed)
	_body_label.get_v_scroll_bar().value_changed.connect(_on_scroll_changed)
	get_viewport().size_changed.connect(_on_viewport_changed)
	var viewport := get_viewport().get_visible_rect().size
	_desired_rect = Rect2(Vector2(24, maxf(0, viewport.y - 344)), Vector2(maxf(480, viewport.x - 48), 320))
	_apply_geometry()
	_panel.hide()

## Offsets are Unicode character positions in the actual plain-text BodyLabel.
## Callers must read that label, not reuse a transport payload or whole history.
func current_assistant_span() -> Dictionary:
	return _assistant_span.duplicate()

func _input(event: InputEvent) -> void:
	if not _panel.visible:
		return
	if _resize_input(event):
		get_viewport().set_input_as_handled()
		return
	if not event is InputEventKey or not event.pressed:
		return
	var owner := get_viewport().gui_get_focus_owner()
	if owner == null or not _panel.is_ancestor_of(owner):
		return
	if event.is_action_pressed("chat_release_focus", false, true):
		owner.release_focus()
	elif event.is_action_pressed("chat_page_up", true, true):
		_page(-1)
	elif event.is_action_pressed("chat_page_down", true, true):
		_page(1)
	elif owner == _body_label and event.is_action_pressed("chat_oldest", false, true):
		_manual_scroll(0)
	elif owner == _body_label and event.is_action_pressed("chat_newest", false, true):
		_manual_scroll(_bottom())
	elif event.is_action_pressed("chat_focus_next", false, true) or event.is_action_pressed("chat_focus_previous", false, true):
		# Two enabled controls; this explicit cycle also skips a pending composer.
		if owner == _body_label and _question_input.editable and _input_row.visible:
			_question_input.grab_focus()
		else:
			_body_label.grab_focus()
	else:
		# Enter stays on LineEdit.text_submitted: exactly one submission path.
		return
	get_viewport().set_input_as_handled()

func _process(delta: float) -> void:
	if not _panel.visible or _revealed >= _reveal_end:
		return
	_revealed = minf(_revealed + CHARS_PER_SECOND * delta, _reveal_end)
	_body_label.visible_characters = int(_revealed)
	if _follow:
		_set_scroll(_bottom())

func _on_npc_approached(agent_id: String, agent_data: Dictionary) -> void:
	_save_view()
	_current_agent_id = agent_id
	_agent_data = agent_data
	_name_label.text = agent_data.get("name", agent_id)
	_role_label.text = _subtitle(agent_data) if not agent_data.is_empty() else "not in the registry"
	_portrait.color = _tint(agent_data.get("color", ""))
	_panel.show()
	var snapshot := BridgeClient.conversation_snapshot(agent_id)
	_follow = snapshot.get("follow", true)
	_render(snapshot, "", float(snapshot.get("scroll", 0)))

func _on_npc_left(agent_id: String) -> void:
	if agent_id != _current_agent_id:
		return
	_save_view()
	_release_focus()
	_current_agent_id = ""
	_drag_edges = 0
	_panel.hide()

func _on_conversation_changed(agent_id: String, reason: String, request_id: String) -> void:
	if agent_id != _current_agent_id or reason in ["draft", "view"]:
		return
	var reveal_id := request_id if reason == "reply" and _panel.visible else ""
	_render(BridgeClient.conversation_snapshot(agent_id), reveal_id, _body_label.get_v_scroll_bar().value)

func _render(snapshot: Dictionary, reveal_id: String, scroll: float) -> void:
	_scroll_guard = true
	_full_text = ""
	_assistant_span = {"start": 0, "length": 0, "request_id": ""}
	_waiting = not snapshot.get("pending", {}).is_empty()
	_input_row.visible = not snapshot.is_empty()
	_question_input.text = snapshot.get("draft", "")
	var composer_had_focus := _question_input.has_focus()
	_question_input.editable = not _waiting and snapshot.get("connected", false)
	_question_input.focus_mode = Control.FOCUS_ALL if _question_input.editable else Control.FOCUS_NONE
	if not _question_input.editable and composer_had_focus:
		_body_label.grab_focus()
	_status_label.text = "Thinking..." if _waiting else ("" if snapshot.get("connected", false) else "Disconnected — history is read-only")
	_status_label.visible = not _status_label.text.is_empty()
	if snapshot.get("omitted", 0) > 0:
		_full_text += "[Older messages omitted]\n\n"
	var last_generation := -1
	for message in snapshot.get("messages", []):
		if message.generation != last_generation:
			last_generation = message.generation
			var archived: bool = not snapshot.connected or last_generation != snapshot.generation
			var boundary := "Archived context" if archived else ("New context restarted" if last_generation > 1 else "Context")
			_full_text += "[%s %d]\n" % [boundary, last_generation]
		var role: String = {"user": "You", "assistant": "Assistant", "error": "Error", "draft": "Archived draft"}.get(message.role, message.role)
		_full_text += "%s (%s):\n" % [role, message.status]
		if message.role == "assistant":
			_assistant_span = {"start": _full_text.length(), "length": message.content.length(), "request_id": message.request_id}
		_full_text += message.content + "\n\n"
	if snapshot.get("connected", false) and snapshot.get("generation", 0) > 1 and last_generation != snapshot.generation:
		_full_text += "[New context restarted — prior history is display only]\n"
	if _full_text.is_empty():
		_full_text = _agent_data.get("description", "")
	_body_label.text = _full_text
	_reveal_end = _full_text.length()
	_revealed = _reveal_end
	_body_label.visible_characters = -1
	if not reveal_id.is_empty() and _assistant_span.request_id == reveal_id:
		_revealed = _assistant_span.start
		_reveal_end = _assistant_span.start + _assistant_span.length
		_body_label.visible_characters = int(_revealed)
	_settle_scroll(scroll)

func _on_draft_changed(text: String) -> void:
	if _current_agent_id.is_empty():
		return
	if not BridgeClient.set_draft(_current_agent_id, text):
		_question_input.text = BridgeClient.conversation_snapshot(_current_agent_id).get("draft", "")

func _on_question_submitted(text: String) -> void:
	if text.strip_edges().is_empty() or _current_agent_id.is_empty() or _waiting:
		return
	BridgeClient.send_query(_current_agent_id, text)
	# Notifications already render admitted/synchronously failed requests.
	# Never infer pending from the returned ID: only the store owns that state.

func _on_query_failed(agent_id: String, _error_type: String, message: String) -> void:
	if agent_id != _current_agent_id:
		return
	# The legacy signal carries the original error, possibly larger than the
	# bounded snapshot. Keep this transient status excerpt bounded too.
	_status_label.text = "Error: " + message.left(220) + (" [truncated]" if message.length() > 220 else "")
	_status_label.show()

func _save_view() -> void:
	if not _current_agent_id.is_empty():
		BridgeClient.save_conversation_view(_current_agent_id, _body_label.get_v_scroll_bar().value, _follow)

func _bottom() -> float:
	var bar := _body_label.get_v_scroll_bar()
	var end := bar.max_value
	if _body_label.visible_characters >= 0 and not _body_label.text.is_empty():
		# RichTextLabel lays out the entire reply before revealing it. Following
		# its raw maximum would show blank future lines until the reveal caught up.
		var character := maxi(0, _body_label.visible_characters - 1)
		var line := _body_label.get_character_line(character)
		end = minf(end, _body_label.get_line_offset(line) + _body_label.get_line_height(line))
	return maxf(0, end - bar.page)

func _set_scroll(value: float) -> void:
	var previous := _scroll_guard
	_scroll_guard = true
	_body_label.get_v_scroll_bar().value = value
	_scroll_guard = previous

func _on_scroll_changed(value: float) -> void:
	if _scroll_guard:
		return
	_follow = value >= _bottom() - 2.0
	_save_view()

func _manual_scroll(value: float) -> void:
	_follow = value >= _bottom() - 2.0
	_set_scroll(value)
	_save_view()

func _page(direction: int) -> void:
	var bar := _body_label.get_v_scroll_bar()
	_manual_scroll(clampf(bar.value + direction * maxf(1, bar.page * 0.9), 0, _bottom()))

func _reading_anchor() -> Dictionary:
	if _follow or _body_label.text.is_empty():
		return {}
	# Find the first character on the line at/after the top of the viewport.
	# Character identity survives wrapping; raw scrollbar pixels do not.
	var value := _body_label.get_v_scroll_bar().value
	var low := 0
	var high := _body_label.text.length() - 1
	while low < high:
		var middle := (low + high) / 2
		var offset := _body_label.get_line_offset(_body_label.get_character_line(middle))
		if offset < value:
			low = middle + 1
		else:
			high = middle
	return {"character": low, "offset": value - _body_label.get_line_offset(_body_label.get_character_line(low))}

func _settle_scroll(value: float, anchor: Dictionary = {}) -> void:
	_layout_anchor = anchor
	_layout_revision += 1
	var revision := _layout_revision
	_scroll_guard = true
	await get_tree().process_frame
	await get_tree().process_frame
	if revision != _layout_revision:
		return
	if not anchor.is_empty():
		value = _body_label.get_line_offset(_body_label.get_character_line(anchor.character)) + anchor.offset
	_set_scroll(_bottom() if _follow else value)
	_layout_anchor = {}
	_scroll_guard = false
	_save_view()

func _release_focus() -> void:
	var owner := get_viewport().gui_get_focus_owner()
	if owner != null and _panel.is_ancestor_of(owner):
		owner.release_focus()

func _on_viewport_changed() -> void:
	_apply_geometry()

func _apply_geometry() -> void:
	var anchor := _layout_anchor if not _layout_anchor.is_empty() else _reading_anchor()
	var scroll := _body_label.get_v_scroll_bar().value
	_scroll_guard = true
	var rect := Geometry.clamp_rect(_desired_rect, get_viewport().get_visible_rect().size, MINIMUM)
	_panel.position = rect.position
	_panel.size = rect.size
	var compact := rect.size.x < 600 or rect.size.y < 340
	_portrait.visible = not compact
	$Panel/Margin/Rows/Header.visible = rect.size.y >= 160
	var margin := 6 if compact else 16
	for side in ["left", "top", "right", "bottom"]:
		$Panel/Margin.add_theme_constant_override("margin_" + side, margin)
	$Panel/Margin/Rows.add_theme_constant_override("separation", 4 if compact else 10)
	_settle_scroll(scroll, anchor)

func _edges_at(point: Vector2) -> int:
	var rect := _panel.get_global_rect()
	if not rect.has_point(point):
		return 0
	var edges := 0
	if point.x <= rect.position.x + GRIP: edges |= Geometry.LEFT
	if point.y <= rect.position.y + GRIP: edges |= Geometry.TOP
	if point.x >= rect.end.x - GRIP: edges |= Geometry.RIGHT
	if point.y >= rect.end.y - GRIP: edges |= Geometry.BOTTOM
	return edges

func _resize_input(event: InputEvent) -> bool:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if not event.pressed:
			var was_dragging := _drag_edges != 0
			_drag_edges = 0
			return was_dragging
		_drag_edges = _edges_at(event.position)
		if _drag_edges != 0:
			_drag_origin = event.position
			_drag_rect = _panel.get_global_rect()
			return true
	if event is InputEventMouseMotion:
		if _drag_edges != 0:
			_desired_rect = Geometry.resize_rect(_drag_rect, event.position - _drag_origin, _drag_edges, get_viewport().get_visible_rect().size, MINIMUM)
			_apply_geometry()
			return true
		var edges := _edges_at(event.position)
		if edges in [3, 12]: _panel.mouse_default_cursor_shape = Control.CURSOR_FDIAGSIZE
		elif edges in [6, 9]: _panel.mouse_default_cursor_shape = Control.CURSOR_BDIAGSIZE
		elif edges & 5: _panel.mouse_default_cursor_shape = Control.CURSOR_HSIZE
		elif edges & 10: _panel.mouse_default_cursor_shape = Control.CURSOR_VSIZE
		else: _panel.mouse_default_cursor_shape = Control.CURSOR_ARROW
	return false


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
