extends RefCounted

## Readable fixed causes. Provider reason strings and structured internals are
## never used as ordinary UI text; the partial assistant answer stays separate.
static func cause(result: Dictionary) -> String:
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
