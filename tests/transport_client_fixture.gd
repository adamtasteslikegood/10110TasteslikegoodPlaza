extends "res://scenes/bridge/ws_client.gd"

## Ordinary transport boundary fault injection; all lifecycle and correlation
## behavior remains in the production client.
var fail_send := false
var send_observation: Dictionary = {}


func _send_text(payload: String) -> Error:
	if fail_send:
		var parsed: Dictionary = JSON.parse_string(payload)
		send_observation = {
			"payload": parsed,
			"mapped": _pending_requests.has(parsed.request_id),
			"pending": conversation_snapshot(parsed.agent_id).pending.duplicate(true),
		}
		return ERR_CONNECTION_ERROR
	return super._send_text(payload)
