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
var hold_domain_status := false

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
			var response := {"type": "agent_status", "request_id": p.request_id, "agent_id": p.agent_id, "execution_kind": "working", "domain_id": "core", "project": workspace(""), "workspace": {"stage": "ready" if prepared else "unprepared"}, "domain_state": observation, "capabilities": {"can_start": not prepared or lifecycle == "inactive", "can_run": prepared and lifecycle in ["active", "background"], "can_prepare_project": true}}
			status_packets.append(response)
			if not hold_status: peer.send_text(JSON.stringify(response))
		elif p.get("type") == "domain_status":
			status_attempts += 1
			if hold_domain_status:
				commands.append(p)
				continue
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
	failed_result_rendering_checks(terminal)
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
	await review_regressions()
	await review_round2()
	check(not button("Stop").disabled, "idle owned session retains Stop")
	check(not BridgeClient.character_snapshot("systems-architect").capabilities.can_start and not BridgeClient.character_snapshot("security-auditor").capabilities.can_start, "active status caches false Start for both representatives")
	hold_status = true
	BridgeClient.agent_status("systems-architect")
	await frames()
	var before_stop_status: Dictionary = status_packets.back()
	button("Stop").pressed.emit()
	await frames()
	check(count("deactivate_domain") == 1, "primary Stop releases idle ownership explicitly")
	lifecycle = "inactive"
	await deliver(state(latest("deactivate_domain").request_id, lifecycle))
	hold_status = false
	await deliver(before_stop_status)
	await frames(20)
	check(not button("Start").disabled, "Stop refreshes primary Start without manual status or approach")
	check(not pane.get_node("Panel/Scroll/Rows/Actions/Start").disabled, "Stop refreshes secondary Start without manual status or approach")
	check(BridgeClient.character_snapshot("systems-architect").capabilities.can_start and BridgeClient.character_snapshot("security-auditor").capabilities.can_start, "Stop refreshes every observed representative capability")
	# Late discovery can cache an observation, never reopen a departed character.
	hold_status = true
	BridgeClient.agent_status("security-auditor")
	await frames()
	var late: Dictionary = status_packets.back()
	GameEvents.npc_left.emit("systems-architect")
	await deliver(late)
	check(not panel.visible and count("activate_domain") == 1 and count("domain_query") == 3, "late status after departure never opens or executes")
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
	check(not panel.visible and count("domain_query") == 3, "status error cannot steal foreground or execute")
	await diagnostic_command_regressions()
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

func failed_result_rendering_checks(template: Dictionary) -> void:
	# Rendering regressions use synthetic result snapshots; lifecycle/transport
	# admission is exercised by the surrounding native production scene flow.
	var domain: Dictionary = BridgeClient.domains._domain("core")
	var original_results: Array = domain.results.duplicate(true)
	var pane := main.get_node("DomainHUD")
	var pane_results: RichTextLabel = pane.get_node("Panel/Scroll/Rows/ResultsLabel")
	for partial in ["", "Partial café 雪"]:
		var failed := template.duplicate(true)
		failed.output = partial
		failed.status = "error"
		failed.reason = "readiness_failed"
		failed.readiness_category = "cwd_mismatch"
		domain.results = [failed]
		hud._render_domain(failed.request_id)
		pane._refresh()
		check(results.visible_characters == -1, "new failed result shows its cause immediately, including empty output")
		for label in [results, pane_results]:
			check(label.text.contains("root cwd") and label.text.contains("Stop"), "both panes show recovery for %s failed output" % ("empty" if partial.is_empty() else "partial"))
			check(partial.is_empty() or label.text.contains(partial), "both panes retain Unicode failed partial answer")
		if not partial.is_empty():
			var span: Dictionary = hud.current_assistant_span()
			check(results.text.substr(span.start, span.length) == partial, "failure cause stays alongside the exact partial assistant span")
	var unknown := template.duplicate(true)
	unknown.output = ""
	unknown.status = "error"
	unknown.reason = "synthetic-sensitive password=not-real"
	domain.results = [unknown]
	domain.error = {"error_type": "workspace_invalid", "message": "The configured workspace needs inspection.", "internal": "synthetic-sensitive"}
	hud._render_domain()
	pane._refresh()
	for label in [results, pane_results]:
		check(label.text.contains("could not complete") and label.text.contains("needs inspection"), "both panes show readable unknown failure and command notice")
		check(not label.text.contains("synthetic-sensitive") and not label.text.contains("\"error_type\""), "ordinary failure display omits raw JSON and untrusted reason")
	domain.results = original_results
	domain.error = {}
	hud._render_domain()
	pane._refresh()

