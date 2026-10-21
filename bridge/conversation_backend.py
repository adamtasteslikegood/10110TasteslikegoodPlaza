"""Request-local execution metadata shared by the two NPC adapters."""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExecutionMetadata:
    """Observed provider identity, never a resume handle or wire field."""

    provider_session_id: str | None = None


class ConversationFailure(Exception):
    def __init__(self, message: str, category: str = "api_error"):
        super().__init__(message)
        self.category = category


class ConversationBackend(Protocol):
    async def complete(
        self,
        *,
        definition: str,
        messages: list[dict],
        model: str,
        timeout: float,
        max_output_tokens: int,
        metadata: ExecutionMetadata,
    ) -> str: ...


def decode_project_reply(output: str) -> tuple[str, dict | None]:
    """Decode the shared optional envelope without discarding a usable answer.

    MemoryStore owns delta grammar/size/identity validation. Malformed or plain
    replies remain visible text; an invalid delta never hides a valid answer.
    """
    import json
    from bridge.workspace import _decode

    try:
        envelope = _decode(output.encode("utf-8"))
    except (ValueError, RecursionError, UnicodeError, json.JSONDecodeError):
        return output, None
    if not isinstance(envelope, dict) or not isinstance(envelope.get("answer"), str):
        return output, None
    delta = envelope.get("memory_delta")
    return envelope["answer"], delta if isinstance(delta, dict) else None
