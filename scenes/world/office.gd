extends Node2D

## The Day 1 greybox: lobby, a short corridor, and the server room.
##
## SB-04 puts the player alone in the lobby with freedom to explore; SB-05 puts the
## Systems Architect in the server room. Those two spaces are the whole of Round 3.
## The remaining Week-1 rooms are M2, which specs/roadmap.md marks as off the
## critical path (M1 -> M4 -> M8).
##
## Geometry is built from the tables below rather than hand-placed in the .tscn.
## Grey-boxing is a measuring exercise -- you move a wall, run, and look again --
## and a named rect in a diff is far easier to review and adjust than a screenful
## of generated node entries.

const WALL_THICKNESS := 20.0

const FLOOR_COLOR_LOBBY := Color(0.20, 0.20, 0.24)
const FLOOR_COLOR_CORRIDOR := Color(0.17, 0.17, 0.21)
const FLOOR_COLOR_SERVER := Color(0.16, 0.19, 0.22)
const WALL_COLOR := Color(0.38, 0.38, 0.43)

## Walkable areas, purely visual.
const FLOORS: Array[Dictionary] = [
	{"rect": Rect2(0, 0, 640, 480), "color": FLOOR_COLOR_LOBBY},
	{"rect": Rect2(640, 190, 120, 100), "color": FLOOR_COLOR_CORRIDOR},
	{"rect": Rect2(760, 0, 440, 480), "color": FLOOR_COLOR_SERVER},
]

## Solid geometry. Each rect becomes a StaticBody2D plus a matching visual, so
## what you see and what you collide with cannot drift apart.
const WALLS: Array[Rect2] = [
	# Lobby shell, with a gap on the right for the corridor mouth.
	Rect2(-20, -20, 680, 20),
	Rect2(-20, 480, 680, 20),
	Rect2(-20, 0, 20, 480),
	Rect2(640, 0, 20, 190),
	Rect2(640, 290, 20, 190),
	# Corridor.
	Rect2(640, 170, 120, 20),
	Rect2(640, 290, 120, 20),
	# Server room shell, with the matching gap on its left.
	Rect2(760, -20, 460, 20),
	Rect2(760, 480, 460, 20),
	Rect2(1200, 0, 20, 480),
	Rect2(740, 0, 20, 170),
	Rect2(740, 290, 20, 190),
]

## The corridor mouth. Consults GameState before letting the player through.
const DOOR_RECT := Rect2(660, 190, 60, 100)
const DOOR_FLOOR_ID := "server-room"


func _ready() -> void:
	_build_floors()
	_build_walls()
	_build_door()


func _build_floors() -> void:
	for entry in FLOORS:
		var rect: Rect2 = entry["rect"]
		var poly := Polygon2D.new()
		poly.polygon = _rect_points(rect)
		poly.color = entry["color"]
		poly.z_index = -10
		add_child(poly)


func _build_walls() -> void:
	for rect in WALLS:
		var body := StaticBody2D.new()
		body.position = rect.position + rect.size / 2.0

		var shape := CollisionShape2D.new()
		var rectangle := RectangleShape2D.new()
		rectangle.size = rect.size
		shape.shape = rectangle
		body.add_child(shape)

		var visual := Polygon2D.new()
		visual.polygon = _rect_points(Rect2(-rect.size / 2.0, rect.size))
		visual.color = WALL_COLOR
		body.add_child(visual)

		add_child(body)


func _build_door() -> void:
	var area := Area2D.new()
	area.name = "ServerRoomDoor"
	area.position = DOOR_RECT.position + DOOR_RECT.size / 2.0

	var shape := CollisionShape2D.new()
	var rectangle := RectangleShape2D.new()
	rectangle.size = DOOR_RECT.size
	shape.shape = rectangle
	area.add_child(shape)

	area.body_entered.connect(_on_door_entered)
	add_child(area)


func _on_door_entered(body: Node2D) -> void:
	if not body.is_in_group("player"):
		return
	# Round 3 leaves both Day 1 rooms open (SB-04 is free exploration), so this
	# reads as a pass-through today. The branch exists because M5 attaches real
	# unlock gates here, and wiring it now means the door is proven before it has
	# to carry weight -- see GameState.UNLOCK_GATES.
	if GameState.is_unlocked(DOOR_FLOOR_ID):
		return
	push_warning("Door: %s is not yet accessible." % DOOR_FLOOR_ID)


func _rect_points(rect: Rect2) -> PackedVector2Array:
	return PackedVector2Array(
		[
			rect.position,
			Vector2(rect.position.x + rect.size.x, rect.position.y),
			rect.position + rect.size,
			Vector2(rect.position.x, rect.position.y + rect.size.y),
		]
	)
