"""Shared strict evidence contract for the disposable probe and product activation."""

import hashlib
import math
from pathlib import Path

SDK_VERSION = "0.2.136"
CLI_VERSION = "2.1.228"
ANYIO_VERSION = "4.14.2"
DOMAIN_TOOLS = ("Read", "Edit", "Bash")
PERMISSION_MODES = ("dontAsk", "bypassPermissions")
ACCEPTANCE_VERSION = 1
GUARD_SOURCES = (
    "bridge/config.py",
    "bridge/readiness.py",
    "bridge/guarded_transport.py",
    "bridge/domain_sdk.py",
    "bridge/tool_guard_evidence.py",
    "scripts/m12_tool_guard_probe.py",
)
REQUIRED_GUARD_CASES = tuple(
    f"{path}_{mode}"
    for path in ("read", "edit", "bash", "mcp", "delegated")
    for mode in ("ready", "deny", "exception", "timeout")
) + (
    "bash_raw_error",
    "bash_malformed",
    "bash_missing_callback",
    "bash_hung_callback",
    "bash_disconnect",
    "stop_connect",
    "stop_idle",
    "stop_query",
    "repeated_cancel",
)


VERSIONS = {"sdk": "0.2.136", "cli": "2.1.228 (Claude Code)", "anyio": "4.14.2"}
PATHS = ("read", "edit", "bash", "mcp", "delegated")
MODES = ("ready", "deny", "exception", "timeout")
REQUIRED_CASES = REQUIRED_GUARD_CASES

MODEL = "claude-haiku-5-5"
CASE_SECONDS = 45
BUDGET_USD = 0.20


