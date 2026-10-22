"""Connection admission and delivery do not own domain execution."""

import asyncio
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.usefixtures("explicit_extras")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "discovery_kind", ["describe_workspace", "agent_status", "project_setup"]
)
async def test_pending_npc_does_not_block_stop_or_discovery(discovery_kind):
    from bridge.connection import ConnectionState

    entered = []
    release = asyncio.Event()
    packets = []

    async def dispatch(raw, histories, *, connection_id, emit):
        entered.append(raw)
        if raw == "npc":
            await release.wait()
        await emit({"type": raw})

    socket = AsyncMock()
    socket.send.side_effect = lambda packet: packets.append(packet)
    state = ConnectionState(socket, dispatch)
    state.submit("npc", {})
    state.submit("stop", {"type": "deactivate_domain"})
    state.submit("discovery", {"type": discovery_kind})
    for _ in range(10):
        await asyncio.sleep(0)
    assert set(entered) == {"npc", "stop", "discovery"}
    assert len(packets) == 2
    await state.close()
    assert not state.histories


@pytest.mark.asyncio
async def test_sender_serializes_and_detaches_slow_socket_without_cancelling_work():
    from bridge.connection import ConnectionState

    socket = AsyncMock()
    entered = asyncio.Event()

    async def send(packet):
        entered.set()
        await asyncio.Future()

    socket.send.side_effect = send
    state = ConnectionState(socket, AsyncMock())
    waiting = asyncio.create_task(state.send({"type": "one"}))
    await entered.wait()
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(waiting, 2.5)
    assert state.closed
    with pytest.raises(ConnectionError):
        await state.send({"type": "two"})
    await state.close()


@pytest.mark.asyncio
async def test_queue_overflow_is_bounded_and_busy_requests_are_correlated():
    from bridge.connection import ConnectionState

    socket = AsyncMock()
    socket.send.side_effect = lambda _: asyncio.sleep(10)
    state = ConnectionState(socket, AsyncMock())
    pending = [asyncio.create_task(state.send({"type": str(i)})) for i in range(34)]
    await asyncio.sleep(0)
    assert state.closed and state._queue.qsize() <= 32
    await state.close()
    await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_new_connection_cannot_steal_domain_output(tmp_path, monkeypatch):
    import json
    import websockets
    from bridge.config import default_config
    from bridge.server import BridgeServer
    from bridge.tests.domain_fakes import FakeOwner, FakeProjectService

    service = FakeProjectService(tmp_path)
    owners = []

    def factory(*args):
        owner = FakeOwner(*args)
        owner.execute_gate = asyncio.Event()
        owners.append(owner)
        return owner

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", factory)
    monkeypatch.setattr("bridge.domain_session.load_agent", lambda _: "definition")
    server = BridgeServer(config=default_config(), project_service=service)
    async with websockets.serve(server._handle_connection, "127.0.0.1", 0) as listener:
        uri = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
        async with websockets.connect(uri) as first:
            await first.send(
                json.dumps(
                    dict(
                        type="activate_domain",
                        domain_id="engineering",
                        request_id="start",
                    )
                )
            )
            assert json.loads(await first.recv())["state"] == "activating"
            active = json.loads(await first.recv())
            generation = active["domain_session_id"]
            command = dict(
                type="domain_query",
                domain_id="engineering",
                domain_session_id=generation,
                agent_id="backend-architect",
                task="work",
                request_id="run",
            )
            await first.send(json.dumps(command))
            assert json.loads(await first.recv())["type"] == "domain_accepted"
            async with websockets.connect(uri) as second:
                await second.send(
                    json.dumps(dict(type="describe_workspace", request_id="observe"))
                )
                assert json.loads(await second.recv())["request_id"] == "observe"
                owners[0].execute_gate.set()
                result = json.loads(await asyncio.wait_for(first.recv(), 3))
                assert (
                    result["type"] == "domain_result" and result["request_id"] == "run"
                )
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(second.recv(), 0.05)
                assert owners[0].lease.held
        assert owners[0].lease.held and not owners[0].stopped.is_set()
        await server._shutdown_domains()
    service.close()


@pytest.mark.asyncio
async def test_stop_and_discovery_preempt_blocked_start_and_npc(tmp_path, monkeypatch):
    import json
    import websockets
    from bridge.config import default_config
    from bridge.server import BridgeServer
    from bridge.tests.domain_fakes import FakeOwner, FakeProjectService

    service = FakeProjectService(tmp_path)
    owners = []

    def factory(*args):
        owner = FakeOwner(*args)
        owner.connect_gate = asyncio.Event()
        owners.append(owner)
        return owner

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", factory)
    server = BridgeServer(config=default_config(), project_service=service)
    npc_entered = asyncio.Event()

    async def npc(*args, **kwargs):
        npc_entered.set()
        await asyncio.Future()

    server.conversation.handle_request = npc
    async with websockets.serve(server._handle_connection, "127.0.0.1", 0) as listener:
        async with websockets.connect(
            f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
        ) as socket:
            await socket.send(
                json.dumps(dict(agent_id="builder", task="talk", request_id="npc"))
            )
            await npc_entered.wait()
            await socket.send(
                json.dumps(
                    dict(
                        type="activate_domain",
                        domain_id="engineering",
                        request_id="start",
                    )
                )
            )
            activating = json.loads(await socket.recv())
            assert activating["state"] == "activating"
            await socket.send(
                json.dumps(dict(type="describe_workspace", request_id="observe"))
            )
            assert json.loads(await socket.recv())["request_id"] == "observe"
            await socket.send(
                json.dumps(
                    dict(type="activate_domain", domain_id="other", request_id="excess")
                )
            )
            busy = json.loads(await socket.recv())
            assert (
                busy["error_type"] == "domain_busy" and busy["request_id"] == "excess"
            )
            assert busy["project_id"] == activating["project_id"]
            assert "workspace_id" not in busy
            await socket.send(
                json.dumps(
                    dict(
                        type="background_domain",
                        domain_id="engineering",
                        domain_session_id=activating["domain_session_id"],
                        request_id="busy-generation",
                    )
                )
            )
            busy_generation = json.loads(await socket.recv())
            assert busy_generation["project_id"] == activating["project_id"]
            assert busy_generation["workspace_id"] == activating["workspace_id"]
            assert (
                busy_generation["domain_session_id"] == activating["domain_session_id"]
            )
            await socket.send(
                json.dumps(
                    dict(
                        type="deactivate_domain",
                        domain_id="engineering",
                        domain_session_id=activating["domain_session_id"],
                        request_id="stop",
                    )
                )
            )
            packets = [
                json.loads(await asyncio.wait_for(socket.recv(), 3)),
                json.loads(await asyncio.wait_for(socket.recv(), 3)),
            ]
            assert any(
                p.get("state") == "inactive" and p["request_id"] == "stop"
                for p in packets
            )
            assert not any(p.get("state") == "active" for p in packets)
            assert owners[0].stopped.is_set() and not owners[0].lease.held
        await server._shutdown_domains()
    service.close()
