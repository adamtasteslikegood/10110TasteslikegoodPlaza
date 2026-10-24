class_name DomainStore
extends RefCounted

## Pure, session-only domain display state. Receipt coverage is independent of
## retained text. No transport, filesystem, UI, or provider state lives here.
const MAX_ENTRIES := 200
const MAX_BYTES := 1048576
const MAX_SPARSE := 256
const MAX_DOMAINS := 10
const STATES := ["inactive", "activating", "active", "background", "stopping", "cleanup_failed"]
const EXECUTION := ["idle", "running", "stopping", "cleanup_failed"]
const COMMANDS := ["describe_workspace", "domain_status", "activate_domain", "domain_query", "background_domain", "refocus_domain", "deactivate_domain", "resume"]
const TERMINAL_REASONS := ["sdk_error", "assistant_error", "permission_denied", "readiness_failed", "max_turns", "max_budget_usd", "max_tokens", "output_limit", "missing_terminal", "transport_error", "deferred_tool_use", "completed", "stopped", "not_executed"]
const READINESS_CATEGORIES := ["cwd_mismatch", "branch_changed", "workspace_invalid", "lease_invalid", "memory_unavailable", "tool_correlation_invalid", "readiness_timeout", "readiness_error", "readiness_cancelled", "workspace_not_ready", "workspace_busy", "cleanup_failed", "context_unavailable"]

var _project_id := ""
var _workspace: Dictionary = {}
var _domains: Dictionary = {}
var _commands: Dictionary = {}
var _epoch := 0


static func valid_id(value: Variant) -> bool:
	return value is String and not value.strip_edges().is_empty() and value.to_utf8_buffer().size() <= 128


static func valid_domain(value: Variant) -> bool:
	if not valid_id(value): return false
	for c in value:
		if not (c >= "a" and c <= "z" or c >= "A" and c <= "Z" or c >= "0" and c <= "9" or c in ["_", "-"]): return false
	return true


static func decimal(value: Variant) -> String:
	if not valid_id(value): return ""
	for c in value:
		if c < "0" or c > "9": return ""
	var n: String = value
	while n.length() > 1 and n.begins_with("0"): n = n.substr(1)
	return n


static func compare(a: String, b: String) -> int:
	if a.length() != b.length(): return -1 if a.length() < b.length() else 1
	return 0 if a == b else (-1 if a < b else 1)


static func successor(a: String) -> String:
	var chars := a.to_utf8_buffer()
	for i in range(chars.size() - 1, -1, -1):
		if chars[i] < 57:
			chars[i] += 1
			return chars.get_string_from_utf8()
		chars[i] = 48
	return "1" + chars.get_string_from_utf8()


static func predecessor(a: String) -> String:
	if a == "0": return "0"
	var chars := a.to_utf8_buffer()
	for i in range(chars.size() - 1, -1, -1):
		if chars[i] > 48:
			chars[i] -= 1
			return decimal(chars.get_string_from_utf8())
		chars[i] = 57
	return "0"


# Omission notices saturate; receipt arithmetic never narrows to int64.
static func distance_capped(a: String, b: String, observed_count: int = 0) -> int:
	var difference := _subtract_decimal(a, b)
	var known := str(observed_count)
	if compare(difference, known) <= 0:
		return 0
	difference = _subtract_decimal(difference, known)
	return 2147483647 if compare(difference, "2147483647") >= 0 else int(difference)


static func _subtract_decimal(a: String, b: String) -> String:
	var out := ""
	var borrow := 0
	var padded := b.lpad(a.length(), "0")
	for i in range(a.length() - 1, -1, -1):
		var digit := a.unicode_at(i) - padded.unicode_at(i) - borrow
		borrow = 1 if digit < 0 else 0
		out = str(digit + 10 if digit < 0 else digit) + out
	return decimal(out)


func bind_project(project_id: String) -> void:
	if project_id != "" and not valid_id(project_id): return
	if project_id == _project_id: return
	_project_id = project_id
	_domains.clear()
	_commands.clear()
	_workspace.clear()


func workspace_snapshot() -> Dictionary:
	return _workspace.duplicate(true)


