extends Node

## No synthetic signals, responses, terminals or store writes. Python observes
## immutable stage files and acknowledges them after independent bridge checks.
var main: Node2D
var player: CharacterBody2D
var hud: CanvasLayer
var panel: Control
var npc_hud: CanvasLayer
var composer: LineEdit
var results: RichTextLabel
var commands: Dictionary = {}
var acknowledgments: Array[Dictionary] = []
var seq := 0
var checks := 0
var failures: Array[String] = []
var generation := ""
var run_request := ""
var finished := false
var control := ""
var run_id := ""
var live_mode := false
var wait_msec := 12000

func _ready() -> void:
	live_mode = OS.get_environment("PLAZA_M12_LIVE") == "1"
	if live_mode: wait_msec = 100000
	get_tree().create_timer(400 if live_mode else 60).timeout.connect(func():
		check(false, "physical integration watchdog")
		finish())
	control = OS.get_environment("PLAZA_M12_CONTROL")
	run_id = OS.get_environment("PLAZA_M12_RUN_ID")
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	BridgeClient._socket.close()
	BridgeClient._socket = WebSocketPeer.new()
	BridgeClient._connected = false
	BridgeClient.bridge_url = OS.get_environment("PLAZA_TEST_BRIDGE_URL")
	main = load("res://scenes/main.tscn").instantiate()
	add_child(main)
	player = main.get_node("Player")
	hud = main.get_node("DomainHUD")
	panel = hud.get_node("Panel")
	npc_hud = main.get_node("HUD")
	composer = npc_hud.get_node("Panel/Margin/Rows/InputRow/QuestionInput")
	results = hud.get_node("Panel/Scroll/Rows/ResultsLabel")
	GameEvents.domain_changed.connect(observe_domain)
	# A real registered engineering role, added only to this fixture scene.
	var engineer: CharacterBody2D = load("res://scenes/npc/agent_npc.tscn").instantiate()
	engineer.agent_id = "backend-architect"
	engineer.position = Vector2(1100, 180)
	main.get_node("Office").add_child(engineer)
	check(AgentRegistry.get_agent("backend-architect").get("dept") == "engineering", "fixture uses real registered distinct engineering domain")
	check(AgentRegistry.get_agent("systems-architect").get("dept") == "core" and AgentRegistry.get_agent("security-auditor").get("dept") == "core", "production taxonomy preserved")
	BridgeClient.set_process(true)
	BridgeClient._attempt_connect()
	if not await until(func(): return BridgeClient.is_bridge_connected() and BridgeClient.workspace_snapshot().get("stage") == "needs_architect"):
		await finish()
		return
	var security: Node2D = main.get_node("Office/SecurityAuditor")
	# Initial fixture placement is outside every anchor. All observed entries,
	# departures and returns below move the actual body with collision checks.
	player.position = Vector2(1025, 420)
	await physics()
	await walk(Vector2(0, -92))
	check(security.get_node("Proximity").overlaps_body(player), "physical ordinary NPC approach")
	var referral := await npc_submit("help prepare configured project", "security-auditor")
	check(referral.assistant.contains("Chief Architect"), "current rendered referral")
	await stage("referral_rendered", referral)
	await key(KEY_ESCAPE)
	await walk(Vector2(-125, -25))
	await walk(Vector2(0, -90))
	check(main.get_node("Office/SystemsArchitect/Proximity").overlaps_body(player), "actual player reaches Chief")
	check(BridgeClient.workspace_snapshot().get("stage") == "needs_architect", "Chief proximity alone never reviews")
	var chief := await npc_submit("review configured project", "systems-architect")
	check(chief.assistant.contains("approved"), "rendered Chief approval")
	BridgeClient.describe_workspace()
	if not await until(func(): return BridgeClient.workspace_snapshot().get("stage") == "ready"):
		await finish()
		return
	var ready := project_identity()
	ready.merge({"request_id": chief.request_id, "assistant": chief.assistant})
	await stage("chief_ready", ready)
	await key(KEY_ESCAPE)
	await walk(Vector2(0, 90))
	await walk(Vector2(200, 0))
	await walk(Vector2(0, -90))
	var area: Area2D = engineer.get_node("Proximity")
	check(area.overlaps_body(player), "actual engineering anchor entry")
	await click(hud.get_node("Global/Toolbar/NearbyDomainButton"))
	check(panel.visible and hud.selected_domain_id == "engineering", "native engineering opener")
	await click(action("Start"))
	if not await until(func(): return BridgeClient.domain_snapshot("engineering").get("state") == "active"):
		await finish()
		return
	generation = BridgeClient.domain_snapshot("engineering").domain_session_id
	var task_input: LineEdit = hud.get_node("Panel/Scroll/Rows/TaskInput")
	task_input.text = FileAccess.get_file_as_string(control.path_join("task.txt")) if live_mode else "execute integration sentinel"
	if live_mode: check(not task_input.text.is_empty(), "execution task supplied")
	task_input.text_changed.emit(task_input.text)
	task_input.grab_focus()
	await key(KEY_ENTER)
	if not await until(func(): return not latest("domain_query").is_empty() and has_ack("domain_accepted", latest("domain_query").get("request_id", ""))):
		await finish()
		return
	run_request = latest("domain_query").request_id
	check(count("activate_domain") == 1 and count("domain_query") == 1, "native Start and Enter submit exactly once")
	var running := domain_identity()
	running.merge({"request_id": run_request, "agent_id": "backend-architect"})
	await stage("domain_running", running)
	await key(KEY_ESCAPE)
	await walk(Vector2(0, 90))
	if not await until(func(): return has_ack("domain_state", latest("background_domain").get("request_id", ""))):
		await finish()
		return
	var radius: float = area.get_node("ProximityShape").shape.radius
	var distance := player.global_position.distance_to(engineer.global_position)
	check(not area.overlaps_body(player) and distance > radius and not panel.visible, "physical departure beyond actual radius closes panel")
	var background := domain_identity()
	background.merge({"request_id": latest("background_domain").request_id, "state": "background", "execution_state": BridgeClient.domain_snapshot("engineering").execution_state, "radius": radius, "distance": distance, "panel_hidden": not panel.visible})
	await stage("background_ack", background)
	await walk(Vector2(-75, 25))
	check(security.get_node("Proximity").overlaps_body(player), "actual unrelated core NPC entry while engineering runs")
	var unrelated := await npc_submit("unrelated core conversation", "security-auditor")
	var npc_payload := domain_identity()
	npc_payload.merge(unrelated)
	npc_payload.execution_state = BridgeClient.domain_snapshot("engineering").execution_state
	if live_mode:
		check(not unrelated.assistant.is_empty(), "live separate current NPC assistant span")
	else:
		check(unrelated.assistant == "unrelated core NPC reply gull" and not unrelated.assistant.contains("ibis"), "separate current NPC assistant span")
	await stage("npc_rendered", npc_payload)
	await key(KEY_ESCAPE)
	if not await until(func(): return has_ack("domain_result", run_request)):
		await finish()
		return
	check(not panel.visible and current_assistant() == unrelated.assistant, "hidden domain completion preserves NPC output and focus")
	await walk(Vector2(75, -25))
	await walk(Vector2(0, -90))
	if not await until(func(): return has_ack("resume_complete", latest("resume").get("request_id", ""))):
		await finish()
		return
	var refocus := latest("refocus_domain")
	var resume := latest("resume")
	check(has_ack("domain_state", refocus.request_id), "exact Refocus ack precedes matching Resume completion")
	check(area.overlaps_body(player) and panel.visible, "physical return opens anchored domain results")
	var snapshot := BridgeClient.domain_snapshot("engineering")
	check(snapshot.results.size() == 1, "live push and replay deduplicate result identity")
	var terminal: Dictionary = snapshot.results[0]
	check(results.text.contains(terminal.output) and results.text.contains(generation) and results.text.contains(terminal.output_id), "actual result label renders full terminal identity and output")
	check(not results.text.contains(unrelated.assistant), "domain rendering excludes NPC history")
	var rendered_count := results.text.count("[%s · output %s ·" % [generation, terminal.output_id])
	check(rendered_count == 1, "actual rendered result appears exactly once")
	var npc_messages: Array = BridgeClient.conversation_snapshot("security-auditor").messages
	check(not JSON.stringify(npc_messages).contains("ibis") and not JSON.stringify(npc_messages).contains("execute integration sentinel"), "ordinary NPC history stays independent of engineering history")
	check(count("domain_query") == 1, "return replay never reexecutes")
	var rendered := domain_identity()
	rendered.merge({"request_id": resume.request_id, "refocus_request_id": refocus.request_id, "output_id": terminal.output_id, "output": terminal.output, "status": terminal.status, "rendered_text": results.text, "rendered_unique_results": rendered_count})
	await stage("domain_rendered", rendered)
	await click(action("Stop"))
	if not await until(func(): return has_ack("domain_state", latest("deactivate_domain").get("request_id", "")) and BridgeClient.domain_snapshot("engineering").get("state") == "inactive"):
		await finish()
		return
	var stopped := domain_identity()
	stopped.merge({"request_id": latest("deactivate_domain").request_id, "state": "inactive"})
	await stage("stop_ack", stopped)
	await finish()

