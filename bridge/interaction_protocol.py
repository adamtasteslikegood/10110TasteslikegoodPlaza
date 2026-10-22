"""Strict, correlated character services, independent of conversation admission."""

from bridge.domain_protocol import valid_text
from bridge.protocol import validate_agent_id

COMMANDS = frozenset({"agent_status", "project_setup"})


def validate_interaction(payload):
    kind = payload.get("type")
    fields = {"type", "agent_id", "request_id"}
    if kind == "project_setup":
        fields.add("intent")
    if (
        kind not in COMMANDS
        or set(payload) != fields
        or not valid_text(payload.get("request_id"))
        or not valid_text(payload.get("agent_id"))
        or not validate_agent_id(payload.get("agent_id"))
        or (kind == "project_setup" and not valid_text(payload.get("intent"), 65536))
    ):
        raise ValueError("invalid_request")
    return payload


def interaction_error(payload, code, project):
    packet = dict(
        type=payload.get("type"),
        status="error",
        error_type=code,
        output="Character service unavailable: " + code,
        project=project,
        architect_decision=project.get("architect_decision"),
    )
    for key in ("agent_id", "request_id"):
        if valid_text(payload.get(key)):
            packet[key] = payload[key]
    return packet
