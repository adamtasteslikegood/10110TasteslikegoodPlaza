"""Pure crash classification and owned, durable startup recovery."""

import importlib
import asyncio
import os
import threading
from uuid import uuid4

import pytest
from dataclasses import replace

from bridge.application_state import StateCommand, StateError, TerminalRecord
from bridge.project_memory import TurnIntent
from bridge.state_coordinator import LazySQLiteStateRepository, StateCoordinator
from bridge.tests.test_sqlite_state import request, packet, STAMP
from bridge.tests.test_domain_lifecycle_v2 import lifecycle as lifecycle_fixture, send
from bridge.domain_manager import DomainManager
from bridge.config import default_config

OLD_BOOT = "00000000-0000-4000-8000-000000000001"
NEW_BOOT = "00000000-0000-4000-8000-000000000002"
lifecycle = lifecycle_fixture


def seed(common, disposition="accepted", boot=OLD_BOOT, committed=False):
    repository = LazySQLiteStateRepository(common, "project")
    repository.load()
    active = repository.apply(
        StateCommand(
            "start",
            dict(
                domain_id="engineering",
                expected_domain_revision=0,
                boot_id=boot,
                execution_id=str(uuid4()),
                timestamp=STAMP,
            ),
        )
    ).result
    record = request(active)
    if disposition:
        repository.apply(StateCommand("accept", dict(request=record)))
        if disposition == "dispatched":
            repository.apply(
                StateCommand(
                    "dispatch",
                    dict(session_id=record.session_id, request_id=record.request_id),
                )
            )
        if committed:
            repository.apply(
                StateCommand(
                    "terminal",
                    dict(
                        session_id=record.session_id,
                        request_id=record.request_id,
                        packet=packet(record),
                    ),
                )
            )
    view = repository.load()
    repository.close()
    return view


@pytest.mark.parametrize(
    "disposition,reason", [("accepted", "not_executed"), ("dispatched", "interrupted")]
)
def test_classifier_is_pure_exact_and_does_not_touch_current_boot(
    tmp_path, disposition, reason
):
    common = tmp_path / "common"
    common.mkdir()
    view = seed(common, disposition)
    recovery = importlib.import_module("bridge.session_recovery")
    commands = recovery.classify_recovery(view, NEW_BOOT, observed_at=STAMP)
    assert len(commands) == 1 and commands[0].kind == "recover"
    value = commands[0].payload["packet"]
    assert value["reason"] == reason and value["status"] == "error"
    assert value["execution_id"] == view.requests[0].execution_id
    assert value["request_id"] == view.requests[0].request_id
    assert value["memory"]["saved"] is False
    assert recovery.classify_recovery(view, OLD_BOOT, observed_at=STAMP) == ()
    assert recovery.classify_recovery(view, NEW_BOOT, observed_at=STAMP) == commands


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "disposition,committed",
    [("accepted", False), ("dispatched", False), ("dispatched", True), (None, False)],
)
async def test_open_recovers_before_publication_once(tmp_path, disposition, committed):
    common = tmp_path / "common"
    common.mkdir()
    before = seed(common, disposition, committed=committed)
    after = None
    for _ in range(2):
        coordinator = StateCoordinator(
            lambda: LazySQLiteStateRepository(common, "project"), boot_id=NEW_BOOT
        )
        await coordinator.open()
        try:
            view = coordinator.snapshot()
            assert all(e.stopped_at for e in view.executions)
            assert len(view.terminals) == bool(disposition)
            if disposition:
                assert view.terminals[0].output_id == 1
            if committed:
                assert view.terminals == before.terminals
            if after is not None:
                assert view == after
            after = view
        finally:
            await coordinator.close()