func project_identity() -> Dictionary:
	var w := BridgeClient.workspace_snapshot()
	return {"project_id": w.project_id, "workspace_id": w.workspace_id}

func domain_identity() -> Dictionary:
	var out := project_identity()
	out.merge({"domain_id": "engineering", "domain_session_id": generation})
	return out

func observe_domain(domain: String, reason: String, request: String) -> void:
	if domain != "engineering": return
	var snapshot := BridgeClient.domain_snapshot(domain)
	if reason == "input":
		for pending in [snapshot.get("pending_control", {}), snapshot.get("pending_query", {})]:
			if pending.get("request_id") == request: commands[request] = pending.duplicate(true)
	elif reason in ["domain_state", "domain_accepted", "domain_result", "resume_complete"]:
		acknowledgments.append({"reason": reason, "request_id": request, "generation": snapshot.get("domain_session_id")})

func has_ack(reason: String, request: String) -> bool:
	if request.is_empty(): return false
	for ack in acknowledgments:
		if ack.reason == reason and ack.request_id == request and ack.generation == generation: return true
	return false

func count(kind: String) -> int:
	var found := 0
	for command in commands.values():
		if command.type == kind: found += 1
	return found

func latest(kind: String) -> Dictionary:
	var values := commands.values()
	for i in range(values.size() - 1, -1, -1):
		if values[i].type == kind: return values[i]
	return {}

