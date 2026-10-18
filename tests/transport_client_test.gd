extends Node

## Deterministic, provider-free transport acceptance over actual loopback sockets.
var _failures: Array[String] = []
var _checks := 0
var _server := TCPServer.new()
var _peer: WebSocketPeer
var _client: Node
var _a := ""
var _b := ""
var _events: Array[Dictionary] = []
var _bad_notification_state := false
var _other_session := ""


func _ready() -> void:
	get_tree().create_timer(10.0).timeout.connect(func():
		_check(false, "transport acceptance timed out")
		_finish()
	)
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	var script = load("res://scenes/bridge/ws_client.gd")
	if not _check(script != null and script.can_instantiate(), "transport script loads and can instantiate"):
		_finish()
		return
	var fixture = load("res://tests/transport_client_fixture.gd")
	if not _check(fixture != null and fixture.can_instantiate(), "transport fixture loads and can instantiate"):
		_finish()
		return
	var candidate = script.new()
	if not _check(candidate.get("conversations") != null, "BridgeClient owns its ConversationStore before ready"):
		candidate.free()
		_finish()
		return
	_other_session = candidate._session_id
	candidate.free()
	if not _check(GameEvents.has_signal("conversation_changed"), "additive conversation_changed signal exists"):
		_finish()
		return
	_a = AgentRegistry._sorted_ids()[0]
	_b = AgentRegistry._sorted_ids()[1]
	GameEvents.connect("conversation_changed", _on_changed)
	GameEvents.agent_query_sent.connect(_on_sent)
	GameEvents.agent_response_received.connect(_on_reply)
	GameEvents.agent_query_failed.connect(_on_failure)
	_check(_server.listen(0, "127.0.0.1") == OK, "loopback peer starts")
	_client = load("res://tests/transport_client_fixture.gd").new()
	_client.bridge_url = "ws://127.0.0.1:%d" % _server.get_local_port()
	_client.conversation_snapshot(_a)
	_client.conversation_snapshot(_b)
	add_child(_client)
	_check(_client.conversations.generation == 0, "connect initiation does not advance generation")
	if not await _wait_open():
		_finish()
		return
	_check(_client.conversations.generation == 1, "actual socket open advances generation once")
	_check(_client._reconnect_timer.is_stopped(), "open cancels reconnect timer")
	_check(_client._session_id != _other_session and _client._session_id.length() == 32, "each client has a random 128-bit session prefix")
	await _frames(3)
	_check(_client.conversations.generation == 1, "repeated open polls do not advance generation")
	_test_wrappers_and_signal_arities()
	await _test_correlated_packets()
	await _test_synchronous_send_failure()
	await _test_disconnect_and_reconnect()
	await _test_bounded_admission_and_live_reply()
	await _test_failed_connection()
	_check(not _bad_notification_state, "all input/terminal/connection notifications observe settled store and map")
	_finish()


func _check(condition: bool, message: String) -> bool:
	_checks += 1
	if not condition:
		_failures.append(message)
	return condition


func _finish() -> void:
	if is_instance_valid(_client):
		_client.set_process(false)
		_client._reconnect_timer.stop()
		_client._socket.close()
	if _peer != null:
		_peer.close()
	_server.stop()
	if _failures.is_empty():
		print("transport_client_test: OK — %d checks passed." % _checks)
		get_tree().quit(0)
	else:
		for failure in _failures:
			printerr("FAIL: " + failure)
		printerr("transport_client_test: %d failures / %d checks." % [_failures.size(), _checks])
		get_tree().quit(1)


func _frames(count: int) -> void:
	for i in range(count):
		if _peer != null:
			_peer.poll()
		await get_tree().process_frame


func _wait_open() -> bool:
	var deadline := Time.get_ticks_msec() + 3000
	while Time.get_ticks_msec() < deadline:
		if _server.is_connection_available():
			_peer = WebSocketPeer.new()
			_check(_peer.accept_stream(_server.take_connection()) == OK, "peer accepts actual TCP stream")
		if _peer != null:
			_peer.poll()
		if _peer != null and _peer.get_ready_state() == WebSocketPeer.STATE_OPEN and _client.is_bridge_connected():
			return true
		await get_tree().process_frame
	return _check(false, "actual WebSocket opens before deadline")


