extends Node

## Driven by test_godot_conversation_integration.py; no synthetic response packets.
const A := "systems-architect"
const B := "security-auditor"
var failures: Array[String] = []
var checks := 0
var hud: Node
var body: RichTextLabel
var composer: LineEdit
var replies: Array[Dictionary] = []
var errors: Array[Dictionary] = []

func _ready() -> void:
	get_tree().create_timer(20.0).timeout.connect(func():
		check(false, "integration watchdog expired")
		finish()
	)
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	BridgeClient._socket.close()
	BridgeClient._socket = WebSocketPeer.new()
	BridgeClient._connected = false
	BridgeClient.conversations = ConversationStore.new(AgentRegistry.has_agent, 8, 512)
	BridgeClient.bridge_url = OS.get_environment("PLAZA_TEST_BRIDGE_URL")
	if not check(not BridgeClient.bridge_url.is_empty(), "Python runner supplies ephemeral bridge URL"):
		finish()
		return
	var script = load("res://scenes/hud/dialogue_panel.gd")
	if not check(script != null and script.can_instantiate(), "production HUD script loads"):
		finish()
		return
	var scene = load("res://scenes/hud/dialogue_panel.tscn")
	if not check(scene != null and scene.can_instantiate(), "production HUD scene loads"):
		finish()
		return
	hud = scene.instantiate()
	add_child(hud)
	body = hud.get_node("Panel/Margin/Rows/BodyLabel")
	composer = hud.get_node("Panel/Margin/Rows/InputRow/QuestionInput")
	GameEvents.agent_response_received.connect(func(agent, output): replies.append({"agent": agent, "output": output}))
	GameEvents.agent_query_failed.connect(func(agent, kind, message): errors.append({"agent": agent, "kind": kind, "message": message}))
	BridgeClient.set_process(true)
	BridgeClient._attempt_connect()
	if not await until(func(): return BridgeClient.is_bridge_connected()):
		finish()
		return
	check(BridgeClient.conversations.generation == 1, "real connection starts first generation")
	approach(A)
	var a := submit("delayed A 雪")
	check(not a.is_empty() and not composer.editable, "real panel admits A and disables its composer")
	approach(B)
	var b := submit("fail B")
	check(not b.is_empty() and a != b, "B receives a distinct correlated request ID")
	check(BridgeClient._pending_requests.size() == 2, "serial bridge retains both per-agent pending requests")
	check(BridgeClient.send_query(A, "duplicate") == "", "second outstanding A request is rejected")
	check(BridgeClient._pending_requests.size() == 2, "busy rejection preserves both requests")
	# Busy rejection is expected; count only subsequent terminal failures.
	errors.clear()
	progress("queued")
	if not await until(func(): return replies.size() == 1 and errors.size() == 1):
		finish()
		return
	check(replies[0] == {"agent": A, "output": "late A success 雪"}, "late success is attributed to hidden A")
	check(errors[0].agent == B and errors[0].message == "B independent failure", "Python provider failure belongs to B")
	check(not body.text.contains("late A success") and body.text.contains("B independent failure"), "B rendered transcript excludes hidden A reply")
	check(composer.editable and BridgeClient._pending_requests.is_empty(), "matching terminals settle map and composer")
	approach(A)
	var span: Dictionary = hud.current_assistant_span()
	check(body.text.substr(span.start, span.length) == "late A success 雪", "actual assistant span restores A reply")
	check(body.text.contains("delayed A 雪") and body.visible_characters == -1, "restored A transcript is immediate")
	approach(B)
	composer.text = "archived draft 雪"
	composer.text_changed.emit(composer.text)
	approach(A)
	var pending := submit("disconnect pending")
	check(not pending.is_empty(), "second A request traverses real bridge")
	progress("disconnect")
	if not await until(func(): return not BridgeClient.is_bridge_connected()):
		finish()
		return
	check(errors.size() == 2 and errors[1].agent == A and errors[1].kind == "connection", "disconnect fails pending A exactly once")
	check(BridgeClient._pending_requests.is_empty(), "disconnect clears pending map")
	check(body.text.contains("Archived") and not composer.editable, "disconnected generation is visibly read-only")
	approach(B)
	check(body.text.contains("archived draft 雪") and not composer.editable, "unsent B draft is archived visibly")
	if not await until(func(): return BridgeClient.is_bridge_connected()):
		finish()
		return
	check(BridgeClient.conversations.generation == 2, "actual reconnect advances generation")
	check(body.text.contains("context restarted") and composer.text.is_empty() and composer.editable, "reconnect marks fresh context with blank editable draft")
	check(BridgeClient.conversation_snapshot(B).messages.back().role == "draft", "archived B draft remains display-only")
	approach(A)
	check(body.text.contains("Connection lost") and body.text.contains("context restarted"), "old A failure and fresh boundary remain visible")
	check(BridgeClient.set_draft(A, "雪".repeat(1000)) == false, "oversized Unicode draft rejected within tiny display budget")
	check(BridgeClient.conversation_snapshot(A).draft.is_empty(), "rejected draft is not retained")
	var fresh := submit("fresh context")
	check(not fresh.is_empty() and fresh != pending, "fresh request has unique generation ID")
	if not await until(func(): return replies.size() == 2):
		finish()
		return
	var snapshot: Dictionary = BridgeClient.conversation_snapshot(A)
	check(snapshot.pending.is_empty() and BridgeClient._pending_requests.is_empty(), "fresh response settles only current request")
	check(replies[1].output.to_utf8_buffer().size() > 3000, "full provider response reaches live notification unchanged")
	check(snapshot.messages.back().truncated and snapshot.messages.back().content.ends_with("[truncated]"), "display reply shortens Unicode with explicit marker")
	span = hud.current_assistant_span()
	check(body.text.substr(span.start, span.length) == snapshot.messages.back().content, "real HUD assistant span equals bounded stored reply")
	check(body.visible_characters == span.start, "new visible assistant reply begins progressive reveal")
	check(not body.text.contains("must never enter fresh thread"), "disconnected late completion cannot pollute fresh display")
	for agent in [A, B]:
		var state: Dictionary = BridgeClient.conversation_snapshot(agent)
		check(state.content_bytes <= 512 and state.message_count <= 8, "aggregate archived/draft/failure/content limits hold for " + agent)
	finish()

func approach(agent: String) -> void:
	GameEvents.npc_approached.emit(agent, AgentRegistry.get_agent(agent))

func submit(text: String) -> String:
	composer.text = text
	composer.text_changed.emit(text)
	composer.text_submitted.emit(text)
	return str(BridgeClient.conversation_snapshot(hud._current_agent_id).pending.get("request_id", ""))

func progress(value: String) -> void:
	var file := FileAccess.open(OS.get_environment("PLAZA_TEST_PROGRESS"), FileAccess.WRITE)
	file.store_string(value)
	file.close()

func until(predicate: Callable) -> bool:
	var deadline := Time.get_ticks_msec() + 6000
	while Time.get_ticks_msec() < deadline:
		if predicate.call():
			return true
		await get_tree().process_frame
	return check(false, "real bridge transition reached before deadline")

func check(ok: bool, message: String) -> bool:
	checks += 1
	if not ok:
		failures.append(message)
	return ok

func finish() -> void:
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	BridgeClient._socket.close()
	for failure in failures:
		printerr("FAIL: " + failure)
	if failures.is_empty():
		print("godot_bridge_integration: OK — %d checks passed." % checks)
	else:
		printerr("godot_bridge_integration: %d failures / %d checks." % [failures.size(), checks])
	get_tree().quit(0 if failures.is_empty() else 1)
