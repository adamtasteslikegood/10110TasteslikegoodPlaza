"""M10 runtime boundaries: settings, ownership, correlation, and safe shutdown."""

import asyncio
from dataclasses import replace
import gc
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

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
    from bridge.domain_session import DEFAULT_DOMAIN_MODEL

    config = default_config()
    assert DEFAULT_MODEL == config.haiku_model == "claude-haiku-5-5"
    assert DEFAULT_DOMAIN_MODEL == config.sonnet_model == "claude-sonnet-5-5"
    assert ConversationEngine().model == config.model_for(config.conversation_tier)
    assert DomainSession("domain").model == config.model_for(config.domain_tier)


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["haiku", "sonnet"])
async def test_domain_uses_snapshot_caps(
    tier, runtime_config, offline_clients, monkeypatch
):
    _, _, sdk_class = offline_clients
    config = replace(
        runtime_config, domain_tier=tier, domain_max_turns=3, domain_max_budget_usd=0.23
    )
    manager = DomainManager(config=config)
    monkeypatch.setenv("PLAZA_DOMAIN_TIER", "bad")
    config.source_path.write_text("invalid")
    await manager.activate_domain("domain")
    session = manager._sessions["domain"]
    options = sdk_class.call_args.kwargs["options"]
    assert options.model == session.model == config.model_for(tier)
    assert options.max_turns == 3
    assert options.max_budget_usd == 0.23
    with pytest.raises(AttributeError):
        session.model = "new"
    await session.deactivate()


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
        def __aiter__(self):
            return self.read()

        async def read(self):
            for _ in range(2):
                yield '{"agent_id":"agent","task":"hi"}'

        async def wait_closed(self):
            await asyncio.Future()

        async def send(self, value):
            pass

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
    runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    _, sdk, _ = offline_clients
    gate = asyncio.Event()

    async def query(_):
        await gate.wait()

    sdk.query.side_effect = query
    server = BridgeServer(config=runtime_config, recorder=recorder)
    await server.dispatch({"type": "activate_domain", "domain_id": "domain"})
    await server.dispatch(
        {
            "type": "domain_query",
            "domain_id": "domain",
            "agent_id": "agent",
            "task": "original",
            "request_id": "origin-request",
        },
        connection_id="old-connection",
    )
    session = server.domains._sessions["domain"]
    await asyncio.sleep(0)
    assert len(messages(writer)) == 1
    await server.dispatch(
        {"agent_id": "agent", "task": "later"}, connection_id="new-connection"
    )
    gate.set()
    await session._active_task
    domain_records = [r for r in messages(writer) if r["engine"] == "domain"]
    assert [(r["role"], r["outcome"]) for r in domain_records] == [
        ("user", "input"),
        ("assistant", "success"),
    ]
    assert all(
        r["connection_id"] == "old-connection" and r["request_id"] == "origin-request"
        for r in domain_records
    )
    assert domain_records[-1]["output_id"] == "0"
    assert domain_records[-1]["provider_session_id"] == "observed-provider-session"
    count = len(messages(writer))
    for _ in range(2):
        response = await server.dispatch({"type": "resume", "domain_id": "domain"})
        assert response[0]["output"] == "domain reply"
    assert len(messages(writer)) == count
    transitions = [r["domain_state"] for r in events(writer, "domain_transition")]
    assert transitions[:2] == ["activating", "active"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [RuntimeError("credential-sentinel private-body"), asyncio.CancelledError()],
)
async def test_domain_execution_failure_recorded_once_and_reraised(
    failure, runtime_config, runtime_archive, offline_clients, capsys
):
    recorder, writer = runtime_archive
    _, sdk, _ = offline_clients
    sdk.query.side_effect = failure
    session = DomainSession("domain", config=runtime_config, recorder=recorder)
    await session.activate()
    await session.submit_query(
        "agent", "task", "origin-request", context=origin(session)
    )
    with pytest.raises(type(failure)):
        await session._active_task
    records = messages(writer)
    outcome = "cancelled" if isinstance(failure, asyncio.CancelledError) else "failure"
    assert [(r["role"], r["outcome"]) for r in records] == [
        ("user", "input"),
        ("error", outcome),
    ]
    assert records[-1]["content"] in ("cancelled", "sdk_error")
    assert session.buffer.latest_id == -1
    assert "private-body" not in json.dumps(writer.records) + capsys.readouterr().err


