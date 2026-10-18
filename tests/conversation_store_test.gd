extends Node

## Pure display-state acceptance. No bridge or provider is contacted.
var _failures: Array[String] = []
var _checks := 0
var _store_script: Script


func _ready() -> void:
	_store_script = load("res://scenes/bridge/conversation_store.gd")
	if not _check(_store_script != null and _store_script.can_instantiate(), "store script loads and can instantiate"):
		get_tree().quit(1)
		return
	_check(ProjectSettings.get_setting("plaza/chat/history_max_messages") == 200, "default message limit configured")
	_check(ProjectSettings.get_setting("plaza/chat/history_max_bytes") == 1048576, "default UTF-8 byte limit configured")
	_test_agents_drafts_and_views()
	_test_pending_and_correlation()
	_test_failure_disconnect_and_archive()
	_test_snapshot_isolation()
	_test_atomic_bounds_and_reservations()
	_test_whole_exchange_eviction()
	_test_unicode_terminal_bounds()
	_test_archived_drafts_and_bounded_generations()
	_test_terminal_exhaustion()
	_test_message_generations_and_terminal_variants()
	if _failures.is_empty():
		print("conversation_store_test: OK — %d checks passed." % _checks)
		get_tree().quit(0)
	else:
		for failure in _failures:
			printerr("FAIL: " + failure)
		printerr("conversation_store_test: %d failures / %d checks." % [_failures.size(), _checks])
		get_tree().quit(1)


func _new_store(max_messages: int = 200, max_bytes: int = 1048576):
	return _store_script.new(func(agent_id: String) -> bool: return agent_id in ["a", "b"], max_messages, max_bytes)


func _check(condition: bool, message: String) -> bool:
	_checks += 1
	if not condition:
		_failures.append(message)
	return condition


func _test_agents_drafts_and_views() -> void:
	var store = _new_store()
	_check(store.generation == 0 and not store.connected, "initial store is disconnected generation zero")
	_check(store.snapshot("unknown").is_empty(), "unknown agent cannot allocate a snapshot")
	_check(not store.set_draft("unknown", "x"), "unknown draft rejected")
	_check(not store.start_request("unknown", "r", "x"), "unknown request rejected")
	store.save_view("unknown", 19.0, false)
	_check(store.snapshot("unknown").is_empty(), "unknown view cannot allocate state")
	_check(not store.start_request("a", "r", "x"), "disconnected request rejected")
	_check(not store.set_draft("a", "offline"), "disconnected generation is read-only")
	_check(store.begin_connection() == 1 and store.connected, "real open begins editable generation")
	if not _check(store.set_draft("a", "Hello 世界"), "known agent draft admitted"):
		return
	_check(store.set_draft("b", "other"), "second agent has independent draft")
	store.save_view("a", 73.5, false)
	var a: Dictionary = store.snapshot("a")
	var b: Dictionary = store.snapshot("b")
	_check(a.draft == "Hello 世界" and b.draft == "other", "drafts isolated by agent")
	_check(a.scroll == 73.5 and not a.follow, "scroll and follow restored")
	_check(b.scroll == 0.0 and b.follow, "view defaults are independent")
	_check(a.content_bytes == 12 and a.message_count == 1, "draft uses exact UTF-8 bytes and one slot")
	_check(store.set_draft("a", ""), "draft can be cleared")
	_check(store.snapshot("a").content_bytes == 0 and store.snapshot("a").message_count == 0, "empty draft uses no bytes or slots")


