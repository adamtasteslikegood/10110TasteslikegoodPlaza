class_name ConversationStore
extends RefCounted

## Session-only display state (BRIDGE-PLATFORM-DESIGN §7). No provider context,
## transport or notifications: BridgeClient owns those boundaries (D-005).
const TRUNCATION_MARKER := "[truncated]"

var generation: int = 0
var connected: bool = false

var _is_known_agent: Callable
var _max_messages: int
var _max_bytes: int
var _agents: Dictionary = {}


func _init(is_known_agent: Callable, max_messages: int, max_bytes: int) -> void:
	_is_known_agent = is_known_agent
	_max_messages = maxi(0, max_messages)
	_max_bytes = maxi(0, max_bytes)


func begin_connection() -> int:
	if not connected:
		generation += 1
		connected = true
	return generation


## Object already defines disconnect(signal, callable); use an unambiguous name.
func disconnect_connection(message: String) -> Array[String]:
	var failed: Array[String] = []
	if not connected:
		return failed
	for agent_id in _agents:
		var state: Dictionary = _agents[agent_id]
		if not state.pending.is_empty():
			var request_id: String = state.pending.request_id
			_finish(state, request_id, "error", "failed", message, "disconnected")
			failed.append(request_id)
		if not state.draft.is_empty():
			var draft: String = state.draft
			state.draft = ""
			state.messages.append(_message("", "draft", draft, "archived"))
	connected = false
	return failed


func set_draft(agent_id: String, text: String) -> bool:
	if not connected or not _is_known_agent.call(agent_id):
		return false
	var candidate: Dictionary = _state(agent_id).duplicate(true)
	candidate.draft = text
	if not _admit(candidate):
		return false
	_agents[agent_id] = candidate
	return true


func start_request(agent_id: String, request_id: String, text: String) -> bool:
	if not connected or not _is_known_agent.call(agent_id) or request_id.is_empty() or text.is_empty():
		return false
	var state: Dictionary = _state(agent_id)
	if not state.pending.is_empty():
		return false
	var candidate: Dictionary = state.duplicate(true)
	if candidate.draft == text:
		candidate.draft = ""
	candidate.messages.append(_message(request_id, "user", text, "pending"))
	candidate.pending = {"request_id": request_id, "generation": generation}
	if not _admit(candidate):
		return false
	_agents[agent_id] = candidate
	return true


func complete_request(agent_id: String, request_id: String, request_generation: int, text: String) -> bool:
	if not _matches(agent_id, request_id, request_generation):
		return false
	_finish(_agents[agent_id], request_id, "assistant", "completed", text)
	return true


func fail_request(agent_id: String, request_id: String, request_generation: int, kind: String, message: String) -> bool:
	if not _matches(agent_id, request_id, request_generation):
		return false
	_finish(_agents[agent_id], request_id, "error", "failed", message, kind)
	return true


func snapshot(agent_id: String) -> Dictionary:
	if not _is_known_agent.call(agent_id):
		return {}
	var state: Dictionary = _state(agent_id)
	var result: Dictionary = state.duplicate(true)
	result.connected = connected
	result.generation = generation
	var usage := _usage(state)
	result.content_bytes = usage.bytes
	result.message_count = usage.count
	return result


func save_view(agent_id: String, scroll: float, follow: bool) -> void:
	if not _is_known_agent.call(agent_id):
		return
	var state: Dictionary = _state(agent_id)
	state.scroll = maxf(0.0, scroll)
	state.follow = follow


func _state(agent_id: String) -> Dictionary:
	if not _agents.has(agent_id):
		_agents[agent_id] = {"messages": [], "draft": "", "pending": {}, "scroll": 0.0, "follow": true, "omitted": 0}
	return _agents[agent_id]


func _matches(agent_id: String, request_id: String, request_generation: int) -> bool:
	if not connected or request_generation != generation or not _is_known_agent.call(agent_id) or not _agents.has(agent_id):
		return false
	var pending: Dictionary = _agents[agent_id].pending
	return not pending.is_empty() and pending.request_id == request_id and pending.generation == request_generation


func _message(request_id: String, role: String, content: String, status: String) -> Dictionary:
	return {"request_id": request_id, "role": role, "content": content, "status": status, "generation": generation, "truncated": false, "original_bytes": content.to_utf8_buffer().size()}


func _finish(state: Dictionary, request_id: String, role: String, status: String, content: String, kind: String = "") -> void:
	# Keep the user record protected until space for this terminal is settled.
	# Admission reserved one slot and at least the marker's bytes, even if a
	# draft now fills every other available slot/byte.
	_make_room(state, 1, content.to_utf8_buffer().size())
	var available: int = _max_bytes - _usage(state).bytes
	var terminal := _message(request_id, role, content, status)
	if terminal.original_bytes > available:
		terminal.content = _excerpt(content, available)
		terminal.truncated = true
	for message in state.messages:
		if message.status == "pending":
			message.status = status
	if role == "error":
		terminal.kind = kind
	state.messages.append(terminal)
	state.pending = {}


func _usage(state: Dictionary) -> Dictionary:
	var count: int = state.messages.size()
	var bytes: int = 0
	for message in state.messages:
		bytes += message.content.to_utf8_buffer().size()
	if not state.draft.is_empty():
		count += 1
		bytes += state.draft.to_utf8_buffer().size()
	return {"count": count, "bytes": bytes}


func _admit(candidate: Dictionary) -> bool:
	var slots := 0 if candidate.pending.is_empty() else 1
	var bytes := 0 if candidate.pending.is_empty() else TRUNCATION_MARKER.to_utf8_buffer().size()
	return _make_room(candidate, slots, bytes)


func _make_room(state: Dictionary, extra_count: int, extra_bytes: int) -> bool:
	var usage := _usage(state)
	while usage.count + extra_count > _max_messages or usage.bytes + extra_bytes > _max_bytes:
		if not _evict_oldest(state):
			return false
		usage = _usage(state)
	return true


func _evict_oldest(state: Dictionary) -> bool:
	# Flat ordered records carry boundaries only while content survives. No
	# per-generation containers or seen-ID sets grow across empty reconnects.
	for i in range(state.messages.size()):
		var oldest: Dictionary = state.messages[i]
		if oldest.status == "pending":
			continue
		if oldest.role == "draft":
			state.messages.remove_at(i)
			state.omitted += 1
		else:
			for j in range(state.messages.size() - 1, -1, -1):
				var message: Dictionary = state.messages[j]
				if message.request_id == oldest.request_id and message.generation == oldest.generation:
					state.messages.remove_at(j)
					state.omitted += 1
		return true
	return false


func _excerpt(text: String, byte_budget: int) -> String:
	var prefix_budget: int = byte_budget - TRUNCATION_MARKER.to_utf8_buffer().size()
	assert(prefix_budget >= 0, "pending admission must reserve marker bytes")
	# Godot String indices are Unicode codepoints, not UTF-8 byte offsets.
	var low := 0
	var high := text.length()
	while low < high:
		var middle: int = (low + high + 1) / 2
		if text.left(middle).to_utf8_buffer().size() <= prefix_budget:
			low = middle
		else:
			high = middle - 1
	return text.left(low) + TRUNCATION_MARKER
