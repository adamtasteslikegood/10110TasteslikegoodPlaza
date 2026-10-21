"""M10 runtime boundaries: settings, ownership, correlation, and safe shutdown."""

import asyncio
from dataclasses import replace
import gc
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
import pytest_asyncio

from bridge.domain_sdk import SDKOutcome, domain_options
from bridge.tests.domain_fakes import (
    FakeProjectService,
    FakeOwner,
    context,
    query,
    collect_until,
)

from bridge.config import ConfigError, default_config
from bridge.conversation import ConversationEngine
from bridge.domain_manager import DomainManager
from bridge.domain_session import DomainSession
from bridge.observability import RequestContext
from bridge.server import BridgeServer
import bridge.server as server_module


def messages(writer):
    return [r for kind, r, _ in writer.records if kind == "transcript"]


def events(writer, name):
    return [
        r for kind, r, _ in writer.records if kind == "event" and r["event"] == name
    ]


def origin(session):
    return RequestContext(
        "old-connection",
        "origin-request",
        "agent",
        "domain",
        session.model,
        session.domain_id,
    )


@pytest.mark.parametrize("tier", ["haiku", "sonnet"])
@pytest.mark.asyncio
async def test_conversation_uses_snapshot_bounds_and_tier(
    tier, runtime_config, offline_clients, monkeypatch
):
    client, _, _ = offline_clients
    config = replace(
        runtime_config,
        conversation_tier=tier,
        conversation_timeout_seconds=7,
        conversation_max_output_tokens=93,
        context_max_messages=2,
    )
    from bridge import conversation_sdk

    deadline = MagicMock(wraps=conversation_sdk.anyio.fail_after)
    monkeypatch.setattr(conversation_sdk.anyio, "fail_after", deadline)
    engine = ConversationEngine(config=config)
    monkeypatch.setenv("PLAZA_CONVERSATION_TIER", "bad-new-value")
    config.source_path.write_text("invalid after construction")
    history = []
    for _ in range(3):
        await engine.handle_request({"agent_id": "agent", "task": "question"}, history)
    kwargs = client.reply.call_args.kwargs
    assert kwargs["model"] == config.model_for(tier) == engine.model
    assert deadline.call_args.args == (7,)
    assert kwargs["max_output_tokens"] == 93
    assert len(history) == 2
    assert len(kwargs["messages"]) == 3
    with pytest.raises(AttributeError):
        engine.model = "new"


@pytest.mark.asyncio
async def test_explicit_conversation_overrides_win(runtime_config, offline_clients):
    backend = AsyncMock(complete=AsyncMock(return_value="explicit reply"))
    engine = ConversationEngine(backend, "explicit", 12, config=runtime_config)
    await engine.handle_request({"agent_id": "agent", "task": "question"})
    assert engine.model == "explicit"
    assert backend.complete.call_args.kwargs["timeout"] == 12
    assert backend.complete.call_args.kwargs["model"] == "explicit"


def test_runtime_compatibility_constants_follow_central_defaults(offline_clients):
    from bridge.conversation import DEFAULT_MODEL

    config = default_config()
    assert DEFAULT_MODEL == config.haiku_model == "claude-haiku-5-5"
    assert config.model_for(config.domain_tier) == "claude-sonnet-5-5"
    assert ConversationEngine().model == config.model_for(config.conversation_tier)


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["haiku", "sonnet"])
async def test_domain_uses_snapshot_caps(
    tier, domain_runtime, runtime_config, monkeypatch
):
    _, session, owner, _, _ = domain_runtime
    config = replace(
        runtime_config, domain_tier=tier, domain_max_turns=3, domain_max_budget_usd=0.23
    )
    session._config = config
    monkeypatch.setenv("PLAZA_DOMAIN_TIER", "bad")
    config.source_path.write_text("invalid")
    options = domain_options(config, owner.workspace, lambda *a: None)
    assert options.model == session.model == config.model_for(tier)
    assert options.max_turns == 3 and options.max_budget_usd == 0.23
    with pytest.raises(AttributeError):
        session.model = "new"