func _receive() -> Dictionary:
	var deadline := Time.get_ticks_msec() + 1000
	while Time.get_ticks_msec() < deadline:
		_peer.poll()
		if _peer.get_available_packet_count() > 0:
			var parsed = JSON.parse_string(_peer.get_packet().get_string_from_utf8())
			return parsed if parsed is Dictionary else {}
		await get_tree().process_frame
	_check(false, "outgoing packet arrives at peer")
	return {}


func _deliver(packet: Variant) -> void:
	_check(_peer.send_text(JSON.stringify(packet)) == OK, "peer sends response")
	await _frames(5)


func _success(agent: String, request_id: String, text: String = "reply") -> Dictionary:
	return {"agent_id": agent, "request_id": request_id, "status": "ok", "output": text}


func _test_wrappers_and_signal_arities() -> void:
	var arities := {"agent_query_sent": 2, "agent_response_received": 2, "agent_query_failed": 3, "conversation_changed": 3}
	for info in GameEvents.get_signal_list():
		if arities.has(info.name):
			_check(info.args.size() == arities[info.name], "signal arity preserved: " + info.name)
	_check(_client.set_draft(_a, "draft 雪"), "draft wrapper admits known agent")
	_check(_client.conversation_snapshot(_a).draft == "draft 雪", "snapshot wrapper returns draft")
	_client.save_conversation_view(_a, 72.5, false)
	var snapshot: Dictionary = _client.conversation_snapshot(_a)
	_check(snapshot.scroll == 72.5 and not snapshot.follow, "view wrapper preserves scroll/follow")
	_check(_count("changed", "draft") == 1 and _count("changed", "view") == 1, "draft/view changes notify")
	_check(_client.conversation_snapshot("unknown").is_empty(), "unknown snapshot rejected")
	_check(not _client.set_draft("unknown", "no"), "unknown draft rejected")
	_check(_client.send_query("unknown", "no") == "", "unknown query rejected")
	_check(_client.send_query(_a, " \t\n") == "", "whitespace-only query rejected")
	_check(_client.set_draft(_a, ""), "clear composing draft")


