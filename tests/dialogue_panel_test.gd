extends Node

## Real scene, loopback transport and native input; no model/provider calls.
const A := "fixture-extra-a"
const B := "fixture-extra-b"
var failures: Array[String] = []
var checks := 0
var hud: Node
var panel: Panel
var body: RichTextLabel
var composer: LineEdit
var server := TCPServer.new()
var peer: WebSocketPeer
var sent := 0

func _ready() -> void:
	preload("res://tests/character_fixture.gd").extras()
	get_tree().create_timer(20.0).timeout.connect(func():
		check(false, "watchdog: panel acceptance did not finish")
		finish()
	)
	var script = load("res://scenes/hud/dialogue_panel.gd")
	if not check(script != null and script.can_instantiate(), "panel script loads"):
		finish()
		return
	var scene = load("res://scenes/hud/dialogue_panel.tscn")
	if not check(scene != null and scene.can_instantiate(), "real panel scene loads"):
		finish()
		return
	hud = scene.instantiate()
	add_child(hud)
	panel = hud.get_node("Panel")
	body = hud.get_node("Panel/Margin/Rows/BodyLabel")
	composer = hud.get_node("Panel/Margin/Rows/InputRow/QuestionInput")
	if not check(hud.has_method("current_assistant_span"), "panel exposes exact current assistant span"):
		finish()
		return
	await connect_bridge()
	GameEvents.agent_query_sent.connect(func(_id, _text): sent += 1)
	await history_checks()
	await input_geometry_checks()
	await review_regressions()
	finish()

func check(ok: bool, label: String) -> bool:
	checks += 1
	if not ok:
		failures.append(label)
	return ok

func finish() -> void:
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	BridgeClient._socket.close()
	if peer != null:
		peer.close()
	server.stop()
	for failure in failures:
		printerr("FAIL: " + failure)
	if failures.is_empty():
		print("dialogue_panel_test: OK — %d checks passed." % checks)
	else:
		printerr("dialogue_panel_test: %d failures / %d checks." % [failures.size(), checks])
	get_tree().quit(0 if failures.is_empty() else 1)

func frames(count: int = 3) -> void:
	for i in count:
		if peer != null:
			peer.poll()
		await get_tree().process_frame

func connect_bridge() -> void:
	BridgeClient._socket = WebSocketPeer.new()
	BridgeClient._connected = false
	BridgeClient._reconnect_timer.stop()
	check(server.listen(0, "127.0.0.1") == OK, "loopback listener opens")
	BridgeClient.bridge_url = "ws://127.0.0.1:%d" % server.get_local_port()
	BridgeClient._attempt_connect()
	for i in 200:
		if peer == null and server.is_connection_available():
			peer = WebSocketPeer.new()
			peer.accept_stream(server.take_connection())
		await frames(1)
		if BridgeClient.is_bridge_connected():
			break
	check(BridgeClient.is_bridge_connected(), "real bridge socket opens")

func approach(id: String) -> void:
	GameEvents.npc_approached.emit(id, AgentRegistry.get_agent(id))

func submit(text: String) -> String:
	composer.text = text
	composer.text_changed.emit(text)
	composer.text_submitted.emit(text)
	return str(BridgeClient.conversation_snapshot(hud._current_agent_id).pending.get("request_id", ""))

func reply(id: String, request: String, text: String) -> void:
	BridgeClient._on_message(JSON.stringify({"agent_id": id, "request_id": request, "status": "ok", "output": text}))

