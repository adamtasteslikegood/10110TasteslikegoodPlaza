extends Node

## WebSocket transport plus session-only display conversations. The Python
## bridge sees opaque request IDs, never frontend state (D-005 / D-015).
const BRIDGE_URL := "ws://localhost:8765"
const RECONNECT_DELAY := 3.0
const DomainState := preload("res://scenes/bridge/domain_store.gd")
const Store := preload("res://scenes/bridge/conversation_store.gd")

@export var bridge_url := BRIDGE_URL

var conversations := Store.new(
	AgentRegistry.has_agent,
	int(ProjectSettings.get_setting("plaza/chat/history_max_messages", 200)),
	int(ProjectSettings.get_setting("plaza/chat/history_max_bytes", 1048576))
)
var domains := DomainState.new()
const Surface := preload("res://scenes/bridge/domain_surface.gd")
var surface := Surface.new(self)
var _character_requests: Dictionary = {}
var _characters: Dictionary = {}
var _character_queue: Array[String] = []
var _setup_request := ""
# Domain/discovery correlation never shares the NPC request map.
var _domain_requests: Dictionary = {}
var _discovery_request := ""
var _refresh_workspace := false
var _status_queue: Array[String] = []
var _resume_queue: Array[String] = []
var _recover_domains: Dictionary = {}
# A failed observation waits for explicit retry or a new connection.
var _failed_status_domains: Dictionary = {}
var _workspace_poll := 0.0
var _socket := WebSocketPeer.new()
var _connected := false
var _pending_requests: Dictionary = {}
var _session_id := Crypto.new().generate_random_bytes(16).hex_encode()
var _request_counter := 0
# Only known registry IDs enter this set; it is bounded by the agent directory.
var _conversation_agents: Dictionary = {}

@onready var _reconnect_timer := Timer.new()


func _ready() -> void:
	add_child(_reconnect_timer)
	_reconnect_timer.one_shot = true
	_reconnect_timer.timeout.connect(_attempt_connect)
	GameEvents.domain_changed.connect(surface.changed)
	_attempt_connect()


func _attempt_connect() -> void:
	if _socket.get_ready_state() != WebSocketPeer.STATE_CLOSED:
		return
	_reconnect_timer.stop()
	var err := _socket.connect_to_url(bridge_url)
	if err != OK:
		push_warning("ws_client: cannot initiate connection to %s" % bridge_url)
		_schedule_reconnect()


func _process(delta: float) -> void:
	_socket.poll()
	match _socket.get_ready_state():
		WebSocketPeer.STATE_OPEN:
			if not _connected:
				_connected = true
				_reconnect_timer.stop()
				conversations.begin_connection()
				_notify_connection()
				describe_workspace()
				for agent_id in _characters: agent_status(agent_id)
			while _socket.get_available_packet_count() > 0:
				_on_message(_socket.get_packet().get_string_from_utf8())
			_workspace_poll += delta
			if _workspace_poll >= 2.0:
				_workspace_poll = 0.0
				if workspace_snapshot().get("stage") in ["preparing", "reviewing", "initializing"]:
					describe_workspace()
		WebSocketPeer.STATE_CLOSED:
			if _connected:
				_on_connection_closed()
			_schedule_reconnect()


func _on_connection_closed() -> void:
	_connected = false
	_character_requests.clear()
	_character_queue.clear()
	_setup_request = ""
	surface.disconnected()
	for agent_id in _characters:
		_characters[agent_id].pending = ""
		_characters[agent_id].error = "Disconnected — refresh status to recover"
		GameEvents.character_changed.emit(agent_id, "connection", "")
	_failed_status_domains.clear()
	domains.disconnect_connection()
	_domain_requests.clear()
	_discovery_request = ""
	_refresh_workspace = false
	_status_queue.clear()
	_resume_queue.clear()
	for domain_id in domains.domain_ids():
		_recover_domains[domain_id] = true
		GameEvents.domain_changed.emit(domain_id, "connection", "")
	GameEvents.workspace_changed.emit("connection", "")
	var pending := _pending_requests.duplicate(true)
	conversations.disconnect_connection("Connection lost during query")
	_pending_requests.clear()
	# Every affected snapshot and map entry is settled before any listener runs.
	for request_id in pending:
		var agent_id: String = pending[request_id].agent_id
		GameEvents.conversation_changed.emit(agent_id, "failure", request_id)
		GameEvents.agent_query_failed.emit(agent_id, "connection", "Connection lost during query")
	_notify_connection()


