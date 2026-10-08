"""Conversation engine — one request, one model call, for NPC chat.

Evolved from bridge.py's handle_request(). Uses the Anthropic Messages API
with Haiku for low-cost personality-driven NPC interactions.

The engine holds no state of its own. A caller that wants a conversation
passes the turns so far as `history` and the engine extends it; the server
keeps one per connection and agent (bridge/PROTOCOL.md, "Conversation
history"). Called without one, every request stands alone, as it did in M8.

D-005: zero UI awareness.
D-006: synchronous with timeout.
"""

import os

from anthropic import Anthropic

from bridge.agents import load_agent
from bridge.protocol import make_error, make_success, validate_agent_id

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_TOKENS = 4096
# Messages kept per conversation, user and assistant turns counted separately.
# Bounds both the memory a long-lived connection can hold and what each
# request re-sends to the model. Even, so trimming never splits an exchange.
MAX_HISTORY_MESSAGES = 40


def build_client():
    """Build an Anthropic client, resolving credentials in priority order.

    1. ANTHROPIC_API_KEY (sk-ant-..., x-api-key header)
    2. ANTHROPIC_AUTH_TOKEN (Authorization: Bearer)
    3. CLAUDE_CODE_OAUTH_TOKEN (bridge-local alias)
    4. CLAUDE_CODE_0AUTH_TOKEN (alternate spelling)
    5. SDK reads ~/.config/anthropic/ automatically
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key.startswith("sk-ant-"):
        return Anthropic(api_key=api_key)

    auth_token = (
        os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        or os.environ.get("CLAUDE_CODE_0AUTH_TOKEN")
    )
    if auth_token:
        return Anthropic(auth_token=auth_token)

    return Anthropic()


class ConversationEngine:
    """Request/response engine for NPC chat and story content.

    Each call is one Haiku invocation — no tool use, no background
    execution, and no state on the engine. Earlier turns reach the model
    only through the `history` the caller hands to handle_request().
    """

    def __init__(self, client=None, model=None, timeout=None):
        self._client = client or build_client()
        self._model = model or DEFAULT_MODEL
        self._timeout = timeout or DEFAULT_TIMEOUT

    def handle_request(self, request, history=None):
        """Answer one request.

        `history` is the caller's list of earlier messages with this agent,
        oldest first. On success the new exchange is appended to it in place
        and the list is trimmed to MAX_HISTORY_MESSAGES. A failed request
        leaves it untouched, so a retry does not send the question twice.
        """
        if not isinstance(request, dict):
            return make_error(
                "", "", "invalid_request", "Request must be a JSON object"
            )

        agent_id = request.get("agent_id", "")
        task = request.get("task", "")

        if not isinstance(agent_id, str) or not isinstance(task, str):
            return make_error(
                "", "", "invalid_request", "agent_id and task must be strings"
            )

        if not agent_id or not task:
            return make_error(
                agent_id, task, "invalid_request", "agent_id and task are required"
            )

        if not validate_agent_id(agent_id):
            return make_error(
                agent_id,
                task,
                "invalid_request",
                "agent_id contains invalid characters",
            )

        definition = load_agent(agent_id)
        if definition is None:
            return make_error(agent_id, task, "not_found", f"No agent '{agent_id}'")

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=DEFAULT_MAX_TOKENS,
                system=definition,
                messages=[*(history or []), {"role": "user", "content": task}],
                timeout=self._timeout,
            )
            parts = [b.text for b in response.content if hasattr(b, "text")]
            output = "\n\n".join(parts) if parts else ""
            # The API rejects an empty assistant turn, so an exchange with no
            # text is not one the next request could replay.
            if history is not None and output:
                history.append({"role": "user", "content": task})
                history.append({"role": "assistant", "content": output})
                del history[:-MAX_HISTORY_MESSAGES]
            return make_success(agent_id, task, output)
        except Exception as exc:
            exc_name = type(exc).__name__
            if "auth" in exc_name.lower() or "authentication" in str(exc).lower():
                return make_error(agent_id, task, "auth", str(exc))
            if "timeout" in exc_name.lower() or "timed out" in str(exc).lower():
                return make_error(
                    agent_id, task, "timeout", f"Timed out after {self._timeout}s"
                )
            return make_error(agent_id, task, "api_error", str(exc))
