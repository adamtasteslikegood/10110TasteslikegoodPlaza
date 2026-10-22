extends Node

var checks := 0
var failures: Array[String] = []
var Store: Script

func check(ok: bool, message: String) -> void:
	checks += 1
	if not ok: failures.append(message)

func command(kind: String, id: String, generation: String = "A") -> Dictionary:
	var p := {"type": kind, "domain_id": "core", "request_id": id}
	if kind not in ["activate_domain", "domain_status"]: p.domain_session_id = generation
	if kind == "resume": p.cursor = "0"
	if kind == "domain_query": p.merge({"agent_id": "systems-architect", "task": "work"})
	return p

func state(id: String, generation: String = "A", lifecycle: String = "active") -> Dictionary:
	return {"type": "domain_state", "request_id": id, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": generation, "state": lifecycle, "execution_state": "idle"}

func result(output: String, generation: String = "A", request: String = "run") -> Dictionary:
	return {"type": "domain_result", "request_id": request, "project_id": "P", "workspace_id": "W", "domain_id": "core", "domain_session_id": generation, "output_id": output, "agent_id": "systems-architect", "task": "work", "output": "answer " + output, "status": "success", "reason": "completed", "truncated": false, "memory": {"saved": true, "revision": 4, "error_type": null}}

func complete(id: String, high: String, earliest: Variant = "1", gap: bool = false, generation: String = "A") -> Dictionary:
	var p := state(id, generation)
	p.merge({"type": "resume_complete", "high_water_mark": high, "earliest_output_id": earliest, "history_gap": gap}, true)
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
	check(s._domains.core.buckets.size() == 2 and s.snapshot("core").received_cursor == "0", "only two generations retained and unknown history ignored")
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
	var discover := {"type": "describe_workspace", "request_id": "describe"}
	s.admit_command(discover)
	var malformed := {"type": "workspace_state", "request_id": "describe", "stage": "ready", "project_id": "P", "workspace_id": "W", "memory": {"status": "saved", "revision": 1}}
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
		terminal.output = "x".repeat(262144 if n < 4 else 260350)
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
	var change: Dictionary = s.apply_packet(state("fresh", "B"))
	var after: Dictionary = s.snapshot("core")
	check(not change.is_empty() and JSON.stringify(after).to_utf8_buffer().size() <= Store.MAX_BYTES, "R5 new-generation acknowledgment enforces complete snapshot byte cap")
	check(after.error.get("unresolved_queries", []) == [unknown] and after.pending_query.is_empty() and after.pending_control.is_empty(), "R5 retention preserves original unknown input after state and control settle")
	check(ids(s) == ["2", "3", "4"] and after.omitted_count == 1 and after.results[0].output == "x".repeat(262144), "R5 archival evicts only oldest whole terminal and counts omission")


func final_rebinding_regression() -> void:
	var s = fresh()
	s.set_draft("core", "prior project private task")
	s.apply_packet(result("1"))
	s.disconnect_connection()
	check(s.admit_command({"type": "describe_workspace", "request_id": "unconfigured-discovery"}), "final R3 discovery admitted")
	var unconfigured := {"type": "workspace_state", "request_id": "unconfigured-discovery", "project_id": null, "workspace_id": null, "stage": "unconfigured", "reason": null, "architect_decision": null, "project_path": null, "worktree_path": null, "branch": null, "changed_files": null, "reservation": null, "memory": {"path": null, "status": "unavailable", "revision": null, "error_type": null}}
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
