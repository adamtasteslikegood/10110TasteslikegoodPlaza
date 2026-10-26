"""Generation ownership, real reservation/memory, deterministic admission/replay."""

import asyncio
import json
import threading
from dataclasses import replace

import pytest
import pytest_asyncio

from bridge.config import default_config
from bridge.domain_session import DomainSession
from bridge.project_memory import MemorySaveResult
from bridge.readiness import owned_io
from bridge.tests.domain_fakes import (
    FakeProjectService,
    FakeOwner,
    context,
    query,
    collect_until,
)


@pytest_asyncio.fixture
async def setup(tmp_path, monkeypatch):
    service = FakeProjectService(tmp_path)
    owners = []

    def factory(*args):
        owner = FakeOwner(*args)
        owners.append(owner)
        return owner

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", factory, raising=False)
    monkeypatch.setattr(
        "bridge.domain_session.load_agent",
        lambda agent: "definition" if agent == "backend-architect" else None,
    )
    session = DomainSession(
        "engineering",
        "generation",
        execution_id="execution",
        config=default_config(),
        project_service=service,
    )
    yield session, service, owners
    if owners:
        owners[0].clean = True
        if owners[0].stop_gate:
            owners[0].stop_gate.set()
    await session.stop()
    service.close()


@pytest.mark.asyncio
async def test_admission_precedes_immediate_terminal(setup):
    session, service, owners = setup
    await session.start()
    packets = []

    async def emit(packet):
        if packet["type"] == "domain_accepted":
            assert "pending" in service.memory.load().todo
            assert not owners[0].calls
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await collect_until(session, packets)
    assert [p["type"] for p in packets] == ["domain_accepted", "domain_result"]
    result = packets[-1]
    assert result["status"] == "success" and result["memory"]["saved"]
    assert result["project_id"] == service.workspace.project_id
    assert result["domain_session_id"] == "generation" and result["output_id"] == "1"
    assert "prior notes/data" in owners[0].calls[0]["prior_project_notes"]
    assert service.reservation.held


@pytest.mark.asyncio
async def test_duplicate_run_is_not_reexecuted(setup):
    session, _, owners = setup
    await session.start()
    owners[0].execute_gate = asyncio.Event()
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await session.admit_query(query(), context=context(), emit=emit)
    await session.admit_query(query(task="conflict"), context=context(), emit=emit)
    await session.admit_query(query("another"), context=context("another"), emit=emit)
    assert packets[-2]["error_type"] == "invalid_request"
    assert packets[-1]["error_type"] == "domain_busy"
    owners[0].execute_gate.set()
    await collect_until(session, packets)
    await session.admit_query(query(), context=context(), emit=emit)
    assert len(owners[0].calls) == 1
    assert len(session.replay(0)) == 2
    assert packets[-1] == packets[-2]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_failed_partial_reply_and_correlated_categories_record_once(
    setup, runtime_archive, enabled
):
    from bridge.domain_sdk import SDKOutcome

    session, _, owners = setup
    recorder, writer = runtime_archive
    recorder.config = replace(recorder.config, transcripts_enabled=enabled)
    session._recorder = recorder
    await session.start()
    owners[0].outcome = SDKOutcome(
        "Partial café 雪 credential-sentinel",
        "error",
        "readiness_failed",
        "provider",
        None,
        readiness_category="cwd_mismatch",
        tool_name="Bash",
        tool_use_id="a" * 64,
    )
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await collect_until(session, packets)
    await session.admit_query(query(), context=context(), emit=emit)
    transcripts = [record for kind, record, _ in writer.records if kind == "transcript"]
    events = [
        record
        for kind, record, _ in writer.records
        if kind == "event" and record["event"] == "request_failed"
    ]
    assert len(events) == 1
    assert events[0]["request_id"] == "run" and events[0]["domain_id"] == "engineering"
    assert events[0]["terminal_reason"] == "readiness_failed"
    assert events[0]["readiness_category"] == "cwd_mismatch"
    assert events[0]["tool_name"] == "Bash" and events[0]["tool_use_id"] == "a" * 64
    assert "Partial" not in str(events) and "credential-sentinel" not in str(events)
    if enabled:
        assert len(transcripts) == 2
        assert transcripts[-1]["content"] == "Partial café 雪 [REDACTED]"
        assert transcripts[-1]["outcome"] == "failure"
    else:
        assert transcripts == []
        assert "Partial" not in str(writer.records)
    assert packets[-1]["output"] == "Partial café 雪 credential-sentinel"
    assert packets[-1]["readiness_category"] == "cwd_mismatch"
    assert len(owners[0].calls) == 1


