"""Temporary, offline runtime wiring fixtures."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

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


@pytest.fixture
def offline_clients(monkeypatch):
    conversation = MagicMock()
    conversation.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(text="conversation reply")]
    )
    sdk = AsyncMock()

    class ResultMessage:
        session_id = "observed-provider-session"
        is_error = False

    async def receive():
        yield SimpleNamespace(content=[SimpleNamespace(text="domain reply")])
        yield ResultMessage()

    sdk.receive_response = receive
    sdk_class = MagicMock(return_value=sdk)
    monkeypatch.setattr("bridge.conversation.build_client", lambda: conversation)
    monkeypatch.setattr("bridge.domain_session.ClaudeSDKClient", sdk_class)
    monkeypatch.setattr("bridge.conversation.load_agent", lambda _: "definition")
    monkeypatch.setattr("bridge.domain_session.load_agent", lambda _: "definition")
    return conversation, sdk, sdk_class
