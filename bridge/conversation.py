"""Async NPC validation/history facade; one request and one full response.

D-005: zero UI awareness. D-033 keeps blocking conversation UX and its deadline.
D-037 defaults execution to Claude Code, with explicit API-key compatibility.
History belongs to the caller and changes only after successful adapter cleanup.
"""

import asyncio

from bridge.agents import load_agent
from bridge.config import BridgeConfig, default_config
from bridge.conversation_backend import (
    ConversationBackend,
    ConversationFailure,
    ExecutionMetadata,
)
from bridge.conversation_sdk import ClaudeCodeBackend
from bridge.conversation_api import MessagesAPIBackend
from bridge.protocol import make_error, make_success, validate_agent_id

# Compatibility names derive from the same validated built-ins as runtime defaults.
_DEFAULT_CONFIG = default_config()
DEFAULT_MODEL = _DEFAULT_CONFIG.model_for(_DEFAULT_CONFIG.conversation_tier)
DEFAULT_TIMEOUT = _DEFAULT_CONFIG.conversation_timeout_seconds
DEFAULT_MAX_TOKENS = _DEFAULT_CONFIG.conversation_max_output_tokens
MAX_HISTORY_MESSAGES = _DEFAULT_CONFIG.context_max_messages


class ConversationEngine:
    """Validation and success-only bounded history, independent of backend."""

    def __init__(
        self,
        backend: ConversationBackend | None = None,
        model=None,
        timeout=None,
        *,
        config: BridgeConfig | None = None,
    ):
        self._config = config if config is not None else default_config()
        self._backend = (
            backend
            if backend is not None
            else (
                ClaudeCodeBackend()
                if self._config.conversation_backend == "claude_code"
                else MessagesAPIBackend()
            )
        )
        self._model = (
            model
            if model is not None
            else self._config.model_for(self._config.conversation_tier)
        )
        self._timeout = (
            timeout
            if timeout is not None
            else self._config.conversation_timeout_seconds
        )

    @property
    def model(self) -> str:
        return self._model

    async def handle_request(
        self,
        request,
        history=None,
        *,
        metadata=None,
        prior_project_notes="",
        deadline=None,
        context_packet=None,
    ):
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

        if context_packet is not None:
            definition += "\n" + context_packet.render()

        # Copy before the first await; even oversized caller input is bounded.
        messages = [
            dict(message)
            for message in (history or [])[-self._config.context_max_messages :]
        ]
        messages.append({"role": "user", "content": task})
        metadata = metadata if metadata is not None else ExecutionMetadata()
        if context_packet is not None:
            metadata.context_sources = context_packet.diagnostics()
        try:
            options = {}
            if prior_project_notes:
                options["prior_project_notes"] = prior_project_notes
            timeout = (
                self._timeout
                if deadline is None
                else deadline - asyncio.get_running_loop().time()
            )
            if timeout <= 0:
                raise TimeoutError()
            output = await self._backend.complete(
                definition=definition,
                messages=messages,
                model=self._model,
                timeout=timeout,
                max_output_tokens=self._config.conversation_max_output_tokens,
                metadata=metadata,
                **options,
            )
            if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError()
            # The API rejects an empty assistant turn, so an exchange with no
            # text is not one the next request could replay.
            if history is not None and output:
                history.append({"role": "user", "content": task})
                history.append({"role": "assistant", "content": output})
                del history[: -self._config.context_max_messages]
            return make_success(agent_id, task, output)
        except ConversationFailure as exc:
            return make_error(agent_id, task, exc.category, str(exc))
        except Exception as exc:
            exc_name = type(exc).__name__
            if "auth" in exc_name.lower() or "authentication" in str(exc).lower():
                return make_error(agent_id, task, "auth", str(exc))
            if "timeout" in exc_name.lower() or "timed out" in str(exc).lower():
                return make_error(
                    agent_id, task, "timeout", f"Timed out after {self._timeout}s"
                )
            return make_error(agent_id, task, "api_error", str(exc))
