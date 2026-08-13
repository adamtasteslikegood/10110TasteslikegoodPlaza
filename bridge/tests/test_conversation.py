"""Tests for bridge.conversation — the conversation engine (Haiku, stateless)."""

import os
import pytest
from unittest.mock import MagicMock, patch

from bridge.conversation import ConversationEngine, build_client


class TestConversationEngine:
    @pytest.fixture(autouse=True)
    def mock_agent_store(self, monkeypatch):
        monkeypatch.setattr(
            "bridge.conversation.load_agent",
            lambda aid: "You are a test agent." if aid == "systems-architect" else None,
        )

    @pytest.fixture
    def mock_anthropic(self):
        client = MagicMock()
        block = MagicMock()
        block.text = "Hello from Haiku"
        response = MagicMock()
        response.content = [block]
        client.messages.create.return_value = response
        return client

    @pytest.fixture
    def engine(self, mock_anthropic):
        return ConversationEngine(client=mock_anthropic)

    def test_success_response(self, engine, mock_anthropic):
        resp = engine.handle_request({"agent_id": "systems-architect", "task": "hi"})
        assert resp["status"] == "ok"
        assert resp["output"] == "Hello from Haiku"
        assert resp["agent_id"] == "systems-architect"

    def test_default_model_is_haiku(self, engine, mock_anthropic):
        engine.handle_request({"agent_id": "systems-architect", "task": "hi"})
        call_kwargs = mock_anthropic.messages.create.call_args
        assert "haiku" in call_kwargs.kwargs.get(
            "model", call_kwargs[1].get("model", "")
        )

    def test_missing_agent_returns_not_found(self, engine):
        resp = engine.handle_request({"agent_id": "nonexistent-agent", "task": "hi"})
        assert resp["status"] == "error"
        assert resp["error_type"] == "not_found"

    def test_missing_agent_id_returns_invalid(self, engine):
        resp = engine.handle_request({"agent_id": "", "task": "hi"})
        assert resp["status"] == "error"
        assert resp["error_type"] == "invalid_request"

    def test_missing_task_returns_invalid(self, engine):
        resp = engine.handle_request({"agent_id": "systems-architect", "task": ""})
        assert resp["status"] == "error"
        assert resp["error_type"] == "invalid_request"

    def test_non_dict_returns_invalid(self, engine):
        resp = engine.handle_request("not a dict")
        assert resp["status"] == "error"

    def test_timeout_error(self, engine, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("timed out")
        resp = engine.handle_request({"agent_id": "systems-architect", "task": "hi"})
        assert resp["error_type"] == "timeout"

    def test_auth_error(self, engine, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception(
            "AuthenticationError: invalid key"
        )
        resp = engine.handle_request({"agent_id": "systems-architect", "task": "hi"})
        assert resp["error_type"] == "auth"


class TestBuildClient:
    def test_api_key_uses_api_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test123")
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        with patch("bridge.conversation.Anthropic") as mock_cls:
            build_client()
            mock_cls.assert_called_once_with(api_key="sk-ant-test123")

    def test_oauth_token_uses_auth_token(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-tok")
        with patch("bridge.conversation.Anthropic") as mock_cls:
            build_client()
            mock_cls.assert_called_once_with(auth_token="oauth-tok")
