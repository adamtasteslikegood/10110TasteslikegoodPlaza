"""Fixed diagnostic vocabulary; never archive arbitrary provider or tool text."""

import hashlib
import re

FAILURE_REASONS = frozenset(
    {
        "sdk_error",
        "assistant_error",
        "permission_denied",
        "readiness_failed",
        "max_turns",
        "max_budget_usd",
        "max_tokens",
        "output_limit",
        "missing_terminal",
        "transport_error",
        "deferred_tool_use",
    }
)
TERMINAL_REASONS = FAILURE_REASONS | {"completed", "stopped", "not_executed"}
READINESS_CATEGORIES = frozenset(
    {
        "cwd_mismatch",
        "branch_changed",
        "workspace_invalid",
        "lease_invalid",
        "memory_unavailable",
        "tool_correlation_invalid",
        "readiness_timeout",
        "readiness_error",
        "readiness_cancelled",
        "workspace_not_ready",
        "workspace_busy",
        "cleanup_failed",
        "context_unavailable",
    }
)
SAFE_CODES = READINESS_CATEGORIES | {
    "sdk_error",
    "session_unavailable",
    "capacity_limit",
}


def failure_reason(value, fallback="sdk_error"):
    aliases = {"error_max_turns": "max_turns", "error_max_budget_usd": "max_budget_usd"}
    if not isinstance(value, str):
        return fallback
    value = aliases.get(value, value)
    return value if value in FAILURE_REASONS else fallback


def readiness_category(error):
    category = getattr(error, "readiness_category", None)
    if isinstance(category, str) and category in READINESS_CATEGORIES:
        return category
    code = getattr(error, "code", None)
    if isinstance(code, str) and code in READINESS_CATEGORIES:
        return code
    if isinstance(error, TimeoutError):
        return "readiness_timeout"
    return "readiness_error"


def tool_correlation(data, tool_use_id):
    """Opaque digest only; hook IDs are untrusted, tool payloads never enter here."""
    result = {}
    if isinstance(data, dict) and data.get("tool_name") in ("Read", "Edit", "Bash"):
        result["tool_name"] = data["tool_name"]
    if isinstance(tool_use_id, str):
        encoded = tool_use_id.encode("utf-8", errors="replace")
        if 0 < len(encoded) <= 256:
            result["tool_use_id"] = hashlib.sha256(encoded).hexdigest()
    return result


def diagnostic_fields(
    *, terminal_reason=None, readiness_category=None, tool_name=None, tool_use_id=None
):
    result = {}
    if terminal_reason is not None:
        result["terminal_reason"] = (
            terminal_reason
            if isinstance(terminal_reason, str) and terminal_reason in TERMINAL_REASONS
            else "sdk_error"
        )
    if (
        isinstance(readiness_category, str)
        and readiness_category in READINESS_CATEGORIES
    ):
        result["readiness_category"] = readiness_category
    if tool_name in ("Read", "Edit", "Bash"):
        result["tool_name"] = tool_name
    if isinstance(tool_use_id, str) and re.fullmatch(r"[0-9a-f]{64}", tool_use_id):
        result["tool_use_id"] = tool_use_id
    return result


def exception_diagnostics(error, fallback="sdk_error"):
    category = readiness_category(error)
    # Exception class alone does not establish the failure stage: a transport
    # TimeoutError is not evidence that a readiness check timed out.
    explicit = getattr(error, "readiness_category", None)
    code = getattr(error, "code", None)
    known_readiness = (
        isinstance(explicit, str) and explicit in READINESS_CATEGORIES
    ) or (isinstance(code, str) and code in READINESS_CATEGORIES)
    return diagnostic_fields(
        terminal_reason=(
            "readiness_failed"
            if known_readiness
            else failure_reason(getattr(error, "terminal_reason", None), fallback)
        ),
        readiness_category=category if known_readiness else None,
    )


class RuntimeFailure(RuntimeError):
    """Safe startup failure retaining only an existing public code/category."""

    def __init__(self, error, *, readiness=False):
        details = (
            dict(
                terminal_reason="readiness_failed",
                readiness_category=readiness_category(error),
            )
            if readiness
            else exception_diagnostics(error, "transport_error")
        )
        self.terminal_reason = details["terminal_reason"]
        self.readiness_category = details.get("readiness_category")
        code = getattr(error, "code", None)
        self.code = (
            code if isinstance(code, str) and code in SAFE_CODES else "sdk_error"
        )
        super().__init__(self.terminal_reason)
