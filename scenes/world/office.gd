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

## One doorway per corridor, sitting in it, named for the room it leads INTO.
## Each becomes an Area2D in the group `doorways` carrying that `room_id`. The
## lobby has none: it is where the player starts, so nothing leads into it.
const DOORWAYS: Array[Dictionary] = [
	{"room_id": "server-room", "rect": Rect2(660, 190, 60, 100)},
	{"room_id": "player-office", "rect": Rect2(-100, 190, 60, 100)},
	{"room_id": "war-room", "rect": Rect2(270, -100, 100, 60)},
	{"room_id": "engineering-floor", "rect": Rect2(270, 510, 100, 60)},
]

## How much of a doorway's depth its barrier fills while the room is locked.
const BARRIER_DEPTH := 20.0
const BARRIER_COLOR := Color(0.55, 0.30, 0.25)


func _ready() -> void:
	_build_floors()
	_build_walls()
	_build_rooms()
	_build_doorways()
	GameEvents.floor_unlocked.connect(_on_floor_unlocked)


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


func _build_doorways() -> void:
	for entry in DOORWAYS:
		var rect: Rect2 = entry["rect"]
		var room_id: String = entry["room_id"]
		var slug := room_id.replace("-", "_")

		var area := Area2D.new()
		area.name = "Doorway_%s" % slug
		area.position = rect.position + rect.size / 2.0
		area.set_meta("room_id", room_id)
		area.add_to_group("doorways")

		var shape := CollisionShape2D.new()
		var rectangle := RectangleShape2D.new()
		rectangle.size = rect.size
		shape.shape = rectangle
		area.add_child(shape)

		area.body_entered.connect(_on_doorway_entered.bind(room_id))
		add_child(area)

		if not GameState.is_unlocked(room_id):
			_build_barrier(room_id, rect)


## A locked corridor is a wall across its doorway, not a message. It leaves the
## tree the moment GameState opens the room, so being in `locked_corridors` and
## stopping a body are the same fact and cannot drift apart.
func _build_barrier(room_id: String, doorway: Rect2) -> void:
	# Span the corridor's full width, whichever way it runs, so it sits flush
	# with the corridor walls either side.
	var size := doorway.size
	if size.x < size.y:
		size.x = BARRIER_DEPTH
	else:
		size.y = BARRIER_DEPTH

	var body := StaticBody2D.new()
	body.name = "LockedCorridor_%s" % room_id.replace("-", "_")
	body.position = doorway.position + doorway.size / 2.0
	body.set_meta("room_id", room_id)
	body.add_to_group("locked_corridors")

	var shape := CollisionShape2D.new()
	var rectangle := RectangleShape2D.new()
	rectangle.size = size
	shape.shape = rectangle
	body.add_child(shape)

	var visual := Polygon2D.new()
	visual.polygon = _rect_points(Rect2(-size / 2.0, size))
	visual.color = BARRIER_COLOR
	body.add_child(visual)

	add_child(body)


func _on_floor_unlocked(floor_id: String) -> void:
	for node in get_tree().get_nodes_in_group("locked_corridors"):
		if is_ancestor_of(node) and node.get_meta("room_id", "") == floor_id:
			node.remove_from_group("locked_corridors")
			node.queue_free()


func _on_doorway_entered(body: Node2D, room_id: String) -> void:
	if not body.is_in_group("player"):
		return
	# An open room is a pass-through. A locked one has a barrier a step further
	# in, and this is where M6 hangs whatever tells the player why.
	if GameState.is_unlocked(room_id):
		return
	push_warning("Doorway: %s is not yet accessible." % room_id)


func _rect_points(rect: Rect2) -> PackedVector2Array:
	return PackedVector2Array(
		[
			rect.position,
			Vector2(rect.position.x + rect.size.x, rect.position.y),
			rect.position + rect.size,
			Vector2(rect.position.x, rect.position.y + rect.size.y),
		]
	)