func _test_pending_and_correlation() -> void:
	var store = _new_store()
	var generation: int = store.begin_connection()
	store.set_draft("a", "question")
	if not _check(store.start_request("a", "a1", "question"), "matching draft moves into pending user message"):
		return
	var snapshot: Dictionary = store.snapshot("a")
	_check(snapshot.draft == "" and snapshot.pending.request_id == "a1", "pending identity and consumed draft exposed")
	_check(snapshot.message_count == 1 and snapshot.content_bytes == 8, "draft movement does not double count")
	_check(snapshot.messages[0].role == "user" and snapshot.messages[0].status == "pending", "pending user record is explicit")
	_check(not store.start_request("a", "a2", "second"), "one pending request per agent")
	_check(store.start_request("b", "b1", "other"), "different agents may both have pending requests")
	_check(not store.complete_request("a", "wrong", generation, "bad"), "mismatched completion rejected")
	_check(not store.complete_request("a", "a1", generation - 1, "bad"), "stale generation completion rejected")
	_check(not store.complete_request("unknown", "a1", generation, "bad"), "unknown completion rejected")
	_check(store.snapshot("a").pending.request_id == "a1", "rejected packets preserve pending identity")
	_check(store.complete_request("a", "a1", generation, "answer"), "matching completion accepted")
	_check(not store.complete_request("a", "a1", generation, "duplicate"), "duplicate completion rejected")
	_check(not store.fail_request("a", "a1", generation, "error", "late"), "late failure cannot replace completion")
	snapshot = store.snapshot("a")
	_check(snapshot.pending.is_empty() and snapshot.messages.size() == 2, "completion clears only its own pending request")
	_check(snapshot.messages[0].status == "completed" and snapshot.messages[1].status == "completed", "both exchange records become terminal")
	_check(snapshot.messages[1].role == "assistant" and snapshot.messages[1].content == "answer", "reply retained separately")
	_check(snapshot.messages[1].generation == generation and snapshot.messages[1].request_id == "a1", "reply retains correlation metadata")
	_check(not snapshot.messages[1].truncated and snapshot.messages[1].original_bytes == 6, "unshortened reply records original byte length")
	_check(store.snapshot("b").pending.request_id == "b1", "A completion does not clear B")


func _test_failure_disconnect_and_archive() -> void:
	var store = _new_store()
	var generation: int = store.begin_connection()
	if not _check(store.start_request("a", "a1", "question"), "failure test starts pending request"):
		return
	_check(not store.fail_request("a", "wrong", generation, "timeout", "bad"), "mismatched failure rejected")
	_check(store.fail_request("a", "a1", generation, "timeout", "timed out"), "matching failure accepted")
	var snapshot: Dictionary = store.snapshot("a")
	_check(snapshot.pending.is_empty() and snapshot.messages[0].status == "failed", "failure clears pending and finalizes user")
	_check(snapshot.messages[1].role == "error" and snapshot.messages[1].kind == "timeout" and snapshot.messages[1].content == "timed out", "failure retains visible kind and message")
	_check(store.start_request("a", "a2", "retry"), "failed agent can send another request")
	_check(store.start_request("b", "b1", "other"), "disconnect has two pending agents")
	store.set_draft("a", "unsent draft")
	var failed: Array[String] = store.disconnect_connection("connection lost")
	_check(failed.size() == 2 and "a2" in failed and "b1" in failed, "disconnect returns every failed ID once")
	_check(store.disconnect_connection("again").is_empty(), "repeated disconnect is idempotent")
	snapshot = store.snapshot("a")
	_check(not store.connected and not snapshot.connected and snapshot.pending.is_empty(), "disconnect archives finalized state")
	_check(snapshot.draft == "" and snapshot.messages[-1].role == "draft" and snapshot.messages[-1].status == "archived" and snapshot.messages[-1].content == "unsent draft", "archived draft remains visible read-only")
	_check(not store.set_draft("a", "overwrite") and not store.start_request("a", "a3", "retry"), "archived generation rejects edits and submits")
	var retained: Array = snapshot.messages.duplicate(true)
	_check(store.begin_connection() == generation + 1, "reconnect advances generation")
	snapshot = store.snapshot("a")
	_check(snapshot.draft == "" and snapshot.pending.is_empty() and snapshot.messages == retained, "fresh context retains archive without replay or draft copying")
	_check(not store.complete_request("a", "a2", generation, "late"), "old generation cannot complete after reconnect")
	_check(store.start_request("a", "a3", "fresh"), "fresh generation accepts new request")
	_check(store.snapshot("a").messages[-1].generation == generation + 1, "new messages identify fresh boundary")


