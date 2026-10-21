extends Node

var checks := 0
var failures: Array[String] = []
var server := TCPServer.new()
var peer: WebSocketPeer
var client: Node
var events: Array[Dictionary] = []

func check(ok: bool, message: String) -> void:
	checks += 1
	if not ok: failures.append(message)

func frames(n: int = 5) -> void:
	for i in range(n):
		if peer != null: peer.poll()
		await get_tree().process_frame

func open() -> void:
	var deadline := Time.get_ticks_msec() + 2000
	while Time.get_ticks_msec() < deadline:
		if server.is_connection_available():
			peer = WebSocketPeer.new()
			peer.accept_stream(server.take_connection())
		if peer != null: peer.poll()
		if peer != null and peer.get_ready_state() == WebSocketPeer.STATE_OPEN and client.is_bridge_connected(): return
		await get_tree().process_frame
	check(false, "loopback opens")

func receive() -> Dictionary:
	var deadline := Time.get_ticks_msec() + 1000
	while Time.get_ticks_msec() < deadline:
		peer.poll()
		if peer.get_available_packet_count() > 0: return JSON.parse_string(peer.get_packet().get_string_from_utf8())
		await get_tree().process_frame
	check(false, "outgoing frame received")
	return {}

func deliver(p: Dictionary) -> void:
	peer.send_text(JSON.stringify(p))
	await frames()

func workspace(id: String, project: Variant = "P") -> Dictionary:
	return {"type": "workspace_state", "request_id": id, "project_id": project, "workspace_id": "W", "stage": "ready", "reason": null, "architect_decision": null, "project_path": "/project", "worktree_path": "/execution", "branch": "plaza/workspace-P", "changed_files": {"total": 0, "tracked": 0, "untracked": 0, "truncated": false}, "reservation": null, "memory": {"path": "/memory", "status": "saved", "revision": 8, "error_type": null}}

