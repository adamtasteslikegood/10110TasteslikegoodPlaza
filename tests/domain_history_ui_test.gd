extends Node

var failures: Array[String] = []
var checks := 0
var server := TCPServer.new()
var peer: WebSocketPeer
var commands: Array[Dictionary] = []
var main: Node
var ended_only := false
var capabilities_version: Variant = 2
var last_character_reply: Dictionary = {}
var storage_error: Variant = null
var backend := "sqlite"

func check(ok: bool, message: String) -> void:
	checks += 1
	if not ok: failures.append(message)

func state(id: String) -> Dictionary:
	return {"type": "domain_state", "protocol_version": 2, "request_id": id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": null if ended_only else "A", "execution_id": null if ended_only else "E-B", "domain_revision": "3", "state": "inactive" if ended_only else "active", "execution_state": "idle", "state_store": {"backend": backend, "continuity_id": "00000000-0000-4000-8000-000000000001" if backend == "sqlite" else "00000000-0000-4000-8000-000000000002", "durable": backend == "sqlite", "continuity": "project" if backend == "sqlite" else "process", "error_type": storage_error}, "saved_sessions": [{"domain_session_id": "C", "created_at": "1", "ended_at": "2", "ended_by": "user", "high_water_mark": "1"}, {"domain_session_id": "A", "created_at": "3", "ended_at": "4" if ended_only else null, "ended_by": "user" if ended_only else null, "high_water_mark": "1"}]}

func workspace(id: String) -> Dictionary:
	return {"type": "workspace_state", "protocol_version": 2, "request_id": id, "project_id": "P", "workspace_id": "W", "stage": "ready", "reason": null, "architect_decision": null, "project_path": "/project", "worktree_path": "/work", "branch": "work", "changed_files": null, "reservation": null, "memory": {"path": "/notes", "status": "saved", "revision": 1, "error_type": null}, "state_store": state("").state_store}

func terminal(session: String, id: String = "saved") -> Dictionary:
	return {"type": "domain_result", "protocol_version": 2, "request_id": id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": session, "execution_id": "E-A", "output_id": "1", "agent_id": "systems-architect", "task": "saved task", "output": "History " + session + " ibis", "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": true, "revision": 1, "error_type": null}}

func frames(n: int = 8) -> void:
	for _i in n:
		if peer == null and server.is_connection_available():
			peer = WebSocketPeer.new()
			peer.accept_stream(server.take_connection())
		if peer != null:
			peer.poll()
			while peer.get_available_packet_count() > 0:
				var p: Dictionary = JSON.parse_string(peer.get_packet().get_string_from_utf8())
				commands.append(p)
				var reply := state(p.request_id)
				if p.type == "describe_workspace": reply = workspace(p.request_id)
				elif p.type == "agent_status": reply = {"type": "agent_status", "request_id": p.request_id, "agent_id": p.agent_id, "execution_kind": "working", "domain_id": "core", "project": workspace(""), "workspace": {"stage": "ready"}, "domain_state": reply, "capabilities": {"protocol_version": capabilities_version, "state_store": state("").state_store, "can_start": ended_only, "can_run": not ended_only, "can_prepare_project": false}}
				elif p.type == "resume":
					peer.send_text(JSON.stringify(terminal(p.domain_session_id)))
					reply.merge({"type": "resume_complete", "domain_session_id": p.domain_session_id, "execution_id": null, "state": "inactive", "ended": ended_only or p.domain_session_id == "C", "high_water_mark": "1", "earliest_output_id": "1", "history_gap": false}, true)
				elif p.type == "end_domain_session": reply.merge({"type": "domain_error", "status": "error", "error_type": "state_store_failed", "message": "End could not be saved"}, true)
				if p.type == "agent_status": last_character_reply = reply.duplicate(true)
				peer.send_text(JSON.stringify(reply))
		await get_tree().process_frame

func _ready() -> void:
	get_tree().create_timer(20).timeout.connect(func(): check(false, "history UI watchdog"); finish())
	main = load("res://scenes/main.tscn").instantiate()
	add_child(main)
	BridgeClient._socket.close()
	BridgeClient._socket = WebSocketPeer.new()
	BridgeClient._connected = false
	BridgeClient._reconnect_timer.stop()
	server.listen(0, "127.0.0.1")
	BridgeClient.bridge_url = "ws://127.0.0.1:%d" % server.get_local_port()
	BridgeClient._attempt_connect()
	await frames(50)
	GameEvents.npc_approached.emit("systems-architect", AgentRegistry.get_agent("systems-architect"))
	await frames(40)
	var dialogue: Node = main.get_node("HUD")
	var pane: Node = main.get_node("DomainHUD")
	var body: RichTextLabel = dialogue.get_node("Panel/Margin/Rows/BodyLabel")
	check(body.get_parsed_text().contains("History A ibis"), "fresh working dialogue discovers saved open history")
	check(commands.filter(func(p): return p.type in ["activate_domain", "domain_query"]).is_empty(), "approach/discovery/replay never Start or Run")
	check(dialogue.has_node("Panel/Margin/Rows/Actions/End") and pane.has_node("Panel/Scroll/Rows/Actions/End"), "both surfaces have separate End")
	check(dialogue.has_node("Panel/Margin/Rows/HistorySelect") and pane.has_node("Panel/Scroll/Rows/HistorySelect"), "both surfaces have saved history selector")
	if not dialogue.has_node("Panel/Margin/Rows/Actions/End"):
		finish()
		return
	BridgeClient.set_domain_draft("core", "preserve failed End draft")
	dialogue.get_node("Panel/Margin/Rows/Actions/End").pressed.emit()
	await frames(30)
	check(BridgeClient.domain_snapshot("core").draft == "preserve failed End draft" and body.get_parsed_text().contains("History A ibis"), "failed End preserves draft and history")
	var history: OptionButton = dialogue.get_node("Panel/Margin/Rows/HistorySelect")
	history.item_selected.emit(0)
	await frames(25)
	check(BridgeClient.domain_snapshot("core").selected_session_id == "C" and body.get_parsed_text().contains("History C ibis"), "older ended history selectable in working dialogue")
	check(dialogue.get_node("Panel/Margin/Rows/Actions/Send").disabled and dialogue.get_node("Panel/Margin/Rows/Actions/End").disabled, "selected ended history cannot Run or End current app")
	pane._open_remote()
	await frames(20)
	check(pane.get_node("Panel/Scroll/Rows/ResultsLabel").text.contains("History C ibis") and pane.get_node("Panel/Scroll/Rows/Actions/Run").disabled and pane.get_node("Panel/Scroll/Rows/Actions/End").disabled, "domain pane shares read-only history selection")
	pane.get_node("Global/Toolbar/StopButton").pressed.emit()
	await frames()
	var stop: Dictionary = commands.filter(func(p): return p.type == "deactivate_domain").back()
	check(stop.domain_session_id == "A" and stop.execution_id == "E-B", "global Stop explicitly targets current work while old history selected")
	BridgeClient.select_domain_session("core", "A")
	await frames(20)
	var unsaved := terminal("A", "unsaved")
	unsaved.execution_id = "E-B"
	unsaved.erase("output_id")
	unsaved.committed = false
	unsaved.output = "Unsaved answer auk"
	unsaved.status = "error"
	unsaved.reason = "state_store_failed"
	unsaved.memory = null
	peer.send_text(JSON.stringify(unsaved))
	await frames(20)
	check(pane.get_node("Panel/Scroll/Rows/ResultsLabel").text.contains("Unsaved answer auk") and pane.get_node("Panel/Scroll/Rows/ResultsLabel").text.contains("UNSAVED"), "uncommitted answer explicitly labeled in domain pane")
	GameEvents.npc_approached.emit("systems-architect", AgentRegistry.get_agent("systems-architect"))
	await frames(20)
	check(body.get_parsed_text().contains("Unsaved answer auk") and body.get_parsed_text().contains("UNSAVED"), "uncommitted answer explicitly labeled in dialogue")
	storage_error = "state_store_uncertain"
	BridgeClient.domain_status("core")
	await frames(25)
	for label in [body, pane.get_node("Panel/Scroll/Rows/ResultsLabel")]:
		check(label.get_parsed_text().contains("Application persistence fault") and label.get_parsed_text().contains("reconcile storage"), "both surfaces expose storage fault independently of ready project")
	check(dialogue.get_node("Panel/Margin/Rows/Actions/Send").disabled and pane.get_node("Panel/Scroll/Rows/Actions/Run").disabled, "storage fault closes both Run controls")
	backend = "memory"
	storage_error = null
	BridgeClient.domain_status("core")
	await frames(25)
	check(body.get_parsed_text().contains("Memory backend") and pane.get_node("Panel/Scroll/Rows/ResultsLabel").text.contains("history lasts only"), "both surfaces explain memory backend discontinuity")
	capabilities_version = "2"
	BridgeClient.agent_status("systems-architect")
	await frames(20)
	check(BridgeClient.character_snapshot("systems-architect").get("pending") == "agent_status", "malformed capability version cannot settle authoritative negotiation")
	last_character_reply.capabilities.protocol_version = 2
	peer.send_text(JSON.stringify(last_character_reply))
	await frames(15)
	check(BridgeClient.character_snapshot("systems-architect").get("pending") == "", "valid v2 capability negotiation settles")
	finish()

func finish() -> void:
	BridgeClient.set_process(false)
	BridgeClient._socket.close()
	if peer != null: peer.close()
	server.stop()
	if failures.is_empty(): print("domain_history_ui_test: OK — %d checks passed." % checks)
	else:
		for failure in failures: printerr("FAIL: " + failure)
	get_tree().quit(0 if failures.is_empty() else 1)