func _test_snapshot_isolation() -> void:
	var store = _new_store()
	store.begin_connection()
	if not _check(store.start_request("a", "r", "question"), "copy test starts pending request"):
		return
	var snapshot: Dictionary = store.snapshot("a")
	snapshot.messages[0].content = "mutated"
	snapshot.pending.request_id = "mutated"
	snapshot.messages.clear()
	snapshot.draft = "mutated"
	snapshot = store.snapshot("a")
	_check(snapshot.messages.size() == 1 and snapshot.messages[0].content == "question", "snapshot message arrays and records are deep copies")
	_check(snapshot.pending.request_id == "r" and snapshot.draft == "", "snapshot pending and draft cannot mutate store")


func _check_bounds(store, agent_id: String, max_messages: int, max_bytes: int) -> void:
	var snapshot: Dictionary = store.snapshot(agent_id)
	var count: int = snapshot.messages.size()
	var bytes: int = snapshot.draft.to_utf8_buffer().size()
	if not snapshot.draft.is_empty():
		count += 1
	for message in snapshot.messages:
		bytes += message.content.to_utf8_buffer().size()
	_check(snapshot.message_count == count and snapshot.content_bytes == bytes, "reported usage equals all actual message and draft content")
	_check(count <= max_messages and bytes <= max_bytes, "aggregate messages and bytes stay within configured limits")


func _test_atomic_bounds_and_reservations() -> void:
	var store = _new_store(3, 20)
	var generation: int = store.begin_connection()
	_check(store.set_draft("a", "éé"), "four-byte draft fits")
	_check(not store.set_draft("a", "é".repeat(11)), "oversized draft rejected atomically")
	_check(store.snapshot("a").draft == "éé", "rejected draft preserves original")
	if not _check(store.start_request("a", "r", "éé"), "draft move reserves a terminal slot and marker bytes"):
		return
	_check_bounds(store, "a", 3, 20)
	_check(store.set_draft("a", "12345"), "new draft may use bytes beyond pending marker reservation")
	var before: Dictionary = store.snapshot("a")
	_check(not store.set_draft("a", "123456"), "draft cannot consume pending marker byte reservation")
	_check(store.snapshot("a") == before, "failed admission preserves complete state")
	_check(store.complete_request("a", "r", generation, "a".repeat(200)), "completion always fits with protected pending and draft")
	var snapshot: Dictionary = store.snapshot("a")
	_check(snapshot.draft == "12345" and snapshot.messages[0].content == "éé", "completion preserves submitted text and composing draft")
	_check(snapshot.messages[1].content == "[truncated]" and snapshot.messages[1].truncated, "zero spare bytes produces explicit reserved marker")
	_check(snapshot.messages[1].original_bytes == 200, "truncated reply retains original byte length")
	_check_bounds(store, "a", 3, 20)
	_check(store.set_draft("b", "b".repeat(20)), "byte cap is per agent")
	_check_bounds(store, "b", 3, 20)
	var rejected = _new_store(3, 20)
	rejected.begin_connection()
	rejected.set_draft("a", "1234567890")
	before = rejected.snapshot("a")
	_check(not rejected.start_request("a", "r", "1234567890"), "submit rejected if marker would exceed bytes")
	_check(rejected.snapshot("a") == before, "rejected submit retains draft and history")