@pytest.mark.asyncio
async def test_same_boot_uncertain_start_only_own_completed_attempt_is_recoverable(
    lifecycle, monkeypatch
):
    manager, _, service, owners, coordinators = lifecycle
    coordinator = coordinators[-1]
    original = coordinator._repository.apply

    def uncertain(command):
        result = original(command)
        if command.kind == "start":
            raise StateError("state_store_uncertain", uncertain=True)
        return result

    monkeypatch.setattr(coordinator._repository, "apply", uncertain)
    assert (await send(manager, "activate_domain"))[
        "error_type"
    ] == "state_store_uncertain"
    assert not owners and service.capacity is None
    monkeypatch.setattr(coordinator._repository, "apply", original)
    await coordinator.reconcile()
    old = coordinator.snapshot().executions[0]
    other = DomainManager(default_config(), service, state_coordinator=coordinator)
    assert (await send(other, "activate_domain"))["error_type"] == "state_store_busy"
    assert coordinator.snapshot().executions[0].stopped_at is None
    result = await send(manager, "activate_domain")
    assert result["state"] == "active" and len(owners) == 1
    assert result["execution_id"] != old.execution_id
    assert next(
        e
        for e in coordinator.snapshot().executions
        if e.execution_id == old.execution_id
    ).stopped_at


@pytest.mark.asyncio
async def test_settled_stop_storage_failure_releases_actual_ownership(lifecycle):
    manager, _, service, owners, coordinators = lifecycle
    await send(manager, "activate_domain")
    coordinator = coordinators[-1]
    coordinator._health = "state_store_failed"
    result = await send(manager, "deactivate_domain")
    assert owners[0].stopped.is_set()
    assert result["state"] == "inactive" and service.reservation is None
    assert result["state_store"]["error_type"] == "state_store_failed"
    assert coordinator.snapshot().executions[0].stopped_at is None
    assert (await send(manager, "activate_domain"))[
        "error_type"
    ] == "state_store_failed"
    await coordinator.reconcile()
    resumed = await send(manager, "activate_domain")
    assert resumed["state"] == "active" and len(owners) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    ["pending", "completed", "mismatch", "domain_mismatch", "no_lease", "unavailable"],
)
async def test_note_reconciliation_requires_owned_exact_turn_and_preserves_truth(
    lifecycle, mode
):
    manager, _, service, _, _ = lifecycle
    await send(manager, "activate_domain")
    session = manager._current("engineering")
    intent = TurnIntent(
        str(uuid4()),
        "note",
        service.owner_run_id,
        "backend-architect",
        "engineering",
        session.domain_session_id,
        "exact task",
        session._workspace.workspace_id,
    )
    if mode == "domain_mismatch":
        intent = replace(intent, domain_id="core")
    snapshot = service.memory.begin_turn(intent)
    active = dict(
        session_id=session.domain_session_id, execution_id=session.execution_id
    )
    record = replace(
        request(active, "note", "exact task"),
        turn_id=intent.turn_id,
        memory_revision=snapshot.revision,
        disposition="recovered",
    )
    terminal = TerminalRecord(
        record.session_id,
        record.request_id,
        1,
        dict(packet(record), recovered=True, reason="interrupted"),
        4,
    )
    if mode == "completed":
        service.memory.finish_turn(
            intent.turn_id, outcome="success", output="real result", delta=None
        )
    if mode == "mismatch":
        record = replace(record, agent_id="other-agent")
    if mode == "unavailable":
        service.memory._directory.joinpath("TODO.md").write_text("invalid")
    before = {p.name: p.read_bytes() for p in service.memory._directory.glob("*.md")}
    recovery = importlib.import_module("bridge.session_recovery")
    result = await recovery.reconcile_memory(
        service, record, terminal, lease=None if mode == "no_lease" else session._lease
    )
    assert result["saved"] is (mode == "pending")
    if mode != "pending":
        assert result["error_type"]
        assert {
            p.name: p.read_bytes() for p in service.memory._directory.glob("*.md")
        } == before
    else:
        assert result["note_state"] == "interrupted"
        again = await recovery.reconcile_memory(
            service, record, terminal, lease=session._lease
        )
        assert again == result
    if mode == "unavailable":
        # Restore the fixture's canonical documents so its ordinary close can drain.
        for name, value in before.items():
            if name == "TODO.md":
                value = snapshot.todo.encode()
            service.memory._directory.joinpath(name).write_bytes(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["sdk", "metadata", "image", "uncertain_fsync"])