func visible_notice(needle: String) -> bool:
	var endpoint := results.text.find(needle) + needle.length()
	return results.text.contains(needle) and (results.visible_characters < 0 or results.visible_characters >= endpoint)

func diagnostic_command_regressions() -> void:
	hold_status = false
	GameEvents.npc_approached.emit("systems-architect", AgentRegistry.get_agent("systems-architect"))
	await frames(20)
	# Settle the earlier departure's actual Background/Refocus/replay commands
	# before starting this independent generation; never replace store snapshots.
	for _i in 6:
		var returning: Dictionary = BridgeClient.domain_snapshot("core").pending_control
		if returning.is_empty(): break
		var returned := state(returning.request_id, "inactive")
		if returning.get("type") == "resume":
			returned.merge({"type": "resume_complete", "high_water_mark": "3", "earliest_output_id": "1", "history_gap": false}, true)
		await deliver(returned)
	generation = "diagnostics"
	lifecycle = "active"
	var start_id := BridgeClient.activate_domain("core")
	check(not start_id.is_empty(), "diagnostic fixture admits explicit Start")
	await frames()
	await deliver(state(start_id, "activating"))
	await deliver(state(start_id))
	check(BridgeClient.domain_snapshot("core").state == "active" and BridgeClient.domain_snapshot("core").domain_session_id == generation, "diagnostic fixture receives active generation")
	var success_id := BridgeClient.send_domain_query("core", "systems-architect", "successful animation before preflight failure")
	check(not success_id.is_empty(), "diagnostic fixture admits explicit successful Run")
	await frames()
	var success := latest("domain_query")
	var answer := "Successful café reply continues revealing. ".repeat(10)
	await deliver({"type": "domain_result", "request_id": success_id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": generation, "output_id": "1", "agent_id": success.agent_id, "task": success.task, "output": answer, "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": true, "revision": 12, "error_type": null}})
	var span: Dictionary = hud.current_assistant_span()
	check(results.visible_characters >= span.start and results.visible_characters < span.start + span.length, "real successful terminal starts ordinary typewriter reveal")
	BridgeClient.set_domain_draft("core", "unrelated draft preserves successful animation")
	await frames(2)
	check(results.visible_characters >= span.start and results.visible_characters < span.start + span.length, "ordinary input notification preserves successful reveal without a failure")
	var failure_id := BridgeClient.send_domain_query("core", "systems-architect", "preflight branch mismatch")
	await frames()
	check(BridgeClient.domain_snapshot("core").pending_query.get("request_id") == failure_id, "real pending Run exists before diagnostic preflight failure")
	var failure := state(failure_id)
	failure.merge({"type": "domain_error", "status": "error", "error_type": "workspace_invalid", "message": "The configured workspace needs inspection.", "terminal_reason": "readiness_failed", "readiness_category": "branch_changed"}, true)
	var arrival_check := func(domain: String, reason: String, request: String):
		if domain == "core" and reason == "domain_error" and request == failure_id:
			check(results.text.contains(failure.message), "actual domain_error notification appends ordinary notice text")
			check(visible_notice(failure.message), "actual new command notice is immediately visible before passive refresh")
	GameEvents.domain_changed.connect(arrival_check)
	await deliver(failure)
	GameEvents.domain_changed.disconnect(arrival_check)
	var notice: Dictionary = BridgeClient.domain_snapshot("core").error
	check(notice.get("terminal_reason") == "readiness_failed" and notice.get("readiness_category") == "branch_changed", "real packet path retains diagnostic categories through automatic status refresh")
	var pane_results: RichTextLabel = main.get_node("DomainHUD/Panel/Scroll/Rows/ResultsLabel")
	for label in [results, pane_results]:
		check(label.text.contains("owned branch") and label.text.contains("no automatic reset or checkout repair"), "normal notification renders branch recovery in both panes")
	check(visible_notice("no automatic reset or checkout repair"), "new preflight notice is immediately inside visible range during prior successful reveal")
	hud._process(float(answer.length()) / 55.0 + 1.0)
	check(visible_notice("no automatic reset or checkout repair"), "preflight notice remains visible after prior successful animation duration")
	# A receipt error and a separate command failure must coexist through the
	# actual completion/error packets, without assigning snapshots or internals.
	var replay_id := BridgeClient.resume_domain("core")
	await frames()
	var completion := state(replay_id)
	completion.merge({"type": "resume_complete", "high_water_mark": "2", "earliest_output_id": "1", "history_gap": false}, true)
	await deliver(completion)
	hold_domain_status = true
	var status_id := BridgeClient.domain_status("core")
	await frames()
	if status_id.is_empty(): status_id = latest("domain_status").get("request_id", "")
	failure.request_id = status_id
	failure.readiness_category = "cwd_mismatch"
	await deliver(failure)
	var layered: Dictionary = BridgeClient.domain_snapshot("core").error
	check(layered.get("error_type") == "replay_incomplete" and layered.get("command_error", {}).get("readiness_category") == "cwd_mismatch", "normal packet flow retains nested command category alongside receipt error")
	for label in [results, pane_results]:
		check(label.text.contains("Retained output is missing") and label.text.contains("root cwd") and label.text.contains("Stop"), "both panes render nested command recovery alongside receipt failure")
	check(visible_notice("root cwd"), "nested command notice is inside NPC visible range")
	status_id = BridgeClient.domain_status("core")
	await frames()
	failure.request_id = status_id
	failure.terminal_reason = "synthetic-sensitive"
	failure.readiness_category = "synthetic-sensitive"
	await deliver(failure)
	var unknown: Dictionary = BridgeClient.domain_snapshot("core").error.get("command_error", {})
	check(not unknown.has("terminal_reason") and not unknown.has("readiness_category"), "real command flow drops untrusted diagnostic strings")
	check(not results.text.contains("synthetic-sensitive") and not pane_results.text.contains("synthetic-sensitive"), "untrusted provider diagnostics remain absent from both panes")
	hold_domain_status = false

func settle_return() -> void:
	await frames()
	lifecycle = "active"
	await deliver(state(latest("refocus_domain").request_id))
	var completion := state(latest("resume").request_id)
	completion.merge({"type": "resume_complete", "high_water_mark": "2", "earliest_output_id": "1", "history_gap": false}, true)
	await deliver(completion)

func review_regressions() -> void:
	var pane := main.get_node("DomainHUD")
	var pane_panel: Control = pane.get_node("Panel")
	var pane_input: LineEdit = pane.get_node("Panel/Scroll/Rows/TaskInput")
	var pane_results: RichTextLabel = pane.get_node("Panel/Scroll/Rows/ResultsLabel")
	pane.get_node("Global/Toolbar/NearbyDomainButton").pressed.emit()
	await frames()
	hold_status = true
	BridgeClient.agent_status("security-auditor")
	await frames()
	await deliver(status_packets.back())
	hold_status = false
	pane_input.text = "intentional Architect pane Run"
	pane_input.text_changed.emit(pane_input.text)
	pane.get_node("Panel/Scroll/Rows/Actions/Run").pressed.emit()
	await frames()
	var run := latest("domain_query")
	check(run.agent_id == "systems-architect", "R1 late other Core status cannot change intentional pane Run representative")
	await deliver({"type": "domain_result", "request_id": run.request_id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": "A", "output_id": "2", "agent_id": run.agent_id, "task": run.task, "output": "Long result line\n".repeat(100), "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": true, "revision": 10, "error_type": null}})
	await frames(8)
	var bar := pane_results.get_v_scroll_bar()
	check(bar.max_value > bar.page + 100, "R2 fixture provides scrollable long history")
	bar.value = 70
	await frames()
	var saved: Dictionary = BridgeClient.domain_snapshot("core").view.duplicate(true)
	check(not saved.follow and not saved.anchor.is_empty(), "R2 pane establishes non-follow semantic reading anchor")
	pane.get_node("Panel/Scroll/Rows/Actions/Background").pressed.emit()
	await frames()
	check(BridgeClient.domain_snapshot("core").view == saved, "R2 hidden dialogue cannot overwrite outgoing pane reading view")
	lifecycle = "background"
	await deliver(state(latest("background_domain").request_id, lifecycle))
	pane.get_node("Global/Toolbar/RefocusButton").pressed.emit()
	await settle_return()
	check(not BridgeClient.domain_snapshot("core").view.follow and BridgeClient.domain_snapshot("core").view.anchor == saved.anchor and is_equal_approx(bar.value, saved.scroll), "R2 pane reopen restores saved scroll, follow and anchor")
	var backgrounds := count("background_domain")
	pane_input.grab_focus()
	await key(KEY_ESCAPE)
	check(not pane_panel.visible and BridgeClient.surface.owner.is_empty() and count("background_domain") == backgrounds + 1 and count("deactivate_domain") == 0, "R3 native pane Escape closes and backgrounds without Stop")
	# Keep the red run bounded even if Escape has not yet implemented closing.
	if pane_panel.visible: pane.get_node("Panel/Scroll/Rows/Actions/Background").pressed.emit()
	await frames()
	lifecycle = "background"
	await deliver(state(latest("background_domain").request_id, lifecycle))
	pane.get_node("Global/Toolbar/RefocusButton").pressed.emit()
	await frames()
	var pending := latest("refocus_domain")
	backgrounds = count("background_domain")
	pane_input.grab_focus()
	await key(KEY_ESCAPE)
	check(not pane_panel.visible and count("background_domain") == backgrounds, "R3 Escape during pending refocus closes and waits for exact control")
	await deliver(state("unrelated-refocus"))
	check(count("background_domain") == backgrounds, "R3 unrelated acknowledgment cannot release deferred background")
	await deliver(state(pending.request_id))
	check(count("background_domain") == backgrounds + 1 and count("deactivate_domain") == 0, "R3 matching pending control backgrounds once without Stop")
	if pane_panel.visible: pane.get_node("Panel/Scroll/Rows/Actions/Background").pressed.emit()
	await frames()
	lifecycle = "background"
	await deliver(state(latest("background_domain").request_id, lifecycle))
	GameEvents.npc_approached.emit("systems-architect", AgentRegistry.get_agent("systems-architect"))
	await settle_return()

func review_round2() -> void:
	var pane := main.get_node("DomainHUD")
	GameEvents.npc_approached.emit("security-auditor", AgentRegistry.get_agent("security-auditor"))
	await frames()
	check(BridgeClient.surface.agent_id == "security-auditor" and panel.visible, "R2 intentional Auditor dialogue owns Core surface")
	pane.get_node("Global/Toolbar/RefocusButton").pressed.emit()
	await frames()
	var pane_input: LineEdit = pane.get_node("Panel/Scroll/Rows/TaskInput")
	pane_input.text = "intentional Auditor remote-pane Run"
	pane_input.text_changed.emit(pane_input.text)
	pane.get_node("Panel/Scroll/Rows/Actions/Run").pressed.emit()
	await frames()
	var run := latest("domain_query")
	check(run.agent_id == "security-auditor" and BridgeClient.surface.agent_id == "security-auditor", "R2 global Refocus handoff retains intentional Auditor Run representative")
	await deliver({"type": "domain_result", "request_id": run.request_id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": "A", "output_id": "3", "agent_id": run.agent_id, "task": run.task, "output": "Auditor result line\n".repeat(100), "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": true, "revision": 11, "error_type": null}})
	GameEvents.npc_approached.emit("systems-architect", AgentRegistry.get_agent("systems-architect"))
	await frames(8)
	hud._manual_scroll(90)
	await frames()
	var outgoing: Dictionary = BridgeClient.domain_snapshot("core").view
	check(not outgoing.follow and not outgoing.anchor.is_empty(), "R2 cross-domain fixture has settled outgoing semantic view")
	var cached := BridgeClient.character_snapshot("systems-architect")
	cached.domain_id = "engineering"
	BridgeClient._characters["backend-architect"] = cached
	var observation := state("", "inactive")
	observation.domain_id = "engineering"
	observation.workspace_id = null
	observation.domain_session_id = null
	BridgeClient.domains.observe_domain(observation, BridgeClient.domains.observation_fence())
	BridgeClient.domains.save_view("engineering", 0, true, {})
	var incoming: Dictionary = BridgeClient.domain_snapshot("engineering").view.duplicate(true)
	hold_status = true
	GameEvents.npc_approached.emit("backend-architect", AgentRegistry.get_agent("backend-architect"))
	check(panel.visible and BridgeClient.surface.domain_id == "engineering", "R2 intentional cached cross-domain approach keeps incoming dialogue visible")
	check(BridgeClient.domain_snapshot("engineering").view == incoming, "R2 cached domain transition never writes rendered Core anchor into incoming view")
	await frames()
	check(BridgeClient.domain_snapshot("engineering").view.anchor.is_empty() and count("activate_domain") == 1, "R2 incoming blank-domain view stays independent without implicit Start")
	var observed: Dictionary = status_packets.back().duplicate(true)
	observed.domain_id = "engineering"
	observed.domain_state = observation
	hold_status = false
	await deliver(observed)
	lifecycle = "background"
	await deliver(state(latest("background_domain").request_id, lifecycle))
	GameEvents.npc_approached.emit("systems-architect", AgentRegistry.get_agent("systems-architect"))
	await frames()
	lifecycle = "active"
	await deliver(state(latest("refocus_domain").request_id))
	var completion := state(latest("resume").request_id)
	completion.merge({"type": "resume_complete", "high_water_mark": "3", "earliest_output_id": "1", "history_gap": false}, true)
	await deliver(completion)