func _test_whole_exchange_eviction() -> void:
	var store = _new_store(4, 100)
	var generation: int = store.begin_connection()
	for i in range(2):
		store.start_request("a", "r%d" % i, "question%d" % i)
		store.complete_request("a", "r%d" % i, generation, "reply%d" % i)
	var before: Dictionary = store.snapshot("a")
	_check(before.message_count == 4, "two terminal exchanges fill four slots")
	_check(store.set_draft("a", "new"), "new draft evicts oldest whole terminal exchange")
	var snapshot: Dictionary = store.snapshot("a")
	_check(snapshot.messages.size() == 2 and snapshot.messages[0].request_id == "r1" and snapshot.messages[1].request_id == "r1", "eviction cannot strand half an exchange")
	_check(snapshot.omitted == 2 and snapshot.message_count == 3, "omission count counts removed display records")
	_check(store.start_request("a", "r2", "new"), "pending reservation fits after draft movement")
	_check(store.complete_request("a", "r2", generation, "reply2"), "second retained exchange completes")
	_check_bounds(store, "a", 4, 100)
	var byte_limited = _new_store(20, 30)
	generation = byte_limited.begin_connection()
	byte_limited.start_request("a", "old", "12345678")
	byte_limited.complete_request("a", "old", generation, "12345678")
	_check(byte_limited.start_request("a", "new", "abcdefgh"), "byte pressure may evict an old whole exchange")
	snapshot = byte_limited.snapshot("a")
	_check(snapshot.messages.size() == 1 and snapshot.messages[0].request_id == "new" and snapshot.omitted == 2, "byte admission includes marker and evicts oldest pair")
	_check_bounds(byte_limited, "a", 20, 30)
	var atomic = _new_store(3, 20)
	generation = atomic.begin_connection()
	atomic.start_request("a", "old", "x")
	atomic.complete_request("a", "old", generation, "y")
	before = atomic.snapshot("a")
	_check(not atomic.set_draft("a", "x".repeat(21)), "impossible draft cannot evict history before rejecting")
	_check(atomic.snapshot("a") == before, "failed eviction attempt rolls back omissions and messages")


func _test_unicode_terminal_bounds() -> void:
	var store = _new_store(4, 28)
	var generation: int = store.begin_connection()
	store.start_request("a", "r", "123456789")
	var reply := "🙂é界".repeat(10)
	_check(store.complete_request("a", "r", generation, reply), "oversized Unicode completion accepted as display excerpt")
	var snapshot: Dictionary = store.snapshot("a")
	if not _check(snapshot.messages.size() == 2, "oversized reply retains submitted user message"):
		return
	var terminal: Dictionary = snapshot.messages[1]
	_check(terminal.content == "🙂é[truncated]", "reply keeps maximal whole Unicode prefix before marker")
	_check(terminal.original_bytes == 90 and terminal.truncated, "UTF-8 original length retained")
	_check(reply == "🙂é界".repeat(10), "caller reply remains unchanged")
	_check_bounds(store, "a", 4, 28)
	store.start_request("a", "next", "z")
	_check(store.fail_request("a", "next", generation, "timeout", "界".repeat(100)), "oversized failure uses same bounded terminal path")
	snapshot = store.snapshot("a")
	_check(snapshot.messages[-1].truncated and snapshot.messages[-1].kind == "timeout", "failed terminal keeps visible classification and truncation")
	_check_bounds(store, "a", 4, 28)


func _test_archived_drafts_and_bounded_generations() -> void:
	var store = _new_store(3, 18)
	for i in range(30):
		store.begin_connection()
		_check(store.set_draft("a", "é%d" % (i % 10)), "bounded reconnect draft admitted")
		store.disconnect_connection("closed")
		_check_bounds(store, "a", 3, 18)
	var snapshot: Dictionary = store.snapshot("a")
	_check(snapshot.messages.size() == 3 and snapshot.omitted == 27, "archived drafts count once and evict oldest generations")
	_check(snapshot.messages[0].generation == 28 and snapshot.messages[-1].generation == 30, "only retained content carries generation boundaries")
	_check(snapshot.content_bytes == 9 and snapshot.draft == "", "archived draft bytes counted exactly")
	var retained: Array = snapshot.messages.duplicate(true)
	for i in range(1000):
		store.begin_connection()
		store.disconnect_connection("empty")
	snapshot = store.snapshot("a")
	_check(snapshot.messages == retained and snapshot.omitted == 27, "empty reconnects retain no generation records or notices")
	_check(snapshot.keys().size() == 10, "snapshot exposes only bounded content/view metadata")
	_check(snapshot.generation == 1030, "empty reconnects still advance visible current generation")
	store.begin_connection()
	_check(store.snapshot("a").draft == "", "new generation never copies archived draft")
	_check_bounds(store, "a", 3, 18)