func domain_ids() -> Array:
	return _domains.keys()


func _domain(id: String) -> Dictionary:
	if not valid_domain(id): return {}
	if not _domains.has(id):
		if _domains.size() >= MAX_DOMAINS: return {}
		_domains[id] = {"project_id": _project_id, "domain_id": id, "domain_session_id": "", "workspace_id": "", "state": "inactive", "execution_state": "idle", "pending_query": {}, "pending_control": {}, "draft": "", "results": [], "omitted_count": 0, "uncertain": false, "error": {}, "memory": {}, "buckets": {}, "version": 0, "lifecycle_uncertain": false, "query_uncertain": false, "cleanup_confirmed": false}
	return _domains[id]


func snapshot(domain_id: String) -> Dictionary:
	var d := _domain(domain_id)
	if d.is_empty(): return {}
	var out := d.duplicate(true)
	out.erase("buckets")
	out.erase("version")
	out.erase("lifecycle_uncertain")
	out.erase("query_uncertain")
	out.erase("cleanup_confirmed")
	var b: Dictionary = d.buckets.get(d.domain_session_id, {})
	out.received_cursor = b.get("received", "0")
	out.consumed_cursor = b.get("consumed", "0")
	if not b.get("receipt_error", {}).is_empty():
		out.error = b.receipt_error.duplicate(true)
		if not d.error.is_empty(): out.error.command_error = d.error.duplicate(true)
	var unresolved := _unresolved_queries(d)
	if not unresolved.is_empty():
		if out.error.is_empty():
			out.error = {"error_type": "unknown_outcome", "message": "An earlier generation's Run outcome is unknown"}
		out.error.unresolved_queries = unresolved
	return out


func set_draft(domain_id: String, text: String) -> bool:
	if text.to_utf8_buffer().size() > 65536: return false
	var d := _domain(domain_id)
	if d.is_empty(): return false
	d.draft = text
	_trim(d)
	return true


func mark_read(domain_id: String, output_id: String) -> void:
	var n := decimal(output_id)
	var d := _domain(domain_id)
	if n == "" or d.is_empty() or not d.buckets.has(d.domain_session_id): return
	var b: Dictionary = d.buckets[d.domain_session_id]
	if compare(n, b.received) <= 0 and compare(n, b.consumed) > 0: b.consumed = n


func disconnect_connection() -> void:
	_epoch += 1
	_commands.clear()
	for d in _domains.values():
		d.pending_control = {}
		d.lifecycle_uncertain = d.domain_session_id != ""
		d.query_uncertain = not d.pending_query.is_empty()
		_refresh_uncertainty(d)


