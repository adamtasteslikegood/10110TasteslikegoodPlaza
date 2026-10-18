extends RefCounted

const LEFT := 1
const TOP := 2
const RIGHT := 4
const BOTTOM := 8

static func clamp_rect(rect: Rect2, viewport: Vector2, minimum: Vector2) -> Rect2:
	var extent := rect.size.clamp(minimum.min(viewport), viewport)
	return Rect2(rect.position.clamp(Vector2.ZERO, viewport - extent), extent)

static func resize_rect(rect: Rect2, delta: Vector2, edges: int, viewport: Vector2, minimum: Vector2) -> Rect2:
	var low := rect.position
	var high := rect.end
	var limit := minimum.min(viewport)
	if edges & LEFT:
		low.x = clampf(low.x + delta.x, 0.0, high.x - limit.x)
	if edges & TOP:
		low.y = clampf(low.y + delta.y, 0.0, high.y - limit.y)
	if edges & RIGHT:
		high.x = clampf(high.x + delta.x, low.x + limit.x, viewport.x)
	if edges & BOTTOM:
		high.y = clampf(high.y + delta.y, low.y + limit.y, viewport.y)
	return clamp_rect(Rect2(low, high - low), viewport, minimum)
