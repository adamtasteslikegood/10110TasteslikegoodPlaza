extends CharacterBody2D

## Top-down 8-direction movement (D-001). No gravity, no jump -- this is a floor
## plan, not a platformer.

@export var speed: float = 220.0


func _physics_process(_delta: float) -> void:
	if get_viewport().gui_get_focus_owner() != null:
		velocity = Vector2.ZERO
	else:
		velocity = _input_vector() * speed
	move_and_slide()


func _input_vector() -> Vector2:
	# ui_* are engine built-ins bound to the arrow keys, so a fresh checkout is
	# playable with no input-map setup. WASD is polled by physical keycode rather
	# than added to the input map: the [input] block in project.godot serialises
	# key events as inline Object(...) literals whose fields have moved between
	# engine versions, and a malformed one fails silently rather than loudly.
	var arrows := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	var wasd := Vector2(
		float(Input.is_physical_key_pressed(KEY_D)) - float(Input.is_physical_key_pressed(KEY_A)),
		float(Input.is_physical_key_pressed(KEY_S)) - float(Input.is_physical_key_pressed(KEY_W))
	)
	return (arrows + wasd).limit_length(1.0)