func admit_command(packet: Dictionary) -> bool:
	var kind: Variant = packet.get("type")
	var id: Variant = packet.get("request_id")
	if kind not in COMMANDS or not valid_id(id) or _commands.has(id):
		return false
	var fields := ["type", "request_id"]
	if kind != "describe_workspace":
		fields.append("domain_id")
	if kind not in ["describe_workspace", "domain_status", "activate_domain"]:
		fields.append("domain_session_id")
	if kind == "domain_query":
		fields.append_array(["agent_id", "task"])
	if kind == "resume":
		fields.append("cursor")
	if packet.size() != fields.size():
		return false
	for key in fields:
		if not packet.has(key):
			return false
	if kind == "describe_workspace":
		for c in _commands.values():
			if c.type == kind:
				return false
		_commands[id] = {"type": kind, "request_id": id, "epoch": _epoch}
		return true
	var d := _domain(packet.get("domain_id", "")) if packet.get("domain_id") is String else {}
	if d.is_empty():
		return false
	if kind == "domain_status":
		for c in _commands.values():
			if c.type == kind and c.domain_id == d.domain_id:
				return false
	elif kind == "activate_domain":
		if not d.pending_control.is_empty():
			return false
		if not d.pending_query.is_empty() and not d.cleanup_confirmed:
			return false
	else:
		if not valid_id(packet.get("domain_session_id")):
			return false
		if kind == "resume":
			if not d.buckets.has(packet.domain_session_id):
				return false
		elif packet.domain_session_id != d.domain_session_id:
			return false
		if kind == "domain_query":
			if not d.pending_query.is_empty() or d.uncertain or d.state not in ["active", "background"]:
				return false
			var valid_task: bool = (
				packet.get("task") is String
				and not packet.task.strip_edges().is_empty()
				and packet.task.to_utf8_buffer().size() <= 65536
			)
			if not valid_id(packet.get("agent_id")) or not valid_task:
				return false
		elif kind == "resume":
			if decimal(packet.get("cursor")) == "" or not d.pending_control.is_empty():
				return false
		elif not d.pending_control.is_empty():
			if kind != "deactivate_domain" or d.pending_control.type != "activate_domain":
				return false
			# Stop supersedes a still-connecting Start. Late active is now fenced.
			_commands.erase(d.pending_control.request_id)
	if kind not in ["domain_status", "domain_query"] and not d.pending_control.is_empty() and kind != "deactivate_domain":
		return false
	var c := packet.duplicate(true)
	c.epoch = _epoch
	c.version = d.version
	if kind != "domain_status": d.version += 1
	_commands[id] = c
	if kind == "domain_query":
		d.pending_query = packet.duplicate(true)
	elif kind != "domain_status":
		d.pending_control = packet.duplicate(true)
	# Status observes lifecycle; even a healthy owner does not prove that the
	# failed task's readiness cause has been repaired. Keep its actionable notice
	# through automatic status refresh until another explicit work/control action.
	if kind != "domain_status": d.error = {}
	_trim(d)
	return true


## Accepted changes return {scope, domain_id, reason, request_id, settled,
## project_changed}. Empty means ignored with no notification. Reasons are wire
## packet types; state is committed before the envelope is returned.
func apply_packet(packet: Dictionary) -> Dictionary:
	var kind: Variant = packet.get("type")
	var id: Variant = packet.get("request_id")
	if not valid_id(id):
		return {}
	var c: Dictionary = _commands.get(id, {})
	if not c.is_empty() and c.epoch != _epoch:
		return {}
	if kind == "workspace_state":
		return _apply_workspace(packet, c)
	if kind == "domain_error" and c.get("type") == "describe_workspace":
		if not _valid_error(packet):
			return {}
		_commands.erase(id)
		_workspace.error = packet.duplicate(true)
		return _change("workspace", "", kind, id)
	if kind not in ["domain_state", "domain_accepted", "domain_result", "domain_error", "resume_complete"]:
		return {}
	if not valid_domain(packet.get("domain_id")) or not _domains.has(packet.domain_id):
		return {}
	var d: Dictionary = _domains[packet.domain_id]
	var same_project: bool = packet.get("project_id") == _project_id
	var unconfigured_project: bool = _project_id == "" and packet.get("project_id") == null
	if not same_project and not unconfigured_project:
		return {}
	if packet.get("workspace_id") != null and not valid_id(packet.workspace_id):
		return {}
	var generation: Variant = packet.get("domain_session_id")
	if generation != null and not valid_id(generation):
		return {}
	if d.buckets.has(generation):
		var same_workspace: bool = d.buckets[generation].get("workspace_id") == packet.get("workspace_id")
		if not same_workspace:
			return {}
	if not c.is_empty():
		if c.get("domain_id") != d.domain_id:
			return {}
		if c.has("domain_session_id") and c.domain_session_id != generation:
			return {}
	if kind == "domain_result":
		return _apply_result(d, packet)
	if c.is_empty():
		return {}
	if kind == "domain_error":
		if not _valid_error(packet):
			return {}
		d.error = {"error_type": packet.error_type, "message": packet.message}
		if packet.get("terminal_reason") is String and packet.terminal_reason in TERMINAL_REASONS:
			d.error.terminal_reason = packet.terminal_reason
		if packet.get("readiness_category") is String and packet.readiness_category in READINESS_CATEGORIES:
			d.error.readiness_category = packet.readiness_category
		if d.pending_query.get("request_id") == id:
			d.pending_query = {}
			d.query_uncertain = false
		_refresh_uncertainty(d)
		_settle(d, id)
		_trim(d)
		return _change("domain", d.domain_id, kind, id)
	if kind == "resume_complete":
		return _apply_completion(d, packet, c)
	if kind == "domain_accepted":
		if c.type != "domain_query" or d.pending_query.get("request_id") != id or generation != d.domain_session_id:
			return {}
		if packet.get("execution_state") != "running" or packet.get("agent_id") != d.pending_query.agent_id or packet.get("task") != d.pending_query.task:
			return {}
		d.execution_state = "running"
		d.version += 1
		# Keep the original command until its terminal or disconnect.
		return _change("domain", d.domain_id, kind, id, false)
	if not _valid_state(packet):
		return {}
	if c.type not in ["activate_domain", "domain_status", "background_domain", "refocus_domain", "deactivate_domain"]:
		return {}
	if c.type == "domain_status" and c.version != d.version:
		_settle(d, id)
		return _change("domain", d.domain_id, "status_stale", id)
	if generation != null and generation != d.domain_session_id:
		if c.type not in ["activate_domain", "domain_status"]:
			return {}
		_switch_generation(d, generation)
		if c.type == "activate_domain":
			d.pending_control = {"type": c.type, "domain_id": d.domain_id, "request_id": id}
	elif generation == null and d.domain_session_id != "":
		if c.type != "domain_status":
			return {}
		_switch_generation(d, "")
	d.workspace_id = packet.get("workspace_id", "")
	if d.buckets.has(generation):
		d.buckets[generation].workspace_id = packet.get("workspace_id")
	d.state = packet.state
	d.execution_state = packet.execution_state
	d.version += 1
	d.lifecycle_uncertain = false
	d.cleanup_confirmed = packet.state == "inactive" and packet.execution_state == "idle"
	_refresh_uncertainty(d)
	var settled: bool = not (c.type == "activate_domain" and packet.state == "activating")
	if settled:
		_settle(d, id)
	_trim(d)
	return _change("domain", d.domain_id, kind, id, settled)


