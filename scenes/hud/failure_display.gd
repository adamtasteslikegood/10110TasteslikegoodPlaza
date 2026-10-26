extends RefCounted

## Readable fixed causes. Provider reason strings and structured internals are
## never used as ordinary UI text; the partial assistant answer stays separate.
static func department_status(character: Dictionary) -> String:
	var stage: Variant = character.get("workspace", {}).get("stage")
	return stage if stage in ["unprepared", "migration_pending", "preparing", "initializing", "ready", "failed"] else "unknown"

## Observation-only guidance. Project setup and department readiness are
## separate; reason codes select fixed prose, never arbitrary service messages.
static func readiness(project: Dictionary, character: Dictionary) -> String:
	var stage: Variant = project.get("stage")
	if stage == "unconfigured": return "Project is not configured. Configure a project path, then ask the Chief Architect to review setup; Refresh status."
	if stage == "needs_architect": return "Project needs Chief Architect review. Ask the Chief Architect to review the configured project, then Refresh status."
	if stage == "reviewing": return "Project review is in progress. Wait for the Chief Architect decision, then Refresh status."
	var department: Dictionary = character.get("workspace", {})
	if stage in ["initializing", "preparing"] or department.get("stage") in ["initializing", "preparing"]:
		return "Project/workspace preparation is in progress. Wait for it to finish, then Refresh status."
	var capabilities: Dictionary = character.get("capabilities", {})
	var reason: Variant = project.get("reason") if stage == "failed" else department.get("reason")
	if not reason is String or reason.is_empty(): reason = capabilities.get("reason")
	var reservation: Variant = department.get("reservation")
	if not reason is String or reason.is_empty():
		if reservation is Dictionary and reservation.get("cleanup_failed", false): reason = "cleanup_failed"
		elif reservation is Dictionary and not capabilities.get("can_start", false) and not capabilities.get("can_run", false): reason = "workspace_busy"
		elif stage == "failed" or department.get("stage") == "failed": reason = "workspace_not_ready"
		else: return ""
	return {
		"workspace_invalid": "Department workspace needs inspection. Ask the Chief Architect to review the workspace and ownership; Refresh status after recovery.",
		"cleanup_failed": "Prior workspace cleanup is unconfirmed. Preserve ownership evidence and have the operator inspect cleanup before reuse; Refresh status after verified recovery.",
		"workspace_busy": "Department workspace is reserved. Use normal Stop with the current owner when appropriate and wait for confirmed cleanup; Refresh status.",
		"capacity_limit": "Execution capacity is in use. Finish or Stop another department session when appropriate, then Refresh status before explicit Start.",
		"workspace_not_ready": "Department is not ready. Review setup with the Chief Architect, then Refresh status.",
		"workspace_unconfigured": "Project is not configured. Configure a project path, then ask the Chief Architect to review setup; Refresh status.",
		"domain_busy": "Department work is in progress. Wait for it to finish, or request Stop when appropriate; Refresh status before another task.",
		"sdk_error": "The execution owner needs inspection. Request normal Stop and verify cleanup before reuse; Refresh status after recovery.",
	}.get(reason, "Department readiness could not be confirmed. Ask the Chief Architect to review setup; Refresh status after inspection.")

static func cause(result: Dictionary) -> String:
	if result.get("committed") is bool and not result.committed: return "UNSAVED answer: application persistence failed. This text has no saved output ID and may be lost when the game closes. Inspect storage; no task will be retried automatically."
	if result.get("recovered") is bool and result.recovered:
		return "Not executed: the bridge restarted before dispatch." if result.get("reason") == "not_executed" else "Interrupted: execution outcome is unknown; external changes may have occurred. Review the workspace before another explicit Run."
	if result.get("status") == "success": return ""
	if result.get("status") == "cancelled": return "Stopped. The partial answer may be incomplete."
	if result.get("readiness_category") == "cwd_mismatch":
		return "Readiness failed: tools require the owned worktree root cwd. Use a scoped command or subshell for subdirectories. Stop and review setup before restarting."
	if result.get("readiness_category") == "branch_changed":
		return "Readiness failed: the active owned branch changed. Stop and review ownership with the Chief Architect before restarting; no automatic reset or checkout repair."
	return {
		"readiness_failed": "Readiness checks failed. Stop and review project, memory, and workspace ownership with the Chief Architect before restarting.",
		"permission_denied": "A required tool was denied permission. Review the task and configured permissions before trying again.",
		"max_turns": "The task reached its turn limit. Review the partial answer and use a smaller follow-up task.",
		"max_budget_usd": "The task reached its budget limit. Review the partial answer and configured budget before running again.",
		"max_tokens": "The response reached its token limit. Review the partial answer and use a smaller follow-up task.",
		"output_limit": "The response reached its output limit. Stop before starting a fresh session.",
		"transport_error": "The execution connection failed. Stop before starting a fresh session.",
		"missing_terminal": "Execution ended without a confirmed result. Stop before starting a fresh session.",
		"deferred_tool_use": "A required tool could not complete in this run. Review the partial answer and task.",
	}.get(result.get("reason", ""), "The task could not complete. Review the partial answer; Stop before starting a fresh session.")

static func notice(error: Dictionary, include_related: bool = true) -> String:
	var text: String = error.get("message", "The command could not complete.")
	if error.has("readiness_category"):
		text += "\n" + cause({"status": "error", "reason": "readiness_failed", "readiness_category": error.readiness_category})
	if not include_related: return text
	var command_error: Dictionary = error.get("command_error", {})
	if not command_error.is_empty(): text += "\n" + notice(command_error)
	for query in error.get("unresolved_queries", []):
		text += "\nUnknown outcome for request %s:\n%s" % [query.get("request_id", ""), query.get("task", "")]
	return text


static func persistence(snapshot: Dictionary) -> String:
	var notices: Array[String] = []
	var storage: Dictionary = snapshot.get("state_store", {})
	if storage.get("backend") == "memory": notices.append("Memory backend · history lasts only for this bridge process. SQLite history is separate; changing backend does not carry it across.")
	if storage.get("error_type") != null: notices.append("Application persistence fault: %s. Start/Run are blocked. Have the operator inspect and reconcile storage, then Refresh status." % storage.error_type)
	var selected: String = snapshot.get("selected_session_id", "")
	if snapshot.get("read_only", false): notices.append("Ended/saved history · read-only. Run and End require selecting the current application. Stop current work always targets the current execution.")
	elif snapshot.get("state") == "inactive" and not selected.is_empty(): notices.append("Stopped/restored application history · use explicit Start before Run. End session closes this application separately.")
	for fact in snapshot.get("memory_reconciliation", []):
		if fact.get("error_type") != null: notices.append("Project notes recovery: %s. Saved application history and notes may differ; operator inspection is required." % fact.error_type)
		elif fact.get("note_state") != null: notices.append("Recovered project notes: %s · application recovery reports the execution outcome separately." % fact.note_state)
	return "\n".join(notices)