@pytest.mark.asyncio
async def test_conversation_recorded_with_duration_and_same_wire_id(
    runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    server = BridgeServer(config=runtime_config, recorder=recorder)
    response = await server.dispatch(
        {"agent_id": "agent", "task": "question", "request_id": "client-id"},
        connection_id="socket",
    )
    assert response == [
        {
            "agent_id": "agent",
            "task": "question",
            "output": "conversation reply",
            "status": "ok",
            "request_id": "client-id",
        }
    ]
    records = messages(writer)
    assert [(r["role"], r["outcome"]) for r in records] == [
        ("user", "input"),
        ("assistant", "success"),
    ]
    assert all(
        r["request_id"] == "client-id" and r["connection_id"] == "socket"
        for r in records
    )
    assert "provider_session_id" not in records[0]
    assert records[-1]["provider_session_id"] == "observed-npc-session"
    assert events(writer, "request_received")
    assert events(writer, "engine_routing")
    assert events(writer, "request_completed")[0]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_conversation_failure_metadata_is_category_only(
    runtime_config, runtime_archive, offline_clients, capsys
):
    recorder, writer = runtime_archive
    client, _, _ = offline_clients
    client.reply.side_effect = RuntimeError("credential-sentinel private-body")
    server = BridgeServer(config=runtime_config, recorder=recorder)
    response = await server.dispatch({"agent_id": "agent", "task": "question"})
    assert response[0]["message"] == "credential-sentinel private-body"
    assert [(r["role"], r["outcome"]) for r in messages(writer)] == [
        ("user", "input"),
        ("error", "failure"),
    ]
    metadata = json.dumps([r for kind, r, _ in writer.records if kind == "event"])
    assert "private-body" not in metadata + capsys.readouterr().err
    assert "credential-sentinel" not in json.dumps(writer.records)
    assert events(writer, "request_failed")[0]["outcome"] == "failure"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        "{oops",
        "[]",
        '{"agent_id":"../bad","task":"private"}',
        '{"type":"domain_query","domain_id":"d",'
        '"agent_id":"../bad","task":"private"}',
    ],
)
async def test_rejected_requests_never_make_transcripts(
    raw, runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    server = BridgeServer(config=runtime_config, recorder=recorder)
    response = await server.dispatch_raw(raw, connection_id="socket")
    assert response[0]["status"] == "error"
    assert not messages(writer)
    rejected = events(writer, "request_rejected")
    assert len(rejected) == 1
    uuid.UUID(rejected[0]["request_id"])
    assert "private" not in json.dumps(writer.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", [None, 8, [], "", "   "])
async def test_unusable_request_id_gets_internal_uuid(
    request_id, runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    server = BridgeServer(config=runtime_config, recorder=recorder)
    await server.dispatch(
        {"agent_id": "agent", "task": "question", "request_id": request_id}
    )
    records = messages(writer)
    assert len({r["request_id"] for r in records}) == 1
    uuid.UUID(records[0]["request_id"])


@pytest.mark.asyncio
async def test_connection_uuid_stays_per_socket(
    runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    server = BridgeServer(config=runtime_config, recorder=recorder)

    class Socket:
        def __init__(self):
            self.sent = asyncio.Event()

        def __aiter__(self):
            return self.read()

        async def read(self):
            for _ in range(2):
                self.sent.clear()
                yield '{"agent_id":"agent","task":"hi"}'
                await self.sent.wait()
                await asyncio.sleep(0)

        async def wait_closed(self):
            await asyncio.Future()

        async def send(self, value):
            self.sent.set()

    await server._handle_connection(Socket())
    await server._handle_connection(Socket())
    opened = events(writer, "connection_opened")
    closed = events(writer, "connection_closed")
    ids = [r["connection_id"] for r in opened]
    assert len(set(ids)) == 2
    for value in ids:
        uuid.UUID(value)
    assert ids == [r["connection_id"] for r in closed]
    assert [r["connection_id"] for r in messages(writer)] == [ids[0]] * 4 + [ids[1]] * 4


@pytest.mark.asyncio
async def test_late_domain_execution_keeps_origin_and_resume_does_not_record(
    domain_runtime, runtime_archive
):
    manager, session, owner, packets, emit = domain_runtime
    _, writer = runtime_archive
    owner.execute_gate = asyncio.Event()
    await submit_runtime(domain_runtime)
    await owner.executing.wait()
    assert len(messages(writer)) == 1
    other_packets = []

    async def other(packet):
        other_packets.append(packet)

    await manager.handle(
        dict(type="domain_status", domain_id="engineering", request_id="later"),
        context=context("later", "new-connection"),
        emit=other,
    )
    owner.execute_gate.set()
    await finish_runtime(domain_runtime)
    records = messages(writer)
    assert [(r["role"], r["outcome"]) for r in records] == [
        ("user", "input"),
        ("assistant", "success"),
    ]
    assert all(
        r["connection_id"] == "old-connection" and r["request_id"] == "origin-request"
        for r in records
    )
    assert (
        records[-1]["output_id"] == "1"
        and records[-1]["provider_session_id"] == "provider"
    )
    assert not any(p["type"] == "domain_result" for p in other_packets)
    for _ in range(2):
        await manager.handle(
            dict(
                type="resume",
                domain_id="engineering",
                domain_session_id=session.domain_session_id,
                request_id="replay",
                cursor="0",
            ),
            context=context("replay", "new-connection"),
            emit=other,
        )
    assert len(messages(writer)) == 2 and len(owner.calls) == 1
    assert other_packets[-2]["request_id"] == "origin-request"
    assert other_packets[-1]["request_id"] == "replay"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["error", "cancelled"])
async def test_domain_execution_failure_recorded_once_as_terminal(
    status, domain_runtime, runtime_archive, capsys
):
    _, session, owner, _, _ = domain_runtime
    _, writer = runtime_archive
    owner.outcome = SDKOutcome(
        "partial",
        status,
        "stopped" if status == "cancelled" else "transport_error",
        "provider",
        None,
    )
    await submit_runtime(domain_runtime)
    await finish_runtime(domain_runtime)
    outcome = "cancelled" if status == "cancelled" else "failure"
    assert [(r["role"], r["outcome"]) for r in messages(writer)] == [
        ("user", "input"),
        ("error", outcome),
    ]
    assert session.replay(0)[0]["status"] == status
    assert "private-body" not in json.dumps(writer.records) + capsys.readouterr().err


@pytest.mark.asyncio
async def test_detached_failure_never_reaches_asyncio_exception_logger(
    domain_runtime, runtime_archive, caplog
):
    _, session, owner, _, _ = domain_runtime
    _, writer = runtime_archive

    async def failure(**kwargs):
        raise RuntimeError("credential-sentinel private-body")

    owner.execute = failure
    loop = asyncio.get_running_loop()
    reports, previous = [], loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: reports.append(context))
    try:
        await submit_runtime(domain_runtime)
        await finish_runtime(domain_runtime)
        gc.collect()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous)
    assert reports == [] and "credential-sentinel" not in caplog.text
    assert len(messages(writer)) == 2
    assert session.replay(0)[0]["status"] == "error"


@pytest.mark.asyncio
async def test_delivery_failure_is_separate_from_successful_execution(
    domain_runtime, runtime_archive
):
    _, session, _, _, _ = domain_runtime
    _, writer = runtime_archive

    async def broken(packet):
        raise RuntimeError("credential-sentinel private-body")

    await submit_runtime(domain_runtime, emit=broken)
    async with asyncio.timeout(3):
        while len(session.replay(0)) == 1:
            await asyncio.sleep(0.001)
    assert [r["outcome"] for r in messages(writer)] == ["input", "success"]
    assert events(writer, "delivery_failed") and not events(writer, "request_failed")
    assert session.replay(0)[0]["status"] == "success"


@pytest.mark.asyncio
async def test_no_fabricated_provider_session_id(domain_runtime, runtime_archive):
    _, _, owner, _, _ = domain_runtime
    _, writer = runtime_archive
    owner.outcome = replace(owner.outcome, provider_session_id=None)
    await submit_runtime(domain_runtime)
    await finish_runtime(domain_runtime)
    assert all("provider_session_id" not in r for r in messages(writer))


@pytest.mark.asyncio
async def test_deactivation_records_cancellation_before_return(
    domain_runtime, runtime_archive
):
    _, session, owner, _, _ = domain_runtime
    _, writer = runtime_archive
    owner.execute_gate = asyncio.Event()
    await submit_runtime(domain_runtime)
    await owner.executing.wait()
    await session.stop()
    assert messages(writer)[-1]["outcome"] == "cancelled"
    assert events(writer, "domain_transition")[-1]["domain_state"] == "inactive"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "cancel", "bind_failure"])
