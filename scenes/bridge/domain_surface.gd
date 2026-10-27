extends RefCounted

## One foreground intent across both renderers. No task execution is queued here.
var client: Node
var owner := ""
var domain_id := ""
var agent_id := ""
var revision := 0
var _refocus := ""
var _after_background: Dictionary = {}
var _after_control: Dictionary = {}

func _init(transport: Node) -> void:
	client = transport

func open(surface: String, domain: String, agent: String) -> void:
	var handoff := not owner.is_empty() and domain_id == domain
	if not owner.is_empty() and domain_id != domain: close(owner)
	GameEvents.domain_surface_changing.emit()
	owner = surface
	domain_id = domain
	agent_id = agent
	revision += 1
	if handoff and _after_background.get("domain_id") == domain: _after_background.revision = revision
	if _after_control.get("domain_id") == domain: _after_control = {}
	GameEvents.domain_surface_changed.emit()
	if not handoff:
		var snapshot: Dictionary = client.domain_snapshot(domain)
		if snapshot.get("state") in ["active", "background"] and not snapshot.get("execution_id", "").is_empty(): refocus()
		elif not snapshot.get("selected_session_id", "").is_empty(): client.resume_domain(domain)

func refocus() -> void:
	_after_background = {}
	if owner.is_empty(): return
	var snapshot: Dictionary = client.domain_snapshot(domain_id)
	if snapshot.get("read_only", true) or snapshot.get("state") == "inactive":
		client.resume_domain(domain_id)
		return
	var pending: Dictionary = snapshot.get("pending_control", {})
	if pending.get("type") == "background_domain":
		_after_background = {"domain_id": domain_id, "generation": snapshot.domain_session_id, "execution_id": snapshot.execution_id, "request_id": pending.request_id, "revision": revision}
	elif pending.get("type") == "refocus_domain": _refocus = pending.request_id
	else: _refocus = client.refocus_domain(domain_id)

func close(surface: String) -> void:
	if owner != surface: return
	var domain := domain_id
	GameEvents.domain_surface_changing.emit()
	owner = ""
	revision += 1
	_refocus = ""
	_after_background = {}
	var snapshot: Dictionary = client.domain_snapshot(domain)
	var pending: Dictionary = snapshot.get("pending_control", {})
	var request: String = client.background_domain(domain)
	if request.is_empty() and client.is_bridge_connected() and pending.get("type") in ["activate_domain", "refocus_domain", "resume"]:
		_after_control = {"domain_id": domain, "generation": snapshot.get("domain_session_id", ""), "execution_id": snapshot.get("execution_id", ""), "request_id": pending.request_id}
	GameEvents.domain_surface_changed.emit()

func changed(domain: String, reason: String, request_id: String) -> void:
	var snapshot: Dictionary = client.domain_snapshot(domain)
	if reason in ["domain_error", "connection"]:
		if domain == domain_id: _refocus = ""
		if _after_control.get("domain_id") == domain: _after_control = {}
		if _after_background.get("domain_id") == domain: _after_background = {}
	if _after_control.get("domain_id") == domain and request_id == _after_control.get("request_id") and reason in ["domain_state", "resume_complete"] and snapshot.pending_control.is_empty():
		var generation: String = _after_control.generation
		var execution: String = _after_control.get("execution_id", "")
		_after_control = {}
		if (generation.is_empty() or generation == snapshot.domain_session_id) and (execution.is_empty() or execution == snapshot.execution_id): client.background_domain(domain)
	if _after_background.get("domain_id") == domain:
		var intent := _after_background
		if intent.revision != revision or owner.is_empty() or snapshot.domain_session_id != intent.generation or snapshot.execution_id != intent.execution_id: _after_background = {}
		elif request_id == intent.request_id and reason == "domain_state" and snapshot.pending_control.is_empty(): refocus()
	if not owner.is_empty() and domain == domain_id and not _refocus.is_empty() and request_id == _refocus and reason == "domain_state" and snapshot.pending_control.is_empty():
		_refocus = ""
		client.resume_domain(domain)

func reset() -> void:
	owner = ""
	domain_id = ""
	agent_id = ""
	revision += 1
	_refocus = ""
	_after_background = {}
	_after_control = {}
	GameEvents.domain_surface_changed.emit()

func disconnected() -> void:
	revision += 1
	_refocus = ""
	_after_background = {}
	_after_control = {}
