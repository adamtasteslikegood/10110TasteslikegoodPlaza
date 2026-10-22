"""Strict domain commands, separate from the compatible NPC wire parser."""

import re

from bridge.protocol import validate_agent_id

COMMANDS = frozenset(
    {
        "describe_workspace",
        "domain_status",
        "activate_domain",
        "domain_query",
        "background_domain",
        "refocus_domain",
        "deactivate_domain",
        "resume",
    }
)
GENERATION_COMMANDS = COMMANDS - {
    "describe_workspace",
    "domain_status",
    "activate_domain",
}
ERROR_MESSAGES = {
    "invalid_binding": "The selected agent does not belong to this domain.",
    "workspace_unconfigured": "Configure a project before starting domain work.",
    "workspace_invalid": "The configured workspace needs inspection.",
    "capacity_limit": "Execution capacity is reserved by another session.",
    "workspace_busy": "The workspace is reserved by another domain.",
    "domain_busy": "The domain is busy; wait for its current operation.",
    "workspace_not_ready": "Talk to the Chief Architect to prepare this project.",
    "context_unavailable": "Current game or project guidance is unavailable.",
    "memory_unavailable": "Project memory is unavailable or was not saved.",
    "session_unavailable": "The requested domain generation is unavailable.",
    "invalid_request": "The domain command or its identifiers are invalid.",
    "sdk_error": "The SDK session is unavailable; Stop before starting again.",
    "cleanup_failed": "Cleanup could not be confirmed; workspace ownership remains.",
}


class DomainCommandError(ValueError):
    def __init__(self, code="invalid_request"):
        self.code = code if code in ERROR_MESSAGES else "sdk_error"
        super().__init__(ERROR_MESSAGES[self.code])


def valid_text(value, limit=128):
    try:
        return (
            isinstance(value, str)
            and bool(value.strip())
            and len(value.encode("utf-8")) <= limit
        )
    except UnicodeError:
        return False


def valid_domain(value):
    return valid_text(value) and re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None


def validate_domain_command(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise DomainCommandError()
    kind = payload.get("type")
    if not isinstance(kind, str) or kind not in COMMANDS:
        raise DomainCommandError()
    fields = {"type", "request_id"}
    if kind != "describe_workspace":
        fields.add("domain_id")
    if kind in GENERATION_COMMANDS:
        fields.add("domain_session_id")
    if kind == "domain_query":
        fields.update(("agent_id", "task"))
    if kind == "resume":
        fields.add("cursor")
    if set(payload) != fields or not valid_text(payload.get("request_id")):
        raise DomainCommandError()
    if "domain_id" in fields and not valid_domain(payload["domain_id"]):
        raise DomainCommandError()
    if "domain_session_id" in fields and not valid_text(payload["domain_session_id"]):
        raise DomainCommandError()
    if kind == "domain_query" and (
        not valid_text(payload["agent_id"])
        or not validate_agent_id(payload["agent_id"])
        or not valid_text(payload["task"], 64 * 1024)
    ):
        raise DomainCommandError()
    result = dict(payload)
    if kind == "resume":
        cursor = payload["cursor"]
        if not valid_text(cursor) or re.fullmatch(r"[0-9]+", cursor) is None:
            raise DomainCommandError()
        try:
            result["cursor"] = int(cursor)
        except ValueError:
            raise DomainCommandError() from None
    return result


def error_packet(command, code, *, project_id=None, workspace_id=None):
    code = code if code in ERROR_MESSAGES else "sdk_error"
    packet = dict(
        type="domain_error",
        status="error",
        error_type=code,
        message=ERROR_MESSAGES[code],
        project_id=project_id,
    )
    if workspace_id is not None:
        packet["workspace_id"] = workspace_id
    if isinstance(command, dict):
        for key in ("request_id", "domain_session_id"):
            if valid_text(command.get(key)):
                packet[key] = command[key]
        if valid_domain(command.get("domain_id")):
            packet["domain_id"] = command["domain_id"]
    return packet
