"""Explicit API-key-only Messages API compatibility; never an automatic fallback."""

import asyncio
import os

from anthropic import AsyncAnthropic

from bridge.conversation_backend import (
    ConversationFailure,
    contextual_definition,
    decode_project_reply,
)


def _api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if (
        not key.startswith("sk-ant-")
        or key.startswith(("sk-ant-oat", "sk-ant-ort"))
        or any(char.isspace() for char in key)
    ):
        raise ConversationFailure(
            "messages_api requires an ANTHROPIC_API_KEY; OAuth/setup tokens are not API keys",
            "auth",
        )
    return key


class MessagesAPIBackend:
    async def complete(
        self,
        *,
        definition,
        messages,
        model,
        timeout,
        max_output_tokens,
        metadata,
        prior_project_notes: str = "",
    ) -> str:
        # Explicit credentials are total in pinned Anthropic 0.121.0. Leaving
        # auth_token=None prevents inherited ANTHROPIC_AUTH_TOKEN bearer headers.
        async with AsyncAnthropic(api_key=_api_key()) as client:
            async with asyncio.timeout(timeout):
                response = await client.messages.create(
                    model=model,
                    max_tokens=max_output_tokens,
                    system=contextual_definition(definition, prior_project_notes),
                    messages=messages,
                    timeout=timeout,
                )
            if response.stop_reason == "max_tokens":
                raise ConversationFailure("Conversation output token limit reached")
            if response.stop_reason == "tool_use":
                raise ConversationFailure("Unexpected tool execution in conversation")
            output = "\n\n".join(
                block.text for block in response.content if block.type == "text"
            )

            if prior_project_notes:
                output, metadata.memory_delta = decode_project_reply(output)
            return output
