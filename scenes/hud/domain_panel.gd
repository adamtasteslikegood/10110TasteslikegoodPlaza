extends CanvasLayer

## View ownership only. BridgeClient owns admission, drafts and execution state.
var nearby_agent_id := ""
var anchor_agent_id := ""
var selected_domain_id := ""
var remote := false
var _return_to_anchor := false
var _agents: Dictionary = {}
var _domains: Array[String] = []
var _project_id := ""
var _view_guard := false
var _view_revision := 0
var _result_spans: Array[Dictionary] = []

@onready var _panel: PanelContainer = $Panel
@onready var _task_input: LineEdit = $Panel/Scroll/Rows/TaskInput
@onready var _results: RichTextLabel = $Panel/Scroll/Rows/ResultsLabel
@onready var _status: Label = $Panel/Scroll/Rows/StatusLabel
@onready var _workspace: Label = $Panel/Scroll/Rows/WorkspaceLabel
@onready var _global: Label = $Global/StatusLabel
@onready var _opener: Button = $Global/Toolbar/NearbyDomainButton
@onready var _select: OptionButton = $Global/Toolbar/DomainSelect
@onready var _global_refocus: Button = $Global/Toolbar/RefocusButton

func _ready() -> void:
	GameEvents.npc_approached.connect(_approached)
	GameEvents.npc_left.connect(_left)
	GameEvents.domain_changed.connect(_domain_changed)
	GameEvents.workspace_changed.connect(_workspace_changed)
	GameEvents.character_changed.connect(_character_changed)
	GameEvents.domain_surface_changing.connect(_surface_changing)
	GameEvents.domain_surface_changed.connect(_surface_changed)
	_opener.pressed.connect(_open_nearby)
	_global_refocus.pressed.connect(_open_remote)
	$Global/Toolbar/StopButton.pressed.connect(func(): BridgeClient.deactivate_domain(selected_domain_id))
	_select.item_selected.connect(func(index):
		if _panel.visible: _background()
		selected_domain_id = _domains[index]
		anchor_agent_id = ""
		remote = true
		_return_to_anchor = false
		_refresh())
	_action("Start").pressed.connect(func(): BridgeClient.activate_domain(selected_domain_id))
	_action("Run").pressed.connect(_submit.bind(""))
	_action("Refocus").pressed.connect(_refocus)
	_action("Background").pressed.connect(_background)
	_action("Stop").pressed.connect(func(): BridgeClient.deactivate_domain(selected_domain_id))
	_action("Status").pressed.connect(_recover)
	_task_input.text_submitted.connect(_submit)
	_task_input.text_changed.connect(_draft)
	_results.get_v_scroll_bar().value_changed.connect(_save_result_view)
	get_viewport().size_changed.connect(_layout)
	_panel.hide()
	_layout()
	_refresh()

func _action(name: String) -> Button:
	return get_node("Panel/Scroll/Rows/Actions/" + name)

func _remember(domain_id: String) -> void:
	if domain_id in _domains or _domains.size() >= 10: return
	_domains.append(domain_id)
	_select.add_item(domain_id)
	if selected_domain_id.is_empty(): selected_domain_id = domain_id

func _approached(agent_id: String, _data: Dictionary) -> void:
	if not AgentRegistry.has_agent(agent_id): return
	nearby_agent_id = agent_id
	if not remote and _return_to_anchor and anchor_agent_id == agent_id:
		_return_to_anchor = false
		_panel.show()
		_refocus()
	_refresh()

func _left(agent_id: String) -> void:
	if nearby_agent_id == agent_id: nearby_agent_id = ""
	if not remote and anchor_agent_id == agent_id and _panel.visible:
		_background()
	_refresh()

func _open_nearby() -> void:
	var agent := BridgeClient.character_snapshot(nearby_agent_id)
	var domain_id: String = agent.get("domain_id", "") if agent.get("domain_id") != null else ""
	if domain_id.is_empty(): return
	if _panel.visible and selected_domain_id != domain_id: _background()
	selected_domain_id = domain_id
	_remember(domain_id)
	_agents[domain_id] = nearby_agent_id
	anchor_agent_id = nearby_agent_id
	remote = false
	_return_to_anchor = false
	_view_guard = true
	_panel.show()
	BridgeClient.surface.open("pane", domain_id, nearby_agent_id)
	_refresh()
	_restore_result_view()

