extends Node

## Production scene + real areas/player/native UI + provider-free loopback.
var checks := 0
var failures: Array[String] = []
var server := TCPServer.new()
var peer: WebSocketPeer
var commands: Array[Dictionary] = []
var main: Node
var hud: Node
var panel: Control
var input: LineEdit
var results: RichTextLabel
var player: CharacterBody2D
var lifecycle := "active"
var execution := "idle"
var generation := "A"
var status_attempts := 0
var fail_next_status := false
var unconfigured := false
var prepared := false
var status_packets: Array[Dictionary] = []
var hold_status := false

func check(ok: bool, message: String) -> bool:
	checks += 1
	if not ok: failures.append(message)
	return ok

func workspace(id: String) -> Dictionary:
	if unconfigured:
		return {"type": "workspace_state", "request_id": id, "project_id": null, "workspace_id": null, "stage": "unconfigured", "reason": null, "architect_decision": null, "project_path": null, "worktree_path": null, "branch": null, "changed_files": null, "reservation": null, "memory": {"path": null, "status": "unavailable", "revision": null, "error_type": null}}
	return {"type": "workspace_state", "request_id": id, "project_id": "P", "workspace_id": "W", "stage": "ready", "reason": null, "architect_decision": null, "project_path": "/project", "worktree_path": "/execution", "branch": "plaza/workspace-P", "changed_files": {"total": 0, "tracked": 0, "untracked": 0, "truncated": false}, "reservation": null, "memory": {"path": "/memory", "status": "saved", "revision": 8, "error_type": null}}

