"""Real durable Run ordering, failure fencing and exact retained replay."""

import asyncio
import hashlib
import threading
from dataclasses import replace
from uuid import uuid4

import pytest
import pytest_asyncio

from bridge.application_state import StateError
from bridge.config import default_config
from bridge.domain_manager import DomainManager
from bridge.state_coordinator import LazySQLiteStateRepository, StateCoordinator
from bridge.tests.domain_fakes import FakeOwner, FakeProjectService, context, query


class ObservedRepository(LazySQLiteStateRepository):
    def __init__(self, common, project, controls):
        super().__init__(common, project)
        self.controls = controls

    def apply(self, command):
        controls = self.controls
        if command.kind == controls.get("block"):
            controls["entered"].set()
            assert controls["release"].wait(5)
        if command.kind == controls.get("fail"):
            raise StateError("state_store_failed")
        commit = super().apply(command)
        if command.kind == controls.get("block_after"):
            controls["entered"].set()
            assert controls["release"].wait(5)
        if command.kind == controls.get("fail_after"):
            raise StateError("state_store_uncertain", uncertain=True)
        controls["events"].append(command.kind)
        return commit


async def wait_for(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest_asyncio.fixture
async def durable(tmp_path, monkeypatch):
    service = FakeProjectService(tmp_path)
    owners = []
    controls = dict(events=[], entered=threading.Event(), release=threading.Event())

    def factory(*args):
        owner = FakeOwner(*args)
        owners.append(owner)
        return owner

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", factory)
    common, project = await service.application_state_binding()
    coordinator = StateCoordinator(
        lambda: ObservedRepository(common, project, controls)
    )
    await coordinator.open()
    manager = DomainManager(default_config(), service, state_coordinator=coordinator)
    packets = []

    async def emit(packet):
        controls["events"].append(packet["type"])
        packets.append(packet)

    await manager.handle(
        dict(
            type="activate_domain",
            protocol_version=2,
            request_id="start",
            domain_id="engineering",
            expected_domain_revision="0",
        ),
        context=context(),
        emit=emit,
    )
    session = manager._current("engineering")
    command = query(
        generation=session.domain_session_id, execution_id=session.execution_id
    )
    controls["events"].clear()
    packets.clear()
    yield manager, session, service, owners[
        0
    ], coordinator, controls, packets, emit, command
    controls["release"].set()
    controls.pop("fail", None)
    controls.pop("block", None)
    controls.pop("block_after", None)
    controls.pop("fail_after", None)
    if coordinator.health:
        await coordinator.reconcile()
    owners[0].clean = True
    await manager.shutdown()
    if session.state.value == "cleanup_failed":
        await session.stop()
    await coordinator.close()
    service.close()


async def run_until_terminal(durable):
    manager, session, _, _, _, _, packets, emit, command = durable
    expected = len(packets) + 2
    await manager.handle(command, context=context(), emit=emit)
    await wait_for(lambda: session._inflight is None and len(packets) >= expected)
    return packets[-1]


@pytest.mark.asyncio
async def test_accept_before_ack_and_dispatch_before_execute(durable):
    _, session, service, owner, coordinator, controls, _, _, command = durable
    execute = owner.execute

    async def observed(**kwargs):
        request = coordinator.find_request(
            session.domain_session_id, command["request_id"]
        )
        assert request.disposition == "dispatched"
        controls["events"].append("execute")
        assert request.turn_id == session._inflight.intent.turn_id
        assert request.memory_revision == session._inflight.memory_revision
        assert (
            request.task_digest == hashlib.sha256(command["task"].encode()).hexdigest()
        )
        assert "pending" in service.memory.load().todo
        return await execute(**kwargs)

    owner.execute = observed
    terminal = await run_until_terminal(durable)
    events = controls["events"]
    assert events.index("accept") < events.index("domain_accepted")
    assert events.index("dispatch") < events.index("execute")
    assert terminal["output_id"] == "1"


@pytest.mark.asyncio
async def test_notes_before_terminal_before_delivery(durable, monkeypatch):
    _, session, service, _, coordinator, controls, _, emit, _ = durable
    finish = service.memory.finish_turn

    def observed(*args, **kwargs):
        result = finish(*args, **kwargs)
        controls["events"].append("notes")
        return result

    monkeypatch.setattr(service.memory, "finish_turn", observed)

    async def checked(packet):
        if packet["type"] == "domain_result":
            assert coordinator.replay(session.domain_session_id, 0).entries == [packet]
            assert (
                coordinator.find_request(session.domain_session_id, "run").disposition
                == "terminal"
            )
        await emit(packet)

    values = list(durable)
    values[7] = checked
    await run_until_terminal(values)
    events = controls["events"]
    assert (
        events.index("notes") < events.index("terminal") < events.index("domain_result")
    )


@pytest.mark.asyncio
async def test_accept_failure_never_executes(durable, runtime_archive):
    manager, session, service, owner, coordinator, controls, packets, emit, command = (
        durable
    )
    recorder, writer = runtime_archive
    session._recorder = recorder
    controls["fail"] = "accept"
    await manager.handle(command, context=context(), emit=emit)
    assert packets[-1]["error_type"] == "state_store_failed"
    assert not owner.calls
    assert session._inflight is None and not coordinator.admission_open
    assert "pending" not in service.memory.load().todo
    assert not coordinator.snapshot().requests
    assert not [record for kind, record, _ in writer.records if kind == "transcript"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dispatch", "terminal"])
async def test_terminal_failure_is_uncommitted(durable, kind):
    _, session, _, owner, coordinator, controls, _, _, _ = durable
    controls["fail"] = kind
    terminal = await run_until_terminal(durable)
    assert terminal["committed"] is False
    assert "output_id" not in terminal
    assert terminal["error_type"] == "state_store_failed"
    assert terminal["output"] == ("done" if kind == "terminal" else "")
    assert bool(owner.calls) is (kind == "terminal")
    assert not coordinator.admission_open and not session.can_run
    assert coordinator.replay(session.domain_session_id, 0).entries == []
    assert coordinator.find_request(session.domain_session_id, "run").disposition == (
        "dispatched" if kind == "terminal" else "accepted"
    )


@pytest.mark.asyncio
async def test_duplicate_during_commit_executes_once(durable):
    manager, session, _, owner, _, controls, packets, emit, command = durable
    controls["block"] = "accept"
    first = asyncio.create_task(manager.handle(command, context=context(), emit=emit))
    try:
        await wait_for(controls["entered"].is_set)
        duplicate = asyncio.create_task(
            manager.handle(command, context=context(), emit=emit)
        )
        await asyncio.sleep(0)
        assert not duplicate.done() and not packets and not owner.calls
    finally:
        controls["release"].set()
    await asyncio.gather(first, duplicate)
    await wait_for(lambda: session._inflight is None)
    terminal = next(p for p in packets if p["type"] == "domain_result")
    await manager.handle(command, context=context(), emit=emit)
    assert packets[-1] == terminal and len(owner.calls) == 1
    assert controls["events"].count("accept") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["accept", "dispatch", "terminal"])
@pytest.mark.parametrize("phase", ["block", "block_after"], ids=["before", "after"])
async def test_cancelled_exact_commit_drains_and_preserves_disposition(
    durable, kind, phase
):
    manager, session, _, owner, coordinator, controls, packets, emit, command = durable
    controls[phase] = kind
    caller = asyncio.create_task(manager.handle(command, context=context(), emit=emit))
    try:
        await wait_for(controls["entered"].is_set)
        job = session._inflight.job
        job.cancel()
        await asyncio.sleep(0.01)
        job.cancel()
        await asyncio.sleep(0)
        assert not job.done() and session._inflight is not None
        assert not coordinator.replay(session.domain_session_id, 0).entries
    finally:
        controls["release"].set()
    await caller
    await wait_for(lambda: session._inflight is None)
    terminal = coordinator.replay(session.domain_session_id, 0).entries[0]
    assert terminal["output_id"] == "1"
    assert terminal["status"] == ("success" if kind == "terminal" else "cancelled")
    assert terminal["output"] == ("done" if kind == "terminal" else "")
    assert bool(owner.calls) is (kind == "terminal")
    assert sum(p["type"] == "domain_result" for p in packets) == 1
    assert controls["events"].count("terminal") == 1
    assert (
        coordinator.find_request(session.domain_session_id, "run").disposition
        == "terminal"
    )


@pytest.mark.asyncio
async def test_cancel_during_accept_delivery_settles_without_dispatch(durable):
    manager, session, _, owner, coordinator, _, packets, emit, command = durable
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(packet):
        if packet["type"] == "domain_accepted":
            entered.set()
            await release.wait()
        await emit(packet)

    caller = asyncio.create_task(
        manager.handle(command, context=context(), emit=blocked)
    )
    try:
        await entered.wait()
        job = session._inflight.job
        job.cancel()
        await asyncio.sleep(0)
        assert not job.done()
    finally:
        release.set()
    await asyncio.wait_for(caller, 3)
    await wait_for(lambda: session._inflight is None)
    terminal = coordinator.replay(session.domain_session_id, 0).entries[0]
    assert terminal["status"] == "cancelled" and terminal["output_id"] == "1"
    assert not owner.calls
    assert [p["type"] for p in packets] == ["domain_accepted", "domain_result"]


@pytest.mark.asyncio
async def test_cancel_during_notes_preserves_real_completed_outcome(
    durable, monkeypatch
):
    _, session, service, _, coordinator, _, _, _, _ = durable
    entered, release = threading.Event(), threading.Event()
    finish = service.memory.finish_turn

    def blocked(*args, **kwargs):
        result = finish(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(service.memory, "finish_turn", blocked)
    caller = asyncio.create_task(run_until_terminal(durable))
    try:
        await wait_for(entered.is_set)
        session._inflight.job.cancel()
        session._inflight.job.cancel()
        await asyncio.sleep(0)
        assert session._inflight is not None
    finally:
        release.set()
    terminal = await caller
    assert terminal["status"] == "success" and terminal["memory"]["saved"] is True
    assert coordinator.replay(session.domain_session_id, 0).entries == [terminal]


@pytest.mark.asyncio
async def test_cancel_during_result_delivery_keeps_published_result(durable):
    manager, session, _, owner, coordinator, _, packets, emit, command = durable
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(packet):
        if packet["type"] == "domain_result":
            entered.set()
            await release.wait()
        await emit(packet)

    await manager.handle(command, context=context(), emit=blocked)
    await entered.wait()
    job = next(job for job in session._jobs if not job.done())
    job.cancel()
    release.set()
    await asyncio.gather(job, return_exceptions=True)
    saved = coordinator.replay(session.domain_session_id, 0).entries[0]
    await manager.handle(command, context=context(), emit=emit)
    assert packets[-1] == saved and saved["status"] == "success"
    assert len(owner.calls) == 1


@pytest.mark.asyncio
async def test_memory_save_failure_frozen_in_committed_terminal(durable, monkeypatch):
    from bridge.project_memory import MemorySaveResult

    _, session, service, _, coordinator, _, _, _, _ = durable
    monkeypatch.setattr(
        service.memory,
        "finish_turn",
        lambda *a, **k: MemorySaveResult(False, 2, "memory_unavailable"),
    )
    terminal = await run_until_terminal(durable)
    assert terminal["status"] == "success"
    assert terminal["memory"] == dict(
        saved=False, revision=2, error_type="memory_unavailable"
    )
    terminal["memory"]["saved"] = True
    assert (
        coordinator.replay(session.domain_session_id, 0).entries[0]["memory"]["saved"]
        is False
    )


@pytest.mark.asyncio
async def test_oversized_terminal_metadata_is_uncommitted(durable):
    _, session, _, _, coordinator, _, _, _, _ = durable
    terminal = session._run_state.terminal

    async def oversized(request, packet):
        return await terminal(request, dict(packet, metadata="x" * (2 * 1024 * 1024)))

    session._run_state.terminal = oversized
    packet = await run_until_terminal(durable)
    assert packet["committed"] is False and packet["error_type"] == "state_store_quota"
    assert packet["output"] == "done" and "output_id" not in packet
    assert coordinator.replay(session.domain_session_id, 0).entries == []
    assert not coordinator.admission_open


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["accept", "dispatch", "terminal"])
async def test_stop_during_exact_commit_drains_before_releasing_ownership(
    durable, kind
):
    manager, session, service, owner, coordinator, controls, _, emit, command = durable
    controls["block"] = kind
    caller = asyncio.create_task(manager.handle(command, context=context(), emit=emit))
    try:
        await wait_for(controls["entered"].is_set)
        stopping = asyncio.create_task(session.stop())
        await wait_for(owner.stopped.is_set)
        await asyncio.sleep(0.01)
        assert not stopping.done() and service.reservation.held
        stopping.cancel()
        await asyncio.sleep(0)
        assert not stopping.done()
    finally:
        controls["release"].set()
    await caller
    with pytest.raises(asyncio.CancelledError):
        await stopping
    terminal = coordinator.replay(session.domain_session_id, 0).entries[0]
    assert terminal["status"] == ("success" if kind == "terminal" else "cancelled")
    assert bool(owner.calls) is (kind == "terminal")
    assert (
        session.clean_inactive and service.capacity is None and not session._lease.held
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("end", [False, True], ids=["stop", "end"])
async def test_server_old_history_reopen_run_stop_end_reopen_exact_sequence(
    tmp_path, monkeypatch, end
):
    """Actual server/manager/coordinator wiring keeps one committed ID sequence."""
    from bridge.project_service import ProjectService
    from bridge.server import BridgeServer
    from bridge.tests.test_workspace import repository

    root = repository(tmp_path)
    config = replace(default_config(), workspace_root_dir=root)
    owners = []

    def factory(*args):
        owner = FakeOwner(*args)
        owners.append(owner)
        return owner

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", factory)

    runtime = tmp_path / "runtime"
    runtime.mkdir()

    async def open_server():
        service = ProjectService(
            config, runtime_root=runtime, owner_run_id=str(uuid4())
        )
        await service.start()
        await service._bootstrap_task
        assert service.snapshot()["stage"] == "ready"
        return BridgeServer(config=config, project_service=service)

    async def send(server, kind, **values):
        command = dict(
            type=kind,
            protocol_version=2,
            request_id=str(uuid4()),
            domain_id="engineering",
        )
        current = server.domains.snapshot("engineering")
        if kind in {"activate_domain", "end_domain_session"}:
            command["expected_domain_revision"] = current["domain_revision"]
        if kind in {"domain_query", "deactivate_domain"}:
            command.update(
                domain_session_id=current["domain_session_id"],
                execution_id=current["execution_id"],
            )
        command.update(values)
        packets = []

        async def emit(packet):
            packets.append(packet)

        await server.dispatch(command, connection_id="socket", emit=emit)
        if (
            kind == "domain_query"
            and packets
            and packets[0]["type"] == "domain_accepted"
        ):
            session = server.domains._current("engineering")
            await wait_for(
                lambda: session._inflight is None
                and any(p["type"] == "domain_result" for p in packets)
            )
        return packets

    server = await open_server()
    try:
        first = (await send(server, "activate_domain"))[-1]
        assert first.get("state") == "active", first
        old = (
            await send(
                server,
                "domain_query",
                request_id="old",
                agent_id="backend-architect",
                task="Original saved task",
            )
        )[-1]
        assert old.get("output_id") == "1", old
        await send(server, "deactivate_domain")
        await server._shutdown()
        server.close()

        server = await open_server()
        replay = await send(
            server, "resume", domain_session_id=first["domain_session_id"], cursor="0"
        )
        assert replay[0] == old and replay[-1]["high_water_mark"] == "1"
        assert len(owners) == 1 and server.domains._sessions == {}
        second = (await send(server, "activate_domain"))[-1]
        assert second["domain_session_id"] == first["domain_session_id"]
        assert second["execution_id"] != first["execution_id"]
        duplicate = await send(
            server,
            "domain_query",
            request_id="old",
            agent_id="backend-architect",
            task="Original saved task",
        )
        assert duplicate == [old] and not owners[-1].calls
        conflict = await send(
            server,
            "domain_query",
            request_id="old",
            agent_id="backend-architect",
            task="conflict",
        )
        assert conflict[-1]["error_type"] == "invalid_request" and not owners[-1].calls
        fresh = (
            await send(
                server,
                "domain_query",
                request_id="new",
                agent_id="backend-architect",
                task="New saved task",
            )
        )[-1]
        assert fresh["output_id"] == "2" and len(owners[-1].calls) == 1
        if end:
            await send(
                server,
                "end_domain_session",
                domain_session_id=first["domain_session_id"],
            )
        else:
            await send(server, "deactivate_domain")
        await server._shutdown()
        server.close()

        server = await open_server()
        replay = await send(
            server, "resume", domain_session_id=first["domain_session_id"], cursor="0"
        )
        assert replay[:-1] == [old, fresh]
        assert replay[-1]["high_water_mark"] == "2" and replay[-1]["ended"] is end
        assert len(owners) == 2 and server.domains._sessions == {}
        if not end:
            await send(server, "activate_domain")
            assert (
                await send(
                    server,
                    "domain_query",
                    request_id="new",
                    agent_id="backend-architect",
                    task="New saved task",
                )
            ) == [fresh]
            assert not owners[-1].calls
    finally:
        await server._shutdown()
        server.close()


@pytest.mark.asyncio
async def test_failed_persistence_records_failure_without_saved_id(
    durable, runtime_archive
):
    _, session, _, _, _, controls, _, _, _ = durable
    recorder, writer = runtime_archive
    session._recorder = recorder
    controls["fail"] = "terminal"
    await run_until_terminal(durable)
    completed = [
        record
        for kind, record, _ in writer.records
        if kind == "event" and record.get("event") == "request_completed"
    ]
    failed = [
        record
        for kind, record, _ in writer.records
        if kind == "event" and record.get("event") == "request_failed"
    ]
    assert not completed and len(failed) == 1
    assert failed[0]["terminal_reason"] == "sdk_error"
    outputs = [
        record
        for kind, record, _ in writer.records
        if kind == "transcript" and record.get("role") == "error"
    ]
    assert outputs[-1]["outcome"] == "failure" and "output_id" not in outputs[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["accept", "dispatch", "terminal"])
async def test_uncertain_commit_never_invents_durable_ack(durable, kind):
    manager, session, _, owner, coordinator, controls, packets, emit, command = durable
    controls["fail_after"] = kind
    await manager.handle(command, context=context(), emit=emit)
    await wait_for(
        lambda: session._inflight is None
        and (len(packets) >= (1 if kind == "accept" else 2))
    )
    packet = packets[-1]
    assert packet["error_type"] == "state_store_uncertain" and "output_id" not in packet
    assert not coordinator.admission_open
    assert not coordinator.replay(session.domain_session_id, 0).entries
    assert bool(owner.calls) is (kind == "terminal")
    if kind != "accept":
        assert packet["committed"] is False
    controls.pop("fail_after")
    await coordinator.reconcile()
    request = coordinator.find_request(session.domain_session_id, "run")
    assert (
        request.disposition
        == {"accept": "accepted", "dispatch": "dispatched", "terminal": "terminal"}[
            kind
        ]
    )
    if kind == "terminal":
        saved = coordinator.replay(session.domain_session_id, 0).entries
        assert (
            len(saved) == 1
            and saved[0]["output_id"] == "1"
            and saved[0]["status"] == "success"
        )
        await manager.handle(command, context=context(), emit=emit)
        assert packets[-1] == saved[0] and len(owner.calls) == 1
    else:
        await manager.handle(command, context=context(), emit=emit)
        assert packets[-1]["type"] == "domain_accepted" and not owner.calls
        assert packets[-1]["execution_id"] == request.execution_id
    await manager.handle(
        dict(command, agent_id="cloud-architect"), context=context(), emit=emit
    )
    assert packets[-1]["error_type"] == "invalid_request"


@pytest.mark.asyncio
async def test_expired_completed_request_can_run_again_with_monotonic_id(durable):
    from bridge.domain_sdk import SDKOutcome

    manager, session, _, owner, coordinator, _, packets, emit, command = durable
    owner.outcome = SDKOutcome(
        "x" * (256 * 1024), "success", "completed", "provider", None
    )
    old = await run_until_terminal(durable)
    old_turn = coordinator.find_request(session.domain_session_id, "run").turn_id
    for index in range(16):
        values = list(durable)
        values[8] = dict(command, request_id="fill-" + str(index))
        await run_until_terminal(values)
    assert coordinator.find_request(session.domain_session_id, "run") is None
    window = coordinator.replay(session.domain_session_id, 0)
    assert window.high_water_mark == 17 and window.history_gap
    assert all(p["request_id"] != "run" for p in window.entries)
    repeated = await run_until_terminal(durable)
    assert repeated["output_id"] == "18" and repeated["output"] == old["output"]
    assert len(owner.calls) == 18
    assert (
        coordinator.find_request(session.domain_session_id, "run").turn_id != old_turn
    )


@pytest.mark.asyncio
async def test_completed_duplicate_replays_while_another_request_runs(durable):
    manager, session, _, owner, _, _, packets, emit, command = durable
    old = await run_until_terminal(durable)
    owner.execute_gate = asyncio.Event()
    try:
        await manager.handle(
            dict(command, request_id="other"), context=context("other"), emit=emit
        )
        await wait_for(lambda: len(owner.calls) == 2)
        await manager.handle(command, context=context(), emit=emit)
        assert packets[-1] == old
        assert (
            session._inflight.command["request_id"] == "other" and len(owner.calls) == 2
        )
    finally:
        owner.execute_gate.set()
        await wait_for(lambda: session._inflight is None)


@pytest.mark.asyncio
async def test_cancelled_socket_observer_detaches_without_cancelling_owned_run(durable):
    manager, session, _, owner, coordinator, controls, _, emit, command = durable
    controls["block"] = "accept"
    caller = asyncio.create_task(manager.handle(command, context=context(), emit=emit))
    try:
        await wait_for(controls["entered"].is_set)
        job = session._inflight.job
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert not job.done() and not owner.calls
    finally:
        controls["release"].set()
    await job
    saved = coordinator.replay(session.domain_session_id, 0).entries
    assert len(saved) == 1 and saved[0]["status"] == "success"
    assert len(owner.calls) == 1 and session._inflight is None


@pytest.mark.asyncio
@pytest.mark.parametrize("after_begin", [False, True], ids=["before", "after"])
async def test_rejected_readiness_never_accepts_and_settles_exact_intent(
    durable, after_begin
):
    from bridge.domain_protocol import DomainCommandError

    manager, session, service, owner, coordinator, _, packets, emit, command = durable
    prepare = session._readiness.prepare_turn
    turns = []

    async def rejected(intent):
        turns.append(intent.turn_id)
        if after_begin:
            await prepare(intent)
        raise DomainCommandError("workspace_invalid")

    session._readiness.prepare_turn = rejected
    await manager.handle(command, context=context(), emit=emit)
    assert packets[-1]["error_type"] == "workspace_invalid"
    assert not owner.calls and not coordinator.snapshot().requests
    assert session._inflight is None and coordinator.admission_open
    assert "pending" not in service.memory.load().todo
    assert len(turns) == 1


@pytest.mark.asyncio
async def test_owner_readiness_failure_after_notes_never_accepts(durable):
    manager, session, service, owner, coordinator, _, packets, emit, command = durable
    start = owner.start
    calls = 0

    async def failed_observation():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("owner failed after notes begin")
        return await start()

    owner.start = failed_observation
    await manager.handle(command, context=context(), emit=emit)
    assert packets[-1]["error_type"] == "sdk_error"
    assert not owner.calls and not coordinator.snapshot().requests
    assert "pending" not in service.memory.load().todo
    assert session._inflight is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["block", "block_after"], ids=["before", "after"])
async def test_stop_during_acceptance_archives_input_and_outcome_once(
    durable, runtime_archive, phase
):
    manager, session, service, owner, coordinator, controls, packets, emit, command = (
        durable
    )
    recorder, writer = runtime_archive
    session._recorder = recorder
    controls[phase] = "accept"
    origin = context(command["request_id"], "original-connection")
    caller = asyncio.create_task(manager.handle(command, context=origin, emit=emit))
    try:
        await wait_for(controls["entered"].is_set)
        stopping = asyncio.create_task(session.stop())
        await wait_for(owner.stopped.is_set)
        assert not stopping.done() and service.reservation.held
        assert not [
            record for kind, record, _ in writer.records if kind == "transcript"
        ]
    finally:
        controls["release"].set()
    await caller
    await stopping

    terminal = coordinator.replay(session.domain_session_id, 0).entries
    assert len(terminal) == 1
    assert terminal[0]["status"] == "cancelled" and terminal[0]["output_id"] == "1"
    assert packets == terminal and not owner.calls and session.clean_inactive
    assert (
        controls["events"].count("accept") == controls["events"].count("terminal") == 1
    )
    records = [record for kind, record, _ in writer.records if kind == "transcript"]
    assert [(record["role"], record["outcome"]) for record in records] == [
        ("user", "input"),
        ("error", "cancelled"),
    ]
    assert records[0]["content"] == command["task"]
    assert all(
        record["request_id"] == command["request_id"]
        and record["connection_id"] == "original-connection"
        and record["agent_id"] == command["agent_id"]
        for record in records
    )
    await manager.handle(
        dict(
            type="resume",
            protocol_version=2,
            domain_id=session.domain_id,
            domain_session_id=session.domain_session_id,
            request_id="replay",
            cursor="0",
        ),
        context=context("replay", "reconnected"),
        emit=emit,
    )
    assert [
        record for kind, record, _ in writer.records if kind == "transcript"
    ] == records
    assert (
        not owner.calls
        and coordinator.replay(session.domain_session_id, 0).entries == terminal
    )
