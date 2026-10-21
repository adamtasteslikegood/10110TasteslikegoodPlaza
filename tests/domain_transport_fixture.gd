extends "res://scenes/bridge/ws_client.gd"

var fail_domain_send := false
var admitted_before_send := false
var sent: Array[Dictionary] = []

func _send_text(payload: String) -> Error:
	var p: Dictionary = JSON.parse_string(payload)
	sent.append(p)
	if p.get("type") == "domain_query":
		admitted_before_send = domain_snapshot(p.domain_id).pending_query.get("request_id") == p.request_id
		if fail_domain_send: return ERR_CONNECTION_ERROR
	return super._send_text(payload)
