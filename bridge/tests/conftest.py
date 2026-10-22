"""Temporary, offline runtime wiring fixtures."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage as SDKResultMessage,
    TextBlock,
)

from bridge.config import load_config
from bridge.observability import BridgeRecorder


@pytest.fixture
def runtime_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"LOG_DIR": "logs", "LOG_LEVEL": "DEBUG"}))
    return load_config(path, environ={})


@pytest.fixture
def runtime_archive(runtime_config):
    class MemoryWriter:
        def __init__(self):
            self.records = []
            self.closed = []

        def append(self, kind, record, *, agent_id=None):
            self.records.append((kind, dict(record), agent_id))
            return True

        def close(self, *, clean=True):
            self.closed.append(clean)

    writer = MemoryWriter()
    recorder = BridgeRecorder(
        runtime_config, "project", writer=writer, redactions=("credential-sentinel",)
    )
    yield recorder, writer
    recorder.close()


@pytest.fixture(autouse=True)
def forbid_live_model_transports(monkeypatch):
    """A missed fake fails closed before Claude launch or provider HTTP."""
    # An ambient (even empty) base URL would redirect fake-transport clients.
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    async def blocked_async(*args, **kwargs):
        pytest.fail("Live model transport is forbidden in offline bridge tests")

    def blocked_sync(*args, **kwargs):
        pytest.fail("Live model transport is forbidden in offline bridge tests")

    monkeypatch.setattr(
        "claude_agent_sdk._internal.transport.subprocess_cli.SubprocessCLITransport.connect",
        blocked_async,
    )
    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", blocked_async)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", blocked_sync)


@pytest.fixture
def offline_clients(monkeypatch, explicit_extras):
    # NPC SDK seam is separate from the domain SDK seam. Fresh clients record
    # decoded JSON input, and yield real SDK message types for adapter validation.
    conversation = SimpleNamespace(
        reply=MagicMock(return_value="conversation reply"), clients=[]
    )

    def conversation_factory(*, options, transport=None):
        client = AsyncMock()
        client.options = options
        conversation.clients.append(client)

        async def receive():
            prompt = client.query.call_args.args[0]
            output = conversation.reply(
                messages=json.loads(prompt.split("\n", 1)[1])["messages"],
                model=options.model,
                system=options.system_prompt,
                max_output_tokens=int(options.env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"]),
            )
            yield AssistantMessage(
                content=[TextBlock(text=output)], model=options.model
            )
            yield SDKResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="observed-npc-session",
                result=output,
            )

        client.receive_response = receive
        return client

    conversation.factory = MagicMock(side_effect=conversation_factory)
    sdk = AsyncMock()

    class ResultMessage:
        session_id = "observed-provider-session"
        is_error = False

    async def receive():
        yield SimpleNamespace(content=[SimpleNamespace(text="domain reply")])
        yield ResultMessage()

    sdk.receive_response = receive
    sdk_class = MagicMock(return_value=sdk)
    monkeypatch.setattr("bridge.conversation_sdk.ClaudeSDKClient", conversation.factory)
    monkeypatch.setattr("bridge.conversation.load_agent", lambda _, **kw: "definition")
    monkeypatch.setattr(
        "bridge.domain_session.load_agent", lambda _, **kw: "definition"
    )
    return conversation, sdk, sdk_class


@pytest.fixture
def explicit_extras(monkeypatch):
    """Register only noncatalog story fixtures; never relabel working agents."""
    from bridge.agent_bindings import BindingRegistry

    original = BindingRegistry.__init__
    extras = {
        name: dict(execution_kind="extra", domain_id=None, definition="Story fixture")
        for name in (
            "agent",
            "test",
            "other",
            "builder",
            "alpha",
            "beta-integration-credential-sentinel",
            "fixture-extra",
            "fixture-extra-a",
            "fixture-extra-b",
        )
    }

    def initialize(self, **kwargs):
        kwargs.setdefault("extras", extras)
        original(self, **kwargs)

    monkeypatch.setattr(BindingRegistry, "__init__", initialize)
    return extras