func _open_remote() -> void:
	if selected_domain_id.is_empty(): return
	if BridgeClient.surface.domain_id == selected_domain_id and not BridgeClient.surface.agent_id.is_empty():
		_agents[selected_domain_id] = BridgeClient.surface.agent_id
	anchor_agent_id = ""
	remote = true
	_return_to_anchor = false
	_view_guard = true
	_panel.show()
	BridgeClient.surface.open("pane", selected_domain_id, _agents.get(selected_domain_id, ""))
	_refresh()
	_restore_result_view()

func _refocus() -> void:
	if BridgeClient.surface.owner == "pane": BridgeClient.surface.refocus()
	else: BridgeClient.surface.open("pane", selected_domain_id, _agents.get(selected_domain_id, ""))
	_refresh()

func _background() -> void:
	_return_to_anchor = not remote and not anchor_agent_id.is_empty()
	_save_result_view(_results.get_v_scroll_bar().value)
	BridgeClient.surface.close("pane")
	_release_focus()
	_panel.hide()
	_refresh()

func _recover() -> void:
	BridgeClient.describe_workspace()
	BridgeClient.domain_status(selected_domain_id)

func _submit(text: String) -> void:
	if _action("Run").disabled: return
	var task := _task_input.text if text.is_empty() else text
	if task.strip_edges().is_empty(): return
	BridgeClient.send_domain_query(selected_domain_id, _agents.get(selected_domain_id, ""), task)

func _draft(text: String) -> void:
	if selected_domain_id.is_empty(): return
	if not BridgeClient.set_domain_draft(selected_domain_id, text):
		_task_input.text = BridgeClient.domain_snapshot(selected_domain_id).get("draft", "")

func _domain_changed(domain_id: String, _reason: String, _request_id: String) -> void:
	_remember(domain_id)
	_refresh()

func _character_changed(agent_id: String, _reason: String, _request_id: String) -> void:
	var data := BridgeClient.character_snapshot(agent_id)
	if data.get("execution_kind") == "working" and BridgeClient.workspace_snapshot().get("project_id") != null:
		_remember(data.domain_id)
		if not _agents.has(data.domain_id): _agents[data.domain_id] = agent_id
	_refresh()

func _surface_changing() -> void:
	if BridgeClient.surface.owner == "pane": _save_result_view(_results.get_v_scroll_bar().value)

func _surface_changed() -> void:
	if BridgeClient.surface.owner != "pane":
		_release_focus()
		_panel.hide()
		_return_to_anchor = false
	_refresh()

func _workspace_changed(_reason: String, _request_id: String) -> void:
	var workspace := BridgeClient.workspace_snapshot()
	var value: Variant = workspace.get("project_id")
	var project: String = value if value is String else ""
	var authoritative_binding: bool = not project.is_empty() or workspace.get("stage") == "unconfigured"
	if authoritative_binding and not _project_id.is_empty() and project != _project_id:
		_release_focus()
		_panel.hide()
		selected_domain_id = ""
		anchor_agent_id = ""
		_return_to_anchor = false
		_domains.clear()
		_agents.clear()
		_select.clear()
	if authoritative_binding:
		_project_id = project
	_refresh()

func _set_enabled(control: Button, enabled: bool) -> void:
	if not enabled and control.has_focus(): control.release_focus()
	control.disabled = not enabled
	control.focus_mode = Control.FOCUS_ALL if enabled else Control.FOCUS_NONE

