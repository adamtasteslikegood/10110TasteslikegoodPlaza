"""Tests for bridge.server — WebSocket routing and backward compat."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bridge.server import BridgeServer


@pytest.fixture
def mock_engines(monkeypatch):
    conv_engine = MagicMock()
    conv_engine.handle_request.return_value = {
        "agent_id": "test",
        "task": "hi",
        "output": "hello",
        "status": "ok",
    }

    domain_mgr = AsyncMock()
    domain_mgr.handle_domain_query = AsyncMock(return_value=None)
    domain_mgr.activate_domain = AsyncMock(
        return_value={
            "type": "domain_state",
            "domain_id": "engineering",
            "state": "active",
            "unread_count": 0,
        }
    )
    domain_mgr.handle_resume = MagicMock(return_value=[])
    domain_mgr.background_domain = MagicMock(
        return_value={
            "type": "domain_state",
            "domain_id": "engineering",
            "state": "backgrounded",
            "unread_count": 0,
        }
    )
    domain_mgr.refocus_domain = MagicMock(
        return_value={
            "type": "domain_state",
            "domain_id": "engineering",
            "state": "active",
            "unread_count": 0,
        }
    )

    monkeypatch.setattr("bridge.server.ConversationEngine", lambda **kw: conv_engine)
    monkeypatch.setattr("bridge.server.DomainManager", lambda **kw: domain_mgr)
    return conv_engine, domain_mgr


@pytest.mark.asyncio
class TestBridgeServerDispatch:
    async def test_legacy_request_routes_to_conversation(self, mock_engines):
        conv, _ = mock_engines
        server = BridgeServer()
        resp = await server.dispatch({"agent_id": "test", "task": "hi"})
        assert resp == [conv.handle_request.return_value]

    async def test_conversation_type_routes_to_conversation(self, mock_engines):
        conv, _ = mock_engines
        server = BridgeServer()
        resp = await server.dispatch(
            {"type": "conversation", "agent_id": "test", "task": "hi"}
        )
        assert resp == [conv.handle_request.return_value]

    async def test_domain_query_routes_to_domain_manager(self, mock_engines):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        resp = await server.dispatch(
            {
                "type": "domain_query",
                "domain_id": "engineering",
                "agent_id": "systems-architect",
                "task": "review",
                "request_id": "r1",
            }
        )
        domain_mgr.handle_domain_query.assert_awaited_once()

    async def test_resume_returns_buffered_entries(self, mock_engines):
        _, domain_mgr = mock_engines
        domain_mgr.handle_resume.return_value = [
            {
                "agent_id": "a",
                "output": "buffered",
                "status": "ok",
                "task": "t",
                "output_id": "0",
                "domain_id": "engineering",
                "request_id": "r1",
            },
        ]
        server = BridgeServer()
        resp = await server.dispatch(
            {"type": "resume", "domain_id": "engineering", "cursor": "-1"}
        )
        assert len(resp) == 1
        assert resp[0]["output"] == "buffered"

    async def test_activate_domain_dispatch(self, mock_engines):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        resp = await server.dispatch(
            {"type": "activate_domain", "domain_id": "engineering"}
        )
        domain_mgr.activate_domain.assert_awaited_once_with("engineering")

    async def test_background_domain_dispatch(self, mock_engines):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        resp = await server.dispatch(
            {"type": "background_domain", "domain_id": "engineering"}
        )
        domain_mgr.background_domain.assert_called_once_with("engineering")

    async def test_refocus_domain_dispatch(self, mock_engines):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        resp = await server.dispatch(
            {"type": "refocus_domain", "domain_id": "engineering"}
        )
        domain_mgr.refocus_domain.assert_called_once_with("engineering")

    async def test_invalid_json_returns_error(self, mock_engines):
        server = BridgeServer()
        resp = await server.dispatch_raw("not json {{{")
        assert len(resp) == 1
        assert resp[0]["status"] == "error"

    async def test_validation_error_returns_error(self, mock_engines):
        server = BridgeServer()
        resp = await server.dispatch(
            {"type": "domain_query", "domain_id": "", "agent_id": "", "task": ""}
        )
        assert len(resp) == 1
        assert resp[0]["status"] == "error"
