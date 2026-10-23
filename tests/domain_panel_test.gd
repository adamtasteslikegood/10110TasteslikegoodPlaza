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
			var observation := state("", lifecycle if count("activate_domain") > 0 else "inactive")
			observation.erase("request_id")
			if count("activate_domain") == 0: observation.domain_session_id = null
			peer.send_text(JSON.stringify({"type": "agent_status", "request_id": p.request_id, "agent_id": p.agent_id, "execution_kind": "extra" if p.agent_id.begins_with("fixture-extra") else "working", "domain_id": null if p.agent_id.begins_with("fixture-extra") else "core", "project": workspace(""), "workspace": {"stage": "unprepared"}, "domain_state": observation, "capabilities": {"can_start": true, "can_run": true, "can_prepare_project": true}}))
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
	return hud.get_node("Panel/Scroll/Rows/Actions/" + name)

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
		panel.get_node("Scroll").ensure_control_visible(control)
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
	if delta.y < 0 and count("activate_domain") > 0 and hud.nearby_agent_id == "systems-architect" and hud.selected_domain_id == "core":
		hud.get_node("Global/Toolbar/NearbyDomainButton").pressed.emit()
		await frames()

func _ready() -> void:
	get_tree().create_timer(22).timeout.connect(func():
		check(false, "watchdog completed flow")
		finish())
	preload("res://tests/character_fixture.gd").extras()
	main = load("res://scenes/main.tscn").instantiate()
	main.get_node("Office/SecurityAuditor").agent_id = "fixture-extra-a"
	add_child(main)
	if not check(main.has_node("DomainHUD"), "production Main mounts separate DomainHUD"):
		finish()
		return
	hud = main.get_node("DomainHUD")
	panel = hud.get_node("Panel")
	input = hud.get_node("Panel/Scroll/Rows/TaskInput")
	results = hud.get_node("Panel/Scroll/Rows/ResultsLabel")
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
	check(BridgeClient.is_bridge_connected(), "actual socket connected")
	var npc: Node2D = main.get_node("Office/SystemsArchitect")
	var area: Area2D = npc.get_node("Proximity")
	var radius: float = area.get_node("ProximityShape").shape.radius
	player.position = npc.position + Vector2(0, radius + 40)
	await get_tree().physics_frame
	await walk(Vector2(0, -55))
	check(area.overlaps_body(player), "actual player enters production Chief area")
	check(count("activate_domain") == 0 and count("domain_query") == 0 and commands.is_empty(), "proximity starts no domain or Chief review")
	check(not panel.visible and hud.get_node("Global/Toolbar/NearbyDomainButton").visible, "nearby explicit opener only")
	await click(hud.get_node("Global/Toolbar/NearbyDomainButton"))
	await frames()
	check(panel.visible and count("activate_domain") == 0, "open does not Start")
	check(not button("Start").disabled and button("Run").disabled, "explicit Start available before generation")
	await click(button("Start"))
	await frames()
	check(count("activate_domain") == 1, "one explicit Start")
	var start := latest("activate_domain")
	await deliver(state(start.request_id, "activating"))
	check(button("Run").disabled and not button("Stop").disabled, "activating permits Stop only")
	await deliver(state(start.request_id))
	check(hud.get_node("Panel/Scroll/Rows/StatusLabel").text.contains("Stop to release workspace"), "idle retains reservation copy")
	input.text = "run native once"
	input.text_changed.emit(input.text)
	input.grab_focus()
	await key(KEY_ENTER)
	check(count("domain_query") == 1, "one native Enter one Run")
	var run := latest("domain_query")
	execution = "running"
	var accepted := state(run.request_id)
	accepted.erase("state")
	accepted.merge({"type": "domain_accepted", "agent_id": "systems-architect", "task": run.task}, true)
	await deliver(accepted)
	check(button("Run").disabled and button("Start").disabled and not button("Stop").disabled, "busy controls reflect admitted task")
	input.text = "next draft"
	input.text_changed.emit(input.text)
	input.grab_focus()
	Input.action_press("ui_right")
	var before := player.position
	for i in 3: await get_tree().physics_frame
	check(player.position.distance_to(before) < 1, "actual focused UI blocks movement")
	input.release_focus()
	for i in 3: await get_tree().physics_frame
	Input.action_release("ui_right")
	check(player.position.x > before.x and not input.has_focus(), "releasing keyboard focus permits actual player movement")
	check(panel.visible and BridgeClient.domain_snapshot("core").pending_query.request_id == run.request_id, "focus release preserves visible running task")
	check(BridgeClient.domain_snapshot("core").draft == "next draft", "busy draft retained")
	button("Stop").grab_focus()
	await key(KEY_TAB)
	check(get_viewport().gui_get_focus_owner() == button("Status"), "Tab skips disabled controls")
	await key(KEY_TAB, true)
	check(button("Stop").has_focus(), "Shift Tab reverses enabled controls")
	GameEvents.npc_left.emit("security-auditor")
	await frames()
	check(panel.visible and count("background_domain") == 0, "unrelated departure preserves anchor")
	await walk(Vector2(0, 90))
	check(not area.overlaps_body(player) and not panel.visible and count("background_domain") == 1, "actual anchor departure backgrounds once and closes")
	check(get_viewport().gui_get_focus_owner() == null, "departure releases domain focus")
	lifecycle = "background"
	await deliver(state(latest("background_domain").request_id, lifecycle))
	var npc_body: RichTextLabel = main.get_node("HUD/Panel/Margin/Rows/BodyLabel")
	await walk(Vector2(125, 25))
	check(main.get_node("Office/SecurityAuditor/Proximity").overlaps_body(player), "actual player reaches other production NPC while work runs")
	var other_input: LineEdit = main.get_node("HUD/Panel/Margin/Rows/InputRow/QuestionInput")
	other_input.text = "what should I do for setup?"
	other_input.text_changed.emit(other_input.text)
	other_input.grab_focus()
	await key(KEY_ENTER)
	var other := latest("")
	check(other.get("agent_id") == "fixture-extra-a", "other NPC native question uses ordinary NPC protocol")
	await deliver({"agent_id": "fixture-extra-a", "request_id": other.request_id, "status": "ok", "output": "Ask the Chief Architect to review the configured project."})
	var referral_span: Dictionary = main.get_node("HUD").current_assistant_span()
	main.get_node("HUD")._process(2.0)
	check(npc_body.get_parsed_text().substr(referral_span.start, referral_span.length) == "Ask the Chief Architect to review the configured project.", "current NPC assistant span renders ordinary referral")
	await key(KEY_ESCAPE)
	var old_npc_text := npc_body.get_parsed_text()
	var terminal := {"type": "domain_result", "request_id": run.request_id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": "A", "output_id": "1", "agent_id": "systems-architect", "task": run.task, "output": "domain result nonce ibis ✓\n雪", "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": false, "revision": 9, "error_type": "write_failed"}}
	execution = "idle"
	await deliver(terminal)
	check(not panel.visible and get_viewport().gui_get_focus_owner() == null and npc_body.get_parsed_text() == old_npc_text, "hidden result cannot open focus or overwrite NPC")
	check(hud.get_node("Global/StatusLabel").text.contains("1 unread"), "passive unread uses unconsumed receipt")
	await walk(Vector2(-125, -25))
	await walk(Vector2(0, -90))
	check(panel.visible and count("refocus_domain") == 1 and count("resume") == 0, "actual return refocus waits for ack")
	var refocus := latest("refocus_domain")
	# Repeating the explicit opener while a control is pending must not erase
	# the correlation that will release replay.
	hud.get_node("Global/Toolbar/NearbyDomainButton").pressed.emit()
	await frames()
	check(count("refocus_domain") == 1, "repeated opener does not duplicate pending Refocus")
	GameEvents.domain_changed.emit("core", "domain_state", "unrelated")
	await frames()
	check(count("resume") == 0, "unrelated ack cannot release replay")
	lifecycle = "active"
	await deliver(state(refocus.request_id))
	check(count("resume") == 1, "matching Refocus ack precedes Resume")
	var resume := latest("resume")
	var complete := state(resume.request_id)
	complete.merge({"type": "resume_complete", "high_water_mark": "1", "earliest_output_id": "1", "history_gap": false}, true)
	await deliver(complete)
	check(results.text.contains("domain result nonce ibis") and results.text.contains("unsaved"), "rendered output retains successful unsaved memory")
	check(BridgeClient.domain_snapshot("core").consumed_cursor == "1", "visible current generation marked read")
	check(not input.has_focus() and count("domain_query") == 1 and count("activate_domain") == 1, "return never grabs composer or executes")
	button("Background").pressed.emit()
	await frames()
	check(not panel.visible and count("background_domain") == 2, "Background Close hides without cancelling")
	lifecycle = "background"
	await deliver(state(latest("background_domain").request_id, lifecycle))
	hud.get_node("Global/Toolbar/RefocusButton").pressed.emit()
	await frames()
	var remote := latest("refocus_domain")
	lifecycle = "active"
	await deliver(state(remote.request_id))
	resume = latest("resume")
	complete.request_id = resume.request_id
	await deliver(complete)
	await walk(Vector2(0, 90))
	check(panel.visible and count("background_domain") == 2, "remote detaches proximity anchor")
	check(input.text == "next draft", "draft survives background and return")
	await preload("res://tests/chat_clipboard_checks.gd").run(self, hud, results, input, "Panel/Scroll/Rows/Actions/Copy", "Panel/Scroll/Rows/Actions/SelectAll")
	await layout_checks()
	# Setup now has a typed independent service; the work composer stays shared.
	await walk(Vector2(0, -90))
	var chief_request := BridgeClient.project_setup("systems-architect", "review configured project")
	await frames()
	check(count("domain_query") == 1 and latest("project_setup").get("request_id") == chief_request, "Chief setup uses typed service without a Run")
	await deliver({"type": "project_setup", "agent_id": "systems-architect", "request_id": chief_request, "status": "ok", "output": "Chief explicit review decision", "project": workspace(""), "architect_decision": null})
	check(BridgeClient.character_snapshot("systems-architect").setup_output == "Chief explicit review decision", "typed Chief review remains separate from work history")
	await recovery_checks()
	# Explicit NPC-domain action reattaches even after remote recovery.
	hud.get_node("Global/Toolbar/NearbyDomainButton").pressed.emit()
	await frames()
	check(not hud.remote and hud.anchor_agent_id == "systems-architect", "explicit NPC action reattaches remote view")
	var refocus_on_departure := latest("refocus_domain")
	var backgrounds_before_departure := count("background_domain")
	var resumes_before_departure := count("resume")
	await walk(Vector2(0, 90))
	check(not panel.visible, "reattached view closes on actual anchor departure")
	await deliver(state(refocus_on_departure.request_id))
	check(count("background_domain") == backgrounds_before_departure + 1 and count("resume") == resumes_before_departure, "departure during Refocus backgrounds after ack without replaying hidden view")
	await pending_background_return_checks(area)
	await clipboard_scope_checks()
	# Selecting another known domain must detach the previous physical anchor.
	GameEvents.domain_changed.emit("engineering", "input", "")
	var selector: OptionButton = hud.get_node("Global/Toolbar/DomainSelect")
	selector.item_selected.emit(1)
	await walk(Vector2(0, -90))
	check(not panel.visible and hud.selected_domain_id == "engineering", "global domain selection cannot inherit old anchor return")
	await unconfigured_hud_checks()
	finish()

func pending_background_return_checks(area: Area2D) -> void:
	var background := latest("background_domain")
	var refocuses := count("refocus_domain")
	var resumes := count("resume")
	var starts := count("activate_domain")
	var runs := count("domain_query")
	# Reverse the original test order: physically return before acknowledging
	# Background, while the public client correctly rejects another control.
	await walk(Vector2(0, -90))
	check(area.overlaps_body(player) and panel.visible, "R1 actual anchor return occurs before Background ack")
	check(count("refocus_domain") == refocuses and count("resume") == resumes, "R1 return waits for pending Background")
	GameEvents.domain_changed.emit("core", "domain_state", "unrelated-background-ack")
	await frames()
	check(count("refocus_domain") == refocuses, "R1 unrelated acknowledgment cannot release Refocus")
	lifecycle = "background"
	await deliver(state(background.request_id, lifecycle))
	if not check(count("refocus_domain") == refocuses + 1 and count("resume") == resumes, "R1 matching Background ack admits exactly one Refocus before replay"):
		return
	var refocus := latest("refocus_domain")
	check(refocus.domain_session_id == background.domain_session_id, "R1 deferred Refocus retains exact generation")
	await deliver(state(background.request_id, "background"))
	GameEvents.domain_changed.emit("core", "domain_state", "unrelated-refocus-ack")
	await frames()
	check(count("refocus_domain") == refocuses + 1 and count("resume") == resumes, "R1 duplicate Background and unrelated Refocus acks cannot replay")
	lifecycle = "active"
	await deliver(state(refocus.request_id))
	check(count("resume") == resumes + 1, "R1 only matching admitted Refocus ack releases one Resume")
	var replay := latest("resume")
	var complete := state(replay.request_id)
	complete.merge({"type": "resume_complete", "high_water_mark": replay.cursor, "earliest_output_id": null, "history_gap": false}, true)
	await deliver(complete)
	check(count("activate_domain") == starts and count("domain_query") == runs and get_viewport().gui_get_focus_owner() == null, "R1 reordered return never Starts Runs or grabs focus")
	# Closing again before the Background ack must cancel this view intent.
	await walk(Vector2(0, 90))
	background = latest("background_domain")
	await walk(Vector2(0, -90))
	check(area.overlaps_body(player) and count("refocus_domain") == refocuses + 1, "R1 second physical return is waiting for Background")
	button("Background").pressed.emit()
	await frames()
	await deliver(state(background.request_id, "background"))
	check(not panel.visible and count("refocus_domain") == refocuses + 1 and count("resume") == resumes + 1, "R1 Close cancels deferred Refocus and replay")
	await walk(Vector2(0, 90))

func recovery_checks() -> void:
	input.text = "outcome must remain unknown"
	input.text_changed.emit(input.text)
	button("Run").pressed.emit()
	await frames()
	var unknown := latest("domain_query")
	check(unknown.get("task") == "outcome must remain unknown", "explicit uncertain-run setup")
	peer.close()
	for i in 50:
		await frames(1)
		if not BridgeClient.is_bridge_connected(): break
	check(button("Status").disabled and button("Run").disabled, "disconnect disables execution")
	peer = null
	lifecycle = "inactive"
	BridgeClient._reconnect_timer.stop()
	BridgeClient._attempt_connect()
	for i in 200:
		if peer == null and server.is_connection_available():
			peer = WebSocketPeer.new()
			peer.accept_stream(server.take_connection())
		await frames(1)
		if BridgeClient.is_bridge_connected(): break
	await frames(20)
	# Reconnect replay is transport-owned; settle it without a fabricated terminal.
	var replay := latest("resume")
	var completion := state(replay.get("request_id", "missing"), "inactive")
	completion.merge({"type": "resume_complete", "high_water_mark": "1", "earliest_output_id": "1", "history_gap": false}, true)
	await deliver(completion)
	button("Stop").pressed.emit()
	await frames()
	await deliver(state(latest("deactivate_domain").get("request_id", "missing"), "inactive"))
	check(not button("Start").disabled and not BridgeClient.domain_snapshot("core").pending_query.is_empty(), "confirmed Stop enables Start despite unresolved Run")
	button("Start").pressed.emit()
	await frames()
	generation = "B"
	lifecycle = "active"
	await deliver(state(latest("activate_domain").get("request_id", "missing")))
	check(results.text.contains("Unknown outcome") and results.text.contains(unknown.task), "archived unknown input rendered truthfully")
	check(not button("Run").disabled, "old unknown error does not block healthy new generation")
	check(BridgeClient.domain_snapshot("core").consumed_cursor == "0", "archived result never marks fresh generation read")
	var starts := count("activate_domain")
	var runs := count("domain_query")
	check(starts == 2 and runs == 2, "recovery does not retry Run")
	var attempts := status_attempts
	fail_next_status = true
	await click(button("Status"))
	await frames(20)
	check(status_attempts == attempts + 1 and results.text.contains("status unavailable") and not button("Status").disabled, "failed explicit status stays visible with manual recovery available")
	await click(button("Status"))
	await frames(20)
	check(status_attempts == attempts + 2 and count("domain_query") == runs, "native status recovery retries observation without retrying Run")
	# A receipt hole and a failed recovery observation must both stay visible.
	var incomplete_id: String = BridgeClient.resume_domain("core")
	await frames()
	var incomplete := state(incomplete_id)
	incomplete.merge({"type": "resume_complete", "high_water_mark": "2", "earliest_output_id": "1", "history_gap": false}, true)
	await deliver(incomplete)
	fail_next_status = true
	await click(button("Status"))
	await frames(20)
	check(results.text.contains("replay_incomplete") and results.text.contains("status unavailable"), "final R6 receipt notice and concurrent command failure both rendered")
	check(results.text.contains(unknown.task) and not button("Status").disabled, "final R6 unknown input and recovery controls survive layered notices")
	# Replay a confirmed unavailable prefix larger than int32: the HUD must show
	# the saturated count as an at-least value, with decimal-string unread math.
	button("Refocus").pressed.emit()
	await frames()
	await deliver(state(latest("refocus_domain").request_id))
	replay = latest("resume")
	completion = state(replay.request_id)
	completion.merge({"type": "resume_complete", "high_water_mark": "99999999999999999999", "earliest_output_id": null, "history_gap": true}, true)
	await deliver(completion)
	check(hud.get_node("Global/StatusLabel").text.contains("at least 2147483647 omitted"), "saturated omissions displayed as lower bound")
	check(hud.get_node("Global/StatusLabel").text.contains("99999999999999999999 unread"), "unread cursor arithmetic does not narrow to int64")
	check(count("domain_query") == runs, "replay history gap never retries task")

func layout_checks() -> void:
	var viewport := get_viewport()
	get_window().content_scale_size = Vector2i.ZERO
	for dimensions in [Vector2i(640, 480), Vector2i(960, 720), Vector2i(1280, 720)]:
		get_window().size = dimensions
		viewport.size_changed.emit()
		await frames()
		var bounds := viewport.get_visible_rect()
		check(bounds.size == Vector2(dimensions), "test actually resizes viewport %s" % dimensions)
		check(bounds.encloses(panel.get_global_rect()), "panel stays within resized viewport %s" % dimensions)
		var npc_panel: Control = main.get_node("HUD/Panel")
		check(not panel.get_global_rect().intersects(npc_panel.get_global_rect()), "domain panel preserves NPC output at %s" % dimensions)
		check(not panel.get_global_rect().intersects(hud.get_node("Global").get_global_rect()), "global controls remain separate from panel at %s" % dimensions)
		for name in ["Copy", "SelectAll", "Start", "Run", "Refocus", "Background", "Stop", "Status"]:
			var control := button(name)
			if not control.disabled:
				panel.get_node("Scroll").ensure_control_visible(control)
				await frames(1)
				check(bounds.encloses(control.get_global_rect()), "enabled native control reachable %s %s" % [name, dimensions])
				check(panel.get_node("Scroll").get_global_rect().encloses(control.get_global_rect()), "enabled control fully visible after scroll %s %s" % [name, dimensions])
				if name == "Copy": await preload("res://tests/chat_clipboard_checks.gd").snapshot(self, "domain-" + str(dimensions))

func finish() -> void:
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	BridgeClient._socket.close()
	if peer != null: peer.close()
	server.stop()
	# Remove the physical body while HUD listeners still exist, so production
	# Area2D exits finish before scene-tree teardown destroys their viewport.
	if is_instance_valid(player):
		player.queue_free()
		await frames(3)
	for message in failures: printerr("FAIL: " + message)
	if failures.is_empty(): print("domain_panel_test: OK — %d checks passed." % checks)
	else: printerr("domain_panel_test: %d failures / %d checks." % [failures.size(), checks])
	get_tree().quit(0 if failures.is_empty() else 1)


func unconfigured_hud_checks() -> void:
	var clipboard = preload("res://tests/chat_clipboard_checks.gd")
	var selector: OptionButton = hud.get_node("Global/Toolbar/DomainSelect")
	selector.item_selected.emit(0)
	hud._open_remote()
	await frames()
	results.select_all()
	await clipboard.reveal_control(self, results)
	await clipboard.mouse(self, results.get_global_rect().position + Vector2(30, 12), MOUSE_BUTTON_RIGHT)
	var menu: PopupMenu = results.get_node("TranscriptClipboard/ClipboardMenu")
	check(menu.visible, "clipboard: popup open before actual project unconfiguration")
	DisplayServer.clipboard_set("project scope sentinel")
	unconfigured = true
	BridgeClient.describe_workspace()
	await frames(20)
	check(not menu.visible and results.get_selection_from() == -1, "clipboard: actual project change invalidates popup and selection")
	menu.id_pressed.emit(0)
	await clipboard.checkpoint(self, "project-unconfigured", "project scope sentinel")
	check(not panel.visible and hud.selected_domain_id == "" and hud.anchor_agent_id == "" and hud._domains.is_empty(), "final R3 authoritative unconfigured discovery clears HUD selection and anchors")
	check(input.text == "" and results.text == "" and hud.get_node("Global/StatusLabel").text.contains("unconfigured"), "final R3 HUD clears prior project text and shows unconfigured state")

func clipboard_scope_checks() -> void:
	var clipboard = preload("res://tests/chat_clipboard_checks.gd")
	hud._open_remote()
	await frames()
	# A handoff closes the old surface synchronously before another domain may
	# own it. Simulate the same public selection action used by the toolbar.
	GameEvents.domain_changed.emit("engineering", "input", "")
	var selector: OptionButton = hud.get_node("Global/Toolbar/DomainSelect")
	await clipboard.stale_action(self, results, func(): selector.item_selected.emit(1), "domain selection change")
	selector.item_selected.emit(0)
	hud._open_remote()
	await frames()
	await clipboard.stale_action(self, results, func(): hud._background(), "domain close")
	hud._open_remote()
	await frames()
	BridgeClient.set_process(false)
	BridgeClient._connected = false
	GameEvents.domain_changed.emit("core", "connection", "")
	await frames()
	check(not button("Copy").disabled and button("Copy").is_visible_in_tree() and not input.editable, "clipboard: disconnected domain history remains copyable")
	results.deselect()
	await clipboard.click(self, button("Copy"))
	await clipboard.checkpoint(self, "disconnected-domain", results.text)
	BridgeClient._connected = true
	BridgeClient.set_process(true)
	GameEvents.domain_changed.emit("core", "connection", "")
	await frames()