func _notify_connection() -> void:
	for agent_id in _conversation_agents.keys():
		GameEvents.conversation_changed.emit(agent_id, "connection", "")


func _schedule_reconnect() -> void:
	if _reconnect_timer.is_stopped():
		_reconnect_timer.start(RECONNECT_DELAY)


## Returns an admitted ID even if transport subsequently fails synchronously.
## Empty means rejection: no pending request or display input was admitted.
func send_query(agent_id: String, task: String) -> String:
	if not AgentRegistry.has_agent(agent_id) or task.strip_edges().is_empty():
		_reject(agent_id, "input", "Choose a known agent and enter a question")
		return ""
	_conversation_agents[agent_id] = true
	if not _connected:
		_reject(agent_id, "connection", "Bridge not connected")
		return ""
	if not conversations.snapshot(agent_id).pending.is_empty():
		_reject(agent_id, "busy", "This agent already has a pending query")
		return ""
	_request_counter += 1
	var request_id := "%s:%d:%d" % [_session_id, conversations.generation, _request_counter]
	if not conversations.start_request(agent_id, request_id, task):
		_reject(agent_id, "capacity", "Question exceeds the conversation display limits")
		return ""
	_pending_requests[request_id] = {"agent_id": agent_id, "generation": conversations.generation}
	GameEvents.conversation_changed.emit(agent_id, "input", request_id)
	GameEvents.agent_query_sent.emit(agent_id, task)
	var payload := JSON.stringify({"agent_id": agent_id, "task": task, "request_id": request_id})
	if _send_text(payload) != OK:
		_fail_request(request_id, "connection", "Failed to send query")
	return request_id


func _send_text(payload: String) -> Error:
	return _socket.send_text(payload)


func conversation_snapshot(agent_id: String) -> Dictionary:
	if AgentRegistry.has_agent(agent_id):
		_conversation_agents[agent_id] = true
	return conversations.snapshot(agent_id)


func set_draft(agent_id: String, text: String) -> bool:
	if not conversations.set_draft(agent_id, text):
		_reject(agent_id, "input", "Draft cannot be changed while disconnected or beyond display limits")
		return false
	_conversation_agents[agent_id] = true
	GameEvents.conversation_changed.emit(agent_id, "draft", "")
	return true


func save_conversation_view(agent_id: String, scroll: float, follow: bool) -> void:
	if not AgentRegistry.has_agent(agent_id):
		return
	_conversation_agents[agent_id] = true
	conversations.save_view(agent_id, scroll, follow)
	GameEvents.conversation_changed.emit(agent_id, "view", "")


func _reject(agent_id: String, kind: String, message: String) -> void:
	GameEvents.conversation_changed.emit(agent_id, "failure", "")
	GameEvents.agent_query_failed.emit(agent_id, kind, message)


func _fail_request(request_id: String, kind: String, message: String) -> void:
	if not _pending_requests.has(request_id):
		return
	var pending: Dictionary = _pending_requests[request_id]
	if not conversations.fail_request(pending.agent_id, request_id, pending.generation, kind, message):
		return
	_pending_requests.erase(request_id)
	GameEvents.conversation_changed.emit(pending.agent_id, "failure", request_id)
	GameEvents.agent_query_failed.emit(pending.agent_id, kind, message)


func _on_message(raw: String) -> void:
	var json := JSON.new()
	if json.parse(raw) != OK or not json.data is Dictionary:
		_protocol_diagnostic("expected a JSON object")
		return
	var parsed: Dictionary = json.data
	if parsed.get("type") in ["agent_status", "project_setup"]:
		_on_character_packet(parsed)
		return
	if parsed.get("type") in ["workspace_state", "domain_state", "domain_accepted", "domain_result", "domain_error", "resume_complete"]:
		_on_domain_packet(parsed)
		return
	var request_id: Variant = parsed.get("request_id")
	if not request_id is String or not _pending_requests.has(request_id):
		_protocol_diagnostic("missing, unknown or completed request ID")
		return
	var pending: Dictionary = _pending_requests[request_id]
	if not parsed.get("agent_id") is String or parsed.agent_id != pending.agent_id:
		_protocol_diagnostic("agent does not match request ID")
		return
	if pending.generation != conversations.generation or not _connected:
		_protocol_diagnostic("request belongs to a closed connection")
		return
	if parsed.has("domain_id") or parsed.has("output_id") or parsed.has("type"):
		_protocol_diagnostic("expected a conversation response")
		return
	var status: Variant = parsed.get("status")
	if status is String and status == "ok" and parsed.get("output") is String:
		var output: String = parsed.output
		if conversations.complete_request(pending.agent_id, request_id, pending.generation, output):
			_pending_requests.erase(request_id)
			GameEvents.conversation_changed.emit(pending.agent_id, "reply", request_id)
			GameEvents.agent_response_received.emit(pending.agent_id, output)
			describe_workspace()
	elif status is String and status == "error" and parsed.get("error_type") is String and parsed.get("message") is String:
		_fail_request(request_id, parsed.error_type, parsed.message)
		describe_workspace()
	else:
		_protocol_diagnostic("invalid conversation response fields")


