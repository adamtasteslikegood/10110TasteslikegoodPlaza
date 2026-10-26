extends Node

var checks := 0
var failures: Array[String] = []
var Store: Script

func check(ok: bool, message: String) -> void:
	checks += 1
	if not ok: failures.append(message)

func command(kind: String, id: String, generation: String = "A") -> Dictionary:
	var p := {"type": kind, "protocol_version": 2, "domain_id": "core", "request_id": id}
	if kind not in ["activate_domain", "domain_status"]: p.domain_session_id = generation
	if kind in ["activate_domain", "end_domain_session"]: p.expected_domain_revision = "1"
	if kind in ["domain_query", "deactivate_domain", "background_domain", "refocus_domain"]: p.execution_id = "E-" + generation
	if kind == "resume": p.cursor = "0"
	if kind == "domain_query": p.merge({"agent_id": "systems-architect", "task": "work"})
	return p

func state(id: String, generation: String = "A", lifecycle: String = "active") -> Dictionary:
	return {"type": "domain_state", "protocol_version": 2, "execution_id": "E-" + generation if lifecycle != "inactive" else null, "domain_revision": "1", "saved_sessions": [{"domain_session_id": generation, "created_at": "2026-10-26", "ended_at": null, "ended_by": null, "high_water_mark": "0"}], "state_store": {"backend": "sqlite", "continuity_id": "00000000-0000-4000-8000-000000000001", "durable": true, "continuity": "project", "error_type": null}, "request_id": id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": generation, "state": lifecycle, "execution_state": "idle"}

func result(output: String, generation: String = "A", request: String = "run") -> Dictionary:
	return {"type": "domain_result", "protocol_version": 2, "execution_id": "E-" + generation, "request_id": request, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": generation, "output_id": output, "agent_id": "systems-architect", "task": "work", "output": "answer " + output, "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": true, "revision": 4, "error_type": null}}

func complete(id: String, high: String, earliest: Variant = "1", gap: bool = false, generation: String = "A") -> Dictionary:
	var p := state(id, generation)
	p.merge({"type": "resume_complete", "high_water_mark": high, "earliest_output_id": earliest, "history_gap": gap, "ended": false}, true)
	return p

func fresh() -> RefCounted:
	var s = Store.new()
	s.bind_project("P")
	check(s.admit_command(command("domain_status", "discover")), "status admitted")
	s.apply_packet(state("discover"))
	return s

func replay(s: RefCounted, id: String = "replay") -> void:
	var p := command("resume", id)
	p.cursor = s.snapshot("core").received_cursor
	check(s.admit_command(p), "replay admitted")

func _ready() -> void:
	BridgeClient.set_process(false)
	Store = load("res://scenes/bridge/domain_store.gd")
	if Store == null or not Store.can_instantiate():
		check(false, "DomainStore loads")
		finish()
		return
	var s = fresh()
	replay(s)
	var changed: Dictionary = s.apply_packet(result("1"))
	check(changed == {"scope": "domain", "domain_id": "core", "reason": "domain_result", "request_id": "run", "settled": true, "project_changed": false}, "change envelope uses original Run correlation and committed domain scope")
	s.apply_packet(complete("replay", "1"))
	check(s.snapshot("core").received_cursor == "1" and s.snapshot("core").pending_control.is_empty(), "initial replay completes")
	var copy: Dictionary = s.snapshot("core")
	copy.results[0].output = "mutated"
	check(s.snapshot("core").results[0].output == "answer 1", "snapshots are deep copies")
	s = fresh()
	replay(s)
	s.apply_packet(complete("replay", "0", null))
	check(s.snapshot("core").received_cursor == "0" and s.snapshot("core").pending_control.is_empty(), "empty completion settles replay")
	s = fresh()
	replay(s)
	for n in ["3", "1", "2"]: s.apply_packet(result(n))
	s.apply_packet(complete("replay", "2"))
	check(s.snapshot("core").received_cursor == "3" and ids(s) == ["1", "2", "3"], "live ahead of replay keeps ordered unique prefix")
	for n in ["4", "5", "7"]: s.apply_packet(result(n))
	check(s.snapshot("core").received_cursor == "5", "hidden lower ID prevents cursor jump")
	for n in ["6", "10", "9", "8"]: s.apply_packet(result(n))
	check(s.snapshot("core").received_cursor == "10" and ids(s).slice(8) == ["9", "10"], "numeric ordering 9 before 10")
	s.mark_read("core", "11")
	check(s.snapshot("core").consumed_cursor == "0", "read beyond prefix rejected")
	s.mark_read("core", "9")
	check(s.snapshot("core").consumed_cursor == "9", "read independent from receipt")
	s = fresh()
	replay(s)
	for n in ["3", "1"]: s.apply_packet(result(n))
	s.disconnect_connection()
	check(s.snapshot("core").received_cursor == "1" and s.snapshot("core").uncertain, "drop mid replay retains safe prefix")
	replay(s, "retry")
	s.apply_packet(complete("replay", "100", "99", true))
	check(s.snapshot("core").pending_control.request_id == "retry" and s.snapshot("core").received_cursor == "1", "old connection completion ignored")
	for n in ["2", "3"]: s.apply_packet(result(n))
	s.apply_packet(complete("retry", "3"))
	check(s.snapshot("core").received_cursor == "3" and ids(s) == ["1", "2", "3"], "retry recovers and deduplicates")
	s = fresh()
	replay(s)
	for n in ["3", "4"]: s.apply_packet(result(n))
	s.disconnect_connection()
	check(s.snapshot("core").received_cursor == "0", "unconfirmed gap never inferred")
	replay(s, "retry")
	s.apply_packet(result("5"))
	s.apply_packet(complete("retry", "5", "3", true))
	check(s.snapshot("core").received_cursor == "5" and s.snapshot("core").omitted_count == 2, "explicit pruned prefix counts only missing")
	s.apply_packet(complete("retry", "5", "3", true))
	check(s.snapshot("core").omitted_count == 2, "duplicate completion does not recount gap")
	s = fresh()
	replay(s)
	for n in ["3", "5"]: s.apply_packet(result(n))
	s.apply_packet(complete("replay", "5", "3", true))
	check(s.snapshot("core").received_cursor == "3" and s.snapshot("core").uncertain, "gap cannot skip retained hole")
	replay(s, "retry")
	s.apply_packet(result("7"))
	s.apply_packet(complete("retry", "7", "7", true))
	check(s.snapshot("core").received_cursor == "7" and s.snapshot("core").omitted_count == 4 and "5" in ids(s), "retention moves without recounting received content")
	s = fresh()
	check(s.admit_command(command("domain_query", "run")), "Run admission")
	s.apply_packet(dict_accepted())
	check(s.snapshot("core").pending_query.request_id == "run", "acceptance does not settle query")
	replay(s)
	s.apply_packet(result("1", "A", "other"))
	check(not s.snapshot("core").pending_query.is_empty(), "unrelated terminal never settles query")
	s.apply_packet(result("2"))
	var stale := complete("replay", "1")
	stale.execution_state = "running"
	s.apply_packet(stale)
	check(s.snapshot("core").pending_query.is_empty() and s.snapshot("core").execution_state == "idle" and s.snapshot("core").received_cursor == "2", "live terminal wins over captured completion")
	check(s.admit_command(command("domain_status", "new")), "new generation discovery")
	s.apply_packet(state("new", "B"))
	check(s.admit_command(command("domain_query", "B1", "B")), "new generation run")
	s.apply_packet(result("3", "A"))
	s.apply_packet(complete("replay", "100"))
	check(s.snapshot("core").domain_session_id == "B" and s.snapshot("core").received_cursor == "0" and s.snapshot("core").pending_query.request_id == "B1", "historical packets cannot replace current generation")
	s.disconnect_connection()
	check(s.snapshot("core").pending_query.request_id == "B1" and s.snapshot("core").uncertain, "disconnect preserves uncertain Run")
	s.bind_project("P2")
	s.apply_packet(result("4"))
	check(s.snapshot("core").results.is_empty() and s.snapshot("core").project_id == "P2", "project binding clears and fences old packets")
	s = fresh()
	check(s.set_draft("core", "a".repeat(65536)), "64 KiB draft admitted")
	check(not s.set_draft("core", "a".repeat(65537)), "64 KiB plus one draft rejected")
	check(s.snapshot("core").draft.length() == 65536, "oversized rejection atomic")
	for i in range(1, 230): s.apply_packet(result(str(i)))
	check(s.snapshot("core").results.size() + 1 <= 200 and s.snapshot("core").omitted_count > 0 and s.snapshot("core").received_cursor == "229", "retention includes draft without rewinding receipt")
	var size: int = s.snapshot("core").results.size()
	for i in range(1, 230): s.apply_packet(result(str(i)))
	check(s.snapshot("core").results.size() == size, "evicted duplicates never repopulate display")
	var large := result("230")
	large.output = "雪".repeat(85000)
	for i in range(230, 239):
		large.output_id = str(i)
		s.apply_packet(large)
	check(JSON.stringify(s.snapshot("core").results).to_utf8_buffer().size() + s.snapshot("core").draft.to_utf8_buffer().size() <= 1048576, "UTF8 byte budget includes full retained wire and draft")
	s = fresh()
	for bad in ["-1", "1.0", "١", "1".repeat(129), 1, null]:
		var p := result("1")
		p.output_id = bad
		s.apply_packet(p)
	check(s.snapshot("core").received_cursor == "0" and s.snapshot("core").results.is_empty(), "corrupt decimal IDs never advance")
	var big := "9223372036854775808"
	replay(s)
	s.apply_packet(result(big))
	s.apply_packet(complete("replay", big, big, true))
	check(s.snapshot("core").received_cursor == big, "decimal cursor exceeds signed int64 safely")
	for i in range(300): s.apply_packet(result(str(1000 + i)))
	check(s._domains.core.buckets.A.observed.size() <= 256, "sparse receipt bookkeeping bounded")
	s = Store.new()
	s.bind_project("P")
	check(s.admit_command(command("activate_domain", "start")), "Start admitted")
	s.apply_packet(state("start", "A", "activating"))
	check(s.admit_command(command("deactivate_domain", "stop")), "Stop admitted during Start connect")
	s.apply_packet(state("stop", "A", "inactive"))
	s.apply_packet(state("start"))
	check(s.snapshot("core").state == "inactive", "late active cannot undo Stop")
	check(s.set_draft("engineering", "independent"), "distinct domain draft")
	check(s.snapshot("core").draft == "" and s.snapshot("engineering").draft == "independent", "core and engineering independent")
	additional_vectors()
	review_regressions()
	archive_retention_boundary()
	final_rebinding_regression()
	diagnostic_command_regressions()
	persistence_v2_regressions()
	duplicate_execution_regression()
	stop_status_order_regression()
	backend_discontinuity_regression()
	execution_control_regression()
	catalog_receipt_bound_regression()
	fix_round1_namespace_regressions()
	fix_round1_budget_regressions()
	fix_round1_namespace_validation_regressions()
	fix_round1_metadata_budget_regressions()
	fix_round2_unavailable_owner_regressions()
	finish()

func dict_accepted() -> Dictionary:
	var p := state("run")
	p.type = "domain_accepted"
	p.execution_state = "running"
	p.erase("state")
	p.agent_id = "systems-architect"
	p.task = "work"
	return p

func ids(s: RefCounted) -> Array:
	var out := []
	for r in s.snapshot("core").results: out.append(r.output_id)
	return out

func finish() -> void:
	if failures.is_empty(): print("domain_store_test: OK — %d checks passed." % checks)
	else:
		for failure in failures: printerr("FAIL: " + failure)
	get_tree().quit(0 if failures.is_empty() else 1)


func additional_vectors() -> void:
	var s = fresh()
	check(s.admit_command(command("domain_query", "run")), "busy test Run")
	s.set_draft("core", "preserve")
	var busy := {"type": "domain_error", "request_id": "run", "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": "A", "status": "error", "error_type": "domain_busy", "message": "busy"}
	s.apply_packet(busy)
	check(s.snapshot("core").draft == "preserve" and s.snapshot("core").state == "active" and s.snapshot("core").pending_query.is_empty(), "server busy preserves draft and lifecycle")
	for key in ["request_id", "project_id", "workspace_id", "domain_id", "domain_session_id", "agent_id"]:
		var corrupt := result("1")
		corrupt[key] = "雪".repeat(43)
		s.apply_packet(corrupt)
	check(s.snapshot("core").results.is_empty(), "all identifiers enforce UTF8 byte cap")
	for field in ["status", "output", "task", "truncated", "memory", "reason"]:
		var corrupt := result("1")
		corrupt[field] = []
		s.apply_packet(corrupt)
	check(s.snapshot("core").results.is_empty(), "corrupt terminal shape atomic")
	replay(s)
	for overrides in [{"high_water_mark": "1.0"}, {"earliest_output_id": "2"}, {"history_gap": "true"}, {"history_gap": true}, {"high_water_mark": "9".repeat(129)}]:
		var corrupt := complete("replay", "1")
		corrupt.merge(overrides, true)
		s.apply_packet(corrupt)
	check(s.snapshot("core").pending_control.request_id == "replay" and s.snapshot("core").received_cursor == "0", "corrupt completion cannot settle or advance")
	s.disconnect_connection()
	var illegal := command("domain_status", "illegal")
	illegal.path = "/not-a-client-field"
	check(not s.admit_command(illegal), "commands reject path/extensions")
	for i in range(1, 201): s.apply_packet(result(str(i)))
	s.admit_command(command("domain_status", "B"))
	s.apply_packet(state("B", "B"))
	s.set_draft("core", "draft")
	for i in range(1, 201): s.apply_packet(result(str(i), "B"))
	check(s.snapshot("core").results.size() <= 199 and s.snapshot("core").received_cursor == "200" and s.snapshot("core").consumed_cursor == "0", "combined generations and draft share retention budget")
	s.admit_command(command("domain_status", "C"))
	s.apply_packet(state("C", "C"))
	s.apply_packet(result("201", "A"))
	check(s._domains.core.buckets.size() == 3 and s.snapshot("core").received_cursor == "0", "saved application receipt buckets retain older history independently")
	s = fresh()
	for i in range(1, 301): s.apply_packet(result(str(i * 2)))
	s.apply_packet(result("1"))
	s.apply_packet(result("3"))
	check(s.snapshot("core").received_cursor == "4" and s.snapshot("core").uncertain, "sparse pressure remains explicit and cannot skip hole")
	# A discarded sparse receipt can be learned again even if its text survives.
	s = fresh()
	for i in range(2, 259): s.apply_packet(result(str(i)))
	s.apply_packet(result("1"))
	s.apply_packet(result("258"))
	check(s.snapshot("core").received_cursor == "258", "replay relearns receipt discarded under sparse pressure")
	s = fresh()
	check(s.admit_command(command("domain_status", "status")), "status snapshot admitted")
	s.apply_packet(result("1"))
	var stale := state("status")
	stale.execution_state = "running"
	var change: Dictionary = s.apply_packet(stale)
	check(change.get("reason") == "status_stale" and s.snapshot("core").execution_state == "idle", "status captured before newer terminal cannot overwrite it")
	for i in range(20): s.set_draft("domain" + str(i), "small")
	check(s.domain_ids().size() == 10, "domain identities bounded")
	s = fresh()
	s.set_draft("core", "x".repeat(65536))
	for i in range(1, 5):
		var p := result(str(i))
		p.output = "z".repeat(245000)
		s.apply_packet(p)
	var run := command("domain_query", "pending-big")
	run.task = "p".repeat(65536)
	check(s.admit_command(run), "large pending query admitted")
	check(JSON.stringify(s.snapshot("core")).to_utf8_buffer().size() <= 1048576, "entire public snapshot includes pending draft and full wire within 1 MiB")
	s = fresh()
	s.admit_command(command("domain_status", "invalid"))
	var invalid := state("invalid")
	invalid.available_generations = ["A", "雪".repeat(43)]
	check(s.apply_packet(invalid).is_empty(), "invalid retained generation identifiers rejected")
	invalid = state("invalid")
	invalid.domain_session_id = null
	check(s.apply_packet(invalid).is_empty(), "active state requires a valid generation")
	s = Store.new()
	var discover := {"type": "describe_workspace", "protocol_version": 2, "request_id": "describe"}
	s.admit_command(discover)
	var malformed := {"type": "workspace_state", "protocol_version": 2, "state_store": {"backend": "sqlite", "continuity_id": "00000000-0000-4000-8000-000000000001", "durable": true, "continuity": "project", "error_type": null}, "request_id": "describe", "stage": "ready", "project_id": "P", "workspace_id": "W", "memory": {"status": "saved", "revision": 1}}
	check(s.apply_packet(malformed).is_empty(), "incomplete discovery schema cannot bind a project")
	s = fresh()
	replay(s)
	var maximum := "9".repeat(128)
	s.apply_packet(result(maximum))
	s.apply_packet(complete("replay", maximum, maximum, true))
	check(s.snapshot("core").received_cursor == maximum and s.snapshot("core").omitted_count == 2147483647, "128-digit explicit gap uses bounded arithmetic and saturating omission count")
	s.mark_read("core", maximum)
	check(s.snapshot("core").consumed_cursor == maximum, "128-digit read compares without narrowing")
	s = fresh()
	var wrong_workspace := result("1")
	wrong_workspace.workspace_id = "other-worktree"
	check(s.apply_packet(wrong_workspace).is_empty(), "terminal cannot cross a generation workspace identity")


func review_regressions() -> void:
	# R1: loss before server admission has no terminal, even after clean Stop.
	var s = fresh()
	check(s.admit_command(command("domain_query", "unreceived-run")), "R1 admit locally before loss")
	s.disconnect_connection()
	s.admit_command(command("domain_status", "reconnected"))
	s.apply_packet(state("reconnected"))
	replay(s, "empty-recovery")
	s.apply_packet(complete("empty-recovery", "0", null))
	check(s.snapshot("core").pending_query.request_id == "unreceived-run" and s.snapshot("core").uncertain, "R1 empty replay preserves unknown outcome")
	check(not s.admit_command(command("activate_domain", "too-early")), "R1 active generation cannot bypass unresolved Run")
	s.admit_command(command("deactivate_domain", "clean-stop"))
	s.apply_packet(state("clean-stop", "A", "inactive"))
	check(s.snapshot("core").uncertain, "R1 clean Stop does not invent query outcome")
	check(s.admit_command(command("activate_domain", "explicit-start")), "R1 explicit new Start allowed after confirmed cleanup")
	s.apply_packet(state("explicit-start", "B"))
	var recovered: Dictionary = s.snapshot("core")
	check(recovered.domain_session_id == "B" and recovered.pending_query.is_empty() and recovered.results.is_empty(), "R1 new generation has no fabricated terminal or automatic Run")
	check(recovered.error.get("unresolved_queries", []).size() == 1, "R1 retired unknown input remains inspectable")
	# If the old Run actually reached the bridge, its later replay can resolve it.
	var historical := command("resume", "old-replay", "A")
	check(s.admit_command(historical), "R1 retained generation remains explicitly replayable")
	s.apply_packet(result("1", "A", "unreceived-run"))
	s.apply_packet(complete("old-replay", "1", "1", false, "A"))
	check(s.snapshot("core").results.size() == 1 and s.snapshot("core").error.get("unresolved_queries", []).is_empty() and s.snapshot("core").received_cursor == "0", "R1 historical terminal resolves only archived unknown outcome")
	# R2: lifecycle observation cannot replace missing receipt evidence.
	s = fresh()
	replay(s)
	s.apply_packet(result("3"))
	s.apply_packet(result("5"))
	s.apply_packet(complete("replay", "5", "3", true))
	s.admit_command(command("domain_status", "status-after-hole"))
	check(s.snapshot("core").error.get("error_type") == "replay_incomplete", "R2 status admission preserves receipt error")
	s.apply_packet(state("status-after-hole"))
	check(s.snapshot("core").uncertain and s.snapshot("core").received_cursor == "3" and s.snapshot("core").error.get("error_type") == "replay_incomplete", "R2 fresh status preserves missing receipt uncertainty")
	check(not s.admit_command(command("domain_query", "blocked-by-hole")), "R2 unresolved receipt hole still blocks Run")
	s.apply_packet(result("4"))
	check(not s.snapshot("core").uncertain and s.snapshot("core").error.is_empty() and s.snapshot("core").received_cursor == "5", "R2 actual hole repair resolves receipt uncertainty")
	s = fresh()
	for i in range(2, 259): s.apply_packet(result(str(i)))
	s.admit_command(command("domain_status", "status-after-capacity"))
	s.apply_packet(state("status-after-capacity"))
	check(s.snapshot("core").uncertain and s.snapshot("core").error.get("error_type") == "receipt_capacity", "R2 status cannot erase sparse receipt loss")
	s.apply_packet(result("1"))
	check(s.snapshot("core").uncertain, "R2 reaching retained prefix does not prove discarded receipt")
	s.apply_packet(result("258"))
	check(not s.snapshot("core").uncertain and s.snapshot("core").received_cursor == "258", "R2 relearning discarded receipt resolves its uncertainty")
	# R4: subtract known receipts before saturating the omission count.
	for vector in [["9".repeat(128), 2147483647], ["2147483649", 2147483647], ["2147483648", 2147483646]]:
		s = fresh()
		replay(s)
		s.apply_packet(result("2"))
		s.apply_packet(result(vector[0]))
		s.apply_packet(complete("replay", vector[0], vector[0], true))
		check(s.snapshot("core").received_cursor == vector[0] and s.snapshot("core").omitted_count == vector[1], "R4 observed unavailable-prefix receipt is subtracted before saturation: " + vector[0])


func archive_retention_boundary() -> void:
	# R5: archived unknown-input metadata must fit before publishing new state.
	var s = fresh()
	for n in range(1, 5):
		var terminal := result(str(n), "A", "old-" + str(n))
		terminal.task = "old"
		terminal.output = "x".repeat(262144 if n < 4 else 259500)
		s.apply_packet(terminal)
	var unknown := command("domain_query", "unknown")
	unknown.task = "unknown"
	check(s.admit_command(unknown), "R5 near-full snapshot admits unknown Run")
	s.disconnect_connection()
	s.admit_command(command("domain_status", "recovery"))
	s.apply_packet(state("recovery"))
	s.admit_command(command("deactivate_domain", "stop"))
	s.apply_packet(state("stop", "A", "inactive"))
	check(s.admit_command(command("activate_domain", "fresh")), "R5 explicit Start admitted after confirmed cleanup")
	var before: Dictionary = s.snapshot("core")
	var before_bytes := JSON.stringify(before).to_utf8_buffer().size()
	check(before.results.size() == 4 and before_bytes <= Store.MAX_BYTES and before_bytes > Store.MAX_BYTES - 100, "R5 setup retains four whole terminals just below byte cap")
	var started := state("fresh", "B")
	started.saved_sessions.push_front({"domain_session_id": "A", "created_at": "2026-10-25", "ended_at": null, "ended_by": null, "high_water_mark": "4"})
	var change: Dictionary = s.apply_packet(started)
	var after: Dictionary = s.snapshot("core")
	check(not change.is_empty() and JSON.stringify(after).to_utf8_buffer().size() <= Store.MAX_BYTES, "R5 new-generation acknowledgment enforces complete snapshot byte cap")
	check(after.error.get("unresolved_queries", []) == [unknown] and after.pending_query.is_empty() and after.pending_control.is_empty(), "R5 retention preserves original unknown input after state and control settle")
	check(ids(s) == ["2", "3", "4"] and after.omitted_count == 1 and after.results[0].output == "x".repeat(262144), "R5 archival evicts only oldest whole terminal and counts omission")


func final_rebinding_regression() -> void:
	var s = fresh()
	s.set_draft("core", "prior project private task")
	s.apply_packet(result("1"))
	s.disconnect_connection()
	check(s.admit_command({"type": "describe_workspace", "protocol_version": 2, "request_id": "unconfigured-discovery"}), "final R3 discovery admitted")
	var unconfigured := {"type": "workspace_state", "protocol_version": 2, "state_store": {"backend": "sqlite", "continuity_id": "00000000-0000-4000-8000-000000000001", "durable": true, "continuity": "project", "error_type": null}, "request_id": "unconfigured-discovery", "project_id": null, "workspace_id": null, "stage": "unconfigured", "reason": null, "architect_decision": null, "project_path": null, "worktree_path": null, "branch": null, "changed_files": null, "reservation": null, "memory": {"path": null, "status": "unavailable", "revision": null, "error_type": null}}
	var changed: Dictionary = s.apply_packet(unconfigured)
	check(changed.get("project_changed", false), "final R3 authoritative unconfigured discovery changes prior binding")
	var current: Dictionary = s.snapshot("core")
	check(current.project_id == "" and current.draft == "" and current.results.is_empty() and current.domain_session_id == "", "final R3 unconfigured rebinding clears prior domain data")
	check(s.admit_command(command("activate_domain", "unconfigured-start")), "final R3 Start admitted after authoritative unconfigured discovery")
	var rejection := {"type": "domain_error", "request_id": "unconfigured-start", "project_id": null, "domain_id": "core", "status": "error", "error_type": "workspace_unconfigured", "message": "Configure a project"}
	check(not s.apply_packet(rejection).is_empty() and s.snapshot("core").pending_control.is_empty(), "final R3 unconfigured Start failure settles matching control")
	check(s.snapshot("core").error.get("error_type") == "workspace_unconfigured", "final R3 unconfigured failure remains visible")
	check(s.apply_packet(result("2")).is_empty(), "final R3 prior-project terminal stays fenced")


func diagnostic_command_regressions() -> void:
	for kind in ["activate_domain", "domain_query", "domain_status"]:
		var s = fresh()
		check(s.admit_command(command(kind, "diagnostic")), "diagnostic command admitted: " + kind)
		var failure := state("diagnostic")
		failure.merge({"type": "domain_error", "status": "error", "error_type": "workspace_invalid", "message": "The configured workspace needs inspection.", "terminal_reason": "readiness_failed", "readiness_category": "branch_changed", "tool_input": "synthetic-sensitive"}, true)
		check(not s.apply_packet(failure).is_empty(), "diagnostic error settles actual command: " + kind)
		var notice: Dictionary = s.snapshot("core").error
		check(notice.get("terminal_reason") == "readiness_failed" and notice.get("readiness_category") == "branch_changed", "safe command diagnostics retained: " + kind)
		check(not notice.has("tool_input"), "tool contents excluded from command notice")
		check(s.admit_command(command("domain_status", "passive-refresh")), "passive status admitted after failure")
		s.apply_packet(state("passive-refresh"))
		check(s.snapshot("core").error == notice, "passive status does not erase actionable command notice")
	var s = fresh()
	replay(s, "diagnostic-replay")
	s.apply_packet(complete("diagnostic-replay", "2"))
	check(s.admit_command(command("domain_status", "nested")), "status admitted alongside receipt hole")
	var failure := state("nested")
	failure.merge({"type": "domain_error", "status": "error", "error_type": "workspace_invalid", "message": "Inspect setup.", "terminal_reason": "readiness_failed", "readiness_category": "cwd_mismatch"}, true)
	s.apply_packet(failure)
	var layered: Dictionary = s.snapshot("core").error
	check(layered.get("error_type") == "replay_incomplete" and layered.get("command_error", {}).get("readiness_category") == "cwd_mismatch", "receipt and nested command diagnostics coexist")
	for value in ["synthetic-sensitive", {"private": "synthetic-sensitive"}, 7, null]:
		check(s.admit_command(command("domain_status", "untrusted")), "untrusted metadata fixture admitted")
		failure.request_id = "untrusted"
		failure.terminal_reason = value
		failure.readiness_category = value
		s.apply_packet(failure)
		var untrusted: Dictionary = s.snapshot("core").error.get("command_error", {})
		check(not untrusted.has("terminal_reason") and not untrusted.has("readiness_category"), "unknown or non-string diagnostic metadata omitted")


func persistence_v2_regressions() -> void:
	# Old execution A has a retained terminal; B owns the same application now.
	var s = fresh()
	var switched := state("new-execution")
	switched.execution_id = "E-B"
	switched.domain_revision = "3"
	check(s.admit_command(command("domain_status", "new-execution")), "v2 current authority refresh admitted")
	s.apply_packet(switched)
	var run := command("domain_query", "run-B")
	run.execution_id = "E-B"
	check(s.admit_command(run), "v2 Run targets current execution B")
	var accepted := dict_accepted()
	accepted.request_id = "run-B"
	accepted.execution_id = "E-B"
	s.apply_packet(accepted)
	s.apply_packet(result("1", "A", "old-A"))
	check(s.snapshot("core").get("execution_id") == "E-B" and s.snapshot("core").execution_state == "running" and s.snapshot("core").pending_query.get("request_id") == "run-B", "old A terminal preserves current B token and running state")
	var stale := state("old-status")
	stale.domain_revision = "1"
	s.admit_command(command("domain_status", "old-status"))
	s.apply_packet(stale)
	check(s.snapshot("core").get("execution_id") == "E-B", "lower revision cannot replace B authority")
	# Ended-only discovery restores latest history without an execution or Start.
	s = Store.new()
	s.bind_project("P")
	s.admit_command(command("domain_status", "ended-only"))
	var ended := state("ended-only", "A", "inactive")
	ended.domain_session_id = null
	ended.saved_sessions = [{"domain_session_id": "A", "created_at": "1", "ended_at": "2", "ended_by": "user", "high_water_mark": "1"}, {"domain_session_id": "C", "created_at": "3", "ended_at": "4", "ended_by": "user", "high_water_mark": "0"}]
	s.apply_packet(ended)
	check(s.snapshot("core").get("selected_session_id") == "C" and s.snapshot("core").get("read_only", false) and s.snapshot("core").domain_session_id == "", "ended-only selects latest ended read-only and retains no current application")
	if s.has_method("select_session"):
		check(s.select_session("core", "A"), "older saved session selectable")
		var replay_old := command("resume", "old-history")
		check(s.admit_command(replay_old), "saved ended history replay admitted")
		s.apply_packet(result("1"))
		var completed := complete("old-history", "1")
		completed.ended = true
		s.apply_packet(completed)
		check(s.selected_results("core").size() == 1 and s.snapshot("core").received_cursor == "0", "ended history exact ID receipt does not create current application")
	else: check(false, "saved history selection exists")
	# Unsaved text remains visible without claiming a saved output ID/cursor.
	s = fresh()
	s.set_draft("core", "keep draft")
	var unsaved := result("1")
	unsaved.erase("output_id")
	unsaved.committed = false
	unsaved.status = "error"
	unsaved.reason = "state_store_failed"
	unsaved.erase("truncated")
	s.apply_packet(unsaved)
	check(s.snapshot("core").get("unsaved_results", []).size() == 1 and s.snapshot("core").received_cursor == "0" and s.snapshot("core").draft == "keep draft", "uncommitted answer visible but no saved cursor or draft loss")
	for flag in ["recovered", "committed"]:
		for value in ["false", 1, {}]:
			var malformed := result("1")
			malformed[flag] = value
			check(s.apply_packet(malformed).is_empty() and s.snapshot("core").received_cursor == "0", "malformed boolean cannot change saved receipt: " + flag)
	s.disconnect_connection()
	s.admit_command(command("domain_status", "unsaved-reconnect"))
	s.apply_packet(state("unsaved-reconnect", "A", "inactive"))
	check(s.snapshot("core").unsaved_results.size() == 1 and s.snapshot("core").received_cursor == "0", "reconnect keeps uncommitted text explicitly unsaved")
	var recovered := result("1")
	recovered.recovered = true
	recovered.status = "error"
	recovered.reason = "interrupted"
	recovered.output = "Execution outcome is unknown"
	s.apply_packet(recovered)
	check(s.snapshot("core").unsaved_results.size() == 1 and s.snapshot("core").results.size() == 1 and s.snapshot("core").received_cursor == "1", "saved recovery notice preserves different unsaved partial answer with no saved ID")


func duplicate_execution_regression() -> void:
	for already_received in [false, true]:
		var s = fresh()
		var retained := result("1", "A", "saved-duplicate")
		retained.erase("protocol_version")
		if already_received: s.apply_packet(retained)
		s.admit_command(command("domain_status", "B-authority"))
		var current := state("B-authority")
		current.execution_id = "E-B"
		current.domain_revision = "3"
		s.apply_packet(current)
		var duplicate := command("domain_query", "saved-duplicate")
		duplicate.execution_id = "E-B"
		check(s.admit_command(duplicate), "duplicate request uses B execution authority")
		s.apply_packet(retained)
		var snapshot: Dictionary = s.snapshot("core")
		check(snapshot.pending_query.is_empty() and snapshot.execution_id == "E-B" and snapshot.execution_state == "idle" and snapshot.state == "active" and snapshot.results.size() == 1, "retained duplicate settles exact request once without altering B authority; previously received=" + str(already_received))


func backend_discontinuity_regression() -> void:
	var s = fresh()
	s.apply_packet(result("1"))
	s.admit_command(command("domain_status", "ended-catalog"))
	var catalog := state("ended-catalog")
	catalog.saved_sessions.push_front({"domain_session_id": "C", "created_at": "1", "ended_at": "2", "ended_by": "user", "high_water_mark": "0"})
	s.apply_packet(catalog)
	s.select_session("core", "C")
	s.disconnect_connection()
	s.admit_command(command("domain_status", "memory-reconnect"))
	var memory := state("memory-reconnect", "A", "inactive")
	memory.domain_session_id = null
	memory.saved_sessions = []
	memory.state_store = {"backend": "memory", "continuity_id": "00000000-0000-4000-8000-000000000002", "durable": false, "continuity": "process", "error_type": null}
	s.apply_packet(memory)
	check(s.snapshot("core").selected_session_id == "" and s.snapshot("core").results.is_empty(), "switch to memory cannot present selected SQLite history as process continuity")
	check(s.apply_packet(result("2")).is_empty(), "old backend packets cannot reintroduce old application history")


func execution_control_regression() -> void:
	var s = fresh()
	check(s.admit_command(command("background_domain", "A-background")), "A background pending before another execution")
	s.admit_command(command("domain_status", "observe-B"))
	var current := state("observe-B")
	current.execution_id = "E-B"
	current.domain_revision = "3"
	s.apply_packet(current)
	check(s.snapshot("core").pending_control.is_empty() and s.snapshot("core").execution_id == "E-B", "B authority retires A pending control within same application")
	s.apply_packet(state("A-background", "A", "background"))
	check(s.snapshot("core").execution_id == "E-B" and s.snapshot("core").state == "active", "late A lifecycle cannot replace B after same-app switch")


func catalog_receipt_bound_regression() -> void:
	var s = fresh()
	for index in range(140):
		var id := "catalog-" + str(index)
		s.admit_command(command("domain_status", id))
		var status := state(id)
		status.saved_sessions.append({"domain_session_id": "old-" + str(index), "created_at": "1", "ended_at": "2", "ended_by": "user", "high_water_mark": "0"})
		s.apply_packet(status)
	check(s._domains.core.buckets.size() <= 128 and s.snapshot("core").domain_session_id == "A", "catalog turnover keeps receipt metadata bounded without evicting current authority")


func fix_round1_namespace_regressions() -> void:
	for old_backend in ["sqlite", "memory"]:
		for nested in [false, true]:
			for revision in ["0", "9"]:
				var s = fresh()
				s.admit_command(command("domain_status", "old-namespace"))
				var old := state("old-namespace")
				old.domain_revision = "3"
				if old_backend == "memory": old.state_store = {"backend": "memory", "continuity_id": "00000000-0000-4000-8000-000000000002", "durable": false, "continuity": "process", "error_type": null}
				s.apply_packet(old)
				s.apply_packet(result("1"))
				s.disconnect_connection()
				var reset := state("new-namespace", "A", "inactive")
				reset.domain_session_id = null
				reset.saved_sessions = []
				reset.domain_revision = revision
				reset.state_store = {"backend": "memory", "continuity_id": "00000000-0000-4000-8000-000000000003", "durable": false, "continuity": "process", "error_type": null}
				var accepted: bool
				if nested: accepted = s.observe_domain(reset, s.observation_fence())
				else:
					s.admit_command(command("domain_status", "new-namespace"))
					accepted = s.apply_packet(reset).get("reason") == "domain_state"
				var after: Dictionary = s.snapshot("core")
				check(accepted and after.domain_revision == revision and after.domain_session_id == "" and after.results.is_empty(), "new %s namespace replaces %s authority at revision %s via %s" % ["memory", old_backend, revision, "observation" if nested else "status"])
	var s = fresh()
	s.admit_command(command("domain_status", "current-namespace"))
	var current := state("current-namespace")
	current.domain_revision = "3"
	s.apply_packet(current)
	var unsaved := result("1", "A", "local-unsaved")
	unsaved.erase("output_id")
	unsaved.committed = false
	s.apply_packet(unsaved)
	s.disconnect_connection()
	s.admit_command(command("domain_status", "same-namespace"))
	current.request_id = "same-namespace"
	s.apply_packet(current)
	check(s.snapshot("core").unsaved_results.size() == 1 and s.snapshot("core").execution_id == "E-A", "same namespace reconnect preserves unsaved text and authority")
	s.admit_command(command("domain_status", "same-namespace-stale"))
	var stale := state("same-namespace-stale")
	stale.domain_revision = "2"
	check(s.apply_packet(stale).get("reason") == "status_stale" and s.snapshot("core").domain_revision == "3", "same namespace still rejects lower revisions")
	check(not s.observe_domain(stale, s.observation_fence()) and s.snapshot("core").unsaved_results.size() == 1, "nested stale same-namespace observation preserves unsaved text")
	s = Store.new()
	s.bind_project("P")
	s.admit_command(command("domain_status", "empty-sqlite"))
	var empty := state("empty-sqlite", "A", "inactive")
	empty.domain_session_id = null
	empty.domain_revision = "0"
	empty.saved_sessions = []
	empty.state_store.continuity_id = null
	s.apply_packet(empty)
	s.set_draft("core", "first Start draft")
	var start := command("activate_domain", "first-start")
	start.expected_domain_revision = "0"
	check(s.admit_command(start), "uninitialized SQLite Start admitted")
	s.apply_packet(state("first-start", "A", "activating"))
	check(s.snapshot("core").draft == "first Start draft" and s.snapshot("core").pending_control.get("request_id") == "first-start", "SQLite instance initialization does not retire pending first Start or draft")


func fix_round1_budget_regressions() -> void:
	var s = fresh()
	var generation := "A"
	for index in range(18):
		var run := command("domain_query", "unknown-" + str(index), generation)
		run.task = "u".repeat(65536)
		check(s.admit_command(run), "large unknown input admitted before archival")
		var next_generation := "archive-" + str(index)
		var status_id := "archive-status-" + str(index)
		s.admit_command(command("domain_status", status_id))
		s.apply_packet(state(status_id, next_generation))
		generation = next_generation
	var archive: Dictionary = s.snapshot("core")
	check(JSON.stringify(archive).to_utf8_buffer().size() <= Store.MAX_BYTES and archive.get("omitted_unknown_count", 0) > 0, "multiple archived 64-KiB inputs fit aggregate byte budget with explicit unknown omission")
	check(archive.domain_session_id == generation and archive.pending_query.is_empty() and archive.error.get("unresolved_queries_omitted", 0) > 0, "unknown omission preserves current authority and unknown-outcome disclosure")
	s = fresh()
	for index in range(199):
		var unsaved := result("1", "A", "unsaved-" + str(index))
		unsaved.erase("output_id")
		unsaved.committed = false
		s.apply_packet(unsaved)
	s.set_draft("core", "next draft")
	check(s.admit_command(command("domain_query", "current-pending")), "pending current Run admitted at unsaved retention boundary")
	check(s.admit_command(command("background_domain", "current-control")), "current control admitted at retention boundary")
	var pending: Dictionary = s.snapshot("core")
	var entries: int = pending.results.size() + pending.unsaved_results.size() + pending.saved_sessions.size() + pending.memory_reconciliation.size() + (0 if pending.draft == "" else 1) + (0 if pending.pending_query.is_empty() else 1) + (0 if pending.pending_control.is_empty() else 1) + pending.error.get("unresolved_queries", []).size()
	check(entries <= Store.MAX_ENTRIES and pending.pending_query.get("request_id") == "current-pending" and pending.draft == "next draft" and pending.pending_control.get("request_id") == "current-control", "unsaved/draft/pending/catalog share one entry budget without dropping current correlation")


func fix_round1_namespace_validation_regressions() -> void:
	var s = fresh()
	s.apply_packet(result("1"))
	for invalid in ["protocol", "project", "flag", "identity", "storage_error_field"]:
		var id: String = "invalid-namespace-" + invalid
		s.admit_command(command("domain_status", id))
		var packet := state(id, "A", "inactive")
		packet.domain_session_id = null
		packet.saved_sessions = []
		packet.domain_revision = "0"
		packet.state_store = {"backend": "memory", "continuity_id": "00000000-0000-4000-8000-000000000003", "durable": false, "continuity": "process", "error_type": null}
		if invalid == "protocol": packet.protocol_version = 1
		elif invalid == "project": packet.project_id = "OTHER"
		elif invalid == "flag": packet.state_store.durable = "false"
		elif invalid == "identity": packet.state_store.erase("continuity_id")
		else: packet.state_store.erase("error_type")
		check(s.apply_packet(packet).is_empty() and s.snapshot("core").results.size() == 1 and s.snapshot("core").domain_session_id == "A", "invalid namespace packet cannot mutate cache: " + invalid)
		var valid := state(id)
		s.apply_packet(valid)
	s.disconnect_connection()
	s.admit_command(command("domain_status", "unknown-store"))
	var failed := state("unknown-store", "A", "inactive")
	failed.domain_session_id = null
	failed.saved_sessions = []
	failed.domain_revision = "0"
	failed.state_store.continuity_id = null
	failed.state_store.error_type = "state_store_invalid"
	s.apply_packet(failed)
	var blocked: Dictionary = s.snapshot("core")
	check(blocked.authority_unavailable and blocked.execution_id == "" and blocked.read_only and blocked.state_store.error_type == "state_store_invalid" and blocked.results.size() == 1, "unidentified failed store exposes fault and keeps only read-only cached history")
	check(not s.admit_command(command("domain_query", "no-unidentified-work")), "unidentified store cannot authorize cached work")


func fix_round1_metadata_budget_regressions() -> void:
	var s = fresh()
	s.admit_command(command("domain_status", "large-status-metadata"))
	var metadata := state("large-status-metadata")
	metadata.state_store.diagnostic_extension = "x".repeat(995000)
	s.apply_packet(metadata)
	s.set_draft("core", "d".repeat(65536))
	check(s.admit_command(command("domain_query", "metadata-current")), "current correlation admitted with extended status metadata")
	check(JSON.stringify(s.snapshot("core")).to_utf8_buffer().size() <= Store.MAX_BYTES and s.snapshot("core").pending_query.get("request_id") == "metadata-current", "retained status facts cannot bypass aggregate byte budget through extensions")
	s = fresh()
	var terminal := result("1")
	terminal.memory.path = "p".repeat(995000)
	s.apply_packet(terminal)
	s.set_draft("core", "d".repeat(65536))
	check(s.admit_command(command("domain_query", "memory-current")), "current correlation admitted with extended terminal memory")
	check(JSON.stringify(s.snapshot("core")).to_utf8_buffer().size() <= Store.MAX_BYTES and s.snapshot("core").pending_query.get("request_id") == "memory-current", "terminal memory extensions cannot escape text eviction into retained status facts")


func fix_round2_unavailable_owner_regressions() -> void:
	for nested in [false, true]:
		for target in ["lower-B", "higher-B", "same-A", "stale-A"]:
			var s = fresh()
			s.admit_command(command("domain_status", "owner-A"))
			var current := state("owner-A")
			current.domain_revision = "3"
			s.apply_packet(current)
			s.apply_packet(result("1"))
			var unsaved := result("2", "A", "owner-A-unsaved")
			unsaved.erase("output_id")
			unsaved.committed = false
			s.apply_packet(unsaved)
			s.set_draft("core", "same project draft")
			s.disconnect_connection()
			var unavailable := state("unavailable", "A", "inactive")
			unavailable.domain_session_id = null
			unavailable.domain_revision = "0"
			unavailable.saved_sessions = []
			unavailable.state_store.continuity_id = null
			unavailable.state_store.error_type = "state_store_invalid"
			if nested: check(s.observe_domain(unavailable, s.observation_fence()), "nested unavailable snapshot accepted")
			else:
				s.admit_command(command("domain_status", "unavailable"))
				check(s.apply_packet(unavailable).get("reason") == "domain_state", "correlated unavailable snapshot accepted")
			check(s.snapshot("core").authority_unavailable and s.snapshot("core").results.size() == 1 and s.snapshot("core").unsaved_results.size() == 1, "unavailable facts preserve read-only cache without claiming identity")
			var replacement := state("replacement", "B" if target.ends_with("B") else "A")
			replacement.domain_revision = {"lower-B": "1", "higher-B": "9", "same-A": "3", "stale-A": "2"}[target]
			if target.ends_with("B"): replacement.state_store.continuity_id = "00000000-0000-4000-8000-000000000004"
			var accepted: bool
			if nested: accepted = s.observe_domain(replacement, s.observation_fence())
			else:
				s.admit_command(command("domain_status", "replacement"))
				accepted = s.apply_packet(replacement).get("reason") == "domain_state"
			var observed: Dictionary = s.snapshot("core")
			if target.ends_with("B"):
				check(accepted and observed.domain_session_id == "B" and observed.domain_revision == replacement.domain_revision and observed.results.is_empty() and observed.unsaved_results.is_empty() and observed.received_cursor == "0" and observed.selected_session_id == "B", "A→unavailable→%s resets cache before comparing revisions via %s" % [target, "nested observation" if nested else "status"])
			elif target == "same-A":
				check(accepted and not observed.authority_unavailable and observed.domain_session_id == "A" and observed.results.size() == 1 and observed.unsaved_results.size() == 1 and observed.received_cursor == "1" and observed.draft == "same project draft", "same A recovery retains saved/unsaved cache and draft")
			else:
				check(not accepted and observed.domain_revision == "3" and observed.authority_unavailable and observed.results.size() == 1, "unavailable interval does not relax same-A lower-revision fencing")


func stop_status_order_regression() -> void:
	for replacement in [false, true]:
		var s = fresh()
		check(s.admit_command(command("deactivate_domain", "pending-stop")), "Stop admitted before concurrent status")
		check(s.admit_command(command("domain_status", "stopped-observation")), "status observes pending Stop independently")
		var stopped := state("stopped-observation", "A", "inactive")
		stopped.domain_revision = "3"
		s.apply_packet(stopped)
		check(s.snapshot("core").execution_id == "" and s.snapshot("core").pending_control.get("request_id") == "pending-stop", "inactive status clears authority but retains exact pending Stop")
		if replacement:
			check(s.admit_command(command("domain_status", "replacement")), "new execution observed on separate client")
			var current := state("replacement")
			current.execution_id = "E-B"
			current.domain_revision = "4"
			s.apply_packet(current)
		stopped.request_id = "pending-stop"
		var change: Dictionary = s.apply_packet(stopped)
		var snapshot: Dictionary = s.snapshot("core")
		if replacement:
			check(change.is_empty() and snapshot.execution_id == "E-B" and snapshot.state == "active" and snapshot.domain_revision == "4", "late Stop ack cannot roll back later execution or revision")
		else:
			check(change.get("request_id") == "pending-stop" and change.get("reason") == "domain_state" and snapshot.pending_control.is_empty() and snapshot.state == "inactive" and snapshot.execution_id == "" and snapshot.domain_revision == "3", "exact Stop ack settles after trusted inactive status without restoring old authority")