@pytest.mark.asyncio
async def test_real_branch_preflight_failure_records_safe_category(
    setup, runtime_archive
):
    from bridge.tests.test_workspace import git

    session, service, owners = setup
    recorder, writer = runtime_archive
    session._recorder = recorder
    await session.start()
    git(service.workspace.worktree_path, "checkout", "--detach")
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    assert len(packets) == 1 and packets[0]["error_type"] == "workspace_invalid"
    assert packets[0]["readiness_category"] == "branch_changed"
    events = [
        record
        for kind, record, _ in writer.records
        if kind == "event" and record["event"] == "request_failed"
    ]
    assert len(events) == 1
    assert (
        events[0]["request_id"] == "run"
        and events[0]["terminal_reason"] == "readiness_failed"
    )
    assert events[0]["readiness_category"] == "branch_changed"
    assert not owners[0].calls


@pytest.mark.asyncio
async def test_cancelled_preflight_records_cancellation_without_body(
    setup, runtime_archive, monkeypatch
):
    session, service, owners = setup
    recorder, writer = runtime_archive
    session._recorder = recorder
    await session.start()

    async def cancel(*args):
        raise asyncio.CancelledError()

    monkeypatch.setattr(service.readiness, "prepare_turn", cancel)
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    events = [
        r
        for kind, r, _ in writer.records
        if kind == "event" and r["event"].startswith("request_")
    ]
    assert len(events) == 1 and events[0]["event"] == "request_cancelled"
    assert (
        events[0]["outcome"] == "cancelled"
        and events[0]["terminal_reason"] == "stopped"
    )
    assert not owners[0].calls
    assert not [r for kind, r, _ in writer.records if kind == "transcript"]


@pytest.mark.asyncio
async def test_memory_save_failure_does_not_retry_completed_task(setup, monkeypatch):
    session, service, owners = setup
    await session.start()
    monkeypatch.setattr(
        service.memory,
        "finish_turn",
        lambda *a, **kw: MemorySaveResult(False, 2, "memory_unavailable"),
    )
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await collect_until(session, packets)
    await session.admit_query(query(), context=context(), emit=emit)
    assert (
        packets[-1]["status"] == "success" and packets[-1]["memory"]["saved"] is False
    )
    assert len(owners[0].calls) == 1


@pytest.mark.asyncio
async def test_delivery_failure_and_caller_cancellation_do_not_cancel_work(setup):
    session, _, owners = setup
    await session.start()
    entered, release = asyncio.Event(), asyncio.Event()

    async def emit(packet):
        if packet["type"] == "domain_accepted":
            entered.set()
            await release.wait()
        raise RuntimeError("socket gone")

    admission = asyncio.create_task(
        session.admit_query(query(), context=context(), emit=emit)
    )
    await entered.wait()
    admission.cancel()
    with pytest.raises(asyncio.CancelledError):
        await admission
    release.set()
    async with asyncio.timeout(3):
        while len(session.replay(0)) == 1:
            await asyncio.sleep(0.001)
    assert session.replay(0)[0]["status"] == "success"
    assert len(owners[0].calls) == 1


@pytest.mark.asyncio
async def test_stop_records_partial_cancel_then_releases_and_is_idempotent(setup):
    session, service, owners = setup
    await session.start()
    owners[0].execute_gate = asyncio.Event()
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await owners[0].executing.wait()
    assert session.background()["state"] == "background"
    assert session.refocus()["state"] == "active"
    assert (await session.stop())["state"] == "inactive"
    assert (await session.stop())["state"] == "inactive"
    result = session.replay(0)[0]
    assert result["status"] == "cancelled" and result["output"] == "partial"
    assert service.reservation is None and "cancelled" in service.memory.load().todo


