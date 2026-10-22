extends RefCounted

static func extras() -> void:
	for id in ["fixture-extra-a", "fixture-extra-b"]:
		AgentRegistry._agents[id] = {"id": id, "name": id, "description": "Independent story fixture", "role": "Guide", "dept": "story", "color": "#ffffff"}
		BridgeClient._characters[id] = {"execution_kind": "extra", "domain_id": null, "pending": "", "error": ""}
