extends Node

## WebSocket client for the Python bridge (ws://localhost:8765).
##
## D-005: knows about WebSocket messages (JSON per bridge/PROTOCOL.md),
## never about agent definitions, auth, or the SDK.
## Emits signals via GameEvents; the dialogue panel consumes them.

const BRIDGE_URL := "ws://localhost:8765"
const RECONNECT_DELAY := 3.0

var _socket := WebSocketPeer.new()
var _connected := false
var _pending_agent_id := ""

@onready var _reconnect_timer := Timer.new()


func _ready() -> void:
	add_child(_reconnect_timer)
	_reconnect_timer.one_shot = true
	_reconnect_timer.timeout.connect(_attempt_connect)
	_attempt_connect()


func _attempt_connect() -> void:
	var err := _socket.connect_to_url(BRIDGE_URL)
	if err != OK:
		push_warning("ws_client: cannot initiate connection to %s" % BRIDGE_URL)
		_schedule_reconnect()


func _process(_delta: float) -> void:
	_socket.poll()

	var state := _socket.get_ready_state()
	match state:
		WebSocketPeer.STATE_OPEN:
			if not _connected:
				_connected = true
			while _socket.get_available_packet_count() > 0:
				_on_message(_socket.get_packet().get_string_from_utf8())
		WebSocketPeer.STATE_CLOSING:
			pass
		WebSocketPeer.STATE_CLOSED:
			if _connected:
				_connected = false
				push_warning("ws_client: connection closed (code %d)" % _socket.get_close_code())
			if _pending_agent_id != "":
				GameEvents.agent_query_failed.emit(
					_pending_agent_id, "connection", "Connection lost during query"
				)
				_pending_agent_id = ""
			_schedule_reconnect()


func _schedule_reconnect() -> void:
	if _reconnect_timer.is_stopped():
		_reconnect_timer.start(RECONNECT_DELAY)


func send_query(agent_id: String, task: String) -> void:
	if not _connected:
		GameEvents.agent_query_failed.emit(
			agent_id, "connection", "Bridge not connected"
		)
		return

	var payload := JSON.stringify({"agent_id": agent_id, "task": task})
	var err := _socket.send_text(payload)
	if err != OK:
		GameEvents.agent_query_failed.emit(
			agent_id, "connection", "Failed to send query"
		)
		return

	_pending_agent_id = agent_id
	GameEvents.agent_query_sent.emit(agent_id, task)


func _on_message(raw: String) -> void:
	var parsed = JSON.parse_string(raw)
	if parsed == null or not parsed is Dictionary:
		GameEvents.agent_query_failed.emit(
			_pending_agent_id, "invalid_response", "Bad JSON from bridge"
		)
		return

	var status: String = parsed.get("status", "error")
	var agent_id: String = parsed.get("agent_id", _pending_agent_id)

	_pending_agent_id = ""

	if status == "ok":
		GameEvents.agent_response_received.emit(agent_id, parsed.get("output", ""))
	else:
		GameEvents.agent_query_failed.emit(
			agent_id,
			parsed.get("error_type", "unknown"),
			parsed.get("message", "Unknown error")
		)


func is_bridge_connected() -> bool:
	return _connected
