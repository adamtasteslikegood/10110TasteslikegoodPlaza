"""Tests for bridge.conversation — the conversation engine (Haiku, NPC chat)."""

import os
import pytest
from unittest.mock import MagicMock, patch

from bridge.conversation import (
    MAX_HISTORY_MESSAGES,
    ConversationEngine,
    build_client,
)


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


def sent_messages(client, call=-1):
    return client.messages.create.call_args_list[call].kwargs["messages"]


class TestConversationHistory:
    @pytest.fixture(autouse=True)
    def mock_agent_store(self, monkeypatch):
        monkeypatch.setattr(
            "bridge.conversation.load_agent", lambda aid: "You are a test agent."
        )

    @pytest.fixture
    def client(self):
        client = MagicMock()

        def reply(**kwargs):
            block = MagicMock()
            block.text = f"reply {client.messages.create.call_count}"
            response = MagicMock()
            response.content = [block]
            return response

        client.messages.create.side_effect = reply
        return client

    @pytest.fixture
    def engine(self, client):
        return ConversationEngine(client=client)

    def ask(self, engine, task, history=None):
        return engine.handle_request(
            {"agent_id": "systems-architect", "task": task}, history
        )

    def test_without_history_each_request_stands_alone(self, engine, client):
        self.ask(engine, "first")
        self.ask(engine, "second")
        assert sent_messages(client) == [{"role": "user", "content": "second"}]

    def test_second_turn_carries_the_first_exchange(self, engine, client):
        history = []
        self.ask(engine, "the code word is kestrel", history)
        self.ask(engine, "what was the code word?", history)
        assert sent_messages(client) == [
            {"role": "user", "content": "the code word is kestrel"},
            {"role": "assistant", "content": "reply 1"},
            {"role": "user", "content": "what was the code word?"},
        ]

    def test_history_is_extended_in_place_on_success(self, engine):
        history = []
        self.ask(engine, "hi", history)
        assert history == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "reply 1"},
        ]

    def test_failed_request_leaves_history_untouched(self, engine, client):
        history = []
        self.ask(engine, "hi", history)
        client.messages.create.side_effect = Exception("timed out")
        resp = self.ask(engine, "are you there?", history)
        assert resp["status"] == "error"
        assert [m["content"] for m in history] == ["hi", "reply 1"]

    def test_rejected_request_leaves_history_untouched(self, engine):
        history = []
        resp = engine.handle_request({"agent_id": "bad id!", "task": "hi"}, history)
        assert resp["error_type"] == "invalid_request"
        assert history == []

    def test_empty_reply_is_not_recorded(self, engine, client):
        response = MagicMock()
        response.content = []
        client.messages.create.side_effect = None
        client.messages.create.return_value = response
        history = []
        resp = self.ask(engine, "hi", history)
        assert resp["status"] == "ok"
        assert history == []

    def test_history_is_bounded_and_keeps_whole_exchanges(self, engine, client):
        history = []
        turns = MAX_HISTORY_MESSAGES // 2 + 3
        for number in range(turns):
            self.ask(engine, f"question {number}", history)
        assert len(history) == MAX_HISTORY_MESSAGES
        # The oldest survivor is a question, never an orphaned answer.
        assert history[0] == {"role": "user", "content": "question 3"}
        assert history[-1]["role"] == "assistant"
        assert len(sent_messages(client)) == MAX_HISTORY_MESSAGES + 1


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