@pytest.mark.asyncio
async def test_detached_failure_never_reaches_asyncio_exception_logger(
    runtime_config, runtime_archive, offline_clients, caplog
):
    recorder, writer = runtime_archive
    _, sdk, _ = offline_clients
    sdk.query.side_effect = RuntimeError("credential-sentinel private-body")
    session = DomainSession("domain", config=runtime_config, recorder=recorder)
    await session.activate()
    loop = asyncio.get_running_loop()
    reports = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: reports.append(context))
    try:
        await session.submit_query(
            "agent", "task", "origin-request", context=origin(session)
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        session._active_task = None  # abandon the task without awaiting its exception
        gc.collect()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous)
    assert reports == []
    assert "credential-sentinel" not in caplog.text
    assert len(messages(writer)) == 2


@pytest.mark.asyncio
async def test_delivery_failure_is_separate_from_successful_execution(
    runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    session = DomainSession("domain", config=runtime_config, recorder=recorder)
    await session.activate()
    callback = AsyncMock(side_effect=RuntimeError("credential-sentinel private-body"))
    await session.submit_query("agent", "task", "r", callback, context=origin(session))
    with pytest.raises(RuntimeError):
        await session._active_task
    assert [r["outcome"] for r in messages(writer)] == ["input", "success"]
    assert events(writer, "delivery_failed")
    assert not events(writer, "request_failed")
    assert session.buffer.latest_id == 0


@pytest.mark.asyncio
async def test_no_fabricated_provider_session_id(
    runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    _, sdk, _ = offline_clients

    async def receive():
        yield SimpleNamespace(content=[SimpleNamespace(text="reply")])

    sdk.receive_response = receive
    session = DomainSession("domain", config=runtime_config, recorder=recorder)
    await session.activate()
    await session.submit_query("agent", "task", "r", context=origin(session))
    await session._active_task
    assert all("provider_session_id" not in r for r in messages(writer))


@pytest.mark.asyncio
async def test_deactivation_records_cancellation_before_return(
    runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    _, sdk, _ = offline_clients
    entered = asyncio.Event()

    async def wait(_):
        entered.set()
        await asyncio.Future()

    sdk.query.side_effect = wait
    session = DomainSession("domain", config=runtime_config, recorder=recorder)
    await session.activate()
    await session.submit_query("agent", "task", "r", context=origin(session))
    await entered.wait()
    await session.deactivate()
    assert session._active_task.cancelled()
    assert messages(writer)[-1]["outcome"] == "cancelled"
    assert events(writer, "domain_transition")[-1]["domain_state"] == "deactivated"


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

    monkeypatch.setattr(server_module.websockets, "serve", lambda *args: Listener())
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
async def test_generated_domain_id_matches_buffered_wire_identity(
    runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    server = BridgeServer(config=runtime_config, recorder=recorder)
    await server.dispatch({"type": "activate_domain", "domain_id": "domain"})
    await server.dispatch(
        {
            "type": "domain_query",
            "domain_id": "domain",
            "agent_id": "agent",
            "task": "question",
        }
    )
    session = server.domains._sessions["domain"]
    await session._active_task
    response = await server.dispatch({"type": "resume", "domain_id": "domain"})
    assert {r["request_id"] for r in messages(writer)} == {response[0]["request_id"]}


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

    monkeypatch.setattr(server_module.websockets, "serve", lambda *args: Listener())
    server = BridgeServer(config=runtime_config, recorder=recorder)
    server._shutdown_domains = AsyncMock(side_effect=RuntimeError("disconnect failed"))
    stopped = asyncio.Event()
    stopped.set()
    with pytest.raises(RuntimeError):
        await server.serve(stop_event=stopped)
    assert writer.closed == [False]


@pytest.mark.asyncio
async def test_sdk_reported_error_keeps_existing_buffer_and_wire_output(
    runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    _, sdk, _ = offline_clients

    class ResultMessage:
        session_id = "provider-error-session"
        is_error = True

    async def receive():
        yield SimpleNamespace(content=[SimpleNamespace(text="partial output")])
        yield ResultMessage()

    sdk.receive_response = receive
    session = DomainSession("domain", config=runtime_config, recorder=recorder)
    await session.activate()
    await session.submit_query("agent", "task", "r")
    await session._active_task
    assert session.buffer.since(-1)[0].output == "partial output"
    assert [(r["role"], r["outcome"]) for r in messages(writer)] == [
        ("user", "input"),
        ("error", "failure"),
    ]
    assert messages(writer)[-1]["provider_session_id"] == "provider-error-session"
    assert len(events(writer, "request_failed")) == 1


@pytest.mark.asyncio
async def test_domain_lifecycle_diagnostics_cover_all_transitions(
    runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    manager = DomainManager(config=runtime_config, recorder=recorder)
    await manager.activate_domain("domain")
    manager.background_domain("domain")
    manager.refocus_domain("domain")
    await manager.deactivate_domain("domain")
    assert [r["domain_state"] for r in events(writer, "domain_transition")] == [
        "activating",
        "active",
        "backgrounded",
        "active",
        "deactivated",
    ]


@pytest.fixture
def bound_runtime_listener(monkeypatch):
    class Listener:
        async def __aenter__(self):
            pass

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(server_module.websockets, "serve", lambda *args: Listener())


@pytest.mark.asyncio
async def test_deactivate_preserves_caller_cancel_during_child_cleanup(
    runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    _, sdk, _ = offline_clients
    query_entered = asyncio.Event()
    cleanup_entered = asyncio.Event()
    release = asyncio.Event()

    async def query(_):
        query_entered.set()
        try:
            await asyncio.Future()
        finally:
            cleanup_entered.set()
            await release.wait()

    sdk.query.side_effect = query
    session = DomainSession("domain", config=runtime_config, recorder=recorder)
    await session.activate()
    await session.submit_query(
        "agent", "task", "origin-request", context=origin(session)
    )
    await query_entered.wait()
    deactivation = asyncio.create_task(session.deactivate())
    await cleanup_entered.wait()
    deactivation.cancel("caller-stop")
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError) as error:
        await deactivation
    assert error.value.args == ("caller-stop",)
    assert session._active_task.cancelled()
    sdk.disconnect.assert_awaited_once()
    assert [r["outcome"] for r in messages(writer)] == ["input", "cancelled"]
    assert session.state.value == "deactivated"


@pytest.mark.asyncio
async def test_stop_event_shutdown_cancel_during_child_cleanup_is_unclean(
    runtime_config, runtime_archive, offline_clients, bound_runtime_listener
):
    recorder, writer = runtime_archive
    _, sdk, _ = offline_clients
    query_entered = asyncio.Event()
    cleanup_entered = asyncio.Event()
    release = asyncio.Event()

    async def query(_):
        query_entered.set()
        try:
            await asyncio.Future()
        finally:
            cleanup_entered.set()
            await release.wait()

    sdk.query.side_effect = query
    server = BridgeServer(config=runtime_config, recorder=recorder)
    await server.domains.activate_domain("domain")
    session = server.domains._sessions["domain"]
    await session.submit_query(
        "agent", "task", "origin-request", context=origin(session)
    )
    await query_entered.wait()
    stopped = asyncio.Event()
    stopped.set()
    serving = asyncio.create_task(server.serve(stop_event=stopped))
    await cleanup_entered.wait()
    serving.cancel("shutdown-stop")
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await serving
    assert writer.closed == [False]
    assert messages(writer)[-1]["outcome"] == "cancelled"
    sdk.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_immediate_submit_deactivate_archives_origin_once_before_sdk_start(
    runtime_config, runtime_archive, offline_clients
):
    recorder, writer = runtime_archive
    _, sdk, _ = offline_clients
    session = DomainSession("domain", config=runtime_config, recorder=recorder)
    await session.activate()
    context = origin(session)
    await session.submit_query("agent", "task", "origin-request", context=context)
    await session.deactivate()  # intentionally no scheduling yield after submission
    assert [(r["role"], r["outcome"]) for r in messages(writer)] == [
        ("user", "input"),
        ("error", "cancelled"),
    ]
    assert all(
        r["connection_id"] == context.connection_id
        and r["request_id"] == context.request_id
        for r in messages(writer)
    )
    assert len(events(writer, "request_cancelled")) == 1
    assert not events(writer, "execution_started")
    assert session._active_task.cancelled()
    sdk.query.assert_not_awaited()
    await asyncio.sleep(0)
    assert len(messages(writer)) == 2


@pytest.mark.asyncio
async def test_shutdown_attempts_all_domains_and_records_before_close_after_disconnect_error(
    runtime_config, runtime_archive, offline_clients, bound_runtime_listener
):
    recorder, writer = runtime_archive
    _, first, sdk_class = offline_clients
    second = AsyncMock()
    sdk_class.side_effect = [first, second]
    entered = {domain: asyncio.Event() for domain in ("first", "second")}

    async def first_query(_):
        entered["first"].set()
        await asyncio.Future()

    async def second_query(_):
        entered["second"].set()
        await asyncio.Future()

    first.query.side_effect = first_query
    second.query.side_effect = second_query
    failure = RuntimeError("credential-sentinel disconnect failed")
    first.disconnect.side_effect = failure
    close_snapshot = []
    original_close = writer.close

    def close(*, clean=True):
        close_snapshot.extend(messages(writer))
        original_close(clean=clean)

    writer.close = close
    server = BridgeServer(config=runtime_config, recorder=recorder)
    for domain_id in entered:
        await server.domains.activate_domain(domain_id)
        session = server.domains._sessions[domain_id]
        await session.submit_query(
            "agent", "task", "origin-request", context=origin(session)
        )
        await entered[domain_id].wait()
    stopped = asyncio.Event()
    stopped.set()
    try:
        with pytest.raises(RuntimeError) as error:
            await server.serve(stop_event=stopped)
        assert error.value is failure
        first.disconnect.assert_awaited_once()
        second.disconnect.assert_awaited_once()
        assert server.domains._sessions["second"].state.value == "deactivated"
        assert [(r["domain_id"], r["outcome"]) for r in close_snapshot] == [
            ("first", "input"),
            ("second", "input"),
            ("first", "cancelled"),
            ("second", "cancelled"),
        ]
        assert writer.closed == [False]
        assert "credential-sentinel" not in json.dumps(writer.records)
    finally:
        for session in server.domains._sessions.values():
            if not session._active_task.done():
                session._active_task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await session._active_task


@pytest.mark.asyncio
@pytest.mark.parametrize("primary", ["cancel", "bind_error"])
async def test_primary_serve_failure_survives_disconnect_failure(
    primary, runtime_config, runtime_archive, offline_clients, monkeypatch
):
    recorder, writer = runtime_archive
    _, sdk, _ = offline_clients
    bind_error = OSError("initial bind error")

    class Listener:
        async def __aenter__(self):
            if primary == "bind_error":
                raise bind_error

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(server_module.websockets, "serve", lambda *args: Listener())
    sdk.disconnect.side_effect = RuntimeError("secondary disconnect error")
    server = BridgeServer(config=runtime_config, recorder=recorder)
    await server.domains.activate_domain("domain")
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
    sdk.disconnect.assert_awaited_once()
    assert writer.closed == [False]
