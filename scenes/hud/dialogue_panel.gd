extends CanvasLayer

## Display snapshots are authoritative; only the selected agent's new reply
## animates. Nothing here owns model context or request lifecycle.
const CHARS_PER_SECOND := 55.0
const Geometry := preload("res://scenes/hud/dialogue_geometry.gd")
const FailureDisplay := preload("res://scenes/hud/failure_display.gd")
const MINIMUM := Vector2(480, 260)
const GRIP := 8.0

var _full_text := ""
var _revealed := 0.0
var _reveal_end := 0
var _current_agent_id := ""
var _agent_data: Dictionary = {}
var _rendered_messages: Array = []
var _rendered_omitted := 0
var _message_spans: Array[Dictionary] = []
# Only known registry agents enter this session-only, bounded view index.
var _view_anchors: Dictionary = {}
var _waiting := false
var _domain_id := ""
# Local binding may change before the outgoing surface saves its rendered view.
var _rendered_domain_id := ""
var _kind := ""
var _setup_draft := ""
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
	GameEvents.character_changed.connect(_character_changed)
	GameEvents.domain_changed.connect(_domain_changed)
	GameEvents.workspace_changed.connect(_workspace_changed)
	GameEvents.domain_surface_changing.connect(_surface_changing)
	GameEvents.domain_surface_changed.connect(_surface_changed)
	_action("Prepare").pressed.connect(func(): BridgeClient.project_setup(_current_agent_id, _question_input.text if not _question_input.text.strip_edges().is_empty() else "Prepare the configured project"))
	_action("Start").pressed.connect(func(): BridgeClient.activate_domain(_domain_id))
	_action("Send").pressed.connect(func(): _on_question_submitted(_question_input.text))
	_action("Stop").pressed.connect(func(): BridgeClient.deactivate_domain(_domain_id))
	_action("Status").pressed.connect(func(): BridgeClient.agent_status(_current_agent_id))
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
		if _kind == "working": BridgeClient.surface.close("dialogue")
	elif event.is_action_pressed("chat_page_up", true, true):
		_page(-1)
	elif event.is_action_pressed("chat_page_down", true, true):
		_page(1)
	elif owner == _body_label and event.is_action_pressed("chat_oldest", false, true):
		_manual_scroll(0)
	elif owner == _body_label and event.is_action_pressed("chat_newest", false, true):
		_manual_scroll(_bottom())
	elif event.is_action_pressed("chat_focus_next", false, true) or event.is_action_pressed("chat_focus_previous", false, true):
		var controls: Array[Control] = [_body_label, _question_input]
		for name in ["Prepare", "Start", "Send", "Stop", "Status"]: controls.append(_action(name))
		var enabled: Array[Control] = []
		for control in controls:
			if control.is_visible_in_tree() and control.focus_mode == Control.FOCUS_ALL: enabled.append(control)
		if not enabled.is_empty(): enabled[posmod(enabled.find(owner) + (-1 if event.shift_pressed else 1), enabled.size())].grab_focus()
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
	_domain_id = ""
	_kind = ""
	_setup_draft = ""
	_character_changed(agent_id, "cached", "")
	BridgeClient.agent_status(agent_id)


func _on_npc_left(agent_id: String) -> void:
	if agent_id != _current_agent_id:
		return
	_save_view()
	BridgeClient.surface.close("dialogue")
	_release_focus()
	_current_agent_id = ""
	_drag_edges = 0
	_panel.hide()

func _on_conversation_changed(agent_id: String, reason: String, request_id: String) -> void:
	if agent_id != _current_agent_id or reason == "view" or _kind != "extra":
		return
	var snapshot := BridgeClient.conversation_snapshot(agent_id)
	if reason == "draft" and snapshot.messages == _rendered_messages and snapshot.omitted == _rendered_omitted:
		return
	var reveal_id := request_id if reason == "reply" and _panel.visible else ""
	_render(snapshot, reveal_id, _body_label.get_v_scroll_bar().value, reason == "draft", _reading_anchor())
	_update_actions()

