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
	return {"type": "workspace_state", "protocol_version": 2, "state_store": {"backend": "sqlite", "continuity_id": "00000000-0000-4000-8000-000000000001", "durable": true, "continuity": "project", "error_type": null}, "request_id": id, "project_id": project, "workspace_id": "W", "stage": "ready", "reason": null, "architect_decision": null, "project_path": "/project", "worktree_path": "/execution", "branch": "plaza/workspace-P", "changed_files": {"total": 0, "tracked": 0, "untracked": 0, "truncated": false}, "reservation": null, "memory": {"path": "/memory", "status": "saved", "revision": 8, "error_type": null}}

func state(id: String, lifecycle: String = "active") -> Dictionary:
	return {"type": "domain_state", "protocol_version": 2, "execution_id": "E-" + "A" if lifecycle != "inactive" else null, "domain_revision": "1", "saved_sessions": [{"domain_session_id": "A", "created_at": "2026-10-26", "ended_at": null, "ended_by": null, "high_water_mark": "0"}], "state_store": {"backend": "sqlite", "continuity_id": "00000000-0000-4000-8000-000000000001", "durable": true, "continuity": "project", "error_type": null}, "request_id": id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": "A", "state": lifecycle, "execution_state": "idle"}

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
	var terminal := {"type": "domain_result", "protocol_version": 2, "execution_id": "E-A", "request_id": run, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": "A", "output_id": "1", "agent_id": "systems-architect", "task": "work", "output": "done", "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": true, "revision": 3, "error_type": null}}
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
	completion.merge({"type": "resume_complete", "ended": false, "high_water_mark": "1", "earliest_output_id": "1", "history_gap": false}, true)
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
	await review_transport_regressions()
	await final_review_regressions()
	await fix_round1_bounded_status_regression()
	await control_heavy_terminal_wire_regression()
	finish()

func polling_and_failure_checks() -> void:
	for stage in ["preparing", "reviewing", "initializing", "ready", "failed", "needs_architect", "unconfigured"]:
		var id: String = client.describe_workspace()
		await receive()
		var p := workspace(id, "P2")
		p.stage = stage
		await deliver(p)
		await settle_ready_status()
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
	await settle_ready_status()
	# Real synchronous boundary failure leaves the admitted Run uncertain.
	id = client.domain_status("core")
	await receive()
	p = state(id)
	p.project_id = "P2"
	await deliver(p)
	# Fresh v2 discovery replays even an empty saved application before work.
	var recovered: Dictionary = client.domain_snapshot("core").pending_control
	if recovered.get("type") == "resume":
		var replay_wire := await receive()
		check(replay_wire.get("type") == "resume", "new project observes history without Run")
		var replayed := state(replay_wire.request_id)
		replayed.project_id = "P2"
		replayed.merge({"type": "resume_complete", "ended": false, "high_water_mark": "0", "earliest_output_id": null, "history_gap": false}, true)
		await deliver(replayed)
		var refreshed := await receive()
		var fresh_state := state(refreshed.request_id)
		fresh_state.project_id = "P2"
		await deliver(fresh_state)
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


func review_transport_regressions() -> void:
	client.set_process(false)
	client._reconnect_timer.stop()
	client._socket.close()
	client.queue_free()
	peer.close()
	peer = null
	client = load("res://tests/domain_transport_fixture.gd").new()
	client.bridge_url = "ws://127.0.0.1:%d" % server.get_local_port()
	add_child(client)
	await open()
	var wire := await receive()
	var reserved := workspace(wire.request_id)
	reserved.reservation = {"domain_id": "core", "domain_session_id": "A", "cleanup_failed": false}
	await deliver(reserved)
	wire = await receive()
	check(wire.get("type") == "domain_status", "R3 reserved workspace requests initial status")
	var failure := {"type": "domain_error", "request_id": wire.request_id, "domain_id": "core", "project_id": "P", "workspace_id": "W", "status": "error", "error_type": "sdk_error", "message": "Unavailable"}
	var before: int = client.sent.size()
	await deliver(failure)
	await frames(10)
	check(client.sent.size() == before and client._discovery_request == "", "R3 status error settles quiescently with reservation")
	# Keep a recovery entry and explicitly refresh the same reservation: no loop.
	client._recover_domains["core"] = true
	var id: String = client.describe_workspace()
	wire = await receive()
	reserved.request_id = wire.get("request_id", id)
	before = client.sent.size()
	await deliver(reserved)
	await frames(10)
	check(client.sent.size() == before, "R3 failed automatic status stays quiescent with recovery entry")
	# A deliberate status request remains usable and can recover the session.
	id = client.domain_status("core")
	wire = await receive()
	check(id != "" and wire.get("type") == "domain_status", "R3 explicit status retries remain available")
	await deliver(state(id))
	wire = await receive()
	var completion := state(wire.get("request_id", "missing"))
	completion.merge({"type": "resume_complete", "ended": false, "high_water_mark": "0", "earliest_output_id": null, "history_gap": false}, true)
	await deliver(completion)
	wire = await receive()
	await deliver(state(wire.get("request_id", "missing")))
	# R1: fault boundary ensures no Run frame reaches the fake bridge.
	client.fail_domain_send = true
	var run: String = client.send_domain_query("core", "systems-architect", "unreceived")
	client.fail_domain_send = false
	check(run != "", "R1 locally admitted Run can fail before wire delivery")
	peer.close()
	await frames(20)
	client._reconnect_timer.start(0.01)
	await open()
	wire = await receive()
	await deliver(workspace(wire.get("request_id", "missing")))
	wire = await receive()
	await deliver(state(wire.get("request_id", "missing")))
	wire = await receive()
	completion.request_id = wire.get("request_id", "missing")
	await deliver(completion)
	wire = await receive()
	await deliver(state(wire.get("request_id", "missing")))
	id = client.deactivate_domain("core")
	await receive()
	await deliver(state(id, "inactive"))
	wire = await receive()
	await deliver(workspace(wire.get("request_id", "missing")))
	id = client.activate_domain("core")
	check(id != "", "R1 explicit Start usable after loss, empty replay and clean Stop")
	if id != "":
		await receive()
		var next := state(id)
		next.domain_session_id = "B"
		next.saved_sessions[0].domain_session_id = "B"
		await deliver(next)
		wire = await receive()
		await deliver(workspace(wire.get("request_id", "missing")))
	var run_count := 0
	for packet in client.sent:
		if packet.get("type") == "domain_query": run_count += 1
	check(run_count == 1 and client.domain_snapshot("core").results.is_empty(), "R1 recovery never resends Run or fabricates terminal")
	# R2: actual automatic status after incomplete replay must preserve the hole.
	if client.domain_snapshot("core").domain_session_id != "B": return
	id = client.resume_domain("core")
	await receive()
	for n in ["3", "5"]:
		await deliver({"type": "domain_result", "protocol_version": 2, "execution_id": "E-A", "request_id": "old-run-" + n, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": "B", "output_id": n, "agent_id": "systems-architect", "task": "old", "output": "answer", "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": true, "revision": 3, "error_type": null}})
		if n == "3":
			wire = await receive()
			await deliver(workspace(wire.get("request_id", "missing")))
	wire = await receive()
	await deliver(workspace(wire.get("request_id", "missing")))
	completion.request_id = id
	completion.domain_session_id = "B"
	completion.saved_sessions[0].domain_session_id = "B"
	completion.high_water_mark = "5"
	completion.earliest_output_id = "3"
	completion.history_gap = true
	await deliver(completion)
	wire = await receive()
	var status := state(wire.get("request_id", "missing"))
	status.domain_session_id = "B"
	status.saved_sessions[0].domain_session_id = "B"
	await deliver(status)
	var snapshot: Dictionary = client.domain_snapshot("core")
	check(snapshot.received_cursor == "3" and snapshot.uncertain and snapshot.error.get("error_type") == "replay_incomplete", "R2 automatic lifecycle status cannot erase replay hole")


func final_review_regressions() -> void:
	client.set_process(false)
	client._reconnect_timer.stop()
	client._socket.close()
	client.queue_free()
	peer.close()
	peer = null
	client = load("res://tests/domain_transport_fixture.gd").new()
	client.bridge_url = "ws://127.0.0.1:%d" % server.get_local_port()
	add_child(client)
	await open()
	var wire := await receive()
	await deliver(workspace(wire.request_id))
	var npc: String = client.send_query("systems-architect", "old project question")
	await receive()
	await deliver({"request_id": npc, "agent_id": "systems-architect", "task": "old project question", "status": "ok", "output": "old project answer"})
	wire = await receive()
	await deliver(workspace(wire.request_id))
	client.set_draft("systems-architect", "private NPC draft")
	var start: String = client.activate_domain("core")
	await receive()
	await deliver(state(start, "activating"))
	client.set_domain_draft("design", "preserve busy draft")
	var busy_notices: Array[String] = []
	GameEvents.domain_changed.connect(func(d, reason, _id):
		if d == "design" and reason == "domain_error": busy_notices.append(client.domain_snapshot(d).error.get("error_type", ""))
	)
	var other: String = client.activate_domain("design")
	wire = await receive()
	check(wire.get("domain_id") == "design", "final R2 cross-domain Start admitted while core connects")
	await deliver({"type": "domain_error", "request_id": other, "domain_id": "design", "project_id": "P", "workspace_id": "W", "status": "error", "error_type": "domain_busy", "message": "busy"})
	var rejected: Dictionary = client.domain_snapshot("design")
	check(rejected.pending_control.is_empty() and not client._domain_requests.has(other) and rejected.draft == "preserve busy draft" and "domain_busy" in busy_notices, "final R2 trusted busy rejection retires matching cross-domain Start and preserves draft")
	wire = await receive()
	var observed := state(wire.request_id, "inactive")
	observed.domain_id = "design"
	observed.domain_session_id = null
	await deliver(observed)
	wire = await receive()
	await deliver(workspace(wire.request_id))
	await deliver(state(start))
	wire = await receive()
	await deliver(workspace(wire.request_id))
	client.set_domain_draft("core", "private domain draft")
	await deliver({"type": "domain_result", "protocol_version": 2, "execution_id": "E-A", "request_id": "old-result", "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": "A", "output_id": "1", "agent_id": "systems-architect", "task": "old task", "output": "private old result", "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": true, "revision": 9, "error_type": null}})
	wire = await receive()
	await deliver(workspace(wire.request_id))
	check(not client.conversation_snapshot("systems-architect").messages.is_empty() and client.domain_snapshot("core").results.size() == 1, "final R3 prior-project caches populated")
	peer.close()
	await frames(20)
	client._reconnect_timer.start(0.01)
	await open()
	wire = await receive()
	var unconfigured := workspace(wire.request_id, null)
	unconfigured.merge({"stage": "unconfigured", "workspace_id": null, "project_path": null, "worktree_path": null, "branch": null, "changed_files": null, "memory": {"path": null, "status": "unavailable", "revision": null, "error_type": null}}, true)
	await deliver(unconfigured)
	check(client.conversation_snapshot("systems-architect").messages.is_empty() and client.conversation_snapshot("systems-architect").draft == "" and client._pending_requests.is_empty(), "final R3 unconfigured reconnect clears NPC transcript and draft")
	var cleared: Dictionary = client.domain_snapshot("core")
	check(cleared.draft == "" and cleared.results.is_empty() and cleared.domain_session_id == "" and client._recover_domains.is_empty(), "final R3 unconfigured reconnect clears domain caches and recovery scheduler")
	# Old automatic recovery must not run against the unconfigured session.
	while peer.get_available_packet_count() > 0: await receive()
	var unconfigured_notices: Array[String] = []
	GameEvents.domain_changed.connect(func(d, reason, _id):
		if d == "core" and reason == "domain_error": unconfigured_notices.append(client.domain_snapshot(d).error.get("error_type", ""))
	)
	start = client.activate_domain("core")
	await receive()
	await deliver({"type": "domain_error", "request_id": start, "domain_id": "core", "project_id": null, "status": "error", "error_type": "workspace_unconfigured", "message": "Configure a project"})
	check(client.domain_snapshot("core").pending_control.is_empty() and not client._domain_requests.has(start) and "workspace_unconfigured" in unconfigured_notices, "final R3 null-project Start rejection settles transport correlation")


func settle_ready_status() -> void:
	# A preparing→ready transition now observes remembered domains once.
	var pending: Dictionary = client._domain_requests.get(client._discovery_request, {})
	if pending.get("type") != "domain_status": return
	var wire := await receive()
	check(wire.get("type") == "domain_status", "ready transition uses read-only domain observation")
	var empty := state(wire.request_id, "inactive")
	empty.project_id = "P2"
	empty.domain_session_id = null
	empty.execution_id = null
	empty.saved_sessions = []
	await deliver(empty)


func fix_round1_bounded_status_regression() -> void:
	client.set_process(false)
	client._reconnect_timer.stop()
	client._socket.close()
	client.queue_free()
	peer.close()
	peer = null
	client = load("res://tests/domain_transport_fixture.gd").new()
	client.bridge_url = "ws://127.0.0.1:%d" % server.get_local_port()
	add_child(client)
	await open()
	var wire := await receive()
	await deliver(workspace(wire.request_id))
	var id: String = client.activate_domain("core")
	await receive()
	var current := state(id)
	current.domain_revision = "3"
	await deliver(current)
	wire = await receive()
	await deliver(workspace(wire.request_id))
	id = client.domain_status("core")
	await receive()
	var stale := state(id)
	stale.domain_revision = "0"
	await deliver(stale)
	wire = await receive()
	check(wire.get("type") == "domain_status", "stale same-namespace snapshot gets one read-only refresh")
	stale.request_id = wire.request_id
	var sent_before: int = client.sent.size()
	await deliver(stale)
	await frames(20)
	check(client.sent.size() == sent_before and client._discovery_request == "" and client.domain_snapshot("core").domain_revision == "3", "unchanged rejected snapshot stops reissuing status regardless of request ID")


var heavy_wires: Array[Dictionary] = []
var heavy_high_water := "0"
const HEAVY_SESSION := "00000000-0000-4000-8000-000000000011"
const HEAVY_EXECUTION := "00000000-0000-4000-8000-000000000012"

func heavy_state(id: String) -> Dictionary:
	var packet := state(id)
	packet.domain_session_id = HEAVY_SESSION
	packet.execution_id = HEAVY_EXECUTION
	packet.saved_sessions[0].domain_session_id = HEAVY_SESSION
	packet.saved_sessions[0].high_water_mark = heavy_high_water
	return packet

func heavy_frames(n: int = 6) -> void:
	for _i in range(n):
		peer.poll()
		while peer.get_available_packet_count() > 0:
			var packet: Dictionary = JSON.parse_string(peer.get_packet().get_string_from_utf8())
			heavy_wires.append(packet)
			if packet.get("type") == "describe_workspace": peer.send_text(JSON.stringify(workspace(packet.request_id)))
			elif packet.get("type") == "domain_status": peer.send_text(JSON.stringify(heavy_state(packet.request_id)))
		await get_tree().process_frame

func control_heavy_terminal_wire_regression() -> void:
	for saved in [true, false]:
		client.set_process(false)
		client._reconnect_timer.stop()
		client._socket.close()
		client.queue_free()
		peer.close()
		peer = null
		client = load("res://tests/domain_transport_fixture.gd").new()
		client.bridge_url = "ws://127.0.0.1:%d" % server.get_local_port()
		add_child(client)
		await open()
		# Fixture sender needs room for a valid server frame; client stays stock.
		peer.outbound_buffer_size = 2097152 + 4096
		heavy_wires.clear()
		heavy_high_water = "0"
		await heavy_frames()
		var start: String = client.activate_domain("core")
		await heavy_frames()
		peer.send_text(JSON.stringify(heavy_state(start)))
		await heavy_frames()
		client.set_domain_draft("core", "wire control-heavy output")
		var run: String = client.send_domain_query("core", "systems-architect", "wire control-heavy output")
		await heavy_frames()
		var accepted := heavy_state(run)
		accepted.erase("state")
		accepted.merge({"type": "domain_accepted", "agent_id": "systems-architect", "task": "wire control-heavy output", "execution_state": "running"}, true)
		peer.send_text(JSON.stringify(accepted))
		await heavy_frames()
		check(not run.is_empty() and client.domain_snapshot("core").pending_query.get("request_id") == run, "control-heavy wire starts with exact current Run pending")
		var terminal := {"type": "domain_result", "protocol_version": 2, "request_id": run, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": HEAVY_SESSION, "execution_id": HEAVY_EXECUTION, "agent_id": "systems-architect", "task": "wire control-heavy output", "output": String.chr(1).repeat(262144), "status": "success", "reason": "completed", "truncated": false, "committed": saved, "memory": {"saved": true, "revision": 8, "error_type": null}}
		var resume := ""
		if saved:
			terminal.output_id = "1"
			heavy_high_water = "1"
			# Freeze replay at server highwater1 while its live push is still held.
			resume = client.resume_domain("core")
			await heavy_frames()
			check(not resume.is_empty() and heavy_wires.back().get("cursor") == "0", "frozen replay admitted from cursor0 with live Run pending")
		else:
			terminal.status = "error"
			terminal.reason = "state_store_failed"
			terminal.memory = null
		var encoded := JSON.stringify(terminal).replace(String.chr(1), "\\u0001")
		var packet_bytes := encoded.to_utf8_buffer().size()
		check(terminal.output.to_utf8_buffer().size() == 262144 and packet_bytes > 1048576 and packet_bytes < 2097152, "valid output fits256KiB and terminal fits2MiB while escaped JSON exceeds1MiB cache")
		print("CONTROL_PACKET ", JSON.stringify({"saved": saved, "bytes": packet_bytes, "client_inbound": client._socket.inbound_buffer_size, "cache_packet_bytes": JSON.stringify(terminal).to_utf8_buffer().size()}))
		check(peer.send_text(encoded) == OK, "fixture sends complete valid control-heavy terminal")
		await heavy_frames(12)
		var result: Dictionary = client.domain_snapshot("core")
		check(client.is_bridge_connected(), "valid2MiB-bounded terminal keeps actual transport connected")
		check(result.pending_query.is_empty() and not client._domain_requests.has(run), "valid control-heavy terminal settles exact Run correlation")
		check(result.results.size() == (1 if saved else 0) and result.unsaved_results.size() == (0 if saved else 1) and result.omitted_count == 0, "decoded control row fits actual Godot cache representation and is retained intact")
		check(JSON.stringify(result).to_utf8_buffer().size() <= 1048576 and result.saved_sessions.size() + result.results.size() + result.unsaved_results.size() <= 200, "control-heavy terminal preserves public1MiB and200entry caps")
		if saved:
			check(result.received_cursor == "1" and result.selected_received_cursor == "1", "saved omitted row still advances exact durable receipt")
			if client.is_bridge_connected():
				peer.send_text(encoded)
				var complete := heavy_state(resume)
				complete.merge({"type": "resume_complete", "ended": false, "high_water_mark": "1", "earliest_output_id": "1", "history_gap": false}, true)
				peer.send_text(JSON.stringify(complete))
				await heavy_frames(12)
				result = client.domain_snapshot("core")
				check(result.pending_control.is_empty() and result.pending_query.is_empty() and result.received_cursor == "1" and result.results.size() == 1 and result.omitted_count == 0, "frozen replay duplicate settles without double render or invented omission")
		else:
			check(result.received_cursor == "0" and result.error.get("error_type") == "state_store_failed" and result.draft == "wire control-heavy output", "retained unsaved answer has no fabricated receipt and preserves fault/draft")
			if client.is_bridge_connected():
				peer.send_text(encoded)
				await heavy_frames()
				check(client.domain_snapshot("core").unsaved_results.size() == 1 and client.domain_snapshot("core").omitted_count == 0 and client.domain_snapshot("core").received_cursor == "0", "duplicate unsaved fitting row neither renders twice nor mints receipt")
		if saved and client.is_bridge_connected():
			await heavy_large_row_and_oversize_checks()


func heavy_large_row_and_oversize_checks() -> void:
	var run: String = client.send_domain_query("core", "systems-architect", "large valid row")
	await heavy_frames()
	check(not run.is_empty(), "next exact Run admitted after fitting control row")
	var packet := {"type": "domain_result", "protocol_version": 2, "request_id": run, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": HEAVY_SESSION, "execution_id": HEAVY_EXECUTION, "output_id": "2", "agent_id": "systems-architect", "task": "large valid row", "output": "done", "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": true, "revision": 8, "error_type": null}, "future_metadata": {"detail": "m".repeat(1100000)}}
	var encoded := JSON.stringify(packet)
	check(encoded.to_utf8_buffer().size() > 1048576 and encoded.to_utf8_buffer().size() < 2097152, "backend-valid packet may exceed actual retained JSON budget")
	heavy_high_water = "2"
	var resume: String = client.resume_domain("core")
	await heavy_frames()
	check(not resume.is_empty(), "large-row frozen replay admitted with exact Run pending")
	check(peer.send_text(encoded) == OK, "send valid full row above display budget")
	await heavy_frames(12)
	var snapshot: Dictionary = client.domain_snapshot("core")
	check(snapshot.pending_query.is_empty() and snapshot.received_cursor == "2" and snapshot.results.is_empty() and snapshot.omitted_count == 2, "large row settles receipt then evicts both whole rows rather than raising cache budget")
	peer.send_text(encoded)
	var complete := heavy_state(resume)
	complete.merge({"type": "resume_complete", "ended": false, "high_water_mark": "2", "earliest_output_id": "1", "history_gap": false}, true)
	peer.send_text(JSON.stringify(complete))
	await heavy_frames(12)
	snapshot = client.domain_snapshot("core")
	check(snapshot.pending_control.is_empty() and snapshot.received_cursor == "2" and snapshot.results.is_empty() and snapshot.omitted_count == 2, "frozen duplicate omitted row never repeats receipt or omission")
	check(JSON.stringify(snapshot).to_utf8_buffer().size() <= 1048576 and snapshot.results.size() + snapshot.unsaved_results.size() + snapshot.saved_sessions.size() <= 200, "whole-row omission preserves original public budgets")
	# Oversized raw input must not enter parsed domain dispatch or settle a Run.
	run = client.send_domain_query("core", "systems-architect", "keep pending after oversized wire")
	await heavy_frames()
	packet.request_id = run
	packet.task = "keep pending after oversized wire"
	packet.output_id = "3"
	packet.future_metadata.detail = "z".repeat(2097152)
	encoded = JSON.stringify(packet)
	check(encoded.to_utf8_buffer().size() > 2097152 and encoded.to_utf8_buffer().size() < 2097152 + 4096, "negative wire exceeds approved packet cap within bounded framing headroom")
	var dispatched: int = client.parsed_domain_ids.count(run)
	check(peer.send_text(encoded) == OK, "fixture sends oversized negative control")
	await heavy_frames(12)
	snapshot = client.domain_snapshot("core")
	check(client.is_bridge_connected() and client.parsed_domain_ids.count(run) == dispatched and snapshot.pending_query.get("request_id") == run and snapshot.received_cursor == "2", "oversized raw packet is rejected before domain dispatch with pending Run/cursor intact")
	packet.erase("future_metadata")
	heavy_high_water = "3"
	peer.send_text(JSON.stringify(packet))
	await heavy_frames(12)
	check(client.domain_snapshot("core").pending_query.is_empty() and client.domain_snapshot("core").received_cursor == "3", "valid terminal still settles same Run after oversized wire denial")
	await maximum_history_envelope_wire_checks()


func maximum_history_envelope_wire_checks() -> void:
	heavy_high_water = "4"
	var resume: String = client.resume_domain("core")
	await heavy_frames()
	check(not resume.is_empty() and heavy_wires.back().get("replay_format") == "history_v1", "real client requests trusted history envelope")
	var terminal := {"type": "domain_result", "protocol_version": 2, "request_id": "old-frozen", "domain_id": "core", "domain_session_id": HEAVY_SESSION, "execution_id": "old-execution", "output_id": "4", "agent_id": "systems-architect", "task": "old saved task", "output": "old answer", "status": "error", "reason": "interrupted", "recovered": true, "memory": {"saved": false, "revision": null, "error_type": "memory_reconciliation_pending"}, "padding": ""}
	var remaining := 2097152 - JSON.stringify(terminal).to_utf8_buffer().size()
	terminal.padding = "é".repeat(remaining / 2) + "a".repeat(remaining % 2)
	var envelope := {"type": "domain_history", "protocol_version": 2, "request_id": resume, "project_id": "P", "domain_id": "core", "domain_session_id": HEAVY_SESSION, "state_store": heavy_state("").state_store, "terminal": terminal}
	var encoded := JSON.stringify(envelope)
	check(JSON.stringify(terminal).to_utf8_buffer().size() == 2097152 and encoded.to_utf8_buffer().size() > 2097152 and encoded.to_utf8_buffer().size() <= 2097152 + 4096, "exact2MiB frozen terminal plus bounded envelope")
	peer.outbound_buffer_size = 2097152 + 8192
	var oversized := envelope.duplicate(true)
	oversized.terminal.padding += "x"
	check(peer.send_text(JSON.stringify(oversized)) == OK, "send terminal one byte beyond cap inside envelope")
	await heavy_frames(12)
	check(client.domain_snapshot("core").received_cursor == "3" and not client.domain_snapshot("core").pending_control.is_empty(), "oversized nested terminal cannot settle receipt")
	for spelling in ["whitespace", "escaped-metadata", "numeric-metadata"]:
		var hostile := JSON.stringify(oversized)
		if spelling == "whitespace": hostile = hostile.replace(',"project_id"', ',  "project_id"')
		elif spelling == "escaped-metadata": hostile = hostile.replace('"project_id":"P"', '"project_id":"\\u0050"')
		else: hostile = hostile.replace('"protocol_version":2', '"protocol_version":2e0')
		check(peer.send_text(hostile) == OK, "send noncanonical " + spelling)
		await heavy_frames(12)
		check(client.domain_snapshot("core").received_cursor == "3" and not client.domain_snapshot("core").pending_control.is_empty(), "noncanonical " + spelling + " cannot conceal oversized nested terminal")
	oversized = envelope.duplicate(true)
	oversized.extra = "x".repeat(4096)
	var dispatched: int = client.parsed_domain_ids.count(resume)
	check(peer.send_text(JSON.stringify(oversized)) == OK, "send oversized envelope metadata")
	await heavy_frames(12)
	check(client.parsed_domain_ids.count(resume) == dispatched and client.domain_snapshot("core").received_cursor == "3", "total envelope cap enforced before dispatch")
	check(peer.send_text(encoded) == OK, "send exact maximum terminal in valid history envelope")
	await heavy_frames(12)
	var snapshot: Dictionary = client.domain_snapshot("core")
	check(client.is_bridge_connected() and snapshot.received_cursor == "4" and snapshot.results.is_empty(), "max history frame advances exact receipt before bounded whole-row eviction")
	var done := heavy_state(resume)
	done.merge({"type": "resume_complete", "ended": false, "high_water_mark": "4", "earliest_output_id": "1", "history_gap": false}, true)
	peer.send_text(JSON.stringify(done))
	await heavy_frames()
	check(client.domain_snapshot("core").pending_control.is_empty() and JSON.stringify(client.domain_snapshot("core")).to_utf8_buffer().size() <= 1048576, "maximum history completion settles within unchanged display budget")
	await history_control_spelling_wire_regression()


func history_control_spelling_wire_regression() -> void:
	heavy_high_water = "5"
	var resume: String = client.resume_domain("core")
	await heavy_frames()
	check(not resume.is_empty(), "control-spelling regression has a real pending resume")
	var terminal := {"type": "domain_result", "protocol_version": 2, "request_id": "frozen-controls", "domain_id": "core", "domain_session_id": HEAVY_SESSION, "execution_id": "old-execution", "output_id": "5", "agent_id": "systems-architect", "task": "old saved task", "output": "old answer", "status": "error", "reason": "interrupted", "recovered": true, "memory": {"saved": false, "revision": null, "error_type": "memory_reconciliation_pending"}, "padding": ""}
	terminal.padding = "a".repeat(2097152 - JSON.stringify(terminal).to_utf8_buffer().size())
	var envelope := {"type": "domain_history", "protocol_version": 2, "request_id": resume, "project_id": "P", "domain_id": "core", "domain_session_id": HEAVY_SESSION, "state_store": heavy_state("").state_store, "terminal": terminal}
	envelope.state_store.error_type = "bad" + String.chr(1) + "x"
	# Literal spellings are rejected even at the limit. Escaped canonical values
	# retain the exact producer maximum; one extra nested byte remains invalid.
	for variant in ["escaped-over", "literal-over", "literal-exact", "invalid-utf8-over", "escaped-exact"]:
		var packet := envelope.duplicate(true)
		if variant.ends_with("over"): packet.terminal.padding += "x"
		var encoded := JSON.stringify(packet)
		if variant.begins_with("escaped"): encoded = encoded.replace(String.chr(1), "\\u0001")
		var bytes := encoded.to_utf8_buffer()
		if variant == "invalid-utf8-over": bytes[bytes.find(1)] = 255
		var dispatched: int = client.parsed_domain_ids.count(resume)
		check(JSON.stringify(packet.terminal).to_utf8_buffer().size() == (2097153 if variant.ends_with("over") else 2097152), "literal/escaped fixture has exact nested byte count: " + variant)
		# Godot closes invalid UTF-8 text frames itself. Its accepted binary
		# frames reach the same JSON receiver and need the same byte admission.
		check(peer.send(bytes, WebSocketPeer.WRITE_MODE_BINARY if variant == "invalid-utf8-over" else WebSocketPeer.WRITE_MODE_TEXT) == OK, "send maximum control-spelling frame: " + variant)
		var started := Time.get_ticks_usec()
		await heavy_frames(12)
		print("CONTROL_BOUNDARY_RECEIVER ", JSON.stringify({"variant": variant, "frame_bytes": bytes.size(), "elapsed_ms": (Time.get_ticks_usec() - started) / 1000.0}))
		var snapshot: Dictionary = client.domain_snapshot("core")
		check(snapshot.received_cursor == ("5" if variant == "escaped-exact" else "4") and snapshot.pending_control.get("request_id") == resume and client._domain_requests.has(resume), "control-spelling boundary preserves exact cursor and pending resume: " + variant)
		if variant.begins_with("literal") or variant == "invalid-utf8-over":
			check(client.parsed_domain_ids.count(resume) == dispatched, "noncanonical string bytes rejected before domain dispatch: " + variant)
	# Exercise every C0 value in metadata, with escaped quotes and even/odd
	# backslash runs before it. TAB/LF/CR inside strings are also forbidden.
	terminal = terminal.duplicate(true)
	terminal.erase("padding")
	terminal.output_id = "6"
	envelope.terminal = terminal
	for code in range(32):
		envelope.state_store.error_type = "bad" + "\\".repeat(code % 3) + '"CONTROL_BYTE' + "x"
		var encoded := JSON.stringify(envelope)
		var marker := encoded.find("CONTROL_BYTE")
		var bytes := encoded.substr(0, marker).to_utf8_buffer()
		bytes.append(code)
		bytes.append_array(encoded.substr(marker + "CONTROL_BYTE".length()).to_utf8_buffer())
		var dispatched: int = client.parsed_domain_ids.count(resume)
		check(peer.send(bytes, WebSocketPeer.WRITE_MODE_TEXT) == OK, "send literal C0 bytes with escape parity: " + str(code))
		await heavy_frames(2)
		var snapshot: Dictionary = client.domain_snapshot("core")
		check(snapshot.received_cursor == "5" and snapshot.pending_control.get("request_id") == resume and client._domain_requests.has(resume) and client.parsed_domain_ids.count(resume) == dispatched, "literal C0 never advances or settles resume: " + str(code))
	for code in [1, 8, 11, 12, 31]:
		var encoded := String.chr(code) + JSON.stringify(envelope)
		var dispatched: int = client.parsed_domain_ids.count(resume)
		check(peer.send_text(encoded) == OK, "send non-whitespace exterior C0: " + str(code))
		await heavy_frames(2)
		check(client.domain_snapshot("core").received_cursor == "5" and client.domain_snapshot("core").pending_control.get("request_id") == resume and client.parsed_domain_ids.count(resume) == dispatched, "non-whitespace exterior C0 preserves receipt and pending resume: " + str(code))
	var controls := ""
	for code in range(1, 32): controls += String.chr(code)
	terminal.output = 'escaped quote " and backslashes \\\\ ' + controls
	envelope.state_store.error_type = "bad" + String.chr(1) + "x"
	var encoded := JSON.stringify(envelope)
	# Godot emits non-JSON \\v for VT and literal bytes for many controls.
	# Use the bridge's canonical JSON spellings without changing values.
	encoded = encoded.replace("\\v", "\\u000b")
	for code in range(1, 32): encoded = encoded.replace(String.chr(code), "\\u%04x" % code)
	encoded = "\t\r\n " + encoded.replace(',"terminal":', ',\t\r\n "terminal":') + " \r\n\t"
	check(peer.send_text(encoded) == OK, "send canonical escaped controls with legal exterior whitespace")
	await heavy_frames(6)
	var snapshot: Dictionary = client.domain_snapshot("core")
	check(snapshot.received_cursor == "6" and snapshot.pending_control.get("request_id") == resume and snapshot.results.size() == 1 and snapshot.results[0].output == terminal.output, "escaped controls/quotes/backslashes and exterior whitespace preserve frozen terminal and exact receipt")
	heavy_high_water = "6"
	var done := heavy_state(resume)
	done.merge({"type": "resume_complete", "ended": false, "high_water_mark": "6", "earliest_output_id": "1", "history_gap": false}, true)
	peer.send_text(JSON.stringify(done))
	await heavy_frames()
	check(client.is_bridge_connected() and client.domain_snapshot("core").pending_control.is_empty() and not client._domain_requests.has(resume) and client.domain_snapshot("core").received_cursor == "6", "only matching completion settles resume after rejected literal controls")