async def test_cancelled_shutdown_drains_each_owned_cleanup_boundary(
    lifecycle, monkeypatch, phase
):
    manager, _, service, owners, coordinators = lifecycle
    await send(manager, "activate_domain")
    coordinator = coordinators[-1]
    session = manager._current("engineering")
    entered, release = threading.Event(), threading.Event()
    sdk_release = asyncio.Event()
    if phase == "sdk":
        owners[0].stop_gate = sdk_release
    elif phase == "metadata":
        original = service.memory.checkpoint_lifecycle

        def checkpoint(**kwargs):
            entered.set()
            assert release.wait(5)
            return original(**kwargs)

        monkeypatch.setattr(service.memory, "checkpoint_lifecycle", checkpoint)
    else:
        image = coordinator._repository._image
        original = os.fsync
        identity = os.fstat(image._parent).st_ino

        def fsync(fd):
            if os.fstat(fd).st_ino == identity:
                entered.set()
                assert release.wait(5)
                if phase == "uncertain_fsync":
                    raise OSError("injected parent synchronization failure")
            original(fd)

        monkeypatch.setattr(os, "fsync", fsync)
    stopping = asyncio.create_task(manager.shutdown())
    try:
        if phase == "sdk":
            await asyncio.wait_for(owners[0].stopped.wait(), 3)
        else:
            assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 3), 4)
        assert service.reservation.held and service.capacity is session
        for _ in range(2):
            stopping.cancel()
            await asyncio.sleep(0)
            assert not stopping.done() and session._lease.held
        with pytest.raises(StateError, match="state_store_busy"):
            LazySQLiteStateRepository(
                service.workspace.common_git_dir, service.workspace.project_id
            ).load()
    finally:
        release.set()
        sdk_release.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert (
        session.clean_inactive and not session._lease.held and service.capacity is None
    )
    assert not coordinator._operations and not manager._operations
    assert coordinator.health == (
        "state_store_uncertain" if phase == "uncertain_fsync" else None
    )


@pytest.mark.asyncio
async def test_unprepared_observation_does_not_latch_absent_state(tmp_path):
    from bridge.project_service import ProjectService
    from bridge.server import BridgeServer
    from bridge.tests.test_workspace import repository

    root = repository(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    config = replace(default_config(), workspace_root_dir=root)
    service = ProjectService(config, runtime_root=runtime, owner_run_id=str(uuid4()))
    server = BridgeServer(config=config, project_service=service)
    await server._ensure_application_state()
    assert server.application_state is None
    assert not (root / ".git/plaza/application-state").exists()
    try:
        await service.start()
        await service._bootstrap_task
        await server._ensure_application_state()
        assert service.snapshot()["stage"] == "ready"
        assert server.application_state is not None
        assert server.application_state.snapshot() is None
        assert not (root / ".git/plaza/application-state").exists()
    finally:
        await server._shutdown()


@pytest.mark.asyncio
async def test_cancelled_recovery_open_and_close_retain_writer_until_settled(tmp_path):
    common = tmp_path / "common"
    common.mkdir()
    seed(common)
    entered, release = threading.Event(), threading.Event()

    def factory():
        repository = LazySQLiteStateRepository(common, "project")
        original = repository.apply

        def apply(command):
            if command.kind == "recover":
                entered.set()
                assert release.wait(5)
            return original(command)

        repository.apply = apply
        return repository

    coordinator = StateCoordinator(factory, boot_id=NEW_BOOT)
    opener = asyncio.create_task(coordinator.open())
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 3), 4)
        assert coordinator.snapshot() is None and not coordinator.admission_open
        opener.cancel()
        with pytest.raises(asyncio.CancelledError):
            await opener
        closing = asyncio.create_task(coordinator.close())
        await asyncio.sleep(0)
        for _ in range(2):
            closing.cancel()
            await asyncio.sleep(0)
            assert not closing.done()
        with pytest.raises(StateError, match="state_store_busy"):
            LazySQLiteStateRepository(common, "project").load()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert coordinator._closed and not coordinator._operations
    again = StateCoordinator(
        lambda: LazySQLiteStateRepository(common, "project"), boot_id=NEW_BOOT
    )
    try:
        await again.open()
        assert len(again.snapshot().terminals) == 1
        assert again.snapshot().terminals[0].output_id == 1
    finally:
        await again.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [False, True])
