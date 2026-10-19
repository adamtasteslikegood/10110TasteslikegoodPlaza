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