func _switch_generation(d: Dictionary, generation: String) -> void:
	# Retire input, not its outcome: no terminal exists until the bridge sends one.
	if not d.pending_query.is_empty() and d.buckets.has(d.domain_session_id):
		d.buckets[d.domain_session_id].unresolved_query = d.pending_query.duplicate(true)
	d.query_uncertain = false
	d.lifecycle_uncertain = false
	d.cleanup_confirmed = false
	for id in _commands.keys():
		var c: Dictionary = _commands[id]
		if c.get("domain_id") == d.domain_id and c.has("domain_session_id") and c.domain_session_id != generation: _commands.erase(id)
	d.pending_query = {}
	d.pending_control = {}
	d.domain_session_id = generation
	if generation == "": return
	if not d.buckets.has(generation): d.buckets[generation] = {"received": "0", "consumed": "0", "observed": {}, "receipt_error": {}, "receipt_fence": "0", "unresolved_query": {}}
	while d.buckets.size() > 2:
		var old: String = d.buckets.keys()[0]
		if not d.buckets[old].unresolved_query.is_empty(): d.omitted_count = mini(2147483647, d.omitted_count + 1)
		d.buckets.erase(old)
		for i in range(d.results.size() - 1, -1, -1):
			if d.results[i].domain_session_id == old:
				d.results.remove_at(i)
				d.omitted_count = mini(2147483647, d.omitted_count + 1)