func _protocol_diagnostic(message: String) -> void:
	# Do not log raw content, guess attribution or release an unrelated request.
	push_warning("ws_client: ignored packet: " + message)


func is_bridge_connected() -> bool:
	return _connected


func workspace_snapshot() -> Dictionary:
	return domains.workspace_snapshot()


func domain_snapshot(domain_id: String) -> Dictionary:
	return domains.snapshot(domain_id)


func set_domain_draft(domain_id: String, text: String) -> bool:
	if not domains.set_draft(domain_id, text): return false
	GameEvents.domain_changed.emit(domain_id, "draft", "")
	return true


func mark_domain_read(domain_id: String, output_id: String) -> void:
	domains.mark_read(domain_id, output_id)
	GameEvents.domain_changed.emit(domain_id, "read", "")


func describe_workspace() -> String:
	if not _connected: return ""
	if _discovery_request != "":
		if _domain_requests.get(_discovery_request, {}).get("type") == "describe_workspace": return _discovery_request
		_refresh_workspace = true
		return ""
	return _send_domain_command({"type": "describe_workspace"})


func domain_status(domain_id: String) -> String:
	_failed_status_domains.erase(domain_id)
	if not _connected or not DomainState.valid_domain(domain_id) or domain_snapshot(domain_id).is_empty(): return ""
	if _discovery_request != "":
		var current: Dictionary = _domain_requests.get(_discovery_request, {})
		if current.get("type") == "domain_status" and current.get("domain_id") == domain_id: return _discovery_request
		if domain_id not in _status_queue: _status_queue.append(domain_id)
		return ""
	return _send_domain_command({"type": "domain_status", "domain_id": domain_id})


func activate_domain(domain_id: String) -> String:
	return _send_domain_command({"type": "activate_domain", "domain_id": domain_id})


func send_domain_query(domain_id: String, agent_id: String, task: String) -> String:
	if not AgentRegistry.has_agent(agent_id): return ""
	return _generation_command("domain_query", domain_id, {"agent_id": agent_id, "task": task})


func background_domain(domain_id: String) -> String:
	return _generation_command("background_domain", domain_id)


func refocus_domain(domain_id: String) -> String:
	return _generation_command("refocus_domain", domain_id)


func deactivate_domain(domain_id: String) -> String:
	return _generation_command("deactivate_domain", domain_id)


func resume_domain(domain_id: String) -> String:
	return _generation_command("resume", domain_id, {"cursor": domain_snapshot(domain_id).get("received_cursor", "0")})


func _generation_command(kind: String, domain_id: String, extra: Dictionary = {}) -> String:
	var packet := {"type": kind, "domain_id": domain_id, "domain_session_id": domain_snapshot(domain_id).get("domain_session_id", "")}
	packet.merge(extra)
	return _send_domain_command(packet)


func _send_domain_command(packet: Dictionary) -> String:
	var socket_open := _socket.get_ready_state() == WebSocketPeer.STATE_OPEN
	if not _connected or not socket_open:
		return ""
	_request_counter += 1
	var id := "%s:domain:%d" % [_session_id, _request_counter]
	packet.request_id = id
	var superseded: Dictionary = domain_snapshot(packet.domain_id).get("pending_control", {}) if packet.has("domain_id") else {}
	if not domains.admit_command(packet):
		return ""
	if packet.type == "deactivate_domain" and superseded.get("type") == "activate_domain":
		_domain_requests.erase(superseded.request_id)
	_domain_requests[id] = packet.duplicate(true)
	if packet.type in ["describe_workspace", "domain_status"]:
		_discovery_request = id
	if packet.has("domain_id"):
		GameEvents.domain_changed.emit(packet.domain_id, "input", id)
	if _send_text(JSON.stringify(packet)) != OK:
		# Delivery may have reached the peer. Preserve uncertain Run; never retry it.
		domains.disconnect_connection()
		_domain_requests.clear()
		_discovery_request = ""
		for domain_id in domains.domain_ids():
			GameEvents.domain_changed.emit(domain_id, "connection", "")
		GameEvents.workspace_changed.emit("connection", id)
	return id