func _render(snapshot: Dictionary, reveal_id: String, scroll: float, preserve_reveal: bool = false, anchor: Dictionary = {}) -> void:
	if _kind != "working": _rendered_domain_id = ""
	var previous_span := _assistant_span
	var previous_progress := _revealed - float(previous_span.start)
	var was_revealing := _revealed < _reveal_end
	_scroll_guard = true
	_rendered_messages = snapshot.get("messages", [])
	_rendered_omitted = snapshot.get("omitted", 0)
	_message_spans.clear()
	_full_text = ""
	_assistant_span = {"start": 0, "length": 0, "request_id": ""}
	_waiting = not snapshot.get("pending", {}).is_empty()
	_input_row.visible = not snapshot.is_empty()
	# Reassigning identical LineEdit text destroys native selection/caret state.
	if _question_input.text != snapshot.get("draft", ""):
		_question_input.text = snapshot.get("draft", "")
	var composer_had_focus := _question_input.has_focus()
	_question_input.editable = (not _waiting or _kind == "working") and snapshot.get("connected", false)
	_question_input.focus_mode = Control.FOCUS_ALL if _question_input.editable else Control.FOCUS_NONE
	if not _question_input.editable and composer_had_focus:
		_body_label.grab_focus()
	_status_label.text = "Thinking..." if _waiting else ("" if snapshot.get("connected", false) else "Disconnected — history is read-only")
	_status_label.visible = not _status_label.text.is_empty()
	if snapshot.get("omitted", 0) > 0:
		_full_text += "[Older messages omitted]\n\n"
	var last_generation := ""
	for message in snapshot.get("messages", []):
		var message_start := _full_text.length()
		if str(message.generation) != last_generation:
			last_generation = str(message.generation)
			var archived: bool = not snapshot.connected or last_generation != str(snapshot.generation)
			var boundary := "Archived context" if archived else ("New context restarted" if (_kind == "extra" and int(last_generation) > 1) else "Context")
			_full_text += "[%s %s]\n" % [boundary, last_generation]
		var role: String = {"user": "You", "assistant": "Assistant", "error": "Error", "draft": "Archived draft"}.get(message.role, message.role)
		_full_text += "%s%s (%s):\n" % [role, " · " + str(message.agent_id) if message.has("agent_id") else "", message.status]
		if message.role == "assistant":
			_assistant_span = {"start": _full_text.length(), "length": message.content.length(), "request_id": message.request_id}
		_full_text += message.content + "\n\n"
		_message_spans.append({"request_id": message.request_id, "generation": message.generation, "role": message.role, "start": message_start, "length": _full_text.length() - message_start})
	if snapshot.get("connected", false) and snapshot.get("generation", 0) is int and snapshot.get("generation", 0) > 1 and last_generation != str(snapshot.generation):
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
	elif preserve_reveal and was_revealing and _assistant_span.request_id == previous_span.request_id:
		_revealed = _assistant_span.start + previous_progress
		_reveal_end = _assistant_span.start + _assistant_span.length
		_body_label.visible_characters = int(_revealed)
	_settle_scroll(scroll, anchor)

func _on_draft_changed(text: String) -> void:
	if _current_agent_id.is_empty():
		return
	if _kind == "working":
		if not _domain_id.is_empty(): BridgeClient.set_domain_draft(_domain_id, text)
		else: _setup_draft = text
		return
	if _kind != "extra": return
	if not BridgeClient.set_draft(_current_agent_id, text):
		_question_input.text = BridgeClient.conversation_snapshot(_current_agent_id).get("draft", "")

func _on_question_submitted(text: String) -> void:
	if text.strip_edges().is_empty() or _current_agent_id.is_empty() or _waiting:
		return
	if _action("Send").disabled: return
	if _kind == "working": BridgeClient.send_domain_query(_domain_id, _current_agent_id, text)
	elif _kind == "extra": BridgeClient.send_query(_current_agent_id, text)
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
	# A render/layout has not settled yet: its temporary pixel range must not
	# overwrite the saved view when switching agents in consecutive frames.
	if _scroll_guard or not AgentRegistry.has_agent(_current_agent_id):
		return
	if not _rendered_domain_id.is_empty():
		if not _panel.visible or BridgeClient.surface.owner != "dialogue" or BridgeClient.surface.domain_id != _rendered_domain_id: return
		BridgeClient.domains.save_view(_rendered_domain_id, _body_label.get_v_scroll_bar().value, _follow, _reading_anchor())
		return
	_view_anchors[_current_agent_id] = _reading_anchor()
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
	var anchor := {"character": low, "offset": value - _body_label.get_line_offset(_body_label.get_character_line(low))}
	for span in _message_spans:
		if low >= span.start and low < span.start + span.length:
			anchor.merge({"request_id": span.request_id, "generation": span.generation, "role": span.role, "relative": low - span.start})
			break
	return anchor

func _resolve_anchor(anchor: Dictionary) -> Dictionary:
	if anchor.has("request_id"):
		for span in _message_spans:
			if span.request_id == anchor.request_id and span.generation == anchor.generation and span.role == anchor.role:
				return {"character": span.start + mini(anchor.relative, span.length - 1), "offset": anchor.offset}
		# The anchor's exchange was evicted. Show the omission notice/oldest
		# retained content instead of guessing a position in a different reply.
		return {"character": 0, "offset": 0.0}
	return {"character": mini(anchor.character, maxi(0, _body_label.text.length() - 1)), "offset": anchor.offset}