func _refresh() -> void:
	if not is_node_ready(): return
	var workspace := BridgeClient.workspace_snapshot()
	var character := BridgeClient.character_snapshot(_agents.get(selected_domain_id, ""))
	var department: Dictionary = character.get("workspace", {})
	var memory: Dictionary = workspace.get("memory", {})
	_workspace.text = "Project: %s\nWorkspace: %s\nBranch: %s\nSetup: %s · Memory: %s" % [workspace.get("project_path", "unconfigured"), department.get("worktree_path", "unprepared"), department.get("branch", "unprepared"), workspace.get("stage", "unknown"), memory.get("status", "unavailable")]
	_opener.visible = BridgeClient.character_snapshot(nearby_agent_id).get("execution_kind") == "working"
	_opener.text = "Domain work · " + str(AgentRegistry.get_agent(nearby_agent_id).get("name", nearby_agent_id))
	_select.visible = not _domains.is_empty()
	if selected_domain_id in _domains: _select.select(_domains.find(selected_domain_id))
	var summaries: Array[String] = []
	for domain_id in _domains:
		var d := BridgeClient.domain_snapshot(domain_id)
		summaries.append("%s: %s / %s · %s unread · %s" % [domain_id, d.get("state", "inactive"), d.get("execution_state", "idle"), _difference(d.get("received_cursor", "0"), d.get("consumed_cursor", "0")), _omitted(d.get("omitted_count", 0))])
	_global.text = "Setup: %s · Memory: %s" % [workspace.get("stage", "unknown"), memory.get("status", "unavailable")]
	if selected_domain_id in _domains: _global.text += "\n" + summaries[_domains.find(selected_domain_id)]
	if not BridgeClient.is_bridge_connected(): _global.text = "Disconnected · " + _global.text
	var snapshot := BridgeClient.domain_snapshot(selected_domain_id) if not selected_domain_id.is_empty() else {}
	var connected: bool = BridgeClient.is_bridge_connected()
	var state: String = snapshot.get("state", "inactive")
	var execution: String = snapshot.get("execution_state", "idle")
	var pending: Dictionary = snapshot.get("pending_control", {})
	var generation: String = snapshot.get("domain_session_id", "")
	var uncertain: bool = snapshot.get("uncertain", false)
	var settled := pending.is_empty()
	var ready := connected and not snapshot.is_empty()
	_set_enabled(_action("Start"), ready and settled and state == "inactive" and execution == "idle" and character.get("capabilities", {}).get("can_start", false))
	_set_enabled(_action("Run"), ready and settled and not uncertain and state in ["active", "background"] and execution == "idle" and snapshot.get("pending_query", {}).is_empty() and _agents.has(selected_domain_id))
	_set_enabled(_action("Stop"), ready and not generation.is_empty() and (settled or pending.get("type") == "activate_domain") and (state != "inactive" or uncertain))
	_set_enabled($Global/Toolbar/StopButton, not _action("Stop").disabled)
	_set_enabled(_action("Refocus"), ready and settled and not generation.is_empty())
	_set_enabled(_global_refocus, ready and settled and not generation.is_empty())
	_set_enabled(_action("Status"), ready)
	_set_enabled(_action("Background"), true)
	_task_input.editable = connected
	if not connected and _task_input.has_focus(): _task_input.release_focus()
	_task_input.focus_mode = Control.FOCUS_ALL if connected else Control.FOCUS_NONE
	var draft: String = snapshot.get("draft", "")
	if _task_input.text != draft: _task_input.text = draft
	_status.text = "%s · %s · %s%s\n%s unread · %s" % [selected_domain_id, state, execution, " · uncertain — Refresh status / Refocus to recover" if uncertain else "", _difference(snapshot.get("received_cursor", "0"), snapshot.get("consumed_cursor", "0")), _omitted(snapshot.get("omitted_count", 0))]
	if not generation.is_empty() and state != "inactive": _status.text += "\nStop to release workspace"
	if not connected: _status.text += "\nDisconnected — work outcome may be unknown"
	var lines: Array[String] = []
	var spans: Array[Dictionary] = []
	var character_offset := 0
	for result in snapshot.get("results", []):
		var archived: bool = result.domain_session_id != generation
		var turn_memory: Dictionary = result.get("memory", {})
		lines.append("[%s%s · %s · output %s · %s · memory %s]\n%s\n%s" % ["Archived " if archived else "", result.domain_session_id, result.agent_id, result.output_id, result.status, "saved" if turn_memory.get("saved", false) else "unsaved", result.get("task", ""), result.get("output", result.get("message", ""))])
		spans.append({"request_id": result.request_id, "generation": result.domain_session_id, "role": "assistant", "start": character_offset, "length": lines.back().length()})
		character_offset += lines.back().length() + 2
	var error: Dictionary = snapshot.get("error", {})
	if not error.is_empty():
		lines.append("Notice: %s — %s" % [error.get("error_type", "unknown"), error.get("message", "")])
		var command_error: Dictionary = error.get("command_error", {})
		if not command_error.is_empty():
			lines.append("Command notice: %s — %s" % [command_error.get("error_type", "unknown"), command_error.get("message", "")])
		for query in error.get("unresolved_queries", []):
			lines.append("[Unknown outcome · generation %s · request %s]\n%s" % [query.get("domain_session_id", ""), query.get("request_id", ""), query.get("task", "")])
	var rendered := "\n\n".join(lines)
	if _results.text != rendered:
		_save_result_view(_results.get_v_scroll_bar().value)
		_view_guard = true
		_results.text = rendered
		_result_spans = spans
		_restore_result_view()
	# Only current-generation displayed receipts may advance current read state.
	if _panel.visible and snapshot.get("received_cursor", "0") != snapshot.get("consumed_cursor", "0"):
		var read_id: String = snapshot.get("consumed_cursor", "0")
		for result in snapshot.get("results", []):
			if result.domain_session_id == generation and _compare(result.output_id, snapshot.received_cursor) <= 0 and _compare(result.output_id, read_id) > 0:
				read_id = result.output_id
		if read_id != snapshot.get("consumed_cursor", "0"): BridgeClient.mark_domain_read(selected_domain_id, read_id)

