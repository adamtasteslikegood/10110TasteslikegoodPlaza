extends Node

func until(predicate: Callable) -> bool:
	var deadline := Time.get_ticks_msec() + 10000
	while Time.get_ticks_msec() < deadline:
		if predicate.call(): return true
		await get_tree().process_frame
	return false

func _ready() -> void:
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	BridgeClient._socket.close()
	BridgeClient._socket = WebSocketPeer.new()
	BridgeClient._connected = false
	BridgeClient.bridge_url = OS.get_environment("PLAZA_TEST_BRIDGE_URL")
	var main: Node = load("res://scenes/main.tscn").instantiate()
	add_child(main)
	BridgeClient.set_process(true)
	BridgeClient._attempt_connect()
	if not await until(func(): return BridgeClient.is_bridge_connected()):
		printerr("fresh history bridge connection timed out")
		get_tree().quit(1)
		return
	if OS.get_environment("PLAZA_HISTORY_STATUS_FIRST") == "1":
		if not await until(func(): return not BridgeClient.workspace_snapshot().get("project_id", "").is_empty()):
			get_tree().quit(1)
			return
		BridgeClient.domain_status("core")
		if not await until(func(): return not BridgeClient.domain_snapshot("core").get("saved_sessions", []).is_empty()):
			printerr("status-first catalog timed out")
			get_tree().quit(1)
			return
	GameEvents.npc_approached.emit("systems-architect", AgentRegistry.get_agent("systems-architect"))
	if not await until(func(): return BridgeClient.domain_snapshot("core").get("selected_received_cursor") == "1" and BridgeClient.domain_snapshot("core").get("pending_control", {}).is_empty()):
		printerr("fresh process history replay timed out: ", BridgeClient.domain_snapshot("core"))
		get_tree().quit(1)
		return
	var hud: Node = main.get_node("HUD")
	var body: RichTextLabel = hud.get_node("Panel/Margin/Rows/BodyLabel")
	var expected := OS.get_environment("PLAZA_HISTORY_EXPECTED")
	if expected.is_empty(): expected = "Readback from prior notes: isolated"
	if not await until(func(): return body.get_parsed_text().contains(expected)):
		printerr("saved answer not rendered: ", body.get_parsed_text())
		get_tree().quit(1)
		return
	var snapshot := BridgeClient.domain_snapshot("core")
	var saved := BridgeClient.domains.selected_results("core")
	var pane: Node = main.get_node("DomainHUD")
	pane._open_remote()
	var pane_body: RichTextLabel = pane.get_node("Panel/Scroll/Rows/ResultsLabel")
	if not await until(func(): return pane_body.get_parsed_text().contains(expected)):
		printerr("saved answer not rendered in domain pane: ", pane_body.get_parsed_text())
		get_tree().quit(1)
		return
	print("HISTORY_REOPEN ", JSON.stringify({"project_id": snapshot.project_id, "domain_session_id": snapshot.domain_session_id, "selected_session_id": snapshot.selected_session_id, "execution_id": snapshot.execution_id, "state": snapshot.state, "read_only": snapshot.read_only, "received_cursor": snapshot.received_cursor, "selected_received_cursor": snapshot.selected_received_cursor, "output_ids": saved.map(func(p): return p.output_id), "result_executions": saved.map(func(p): return p.execution_id), "results": saved, "answer": body.get_parsed_text(), "pane_answer": pane_body.get_parsed_text(), "start_disabled": hud.get_node("Panel/Margin/Rows/Actions/Start").disabled, "pane_start_disabled": pane.get_node("Panel/Scroll/Rows/Actions/Start").disabled, "pane_run_disabled": pane.get_node("Panel/Scroll/Rows/Actions/Run").disabled, "run_disabled": hud.get_node("Panel/Margin/Rows/Actions/Send").disabled, "end_disabled": hud.get_node("Panel/Margin/Rows/Actions/End").disabled, "focus": get_viewport().gui_get_focus_owner() != null}))
	BridgeClient.set_process(false)
	BridgeClient._socket.close()
	get_tree().quit()