@pytest.mark.asyncio
async def test_cleanup_failure_retains_reservation(setup):
    session, service, owners = setup
    await session.start()
    owners[0].clean = False
    assert (await session.stop())["state"] == "cleanup_failed"
    assert service.reservation.held
    owners[0].clean = True
    assert (await session.stop())["state"] == "inactive"


@pytest.mark.asyncio
async def test_stop_drains_late_prepare_and_settles_nonexecuted_intent(
    setup, monkeypatch
):
    session, service, owners = setup
    await session.start()
    entered, release = threading.Event(), threading.Event()
    real = service.memory.begin_turn

    def blocked(turn):
        result = real(turn)
        entered.set()
        release.wait(5)
        return result

    monkeypatch.setattr(service.memory, "begin_turn", blocked)
    packets = []

    async def emit(packet):
        packets.append(packet)

    admission = asyncio.create_task(
        session.admit_query(query(), context=context(), emit=emit)
    )
    await asyncio.to_thread(entered.wait, 3)
    stop = asyncio.create_task(session.stop())
    await asyncio.sleep(0.02)
    assert not stop.done() and service.reservation.held
    release.set()
    await stop
    await admission
    assert not owners[0].calls
    assert "pending" not in service.memory.load().todo
    assert not any(p["type"] == "domain_accepted" for p in packets)


@pytest.mark.asyncio
async def test_unknown_agent_rejected_before_checkpoint(setup):
    session, service, owners = setup
    await session.start()
    revision = service.memory.load().revision
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(agent_id="unknown"), context=context(), emit=emit)
    assert packets[-1]["error_type"] == "invalid_binding"
    assert service.memory.load().revision == revision and not owners[0].calls


@pytest.mark.asyncio
async def test_replay_highwater_and_history_gap(setup):
    session, _, owners = setup
    await session.start()
    packets = []

    async def emit(packet):
        packets.append(packet)

    for i in range(258):
        await session.admit_query(query(str(i)), context=context(str(i)), emit=emit)
        await collect_until(session, packets, i + 1)
    replay = session.replay(0)
    assert len(replay) == 257
    assert replay[-1]["history_gap"] is True and replay[-1]["earliest_output_id"] == "3"
    assert replay[-1]["high_water_mark"] == "258"
    assert session.replay(258)[-1]["type"] == "resume_complete"
    await session.admit_query(query("0"), context=context("0"), emit=emit)
    await collect_until(session, packets, 259)
    assert len(owners[0].calls) == 259  # No unbounded lifetime tombstones.


@pytest.mark.asyncio
async def test_output_and_total_bytes_are_bounded_and_owner_truncation_survives(setup):
    session, _, owners = setup
    await session.start()
    owners[0].outcome = replace(owners[0].outcome, output="é" * (256 * 1024))
    packets = []

    async def emit(packet):
        packets.append(packet)

    for i in range(18):
        await session.admit_query(query(str(i)), context=context(str(i)), emit=emit)
        await collect_until(session, packets, i + 1)
    results = session.replay(0)[:-1]
    assert sum(len(p["output"].encode()) for p in results) <= 4 * 1024 * 1024
    assert all(
        len(p["output"].encode()) <= 256 * 1024 and p["truncated"] for p in results
    )
    owners[0].outcome = replace(
        owners[0].outcome, output="short", status="error", reason="output_limit"
    )
    await session.admit_query(query("limit"), context=context("limit"), emit=emit)
    await collect_until(session, packets, 19)
    assert packets[-1]["truncated"] is True


@pytest.mark.asyncio
async def test_prepare_failure_rejects_without_execution_and_clears_admission(
    setup, monkeypatch
):
    session, service, owners = setup
    await session.start()
    original = service.readiness.prepare_turn

    async def fail(turn):
        await original(turn)
        raise TimeoutError("late checkpoint")

    monkeypatch.setattr(service.readiness, "prepare_turn", fail)
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    assert packets[-1]["error_type"] == "memory_unavailable" and not owners[0].calls
    assert "pending" not in service.memory.load().todo
    monkeypatch.setattr(service.readiness, "prepare_turn", original)
    await session.admit_query(query(), context=context(), emit=emit)
    await collect_until(session, packets)
    assert len(owners[0].calls) == 1