func _apply_result(d: Dictionary, p: Dictionary) -> Dictionary:
	var n := decimal(p.get("output_id"))
	if n in ["", "0"] or not d.buckets.has(p.get("domain_session_id")): return {}
	if p.get("status") not in ["success", "error", "cancelled"] or not valid_id(p.get("agent_id")): return {}
	if not p.get("task") is String or p.task.to_utf8_buffer().size() > 65536 or not p.get("output") is String or p.output.to_utf8_buffer().size() > 262144: return {}
	if not p.get("reason") is String or not p.get("truncated") is bool or not _valid_memory(p.get("memory"), true): return {}
	# Bound the full shape, including unexpected extensions, before retaining it.
	if JSON.stringify(p).to_utf8_buffer().size() > MAX_BYTES: return {}
	var b: Dictionary = d.buckets[p.domain_session_id]
	if compare(n, b.received) <= 0 or b.observed.has(n): return {}
	var retained := false
	for r in d.results:
		if r.domain_session_id == p.domain_session_id and decimal(r.output_id) == n: retained = true
	b.observed[n] = true
	if not retained: d.results.append(p.duplicate(true))
	var generations: Array = d.buckets.keys()
	d.results.sort_custom(func(a, z):
		if a.domain_session_id != z.domain_session_id: return generations.find(a.domain_session_id) < generations.find(z.domain_session_id)
		return compare(decimal(a.output_id), decimal(z.output_id)) < 0)
	_advance(b)
	if b.observed.size() > MAX_SPARSE:
		var keys: Array = b.observed.keys()
		keys.sort_custom(func(a, z): return compare(a, z) < 0)
		var discarded: String = keys.back()
		b.observed.erase(discarded)
		_receipt_problem(b, "receipt_capacity", "Receipt history needs replay", discarded)
	if p.domain_session_id == d.domain_session_id:
		if d.pending_query.get("request_id") == p.request_id:
			d.pending_query = {}
			_commands.erase(p.request_id)
			d.execution_state = "idle"
			d.query_uncertain = false
			d.draft = "" if d.draft == p.task else d.draft
		d.version += 1
		_merge_memory(d.memory, p.memory)
	if b.unresolved_query.get("request_id") == p.request_id:
		b.unresolved_query = {}
	_refresh_uncertainty(d)
	_merge_workspace_memory(p.memory)
	_trim(d)
	return _change("domain", d.domain_id, "domain_result", p.request_id)


func _apply_completion(d: Dictionary, p: Dictionary, c: Dictionary) -> Dictionary:
	if c.type != "resume" or not d.buckets.has(p.get("domain_session_id")) or not p.get("history_gap") is bool or not _valid_state(p): return {}
	var h := decimal(p.get("high_water_mark"))
	var e := decimal(p.get("earliest_output_id")) if p.get("earliest_output_id") != null else ""
	var requested := decimal(c.cursor)
	if h == "" or compare(h, requested) < 0: return {}
	if p.get("earliest_output_id") != null and (e in ["", "0"] or compare(e, h) > 0): return {}
	var start := successor(h) if e == "" else e
	var gap_expected := compare(requested, predecessor(start)) < 0
	if p.history_gap != gap_expected: return {}
	var b: Dictionary = d.buckets[p.domain_session_id]
	if p.history_gap and compare(predecessor(start), b.received) > 0:
		var end := predecessor(start)
		var known := 0
		for n in b.observed.keys():
			if compare(n, end) <= 0:
				known += 1
				b.observed.erase(n)
		var missing := distance_capped(end, b.received, known)
		b.received = end
		d.omitted_count = mini(2147483647, d.omitted_count + missing)
	_advance(b)
	if compare(b.received, h) < 0:
		_receipt_problem(b, "replay_incomplete", "Retained output is missing; replay again", h)
	_refresh_uncertainty(d)
	# Completion fields were captured before sends; never overwrite live lifecycle.
	_settle(d, p.request_id)
	return _change("domain", d.domain_id, "resume_complete", p.request_id)


func _advance(b: Dictionary) -> void:
	while b.observed.has(successor(b.received)):
		b.received = successor(b.received)
		b.observed.erase(b.received)


func _receipt_problem(b: Dictionary, kind: String, message: String, fence: String) -> void:
	b.receipt_error = {"error_type": kind, "message": message}
	if compare(fence, b.receipt_fence) > 0:
		b.receipt_fence = fence


func _refresh_uncertainty(d: Dictionary) -> void:
	for bucket in d.buckets.values():
		if compare(bucket.received, bucket.receipt_fence) >= 0:
			bucket.receipt_error = {}
	var current: Dictionary = d.buckets.get(d.domain_session_id, {})
	d.uncertain = d.lifecycle_uncertain or d.query_uncertain or not current.get("receipt_error", {}).is_empty()