func _on_domain_packet(packet: Dictionary) -> void:
	if not _connected:
		return
	var command: Dictionary = _domain_requests.get(packet.get("request_id"), {}).duplicate(true)
	var change := domains.apply_packet(packet)
	if change.is_empty():
		return
	if change.settled:
		_domain_requests.erase(change.request_id)
		if _discovery_request == change.request_id:
			_discovery_request = ""
	# Generation replacement can retire more than the packet's own request.
	# Mirror only currently pending controls/queries, without completed-ID sets.
	for id in _domain_requests.keys():
		var pending: Dictionary = _domain_requests[id]
		if pending.type in ["describe_workspace", "domain_status"]:
			continue
		var current := domain_snapshot(pending.domain_id)
		var query_pending: bool = id == current.get("pending_query", {}).get("request_id")
		var control_pending: bool = id == current.get("pending_control", {}).get("request_id")
		if not query_pending and not control_pending:
			_domain_requests.erase(id)
	if change.project_changed:
		_reset_project_views()
	if change.scope == "workspace":
		GameEvents.workspace_changed.emit(change.reason, change.request_id)
		if change.reason == "workspace_state":
			for domain_id in _recover_domains:
				_queue_status_observation(domain_id)
			var reservation: Variant = workspace_snapshot().get("reservation")
			if reservation is Dictionary and DomainState.valid_domain(reservation.get("domain_id")):
				_queue_status_observation(reservation.domain_id)
	else:
		if change.reason == "domain_error" and command.get("type") == "domain_status":
			_failed_status_domains[change.domain_id] = true
			_status_queue.erase(change.domain_id)
			_resume_queue.erase(change.domain_id)
		GameEvents.domain_changed.emit(change.domain_id, change.reason, change.request_id)
		var failed_control: bool = change.reason == "domain_error" and command.get("type") != "domain_status"
		if change.reason in ["resume_complete", "status_stale"] or failed_control:
			domain_status(change.domain_id)
		if change.reason == "domain_state" and command.get("type") == "domain_status" and _recover_domains.has(change.domain_id):
			_recover_domains.erase(change.domain_id)
			if domain_snapshot(change.domain_id).domain_session_id != "":
				_resume_queue.append(change.domain_id)
		var settled_control: bool = change.reason == "domain_state" and command.get("type") != "domain_status" and change.settled
		if change.reason == "domain_result" or failed_control or settled_control:
			# Lifecycle/capacity changes invalidate every observed working character.
			# Queue even behind an in-flight status: its fence predates settlement.
			for agent_id in _characters:
				if _characters[agent_id].get("execution_kind") == "working" and agent_id not in _character_queue:
					_character_queue.append(agent_id)
			describe_workspace()
	_pump_discovery()


func _queue_status_observation(domain_id: String) -> void:
	if domain_id not in _status_queue and not _failed_status_domains.has(domain_id):
		_status_queue.append(domain_id)


func _pump_discovery() -> void:
	if _discovery_request == "":
		if _refresh_workspace:
			_refresh_workspace = false
			describe_workspace()
		elif not _character_queue.is_empty():
			agent_status(_character_queue.pop_front())
		elif not _status_queue.is_empty():
			domain_status(_status_queue.pop_front())
	if not _resume_queue.is_empty():
		var domain_id: String = _resume_queue[0]
		if not resume_domain(domain_id).is_empty():
			_resume_queue.pop_front()