func _test_correlated_packets() -> void:
	var task := "  exact task 雪\n"
	_check(_client.set_draft(_a, task), "matching task draft stored")
	var a: String = _client.send_query(_a, task)
	var b: String = _client.send_query(_b, "B")
	_check(not a.is_empty() and not b.is_empty() and a != b, "A/B receive distinct admitted IDs")
	var first: Dictionary = await _receive()
	var second: Dictionary = await _receive()
	_check(first == {"agent_id": _a, "task": task, "request_id": a}, "outgoing A task and ID exact")
	_check(second == {"agent_id": _b, "task": "B", "request_id": b}, "outgoing B task and ID exact")
	_check(_client._pending_requests.size() == 2, "both agents stay independently pending")
	_check(_client._pending_requests[a] == {"agent_id": _a, "generation": 1}, "map stores exact agent/generation pair")
	_check(a.begins_with(_client._session_id + ":1:"), "wire ID combines session prefix, generation and counter")
	_check(_client.send_query(_a, "duplicate") == "", "second query to same pending agent rejected")
	_check(_client._pending_requests.size() == 2, "rejection cannot clear pending")
	_check(_client.conversation_snapshot(_a).draft == "", "matching draft moves to admitted input")
	var invalid: Array = [null, [], 7, "bad", {},
		{"agent_id": _a, "status": "ok", "output": "no ID"},
		_success(_a, "unknown"), _success(_b, a),
		{"agent_id": _a, "request_id": 3, "status": "ok", "output": "bad"},
		{"agent_id": _a, "request_id": a, "status": true, "output": "bad"},
		{"agent_id": _a, "request_id": a, "status": "ok", "output": []},
		{"request_id": a, "status": "ok", "output": "no agent"},
		{"agent_id": 3, "request_id": a, "status": "ok", "output": "bad"},
		{"agent_id": _a, "request_id": a, "status": "weird", "output": "bad"},
		{"agent_id": _a, "request_id": a, "status": "error", "error_type": [], "message": "bad"},
		{"agent_id": _a, "request_id": a, "status": "error", "error_type": "api_error", "message": null},
		{"agent_id": _a, "request_id": a, "status": "ok"},
		{"agent_id": _a, "request_id": a, "status": "error"},
		{"agent_id": _a, "request_id": a, "status": "ok", "output": "domain", "domain_id": "engineering"}]
	for bad_id in [null, "", "   ", true, [], {}, a + " "]:
		invalid.append({"agent_id": _a, "request_id": bad_id, "status": "ok", "output": "bad ID"})
	var notifications := _events.size()
	for packet in invalid:
		await _deliver(packet)
		_check(_client._pending_requests.size() == 2, "uncorrelated/malformed packet preserves both requests: " + str(packet))
	_check(_peer.send_text("{malformed") == OK, "send malformed JSON")
	await _frames(5)
	_check(_client._pending_requests.size() == 2 and _events.size() == notifications, "malformed packets emit no guessed legacy or conversation terminal")
	# Hidden A completes while B is still pending; no focus belongs to transport.
	await _deliver(_success(_a, a, "hidden A 雪"))
	_check(_client._pending_requests.size() == 1 and _client._pending_requests.has(b), "A success removes only A map entry")
	_check(_client.conversation_snapshot(_a).messages.back().content == "hidden A 雪", "hidden A reply retained")
	_check(_client.conversation_snapshot(_b).pending.request_id == b, "B remains pending after hidden A result")
	var after_a := _events.size()
	await _deliver(_success(_a, a, "duplicate"))
	_check(_events.size() == after_a and _client._pending_requests.has(b), "duplicate A cannot clear or notify B")
	await _deliver({"agent_id": _b, "request_id": b, "status": "error", "error_type": "timeout", "message": "B timed out"})
	_check(_client._pending_requests.is_empty(), "B failure clears final matching entry")
	_check(_client.conversation_snapshot(_b).messages.back().kind == "timeout", "B failure retained with kind")
	_check(_count("reply") == 1, "only hidden A success emits a legacy reply")
	for entry in _events:
		if entry.event == "reply":
			_check(entry.agent == _a and entry.output == "hidden A 雪", "legacy reply carries the exact correlated agent/output")
	var after_b := _events.size()
	await _deliver({"agent_id": _b, "request_id": b, "status": "error", "error_type": "timeout", "message": "duplicate"})
	_check(_events.size() == after_b, "duplicate failure emits no second terminal")
	_check(_count("changed", "reply", a) == 1 and _count("changed", "failure", b) == 1, "terminals notify exact agent request IDs once")
	# IDs remain unique after terminal removal, without a completed-ID set.
	var again: String = _client.send_query(_a, "again")
	await _receive()
	_check(again != a and again != b, "counter keeps IDs unique after removal")
	await _deliver(_success(_a, a, "old same generation"))
	_check(_client.conversation_snapshot(_a).pending.request_id == again, "old same-generation reply cannot clear new request")
	await _deliver(_success(_a, again))


func _test_synchronous_send_failure() -> void:
	_events.clear()
	_client.fail_send = true
	_check(_client.set_draft(_a, "sync failure"), "sync failure draft admitted")
	var id: String = _client.send_query(_a, "sync failure")
	_check(not id.is_empty(), "synchronous send failure still returns admitted ID")
	var observation: Dictionary = _client.send_observation
	_check(observation.mapped and observation.pending.request_id == id, "pending map and store registered before send_text can fail")
	_check(_client._pending_requests.is_empty() and _client.conversation_snapshot(_a).pending.is_empty(), "sync failure settles map and store before return")
	_check(_client.conversation_snapshot(_a).messages.back().kind == "connection", "sync failure is retained")
	_check(_count("failure") == 1 and _count("changed", "failure", id) == 1, "sync failure notifies once")
	var sent_index := -1
	var failure_index := -1
	for i in range(_events.size()):
		if _events[i].event == "sent": sent_index = i
		if _events[i].event == "failure": failure_index = i
	_check(sent_index < failure_index, "no legacy sent notification occurs after terminal failure")
	_client.fail_send = false
	await _deliver(_success(_a, id, "too late"))
	_check(_count("failure") == 1 and _count("reply") == 0, "reply after failed send cannot revive request")