@pytest.mark.asyncio
async def test_pending_duplicate_waits_for_durable_admission(setup, monkeypatch):
    session, service, owners = setup
    await session.start()
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.readiness.prepare_turn

    async def blocked(turn):
        entered.set()
        await release.wait()
        return await original(turn)

    monkeypatch.setattr(service.readiness, "prepare_turn", blocked)
    owners[0].execute_gate = asyncio.Event()
    packets = []

    async def emit(packet):
        packets.append(packet)

    first = asyncio.create_task(
        session.admit_query(query(), context=context(), emit=emit)
    )
    await entered.wait()
    duplicate = asyncio.create_task(
        session.admit_query(query(), context=context(), emit=emit)
    )
    await asyncio.sleep(0)
    assert not packets and not duplicate.done()
    release.set()
    await first
    await duplicate
    assert [p["type"] for p in packets] == ["domain_accepted", "domain_accepted"]
    await session.stop()
    assert len(session.replay(0)) == 2


@pytest.mark.asyncio
async def test_stop_waits_for_terminal_memory_io_before_release(setup, monkeypatch):
    session, service, owners = setup
    await session.start()
    entered, release = threading.Event(), threading.Event()
    original = service.memory.finish_turn

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(service.memory, "finish_turn", blocked)
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await asyncio.to_thread(entered.wait, 3)
    stop = asyncio.create_task(session.stop())
    await asyncio.sleep(0.02)
    assert not stop.done() and service.reservation.held
    release.set()
    await stop
    assert service.reservation is None and session.replay(0)[0]["status"] == "success"


@pytest.mark.asyncio
async def test_mutating_sink_and_replay_cannot_change_stored_terminal(setup):
    session, _, _ = setup
    await session.start()
    done = asyncio.Event()

    async def emit(packet):
        if packet["type"] == "domain_result":
            packet["output"] = "changed"
            packet["memory"]["saved"] = False
            done.set()

    await session.admit_query(query(), context=context(), emit=emit)
    await done.wait()
    replay = session.replay(0)
    assert replay[0]["output"] == "done" and replay[0]["memory"]["saved"]
    replay[0]["memory"]["saved"] = False
    assert session.replay(0)[0]["memory"]["saved"]


@pytest.mark.asyncio
async def test_background_and_stop_checkpoint_lifecycle_without_finishing_run(setup):
    session, service, owners = setup
    await session.start()
    owners[0].execute_gate = asyncio.Event()
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await owners[0].executing.wait()
    service.memory_result = None
    session.background()
    async with asyncio.timeout(3):
        while service.memory_result is None:
            await asyncio.sleep(0.005)
    assert service.memory_result.saved
    assert "Bridge lifecycle event: background" in service.memory.load().progress
    assert "pending" in service.memory.load().todo
    await session.stop()
    progress = service.memory.load().progress
    assert "Bridge lifecycle event: stop" in progress
    assert "cancelled" in service.memory.load().todo


@pytest.mark.asyncio
async def test_direct_start_after_stop_never_reports_active(setup):
    session, _, _ = setup
    await session.start()
    await session.stop()
    assert (await session.start())["state"] == "inactive"


@pytest.mark.asyncio
async def test_actual_sdk_owner_receives_workspace_context_and_single_task_lifecycle(
    setup, monkeypatch
):
    session, service, _ = setup
    from bridge.domain_sdk import DomainSDKOwner
    from bridge.tests.test_domain_sdk import Client

    clients = []

    def client_factory(**kwargs):
        client = Client(**kwargs)
        clients.append(client)
        return client

    def owner_factory(*args):
        return DomainSDKOwner(*args, client_factory=client_factory)

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", owner_factory)
    await session.start()
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await collect_until(session, packets)
    await session.stop()
    assert packets[-1]["status"] == "success" and packets[-1]["output"] == "partial"
    assert clients[0].options.cwd == str(service.workspace.worktree_path)
    assert "prior notes/data" in clients[0].prompt
    assert len({task for _, task in clients[0].calls}) == 1
    assert [name for name, _ in clients[0].calls] == [
        "connect",
        "query",
        "receive",
        "disconnect",
    ]