func _unresolved_queries(d: Dictionary) -> Array:
	var unresolved := []
	for bucket in d.buckets.values():
		if not bucket.unresolved_query.is_empty():
			unresolved.append(bucket.unresolved_query.duplicate(true))
	return unresolved


func _settle(d: Dictionary, id: String) -> void:
	_commands.erase(id)
	if d.pending_control.get("request_id") == id: d.pending_control = {}


func _valid_state(p: Dictionary) -> bool:
	if p.get("state") not in STATES or p.get("execution_state") not in EXECUTION: return false
	if p.get("domain_session_id") == null and p.state != "inactive": return false
	if p.has("available_generations"):
		if not p.available_generations is Array or p.available_generations.size() > 2: return false
		for generation in p.available_generations:
			if not valid_id(generation): return false
	return true


func _valid_error(p: Dictionary) -> bool:
	return p.get("status") == "error" and valid_id(p.get("error_type")) and p.get("message") is String and p.message.to_utf8_buffer().size() <= 65536


func _valid_memory(value: Variant, terminal: bool = false) -> bool:
	if not value is Dictionary or not value.has("revision") or not value.has("error_type"): return false
	if value.error_type != null and not valid_id(value.error_type): return false
	if not terminal and (not value.has("path") or (value.path != null and not value.path is String)): return false
	var revision: Variant = value.get("revision")
	if revision != null and (not (revision is int or revision is float) or not is_finite(float(revision)) or revision < 0 or floor(float(revision)) != float(revision)): return false
	return value.get("saved") is bool if terminal else value.get("status") in ["unavailable", "saved", "unsaved"]


func _merge_memory(target: Dictionary, incoming: Dictionary) -> void:
	if float(incoming.get("revision", 0) if incoming.get("revision") != null else 0) < float(target.get("revision", 0) if target.get("revision") != null else 0): return
	for key in ["saved", "revision", "error_type", "path", "status"]:
		if incoming.has(key): target[key] = incoming[key]


func _merge_workspace_memory(incoming: Dictionary) -> void:
	if _workspace.is_empty(): return
	# A replayed turn at the same revision cannot erase a later failed save.
	if float(incoming.get("revision", 0) if incoming.get("revision") != null else 0) <= float(_workspace.memory.get("revision", 0) if _workspace.memory.get("revision") != null else 0): return
	var memory: Dictionary = incoming.duplicate(true)
	memory.status = "saved" if memory.saved else "unsaved"
	memory.erase("saved")
	_merge_memory(_workspace.memory, memory)


func _apply_workspace(p: Dictionary, c: Dictionary) -> Dictionary:
	if c.get("type") != "describe_workspace": return {}
	for key in ["project_id", "workspace_id", "reason", "architect_decision", "project_path", "worktree_path", "branch", "changed_files", "reservation", "memory"]:
		if not p.has(key): return {}
	for key in ["reason", "project_path", "worktree_path", "branch"]:
		if p[key] != null and not p[key] is String: return {}
	if p.architect_decision != null and not p.architect_decision is Dictionary: return {}
	if p.changed_files != null:
		if not p.changed_files is Dictionary or not p.changed_files.get("truncated") is bool: return {}
		for key in ["total", "tracked", "untracked"]:
			var count: Variant = p.changed_files.get(key)
			if not (count is int or count is float) or not is_finite(float(count)) or count < 0 or floor(float(count)) != float(count): return {}
	if p.reservation != null:
		if not p.reservation is Dictionary or not valid_domain(p.reservation.get("domain_id")) or not valid_id(p.reservation.get("domain_session_id")) or not p.reservation.get("cleanup_failed") is bool: return {}
	if p.get("stage") not in ["unconfigured", "needs_architect", "preparing", "reviewing", "initializing", "ready", "failed"]: return {}
	for key in ["project_id", "workspace_id"]:
		if p.get(key) != null and not valid_id(p[key]): return {}
	if not _valid_memory(p.get("memory")) or JSON.stringify(p).to_utf8_buffer().size() > MAX_BYTES: return {}
	var project: String = p.project_id if p.get("project_id") != null else ""
	# Only an authoritative unconfigured snapshot can clear a known binding.
	# Preparing/reviewing/initializing may temporarily lack an identity.
	var authoritative_unconfigured: bool = p.stage == "unconfigured" and project == ""
	var changed := _project_id != "" and project != _project_id and (project != "" or authoritative_unconfigured)
	if changed:
		bind_project(project)
	elif project != "" and project != _project_id:
		_project_id = project
		for d in _domains.values():
			d.project_id = project
	var memory: Dictionary = _workspace.get("memory", {}).duplicate(true)
	_merge_memory(memory, p.memory)
	_workspace = p.duplicate(true)
	_workspace.memory = memory if not changed else p.memory.duplicate(true)
	_commands.erase(p.request_id)
	return _change("workspace", "", "workspace_state", p.request_id, true, changed)