func history_checks() -> void:
	approach(A)
	check(body.text == AgentRegistry.get_agent(A).description, "empty history introduces agent")
	composer.text = "draft A"
	composer.text_changed.emit(composer.text)
	approach(B)
	composer.text = "draft B"
	composer.text_changed.emit(composer.text)
	approach(A)
	check(composer.text == "draft A", "A draft survives A B A")
	var a := submit("Remember nonce kestrel-4417")
	check(not a.is_empty() and not composer.editable, "admitted A request disables composer")
	approach(B)
	check(composer.text == "draft B" and composer.editable, "B has independent editable draft")
	var b := submit("B question")
	reply(A, a, "First reply knows kestrel-4417.")
	check(not body.text.contains("First reply"), "hidden A success cannot animate or overwrite B")
	BridgeClient._on_message(JSON.stringify({"agent_id": B, "request_id": b, "status": "error", "error_type": "engine", "message": "B independent error"}))
	check(body.text.contains("B independent error") and composer.editable, "B error retained and re-enables only B")
	approach(A)
	check(body.text.contains("You") and body.text.contains("Assistant") and body.text.contains("Remember nonce"), "ordered role transcript retained")
	check(body.visible_characters == -1 or body.visible_characters == body.text.length(), "restored hidden reply is immediately visible")
	var second := submit("Recall the token")
	var old_text := body.text
	BridgeClient.send_query(A, "duplicate")
	check(not composer.editable and hud._waiting, "empty-ID rejection cannot clear pending")
	reply(A, second, "I forgot the token entirely.")
	var span: Dictionary = hud.current_assistant_span()
	check(body.text.substr(span.start, span.length) == "I forgot the token entirely.", "current assistant span excludes historical nonce (wrong-turn regression)")
	check(not body.text.substr(span.start, span.length).contains("kestrel-4417") and body.text.contains("kestrel-4417"), "whole transcript would falsely pass nonce recall")
	var live_script = load("res://tests/live_conversation.gd")
	if check(live_script != null and live_script.can_instantiate() and live_script.has_method("read_rendered_reply"), "live harness exposes actual-label assistant readback"):
		check(live_script.read_rendered_reply(body, span) == "I forgot the token entirely.", "live turn-two readback cannot inherit turn-one nonce")
		check(live_script.visible_in_span(body, span) == 0, "live sampling subtracts assistant start offset")
	check(body.visible_characters == span.start, "new reveal starts after all previous transcript text")
	await frames(5)
	check(body.visible_characters > span.start and body.visible_characters < span.start + span.length, "progressive visible reply advances relative to its span")
	check(body.text.contains("Remember nonce") and old_text.contains("Remember nonce"), "older text remains present through reveal")
	approach(B)
	approach(A)
	check(body.visible_characters == -1, "switch during reveal restores complete cached reply")
	GameEvents.npc_left.emit(B)
	check(panel.visible and hud._current_agent_id == A, "unrelated NPC leave cannot close selected panel")
	composer.text = "archived draft"
	composer.text_changed.emit(composer.text)
	BridgeClient._on_connection_closed()
	check(body.text.contains("archived draft") and body.text.contains("Archived") and not composer.editable, "disconnect archives draft visibly and read-only")
	BridgeClient.conversations.begin_connection()
	BridgeClient._connected = true
	BridgeClient._notify_connection()
	check(body.text.contains("context restarted") and composer.text.is_empty() and composer.editable, "reconnect creates visible fresh context without copying draft")

