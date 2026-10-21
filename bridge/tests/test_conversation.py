"""Tests for bridge.conversation — the conversation engine (Haiku, NPC chat)."""

import pytest
from unittest.mock import AsyncMock

from bridge.conversation import (
    MAX_HISTORY_MESSAGES,
    ConversationEngine,
)


@pytest.mark.asyncio
class TestConversationEngine:
    @pytest.fixture(autouse=True)
    def mock_agent_store(self, monkeypatch):
        monkeypatch.setattr(
            "bridge.conversation.load_agent",
            lambda aid: "You are a test agent." if aid == "systems-architect" else None,
        )

    @pytest.fixture
    def mock_backend(self):
        return AsyncMock(complete=AsyncMock(return_value="Hello from Haiku"))

    @pytest.fixture
    def engine(self, mock_backend):
        return ConversationEngine(backend=mock_backend)

    async def test_success_response(self, engine, mock_backend):
        resp = await engine.handle_request(
            {"agent_id": "systems-architect", "task": "hi"}
        )
        assert resp["status"] == "ok"
        assert resp["output"] == "Hello from Haiku"
        assert resp["agent_id"] == "systems-architect"

    async def test_default_model_is_haiku(self, engine, mock_backend):
        await engine.handle_request({"agent_id": "systems-architect", "task": "hi"})
        call_kwargs = mock_backend.complete.call_args
        assert "haiku" in call_kwargs.kwargs.get(
            "model", call_kwargs[1].get("model", "")
        )

    async def test_missing_agent_returns_not_found(self, engine):
        resp = await engine.handle_request(
            {"agent_id": "nonexistent-agent", "task": "hi"}
        )
        assert resp["status"] == "error"
        assert resp["error_type"] == "not_found"

    async def test_missing_agent_id_returns_invalid(self, engine):
        resp = await engine.handle_request({"agent_id": "", "task": "hi"})
        assert resp["status"] == "error"
        assert resp["error_type"] == "invalid_request"

    async def test_missing_task_returns_invalid(self, engine):
        resp = await engine.handle_request(
            {"agent_id": "systems-architect", "task": ""}
        )
        assert resp["status"] == "error"
        assert resp["error_type"] == "invalid_request"

    async def test_non_dict_returns_invalid(self, engine):
        resp = await engine.handle_request("not a dict")
        assert resp["status"] == "error"

    async def test_timeout_error(self, engine, mock_backend):
        mock_backend.complete.side_effect = Exception("timed out")
        resp = await engine.handle_request(
            {"agent_id": "systems-architect", "task": "hi"}
        )
        assert resp["error_type"] == "timeout"

    async def test_auth_error(self, engine, mock_backend):
        mock_backend.complete.side_effect = Exception(
            "AuthenticationError: invalid key"
        )
        resp = await engine.handle_request(
            {"agent_id": "systems-architect", "task": "hi"}
        )
        assert resp["error_type"] == "auth"


def sent_messages(client, call=-1):
    return client.complete.call_args_list[call].kwargs["messages"]


@pytest.mark.asyncio
class TestConversationHistory:
    @pytest.fixture(autouse=True)
    def mock_agent_store(self, monkeypatch):
        monkeypatch.setattr(
            "bridge.conversation.load_agent", lambda aid: "You are a test agent."
        )

    @pytest.fixture
    def client(self):
        client = AsyncMock()

        def reply(**kwargs):
            return f"reply {client.complete.call_count}"

        client.complete.side_effect = reply
        return client

    @pytest.fixture
    def engine(self, client):
        return ConversationEngine(backend=client)

    async def ask(self, engine, task, history=None):
        return await engine.handle_request(
            {"agent_id": "systems-architect", "task": task}, history
        )

    async def test_without_history_each_request_stands_alone(self, engine, client):
        await self.ask(engine, "first")
        await self.ask(engine, "second")
        assert sent_messages(client) == [{"role": "user", "content": "second"}]

    async def test_second_turn_carries_the_first_exchange(self, engine, client):
        history = []
        await self.ask(engine, "the code word is kestrel", history)
        await self.ask(engine, "what was the code word?", history)
        assert sent_messages(client) == [
            {"role": "user", "content": "the code word is kestrel"},
            {"role": "assistant", "content": "reply 1"},
            {"role": "user", "content": "what was the code word?"},
        ]

    async def test_history_is_extended_in_place_on_success(self, engine):
        history = []
        await self.ask(engine, "hi", history)
        assert history == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "reply 1"},
        ]

    async def test_failed_request_leaves_history_untouched(self, engine, client):
        history = []
        await self.ask(engine, "hi", history)
        client.complete.side_effect = Exception("timed out")
        resp = await self.ask(engine, "are you there?", history)
        assert resp["status"] == "error"
        assert [m["content"] for m in history] == ["hi", "reply 1"]

    async def test_rejected_request_leaves_history_untouched(self, engine):
        history = []
        resp = await engine.handle_request(
            {"agent_id": "bad id!", "task": "hi"}, history
        )
        assert resp["error_type"] == "invalid_request"
        assert history == []

    async def test_empty_reply_is_not_recorded(self, engine, client):
        client.complete.side_effect = None
        client.complete.return_value = ""
        history = []
        resp = await self.ask(engine, "hi", history)
        assert resp["status"] == "ok"
        assert history == []

    async def test_history_is_bounded_and_keeps_whole_exchanges(self, engine, client):
        history = []
        turns = MAX_HISTORY_MESSAGES // 2 + 3
        for number in range(turns):
            await self.ask(engine, f"question {number}", history)
        assert len(history) == MAX_HISTORY_MESSAGES
        # The oldest survivor is a question, never an orphaned answer.
        assert history[0] == {"role": "user", "content": "question 3"}
        assert history[-1]["role"] == "assistant"
        assert len(sent_messages(client)) == MAX_HISTORY_MESSAGES + 1


@pytest.mark.asyncio
async def test_request_local_deadline_includes_reply_preparation(monkeypatch):
    import asyncio
    import time
    from unittest.mock import AsyncMock
    from bridge.conversation import ConversationEngine

    monkeypatch.setattr("bridge.conversation.load_agent", lambda _: "definition")
    backend = AsyncMock()

    async def late_reply(**kwargs):
        # Synchronous response preparation can finish after the absolute budget
        # before the event loop gets a chance to deliver its timeout callback.
        time.sleep(0.02)
        return "too late"

    backend.complete.side_effect = late_reply
    history = []
    response = await ConversationEngine(backend=backend).handle_request(
        dict(agent_id="agent", task="work"),
        history,
        deadline=asyncio.get_running_loop().time() + 0.005,
    )
    assert response["error_type"] == "timeout"
    assert history == []