func state(id: String, value: String = "active") -> Dictionary:
	return {"type": "domain_state", "request_id": id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": generation, "state": value, "execution_state": execution}

func service() -> void:
	if peer == null: return
	peer.poll()
	while peer.get_available_packet_count() > 0:
		var p: Dictionary = JSON.parse_string(peer.get_packet().get_string_from_utf8())
		if p.get("type") == "describe_workspace": peer.send_text(JSON.stringify(workspace(p.request_id)))
		elif p.get("type") == "agent_status":
			var observation := state("", lifecycle if prepared else "inactive")
			observation.erase("request_id")
			if not prepared: observation.domain_session_id = null
			var response := {"type": "agent_status", "request_id": p.request_id, "agent_id": p.agent_id, "execution_kind": "working", "domain_id": "core", "project": workspace(""), "workspace": {"stage": "ready" if prepared else "unprepared"}, "domain_state": observation, "capabilities": {"can_start": true, "can_run": prepared, "can_prepare_project": true}}
			status_packets.append(response)
			if not hold_status: peer.send_text(JSON.stringify(response))
		elif p.get("type") == "domain_status":
			status_attempts += 1
			var response := state(p.request_id, lifecycle)
			if fail_next_status:
				fail_next_status = false
				response.merge({"type": "domain_error", "status": "error", "error_type": "status_unavailable", "message": "status unavailable"}, true)
			peer.send_text(JSON.stringify(response))
		else: commands.append(p)

func frames(n: int = 5) -> void:
	for i in n:
		service()
		await get_tree().process_frame

func deliver(p: Dictionary) -> void:
	peer.send_text(JSON.stringify(p))
	await frames()

func count(kind: String) -> int:
	var total := 0
	for p in commands:
		if p.get("type") == kind: total += 1
	return total

func latest(kind: String) -> Dictionary:
	for i in range(commands.size() - 1, -1, -1):
		if commands[i].get("type", "") == kind: return commands[i]
	return {}

func button(name: String) -> Button:
	return hud.get_node("Panel/Margin/Rows/Actions/" + name)

func key(code: Key, shift: bool = false) -> void:
	var e := InputEventKey.new()
	e.keycode = code
	e.physical_keycode = code
	e.shift_pressed = shift
	e.pressed = true
	Input.parse_input_event(e)
	await frames(2)
	e = e.duplicate()
	e.pressed = false
	Input.parse_input_event(e)
	await frames(2)

func click(control: Control) -> void:
	if panel.is_ancestor_of(control):
		await frames(3)
	for pressed in [true, false]:
		var event := InputEventMouseButton.new()
		event.button_index = MOUSE_BUTTON_LEFT
		event.position = control.get_global_rect().get_center()
		event.global_position = event.position
		event.pressed = pressed
		get_viewport().push_input(event, true)
	await frames(3)

func walk(delta: Vector2) -> void:
	for i in 12:
		player.move_and_collide(delta / 12.0)
		await get_tree().physics_frame
	await frames()

func _ready() -> void:
	get_tree().create_timer(25).timeout.connect(func(): check(false, "watchdog"); finish())
	main = load("res://scenes/main.tscn").instantiate()
	add_child(main)
	hud = main.get_node("HUD")
	panel = hud.get_node("Panel")
	input = hud.get_node("Panel/Margin/Rows/InputRow/QuestionInput")
	results = hud.get_node("Panel/Margin/Rows/BodyLabel")
	player = main.get_node("Player")
	BridgeClient._socket.close()
	BridgeClient._socket = WebSocketPeer.new()
	BridgeClient._connected = false
	BridgeClient._reconnect_timer.stop()
	check(server.listen(0, "127.0.0.1") == OK, "loopback listener")
	BridgeClient.bridge_url = "ws://127.0.0.1:%d" % server.get_local_port()
	BridgeClient._attempt_connect()
	for i in 200:
		if peer == null and server.is_connection_available():
			peer = WebSocketPeer.new()
			peer.accept_stream(server.take_connection())
		await frames(1)
		if BridgeClient.is_bridge_connected(): break
	await frames()
	GameEvents.npc_approached.emit("systems-architect", AgentRegistry.get_agent("systems-architect"))
	await frames(12)
	check(not status_packets.is_empty() and commands.is_empty(), "approach performs observation only")
	check(panel.visible and not button("Start").disabled and button("Send").disabled, "primary explicit Start before Run")
	input.text = "first task"
	input.text_changed.emit(input.text)
	input.grab_focus()
	await key(KEY_ENTER)
	check(commands.is_empty(), "Enter never prepares or starts")
	button("Prepare").pressed.emit()
	await frames()
	var setup := latest("project_setup")
	check(setup.get("intent") == "first task", "Prepare sends explicit setup intent")
	await deliver({"type": "project_setup", "agent_id": "systems-architect", "request_id": setup.request_id, "status": "ok", "output": "Approved setup", "project": workspace(""), "architect_decision": {"approved": true}})
	check(results.text.contains("Approved setup") and input.text == "first task", "setup output visible without consuming domain draft")
	button("Start").pressed.emit()
	await frames()
	var start := latest("activate_domain")
	check(count("activate_domain") == 1 and count("domain_query") == 0, "Start reserves without Run")
	prepared = true
	await deliver(state(start.request_id, "activating"))
	check(not button("Stop").disabled and button("Send").disabled, "activating retains Stop")
	await deliver(state(start.request_id))
	input.grab_focus()
	await key(KEY_ENTER)
	var run := latest("domain_query")
	check(count("domain_query") == 1 and run.agent_id == "systems-architect", "Enter sends one admitted originating Run")
	input.text = "next draft"
	input.text_changed.emit(input.text)
	check(input.editable and BridgeClient.domain_snapshot("core").draft == "next draft", "pending Run permits next draft edit")
	var pane := main.get_node("DomainHUD")
	pane.get_node("Global/Toolbar/NearbyDomainButton").pressed.emit()
	await frames()
	check(not panel.visible and pane.get_node("Panel").visible, "secondary handoff has one visible composer")
	check(pane.get_node("Panel/Scroll/Rows/TaskInput").text == "next draft" and count("background_domain") == 0 and count("domain_query") == 1, "same domain handoff shares draft and pending Run")
	GameEvents.npc_approached.emit("security-auditor", AgentRegistry.get_agent("security-auditor"))
	await frames(12)
	check(panel.visible and not pane.get_node("Panel").visible, "other representative uses primary shared surface")
	check(results.text.contains("systems-architect") and not button("Stop").disabled and button("Send").disabled, "inflight attribution remains original representative")
	var terminal := {"type": "domain_result", "request_id": run.request_id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": "A", "output_id": "1", "agent_id": "systems-architect", "task": run.task, "output": "Architect output ibis", "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": false, "revision": 9, "error_type": "write_failed"}}
	await deliver(terminal)
	check(results.text.contains("Architect output ibis") and results.text.contains("systems-architect") and results.text.contains("unsaved"), "same department terminal attributed with unsaved memory")
	check(input.text == "next draft" and BridgeClient.domain_snapshot("core").consumed_cursor == "1", "one shared draft and visible read cursor")
	input.select(0, 4)
	GameEvents.domain_changed.emit("core", "read", "")
	check(input.get_selected_text() == "next", "equal draft refresh preserves native selection")
	input.grab_focus()
	await key(KEY_ESCAPE)
	check(not panel.visible and count("background_domain") == 1 and count("deactivate_domain") == 0, "Escape backgrounds idle ownership without Stop")
	var bg := latest("background_domain")
	GameEvents.npc_left.emit("security-auditor")
	GameEvents.npc_approached.emit("systems-architect", AgentRegistry.get_agent("systems-architect"))
	await frames()
	check(count("refocus_domain") == 0, "return before background ack waits")
	GameEvents.domain_changed.emit("core", "domain_state", "unrelated")
	check(count("refocus_domain") == 0, "unrelated ack does not release return")
	lifecycle = "background"
	await deliver(state(bg.request_id, lifecycle))
	check(count("refocus_domain") == 1 and count("resume") == 0, "matching background ack releases one refocus")
	var refocus := latest("refocus_domain")
	lifecycle = "active"
	await deliver(state(refocus.request_id))
	check(count("resume") == 1, "matching visible refocus releases one replay")
	var resume := latest("resume")
	var completion := state(resume.request_id)
	completion.merge({"type": "resume_complete", "high_water_mark": "1", "earliest_output_id": "1", "history_gap": false}, true)
	await deliver(terminal)
	await deliver(completion)
	check(BridgeClient.domain_snapshot("core").results.size() == 1 and count("domain_query") == 1, "return replay deduplicates without execution")
	check(not button("Stop").disabled, "idle owned session retains Stop")
	button("Stop").pressed.emit()
	await frames()
	check(count("deactivate_domain") == 1, "primary Stop releases idle ownership explicitly")
	await deliver(state(latest("deactivate_domain").request_id, "inactive"))
	# Late discovery can cache an observation, never reopen a departed character.
	hold_status = true
	BridgeClient.agent_status("security-auditor")
	await frames()
	var late: Dictionary = status_packets.back()
	GameEvents.npc_left.emit("systems-architect")
	await deliver(late)
	check(not panel.visible and count("activate_domain") == 1 and count("domain_query") == 1, "late status after departure never opens or executes")
	# Typed service errors retain the status binding and settle only exact correlation.
	var status_request := BridgeClient.agent_status("systems-architect")
	await frames()
	var wrong := {"type": "agent_status", "agent_id": "security-auditor", "request_id": status_request, "status": "error", "error_type": "service_busy", "output": "wrong representative", "project": workspace("")}
	await deliver(wrong)
	check(BridgeClient.character_snapshot("systems-architect").pending == "agent_status", "wrong representative cannot settle character status")
	wrong.agent_id = "systems-architect"
	wrong.type = "project_setup"
	await deliver(wrong)
	check(BridgeClient.character_snapshot("systems-architect").pending == "agent_status", "wrong service cannot settle character status")
	wrong.type = "agent_status"
	wrong.output = "Status temporarily unavailable"
	await deliver(wrong)
	var failed_status := BridgeClient.character_snapshot("systems-architect")
	check(failed_status.pending.is_empty() and failed_status.error == wrong.output and failed_status.domain_id == "core", "typed status error uses output and preserves binding")
	check(not panel.visible and count("domain_query") == 1, "status error cannot steal foreground or execute")
	var setup_late := BridgeClient.project_setup("systems-architect", "explicit review before disconnect")
	await frames()
	# Store observation fences refuse lifecycle snapshots captured before newer work.
	var fence := BridgeClient.domains.observation_fence()
	BridgeClient.domains.admit_command({"type": "activate_domain", "request_id": "new-start", "domain_id": "core"})
	check(not BridgeClient.domains.observe_domain(state("", "inactive"), fence), "older discovery cannot overwrite newly admitted lifecycle")
	BridgeClient._on_connection_closed()
	check(not BridgeClient.domains.observe_domain(state("", "inactive"), fence), "closed epoch rejects nested observation")
	BridgeClient._on_message(JSON.stringify({"type": "project_setup", "agent_id": "systems-architect", "request_id": setup_late, "status": "ok", "output": "stale disconnected setup", "project": workspace(""), "architect_decision": null}))
	check(BridgeClient.character_snapshot("systems-architect").get("setup_output") != "stale disconnected setup" and BridgeClient.character_snapshot("systems-architect").pending.is_empty(), "disconnect settles service and rejects late setup output")
	finish()

func finish() -> void:
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	BridgeClient._socket.close()
	if peer != null: peer.close()
	server.stop()
	for failure in failures: printerr("FAIL: " + failure)
	if failures.is_empty(): print("character_domain_test: OK — %d checks passed." % checks)
	else: printerr("character_domain_test: %d failures / %d checks." % [failures.size(), checks])
	get_tree().quit(0 if failures.is_empty() else 1)