func input_geometry_checks() -> void:
	for action in ["chat_page_up", "chat_page_down", "chat_oldest", "chat_newest", "chat_submit", "chat_release_focus", "chat_focus_next", "chat_focus_previous"]:
		check(InputMap.has_action(action) and InputMap.action_get_events(action).size() == 1, "serialized named action: " + action)
	var bindings := {"chat_page_up": [KEY_PAGEUP, false, false], "chat_page_down": [KEY_PAGEDOWN, false, false], "chat_oldest": [KEY_HOME, true, false], "chat_newest": [KEY_END, true, false], "chat_submit": [KEY_ENTER, false, false], "chat_release_focus": [KEY_ESCAPE, false, false], "chat_focus_next": [KEY_TAB, false, false], "chat_focus_previous": [KEY_TAB, false, true]}
	for action in bindings:
		var event: InputEventKey = InputMap.action_get_events(action)[0]
		check(event.keycode == bindings[action][0] and event.ctrl_pressed == bindings[action][1] and event.shift_pressed == bindings[action][2] and not event.alt_pressed and not event.meta_pressed, "exact pinned-engine action modifiers: " + action)
	var plain_home := InputEventKey.new()
	plain_home.keycode = KEY_HOME
	plain_home.pressed = true
	check(not plain_home.is_action_pressed("chat_oldest", false, true), "Ctrl+Home exact modifier excludes native Home")
	var shift_tab: InputEventKey = InputMap.action_get_events("chat_focus_previous")[0]
	check(shift_tab.keycode == KEY_TAB and shift_tab.shift_pressed and not shift_tab.ctrl_pressed, "Shift+Tab serialized modifiers")
	var request := submit("long question")
	reply(A, request, ("Long response line and some wrapping words. ".repeat(3) + "\n").repeat(100))
	var fresh: Dictionary = hud.current_assistant_span()
	check(body.text.substr(fresh.start, fresh.length).begins_with("Long response"), "fresh-generation assistant span uses exact rendered offsets")
	await frames(4)
	var revealed_line := body.get_character_line(maxi(0, body.visible_characters - 1))
	var revealed_y := body.get_line_offset(revealed_line)
	check(body.get_v_scroll_bar().value <= revealed_y, "bottom-follow keeps revealed text in view instead of blank future lines")
	body.grab_focus()
	await key(KEY_HOME, true)
	check(body.get_v_scroll_bar().value == 0 and not hud._follow, "transcript Ctrl+Home disables follow")
	await frames(8)
	check(body.get_v_scroll_bar().value == 0 and not hud._follow, "reveal respects manual reading position")
	composer.grab_focus()
	composer.text = "native edit words"
	composer.text_changed.emit(composer.text)
	composer.caret_column = 6
	await key(KEY_HOME)
	check(composer.caret_column == 0, "composer Home keeps native editing")
	await key(KEY_END)
	check(composer.caret_column == composer.text.length(), "composer End keeps native editing")
	composer.select(0, 6)
	await key(KEY_C, true)
	check(composer.get_selected_text() == "native" and composer.text == "native edit words", "native copy shortcut preserves selection and draft")
	await key(KEY_PAGEDOWN)
	check(body.get_v_scroll_bar().value > 0 and composer.has_focus(), "PgDn scrolls while composing without moving focus")
	await key(KEY_PAGEUP)
	check(body.get_v_scroll_bar().value == 0, "PgUp works while composing")
	await key(KEY_TAB)
	check(body.has_focus(), "Tab traverses composer to transcript")
	await key(KEY_TAB, false, true)
	check(composer.has_focus(), "Shift+Tab traverses transcript to enabled composer")
	body.grab_focus()
	await key(KEY_END, true)
	check(hud._follow and is_equal_approx(body.get_v_scroll_bar().value, hud._bottom()), "Ctrl+End resumes bottom following")
	await wheel(MOUSE_BUTTON_WHEEL_UP, body.get_global_rect().get_center())
	check(not hud._follow and body.get_v_scroll_bar().value < hud._bottom(), "native mouse wheel upward stops follow")
	var reading := body.get_v_scroll_bar().value
	await frames(5)
	check(is_equal_approx(body.get_v_scroll_bar().value, reading), "reveal does not override wheel reading position")
	var bar := body.get_v_scroll_bar()
	await drag(scrollbar_thumb_center(bar), Vector2(0, -50))
	check(bar.value < reading, "native scrollbar drag changes reading position")
	var remembered := bar.value
	approach(B)
	approach(A)
	await frames(4)
	check(not hud._follow and is_equal_approx(bar.value, remembered), "agent switch restores independent scroll and follow")
	var start := panel.get_global_rect()
	await drag(Vector2(start.position.x + 2, start.position.y + 2), Vector2(100, 30))
	check(panel.size.x < start.size.x and panel.size.y < start.size.y, "native top-left corner drag resizes both axes")
	check(panel.get_global_rect().end.is_equal_approx(start.end), "corner drag retains opposite corner")
	var anchor := 1800
	var anchor_line := body.get_character_line(anchor)
	while anchor > 0 and body.get_character_line(anchor - 1) == anchor_line:
		anchor -= 1
	hud._manual_scroll(body.get_line_offset(anchor_line))
	start = panel.get_global_rect()
	await drag(Vector2(start.end.x - 2, start.get_center().y), Vector2(-900, 0))
	check(absf(body.get_v_scroll_bar().value - body.get_line_offset(body.get_character_line(anchor))) < 2, "width reflow preserves the text line being read")
	check(is_equal_approx(panel.size.x, 480), "native right edge drag obeys 480 minimum")
	start = panel.get_global_rect()
	await drag(Vector2(start.get_center().x, start.end.y - 2), Vector2(0, -900))
	check(is_equal_approx(panel.size.y, 260), "native bottom edge drag obeys 260 minimum")
	await check_children("minimum")
	var desired: Vector2 = hud._desired_rect.size
	var window := get_window()
	window.content_scale_size = Vector2i.ZERO
	window.size = Vector2i(320, 180)
	await frames(5)
	check(panel.size.is_equal_approx(Vector2(320, 180)), "small viewport clamps panel below minimum")
	await check_children("small viewport")
	check(hud._desired_rect.size == desired, "temporary viewport clamp retains desired dimensions")
	window.size = Vector2i(1280, 720)
	await frames(5)
	check(panel.size.is_equal_approx(desired), "desktop shrink/grow restores desired dimensions")
	check(not hud._follow, "resize never reenables follow while reading above bottom")
	await check_children("regrown viewport")
	composer.grab_focus()
	var before := sent
	composer.text = "native Enter question"
	composer.text_changed.emit(composer.text)
	await key(KEY_ENTER)
	check(sent == before + 1 and not composer.editable, "native Enter admits exactly one request")
	await key(KEY_TAB)
	check(body.has_focus(), "pending composer skipped in Tab order")
	await key(KEY_TAB, false, true)
	check(body.has_focus(), "pending composer skipped in reverse Tab order")
	await key(KEY_ESCAPE)
	check(get_viewport().gui_get_focus_owner() == null and hud._waiting, "Escape releases focus preserving pending request")
	var pending: String = BridgeClient.conversation_snapshot(A).pending.get("request_id", "")
	reply(A, pending, "done")
	composer.text = "draft survives Escape"
	composer.text_changed.emit(composer.text)
	composer.grab_focus()
	var player_scene = load("res://scenes/player/player.tscn")
	if check(player_scene != null and player_scene.can_instantiate(), "player scene loads"):
		var player = player_scene.instantiate()
		add_child(player)
		var before_position: Vector2 = player.position
		Input.action_press("ui_right")
		await get_tree().physics_frame
		await get_tree().physics_frame
		check(player.position == before_position, "player stays still while GUI owns focus")
		await key(KEY_PAGEDOWN)
		check(player.position == before_position, "paging while composing leaves player still")
		await key(KEY_ESCAPE)
		await get_tree().physics_frame
		await get_tree().physics_frame
		check(player.position.x > before_position.x, "Escape allows world movement again")
		check(composer.text == "draft survives Escape", "Escape preserves draft")
		Input.action_release("ui_right")
		player.queue_free()
	# A synchronous send can return an admitted ID whose pending state is already terminal.
	BridgeClient.set_process(false)
	BridgeClient._socket = WebSocketPeer.new()
	var sync_before := sent
	composer.text = "preserved failed send"
	composer.text_changed.emit(composer.text)
	Engine.print_error_messages = false # Expected closed-socket send fault.
	composer.text_submitted.emit(composer.text)
	Engine.print_error_messages = true
	check(sent == sync_before + 1 and not hud._waiting and composer.editable, "synchronous failed send cannot leave panel waiting")
	check(body.text.contains("preserved failed send") and body.text.contains("Failed to send query"), "synchronous send failure remains visible")
	BridgeClient.conversations._max_bytes = 20
	composer.text = "inadmissible draft".repeat(100)
	composer.text_changed.emit(composer.text)
	check(composer.text != "inadmissible draft".repeat(100) and hud._status_label.visible, "rejected draft restores admitted text with visible error")
	hud._on_query_failed(A, "engine", "Very long error detail. ".repeat(100))
	check(hud._status_label.text.length() <= 256 and hud._status_label.text.contains("[truncated]"), "transient status cannot retain an unbounded legacy error payload")
	await check_children("long status")

