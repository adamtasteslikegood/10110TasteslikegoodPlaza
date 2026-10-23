extends RefCounted

static func native_reveal_checks(test: Node) -> void:
	# A real production panel owns the renderer. A SubViewport gives headless
	# input a genuine pointer position; X11 uses the default product viewport.
	var viewport: Viewport = test.get_viewport()
	var isolated: SubViewport
	if DisplayServer.get_name() == "headless":
		isolated = SubViewport.new()
		isolated.size = Vector2i(1280, 720)
		test.add_child(isolated)
		viewport = isolated
	var hud: Node = load("res://scenes/hud/dialogue_panel.tscn").instantiate()
	(viewport if isolated != null else test).add_child(hud)
	hud.set_process(false)
	hud._on_npc_approached("fixture-extra-a", AgentRegistry.get_agent("fixture-extra-a"))
	var body: RichTextLabel = hud.get_node("Panel/Margin/Rows/BodyLabel")
	var prefix := "Visible partial"
	var answer := prefix + "SECRET\nNEVER revealed paragraph"
	var request := "native-reveal-fixture"
	hud._render({"messages": [{"generation": 1, "role": "assistant", "content": answer, "status": "completed", "request_id": request}], "pending": {}, "draft": "", "connected": true, "generation": 1}, request, 0)
	hud._process((prefix.length() + 0.1) / hud.CHARS_PER_SECOND)
	await test.frames(3)
	var span: Dictionary = hud.current_assistant_span()
	var expected: String = hud._full_text.left(int(span.start) + prefix.length())
	test.check(body.get_parsed_text() == expected, "native reveal: selectable panel stores only currently revealed prefix")
	var font := body.get_theme_font("normal_font")
	var font_size := body.get_theme_font_size("normal_font_size")
	var line := body.get_character_line(span.start)
	var y := body.get_line_offset(line) + body.get_line_height(line) / 2 - body.get_v_scroll_bar().value
	var word_x := font.get_string_size("Visible ", HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x
	word_x += font.get_string_size("partial", HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x / 2
	var word_point := body.global_position + Vector2(word_x, y)
	seed_native_selection()
	await pointer_button(test, viewport, word_point, true, true)
	await pointer_button(test, viewport, word_point, false)
	test.check(body.get_selected_text() == "partial", "native reveal: partial-word double click selects only revealed word")
	await checkpoint(test, "native-partial-word-primary", "partial", "primary")
	await checkpoint(test, "native-partial-word-clipboard", "native selection clipboard sentinel")
	# Refresh native double-click timing immediately before the following single
	# click, so it is a real triple click even after an external checkpoint read.
	await pointer_button(test, viewport, word_point, true, true)
	await pointer_button(test, viewport, word_point, false)
	seed_native_selection()
	await pointer_button(test, viewport, word_point, true)
	await pointer_button(test, viewport, word_point, false)
	test.check(body.get_selected_text() == prefix, "native reveal: paragraph triple click excludes unrevealed suffix and newline")
	await checkpoint(test, "native-partial-paragraph-primary", prefix, "primary")
	await checkpoint(test, "native-partial-paragraph-clipboard", "native selection clipboard sentinel")
	body.deselect()
	# Start two characters in, beyond the panel's real left resize grip.
	var selected_prefix := prefix.substr(2)
	var start := body.global_position + Vector2(font.get_string_size(prefix.left(2), HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x, y)
	var end := body.global_position + Vector2(font.get_string_size(prefix, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x - 1, y)
	seed_native_selection()
	await pointer_button(test, viewport, start, true)
	await pointer_motion(test, viewport, start, end)
	gesture_diagnostic(body, "held", end)
	test.check(body.get_selected_text() == selected_prefix, "native reveal: ordinary held drag genuinely selects revealed text")
	# Continue across the blank next line where the old full buffer stored an
	# entirely hidden paragraph, then release before any explicit Copy action.
	var blank := end + Vector2(0, body.get_line_height(line) * 1.2)
	await pointer_motion(test, viewport, end, blank)
	await pointer_button(test, viewport, blank, false)
	gesture_diagnostic(body, "released", blank)
	if DisplayServer.get_name() != "headless":
		test.check(viewport.get_mouse_position().distance_to(blank) < 2, "native reveal: desktop physical pointer matches viewport drag endpoint")
	test.check(body.get_selected_text() == selected_prefix, "native reveal: blank-line drag/release cannot select hidden paragraph")
	await checkpoint(test, "native-partial-drag-release-primary", selected_prefix, "primary")
	await checkpoint(test, "native-partial-drag-release-clipboard", "native selection clipboard sentinel")
	hud._process(3.0 / hud.CHARS_PER_SECOND)
	await test.frames(2)
	test.check(body.get_parsed_text() == expected + "SEC" and body.get_selected_text() == selected_prefix, "native reveal: append preserves existing mouse selection while reveal advances")
	hud._on_npc_approached("systems-architect", AgentRegistry.get_agent("systems-architect"))
	var changed := body.get_parsed_text()
	hud._follow = false
	hud._process(10)
	test.check(body.get_parsed_text() == changed and not changed.contains("SECRET"), "native reveal: identity/status change cannot append previous hidden reply")
	hud.queue_free()
	if isolated != null: isolated.queue_free()
	await test.frames(2)

static func gesture_diagnostic(body: RichTextLabel, phase: String, expected_pointer: Vector2) -> void:
	if OS.get_environment("PLAZA_CLIPBOARD_PROBE_DIR").is_empty(): return
	print("CLIPBOARD_GESTURE " + JSON.stringify({"phase": phase, "selected": body.get_selected_text(), "expected_pointer": expected_pointer, "actual_pointer": body.get_viewport().get_mouse_position(), "window_position": DisplayServer.window_get_position(body.get_window().get_window_id())}))

static func seed_native_selection() -> void:
	DisplayServer.clipboard_set("native selection clipboard sentinel")
	if DisplayServer.has_feature(DisplayServer.FEATURE_CLIPBOARD_PRIMARY):
		DisplayServer.clipboard_set_primary("native selection primary sentinel")

static func pointer_button(test: Node, viewport: Viewport, point: Vector2, pressed: bool, double_click: bool = false) -> void:
	if DisplayServer.get_name() != "headless":
		# Viewport converts to window-relative warp coordinates. XTest's root-
		# screen coordinates include window position, but Input.warp_mouse must not.
		viewport.warp_mouse(point)
	var event := InputEventMouseButton.new()
	event.position = point
	event.global_position = point
	event.button_index = MOUSE_BUTTON_LEFT
	event.pressed = pressed
	event.double_click = double_click
	viewport.push_input(event, true)
	await test.frames(1)

static func pointer_motion(test: Node, viewport: Viewport, start: Vector2, end: Vector2) -> void:
	if DisplayServer.get_name() != "headless":
		viewport.warp_mouse(end)
	var event := InputEventMouseMotion.new()
	event.position = end
	event.global_position = end
	event.relative = end - start
	event.button_mask = MOUSE_BUTTON_MASK_LEFT
	viewport.push_input(event, true)
	# RichTextLabel's native held-click timer updates its selection every 50 ms.
	await test.get_tree().create_timer(0.08).timeout
	await test.frames(2)

## Runs against both production panels. Desktop checkpoints are independently
## read by scripts/check_chat_clipboard.py; headless runs never claim OS proof.
static func run(test: Node, hud: Node, body: RichTextLabel, composer: LineEdit, copy_path: String, select_path: String) -> void:
	if not test.check(hud.has_node(copy_path) and hud.has_node(select_path), "clipboard: real panel exposes Copy and Select All"):
		return
	var copy_button: Button = hud.get_node(copy_path)
	var select_button: Button = hud.get_node(select_path)
	var helper: Node = body.get_node("TranscriptClipboard")
	var full := body.get_parsed_text()
	var original_visible := body.visible_characters
	var was_processing := hud.is_processing()
	hud.set_process(false)
	var original_draft := composer.text
	if composer.editable and composer.text.is_empty():
		composer.text = "Clipboard composer draft ✓"
		composer.text_changed.emit(composer.text)
	var draft := composer.text
	var commands: Dictionary = BridgeClient.domains._commands.duplicate(true)
	var request_counter: int = BridgeClient._request_counter
	var pending: Dictionary = BridgeClient.domain_snapshot("core").pending_query.duplicate(true)
	var owner: String = BridgeClient.surface.owner
	var generation: String = BridgeClient.domain_snapshot("core").domain_session_id
	await test.frames(3)
	test.check(full.contains("✓\n雪"), "clipboard: actual renderer retains Unicode and newlines")
	test.check(copy_button.is_visible_in_tree() and not copy_button.disabled and not select_button.disabled, "clipboard: controls available for displayed history")
	test.check(not body.context_menu_enabled and composer.context_menu_enabled, "clipboard: transcript has controlled menu and composer keeps native menu")
	test.check(not body.drag_and_drop_selection_enabled, "clipboard: native selected-text export cannot carry hidden suffix")
	# Make hidden text include real rendered output, rather than only a fixture
	# string tested independently of its panel.
	var limit := maxi(1, full.find("✓") + 1)
	body.visible_characters = limit
	body.deselect()
	await test.frames(2)
	await click(test, copy_button)
	test.check(helper.text_to_copy() == full.left(limit), "clipboard: no-selection Copy uses revealed rendered prefix")
	await checkpoint(test, "button-prefix", full.left(limit))
	body.grab_focus()
	await shortcut(test, body.get_viewport(), "ui_copy")
	await checkpoint(test, "keyboard-fallback-prefix", full.left(limit))
	# Native Select All includes the hidden suffix internally. Every copy action
	# must clamp it before any clipboard setter runs.
	await click(test, select_button)
	test.check(body.has_focus() and not body.get_selected_text().is_empty(), "clipboard: Select All highlights and focuses transcript")
	test.check(helper.text_to_copy() == full.left(limit), "clipboard: native whole-string selection clamps hidden suffix")
	# X11's native selected-text drag attempt can publish the entire stored
	# selection to PRIMARY on release. A fresh sentinel and independent target
	# read verify the real panel's selected-click path before reselecting it.
	DisplayServer.clipboard_set("clipboard selection sentinel")
	if DisplayServer.has_feature(DisplayServer.FEATURE_CLIPBOARD_PRIMARY):
		DisplayServer.clipboard_set_primary("primary selection sentinel")
	await reveal_control(test, body)
	await native_click(test, body.get_global_rect().position + Vector2(30, 12))
	test.check(body.get_selected_text().is_empty(), "clipboard: selected click clears selection without exporting stored suffix")
	await checkpoint(test, "native-selected-click-clipboard", "clipboard selection sentinel")
	await checkpoint(test, "native-selected-click-primary", "primary selection sentinel", "primary")
	await click(test, select_button)
	await shortcut(test, body.get_viewport(), "ui_copy")
	await checkpoint(test, "keyboard-prefix", full.left(limit))
	await click(test, copy_button)
	test.check(not body.get_selected_text().is_empty(), "clipboard: button focus preserves native selection")
	await checkpoint(test, "selected-button-prefix", full.left(limit))
	var old_scale := body.scale
	body.scale = Vector2(1.25, 1.25)
	await reveal_control(test, body)
	var local_point := Vector2(30, 12)
	await mouse(test, body.get_global_transform() * local_point, MOUSE_BUTTON_RIGHT)
	var scaled_menu: PopupMenu = helper.get_node("ClipboardMenu")
	test.check(Vector2(scaled_menu.position).distance_to(body.get_screen_transform() * local_point) < 2, "clipboard: right-click menu follows scaled transcript position")
	body.scale = old_scale
	await menu_action(test, scaled_menu, 0)
	await checkpoint(test, "scaled-menu-prefix", full.left(limit))
	body.grab_focus()
	await shortcut(test, body.get_viewport(), "ui_text_select_all")
	await shortcut(test, body.get_viewport(), "ui_copy")
	await checkpoint(test, "native-select-all-prefix", full.left(limit))
	await reveal_control(test, body)
	await mouse(test, body.get_global_rect().position + Vector2(30, 12), MOUSE_BUTTON_RIGHT)
	await menu_action(test, helper.get_node("ClipboardMenu"), 0)
	await checkpoint(test, "menu-prefix", full.left(limit))
	body.grab_focus()
	await shortcut(test, body.get_viewport(), "ui_menu")
	test.check(helper.get_node("ClipboardMenu").visible, "clipboard: platform menu shortcut opens transcript menu")
	await menu_action(test, helper.get_node("ClipboardMenu"), 0)
	await checkpoint(test, "keyboard-menu-prefix", full.left(limit))
	body.grab_focus()
	await key_event(test, body.get_viewport(), InputMap.action_get_events("chat_focus_next")[0])
	DisplayServer.clipboard_set("clipboard action sentinel")
	await shortcut(test, body.get_viewport(), "ui_accept")
	await checkpoint(test, "keyboard-button-prefix", full.left(limit))
	# Ctrl+Insert is another standard ui_copy binding on Linux. Use all engine
	# bindings so platform mappings, including Command on macOS, stay native.
	for binding in InputMap.action_get_events("ui_copy"):
		if binding is InputEventKey:
			body.grab_focus()
			DisplayServer.clipboard_set("clipboard action sentinel")
			await key_event(test, body.get_viewport(), binding)
			await checkpoint(test, "copy-binding", full.left(limit))
	var bar := body.get_v_scroll_bar()
	bar.value = 0
	body.deselect()
	body.visible_characters = -1
	await test.frames(2)
	# A native double click gives a genuine partial mouse selection. The expected
	# payload comes from that selection, not from the helper under test.
	await reveal_control(test, body)
	var expected_word := await select_word(test, body)
	var selected := body.get_selected_text()
	test.check(selected == expected_word and not selected.is_empty() and selected.length() < full.length(), "clipboard: native mouse selects a transcript word")
	var reading := bar.value
	await click(test, copy_button)
	test.check(body.get_selected_text() == selected and helper.text_to_copy() == selected, "clipboard: selected text wins over full transcript")
	await checkpoint(test, "selected-word-button", selected)
	await reveal_control(test, body)
	await mouse(test, body.get_global_rect().position + Vector2(30, 12), MOUSE_BUTTON_RIGHT)
	var menu: PopupMenu = helper.get_node("ClipboardMenu")
	test.check(menu.visible and menu.item_count == 2 and menu.get_item_text(0) == "Copy" and menu.get_item_text(1) == "Select All", "clipboard: right click opens bounded transcript menu")
	test.check(body.get_selected_text() == selected, "clipboard: right click preserves selection")
	await menu_action(test, menu, 0)
	await checkpoint(test, "selected-word-menu", selected)
	await reveal_control(test, body)
	await mouse(test, body.get_global_rect().position + Vector2(30, 12), MOUSE_BUTTON_RIGHT)
	await menu_action(test, menu, 1)
	test.check(body.has_focus() and helper.text_to_copy() == full, "clipboard: menu Select All keeps keyboard Copy usable")
	await shortcut(test, body.get_viewport(), "ui_copy")
	await checkpoint(test, "menu-select-all-copy", full)
	test.check(is_equal_approx(bar.value, reading), "clipboard: actions preserve reading scroll")
	# Composer shortcuts remain scoped to its editable text even with a retained
	# transcript selection. They must never run the transcript copy callback.
	if composer.editable:
		composer.grab_focus()
		composer.select_all()
		await shortcut(test, composer.get_viewport(), "ui_copy")
		await checkpoint(test, "native-composer-copy", draft)
		test.check(composer.text == draft and composer.get_selected_text() == draft, "clipboard: composer keeps native editing selection")
	body.visible_characters = 0
	await test.frames(2)
	test.check(copy_button.disabled and select_button.disabled and helper.text_to_copy().is_empty(), "clipboard: unrevealed empty transcript disables controls")
	body.grab_focus()
	await shortcut(test, body.get_viewport(), "ui_copy")
	await checkpoint(test, "empty-reveal-copy", "clipboard action sentinel")
	body.visible_characters = -1
	await test.frames(2)
	var saved := body.get_parsed_text()
	body.text = ""
	await test.frames(2)
	test.check(copy_button.disabled and select_button.disabled, "clipboard: empty transcript disables controls")
	body.grab_focus()
	await key_event(test, body.get_viewport(), InputMap.action_get_events("chat_focus_next")[0])
	test.check(not copy_button.has_focus() and not select_button.has_focus(), "clipboard: Tab skips disabled clipboard controls")
	body.text = saved
	body.visible_characters = original_visible
	await test.frames(2)
	test.check(composer.text == draft and BridgeClient.surface.owner == owner and BridgeClient.domains._commands == commands and BridgeClient._request_counter == request_counter and BridgeClient.domain_snapshot("core").pending_query == pending and BridgeClient.domain_snapshot("core").domain_session_id == generation, "clipboard: actions preserve draft, ownership and execution controls")
	# Both new buttons participate in the panel's explicit focus traversal.
	body.grab_focus()
	await key_event(test, body.get_viewport(), InputMap.action_get_events("chat_focus_next")[0])
	test.check(copy_button.has_focus(), "clipboard: Tab reaches Copy")
	await key_event(test, body.get_viewport(), InputMap.action_get_events("chat_focus_next")[0])
	test.check(select_button.has_focus(), "clipboard: Tab reaches Select All")
	if composer.text != original_draft:
		composer.text = original_draft
		composer.text_changed.emit(composer.text)
	hud.set_process(was_processing)

static func snapshot(test: Node, name: String) -> void:
	var directory := OS.get_environment("PLAZA_CLIPBOARD_SCREENSHOT_DIR")
	if directory.is_empty(): return
	await RenderingServer.frame_post_draw
	var path := directory.path_join(name.validate_filename() + ".png")
	test.check(test.get_viewport().get_texture().get_image().save_png(path) == OK, "clipboard: desktop screenshot saved " + name)

static func stale_action(test: Node, body: RichTextLabel, change: Callable, description: String) -> void:
	body.grab_focus()
	body.select_all()
	await reveal_control(test, body)
	await mouse(test, body.get_global_rect().position + Vector2(30, 12), MOUSE_BUTTON_RIGHT)
	var menu: PopupMenu = body.get_node("TranscriptClipboard/ClipboardMenu")
	test.check(menu.visible, "clipboard: popup open before " + description)
	var sentinel := "clipboard scope sentinel ✓"
	DisplayServer.clipboard_set(sentinel)
	change.call()
	await test.frames(2)
	test.check(not menu.visible and body.get_selection_from() == -1, "clipboard: stale menu and selection invalidated on " + description)
	# A queued callback from the dismissed menu cannot copy the replacement
	# identity's text. Actual visible-menu activation is tested above.
	menu.id_pressed.emit(0)
	await checkpoint(test, "stale-" + description, sentinel)

static func click(test: Node, control: Control) -> void:
	await reveal_control(test, control)
	if control.name == "Copy": DisplayServer.clipboard_set("clipboard action sentinel")
	await mouse(test, control.get_global_rect().get_center(), MOUSE_BUTTON_LEFT)

static func reveal_control(test: Node, control: Control) -> void:
	var ancestor := control.get_parent()
	while ancestor != null:
		if ancestor is ScrollContainer:
			ancestor.ensure_control_visible(control)
			await test.frames(2)
		ancestor = ancestor.get_parent()

static func select_word(test: Node, body: RichTextLabel) -> String:
	# Compute a point inside a real first-line word; a fixed x can land on a
	# status-label separator and correctly produce no native word selection.
	var words := RegEx.new()
	words.compile("[A-Za-z]{2,}")
	var match := words.search(body.get_parsed_text().get_slice("\n", 0))
	if match == null:
		test.check(false, "clipboard: synthetic renderer supplies a selectable word")
		return ""
	var font := body.get_theme_font("normal_font")
	var font_size := body.get_theme_font_size("normal_font_size")
	var prefix := body.get_parsed_text().left(match.get_start())
	var x := font.get_string_size(prefix, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x
	x += font.get_string_size(match.get_string(), HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x / 2
	var y := body.get_line_offset(0) + body.get_line_height(0) / 2 - body.get_v_scroll_bar().value
	await mouse(test, body.get_global_rect().position + Vector2(x, y), MOUSE_BUTTON_LEFT, true)
	return match.get_string()

static func mouse(test: Node, position: Vector2, button: MouseButton, double_click: bool = false) -> void:
	for pressed in [true, false]:
		var event := InputEventMouseButton.new()
		event.position = position
		event.global_position = position
		event.button_index = button
		event.pressed = pressed
		event.double_click = double_click and pressed
		test.get_viewport().push_input(event, true)
	await test.frames(2)

static func native_click(test: Node, position: Vector2) -> void:
	# Selected-click export consults Input's mouse state as well as the GUI
	# event. Enter through Input, as a real platform mouse event does.
	for pressed in [true, false]:
		var event := InputEventMouseButton.new()
		event.window_id = test.get_window().get_window_id()
		event.position = position
		event.global_position = position
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		if DisplayServer.get_name() == "headless":
			# Headless has no platform pointer. Exercise native GUI handling;
			# the X11 driver below uses the real Input singleton event path.
			test.get_viewport().push_input(event, true)
		else:
			Input.parse_input_event(event)
			Input.flush_buffered_events()
		await test.frames(1)

static func shortcut(test: Node, viewport: Viewport, action: String) -> void:
	if action == "ui_copy": DisplayServer.clipboard_set("clipboard action sentinel")
	for binding in InputMap.action_get_events(action):
		if binding is InputEventKey:
			await key_event(test, viewport, binding)
			return
	test.check(false, "clipboard: engine provides " + action)

static func key_event(test: Node, viewport: Viewport, binding: InputEventKey) -> void:
	for pressed in [true, false]:
		var event := binding.duplicate() as InputEventKey
		event.pressed = pressed
		viewport.push_input(event, true)
	await test.frames(2)

static func menu_action(test: Node, menu: PopupMenu, index: int) -> void:
	# Exercise PopupMenu's actual native keyboard activation, not id_pressed.emit.
	if index == 0: DisplayServer.clipboard_set("clipboard action sentinel")
	menu.set_focused_item(index)
	var enter := InputEventKey.new()
	enter.keycode = KEY_ENTER
	await key_event(test, test.get_viewport(), enter)

static func checkpoint(test: Node, name: String, expected: String, selection: String = "clipboard") -> void:
	var directory := OS.get_environment("PLAZA_CLIPBOARD_PROBE_DIR")
	if directory.is_empty(): return
	var path := directory.path_join("checkpoint.json")
	var file := FileAccess.open(path + ".tmp", FileAccess.WRITE)
	file.store_string(JSON.stringify({"name": name, "expected": expected, "selection": selection}))
	file.close()
	DirAccess.rename_absolute(path + ".tmp", path)
	var deadline := Time.get_ticks_msec() + 5000
	while FileAccess.file_exists(path) and Time.get_ticks_msec() < deadline:
		await test.get_tree().process_frame
	test.check(not FileAccess.file_exists(path), "clipboard: independent desktop read completed " + name)
