"""Protocol layer — message types, parsing, classification, response builders.

Shared vocabulary for the bridge's two engines (conversation and domain session).
This module has no I/O — it is pure data transformation.
"""

import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RequestType(Enum):
    DOMAIN_QUERY = "domain_query"
    CONVERSATION = "conversation"
    RESUME = "resume"


@dataclass
class BridgeRequest:
    type: RequestType = RequestType.CONVERSATION
    agent_id: str = ""
    task: str = ""
    domain_id: str = ""
    request_id: str = ""
    cursor: str = ""


_VALID_AGENT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def classify_request(raw: dict) -> RequestType:
    type_str = raw.get("type", "conversation")
    try:
        return RequestType(type_str)
    except ValueError:
        return RequestType.CONVERSATION


def parse_request(raw: dict) -> BridgeRequest:
    return BridgeRequest(
        type=classify_request(raw),
        agent_id=raw.get("agent_id", ""),
        task=raw.get("task", ""),
        domain_id=raw.get("domain_id", ""),
        request_id=raw.get("request_id", "") or str(uuid.uuid4()),
        cursor=raw.get("cursor", ""),
    )


def validate_request(request: BridgeRequest) -> Optional[str]:
    if request.type == RequestType.DOMAIN_QUERY:
        if not request.domain_id:
            return "domain_id is required for domain_query"
        if not request.agent_id:
            return "agent_id is required for domain_query"
        if not request.task:
            return "task is required for domain_query"
    elif request.type == RequestType.CONVERSATION:
        if not request.agent_id:
            return "agent_id is required"
        if not request.task:
            return "task is required"
    elif request.type == RequestType.RESUME:
        if not request.domain_id:
            return "domain_id is required for resume"
    return None


def validate_agent_id(agent_id: str) -> bool:
    return bool(
        agent_id and isinstance(agent_id, str) and _VALID_AGENT_ID.match(agent_id)
    )


def make_error(agent_id, task, error_type, message, **kwargs):
    resp = {
        "agent_id": agent_id,
        "task": task,
        "output": "",
        "status": "error",
        "error_type": error_type,
        "message": message,
    }
    resp.update(kwargs)
    return resp


def make_success(agent_id, task, output, **kwargs):
    resp = {
        "agent_id": agent_id,
        "task": task,
        "output": output,
        "status": "ok",
    }
    resp.update(kwargs)
    return resp


def make_domain_state(domain_id, state, unread_count):
    return {
        "type": "domain_state",
        "domain_id": domain_id,
        "state": state,
        "unread_count": unread_count,
    }