func _test_disconnect_and_reconnect() -> void:
	_events.clear()
	var a: String = _client.send_query(_a, "queued A")
	var b: String = _client.send_query(_b, "queued B")
	await _receive()
	await _receive()
	_check(_client.set_draft(_a, "archive this draft"), "composing next draft while pending")
	var generation: int = _client.conversations.generation
	_peer.close(1000, "test disconnect")
	var deadline := Time.get_ticks_msec() + 3000
	while _client.is_bridge_connected() and Time.get_ticks_msec() < deadline:
		await _frames(1)
	_check(not _client.is_bridge_connected(), "actual socket close observed")
	_check(_client.conversations.generation == generation, "close does not advance generation")
	_check(_client._pending_requests.is_empty(), "disconnect clears all pending map entries")
	_check(_count("failure") == 2 and _count("changed", "failure", a) == 1 and _count("changed", "failure", b) == 1, "disconnect fails both queued agents exactly once")
	var archived: Dictionary = _client.conversation_snapshot(_a)
	_check(archived.draft == "" and archived.messages.back().content == "archive this draft" and archived.messages.back().status == "archived", "disconnect archives draft read-only")
	var settled := _events.size()
	await _frames(5)
	_check(_events.size() == settled, "repeated closed polls do not notify failures again")
	_check(_client.send_query(_a, "offline") == "", "offline send rejected")
	_check(not _client.set_draft(_a, "offline replacement"), "offline draft rejected")
	_check(_client.conversation_snapshot(_a) == archived, "offline rejections preserve entire archive")
	_check(not _client._reconnect_timer.is_stopped(), "close schedules a reconnect")
	_client._reconnect_timer.start(0.01)
	_check(_client.conversations.generation == generation, "scheduled reconnect does not advance generation before open")
	if not await _wait_open():
		return
	_check(_client.conversations.generation == generation + 1, "actual reconnect starts next generation")
	_check(_client.conversation_snapshot(_a).draft == "" and _client.conversation_snapshot(_a).messages == archived.messages, "fresh generation does not copy draft or replay history")
	await _frames(3)
	_check(_peer.get_available_packet_count() == 0, "reconnect sends no automatic replay")
	var fresh: String = _client.send_query(_a, "fresh")
	var packet: Dictionary = await _receive()
	_check(fresh != a and fresh != b and packet.request_id == fresh, "reconnect uses new unique request ID")
	await _deliver(_success(_a, a, "stale generation"))
	_check(_client.conversation_snapshot(_a).pending.request_id == fresh, "stale generation ID cannot clear fresh request")
	await _deliver(_success(_a, fresh, "fresh reply"))
	_check(_client.conversation_snapshot(_a).messages.back().generation == generation + 1, "new response belongs to fresh generation")
	_check(_count("changed", "connection") >= 4, "both affected agent views notified on close and open")