def case_errors(record):
    """Validate observations, never infer non-execution from missing fields."""
    if not isinstance(record, dict) or record.get("name") not in REQUIRED_CASES:
        return ["Unknown or malformed case"]
    name = record["name"]
    booleans = (
        "attempted",
        "hook_seen",
        "reaped",
        "cleanup_clean",
        "sentinel_executed",
        "successful_tool_result",
        "post_seen",
        "terminal_seen",
        "child_attributed",
    )
    counts = (
        "owner_task_count",
        "mcp_invocations",
        "normalized_denials",
        "timeout_denials",
        "hook_tasks_remaining",
    )
    if (
        any(type(record.get(key)) is not bool for key in booleans)
        or any(type(record.get(key)) is not int or record[key] < 0 for key in counts)
        or type(record.get("returncode")) is not int
        or type(record.get("seconds")) not in (int, float)
        or not math.isfinite(record["seconds"])
        or record["seconds"] < 0
        or record.get("decision") not in (None, "unchanged", "deny")
        or any(
            not isinstance(record.get(key), list)
            for key in (
                "inventory",
                "assistant_errors",
                "attempts",
                "lifecycle",
                "successful_tool_ids",
                "post_tool_ids",
            )
        )
        or any(
            not isinstance(value, str)
            for key in (
                "inventory",
                "assistant_errors",
                "lifecycle",
                "successful_tool_ids",
                "post_tool_ids",
            )
            for value in record[key]
        )
    ):
        return ["Missing or invalid observation types"]
    for attempt in record["attempts"]:
        if (
            not isinstance(attempt, dict)
            or not isinstance(attempt.get("name"), str)
            or not isinstance(attempt.get("id"), str)
            or not attempt["id"]
            or "parent" not in attempt
            or (
                attempt["parent"] is not None and not isinstance(attempt["parent"], str)
            )
        ):
            return ["Malformed tool-attempt correlation"]
    errors = []
    lifecycle = name in {"stop_connect", "stop_idle", "stop_query", "repeated_cancel"}
    ready = name.endswith("_ready")
    active = name not in {"stop_connect", "stop_idle"}
    target = {"read": "Read", "edit": "Edit", "mcp": "mcp__m12_fixture__sentinel"}.get(
        name.split("_")[0], "Bash"
    )
    target_ids = {
        attempt["id"] for attempt in record["attempts"] if attempt["name"] == target
    }
    for summary, ids in (
        ("successful_tool_result", "successful_tool_ids"),
        ("post_seen", "post_tool_ids"),
    ):
        if record[summary] != bool(record[ids]) or not set(record[ids]) <= target_ids:
            errors.append("Contradictory or uncorrelated tool execution observations")
    if record.get("forced_cleanup"):
        errors.append("Probe rescue is not clean owner teardown")
    if not record["reaped"] or not record["cleanup_clean"]:
        errors.append("CLI cleanup/reaping not confirmed")
    if record["hook_tasks_remaining"]:
        errors.append("Mandatory hook tasks remain after cleanup")
    if name in {"stop_query", "repeated_cancel"} and any(
        record.get(field) is not True
        for field in (
            "hook_worker_entered",
            "hook_worker_finished",
            "stop_waited_for_hook_worker",
        )
    ):
        errors.append("Missing synchronous hook IO shutdown/drain evidence")
    if record.get("error") or record["assistant_errors"]:
        errors.append("Unexpected runtime/provider error")
    expected_lifecycle = (
        ["connect", "query", "receive", "disconnect"]
        if active
        else ["connect", "disconnect"]
    )
    if record["owner_task_count"] != 1 or record["lifecycle"] != expected_lifecycle:
        errors.append("SDK lifecycle ownership or method evidence is incomplete")
    if active and (
        not record["attempted"]
        or not record["hook_seen"]
        or target not in record["inventory"]
        or not any(attempt["name"] == target for attempt in record["attempts"])
    ):
        errors.append("Missing target tool attempt/hook/inventory")
    if not active and (
        record["attempted"] or record["hook_seen"] or record["attempts"]
    ):
        errors.append("Connect/idle unexpectedly attempted tools")
    if ready:
        if (
            record["decision"] != "unchanged"
            or record["normalized_denials"]
            or record["timeout_denials"]
        ):
            errors.append("Ready guard changed ordinary permissions")
        if not all(
            record[key]
            for key in ("sentinel_executed", "successful_tool_result", "post_seen")
        ):
            errors.append("Positive control did not execute sentinel")
    elif any(
        record[key]
        for key in ("sentinel_executed", "successful_tool_result", "post_seen")
    ):
        errors.append("Tool executed despite denial or pending-hook Stop")
    if name.startswith("mcp_"):
        if (ready and record["mcp_invocations"] < 1) or (
            not ready and record["mcp_invocations"] != 0
        ):
            errors.append("Independent MCP handler counter contradicts guard")
    elif record["mcp_invocations"] != 0:
        errors.append("Unexpected MCP execution")
    if (
        not lifecycle
        and not ready
        and name != "bash_disconnect"
        and record["decision"] != "deny"
    ):
        errors.append("Missing explicit denial")
    if name.startswith("delegated_") and (
        not record["child_attributed"]
        or not any(
            attempt["name"] == "Bash" and attempt["parent"]
            for attempt in record["attempts"]
        )
    ):
        errors.append("Missing delegated child attribution/correlation")
    path = name.split("_")[0]
    expected_inventory = (
        {"edit": {"Read", "Edit"}, "delegated": {"Task", "Bash"}}.get(path, {target})
        if active
        else set()
    )
    if set(record["inventory"]) != expected_inventory or len(
        record["inventory"]
    ) != len(expected_inventory):
        errors.append("Unverified or incomplete exposed tool inventory")
    if name.startswith("delegated_"):
        parents = {
            attempt["id"]
            for attempt in record["attempts"]
            if attempt["name"] == "Agent"
        }
        if not parents or not all(
            attempt["parent"] in parents
            for attempt in record["attempts"]
            if attempt["name"] == "Bash" and attempt["parent"] is not None
        ):
            errors.append("Delegated child has no observed parent Agent")
        # The model can attempt the exposed parent Bash after its child fails.
        # That is separate coverage: require this exact ID's observed denial.
        fallback_ids = [
            attempt["id"]
            for attempt in record["attempts"]
            if attempt["name"] == "Bash" and attempt["parent"] is None
        ]
        decisions = record.get("hook_decisions")
        if fallback_ids and (
            not isinstance(decisions, dict)
            or any(decisions.get(tool_id) != "deny" for tool_id in fallback_ids)
            or any(
                tool_id in record["successful_tool_ids"]
                or tool_id in record["post_tool_ids"]
                for tool_id in fallback_ids
            )
        ):
            errors.append("Parent fallback lacks its own observed hook denial")
        child_ids = {
            attempt["id"]
            for attempt in record["attempts"]
            if attempt["name"] == "Bash" and attempt["parent"] in parents
        }
        if ready and not any(
            tool_id in record["successful_tool_ids"]
            and tool_id in record["post_tool_ids"]
            for tool_id in child_ids
        ):
            errors.append("Missing successful child result/PostToolUse correlation")
    elif record["child_attributed"]:
        errors.append("Unexpected delegated tool path")
    if name.endswith(("_deny", "_exception", "_timeout")) and (
        record["normalized_denials"] or record["timeout_denials"]
    ):
        errors.append("Checker denial was replaced by an adapter failure")
    terminal = record.get("terminal")
    if record["terminal_seen"]:
        if (
            not isinstance(terminal, dict)
            or not isinstance(terminal.get("subtype"), str)
            or type(terminal.get("is_error")) is not bool
            or terminal.get("reason") not in (None, "completed")
            or type(terminal.get("permission_denials")) is not int
            or terminal["permission_denials"] < 0
            or type(terminal.get("cost_usd")) not in (int, float)
            or not math.isfinite(terminal["cost_usd"])
            or terminal["cost_usd"] < 0
        ):
            errors.append("Malformed terminal observation")
        else:
            if terminal["subtype"] != "success" or terminal["is_error"]:
                errors.append("Unexpected provider terminal error")
            if (
                not ready
                and not lifecycle
                and name != "bash_disconnect"
                and terminal["permission_denials"] < 1
            ):
                errors.append("CLI terminal did not record denial")
    elif terminal is not None or (
        not lifecycle and name not in {"bash_disconnect", "bash_hung_callback"}
    ):
        errors.append("Missing or contradictory terminal result")
    if (
        name in {"bash_raw_error", "bash_malformed", "bash_missing_callback"}
        and record["normalized_denials"] < 1
    ):
        errors.append("Missing adapter normalization")
    if name == "bash_hung_callback" and record["timeout_denials"] < 1:
        errors.append("Missing watchdog denial")
    if name == "bash_disconnect" and record.get("channel_dropped") is not True:
        errors.append("Missing pending-control disconnect")
    return errors


