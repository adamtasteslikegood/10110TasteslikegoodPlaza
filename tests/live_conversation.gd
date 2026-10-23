extends Node

## Headless half of Gate B: sends real turns through the in-engine path.
##
##     LIVE_AGENT=systems-architect LIVE_TURNS='["...","..."]' \
##         godot --headless tests/live_conversation.tscn
##
## Run by scripts/sprint_6_live.py, which starts the bridge first and judges the
## result. This scene judges nothing about the model's wording. It drives the
## path a player drives -- NPC approached, question submitted through the
## panel's own LineEdit signal, BridgeClient, bridge, reply into BodyLabel --
## and prints one line per turn saying what came back and where it was read.
##
## `received` is read from BodyLabel, not from the signal payload: the claim is
## that the reply reached the panel, so the panel is what gets quoted. Nothing
## here emits agent_response_received; if no bridge answers, the turn times out.

const CONNECT_TIMEOUT := 20.0
const TURN_TIMEOUT := 120.0
const BODY_LABEL := "Panel/Margin/Rows/BodyLabel"
const QUESTION_INPUT := "Panel/Margin/Rows/InputRow/QuestionInput"

var _reply = null
var _failure = null


func _ready() -> void:
	var agent_id := OS.get_environment("LIVE_AGENT")
	var turns = JSON.parse_string(OS.get_environment("LIVE_TURNS"))
	if agent_id == "" or not (turns is Array) or turns.is_empty():
		_abort("setup", "LIVE_AGENT and LIVE_TURNS (a JSON array) must be set")
		return

	var main: PackedScene = load("res://scenes/main.tscn")
	var instance: Node = main.instantiate()
	get_tree().root.add_child.call_deferred(instance)
	await get_tree().process_frame

	var waited := 0.0
	while not BridgeClient.is_bridge_connected() and waited < CONNECT_TIMEOUT:
		await get_tree().process_frame
		waited += get_process_delta_time()
	if not BridgeClient.is_bridge_connected():
		_abort("connection", "BridgeClient never connected")
		return

	var hud: Node = instance.get_node("HUD")
	var body: RichTextLabel = hud.get_node(BODY_LABEL)
	var input: LineEdit = hud.get_node(QUESTION_INPUT)
	GameEvents.agent_response_received.connect(func(_id, text): _reply = text)
	GameEvents.agent_query_failed.connect(
		func(_id, kind, message): _failure = {"error_type": kind, "message": message}
	)
	GameEvents.npc_approached.emit(agent_id, AgentRegistry.get_agent(agent_id))

	for index in turns.size():
		_reply = null
		_failure = null
		input.text = str(turns[index])
		input.text_submitted.emit(input.text)
		waited = 0.0
		while _reply == null and _failure == null and waited < TURN_TIMEOUT:
			await get_tree().process_frame
			waited += get_process_delta_time()
		if _failure != null:
			_abort(_failure["error_type"], _failure["message"], index + 1)
			return
		if _reply == null:
			_abort("timeout", "no reply in %ds" % int(TURN_TIMEOUT), index + 1)
			return
		# D-007: the reply is revealed over time, never all at once. Sample the
		# reveal right after it lands and again a few frames later.
		var span: Dictionary = hud.current_assistant_span()
		var at_arrival := visible_in_span(body, span)
		for _frame in 5:
			await get_tree().process_frame
		var after_frames := visible_in_span(body, span)
		var reveal_error := await wait_for_reveal(hud, body, span)
		if not reveal_error.is_empty():
			_abort(reveal_error.error_type, reveal_error.message, index + 1)
			return
		if _failure != null:
			_abort(_failure["error_type"], _failure["message"], index + 1)
			return
		var received := read_rendered_reply(body, span)
		print(
			(
				"LIVE %s"
				% JSON.stringify(
					{
						"turn": index + 1,
						"sent": str(turns[index]),
						"received": received,
						"label_holds_reply": received == str(_reply),
						"typewriter_started_at": at_arrival,
						"typewriter_after_frames": after_frames,
					}
				)
			)
		)

	instance.queue_free()
	get_tree().quit(0)


func _abort(kind: String, message: String, turn: int = 0) -> void:
	print(
		"LIVE_ERROR %s" % JSON.stringify({"turn": turn, "error_type": kind, "message": message})
	)
	get_tree().quit(1)


## Final evidence comes from the current native label after natural reveal.
## Keep this bounded: a stopped animation or changed reply cannot become a
## successful final record, and the transport payload never supplies readback.
static func wait_for_reveal(hud: Node, body: RichTextLabel, span: Dictionary, timeout: float = TURN_TIMEOUT) -> Dictionary:
	var deadline := Time.get_ticks_msec() + int(timeout * 1000)
	while true:
		if span.get("request_id", "").is_empty() or hud.current_assistant_span() != span or not body.is_visible_in_tree():
			return {"error_type": "reveal_changed", "message": "current assistant display changed before reveal completed"}
		if visible_in_span(body, span) == int(span.length) and body.get_parsed_text().length() >= int(span.start) + int(span.length):
			return {}
		if Time.get_ticks_msec() >= deadline:
			return {"error_type": "reveal_timeout", "message": "assistant display did not finish revealing in %.2fs" % timeout}
		await body.get_tree().process_frame
	return {}


## Shared with the deterministic wrong-turn-two regression. The nonce from the
## first user message must never count as a model recall in a later reply.
static func read_rendered_reply(body: RichTextLabel, span: Dictionary) -> String:
	return body.get_parsed_text().substr(int(span.start), int(span.length))


static func visible_in_span(body: RichTextLabel, span: Dictionary) -> int:
	var visible := body.get_parsed_text().length() if body.visible_characters < 0 else body.visible_characters
	return clampi(visible - int(span.start), 0, int(span.length))