func state(id: String, lifecycle: String = "active") -> Dictionary:
	return {"type": "domain_state", "request_id": id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": "A", "state": lifecycle, "execution_state": "idle"}

func _ready() -> void:
	BridgeClient.set_process(false)
	BridgeClient._reconnect_timer.stop()
	var script = load("res://scenes/bridge/ws_client.gd")
	client = script.new()
	if not client.has_method("domain_snapshot"):
		check(false, "domain wrappers exist")
		client.free()
		finish()
		return
	client.free()
	get_tree().create_timer(20.0).timeout.connect(func():
		check(false, "domain transport timed out")
		finish()
	)
	client = load("res://tests/domain_transport_fixture.gd").new()
	GameEvents.domain_changed.connect(func(d, r, id): events.append({"domain": d, "reason": r, "id": id}))
	check(server.listen(0, "127.0.0.1") == OK, "actual TCP listener")
	client.bridge_url = "ws://127.0.0.1:%d" % server.get_local_port()
	add_child(client)
	await open()
	var discovery := await receive()
	check(discovery.get("type") == "describe_workspace", "actual open automatically discovers")
	check(client.describe_workspace() == discovery.request_id, "discovery coalesces")
	var initial := workspace(discovery.request_id, null)
	initial.stage = "preparing"
	await deliver(initial)
	client.set_draft("systems-architect", "initial identity draft")
	var initial_id: String = client.describe_workspace()
	await receive()
	await deliver(workspace(initial_id))
	check(client.conversation_snapshot("systems-architect").draft == "initial identity draft", "first project identity preserves initial NPC state")
	client.set_draft("systems-architect", "")
	check(client.workspace_snapshot().project_id == "P", "workspace snapshot")
	var start: String = client.activate_domain("core")
	check((await receive()).request_id == start, "Start wire")
	await deliver(state(start, "activating"))
	check(client.domain_snapshot("core").domain_session_id == "A", "activating exposes generation")
	var stop: String = client.deactivate_domain("core")
	var stopped := await receive()
	check(stopped.get("domain_session_id") == "A", "Stop captures generation while Start pending")
	await deliver(state(stop, "inactive"))
	await deliver(state(start))
	check(client.domain_snapshot("core").state == "inactive", "late Start cannot revive stopped session")
	check(not client._domain_requests.has(start), "superseded Start correlation is removed")
	# Service coalesced workspace refresh after lifecycle.
	var refresh := await receive()
	check(refresh.get("type") == "describe_workspace", "lifecycle refreshes workspace")
	await deliver(workspace(refresh.request_id))
	start = client.activate_domain("core")
	await receive()
	await deliver(state(start))
	refresh = await receive()
	await deliver(workspace(refresh.request_id))
	client.set_domain_draft("core", "retain after busy")
	var rejected: String = client.send_domain_query("core", "systems-architect", "retain after busy")
	await receive()
	var rejection := state(rejected)
	rejection.merge({"type": "domain_error", "status": "error", "error_type": "domain_busy", "message": "busy"}, true)
	await deliver(rejection)
	check(client.domain_snapshot("core").draft == "retain after busy" and client.domain_snapshot("core").pending_query.is_empty(), "server rejection preserves input and clears only matching query")
	var status_refresh := await receive()
	check(status_refresh.get("type") == "domain_status", "control error refreshes authoritative lifecycle")
	await deliver(state(status_refresh.get("request_id", "missing")))
	refresh = await receive()
	await deliver(workspace(refresh.get("request_id", "missing")))
	var npc: String = client.send_query("systems-architect", "NPC")
	await receive()
	client.set_domain_draft("core", "work")
	var run: String = client.send_domain_query("core", "systems-architect", "work")
	var wire := await receive()
	check(wire.get("domain_session_id") == "A" and wire.get("task") == "work" and client.admitted_before_send, "Run generation exact and pending visible before send")
	var accepted := state(run)
	accepted.type = "domain_accepted"
	accepted.execution_state = "running"
	accepted.erase("state")
	accepted.agent_id = "systems-architect"
	accepted.task = "work"
	await deliver(accepted)
	check(client.domain_snapshot("core").pending_query.request_id == run, "acceptance preserves query")
	client.set_domain_draft("core", "keep")
	check(client.send_domain_query("core", "systems-architect", "again") == "" and client.domain_snapshot("core").draft == "keep", "busy retains draft")
	var terminal := {"type": "domain_result", "request_id": run, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": "A", "output_id": "1", "agent_id": "systems-architect", "task": "work", "output": "done", "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": true, "revision": 3, "error_type": null}}
	var forged := terminal.duplicate(true)
	forged.request_id = npc
	forged.domain_session_id = "wrong-generation"
	await deliver(forged)
	check(client._pending_requests.has(npc) and client.domain_snapshot("core").pending_query.request_id == run, "domain packet using NPC ID cannot settle either pending request")
	await deliver(terminal)
	await deliver(terminal)
	check(client._pending_requests.size() == 1 and client._pending_requests.has(npc), "domain packets never settle NPC")
	check(client.domain_snapshot("core").results.size() == 1 and client.domain_snapshot("core").pending_query.is_empty(), "duplicate terminal renders once")
	check(client.workspace_snapshot().memory.revision == 8, "old replay memory cannot regress workspace")
	refresh = await receive()
	await deliver(workspace(refresh.request_id))
	var resume: String = client.resume_domain("core")
	wire = await receive()
	check(wire.get("cursor") == "1", "resume uses safe receipt cursor")
	var completion := state(resume)
	completion.merge({"type": "resume_complete", "high_water_mark": "1", "earliest_output_id": "1", "history_gap": false}, true)
	await deliver(completion)
	check(client.domain_snapshot("core").pending_control.is_empty(), "empty replay completes")
	wire = await receive()
	check(wire.get("type") == "domain_status", "replay completion requests fresh lifecycle status")
	await deliver(state(wire.request_id))
	var pending: String = client.send_domain_query("core", "systems-architect", "uncertain")
	await receive()
	peer.close()
	await frames(20)
	check(client.domain_snapshot("core").uncertain and client.domain_snapshot("core").pending_query.request_id == pending, "socket loss preserves uncertain query")
	client._reconnect_timer.start(0.01)
	await open()
	discovery = await receive()
	check(discovery.get("type") == "describe_workspace", "reconnect discovers without Run retry")
	await deliver(workspace(discovery.request_id))
	wire = await receive()
	check(wire.get("type") == "domain_status", "same project reconnect discovers session")
	await deliver(state(wire.request_id))
	wire = await receive()
	check(wire.get("type") == "resume" and wire.get("cursor") == "1", "same session reconnect explicitly replays")
	completion.request_id = wire.request_id
	await deliver(completion)
	wire = await receive()
	await deliver(state(wire.request_id))
	var count := 0
	for p in client.sent:
		if p.get("type") == "domain_query": count += 1
	check(count == 3, "reconnect never resubmits Run")
	client.set_draft("systems-architect", "old NPC")
	client.set_domain_draft("core", "old domain")
	var describe: String = client.describe_workspace()
	await receive()
	await deliver(workspace(describe, "P2"))
	check(client.conversation_snapshot("systems-architect").draft == "" and client.domain_snapshot("core").draft == "", "project replacement clears NPC and domain before presentation")
	await polling_and_failure_checks()
	finish()

func polling_and_failure_checks() -> void:
	for stage in ["preparing", "reviewing", "initializing", "ready", "failed", "needs_architect", "unconfigured"]:
		var id: String = client.describe_workspace()
		await receive()
		var p := workspace(id, "P2")
		p.stage = stage
		await deliver(p)
		var count: int = client.sent.size()
		client._workspace_poll = 0.0
		client._process(1.0)
		check(client.sent.size() == count, "no setup polling before 2s: " + stage)
		client._process(1.0)
		if stage in ["preparing", "reviewing", "initializing"]:
			check(client.sent.size() == count + 1, "progressing setup polls once: " + stage)
			var request := await receive()
			p.request_id = request.request_id
			await deliver(p)
			check(client.sent.size() == count + 1, "discovery response never recursively polls")
		else: check(client.sent.size() == count, "stable setup does not poll: " + stage)
	# Initial absent identity followed by a known project preserves NPC state.
	client.set_draft("systems-architect", "preserve through null identity")
	var id: String = client.describe_workspace()
	await receive()
	var p := workspace(id, null)
	p.stage = "preparing"
	await deliver(p)
	check(client.conversation_snapshot("systems-architect").draft == "preserve through null identity", "null setup identity is not project replacement")
	id = client.describe_workspace()
	await receive()
	p = workspace(id, "P2")
	await deliver(p)
	# Real synchronous boundary failure leaves the admitted Run uncertain.
	id = client.domain_status("core")
	await receive()
	p = state(id)
	p.project_id = "P2"
	await deliver(p)
	var old_run: String = client.send_domain_query("core", "systems-architect", "old generation")
	await receive()
	id = client.domain_status("core")
	await receive()
	p = state(id)
	p.project_id = "P2"
	p.domain_session_id = "B"
	await deliver(p)
	check(not client._domain_requests.has(old_run), "new generation removes obsolete query correlation")
	client.fail_domain_send = true
	id = client.send_domain_query("core", "systems-architect", "send uncertain")
	check(id != "" and client.admitted_before_send and client.domain_snapshot("core").uncertain and client.domain_snapshot("core").pending_query.request_id == id, "synchronous send failure preserves admitted uncertain Run")
	var arities := {"workspace_changed": 2, "domain_changed": 3, "conversation_changed": 3, "agent_query_sent": 2, "agent_response_received": 2, "agent_query_failed": 3}
	for info in GameEvents.get_signal_list():
		if arities.has(info.name): check(info.args.size() == arities[info.name], "signal arity: " + info.name)

func finish() -> void:
	if is_instance_valid(client):
		client.set_process(false)
		client._reconnect_timer.stop()
		client._socket.close()
	if peer != null: peer.close()
	server.stop()
	if failures.is_empty(): print("domain_transport_test: OK — %d checks passed." % checks)
	else:
		for f in failures: printerr("FAIL: " + f)
	get_tree().quit(0 if failures.is_empty() else 1)
