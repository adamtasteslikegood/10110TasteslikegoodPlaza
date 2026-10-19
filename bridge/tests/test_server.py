"""Tests for bridge.server — WebSocket routing and backward compat."""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from bridge.server import BridgeServer


@pytest.fixture
def mock_engines(monkeypatch):
    conv_engine = MagicMock()
    conv_engine.handle_request = AsyncMock()
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
    # Synchronous in DomainManager. Left as the AsyncMock default it returns an
    # un-awaited coroutine, which is truthy, so the resume branch passed by
    # accident and leaked a RuntimeWarning.
    domain_mgr.get_domain_state = MagicMock(return_value=None)
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
        domain_mgr.refocus_domain.assert_not_called()

    async def test_resume_refocuses_a_known_domain(self, mock_engines):
        _, domain_mgr = mock_engines
        domain_mgr.get_domain_state.return_value = {
            "type": "domain_state",
            "domain_id": "engineering",
            "state": "backgrounded",
            "unread_count": 1,
        }
        server = BridgeServer()
        await server.dispatch(
            {"type": "resume", "domain_id": "engineering", "cursor": "-1"}
        )
        domain_mgr.get_domain_state.assert_called_once_with("engineering")
        domain_mgr.refocus_domain.assert_called_once_with("engineering")

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


@pytest.mark.asyncio
class TestConversationHistoryRouting:
    """History belongs to a connection and, within it, to an agent."""

    def passed_history(self, conv, call=-1):
        args = conv.handle_request.call_args_list[call].args
        return args[1] if len(args) > 1 else None

    def answering(self, conv):
        """Make the mocked engine keep a history the way the real one does."""

        async def handle(request, history=None, *, metadata=None):
            if history is not None:
                history += [
                    {"role": "user", "content": request["task"]},
                    {"role": "assistant", "content": "x"},
                ]
            return {"status": "ok", "output": "x"}

        conv.handle_request.side_effect = handle

    async def test_dispatch_without_a_connection_passes_no_history(self, mock_engines):
        conv, _ = mock_engines
        server = BridgeServer()
        await server.dispatch({"agent_id": "test", "task": "hi"})
        assert self.passed_history(conv) is None

    async def test_same_agent_on_one_connection_shares_a_history(self, mock_engines):
        conv, _ = mock_engines
        self.answering(conv)
        server = BridgeServer()
        histories = {}
        await server.dispatch({"agent_id": "test", "task": "one"}, histories)
        await server.dispatch({"agent_id": "test", "task": "two"}, histories)
        assert self.passed_history(conv, 0) is self.passed_history(conv, 1)
        assert self.passed_history(conv) is histories["test"]

    async def test_another_agent_gets_its_own_history(self, mock_engines):
        conv, _ = mock_engines
        self.answering(conv)
        server = BridgeServer()
        histories = {}
        await server.dispatch({"agent_id": "test", "task": "one"}, histories)
        await server.dispatch({"agent_id": "other", "task": "two"}, histories)
        assert self.passed_history(conv, 0) is not self.passed_history(conv, 1)

    async def test_each_connection_starts_with_no_history(self, mock_engines):
        conv, _ = mock_engines
        server = BridgeServer()

        class FakeSocket:
            def __init__(self, messages):
                self.messages = messages
                self.sent = []

            def __aiter__(self):
                return self._iterate()

            async def _iterate(self):
                for message in self.messages:
                    yield message

            async def wait_closed(self):
                await asyncio.Future()

            async def send(self, payload):
                self.sent.append(payload)

        self.answering(conv)
        request = json.dumps({"agent_id": "test", "task": "hi"})
        first, second = FakeSocket([request, request]), FakeSocket([request])
        await server._handle_connection(first)
        await server._handle_connection(second)

        assert len(first.sent) == 2 and len(second.sent) == 1
        assert self.passed_history(conv, 0) is self.passed_history(conv, 1)
        assert self.passed_history(conv, 2) is not self.passed_history(conv, 0)

    async def test_a_request_that_fails_leaves_no_history_behind(self, mock_engines):
        conv, _ = mock_engines
        conv.handle_request.return_value = {"status": "error"}
        server = BridgeServer()
        histories = {}
        for n in range(50):
            await server.dispatch({"agent_id": f"nobody-{n}", "task": "hi"}, histories)
        assert histories == {}

    async def test_agent_id_that_cannot_key_a_history_gets_none(self, mock_engines):
        conv, _ = mock_engines
        server = BridgeServer()
        histories = {}
        for agent_id in (["a"], {"a": 1}, 7):
            await server.dispatch({"agent_id": agent_id, "task": "hi"}, histories)
            assert self.passed_history(conv) is None
        assert histories == {}

    async def test_json_that_is_no_object_is_an_error_not_a_crash(self, mock_engines):
        server = BridgeServer()
        resp = await server.dispatch_raw("[1, 2]")
        assert resp[0]["error_type"] == "invalid_request"


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown", [False, True])
async def test_domain_activation_survives_peer_close(
    offline_clients, runtime_config, shutdown
):
    """A closed peer must not strand the real domain lifecycle in ACTIVATING."""
    import websockets

    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    _, sdk, _ = offline_clients

    async def connect():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    sdk.connect.side_effect = connect
    server = BridgeServer(config=runtime_config)
    listener = await websockets.serve(server._handle_connection, "127.0.0.1", 0)
    socket = await websockets.connect(
        f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
    )
    try:
        await socket.send(
            json.dumps({"type": "activate_domain", "domain_id": "engineering"})
        )
        await asyncio.wait_for(entered.wait(), 1)
        assert server.domains.get_domain_state("engineering")["state"] == "activating"
        if shutdown:
            listener.close()
        await socket.close()
        listener.close()
        # Closing a listener must still wait for the blocked activation. Give
        # its real close watcher time to run before allowing connect to finish.
        closed = asyncio.create_task(listener.wait_closed())
        await asyncio.wait({closed}, timeout=0.1)
        release.set()
        await asyncio.wait_for(listener.wait_closed(), 1)
        await closed
        assert not cancelled.is_set()
        assert server.domains.list_active_domains() == ["engineering"]
        assert server.domains.get_domain_state("engineering")["state"] == "active"
        await server._shutdown_domains()
        assert server.domains.get_domain_state("engineering")["state"] == "deactivated"
        assert server.domains.list_active_domains() == []
        sdk.disconnect.assert_awaited_once()
    finally:
        release.set()
        await socket.close()
        listener.close()
        await listener.wait_closed()
        await server._shutdown_domains()
        server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_type", [None, "conversation", "unknown", "activate_domain"]
)
async def test_queued_request_after_peer_close_obeys_engine_lifetime(
    mock_engines, request_type
):
    conv, domains = mock_engines
    request = {"agent_id": "test", "task": "hi", "domain_id": "engineering"}
    if request_type is not None:
        request["type"] = request_type

    class ClosedSocket:
        def __aiter__(self):
            return self._iterate()

        async def _iterate(self):
            # Closure can be observed before an already buffered frame is read.
            await asyncio.sleep(0)
            yield json.dumps(request)

        async def wait_closed(self):
            return

        async def send(self, payload):
            pass

    server = BridgeServer()
    try:
        await server._handle_connection(ClosedSocket())
    except asyncio.CancelledError:
        pass
    conv.handle_request.assert_not_awaited()
    if request_type == "activate_domain":
        domains.activate_domain.assert_awaited_once_with("engineering")
    else:
        domains.activate_domain.assert_not_awaited()