func _trim(d: Dictionary) -> void:
	# Count the complete exposed wire shapes, pending input and draft together.
	# Receipt metadata is independently bounded (two buckets, 256 sparse IDs each).
	var bytes: int = JSON.stringify(snapshot(d.domain_id)).to_utf8_buffer().size()
	var extra := (0 if d.draft == "" else 1) + (0 if d.pending_query.is_empty() else 1) + _unresolved_queries(d).size()
	while not d.results.is_empty() and (d.results.size() + extra > MAX_ENTRIES or bytes > MAX_BYTES):
		d.results.pop_front()
		d.omitted_count = mini(2147483647, d.omitted_count + 1)
		bytes = JSON.stringify(snapshot(d.domain_id)).to_utf8_buffer().size()


func _change(scope: String, domain: String, reason: String, id: String, settled: bool = true, changed: bool = false) -> Dictionary:
	return {"scope": scope, "domain_id": domain, "reason": reason, "request_id": id, "settled": settled, "project_changed": changed}


## Discovery captures all existing versions because the binding is not known yet.
func observation_fence() -> Dictionary:
	var versions := {}
	for id in _domains: versions[id] = _domains[id].version
	return {"epoch": _epoch, "project_id": _project_id, "versions": versions}

func observation_current(fence: Dictionary) -> bool:
	return fence.get("epoch") == _epoch and fence.get("project_id") == _project_id

func observe_project(project: Dictionary) -> Dictionary:
	var packet := project.duplicate(true)
	packet.request_id = ""
	return _apply_workspace(packet, {"type": "describe_workspace"})

func observe_domain(packet: Dictionary, fence: Dictionary) -> bool:
	if fence.get("epoch") != _epoch or not valid_domain(packet.get("domain_id")) or not _valid_state(packet): return false
	if packet.get("project_id", "") != _project_id and not (_project_id == "" and packet.get("project_id") == null): return false
	var d := _domain(packet.domain_id)
	if d.is_empty() or d.version != fence.get("versions", {}).get(packet.domain_id, 0): return false
	if not d.pending_control.is_empty() or not d.pending_query.is_empty(): return false
	var generation: Variant = packet.get("domain_session_id")
	if generation != null and not valid_id(generation): return false
	if packet.get("workspace_id") != null and not valid_id(packet.workspace_id): return false
	if d.buckets.has(generation) and d.buckets[generation].get("workspace_id") != packet.get("workspace_id"): return false
	if generation == null: generation = ""
	if generation != d.domain_session_id: _switch_generation(d, generation)
	d.workspace_id = packet.get("workspace_id")
	if d.buckets.has(generation): d.buckets[generation].workspace_id = packet.get("workspace_id")
	d.state = packet.state
	d.execution_state = packet.execution_state
	d.lifecycle_uncertain = false
	d.cleanup_confirmed = packet.state == "inactive" and packet.execution_state == "idle"
	d.version += 1
	_refresh_uncertainty(d)
	return true

func save_view(domain_id: String, scroll: float, follow: bool, anchor: Dictionary) -> void:
	var d := _domain(domain_id)
	if not d.is_empty(): d.view = {"scroll": scroll, "follow": follow, "anchor": anchor.duplicate(true)}