@pytest.mark.asyncio
async def test_broken_sdk_rejects_further_runs_until_stop(setup):
    session, _, owners = setup
    await session.start()

    async def fail(**kwargs):
        raise RuntimeError("private transport detail")

    owners[0].execute = fail
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await collect_until(session, packets)
    await session.admit_query(query("second"), context=context("second"), emit=emit)
    assert packets[-1]["error_type"] == "sdk_error"
    assert session.replay(0)[0]["status"] == "error"
    assert "private" not in str(packets)


@pytest.mark.asyncio
async def test_lease_release_failure_retains_ownership_until_confirmed_retry(
    setup, monkeypatch
):
    session, service, _ = setup
    await session.start()
    lease = service.reservation
    original = lease.release

    def fail(**kwargs):
        raise OSError("cannot fsync")

    monkeypatch.setattr(lease, "release", fail)
    assert (await session.stop())["state"] == "cleanup_failed"
    assert lease.held and service.reservation is lease
    monkeypatch.setattr(lease, "release", original)
    assert (await session.stop())["state"] == "inactive"
    assert not lease.held


@pytest.mark.asyncio
async def test_owner_stopped_itself_rejects_further_admission(setup):
    session, _, owners = setup
    await session.start()
    owners[0].outcome = replace(owners[0].outcome, status="cancelled", reason="stopped")
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await collect_until(session, packets)
    await session.admit_query(query("next"), context=context("next"), emit=emit)
    assert (
        packets[-1]["type"] == "domain_error"
        and packets[-1]["error_type"] == "sdk_error"
    )
    assert len(owners[0].calls) == 1


@pytest.mark.asyncio
async def test_replay_snapshot_excludes_later_live_terminal(setup):
    session, _, owners = setup
    await session.start()
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await collect_until(session, packets)
    snapshot = session.replay(0)
    owners[0].execute_gate = asyncio.Event()
    await session.admit_query(query("later"), context=context("later"), emit=emit)
    owners[0].execute_gate.set()
    await collect_until(session, packets, 2)
    assert [p["output_id"] for p in snapshot[:-1]] == ["1"]
    assert snapshot[-1]["high_water_mark"] == "1"
    assert session.replay(1)[0]["output_id"] == "2"


@pytest.mark.asyncio
async def test_owned_background_checkpoint_cannot_race_terminal_memory_save(
    setup, monkeypatch
):
    session, service, owners = setup
    await session.start()
    owners[0].execute_gate = asyncio.Event()
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await owners[0].executing.wait()
    entered, release, terminal_entered = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    original_save = service.memory._save
    original_finish = service.memory.finish_turn

    def blocked_save(*args, **kwargs):
        # The first background save is paused inside the real store's file lock.
        if not entered.is_set():
            entered.set()
            release.wait(5)
        return original_save(*args, **kwargs)

    def observed_finish(*args, **kwargs):
        terminal_entered.set()
        return original_finish(*args, **kwargs)

    monkeypatch.setattr(service.memory, "_save", blocked_save)
    monkeypatch.setattr(service.memory, "finish_turn", observed_finish)
    session.background()
    await asyncio.to_thread(entered.wait, 3)
    stop = asyncio.create_task(session.stop())
    await owners[0].stopped.wait()
    await asyncio.sleep(0.03)
    try:
        assert not terminal_entered.is_set()
        assert not stop.done() and service.reservation.held
    finally:
        release.set()
        await stop
    result = session.replay(0)[0]
    assert result["status"] == "cancelled" and result["memory"]["saved"]
    assert "cancelled" in service.memory.load().todo
    assert "pending" not in service.memory.load().todo


