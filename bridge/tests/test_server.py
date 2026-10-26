"""Tests for bridge.server — WebSocket routing and backward compat."""

import asyncio
import json

import pytest

pytestmark = pytest.mark.usefixtures("explicit_extras")
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

    from bridge.domain_protocol import (
        validate_domain_command,
        error_packet,
        DomainCommandError,
    )
    from bridge.domain_session import deliver

    domain_mgr = AsyncMock()
    domain_mgr.replies = []

    async def handle(command, *, context, emit):
        try:
            validate_domain_command(command)
        except DomainCommandError:
            await deliver(emit, error_packet(command, "invalid_request"), None, context)
            return
        for packet in domain_mgr.replies:
            await deliver(emit, packet, None, context)

    domain_mgr.handle.side_effect = handle

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
                "domain_session_id": "generation",
                "request_id": "r1",
            }
        )
        domain_mgr.handle.assert_awaited_once()
        assert domain_mgr.handle.call_args.args[0]["type"] == "domain_query"

    async def test_resume_returns_buffered_entries(self, mock_engines):
        _, domain_mgr = mock_engines
        domain_mgr.replies = [
            {
                "agent_id": "a",
                "output": "buffered",
                "status": "success",
                "type": "domain_result",
                "task": "t",
                "output_id": "1",
                "domain_id": "engineering",
                "request_id": "r1",
            },
        ]
        server = BridgeServer()
        resp = await server.dispatch(
            {
                "type": "resume",
                "domain_id": "engineering",
                "domain_session_id": "generation",
                "request_id": "resume",
                "cursor": "0",
            }
        )
        assert len(resp) == 1
        assert resp[0]["output"] == "buffered"
        assert domain_mgr.handle.await_count == 1

    async def test_resume_does_not_implicitly_refocus_a_known_domain(
        self, mock_engines
    ):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        await server.dispatch(
            dict(
                type="resume",
                domain_id="engineering",
                domain_session_id="generation",
                request_id="resume",
                cursor="0",
            )
        )
        domain_mgr.handle.assert_awaited_once()
        assert domain_mgr.handle.call_args.args[0]["type"] == "resume"

    async def test_activate_domain_dispatch(self, mock_engines):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        resp = await server.dispatch(
            {"type": "activate_domain", "domain_id": "engineering"}
        )
        domain_mgr.handle.assert_awaited_once()
        assert domain_mgr.handle.call_args.args[0]["type"] == "activate_domain"

    async def test_background_domain_dispatch(self, mock_engines):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        resp = await server.dispatch(
            {"type": "background_domain", "domain_id": "engineering"}
        )
        domain_mgr.handle.assert_awaited_once()
        assert domain_mgr.handle.call_args.args[0]["type"] == "background_domain"

    async def test_refocus_domain_dispatch(self, mock_engines):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        resp = await server.dispatch(
            {"type": "refocus_domain", "domain_id": "engineering"}
        )
        domain_mgr.handle.assert_awaited_once()
        assert domain_mgr.handle.call_args.args[0]["type"] == "refocus_domain"

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

        async def handle(request, history=None, *, metadata=None, context_packet=None):
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
                    count = len(self.sent)
                    yield message
                    while len(self.sent) == count:
                        await asyncio.sleep(0)
                    await asyncio.sleep(0)

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
            conv.handle_request.assert_not_called()
        assert histories == {}

    async def test_json_that_is_no_object_is_an_error_not_a_crash(self, mock_engines):
        server = BridgeServer()
        resp = await server.dispatch_raw("[1, 2]")
        assert resp[0]["error_type"] == "invalid_request"


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown", [False, True])
async def test_domain_activation_survives_peer_close(
    tmp_path, monkeypatch, runtime_config, shutdown
):
    import websockets
    from bridge.tests.domain_fakes import FakeOwner, FakeProjectService

    service = FakeProjectService(tmp_path)
    owner = FakeOwner(runtime_config, service.workspace, None, service.readiness)
    owner.connect_gate = asyncio.Event()

    def factory(config, workspace, lease, readiness):
        owner.lease = lease
        return owner

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", factory)
    server = BridgeServer(config=runtime_config, project_service=service)
    listener = await websockets.serve(server._handle_connection, "127.0.0.1", 0)
    socket = await websockets.connect(
        f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
    )
    try:
        await socket.send(
            json.dumps(
                dict(
                    type="activate_domain", domain_id="engineering", request_id="start"
                )
            )
        )
        packet = json.loads(await asyncio.wait_for(socket.recv(), 3))
        assert packet["state"] == "activating"
        await asyncio.wait_for(owner.started.wait(), 3)
        session = server.domains._sessions["engineering"][-1]
        if shutdown:
            listener.close()
        await socket.close()
        listener.close()
        await listener.wait_closed()
        assert owner.lease.held and not owner.stopped.is_set()
        owner.connect_gate.set()
        await session.start()
        assert session.snapshot()["state"] == "active"
        await server._shutdown_domains()
        assert session.snapshot()["state"] == "inactive"
        assert owner.stopped.is_set() and not owner.lease.held
    finally:
        owner.connect_gate.set()
        await socket.close()
        listener.close()
        await listener.wait_closed()
        await server._shutdown_domains()
        if server.application_state is not None:
            await server.application_state.close()
        service.close()
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
    await asyncio.gather(*tuple(server._connection_tasks))
    conv.handle_request.assert_not_awaited()
    if request_type == "activate_domain":
        domains.handle.assert_awaited_once()
    else:
        domains.handle.assert_not_awaited()