func current_assistant() -> String:
	var span: Dictionary = npc_hud.current_assistant_span()
	return npc_hud.get_node("Panel/Margin/Rows/BodyLabel").text.substr(span.start, span.length)

func npc_submit(text: String, agent: String) -> Dictionary:
	composer.text = text
	composer.text_changed.emit(text)
	composer.grab_focus()
	await key(KEY_ENTER)
	await until(func(): return BridgeClient.conversation_snapshot(agent).get("pending", {}).is_empty() and not current_assistant().is_empty())
	var messages: Array = BridgeClient.conversation_snapshot(agent).messages
	var message: Dictionary = messages.back()
	check(message.role == "assistant" and current_assistant() == message.content, "current assistant span matches completed " + agent)
	return {"request_id": message.request_id, "agent_id": agent, "assistant": current_assistant()}

func stage(name: String, payload: Dictionary) -> void:
	seq += 1
	var path := control.path_join("%02d-%s.json" % [seq, name])
	var file := FileAccess.open(path + ".tmp", FileAccess.WRITE)
	file.store_string(JSON.stringify({"schema_version": 1, "run_id": run_id, "scenario": "a_initial", "producer": "godot", "seq": seq, "stage": name, "payload": payload}))
	file.close()
	check(DirAccess.rename_absolute(path + ".tmp", path) == OK, "atomic stage " + name)
	await until(func(): return FileAccess.file_exists(control.path_join("ack-%d" % seq)) and FileAccess.get_file_as_string(control.path_join("ack-%d" % seq)) == run_id)

func action(name: String) -> Button:
	return hud.get_node("Panel/Scroll/Rows/Actions/" + name)

func click(button: Control) -> void:
	if panel.is_ancestor_of(button):
		panel.get_node("Scroll").ensure_control_visible(button)
		await frames(3)
	for pressed in [true, false]:
		var event := InputEventMouseButton.new()
		event.button_index = MOUSE_BUTTON_LEFT
		event.position = button.get_global_rect().get_center()
		event.global_position = event.position
		event.pressed = pressed
		get_viewport().push_input(event, true)
	await frames(3)

func key(code: Key) -> void:
	for pressed in [true, false]:
		var event := InputEventKey.new()
		event.keycode = code
		event.physical_keycode = code
		event.pressed = pressed
		Input.parse_input_event(event)
		await frames(2)

func walk(delta: Vector2) -> void:
	for i in 12:
		player.move_and_collide(delta / 12.0)
		await get_tree().physics_frame
	await physics()
	await frames(3)

func physics() -> void:
	await get_tree().physics_frame
	await get_tree().physics_frame

func frames(n: int = 3) -> void:
	for i in n: await get_tree().process_frame

func until(predicate: Callable) -> bool:
	var deadline := Time.get_ticks_msec() + wait_msec
	while Time.get_ticks_msec() < deadline:
		if predicate.call(): return true
		await get_tree().process_frame
	return check(false, "required physical/native stage before deadline seq %d" % seq)

func check(ok: bool, message: String) -> bool:
	checks += 1
	if not ok: failures.append(message)
	return ok

func finish() -> void:
	if finished: return
	finished = true
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	BridgeClient._socket.close()
	if is_instance_valid(player):
		player.queue_free()
		await frames(3)
	for failure in failures: printerr("FAIL: " + failure)
	if failures.is_empty(): print("godot_domain_integration: OK — %d checks passed." % checks)
	else: printerr("godot_domain_integration: %d failures / %d checks." % [failures.size(), checks])
	get_tree().quit(0 if failures.is_empty() else 1)
