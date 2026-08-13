"""Tests for bridge.domain_session — output buffer and domain session lifecycle."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bridge.domain_session import (
    OutputBuffer,
    OutputEntry,
    SessionState,
    DomainSession,
    InvalidTransitionError,
)


class TestOutputBuffer:
    def test_append_returns_entry_with_monotonic_id(self):
        buf = OutputBuffer()
        e1 = buf.append("agent-a", "task 1", "output 1", "r1")
        e2 = buf.append("agent-b", "task 2", "output 2", "r2")
        assert e1.output_id == 0
        assert e2.output_id == 1

    def test_since_cursor_returns_newer_entries(self):
        buf = OutputBuffer()
        buf.append("a", "t", "first", "r1")
        buf.append("a", "t", "second", "r2")
        buf.append("a", "t", "third", "r3")
        entries = buf.since(0)
        assert len(entries) == 2
        assert entries[0].output == "second"
        assert entries[1].output == "third"

    def test_since_minus_one_returns_all(self):
        buf = OutputBuffer()
        buf.append("a", "t", "first", "r1")
        buf.append("a", "t", "second", "r2")
        entries = buf.since(-1)
        assert len(entries) == 2

    def test_since_latest_returns_empty(self):
        buf = OutputBuffer()
        buf.append("a", "t", "first", "r1")
        entries = buf.since(0)
        assert entries == []

    def test_count_since(self):
        buf = OutputBuffer()
        buf.append("a", "t", "first", "r1")
        buf.append("a", "t", "second", "r2")
        buf.append("a", "t", "third", "r3")
        assert buf.count_since(0) == 2
        assert buf.count_since(-1) == 3
        assert buf.count_since(2) == 0

    def test_latest_id_empty_buffer(self):
        buf = OutputBuffer()
        assert buf.latest_id == -1

    def test_latest_id_after_append(self):
        buf = OutputBuffer()
        buf.append("a", "t", "o", "r")
        assert buf.latest_id == 0
        buf.append("a", "t", "o", "r")
        assert buf.latest_id == 1


class TestSessionState:
    def test_initial_state_is_inactive(self):
        session = DomainSession("engineering")
        assert session.state == SessionState.INACTIVE

    def test_phase1_accommodation_defaults(self):
        session = DomainSession("engineering")
        assert session.claims == []
        assert session.worktree_path is None
        assert session.base_path is not None

    def test_custom_base_path(self):
        session = DomainSession("engineering", base_path="/custom/path")
        assert session.base_path == "/custom/path"

    def test_background_from_active(self):
        session = DomainSession("engineering")
        session._state = SessionState.ACTIVE
        session.background()
        assert session.state == SessionState.BACKGROUNDED

    def test_refocus_from_backgrounded(self):
        session = DomainSession("engineering")
        session._state = SessionState.BACKGROUNDED
        session.refocus()
        assert session.state == SessionState.ACTIVE

    def test_invalid_transition_raises(self):
        session = DomainSession("engineering")
        with pytest.raises(InvalidTransitionError):
            session.background()


@pytest.mark.asyncio
class TestDomainSessionSDK:
    @pytest.fixture
    def mock_sdk(self, monkeypatch):
        mock_client = AsyncMock()

        async def fake_receive():
            msg = MagicMock()
            msg.content = [MagicMock(text="SDK response text")]
            type(msg).__name__ = "AssistantMessage"
            yield msg
            result = MagicMock()
            type(result).__name__ = "ResultMessage"
            yield result

        mock_client.receive_response = fake_receive
        mock_cls = MagicMock(return_value=mock_client)
        monkeypatch.setattr("bridge.domain_session.ClaudeSDKClient", mock_cls)
        return mock_client, mock_cls

    async def test_activate_transitions_to_active(self, mock_sdk):
        session = DomainSession("engineering")
        await session.activate()
        assert session.state == SessionState.ACTIVE

    async def test_activate_connects_sdk_client(self, mock_sdk):
        mock_client, _ = mock_sdk
        session = DomainSession("engineering")
        await session.activate()
        mock_client.connect.assert_awaited_once()

    async def test_deactivate_disconnects(self, mock_sdk):
        mock_client, _ = mock_sdk
        session = DomainSession("engineering")
        await session.activate()
        await session.deactivate()
        assert session.state == SessionState.DEACTIVATED
        mock_client.disconnect.assert_awaited_once()

    async def test_submit_query_buffers_output(self, mock_sdk, monkeypatch):
        monkeypatch.setattr(
            "bridge.domain_session.load_agent",
            lambda aid: "You are an engineer.",
        )
        session = DomainSession("engineering")
        await session.activate()
        callback = AsyncMock()
        await session.submit_query(
            "systems-architect", "review code", "r1", on_output=callback
        )
        await asyncio.sleep(0.1)
        assert session.buffer.latest_id == 0
        entry = session.buffer.since(-1)[0]
        assert entry.output == "SDK response text"
        assert entry.agent_id == "systems-architect"

    async def test_submit_query_calls_callback(self, mock_sdk, monkeypatch):
        monkeypatch.setattr(
            "bridge.domain_session.load_agent",
            lambda aid: "You are an engineer.",
        )
        session = DomainSession("engineering")
        await session.activate()
        callback = AsyncMock()
        await session.submit_query(
            "systems-architect", "review code", "r1", on_output=callback
        )
        await asyncio.sleep(0.1)
        callback.assert_awaited_once()