async def test_serve_lifecycle_releases_recorder_with_truthful_clean_status(
    mode, runtime_config, runtime_archive, offline_clients, monkeypatch, capsys
):
    recorder, writer = runtime_archive

    class Listener:
        async def __aenter__(self):
            if mode == "bind_failure":
                raise OSError("bind failed")

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(
        server_module.websockets, "serve", lambda *args, **kwargs: Listener()
    )
    server = BridgeServer(config=runtime_config, recorder=recorder)
    stopped = asyncio.Event()
    stopped.set()
    if mode == "normal":
        await server.serve(stop_event=stopped)
    elif mode == "cancel":
        task = asyncio.create_task(server.serve())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(OSError):
            await server.serve()
    server.close()
    assert writer.closed == [mode == "normal"]
    assert len(events(writer, "bridge_stopped")) == 1
    assert bool(events(writer, "bridge_started")) == (mode != "bind_failure")
    assert ("Bridge running on ws://localhost:8765" in capsys.readouterr().err) == (
        mode != "bind_failure"
    )


@pytest.mark.asyncio
async def test_composition_loads_once_injects_same_snapshot_and_closes_on_failure(
    runtime_config, monkeypatch
):
    recorder = MagicMock()
    constructed = []
    load = MagicMock(return_value=runtime_config)
    make_recorder = MagicMock(return_value=recorder)

    class Server:
        def __init__(self, base_path=None, *, config, recorder):
            constructed.append((base_path, config, recorder))
            raise RuntimeError("construction failure")

    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "credential-sentinel")
    monkeypatch.setenv("UNRELATED_SECRET", "unrelated")
    monkeypatch.setattr(server_module, "load_config", load, raising=False)
    monkeypatch.setattr(server_module, "BridgeRecorder", make_recorder, raising=False)
    monkeypatch.setattr(server_module, "BridgeServer", Server)
    with pytest.raises(RuntimeError):
        await server_module.serve()
    load.assert_called_once_with()
    assert constructed == [(None, runtime_config, recorder)]
    assert "credential-sentinel" in make_recorder.call_args.kwargs["redactions"]
    assert "unrelated" not in make_recorder.call_args.kwargs["redactions"]
    recorder.close.assert_called_once_with(clean=False)