func _test_terminal_exhaustion() -> void:
	for limits in [[0, 100], [1, 100], [2, 0], [2, 11]]:
		var store = _new_store(limits[0], limits[1])
		store.begin_connection()
		_check(not store.start_request("a", "r", "x"), "request rejects terminal slot or marker byte exhaustion")
		_check(store.snapshot("a").pending.is_empty(), "impossible request creates no pending work")
		_check_bounds(store, "a", limits[0], limits[1])
	var exact = _new_store(2, 12)
	var generation: int = exact.begin_connection()
	_check(exact.start_request("a", "r", "x"), "exact user plus marker reservation admitted")
	_check(not exact.set_draft("a", "z"), "composer cannot consume reserved terminal slot")
	_check(exact.complete_request("a", "r", generation, "oversized reply"), "terminal uses final reserved slot and bytes")
	_check(exact.snapshot("a").message_count == 2 and exact.snapshot("a").content_bytes == 12, "full completion reaches actual configured limits exactly")
	_check_bounds(exact, "a", 2, 12)
	var disconnected = _new_store(3, 15)
	disconnected.begin_connection()
	disconnected.start_request("a", "r", "x")
	disconnected.set_draft("a", "é")
	_check(disconnected.disconnect_connection("lost connection and more").size() == 1, "disconnect terminal fits with pending and archived draft")
	_check(disconnected.snapshot("a").messages[-1].content == "é", "disconnect preserves archived draft at exhaustion")
	_check_bounds(disconnected, "a", 3, 15)


func _test_message_generations_and_terminal_variants() -> void:
	var store = _new_store(5, 40)
	for i in range(40):
		var generation: int = store.begin_connection()
		_check(store.start_request("a", "r%d" % i, "é"), "message reconnect accepts fresh user text")
		_check(store.set_draft("a", "界"), "message reconnect admits separate composing draft")
		_check_bounds(store, "a", 5, 40)
		if i % 2 == 0:
			_check(store.complete_request("a", "r%d" % i, generation, "🙂"), "message reconnect completes current generation")
			_check(store.disconnect_connection("closed").is_empty(), "completed request is not failed again by disconnect")
		else:
			_check(store.disconnect_connection("error".repeat(20)) == ["r%d" % i], "message reconnect fails exactly its pending ID")
		_check_bounds(store, "a", 5, 40)
		_check(not store.complete_request("a", "r%d" % i, generation, "late"), "archived generation rejects later terminal packets")
	var snapshot: Dictionary = store.snapshot("a")
	_check(snapshot.omitted > 0 and snapshot.messages[-1].generation == 40, "message reconnects evict old content and retain latest boundary")
	_check(snapshot.messages[-1].role == "draft" and snapshot.messages[-1].original_bytes == 3, "archived Unicode draft counts once")
	var exact = _new_store(3, 20)
	var generation: int = exact.begin_connection()
	_check(exact.begin_connection() == generation, "duplicate open notification does not strand current generation")
	_check(not exact.start_request("a", "", "x") and not exact.start_request("a", "empty", ""), "empty ID and empty submitted text rejected")
	exact.set_draft("a", "draft")
	_check(exact.start_request("a", "different", "x"), "nonmatching submitted task leaves independent draft")
	snapshot = exact.snapshot("a")
	_check(snapshot.draft == "draft" and snapshot.content_bytes == 6 and snapshot.message_count == 2, "nonmatching draft and pending input counted independently")
	_check(exact.complete_request("a", "different", generation, ""), "empty successful reply still completes with terminal record")
	snapshot = exact.snapshot("a")
	_check(snapshot.messages[-1].content == "" and not snapshot.messages[-1].truncated and snapshot.messages[-1].original_bytes == 0, "short reply uses actual bytes without reservation padding")
	_check_bounds(exact, "a", 3, 20)
