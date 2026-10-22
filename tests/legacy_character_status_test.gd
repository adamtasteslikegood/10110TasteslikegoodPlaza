extends Node

## Consume real Python agent_status output through the production receive/store/UI path.
func _ready() -> void:
	var fixture: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(OS.get_environment("PLAZA_LEGACY_STATUS_FIXTURE")))
	var packet: Dictionary = fixture.packet
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	BridgeClient._socket.close()
	BridgeClient._connected = true
	var main: Node = load("res://scenes/main.tscn").instantiate()
	add_child(main)
	# Reserve discovery while injecting the correlated server observation. Approach
	# may queue its next read, but must never send Start or Run on its own.
	BridgeClient._discovery_request = "held-observation"
	BridgeClient._character_requests[packet.request_id] = {"type": "agent_status", "agent_id": packet.agent_id, "fence": BridgeClient.domains.observation_fence()}
	BridgeClient._on_character_packet(packet)
	BridgeClient._discovery_request = "held-observation"
	GameEvents.npc_approached.emit(packet.agent_id, AgentRegistry.get_agent(packet.agent_id))
	var hud: Node = main.get_node("HUD")
	var pane: Node = main.get_node("DomainHUD")
	var expected: bool = fixture.can_start
	var primary: Button = hud.get_node("Panel/Margin/Rows/Actions/Start")
	var ok: bool = primary.disabled == not expected and hud.get_node("Panel").visible
	pane.get_node("Global/Toolbar/NearbyDomainButton").pressed.emit()
	var secondary: Button = pane.get_node("Panel/Scroll/Rows/Actions/Start")
	ok = ok and secondary.disabled == not expected and pane.get_node("Panel").visible
	ok = ok and BridgeClient._domain_requests.is_empty()
	if ok: print("legacy_character_status_test: OK — both Start controls reflect real server eligibility")
	else: printerr("FAIL: legacy status must reach both Start controls without executing")
	get_tree().quit(0 if ok else 1)