async def test_explicit_start_defers_notes_until_lease_and_reports_discrepancy(
    lifecycle, completed
):
    manager, _, service, owners, coordinators = lifecycle
    await send(manager, "activate_domain")
    session = manager._current("engineering")
    intent = TurnIntent(
        str(uuid4()),
        "recover-note",
        service.owner_run_id,
        "backend-architect",
        "engineering",
        session.domain_session_id,
        "recover exact",
        session._workspace.workspace_id,
    )
    snapshot = service.memory.begin_turn(intent)
    record = replace(
        request(
            dict(
                session_id=session.domain_session_id, execution_id=session.execution_id
            ),
            "recover-note",
            "recover exact",
        ),
        turn_id=intent.turn_id,
        memory_revision=snapshot.revision,
    )
    coordinator = coordinators[-1]
    await coordinator.commit(StateCommand("accept", dict(request=record)))
    if completed:
        await coordinator.commit(
            StateCommand(
                "dispatch",
                dict(session_id=record.session_id, request_id=record.request_id),
            )
        )
        assert service.memory.finish_turn(
            intent.turn_id, outcome="success", output="real complete", delta=None
        ).saved
    await send(manager, "deactivate_domain")
    before = {p.name: p.read_bytes() for p in service.memory._directory.glob("*.md")}
    started = await send(manager, "activate_domain")
    assert started["state"] == "active" and len(owners) == 2
    assert not any(o.calls for o in owners)
    report = started["memory_reconciliation"][0]
    assert report["request_id"] == record.request_id
    assert report["saved"] is (not completed)
    if completed:
        assert report["note_state"] == "success"
        assert report["error_type"] == "memory_outcome_discrepancy"
        assert {
            p.name: p.read_bytes() for p in service.memory._directory.glob("*.md")
        } == before
    terminal = coordinator.snapshot().terminals[0]
    assert terminal.packet["reason"] == ("interrupted" if completed else "not_executed")
    assert terminal.packet["memory"]["saved"] is False
    assert terminal.output_id == 1


@pytest.mark.asyncio
async def test_note_recovery_does_not_steal_foreign_live_run(lifecycle, monkeypatch):
    from bridge.project_memory import ProjectMemoryStore
    from bridge.session_recovery import reconcile_memory

    manager, _, service, _, _ = lifecycle
    await send(manager, "activate_domain")
    session = manager._current("engineering")
    intent = TurnIntent(
        str(uuid4()),
        "foreign-note",
        service.owner_run_id,
        "backend-architect",
        "engineering",
        session.domain_session_id,
        "foreign exact",
        session._workspace.workspace_id,
    )
    snapshot = service.memory.begin_turn(intent)
    record = replace(
        request(
            dict(
                session_id=session.domain_session_id, execution_id=session.execution_id
            ),
            intent.request_id,
            intent.task,
        ),
        turn_id=intent.turn_id,
        memory_revision=snapshot.revision,
        disposition="recovered",
    )
    terminal = TerminalRecord(
        record.session_id,
        record.request_id,
        1,
        dict(packet(record), recovered=True, reason="interrupted"),
        4,
    )
    before = service.memory.load()
    foreign = ProjectMemoryStore(service.workspace)
    monkeypatch.setattr(service, "require_memory", lambda: foreign)
    result = await reconcile_memory(service, record, terminal, lease=session._lease)
    assert result["saved"] is False and result["error_type"] == "memory_owner_active"
    assert service.memory.load() == before