@pytest.mark.asyncio
async def test_bad_startup_config_prevents_clients_and_bind(monkeypatch, capsys):
    load = MagicMock(side_effect=ConfigError("CONTEXT_MAX_MESSAGES must be even"))
    server = MagicMock()
    monkeypatch.setattr(server_module, "load_config", load, raising=False)
    monkeypatch.setattr(server_module, "BridgeServer", server)
    with pytest.raises(SystemExit) as error:
        await server_module.serve()
    assert error.value.code == 2
    server.assert_not_called()
    assert "CONTEXT_MAX_MESSAGES" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_domain_requires_client_id_and_preserves_buffered_wire_identity(
    domain_runtime, runtime_archive
):
    manager, session, owner, packets, emit = domain_runtime
    _, writer = runtime_archive
    command = query(generation=session.domain_session_id)
    del command["request_id"]
    await manager.handle(command, context=context(), emit=emit)
    assert packets[-1]["error_type"] == "invalid_request"
    assert "request_id" not in packets[-1] and not owner.calls
    await submit_runtime(domain_runtime)
    await finish_runtime(domain_runtime)
    assert {r["request_id"] for r in messages(writer)} == {
        session.replay(0)[0]["request_id"]
    }


def test_isolated_construction_uses_no_file_env_or_disk_recorder(
    monkeypatch, offline_clients
):
    def forbidden(*args, **kwargs):
        raise AssertionError("isolated construction must not load config or open logs")

    monkeypatch.setenv("PLAZA_CONVERSATION_TIER", "invalid")
    monkeypatch.setenv("BRIDGE_CONFIG_PATH", "/missing/config.json")
    monkeypatch.setattr(server_module, "load_config", forbidden)
    monkeypatch.setattr(server_module, "BridgeRecorder", forbidden)
    server = BridgeServer()
    assert server.conversation.model == default_config().haiku_model
    assert server._recorder is None
    assert server.domains._recorder is None
    server.close()


