extends Node2D

## The Week-1 greybox: a lobby with four rooms off it, one per wall.
##
## SB-04 puts the player alone in the lobby with freedom to explore; SB-05 puts the
## Systems Architect in the server room, east. Sprint 6 (M2, PLZG-258) added the
## player's office west, the war room north and the engineering floor south, each
## reached through a short corridor cut through the lobby wall.
##
## Geometry is built from the tables below rather than hand-placed in the .tscn.
## Grey-boxing is a measuring exercise -- you move a wall, run, and look again --
## and a named rect in a diff is far easier to review and adjust than a screenful
## of generated node entries.

const WALL_THICKNESS := 20.0

const FLOOR_COLOR_LOBBY := Color(0.20, 0.20, 0.24)
const FLOOR_COLOR_CORRIDOR := Color(0.17, 0.17, 0.21)
const FLOOR_COLOR_SERVER := Color(0.16, 0.19, 0.22)
const FLOOR_COLOR_OFFICE := Color(0.21, 0.19, 0.17)
const FLOOR_COLOR_WAR_ROOM := Color(0.21, 0.17, 0.19)
const FLOOR_COLOR_ENGINEERING := Color(0.17, 0.21, 0.19)
const WALL_COLOR := Color(0.38, 0.38, 0.43)

## Walkable areas, purely visual.
const FLOORS: Array[Dictionary] = [
	{"rect": Rect2(0, 0, 640, 480), "color": FLOOR_COLOR_LOBBY},
	{"rect": Rect2(640, 190, 120, 100), "color": FLOOR_COLOR_CORRIDOR},
	{"rect": Rect2(760, 0, 440, 480), "color": FLOOR_COLOR_SERVER},
	{"rect": Rect2(-140, 190, 140, 100), "color": FLOOR_COLOR_CORRIDOR},
	{"rect": Rect2(-460, 60, 320, 360), "color": FLOOR_COLOR_OFFICE},
	{"rect": Rect2(270, -140, 100, 140), "color": FLOOR_COLOR_CORRIDOR},
	{"rect": Rect2(120, -440, 400, 300), "color": FLOOR_COLOR_WAR_ROOM},
	{"rect": Rect2(270, 480, 100, 120), "color": FLOOR_COLOR_CORRIDOR},
	{"rect": Rect2(-100, 600, 840, 400), "color": FLOOR_COLOR_ENGINEERING},
]

## The rooms themselves, as the areas a body is in when it is "in the room".
## Each becomes an Area2D in the group `rooms` carrying a `room_id`, which is
## how tests/room_probe.gd -- and later the map -- know a room exists. A floor
## polygon is only paint; this is what says the space is a place.
const ROOMS: Array[Dictionary] = [
	{"id": "lobby", "rect": Rect2(0, 0, 640, 480)},
	{"id": "server-room", "rect": Rect2(760, 0, 440, 480)},
	{"id": "player-office", "rect": Rect2(-460, 60, 320, 360)},
	{"id": "war-room", "rect": Rect2(120, -440, 400, 300)},
	{"id": "engineering-floor", "rect": Rect2(-100, 600, 840, 400)},
]

## Solid geometry. Each rect becomes a StaticBody2D plus a matching visual, so
## what you see and what you collide with cannot drift apart.
const WALLS: Array[Rect2] = [
	# Lobby shell, with a 100px gap in each wall for a corridor mouth.
	Rect2(-20, -20, 290, 20),
	Rect2(370, -20, 290, 20),
	Rect2(-20, 480, 290, 20),
	Rect2(370, 480, 290, 20),
	Rect2(-20, 0, 20, 190),
	Rect2(-20, 290, 20, 190),
	Rect2(640, 0, 20, 190),
	Rect2(640, 290, 20, 190),
	# East corridor.
	Rect2(640, 170, 120, 20),
	Rect2(640, 290, 120, 20),
	# Server room shell, with the matching gap on its left.
	Rect2(760, -20, 460, 20),
	Rect2(760, 480, 460, 20),
	Rect2(1200, 0, 20, 480),
	Rect2(740, 0, 20, 170),
	Rect2(740, 290, 20, 190),
	# West corridor and the player's office, gap on its right.
	Rect2(-140, 170, 140, 20),
	Rect2(-140, 290, 140, 20),
	Rect2(-480, 40, 360, 20),
	Rect2(-480, 420, 360, 20),
	Rect2(-480, 60, 20, 360),
	Rect2(-140, 60, 20, 130),
	Rect2(-140, 290, 20, 130),
	# North corridor and the war room, gap in its bottom wall.
	Rect2(250, -140, 20, 140),
	Rect2(370, -140, 20, 140),
	Rect2(100, -460, 440, 20),
	Rect2(100, -440, 20, 300),
	Rect2(520, -440, 20, 300),
	Rect2(100, -140, 170, 20),
	Rect2(370, -140, 170, 20),
	# South corridor and the engineering floor, gap in its top wall.
	Rect2(250, 480, 20, 120),
	Rect2(370, 480, 20, 120),
	Rect2(-120, 580, 390, 20),
	Rect2(370, 580, 390, 20),
	Rect2(-120, 600, 20, 400),
	Rect2(740, 600, 20, 400),
	Rect2(-120, 1000, 880, 20),
]

## The corridor mouth. Consults GameState before letting the player through.
const DOOR_RECT := Rect2(660, 190, 60, 100)
const DOOR_FLOOR_ID := "server-room"


func _ready() -> void:
	_build_floors()
	_build_walls()
	_build_rooms()
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


func _build_rooms() -> void:
	for entry in ROOMS:
		var rect: Rect2 = entry["rect"]
		var area := Area2D.new()
		area.name = "Room_%s" % str(entry["id"]).replace("-", "_")
		area.position = rect.position + rect.size / 2.0
		area.set_meta("room_id", entry["id"])
		area.add_to_group("rooms")

		var shape := CollisionShape2D.new()
		var rectangle := RectangleShape2D.new()
		rectangle.size = rect.size
		shape.shape = rectangle
		area.add_child(shape)

		add_child(area)


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