@pytest.mark.asyncio
async def test_end_with_existing_store_fault_drains_only_exact_owner(lifecycle):
    manager, _, service, owners, coordinators = lifecycle
    first = await send(manager, "activate_domain")
    coordinator = coordinators[-1]
    coordinator._health = "state_store_failed"
    stale = await send(
        manager,
        "end_domain_session",
        domain_session_id=first["domain_session_id"],
        expected_domain_revision="0",
    )
    assert stale["error_type"] == "stale_domain_revision"
    assert not owners[0].stopped.is_set() and service.reservation.held
    wrong = await send(manager, "end_domain_session", domain_session_id=str(uuid4()))
    assert wrong["error_type"] == "session_unavailable"
    assert not owners[0].stopped.is_set() and service.reservation.held
    result = await send(
        manager, "end_domain_session", domain_session_id=first["domain_session_id"]
    )
    assert result["error_type"] == "state_store_failed"
    assert owners[0].stopped.is_set() and service.reservation is None
    assert (
        service.capacity is None and coordinator.snapshot().sessions[0].ended_at is None
    )
    assert (
        manager.snapshot("engineering")["domain_session_id"]
        == first["domain_session_id"]
    )
    assert manager.snapshot("engineering")["state"] == "inactive"
    await coordinator.reconcile()
    ended = await send(
        manager, "end_domain_session", domain_session_id=first["domain_session_id"]
    )
    assert ended["state"] == "inactive" and ended["domain_session_id"] is None
    assert coordinator.snapshot().sessions[0].ended_at
    assert len(owners) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "memory"])
async def test_runtime_policy_protects_domain_but_reconciles_legacy_extra(
    tmp_path, backend
):
    from bridge.project_memory import ProjectMemoryStore
    from bridge.project_service import ProjectService
    from bridge.server import BridgeServer
    from bridge.readiness import owned_io
    from bridge.tests.test_workspace import repository
    from bridge.workspace import inspect_project

    root = repository(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    old = ProjectMemoryStore(inspect_project(root))
    old.initialize()
    old.attach_run("old-owner")
    domain = TurnIntent(
        str(uuid4()),
        "old-domain",
        "old-owner",
        "backend-architect",
        "engineering",
        str(uuid4()),
        "domain pending",
    )
    extra = TurnIntent(
        str(uuid4()),
        "old-extra",
        "old-owner",
        "story-weaver",
        None,
        None,
        "extra pending",
    )
    old.begin_turn(domain)
    old.begin_turn(extra)
    _, marker = old._run_paths("old-owner")
    marker_bytes = marker.read_bytes()
    old._runs.pop("old-owner").close()
    config = replace(
        default_config(), workspace_root_dir=root, domain_state_backend=backend
    )
    service = ProjectService(config, runtime_root=runtime, owner_run_id=str(uuid4()))
    server = BridgeServer(config=config, project_service=service)

    def states():
        with service.require_memory()._operation() as (check, _):
            value, _, _, _ = service.require_memory()._read(check)
            return {i["turn_id"]: i["state"] for i in value["items"]}

    try:
        await service.start()
        await service._bootstrap_task
        await server._ensure_application_state()
        assert (await owned_io(states))[domain.turn_id] == "pending"
        current = TurnIntent(
            str(uuid4()),
            "new-extra",
            service.owner_run_id,
            "story-weaver",
            None,
            None,
            "new extra",
        )
        await service.prepare_memory_turn(current)
        result = await owned_io(
            service.require_memory().finish_turn,
            current.turn_id,
            outcome="success",
            output="done",
            delta=None,
        )
        assert result.saved
        observed = await owned_io(states)
        assert observed[domain.turn_id] == "pending"
        assert observed[extra.turn_id] == "interrupted"
        assert marker.read_bytes() == marker_bytes
        assert not (root / ".git/plaza/application-state").exists()
    finally:
        await server._shutdown()