func _test_bounded_admission_and_live_reply() -> void:
	var original_client: Node = _client
	var original_peer := _peer
	_client = load("res://tests/transport_client_fixture.gd").new()
	_client.bridge_url = "ws://127.0.0.1:%d" % _server.get_local_port()
	_client.conversations = load("res://scenes/bridge/conversation_store.gd").new(AgentRegistry.has_agent, 3, 30)
	_peer = null
	add_child(_client)
	if await _wait_open():
		_check(_client.set_draft(_a, "keep"), "tiny-store draft admitted")
		var before: Dictionary = _client.conversation_snapshot(_a)
		var failures := _count("failure")
		_check(not _client.set_draft(_a, "雪".repeat(20)), "draft exceeding UTF-8 display bound rejected")
		_check(_client.conversation_snapshot(_a) == before, "draft rejection is atomic through wrapper")
		_check(_count("failure") == failures + 1, "draft rejection emits visible legacy failure")
		_check(_client.send_query(_a, "雪".repeat(20)) == "", "input exceeding reserved display capacity rejected")
		_check(_client.conversation_snapshot(_a) == before and _client._pending_requests.is_empty(), "input rejection retains draft and admits no map entry")
		_check(_count("failure") == failures + 2, "input capacity rejection emits visible failure")
		var id: String = _client.send_query(_a, "keep")
		var packet: Dictionary = await _receive()
		_check(packet.task == "keep" and packet.request_id == id, "tiny display store does not shorten submitted task")
		var full_reply := "雪".repeat(40)
		await _deliver(_success(_a, id, full_reply))
		var snapshot: Dictionary = _client.conversation_snapshot(_a)
		_check(snapshot.messages.back().truncated and snapshot.content_bytes <= 30, "transport stores bounded Unicode display excerpt")
		var reply: Dictionary = _events.back()
		_check(reply.event == "reply" and reply.output == full_reply, "legacy live reply remains full text despite display truncation")
	_client.set_process(false)
	_client._reconnect_timer.stop()
	_client._socket.close()
	if _peer != null:
		_peer.close()
	_client.queue_free()
	_client = original_client
	_peer = original_peer
	await _frames(2)


func _test_failed_connection() -> void:
	var closed_server := TCPServer.new()
	_check(closed_server.listen(0, "127.0.0.1") == OK, "reserve an unused local port")
	var port := closed_server.get_local_port()
	closed_server.stop()
	var failed_client = load("res://scenes/bridge/ws_client.gd").new()
	failed_client.bridge_url = "ws://127.0.0.1:%d" % port
	failed_client.conversation_snapshot(_a)
	var notifications := _events.size()
	add_child(failed_client)
	var deadline := Time.get_ticks_msec() + 1000
	while failed_client._reconnect_timer.is_stopped() and Time.get_ticks_msec() < deadline:
		await get_tree().process_frame
	_check(not failed_client.is_bridge_connected() and failed_client.conversations.generation == 0, "refused actual socket attempt cannot create a generation")
	_check(not failed_client._reconnect_timer.is_stopped(), "failed connection schedules retry")
	_check(_events.size() == notifications, "failed pre-open attempt does not archive or emit connection changes")
	failed_client.set_process(false)
	failed_client._reconnect_timer.stop()
	failed_client.queue_free()


func _count(event: String, reason: String = "", request_id: String = "") -> int:
	var count := 0
	for entry in _events:
		if entry.event == event and (reason == "" or entry.get("reason") == reason) and (request_id == "" or entry.get("id") == request_id):
			count += 1
	return count


func _on_changed(agent: String, reason: String, request_id: String) -> void:
	_events.append({"event": "changed", "agent": agent, "reason": reason, "id": request_id})
	var snapshot: Dictionary = _client.conversation_snapshot(agent)
	if request_id != "" and reason == "input":
		if not _client._pending_requests.has(request_id) or snapshot.pending.get("request_id") != request_id:
			_bad_notification_state = true
	if request_id != "" and reason in ["reply", "failure"]:
		if _client._pending_requests.has(request_id) or snapshot.pending.get("request_id") == request_id:
			_bad_notification_state = true
	if reason == "connection" and snapshot.connected != _client.is_bridge_connected():
		_bad_notification_state = true


func _on_sent(agent: String, _task: String) -> void:
	_events.append({"event": "sent", "agent": agent})
	if _client.conversation_snapshot(agent).pending.is_empty():
		_bad_notification_state = true


func _on_reply(agent: String, response: String) -> void:
	_events.append({"event": "reply", "agent": agent, "output": response})
	if not _client.conversation_snapshot(agent).pending.is_empty():
		_bad_notification_state = true


func _on_failure(agent: String, _kind: String, _message: String) -> void:
	_events.append({"event": "failure", "agent": agent})