func _settle_scroll(value: float, anchor: Dictionary = {}) -> void:
	_layout_anchor = anchor
	_layout_revision += 1
	var revision := _layout_revision
	_scroll_guard = true
	await get_tree().process_frame
	await get_tree().process_frame
	if revision != _layout_revision:
		return
	if not anchor.is_empty() and not _body_label.text.is_empty():
		var resolved := _resolve_anchor(anchor)
		value = _body_label.get_line_offset(_body_label.get_character_line(resolved.character)) + resolved.offset
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
	var tiny := rect.size.y < 160
	_portrait.visible = not compact
	# Identity remains visible even below the normal panel minimum. Reduce
	# decoration, type sizes and spacing together; never hide the header.
	$Panel/Margin/Rows/Header.show()
	_name_label.add_theme_font_size_override("font_size", 14 if tiny else 22)
	_role_label.add_theme_font_size_override("font_size", 10 if tiny else 14)
	$Panel/Margin/Rows/Header/Titles.add_theme_constant_override("separation", 0 if tiny else 4)
	_body_label.add_theme_font_size_override("normal_font_size", 12 if tiny else 16)
	_body_label.custom_minimum_size.y = 12
	_question_input.add_theme_font_size_override("font_size", 12 if tiny else 14)
	_status_label.add_theme_font_size_override("font_size", 10 if tiny else 13)
	_status_label.max_lines_visible = 1 if tiny else 2
	var margin := 2 if tiny else (6 if compact else 16)
	for side in ["left", "top", "right", "bottom"]:
		$Panel/Margin.add_theme_constant_override("margin_" + side, margin)
	$Panel/Margin/Rows.add_theme_constant_override("separation", 2 if tiny else (4 if compact else 10))
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


func _action(name: String) -> Button:
	return get_node("Panel/Margin/Rows/Actions/" + name)

func _enable(button: Button, enabled: bool) -> void:
	button.disabled = not enabled
	button.focus_mode = Control.FOCUS_ALL if enabled else Control.FOCUS_NONE
	if not enabled and button.has_focus(): button.release_focus()

func _character_changed(agent: String, _reason: String, _request: String) -> void:
	if agent != _current_agent_id: return
	var data := BridgeClient.character_snapshot(agent)
	var previous_kind := _kind
	_kind = data.get("execution_kind", "")
	var domain: String = data.get("domain_id", "") if data.get("domain_id") != null else ""
	var newly_bound := domain != _domain_id
	_domain_id = domain
	if newly_bound and _panel.visible and not domain.is_empty():
		BridgeClient.surface.open("dialogue", domain, agent)
		_panel.show()
	if _kind == "extra":
		if previous_kind == "extra" and _reason != "cached":
			_update_actions()
			return
		BridgeClient.surface.close("dialogue")
		var snapshot := BridgeClient.conversation_snapshot(agent)
		_follow = snapshot.get("follow", true)
		_render(snapshot, "", float(snapshot.get("scroll", 0)), false, _view_anchors.get(agent, {}))
	elif _kind == "working":
		_render_domain("", newly_bound)
	else:
		_rendered_domain_id = ""
		_body_label.text = data.get("error", "Checking character status…")
		_question_input.editable = false
		_question_input.focus_mode = Control.FOCUS_NONE
	_update_actions()

func _update_actions() -> void:
	var data := BridgeClient.character_snapshot(_current_agent_id)
	var capabilities: Dictionary = data.get("capabilities", {})
	var snapshot := BridgeClient.domain_snapshot(_domain_id) if not _domain_id.is_empty() else {}
	var connected := BridgeClient.is_bridge_connected()
	var pending: Dictionary = snapshot.get("pending_control", {})
	var state: String = snapshot.get("state", "inactive")
	var working := _kind == "working"
	$Panel/Margin/Rows/Actions.visible = _kind != "extra"
	for name in ["Prepare", "Start", "Stop"]: _action(name).visible = working
	_action("Prepare").text = "Prepare this project" if capabilities.get("can_prepare_project", false) else "Project help"
	_enable(_action("Prepare"), connected and working and data.get("pending", "").is_empty() and (capabilities.get("can_prepare_project", false) or BridgeClient.workspace_snapshot().get("stage") in ["unconfigured", "needs_architect", "failed"]))
	_enable(_action("Start"), connected and working and pending.is_empty() and state == "inactive" and capabilities.get("can_start", false))
	var run: bool = connected and pending.is_empty() and state in ["active", "background"] and snapshot.get("execution_state") == "idle" and snapshot.get("pending_query", {}).is_empty() and not snapshot.get("uncertain", false)
	_enable(_action("Send"), run if working else (connected and _kind == "extra" and not _waiting))
	_enable(_action("Stop"), connected and working and not snapshot.get("domain_session_id", "").is_empty() and (pending.is_empty() or pending.get("type") == "activate_domain") and (state != "inactive" or snapshot.get("uncertain", false)))
	_enable(_action("Status"), connected and data.get("pending", "").is_empty())