@pytest.mark.asyncio
async def test_shutdown_failure_still_releases_writer_unclean(
    runtime_config, runtime_archive, offline_clients, monkeypatch
):
    recorder, writer = runtime_archive

    class Listener:
        async def __aenter__(self):
            pass

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(
        server_module.websockets, "serve", lambda *args, **kwargs: Listener()
    )
    server = BridgeServer(config=runtime_config, recorder=recorder)
    server._shutdown_domains = AsyncMock(side_effect=RuntimeError("disconnect failed"))
    stopped = asyncio.Event()
    stopped.set()
    with pytest.raises(RuntimeError):
        await server.serve(stop_event=stopped)
    assert writer.closed == [False]


@pytest.mark.asyncio
async def test_sdk_reported_error_keeps_existing_buffer_and_wire_output(
    domain_runtime, runtime_archive
):
    _, session, owner, _, _ = domain_runtime
    _, writer = runtime_archive
    owner.outcome = SDKOutcome(
        "partial output", "error", "error_max_turns", "provider-error-session", None
    )
    await submit_runtime(domain_runtime)
    await finish_runtime(domain_runtime)
    assert session.replay(0)[0]["output"] == "partial output"
    assert [(r["role"], r["outcome"]) for r in messages(writer)] == [
        ("user", "input"),
        ("error", "failure"),
    ]
    assert messages(writer)[-1]["provider_session_id"] == "provider-error-session"
    assert len(events(writer, "request_failed")) == 1


@pytest.mark.asyncio
async def test_domain_lifecycle_diagnostics_cover_all_transitions(
    domain_runtime, runtime_archive
):
    _, session, _, _, _ = domain_runtime
    _, writer = runtime_archive
    session.background()
    session.refocus()
    await session.stop()
    assert [r["domain_state"] for r in events(writer, "domain_transition")] == [
        "activating",
        "active",
        "background",
        "active",
        "stopping",
        "inactive",
    ]


@pytest.fixture
def bound_runtime_listener(monkeypatch):
    class Listener:
        async def __aenter__(self):
            pass

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(
        server_module.websockets, "serve", lambda *args, **kwargs: Listener()
    )


@pytest.mark.asyncio
async def test_deactivate_preserves_caller_cancel_during_child_cleanup(
    domain_runtime, runtime_archive
):
    _, session, owner, _, _ = domain_runtime
    _, writer = runtime_archive
    owner.execute_gate, owner.stop_gate = asyncio.Event(), asyncio.Event()
    await submit_runtime(domain_runtime)
    await owner.executing.wait()
    stop = asyncio.create_task(session.stop())
    await owner.stopped.wait()
    stop.cancel("caller-stop")
    await asyncio.sleep(0)
    assert not stop.done() and owner.lease.held
    owner.stop_gate.set()
    with pytest.raises(asyncio.CancelledError) as error:
        await stop
    assert error.value.args == ("caller-stop",)
    assert [r["outcome"] for r in messages(writer)] == ["input", "cancelled"]
    assert session.state.value == "inactive" and not owner.lease.held


@pytest.mark.asyncio
async def test_stop_event_shutdown_cancel_during_child_cleanup_is_unclean(
    server_runtime, runtime_archive, bound_runtime_listener
):
    server, session, owner = server_runtime
    _, writer = runtime_archive
    owner.execute_gate = asyncio.Event()
    owner.stop_gate = asyncio.Event()
    await server.dispatch(query("origin-request", session.domain_session_id))
    await owner.executing.wait()
    stopped = asyncio.Event()
    stopped.set()
    serving = asyncio.create_task(server.serve(stop_event=stopped))
    await owner.stopped.wait()
    serving.cancel("shutdown-stop")
    await asyncio.sleep(0)
    assert not serving.done() and writer.closed == []
    owner.stop_gate.set()
    with pytest.raises(asyncio.CancelledError):
        await serving
    assert writer.closed == [False]
    assert messages(writer)[-1]["outcome"] == "cancelled"
    assert owner.stopped.is_set() and not owner.lease.held


