extends Node

var control := ""
var main: Node

func until(predicate: Callable, timeout: int = 12000) -> bool:
	var deadline := Time.get_ticks_msec() + timeout
	while Time.get_ticks_msec() < deadline:
		if predicate.call(): return true
		await get_tree().process_frame
	return false

func write_receipt(name: String, value: Dictionary) -> void:
	var path := control.path_join(name + ".json")
	var temporary := path + ".tmp"
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	file.store_string(JSON.stringify(value))
	file.close()
	DirAccess.rename_absolute(temporary, path)

func _ready() -> void:
	control = OS.get_environment("PLAZA_CONTINUITY_CONTROL")
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	BridgeClient._socket.close()
	BridgeClient._connected = false
	main = load("res://scenes/main.tscn").instantiate()
	add_child(main)
	for sequence in range(1, 5):
		var path := control.path_join("step-%d.json" % sequence)
		if not await until(func(): return FileAccess.file_exists(path)):
			fail("missing next continuity step")
			return
		var step: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
		if BridgeClient._connected: BridgeClient._on_connection_closed()
		BridgeClient._reconnect_timer.stop()
		BridgeClient._socket.close()
		BridgeClient._socket = WebSocketPeer.new()
		BridgeClient.bridge_url = step.url
		BridgeClient.set_process(true)
		BridgeClient._attempt_connect()
		if not await until(func(): return BridgeClient.is_bridge_connected()):
			fail("kept client reconnect failed")
			return
		GameEvents.npc_approached.emit("systems-architect", AgentRegistry.get_agent("systems-architect"))
		var observed := await until(func():
			var snapshot := BridgeClient.domain_snapshot("core")
			return snapshot.get("domain_revision") == step.revision and snapshot.get("domain_session_id") == step.application and snapshot.get("state_store", {}).get("continuity_id") == step.continuity_id and snapshot.get("selected_received_cursor") == step.cursor and snapshot.get("pending_control", {}).is_empty() and BridgeClient._discovery_request == "")
		if not observed:
			fail("continuity step %d failed: %s" % [sequence, BridgeClient.domain_snapshot("core")])
			return
		var snapshot := BridgeClient.domain_snapshot("core")
		var hud: Node = main.get_node("HUD")
		write_receipt("observed-%d" % sequence, {"snapshot": snapshot, "start_enabled": not hud.get_node("Panel/Margin/Rows/Actions/Start").disabled, "focus": get_viewport().gui_get_focus_owner() != null})
		if sequence == 1:
			var unsaved: Dictionary = snapshot.results[0].duplicate(true)
			unsaved.erase("output_id")
			unsaved.committed = false
			unsaved.request_id = "client-unsaved"
			unsaved.output = "unsaved continuity text"
			BridgeClient._on_domain_packet(unsaved)
		if sequence == 4:
			if not await until(func(): return FileAccess.file_exists(control.path_join("explicit-start"))):
				fail("explicit Start barrier missing")
				return
			hud.get_node("Panel/Margin/Rows/Actions/Start").pressed.emit()
			if not await until(func(): return BridgeClient.domain_snapshot("core").get("state") == "active" and BridgeClient.domain_snapshot("core").get("pending_control", {}).is_empty()):
				fail("explicit Start after discontinuity failed")
				return
			write_receipt("started", BridgeClient.domain_snapshot("core"))
	BridgeClient.set_process(false)
	BridgeClient._socket.close()
	print("godot_history_continuity: OK")
	get_tree().quit()

func fail(message: String) -> void:
	printerr(message)
	get_tree().quit(1)