func review_regressions() -> void:
	# Review 1: admitted draft changes can evict completed transcript records.
	BridgeClient.conversations = load("res://scenes/bridge/conversation_store.gd").new(AgentRegistry.has_agent, 200, 80)
	BridgeClient.conversations.begin_connection()
	check(BridgeClient.conversations.start_request(A, "draft-old", "Old question"), "draft eviction fixture admits old question")
	BridgeClient.conversations.complete_request(A, "draft-old", 1, "Old retained answer")
	approach(A)
	await frames(3)
	composer.text = "x".repeat(75)
	composer.caret_column = 9
	composer.select(3, 9)
	composer.text_changed.emit(composer.text)
	check(BridgeClient.conversation_snapshot(A).messages.is_empty(), "admitted large draft evicts old messages")
	check(not body.text.contains("Old retained answer") and body.text.contains("Older messages omitted"), "draft eviction immediately updates actual transcript and omission notice")
	check(composer.caret_column == 9 and composer.get_selection_from_column() == 3 and composer.get_selection_to_column() == 9, "draft eviction preserves native caret and selection")
	# Preserve an ongoing reveal when older records, but not that reply, are evicted.
	BridgeClient.conversations = load("res://scenes/bridge/conversation_store.gd").new(AgentRegistry.has_agent, 200, 240)
	BridgeClient.conversations.begin_connection()
	BridgeClient.conversations.start_request(A, "reveal-old", "old user")
	BridgeClient.conversations.complete_request(A, "reveal-old", 1, "OLD-".repeat(15))
	BridgeClient.conversations.start_request(A, "reveal-kept", "new user")
	approach(A)
	BridgeClient.conversations.complete_request(A, "reveal-kept", 1, "NEW-".repeat(25))
	GameEvents.conversation_changed.emit(A, "reply", "reveal-kept")
	await frames(5)
	var before_span: Dictionary = hud.current_assistant_span()
	var progress := body.visible_characters - int(before_span.start)
	composer.text = "d".repeat(100)
	composer.caret_column = 12
	composer.select(4, 12)
	composer.text_changed.emit(composer.text)
	var after_span: Dictionary = hud.current_assistant_span()
	check(BridgeClient.conversation_snapshot(A).messages.size() == 2 and not body.text.contains("OLD-"), "draft eviction retains only the new exchange in label")
	check(body.visible_characters - int(after_span.start) == progress and body.visible_characters < after_span.start + after_span.length, "draft transcript refresh preserves exact reveal progress")
	check(composer.caret_column == 12 and composer.get_selected_text() == "d".repeat(8), "draft transcript refresh keeps composer selection")
	await frames(5)
	check(body.visible_characters - int(after_span.start) > progress, "preserved reveal keeps advancing after draft eviction")
	# Review 2: another agent can resize this shared panel while A is hidden.
	BridgeClient.conversations = load("res://scenes/bridge/conversation_store.gd").new(AgentRegistry.has_agent, 200, 1048576)
	BridgeClient.conversations.begin_connection()
	BridgeClient.conversations.start_request(A, "hidden-resize", "Long question")
	BridgeClient.conversations.complete_request(A, "hidden-resize", 1, ("A long wrapping line for an identifiable reading position. ".repeat(3) + "\n").repeat(100))
	hud._desired_rect = Rect2(24, 300, 1000, 320)
	hud._apply_geometry()
	approach(A)
	await frames(4)
	var anchor := 1800
	var line := body.get_character_line(anchor)
	while anchor > 0 and body.get_character_line(anchor - 1) == line:
		anchor -= 1
	hud._manual_scroll(body.get_line_offset(line))
	approach(B)
	await frames(3)
	var rect := panel.get_global_rect()
	await drag(Vector2(rect.end.x - 2, rect.get_center().y), Vector2(-800, 0))
	approach(A)
	await frames(4)
	check(absf(body.get_v_scroll_bar().value - body.get_line_offset(body.get_character_line(anchor))) < 2 and not hud._follow, "A B resize A restores the same content anchor after wrapping")
	approach(B)
	BridgeClient.conversations._max_bytes = 80
	check(BridgeClient.set_draft(A, "z".repeat(75)), "hidden draft can evict anchor message")
	approach(A)
	await frames(4)
	check(body.text.contains("Older messages omitted") and body.get_v_scroll_bar().value == 0 and not hud._follow, "evicted hidden content anchor falls back to oldest retained text without following")
	# Stable message identity also survives earlier-history eviction; if the
	# read message itself is evicted, newer retained text must not inherit its offset.
	for evict_read_message in [false, true]:
		BridgeClient.conversations = load("res://scenes/bridge/conversation_store.gd").new(AgentRegistry.has_agent, 200, 1048576)
		BridgeClient.conversations.begin_connection()
		var older := ("OLDER paragraph for history eviction and reading. ".repeat(3) + "\n").repeat(50)
		var newer := ("NEWER paragraph that remains after older history eviction. ".repeat(3) + "\n").repeat(50)
		BridgeClient.conversations.start_request(A, "anchor-first", "First question")
		BridgeClient.conversations.complete_request(A, "anchor-first", 1, older)
		BridgeClient.conversations.start_request(A, "anchor-second", "Second question")
		BridgeClient.conversations.complete_request(A, "anchor-second", 1, newer)
		approach(A)
		await frames(4)
		var content_start := body.text.find(older if evict_read_message else newer)
		var character := content_start + 1800
		var reading_line := body.get_character_line(character)
		while body.get_character_line(character - 1) == reading_line:
			character -= 1
		var relative := character - content_start
		hud._manual_scroll(body.get_line_offset(reading_line))
		approach(B)
		BridgeClient.conversations._max_bytes = BridgeClient.conversation_snapshot(A).content_bytes + 99
		check(BridgeClient.set_draft(A, "f".repeat(100)), "hidden draft evicts only older exchange")
		approach(A)
		await frames(4)
		check(BridgeClient.conversation_snapshot(A).messages.size() == 2 and not body.text.contains("OLDER"), "hidden eviction keeps newer exchange and drops older display")
		var expected := 0.0 if evict_read_message else body.get_line_offset(body.get_character_line(body.text.find(newer) + relative))
		check(absf(body.get_v_scroll_bar().value - expected) < 2 and not hud._follow, "message anchor resolves after eviction; anchor removed=%s" % evict_read_message)
	# Review 3: required identity and controls stay visible below 160px height.
	hud._on_query_failed(A, "test", "A long status that needs compact layout. ".repeat(10))
	for extent in [Vector2i(320, 140), Vector2i(200, 100)]:
		get_window().size = extent
		await frames(5)
		check(panel.size.is_equal_approx(Vector2(extent)), "tiny viewport clamps outer panel %s" % extent)
		await check_children("required tiny layout %s" % extent)
		check(hud._name_label.text == AgentRegistry.get_agent(A).name and not hud._role_label.text.is_empty(), "tiny layout retains NPC identity and role")
		check(body.size.y >= 12 and composer.size.y >= 20, "tiny transcript and composer retain usable positive heights")
		check(hud._status_label.is_visible_in_tree() and hud._status_label.size.y > 0, "tiny status remains visible and reachable")
		body.grab_focus()
		mouse(MOUSE_BUTTON_LEFT, composer.get_global_rect().get_center(), true)
		mouse(MOUSE_BUTTON_LEFT, composer.get_global_rect().get_center(), false)
		await key(KEY_HOME)
		check(composer.has_focus() and composer.caret_column == 0, "tiny composer remains keyboard reachable")
	get_window().size = Vector2i(1280, 720)
	await frames(4)