@pytest.mark.asyncio
async def test_immediate_submit_deactivate_archives_origin_once_before_sdk_start(
    domain_runtime, runtime_archive
):
    manager, session, owner, packets, emit = domain_runtime
    _, writer = runtime_archive
    stop_tasks = []

    async def stopping_sink(packet):
        packets.append(packet)
        if packet["type"] == "domain_accepted":
            stop_tasks.append(asyncio.create_task(session.stop()))
            await asyncio.sleep(0)

    await submit_runtime(domain_runtime, emit=stopping_sink)
    await stop_tasks[0]
    assert [(r["role"], r["outcome"]) for r in messages(writer)] == [
        ("user", "input"),
        ("error", "cancelled"),
    ]
    assert all(
        r["connection_id"] == "old-connection" and r["request_id"] == "origin-request"
        for r in messages(writer)
    )
    assert len(events(writer, "request_cancelled")) == 1 and not owner.calls
    assert session.replay(0)[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_shutdown_attempts_all_domains_and_records_before_close_after_disconnect_error(
    server_runtime, runtime_archive, bound_runtime_listener, tmp_path
):
    # Defensive shutdown drains all registered generations, including a failed
    # owner and a separately prepared generation. Normal admission uses one slot.
    from bridge.domain_protocol import DomainCommandError

    server, first_session, first = server_runtime
    recorder, writer = runtime_archive
    extra_root = tmp_path / "extra"
    extra_root.mkdir()
    extra = FakeProjectService(extra_root)
    second_session = DomainSession(
        "second",
        "second-generation",
        config=server._config,
        project_service=extra,
        recorder=recorder,
    )
    await second_session.start()
    second = second_session._owner
    server.domains._sessions["second"] = [second_session]
    first.execute_gate = second.execute_gate = asyncio.Event()
    first.clean = False
    packets = []

    async def sink(packet):
        packets.append(packet)

    for session in (first_session, second_session):
        await session.admit_query(
            query(
                "origin-request", session.domain_session_id, domain_id=session.domain_id
            ),
            context=origin(session),
            emit=sink,
        )
        await session._owner.executing.wait()
    close_snapshot = []
    original_close = writer.close

    def close(*, clean=True):
        close_snapshot.extend(messages(writer))
        original_close(clean=clean)

    writer.close = close
    stopped = asyncio.Event()
    stopped.set()
    try:
        with pytest.raises(DomainCommandError, match="Cleanup"):
            await server.serve(stop_event=stopped)
        assert first.stopped.is_set() and second.stopped.is_set()
        assert second_session.state.value == "inactive"
        assert sorted((r["domain_id"], r["outcome"]) for r in close_snapshot) == sorted(
            [
                ("engineering", "input"),
                ("second", "input"),
                ("engineering", "cancelled"),
                ("second", "cancelled"),
            ]
        )
        assert writer.closed == [False]
        assert "credential-sentinel" not in json.dumps(writer.records)
    finally:
        first.clean = True
        await first_session.stop()
        extra.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("primary", ["cancel", "bind_error"])
async def test_primary_serve_failure_survives_disconnect_failure(
    primary, server_runtime, runtime_archive, monkeypatch
):
    server, session, owner = server_runtime
    _, writer = runtime_archive
    bind_error = OSError("initial bind error")

    class Listener:
        async def __aenter__(self):
            if primary == "bind_error":
                raise bind_error

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(
        server_module.websockets, "serve", lambda *args, **kwargs: Listener()
    )
    owner.clean = False
    if primary == "cancel":
        serving = asyncio.create_task(server.serve())
        await asyncio.sleep(0)
        serving.cancel("primary cancellation")
        with pytest.raises(asyncio.CancelledError) as error:
            await serving
        assert error.value.args == ("primary cancellation",)
    else:
        with pytest.raises(OSError) as error:
            await server.serve()
        assert error.value is bind_error
    assert owner.stopped.is_set()
    assert writer.closed == [False]


@pytest_asyncio.fixture
async def domain_runtime(tmp_path, runtime_config, runtime_archive, monkeypatch):
    service = FakeProjectService(tmp_path)
    owners = []

    def factory(*args):
        owner = FakeOwner(*args)
        owners.append(owner)
        return owner

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", factory)
    monkeypatch.setattr("bridge.domain_session.load_agent", lambda _: "definition")
    recorder, writer = runtime_archive
    manager = DomainManager(runtime_config, service, recorder=recorder)
    packets = []

    async def emit(packet):
        packets.append(packet)

    await manager.handle(
        dict(type="activate_domain", request_id="start", domain_id="engineering"),
        context=context("start"),
        emit=emit,
    )
    session = manager._sessions["engineering"][-1]
    yield manager, session, owners[0], packets, emit
    owners[0].clean = True
    if owners[0].stop_gate:
        owners[0].stop_gate.set()
    await manager.shutdown()
    service.close()


async def submit_runtime(runtime, request="origin-request", emit=None):
    manager, session, owner, packets, sink = runtime
    await manager.handle(
        query(request, session.domain_session_id),
        context=context(request, "old-connection"),
        emit=emit or sink,
    )


async def finish_runtime(runtime):
    _, session, _, packets, _ = runtime
    await collect_until(session, packets)


@pytest_asyncio.fixture
async def server_runtime(tmp_path, runtime_config, runtime_archive, monkeypatch):
    from bridge.project_service import ProjectService
    from bridge.tests.test_workspace import repository

    config = replace(runtime_config, workspace_root_dir=repository(tmp_path))
    service = ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="server-test-run"
    )
    await service.start()
    await service._bootstrap_task
    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", FakeOwner)
    monkeypatch.setattr("bridge.domain_session.load_agent", lambda _: "definition")
    server = BridgeServer(
        config=config, project_service=service, recorder=runtime_archive[0]
    )
    await server.dispatch(
        dict(type="activate_domain", domain_id="engineering", request_id="start")
    )
    session = server.domains._sessions["engineering"][-1]
    owner = session._owner
    yield server, session, owner
    owner.clean = True
    if owner.stop_gate:
        owner.stop_gate.set()
    await server._shutdown_domains()
    await service.close()
    server.close()