@pytest.mark.asyncio
async def test_unrelated_memory_lock_still_rejects_run_without_retry(setup):
    session, service, owners = setup
    await session.start()
    from bridge.project_files import FileLock

    revision = service.memory.load().revision
    lock = FileLock.acquire(service.memory._base / "memory.lock")
    packets = []

    async def emit(packet):
        packets.append(packet)

    try:
        await session.admit_query(query(), context=context(), emit=emit)
    finally:
        lock.close()
    assert [p["type"] for p in packets] == ["domain_error"]
    assert packets[0]["error_type"] == "memory_unavailable"
    assert not owners[0].calls and service.memory.load().revision == revision
    assert len(session.replay(0)) == 1


@pytest_asyncio.fixture
async def real_owner_session(setup, monkeypatch, runtime_archive):
    """Real idle-owner lifecycle behind the existing offline SDK client seam."""
    from bridge.domain_sdk import DomainSDKOwner
    from bridge.tests.test_domain_sdk import Client

    session, service, _ = setup
    recorder, writer = runtime_archive
    session._recorder = recorder
    clients = []

    def client_factory(**kwargs):
        client = Client(**kwargs)
        clients.append(client)
        return client

    def owner_factory(*args):
        return DomainSDKOwner(*args, client_factory=client_factory)

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", owner_factory)
    await session.start()
    return session, service, session._owner, clients, writer


async def fail_idle_owner(owner):
    owner.transport._fail()
    await asyncio.wait_for(asyncio.shield(owner._worker), 2)
    assert owner.transport.broken and owner._worker.done()


def assert_rejected_dead_owner(packets, session, clients, writer):
    assert [packet["type"] for packet in packets] == ["domain_error"]
    assert packets[0]["error_type"] == "sdk_error"
    assert packets[0]["request_id"] == "run"
    assert packets[0]["domain_session_id"] == session.domain_session_id
    assert len(session.replay(0)) == 1
    assert len(clients) == 1
    assert [name for name, _ in clients[0].calls] == ["connect", "disconnect"]
    assert not [record for kind, record, _ in writer.records if kind == "transcript"]
    assert not [
        record
        for kind, record, _ in writer.records
        if kind == "event" and record["event"] == "execution_started"
    ]


@pytest.mark.asyncio
async def test_real_idle_owner_failure_rejects_without_memory_or_execution(
    real_owner_session,
):
    session, service, owner, clients, writer = real_owner_session
    before = service.memory.load()
    await fail_idle_owner(owner)
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    assert_rejected_dead_owner(packets, session, clients, writer)
    assert service.memory.load() == before
    assert session._broken and service.reservation.held
    await session.admit_query(query("next"), context=context("next"), emit=emit)
    assert packets[-1]["error_type"] == "sdk_error"
    assert service.memory.load() == before
    await session.stop()
    assert service.reservation is None


@pytest.mark.asyncio
async def test_real_owner_failure_during_prepare_settles_nonexecuted_intent(
    real_owner_session, monkeypatch
):
    session, service, owner, clients, writer = real_owner_session
    entered, release = threading.Event(), threading.Event()
    original = service.memory.begin_turn

    def blocked(turn):
        snapshot = original(turn)
        entered.set()
        release.wait(5)
        return snapshot

    monkeypatch.setattr(service.memory, "begin_turn", blocked)
    packets = []

    async def emit(packet):
        packets.append(packet)

    admission = asyncio.create_task(
        session.admit_query(query(), context=context(), emit=emit)
    )
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        assert "pending" in service.memory.load().todo
        await fail_idle_owner(owner)
        assert service.reservation.held and not admission.done()
    finally:
        release.set()
        await admission
    assert_rejected_dead_owner(packets, session, clients, writer)
    snapshot = service.memory.load()
    assert "pending" not in snapshot.todo and '"state":"error"' in snapshot.todo
    assert "Not executed" in snapshot.progress
    assert session._broken and service.reservation.held
    await session.stop()
    assert service.reservation is None


@pytest.mark.asyncio
async def test_retained_duplicate_replays_after_real_idle_owner_failure(
    real_owner_session,
):
    session, service, owner, clients, writer = real_owner_session
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    await collect_until(session, packets)
    terminal = packets[-1]
    before = service.memory.load()
    record_count = len(writer.records)
    await fail_idle_owner(owner)
    await session.admit_query(query(), context=context(), emit=emit)
    assert packets[-1] == terminal
    assert service.memory.load() == before
    assert len(writer.records) == record_count
    assert len(clients) == 1
    assert [name for name, _ in clients[0].calls] == [
        "connect",
        "query",
        "receive",
        "disconnect",
    ]
    assert service.reservation.held