func key(code: Key, ctrl: bool = false, shift: bool = false) -> void:
	var event := InputEventKey.new()
	event.keycode = code
	event.ctrl_pressed = ctrl
	event.shift_pressed = shift
	event.pressed = true
	get_viewport().push_input(event, true)
	event = event.duplicate()
	event.pressed = false
	get_viewport().push_input(event, true)
	await frames(3)

func mouse(button: MouseButton, point: Vector2, pressed: bool) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = button
	event.position = point
	event.global_position = point
	event.pressed = pressed
	get_viewport().push_input(event, true)

func wheel(button: MouseButton, point: Vector2) -> void:
	mouse(button, point, true)
	mouse(button, point, false)
	await frames(3)

func drag(point: Vector2, delta: Vector2) -> void:
	mouse(MOUSE_BUTTON_LEFT, point, true)
	var motion := InputEventMouseMotion.new()
	motion.position = point + delta
	motion.global_position = motion.position
	motion.relative = delta
	motion.button_mask = MOUSE_BUTTON_MASK_LEFT
	get_viewport().push_input(motion, true)
	mouse(MOUSE_BUTTON_LEFT, point + delta, false)
	await frames(4)

func check_children(label: String) -> void:
	await frames(3)
	var bounds := panel.get_global_rect().grow(0.1)
	for path in ["Margin", "Margin/Rows", "Margin/Rows/Header", "Margin/Rows/Header/Titles", "Margin/Rows/Header/Titles/NameLabel", "Margin/Rows/Header/Titles/RoleLabel", "Margin/Rows/BodyLabel", "Margin/Rows/InputRow", "Margin/Rows/InputRow/QuestionInput", "Margin/Rows/StatusLabel"]:
		var child: Control = panel.get_node(path)
		if path != "Margin/Rows/StatusLabel":
			check(child.is_visible_in_tree(), "%s: required %s is visible" % [label, path])
		if child.is_visible_in_tree():
			check(bounds.encloses(child.get_global_rect()), "%s: actual %s rect fits panel %s / %s" % [label, path, bounds, child.get_global_rect()])


func scrollbar_thumb_center(bar: VScrollBar) -> Vector2:
	var decrement := bar.get_theme_icon("decrement").get_height()
	var increment := bar.get_theme_icon("increment").get_height()
	var track := bar.size.y - decrement - increment
	var thumb := maxf(bar.get_theme_stylebox("grabber").get_minimum_size().y, track * bar.page / (bar.max_value - bar.min_value))
	var ratio := (bar.value - bar.min_value) / maxf(1, bar.max_value - bar.min_value - bar.page)
	return bar.global_position + Vector2(bar.size.x / 2, decrement + (track - thumb) * ratio + thumb / 2)