def validate_evidence(evidence, source_root=None, *, permission_mode=None):
    if not isinstance(evidence, dict):
        return ["Malformed evidence"]
    errors = []
    mode = evidence.get("permission_mode")
    if mode not in PERMISSION_MODES or (
        permission_mode is not None and mode != permission_mode
    ):
        errors.append("Missing or mismatched permission mode")
    if evidence.get("versions") != VERSIONS:
        errors.append("Pinned runtime versions not verified")
    if (
        evidence.get("production_tools") != list(DOMAIN_TOOLS)
        or evidence.get("model") != MODEL
    ):
        errors.append("Wrong production inventory or probe model")
    expected_limits = {
        "case_deadline_seconds": CASE_SECONDS,
        "case_budget_usd": BUDGET_USD,
        "max_queries": len(REQUIRED_CASES) - 2,
        "watchdog_seconds": 7,
        "checker_seconds": 5,
        "matcher_seconds": 10,
    }
    if any(
        type(evidence.get(key)) not in (int, float) or evidence[key] != value
        for key, value in expected_limits.items()
    ):
        errors.append("Missing or invalid probe limits")

    def digest(value):
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(c in "0123456789abcdef" for c in value)
        )

    if not digest(evidence.get("cli_sha256")):
        errors.append("Missing CLI binary fingerprint")
    sources = evidence.get("source_sha256")
    if not isinstance(sources, dict) or set(sources) != set(GUARD_SOURCES):
        errors.append("Missing enforcement source fingerprints")
    else:
        root = (
            source_root
            if source_root is not None
            else Path(__file__).resolve().parents[1]
        )
        for name in GUARD_SOURCES:
            try:
                matches = (
                    digest(sources[name])
                    and hashlib.sha256((root / name).read_bytes()).hexdigest()
                    == sources[name]
                )
            except OSError:
                matches = False
            if not matches:
                errors.append("Source fingerprint mismatch: " + name)
    records = evidence.get("cases")
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        return errors + ["Malformed case list"]
    names = [record.get("name") for record in records]
    if (
        any(not isinstance(name, str) for name in names)
        or len(names) != len(REQUIRED_CASES)
        or set(names) != set(REQUIRED_CASES)
    ):
        errors.append("Required matrix is incomplete or duplicated")
    for record in records:
        observed = case_errors(record)
        errors.extend(f"{record.get('name')}: {error}" for error in observed)
        if record.get("errors") != observed:
            errors.append(f"{record.get('name')}: inconsistent stored case validation")
    return errors


def acceptance_envelope(records, source_root=None):
    """Publish only two independently accepted, current-source probe records.

    Never refresh fingerprints here: a source change requires new live probes.
    """
    from copy import deepcopy

    if not isinstance(records, list) or len(records) != len(PERMISSION_MODES):
        raise ValueError("Both permission mode records are required")
    indexed = {}
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get("permission_mode") not in PERMISSION_MODES
            or record["permission_mode"] in indexed
            or record.get("accepted") is not True
            or record.get("errors") != []
            or validate_evidence(record, source_root)
        ):
            raise ValueError("Invalid, duplicate or stale permission mode record")
        indexed[record["permission_mode"]] = deepcopy(record)
    return {"schema_version": ACCEPTANCE_VERSION, "records": indexed}