func _reset_project_views() -> void:
	# Commit both stores before presenting the authoritative new binding.
	_pending_requests.clear()
	conversations = Store.new(
		AgentRegistry.has_agent,
		int(ProjectSettings.get_setting("plaza/chat/history_max_messages", 200)),
		int(ProjectSettings.get_setting("plaza/chat/history_max_bytes", 1048576))
	)
	conversations.begin_connection()
	_domain_requests.clear()
	_discovery_request = ""
	_status_queue.clear()
	_resume_queue.clear()
	_recover_domains.clear()
	_failed_status_domains.clear()
	_notify_connection()
	_character_requests.clear()
	_character_queue.clear()
	_setup_request = ""
	_characters.clear()
	surface.reset()


func character_snapshot(agent_id: String) -> Dictionary:
	return _characters.get(agent_id, {}).duplicate(true)

func agent_status(agent_id: String) -> String:
	if not AgentRegistry.has_agent(agent_id) or not _connected: return ""
	if _discovery_request != "":
		var current: Dictionary = _character_requests.get(_discovery_request, {})
		if current.get("agent_id") == agent_id: return _discovery_request
		if agent_id not in _character_queue: _character_queue.append(agent_id)
		return ""
	return _send_character({"type": "agent_status", "agent_id": agent_id})

func project_setup(agent_id: String, intent: String) -> String:
	if not _connected or not AgentRegistry.has_agent(agent_id) or not _setup_request.is_empty() or intent.strip_edges().is_empty() or intent.to_utf8_buffer().size() > 65536: return ""
	return _send_character({"type": "project_setup", "agent_id": agent_id, "intent": intent})

func _send_character(packet: Dictionary) -> String:
	_request_counter += 1
	var id := "%s:character:%d" % [_session_id, _request_counter]
	packet.request_id = id
	_character_requests[id] = {"type": packet.type, "agent_id": packet.agent_id, "fence": domains.observation_fence()}
	if packet.type == "agent_status": _discovery_request = id
	else: _setup_request = id
	if not _characters.has(packet.agent_id): _characters[packet.agent_id] = {}
	_characters[packet.agent_id].pending = packet.type
	_characters[packet.agent_id].error = ""
	GameEvents.character_changed.emit(packet.agent_id, "input", id)
	if _send_text(JSON.stringify(packet)) != OK: _on_connection_closed()
	return id

func _on_character_packet(packet: Dictionary) -> void:
	var id: Variant = packet.get("request_id")
	var request: Dictionary = _character_requests.get(id, {})
	if not _connected or request.is_empty() or request.type != packet.get("type") or request.agent_id != packet.get("agent_id")  : return
	if not packet.get("project") is Dictionary: return
	var current_fence := domains.observation_fence()
	if request.fence.epoch != current_fence.epoch: return
	if not domains.observation_current(request.fence):
		if request.fence.project_id != "" or packet.project.get("project_id") != current_fence.project_id: return
	var failed: bool = packet.get("status") == "error"
	if failed or packet.type == "project_setup":
		if not packet.get("output") is String or packet.get("status") not in ["ok", "error"]: return
	else:
		if packet.get("execution_kind") not in ["working", "extra"] or not packet.get("capabilities") is Dictionary: return
		if packet.execution_kind == "working" and (not DomainState.valid_domain(packet.get("domain_id")) or not packet.get("domain_state") is Dictionary or not packet.get("workspace") is Dictionary): return
		if packet.execution_kind == "extra" and packet.get("domain_id") != null: return
		for key in ["can_start", "can_run", "can_prepare_project"]:
			if not packet.capabilities.get(key) is bool: return
	var change := domains.observe_project(packet.project)
	if change.is_empty(): return
	_character_requests.erase(id)
	if _discovery_request == id: _discovery_request = ""
	if _setup_request == id: _setup_request = ""
	if change.project_changed: _reset_project_views()
	var data: Dictionary = _characters.get(packet.agent_id, {}).duplicate(true)
	data.pending = ""
	data.error = packet.output if failed else ""
	if packet.type == "project_setup": data.setup_output = packet.output
	elif not failed:
		for key in ["execution_kind", "domain_id", "workspace", "capabilities"]: data[key] = packet[key]
		if packet.execution_kind == "working":
			if domains.observe_domain(packet.domain_state, request.fence):
				GameEvents.domain_changed.emit(packet.domain_id, "observation", id)
	_characters[packet.agent_id] = data
	GameEvents.workspace_changed.emit("workspace_state", id)
	GameEvents.character_changed.emit(packet.agent_id, packet.type, id)
	if packet.type == "project_setup":
		describe_workspace()
		agent_status(packet.agent_id)
	_pump_discovery()