@pytest.mark.asyncio
async def test_shutdown_drains_domains_before_npc_and_project_detach(
    runtime_config, monkeypatch
):
    import websockets

    order = []
    entered = asyncio.Event()
    ready = asyncio.Event()
    listeners = []
    actual = websockets.serve

    def listen(handler, host, port, **kwargs):
        result = actual(handler, "127.0.0.1", 0, **kwargs)
        listeners.append(result)
        return result

    monkeypatch.setattr(server_module.websockets, "serve", listen)
    server = BridgeServer(config=runtime_config)
    original_event = server._event

    def event(name, *args, **kwargs):
        original_event(name, *args, **kwargs)
        if name == "bridge_started":
            ready.set()
        if name == "bridge_stopped":
            order.append("recorder")

    server._event = event

    async def conversation(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            order.append("npc")

    server.conversation.handle_request = conversation

    async def domains():
        order.append("domains")

    async def project():
        order.append("detach")

    server._shutdown_domains = domains
    server.project.close = project
    stop = asyncio.Event()
    serving = asyncio.create_task(server.serve(stop_event=stop))
    await ready.wait()
    socket = await websockets.connect(
        f"ws://127.0.0.1:{listeners[0].server.sockets[0].getsockname()[1]}"
    )
    await socket.send(json.dumps(dict(agent_id="builder", task="work")))
    await entered.wait()
    stop.set()
    await serving
    await socket.close()
    assert order == ["domains", "npc", "detach", "recorder"]


@pytest.mark.asyncio
async def test_emitted_domain_rejection_records_failure_without_duplicate_delivery(
    runtime_config, runtime_archive
):
    recorder, writer = runtime_archive
    server = BridgeServer(config=runtime_config, recorder=recorder)
    packets = []

    async def emit(packet):
        packets.append(packet)

    response = await server.dispatch(
        dict(
            type="activate_domain", domain_id="engineering", request_id="rejected-start"
        ),
        connection_id="connection",
        emit=emit,
    )
    assert response == [] and len(packets) == 1
    assert packets[0]["error_type"] == "workspace_unconfigured"
    failures = events(writer, "request_failed")
    assert len(failures) == 1 and failures[0]["request_id"] == "rejected-start"
    assert not events(writer, "request_completed")
    await server._shutdown_domains()