@pytest.mark.asyncio
@pytest.mark.parametrize("skip", [False, True])
async def test_persistent_domain_context_refresh_and_symlink_replacement(
    setup, tmp_path, skip
):
    session, service, owners = setup
    root = service.workspace.project_root
    guidance = root / "PLAZA_AGENTS.md"
    session._config = replace(
        session._config,
        workspace_root_dir=root,
        install_context_dir=tmp_path / "owner-absent",
        domain_dangerously_skip_permissions=skip,
    )
    guidance.write_text("first revision")
    await session.start()
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query("first"), context=context("first"), emit=emit)
    await collect_until(session, packets)
    first = owners[0].calls[0]["context_packet"]
    assert "first revision" in first.render()
    assert (
        json.loads(first.runtime)["permission_mode"]
        == session._config.domain_permission_mode
    )
    guidance.write_text("second revision")
    packets.clear()
    await session.admit_query(query("second"), context=context("second"), emit=emit)
    await collect_until(session, packets)
    second = owners[0].calls[1]["context_packet"]
    assert "second revision" in second.render()
    assert first.diagnostics() != second.diagnostics()
    assert len(owners) == 1
    guidance.unlink()
    guidance.symlink_to(root / "README.md")
    packets.clear()
    await session.admit_query(query("third"), context=context("third"), emit=emit)
    assert packets[-1]["error_type"] == "context_unavailable"
    assert len(owners[0].calls) == 2
    assert "pending" not in service.memory.load().todo


@pytest.mark.asyncio
async def test_status_observes_dead_idle_owner_without_mutating_ownership(
    real_owner_session,
):
    from bridge.server import BridgeServer

    session, service, owner, clients, writer = real_owner_session
    from bridge.application_state import StateCommand
    from bridge.state_coordinator import StateCoordinator, VolatileStateRepository
    from uuid import uuid4

    coordinator = StateCoordinator(
        lambda: VolatileStateRepository(service.workspace.project_id)
    )
    await coordinator.open()
    session.execution_id = str(uuid4())
    commit = await coordinator.commit(
        StateCommand(
            "start",
            dict(
                domain_id=session.domain_id,
                expected_domain_revision=0,
                boot_id=str(uuid4()),
                execution_id=session.execution_id,
                timestamp="2026-10-26T00:00:00Z",
            ),
        )
    )
    session.domain_session_id = commit.result["session_id"]
    session._coordinator = coordinator
    server = BridgeServer(
        config=session._config, project_service=service, state_coordinator=coordinator
    )
    server.domains._sessions[session.domain_id] = [session]
    command = dict(
        type="agent_status", agent_id="backend-architect", request_id="status"
    )
    healthy = (await server.dispatch(command))[0]
    assert healthy["capabilities"]["can_run"]
    before = service.memory.load()
    await fail_idle_owner(owner)
    calls = list(clients[0].calls)
    snapshot = session.snapshot()
    capacity = service.capacity_snapshot()
    packet = (await server.dispatch(command))[0]
    assert not packet["capabilities"]["can_run"]
    assert packet["capabilities"]["tools"] == []
    assert packet["capabilities"]["reason"] == "sdk_error"
    assert packet["domain_state"]["domain_session_id"] == session.domain_session_id
    assert session.snapshot() == snapshot
    assert service.capacity_snapshot() == capacity
    assert service.reservation.held and not session._broken
    assert service.memory.load() == before
    assert clients[0].calls == calls and len(clients) == 1
    assert not [record for kind, record, _ in writer.records if kind == "transcript"]
    stopped = (
        await server.dispatch(
            dict(
                type="deactivate_domain",
                protocol_version=2,
                execution_id=session.execution_id,
                domain_id=session.domain_id,
                domain_session_id=session.domain_session_id,
                request_id="stop",
            )
        )
    )[-1]
    assert stopped["state"] == "inactive"
    assert service.reservation is None and service.capacity is None
    await coordinator.close()
    server.close()
