extends Node

## Callers store only the revealed prefix: native mouse selection can publish
## PRIMARY without a Copy event. Clamp explicit Copy paths as an extra boundary.
var _label: RichTextLabel
var _copy: Button
var _select: Button
var _menu: PopupMenu
var _menu_valid := false

func _init(label: RichTextLabel, copy_button: Button, select_button: Button) -> void:
	name = "TranscriptClipboard"
	_label = label
	_copy = copy_button
	_select = select_button
	_label.context_menu_enabled = false
	_label.deselect_on_focus_loss_enabled = false
	# Native selected-text export can publish the stored, unrevealed suffix to
	# X11 PRIMARY or an external drag target before our Copy handler runs.
	_label.drag_and_drop_selection_enabled = false
	_label.gui_input.connect(_gui_input)
	_label.visibility_changed.connect(func():
		if not _label.is_visible_in_tree(): invalidate())
	_copy.pressed.connect(_copy_text)
	_select.pressed.connect(_select_all)
	_menu = PopupMenu.new()
	_menu.name = "ClipboardMenu"
	_menu.add_item("Copy", 0)
	_menu.add_item("Select All", 1)
	_menu.id_pressed.connect(_menu_selected)
	add_child(_menu)

func _process(_delta: float) -> void:
	var empty := _label.visible_characters == 0 or _label.get_total_character_count() == 0
	for button in [_copy, _select]:
		button.disabled = empty
		button.focus_mode = Control.FOCUS_NONE if empty else Control.FOCUS_ALL
		if empty and button.has_focus(): button.release_focus()

func _visible_text() -> String:
	var text := _label.get_parsed_text()
	return text if _label.visible_characters < 0 else text.left(_label.visible_characters)

func text_to_copy() -> String:
	var text := _visible_text()
	var start := _label.get_selection_from()
	if start < 0: return text
	# Selection endpoints are inclusive Unicode character offsets. Clamp before
	# passing anything to DisplayServer, including a native Select All selection.
	var end := mini(_label.get_selection_to() + 1, text.length())
	return text.substr(start, maxi(0, end - start))

func _copy_text() -> void:
	if not _label.is_visible_in_tree(): return
	var text := text_to_copy()
	if not text.is_empty(): DisplayServer.clipboard_set(text)

func _select_all() -> void:
	if not _label.is_visible_in_tree() or _visible_text().is_empty(): return
	var scroll := _label.get_v_scroll_bar().value
	_label.grab_focus()
	_label.select_all()
	_label.get_v_scroll_bar().value = scroll

func invalidate() -> void:
	_menu_valid = false
	_menu.hide()
	_label.deselect()

func _popup(position: Vector2) -> void:
	_menu_valid = true
	var empty := _visible_text().is_empty()
	_menu.set_item_disabled(0, empty)
	_menu.set_item_disabled(1, empty)
	_menu.position = Vector2i(position)
	_menu.popup()

func _menu_selected(id: int) -> void:
	if not _menu_valid or not _label.is_visible_in_tree(): return
	_menu_valid = false
	if id == 0: _copy_text()
	elif id == 1: _select_all()

func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_RIGHT:
		if event.pressed: _popup(_label.get_screen_transform() * event.position)
		_label.accept_event()
	elif event.is_action_pressed("ui_copy", false, true):
		_copy_text()
		_label.accept_event()
	elif event.is_action_pressed("ui_text_select_all", false, true):
		_select_all()
		_label.accept_event()
	elif event.is_action_pressed("ui_menu", false, true):
		_popup(_label.get_screen_position())
		_label.accept_event()