func _render_domain(reveal_id: String = "", restore: bool = false) -> void:
	if _domain_id.is_empty(): return
	var snapshot := BridgeClient.domain_snapshot(_domain_id)
	var view: Dictionary = snapshot.get("view", {})
	if restore: _follow = view.get("follow", true)
	var messages := []
	var reveal_failed := false
	for result in snapshot.get("results", []):
		messages.append({"role": "user", "content": result.task, "status": "submitted", "generation": result.domain_session_id, "request_id": result.request_id, "agent_id": result.agent_id})
		messages.append({"role": "assistant", "content": result.output, "status": "%s · memory %s" % [result.status, "saved" if result.get("memory", {}).get("saved", false) else "unsaved"], "generation": result.domain_session_id, "request_id": result.request_id, "agent_id": result.agent_id})
		var cause := FailureDisplay.cause(result)
		if not cause.is_empty(): messages.append({"role": "error", "content": cause, "status": "cause", "generation": result.domain_session_id, "request_id": result.request_id, "agent_id": result.agent_id})
		# A failed terminal's recovery text follows its partial assistant span.
		# Reveal the whole failure immediately so typewriter clipping cannot hide
		# that cause forever, especially when the partial answer is empty.
		if result.request_id == reveal_id and result.status != "success":
			reveal_id = ""
			reveal_failed = true
	var pending: Dictionary = snapshot.get("pending_query", {})
	if not pending.is_empty(): messages.append({"role": "user", "content": pending.task, "status": "pending", "generation": snapshot.domain_session_id, "request_id": pending.request_id, "agent_id": pending.agent_id})
	var error: Dictionary = snapshot.get("error", {})
	if not error.is_empty(): messages.append({"role": "error", "content": FailureDisplay.notice(error), "status": "notice", "generation": snapshot.domain_session_id, "request_id": "notice"})
	var data := BridgeClient.character_snapshot(_current_agent_id)
	for key in ["setup_output", "error"]:
		if not data.get(key, "").is_empty(): messages.append({"role": "setup" if key == "setup_output" else "error", "content": data[key], "status": "notice", "generation": snapshot.domain_session_id, "request_id": key})
	_rendered_domain_id = _domain_id
	var presentation := {"messages": messages, "omitted": snapshot.get("omitted_count", 0), "pending": pending, "draft": snapshot.draft, "connected": BridgeClient.is_bridge_connected(), "generation": snapshot.domain_session_id}
	_render(presentation, reveal_id, view.get("scroll", 0.0) if restore else _body_label.get_v_scroll_bar().value, not reveal_failed, view.get("anchor", {}) if restore else _reading_anchor())
	_status_label.text = "%s · %s / %s · Project %s%s" % [_domain_id, snapshot.state, snapshot.execution_state, BridgeClient.workspace_snapshot().get("stage", "unknown"), " · Stop to release workspace" if not snapshot.domain_session_id.is_empty() and snapshot.state != "inactive" else ""]
	if snapshot.get("uncertain", false): _status_label.text += " · Unknown outcome — Refresh status"
	if not BridgeClient.is_bridge_connected(): _status_label.text += " · Disconnected"
	_status_label.show()
	_update_actions()
	if _panel.visible and BridgeClient.surface.owner == "dialogue":
		for result in snapshot.results:
			if result.domain_session_id == snapshot.domain_session_id and BridgeClient.DomainState.compare(result.output_id, snapshot.received_cursor) <= 0 and BridgeClient.DomainState.compare(result.output_id, snapshot.consumed_cursor) > 0:
				BridgeClient.mark_domain_read(_domain_id, result.output_id)

func _domain_changed(domain: String, reason: String, request: String) -> void:
	if domain == _domain_id and _kind == "working":
		_render_domain(request if reason == "domain_result" and _panel.visible else "")
		if reason == "domain_error":
			# A new command/startup/preflight notice follows the previous answer.
			# Settle that older reveal so its clipping limit cannot hide the cause.
			_reveal_end = _full_text.length()
			_revealed = _reveal_end
			_body_label.visible_characters = -1

func _workspace_changed(_reason: String, _request: String) -> void:
	if _current_agent_id.is_empty(): return
	if BridgeClient.character_snapshot(_current_agent_id).is_empty():
		_domain_id = ""
		_kind = ""
		BridgeClient.agent_status(_current_agent_id)
	_update_actions()

func _surface_changing() -> void:
	if BridgeClient.surface.owner == "dialogue": _save_view()

func _surface_changed() -> void:
	if _kind != "working": return
	if BridgeClient.surface.owner != "dialogue":
		_release_focus()
		_panel.hide()
