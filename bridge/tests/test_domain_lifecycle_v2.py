"""Application identity, execution authority and durable lifecycle CAS."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
import pytest_asyncio

from bridge.application_state import StateCommand, StateError
from bridge.config import default_config
from bridge.domain_manager import DomainManager
from bridge.state_coordinator import StateCoordinator, LazySQLiteStateRepository
from bridge.tests.domain_fakes import FakeOwner, FakeProjectService, context


@pytest_asyncio.fixture
async def lifecycle(tmp_path, monkeypatch):
    service = FakeProjectService(tmp_path)
    owners = []

    def factory(*args):
        owner = FakeOwner(*args)
        owners.append(owner)
        return owner

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", factory)
    common, project = await service.application_state_binding()
    coordinators, managers = [], []

    async def reboot():
        if managers:
            await managers[-1].shutdown()
            await coordinators[-1].close()
        coordinator = StateCoordinator(
            lambda: LazySQLiteStateRepository(common, project)
        )
        await coordinator.open()
        manager = DomainManager(
            default_config(), service, state_coordinator=coordinator
        )
        managers.append(manager)
        coordinators.append(coordinator)
        return manager

    manager = await reboot()
    yield manager, reboot, service, owners, coordinators
    for owner in owners:
        owner.clean = True
        if owner.stop_gate:
            owner.stop_gate.set()
    await managers[-1].shutdown()
    await coordinators[-1].close()
    service.close()


async def send(manager, kind, **values):
    packet = dict(
        type=kind, protocol_version=2, request_id=str(uuid4()), domain_id="engineering"
    )
    packet.update(values)
    if kind in ("activate_domain", "end_domain_session"):
        packet.setdefault(
            "expected_domain_revision",
            manager.snapshot("engineering")["domain_revision"],
        )
    if kind in (
        "deactivate_domain",
        "background_domain",
        "refocus_domain",
        "domain_query",
    ):
        current = manager.snapshot("engineering")
        packet.setdefault("domain_session_id", current["domain_session_id"])
        packet.setdefault("execution_id", current["execution_id"])
    packets = []

    async def emit(value):
        packets.append(value)

    await manager.handle(packet, context=context(), emit=emit)
    return packets[-1]


@pytest.mark.asyncio
async def test_stop_restart_preserves_app_id(lifecycle):
    manager, reboot, _, owners, _ = lifecycle
    first = await send(manager, "activate_domain")
    stopped = await send(manager, "deactivate_domain")
    assert stopped["domain_session_id"] == first["domain_session_id"]
    assert stopped["execution_id"] is None
    manager = await reboot()
    restored = manager.snapshot("engineering")
    assert restored["domain_session_id"] == first["domain_session_id"]
    assert restored["execution_id"] is None and len(owners) == 1
    second = await send(manager, "activate_domain")
    assert second["domain_session_id"] == first["domain_session_id"]
    assert second["execution_id"] != first["execution_id"]
    assert int(second["domain_revision"]) > int(stopped["domain_revision"])
    assert len(owners) == 2


@pytest.mark.asyncio
async def test_end_then_start_new_app_id(lifecycle):
    manager, _, _, _, coordinators = lifecycle
    first = await send(manager, "activate_domain")
    ended = await send(
        manager, "end_domain_session", domain_session_id=first["domain_session_id"]
    )
    assert ended["state"] == "inactive" and ended["execution_id"] is None
    assert int(ended["domain_revision"]) == int(first["domain_revision"]) + 2
    record = coordinators[-1].snapshot().sessions[0]
    assert record.ended_at and record.ended_by == "user"
    assert ended["domain_session_id"] is None
    second = await send(manager, "activate_domain")
    assert second["domain_session_id"] != first["domain_session_id"]
    assert len(second["saved_sessions"]) == 2


@pytest.mark.asyncio
async def test_stale_execution_rejected(lifecycle):
    manager, _, _, owners, _ = lifecycle
    first = await send(manager, "activate_domain")
    await send(manager, "deactivate_domain")
    second = await send(manager, "activate_domain")
    for action in (
        "domain_query",
        "background_domain",
        "refocus_domain",
        "deactivate_domain",
    ):
        values = dict(
            execution_id=first["execution_id"],
            domain_session_id=first["domain_session_id"],
        )
        if action == "domain_query":
            values.update(agent_id="backend-architect", task="stale")
        assert (await send(manager, action, **values))[
            "error_type"
        ] == "stale_execution"
    assert manager.snapshot("engineering")["execution_id"] == second["execution_id"]
    assert not owners[-1].stopped.is_set() and not owners[-1].calls


@pytest.mark.asyncio
async def test_stale_start_and_end_revision_rejected(lifecycle):
    manager, _, service, _, _ = lifecycle
    first = await send(manager, "activate_domain")
    for action in ("activate_domain", "end_domain_session"):
        values = dict(expected_domain_revision="0")
        if action == "end_domain_session":
            values["domain_session_id"] = first["domain_session_id"]
        assert (await send(manager, action, **values))[
            "error_type"
        ] == "stale_domain_revision"
    assert service.reservation.held
    assert manager.snapshot("engineering")["execution_id"] == first["execution_id"]


@pytest.mark.asyncio
async def test_old_client_upgrade_required(lifecycle):
    manager, _, _, owners, _ = lifecycle
    packets = []

    async def emit(packet):
        packets.append(packet)

    for version in (None, 1, 3, True, "2"):
        command = dict(
            type="activate_domain", request_id="old", domain_id="engineering"
        )
        if version is not None:
            command["protocol_version"] = version
        await manager.handle(command, context=context(), emit=emit)
        assert packets[-1]["error_type"] == "upgrade_required"
    assert not owners


@pytest.mark.asyncio
async def test_ended_replay_without_sdk(lifecycle):
    manager, reboot, _, owners, _ = lifecycle
    first = await send(manager, "activate_domain")
    await send(
        manager, "end_domain_session", domain_session_id=first["domain_session_id"]
    )
    manager = await reboot()
    packet = await send(
        manager, "resume", domain_session_id=first["domain_session_id"], cursor="0"
    )
    assert packet["type"] == "resume_complete" and packet["ended"]
    assert packet["execution_id"] is None and len(owners) == 1
    assert manager.snapshot("engineering")["domain_session_id"] is None


@pytest.mark.asyncio
async def test_failed_cleanup_end_retains_open_id_and_ownership(lifecycle):
    manager, _, service, owners, coordinators = lifecycle
    first = await send(manager, "activate_domain")
    owners[-1].clean = False
    packet = await send(
        manager, "end_domain_session", domain_session_id=first["domain_session_id"]
    )
    assert packet["error_type"] == "cleanup_failed"
    assert service.reservation.held
    assert coordinators[-1].snapshot().sessions[0].ended_at is None
    assert (
        manager.snapshot("engineering")["domain_session_id"]
        == first["domain_session_id"]
    )


@pytest.mark.asyncio
async def test_concurrent_end_validates_cas_before_its_own_stop(lifecycle):
    manager, _, _, owners, _ = lifecycle
    first = await send(manager, "activate_domain")
    owners[-1].stop_gate = asyncio.Event()
    values = dict(
        domain_session_id=first["domain_session_id"],
        expected_domain_revision=first["domain_revision"],
    )
    end = asyncio.create_task(send(manager, "end_domain_session", **values))
    await owners[-1].stopped.wait()
    duplicate = asyncio.create_task(send(manager, "end_domain_session", **values))
    owners[-1].stop_gate.set()
    results = await asyncio.gather(end, duplicate)
    assert results[0]["state"] == "inactive"
    assert results[1]["error_type"] == "stale_domain_revision"


@pytest.mark.asyncio
async def test_store_failure_denies_run_and_actual_tool_hook(lifecycle):
    manager, _, service, _, coordinators = lifecycle
    await send(manager, "activate_domain")
    session = manager._sessions["engineering"][-1]
    coordinator = coordinators[-1]
    coordinator._health = "state_store_failed"
    packet = await send(
        manager, "domain_query", agent_id="backend-architect", task="blocked"
    )
    assert packet["error_type"] == "state_store_failed"
    hook = session._readiness.pre_tool_hook(service.reservation)
    denied = await hook({}, "tool", {})
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    coordinator._health = None


async def persisted_result(coordinator, identity):
    """Genuine committed fixture history; production Run ordering is Task 5."""
    from bridge.tests.test_sqlite_state import request, packet

    active = dict(
        session_id=identity["domain_session_id"], execution_id=identity["execution_id"]
    )
    record = request(active, "saved-turn")
    await coordinator.commit(StateCommand("accept", dict(request=record)))
    await coordinator.commit(
        StateCommand(
            "dispatch", dict(session_id=record.session_id, request_id=record.request_id)
        )
    )
    result = await coordinator.commit(
        StateCommand(
            "terminal",
            dict(
                session_id=record.session_id,
                request_id=record.request_id,
                packet=packet(record, "saved café"),
            ),
        )
    )
    return result.result["terminal"]


@pytest.mark.asyncio
async def test_committed_ended_history_reopens_exactly_without_sdk(lifecycle):
    manager, reboot, _, owners, coordinators = lifecycle
    first = await send(manager, "activate_domain")
    terminal = await persisted_result(coordinators[-1], first)
    await send(
        manager, "end_domain_session", domain_session_id=first["domain_session_id"]
    )
    manager = await reboot()
    packets = []

    async def emit(packet):
        packets.append(packet)

    await manager.handle(
        dict(
            type="resume",
            protocol_version=2,
            domain_id="engineering",
            domain_session_id=first["domain_session_id"],
            request_id="replay",
            cursor="0",
        ),
        context=context(),
        emit=emit,
    )
    assert packets[0] == terminal and packets[0]["output_id"] == "1"
    assert packets[1]["ended"] and packets[1]["high_water_mark"] == "1"
    assert len(owners) == 1


@pytest.mark.asyncio
async def test_saved_old_terminal_does_not_overwrite_new_execution(lifecycle):
    manager, _, _, owners, coordinators = lifecycle
    first = await send(manager, "activate_domain")
    terminal = await persisted_result(coordinators[-1], first)
    await send(manager, "deactivate_domain")
    second = await send(manager, "activate_domain")
    packets = []

    async def emit(packet):
        packets.append(packet)

    await manager.handle(
        dict(
            type="resume",
            protocol_version=2,
            domain_id="engineering",
            domain_session_id=first["domain_session_id"],
            request_id="replay",
            cursor="0",
        ),
        context=context(),
        emit=emit,
    )
    assert packets[0] == terminal
    assert packets[-1]["execution_id"] == second["execution_id"]
    assert manager.snapshot("engineering")["state"] == "active"
    assert not owners[-1].stopped.is_set()


@pytest.mark.asyncio
async def test_concurrent_duplicate_activation_has_one_fresh_owner(lifecycle):
    manager, _, _, owners, _ = lifecycle
    results = await asyncio.gather(
        *(
            send(manager, "activate_domain", expected_domain_revision="0")
            for _ in range(2)
        )
    )
    assert sum(result.get("state") == "active" for result in results) == 1
    assert (
        sum(result.get("error_type") == "stale_domain_revision" for result in results)
        == 1
    )
    assert len(owners) == 1


@pytest.mark.asyncio
async def test_failed_sdk_activation_records_actual_failure(lifecycle, monkeypatch):
    manager, _, service, _, coordinators = lifecycle

    async def fail(owner):
        raise RuntimeError("private startup")

    monkeypatch.setattr(FakeOwner, "start", fail)
    reply = await send(manager, "activate_domain")
    assert reply["error_type"] == "sdk_error"
    view = coordinators[-1].snapshot()
    assert view.executions[0].outcome == "startup_failed"
    assert view.executions[0].stopped_at and not service.capacity
    assert view.sessions[0].ended_at is None


@pytest.mark.asyncio
async def test_requestless_old_boot_is_interrupted_before_start(lifecycle):
    manager, _, _, owners, coordinators = lifecycle
    commit = await coordinators[-1].commit(
        StateCommand(
            "start",
            dict(
                domain_id="engineering",
                expected_domain_revision=0,
                boot_id=str(uuid4()),
                execution_id=str(uuid4()),
                timestamp="2026-10-25T00:00:00Z",
            ),
        )
    )
    first = commit.result
    result = await send(manager, "activate_domain", expected_domain_revision="1")
    assert result["domain_session_id"] == first["session_id"]
    assert result["domain_revision"] == "3" and len(owners) == 1
    old = next(
        e
        for e in coordinators[-1].snapshot().executions
        if e.execution_id == first["execution_id"]
    )
    assert old.outcome == "interrupted" and old.stopped_at


@pytest.mark.asyncio
async def test_second_manager_cannot_recover_live_same_boot(lifecycle):
    manager, _, service, owners, coordinators = lifecycle
    first = await send(manager, "activate_domain")
    other = DomainManager(default_config(), service, state_coordinator=coordinators[-1])
    result = await send(
        other, "activate_domain", expected_domain_revision=first["domain_revision"]
    )
    assert result["error_type"] in {"capacity_limit", "state_store_busy"}
    execution = coordinators[-1].snapshot().executions[0]
    assert execution.stopped_at is None and not owners[0].stopped.is_set()


@pytest.mark.asyncio
async def test_stop_state_fault_drains_sdk_retains_lease_and_blocks_start(lifecycle):
    manager, _, service, owners, coordinators = lifecycle
    first = await send(manager, "activate_domain")
    coordinators[-1]._health = "state_store_failed"
    try:
        reply = await send(manager, "deactivate_domain")
        assert reply["state"] == "cleanup_failed"
        assert owners[0].stopped.is_set() and service.reservation.held
        assert (await send(manager, "activate_domain"))[
            "error_type"
        ] == "state_store_failed"
        assert (
            manager.snapshot("engineering")["domain_session_id"]
            == first["domain_session_id"]
        )
        assert coordinators[-1].snapshot().executions[0].stopped_at is None
    finally:
        coordinators[-1]._health = None


@pytest.mark.asyncio
async def test_cancelled_start_during_commit_keeps_registered_startup(
    lifecycle, monkeypatch
):
    manager, _, service, owners, coordinators = lifecycle
    coordinator = coordinators[-1]
    original = coordinator.commit
    committed, release = asyncio.Event(), asyncio.Event()

    async def barrier(command):
        result = await original(command)
        if command.kind == "start":
            committed.set()
            await release.wait()
        return result

    monkeypatch.setattr(coordinator, "commit", barrier)
    start = asyncio.create_task(send(manager, "activate_domain"))
    await committed.wait()
    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start
    release.set()
    async with asyncio.timeout(3):
        while not owners or not owners[0].started.is_set():
            await asyncio.sleep(0)
    session = manager._sessions["engineering"][-1]
    await session._startup
    assert service.reservation.held and session.state.value == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [False, True])
async def test_failed_end_never_acknowledges_or_retries_marker(
    lifecycle, monkeypatch, uncertain
):
    manager, _, _, owners, coordinators = lifecycle
    first = await send(manager, "activate_domain")
    coordinator = coordinators[-1]
    repository = coordinator._repository
    original = repository.apply
    calls = []

    def fail(command):
        if command.kind != "end":
            return original(command)
        calls.append(command)
        if uncertain:
            original(command)
        raise StateError(
            "state_store_uncertain" if uncertain else "state_store_failed",
            uncertain=uncertain,
        )

    monkeypatch.setattr(repository, "apply", fail)
    result = await send(
        manager, "end_domain_session", domain_session_id=first["domain_session_id"]
    )
    assert result["error_type"] == (
        "state_store_uncertain" if uncertain else "state_store_failed"
    )
    assert coordinator.snapshot().sessions[0].ended_at is None
    assert (
        manager.snapshot("engineering")["domain_session_id"]
        == first["domain_session_id"]
    )
    assert not coordinator.admission_open and owners[0].stopped.is_set()
    assert len(calls) == 1
    monkeypatch.setattr(repository, "apply", original)
    await coordinator.reconcile()
    assert bool(coordinator.snapshot().sessions[0].ended_at) is uncertain
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_missing_explicit_binding_fails_closed(lifecycle):
    _, _, service, owners, _ = lifecycle
    unbound = DomainManager(default_config(), service)
    result = await send(unbound, "activate_domain", expected_domain_revision="0")
    assert result["error_type"] == "state_store_busy"
    assert not owners and unbound.coordinator is None


@pytest.mark.asyncio
async def test_saved_catalog_does_not_retain_closed_sdk_owners(lifecycle):
    manager, _, _, owners, _ = lifecycle
    identity = None
    for _ in range(3):
        active = await send(manager, "activate_domain")
        identity = identity or active["domain_session_id"]
        assert active["domain_session_id"] == identity
        await send(manager, "deactivate_domain")
    assert len(owners) == 3
    assert len(manager._sessions["engineering"]) == 1
    assert len(manager.snapshot("engineering")["saved_sessions"]) == 1


@pytest.mark.asyncio
async def test_real_sdk_installed_hook_denies_faulted_application_state(
    lifecycle, monkeypatch
):
    from bridge.domain_sdk import DomainSDKOwner
    from bridge.tests.test_domain_sdk import Client

    manager, _, service, _, coordinators = lifecycle
    clients = []

    def client_factory(**kwargs):
        client = Client(**kwargs)
        clients.append(client)
        return client

    def owner_factory(*args):
        return DomainSDKOwner(*args, client_factory=client_factory)

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", owner_factory)
    await send(manager, "activate_domain")
    assert len(clients) == 1
    callback = clients[0].options.hooks["PreToolUse"][0].hooks[0]
    coordinator = coordinators[-1]
    coordinator._health = "state_store_failed"
    try:
        denied = await asyncio.create_task(
            callback(
                dict(
                    hook_event_name="PreToolUse",
                    tool_name="Read",
                    tool_use_id="tool",
                    cwd=str(service.workspace.worktree_path),
                ),
                "tool",
                {},
            )
        )
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert not [call for call, _ in clients[0].calls if call == "query"]
    finally:
        coordinator._health = None


@pytest.mark.asyncio
@pytest.mark.parametrize("clean", [True, False])
async def test_shutdown_cancellation_drains_pending_end_and_other_owner(
    lifecycle, monkeypatch, clean
):
    import threading

    manager, _, service, owners, coordinators = lifecycle
    coordinator = coordinators[-1]
    core = await coordinator.commit(
        StateCommand(
            "start",
            dict(
                domain_id="core",
                expected_domain_revision=0,
                boot_id=str(uuid4()),
                execution_id=str(uuid4()),
                timestamp="2026-10-26T00:00:00Z",
            ),
        )
    )
    await coordinator.commit(
        StateCommand(
            "stop",
            dict(
                execution_id=core.result["execution_id"],
                outcome="stopped",
                timestamp="2026-10-26T00:00:01Z",
            ),
        )
    )
    await send(manager, "activate_domain")
    owner = owners[-1]
    owner.clean = clean
    owner.stop_gate = asyncio.Event()
    entered, release = threading.Event(), threading.Event()
    original = coordinator._repository.apply

    def blocked(command):
        if command.kind == "end":
            entered.set()
            assert release.wait(5), "test did not release the End worker"
        return original(command)

    monkeypatch.setattr(coordinator._repository, "apply", blocked)
    packets = []

    async def emit(packet):
        packets.append(packet)

    end = asyncio.create_task(
        manager.handle(
            dict(
                type="end_domain_session",
                protocol_version=2,
                request_id="end-core",
                domain_id="core",
                domain_session_id=core.result["session_id"],
                expected_domain_revision="2",
            ),
            context=context(),
            emit=emit,
        )
    )
    shutdown = None
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        pending_end = next(iter(manager._operations))
        shutdown = asyncio.create_task(manager.shutdown())
        await asyncio.sleep(0)
        shutdown.cancel("first shutdown cancellation")
        await asyncio.sleep(0)
        assert not shutdown.done()
        assert not pending_end.cancelled() and not pending_end.done()
        shutdown.cancel("second shutdown cancellation")
        await asyncio.sleep(0)
        assert not shutdown.done() and not pending_end.cancelled()
        assert not owner.stopped.is_set() and service.reservation.held
        release.set()
        await asyncio.wait_for(asyncio.shield(end), 3)
        await asyncio.wait_for(owner.stopped.wait(), 3)
        assert packets[-1]["type"] == "domain_state"
        assert packets[-1]["domain_session_id"] is None
        shutdown.cancel("third shutdown cancellation")
        await asyncio.sleep(0)
        assert not shutdown.done() and service.reservation.held
        owner.stop_gate.set()
        with pytest.raises(asyncio.CancelledError) as error:
            await shutdown
        assert error.value.args == ("third shutdown cancellation",)
        assert owner.stopped.is_set()
        assert owner.lease.held is not clean
        assert bool(service.reservation) is not clean
        assert bool(service.capacity) is not clean
        assert manager.snapshot("engineering")["state"] == (
            "inactive" if clean else "cleanup_failed"
        )
        saved_core = next(
            s
            for s in coordinator.snapshot().sessions
            if s.session_id == core.result["session_id"]
        )
        assert saved_core.ended_at is not None
        assert not manager._operations and not coordinator._operations
    finally:
        release.set()
        owner.clean = True
        owner.stop_gate.set()
        await asyncio.gather(
            end, *([shutdown] if shutdown else []), return_exceptions=True
        )
        await manager.shutdown()
