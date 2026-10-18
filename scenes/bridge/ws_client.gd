extends Node

## WebSocket transport plus session-only display conversations. The Python
## bridge sees opaque request IDs, never frontend state (D-005 / D-015).
const BRIDGE_URL := "ws://localhost:8765"
const RECONNECT_DELAY := 3.0
const Store := preload("res://scenes/bridge/conversation_store.gd")

@export var bridge_url := BRIDGE_URL

var conversations := Store.new(
	AgentRegistry.has_agent,
	int(ProjectSettings.get_setting("plaza/chat/history_max_messages", 200)),
	int(ProjectSettings.get_setting("plaza/chat/history_max_bytes", 1048576))
)
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
	_attempt_connect()


func _attempt_connect() -> void:
	if _socket.get_ready_state() != WebSocketPeer.STATE_CLOSED:
		return
	_reconnect_timer.stop()
	var err := _socket.connect_to_url(bridge_url)
	if err != OK:
		push_warning("ws_client: cannot initiate connection to %s" % bridge_url)
		_schedule_reconnect()


func _process(_delta: float) -> void:
	_socket.poll()
	match _socket.get_ready_state():
		WebSocketPeer.STATE_OPEN:
			if not _connected:
				_connected = true
				_reconnect_timer.stop()
				conversations.begin_connection()
				_notify_connection()
			while _socket.get_available_packet_count() > 0:
				_on_message(_socket.get_packet().get_string_from_utf8())
		WebSocketPeer.STATE_CLOSED:
			if _connected:
				_on_connection_closed()
			_schedule_reconnect()


func _on_connection_closed() -> void:
	_connected = false
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
	elif status is String and status == "error" and parsed.get("error_type") is String and parsed.get("message") is String:
		_fail_request(request_id, parsed.error_type, parsed.message)
	else:
		_protocol_diagnostic("invalid conversation response fields")


func _protocol_diagnostic(message: String) -> void:
	# Do not log raw content, guess attribution or release an unrelated request.
	push_warning("ws_client: ignored packet: " + message)


func is_bridge_connected() -> bool:
	return _connected
