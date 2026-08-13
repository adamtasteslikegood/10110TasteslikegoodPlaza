"""Tests for bridge.domain_manager — domain session orchestration."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bridge.domain_manager import DomainManager
from bridge.domain_session import SessionState, OutputEntry
from bridge.protocol import BridgeRequest, RequestType


@pytest.fixture
def mock_session_cls(monkeypatch):
    sessions = {}

    def make_session(domain_id, base_path=None):
        session = MagicMock()
        session.domain_id = domain_id
        session.state = SessionState.INACTIVE
        session._state = SessionState.INACTIVE
        session.buffer = MagicMock()
        session.buffer.latest_id = -1
        session.buffer.count_since.return_value = 0
        session.buffer.since.return_value = []
        session.activate = AsyncMock(
            side_effect=lambda **kw: setattr(session, "state", SessionState.ACTIVE)
            or setattr(session, "_state", SessionState.ACTIVE)
        )
        session.submit_query = AsyncMock()
        session.background = MagicMock(
            side_effect=lambda: setattr(session, "state", SessionState.BACKGROUNDED)
        )
        session.refocus = MagicMock(
            side_effect=lambda: setattr(session, "state", SessionState.ACTIVE)
        )
        session.deactivate = AsyncMock(
            side_effect=lambda: setattr(session, "state", SessionState.DEACTIVATED)
        )
        sessions[domain_id] = session
        return session

    monkeypatch.setattr("bridge.domain_manager.DomainSession", make_session)
    return sessions


@pytest.mark.asyncio
class TestDomainManager:
    async def test_activate_domain(self, mock_session_cls):
        mgr = DomainManager()
        result = await mgr.activate_domain("engineering")
        assert result["domain_id"] == "engineering"
        assert result["state"] == "active"
        assert "engineering" in mgr.list_active_domains()

    async def test_activate_already_active(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        result = await mgr.activate_domain("engineering")
        assert result["state"] == "active"

    async def test_submit_query_to_active_domain(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        req = BridgeRequest(
            type=RequestType.DOMAIN_QUERY,
            domain_id="engineering",
            agent_id="systems-architect",
            task="review code",
            request_id="r1",
        )
        callback = AsyncMock()
        result = await mgr.handle_domain_query(req, on_output=callback)
        assert result is None  # async — output comes via callback
        mock_session_cls["engineering"].submit_query.assert_awaited_once()

    async def test_submit_query_to_inactive_domain(self, mock_session_cls):
        mgr = DomainManager()
        req = BridgeRequest(
            type=RequestType.DOMAIN_QUERY,
            domain_id="engineering",
            agent_id="a",
            task="t",
            request_id="r1",
        )
        result = await mgr.handle_domain_query(req, on_output=AsyncMock())
        assert result["status"] == "error"
        assert "not active" in result["message"]

    async def test_background_domain(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        result = mgr.background_domain("engineering")
        assert result["state"] == "backgrounded"

    async def test_refocus_domain(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        mgr.background_domain("engineering")
        result = mgr.refocus_domain("engineering")
        assert result["state"] == "active"

    async def test_resume_returns_buffered_entries(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        entry = OutputEntry(
            output_id=0, agent_id="a", task="t", output="hello", request_id="r1"
        )
        mock_session_cls["engineering"].buffer.since.return_value = [entry]
        results = mgr.handle_resume("engineering", cursor=-1)
        assert len(results) == 1
        assert results[0]["output"] == "hello"
        assert results[0]["output_id"] == "0"

    async def test_deactivate_domain(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        result = await mgr.deactivate_domain("engineering")
        assert result["state"] == "deactivated"

    async def test_get_domain_state(self, mock_session_cls):
        mgr = DomainManager()
        assert mgr.get_domain_state("engineering") is None
        await mgr.activate_domain("engineering")
        state = mgr.get_domain_state("engineering")
        assert state["domain_id"] == "engineering"
        assert state["state"] == "active"