func _omitted(value: int) -> String:
	return ("at least " if value == 2147483647 else "") + str(value) + " omitted"

func _compare(a: String, b: String) -> int:
	if a.length() != b.length(): return 1 if a.length() > b.length() else -1
	return 0 if a == b else (1 if a > b else -1)

func _difference(a: String, b: String) -> String:
	# Cursor magnitude never passes through int64.
	if _compare(a, b) <= 0: return "0"
	var output := ""
	var borrow := 0
	var padded := b.lpad(a.length(), "0")
	for i in range(a.length() - 1, -1, -1):
		var digit := a.unicode_at(i) - padded.unicode_at(i) - borrow
		borrow = 1 if digit < 0 else 0
		output = str(digit + 10 if digit < 0 else digit) + output
	while output.length() > 1 and output.begins_with("0"): output = output.substr(1)
	return output

func _release_focus() -> void:
	var owner := get_viewport().gui_get_focus_owner()
	if owner != null and (_panel.is_ancestor_of(owner) or $Global.is_ancestor_of(owner)): owner.release_focus()

func _input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed: return
	var owner := get_viewport().gui_get_focus_owner()
	if owner == null or not (_panel.is_ancestor_of(owner) or $Global.is_ancestor_of(owner)): return
	if event.is_action_pressed("chat_release_focus", false, true):
		if _panel.visible: _background()
		else: owner.release_focus()
	elif _panel.is_ancestor_of(owner) and (event.is_action_pressed("chat_focus_next", false, true) or event.is_action_pressed("chat_focus_previous", false, true)):
		var controls: Array[Control] = [_results, _task_input]
		for name in ["Start", "Run", "Refocus", "Background", "Stop", "Status"]: controls.append(_action(name))
		var enabled: Array[Control] = []
		for control in controls:
			if control.is_visible_in_tree() and control.focus_mode == Control.FOCUS_ALL: enabled.append(control)
		var direction := -1 if event.shift_pressed else 1
		var next := enabled[posmod(enabled.find(owner) + direction, enabled.size())]
		next.grab_focus()
		$Panel/Scroll.ensure_control_visible(next)
	else: return
	get_viewport().set_input_as_handled()

func _layout() -> void:
	var size := get_viewport().get_visible_rect().size
	# Reserve the lower half for existing NPC output. Scroll keeps all controls
	# reachable at smaller window sizes without changing the NPC panel geometry.
	$Global.position = Vector2(12, 8)
	$Global.size.x = maxf(1, size.x - 24)
	_panel.position = Vector2(12, 92)
	_panel.size = Vector2(maxf(1, size.x - 24), maxf(1, minf(240, size.y - 420)))
	if _panel.position.y + _panel.size.y > size.y: _panel.position.y = maxf(0, size.y - _panel.size.y)


func _save_result_view(value: float) -> void:
	if _view_guard or not _panel.visible or BridgeClient.surface.owner != "pane" or selected_domain_id.is_empty(): return
	var bar := _results.get_v_scroll_bar()
	var follow := value >= maxf(0, bar.max_value - bar.page) - 2
	var anchor := {}
	if not follow:
		for span in _result_spans:
			var line := _results.get_character_line(span.start + span.length - 1)
			if _results.get_line_offset(line) >= value:
				anchor = {"request_id": span.request_id, "generation": span.generation, "role": span.role, "relative": 0, "character": span.start, "offset": value - _results.get_line_offset(_results.get_character_line(span.start))}
				break
	BridgeClient.domains.save_view(selected_domain_id, value, follow, anchor)

func _restore_result_view() -> void:
	_view_guard = true
	_view_revision += 1
	var revision := _view_revision
	var domain := selected_domain_id
	await get_tree().process_frame
	await get_tree().process_frame
	if revision != _view_revision or domain != selected_domain_id: return
	var view: Dictionary = BridgeClient.domain_snapshot(domain).get("view", {})
	var bar := _results.get_v_scroll_bar()
	var value: float = view.get("scroll", 0.0)
	var anchor: Dictionary = view.get("anchor", {})
	if not anchor.is_empty():
		value = 0
		for span in _result_spans:
			if span.request_id == anchor.get("request_id") and str(span.generation) == str(anchor.get("generation")):
				value = _results.get_line_offset(_results.get_character_line(span.start)) + anchor.get("offset", 0.0)
				break
	bar.value = maxf(0, bar.max_value - bar.page) if view.get("follow", true) else value
	_view_guard = false
