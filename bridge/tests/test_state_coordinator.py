"""Real serialized images behind deterministic worker barriers, never model calls."""

import asyncio
import errno
import hashlib
import os
import stat
import threading
from uuid import uuid4

import pytest

from bridge.application_state import (
    COMPLETION_ALLOWANCE_BYTES,
    RequestRecord,
    StateCommand,
    StateError,
)


def start(revision=0):
    return StateCommand(
        "start",
        dict(
            domain_id="engineering",
            expected_domain_revision=revision,
            boot_id=str(uuid4()),
            execution_id=str(uuid4()),
            timestamp="now",
        ),
    )


async def opened(tmp_path):
    from bridge.state_coordinator import StateCoordinator, LazySQLiteStateRepository

    coordinator = StateCoordinator(
        lambda: LazySQLiteStateRepository(tmp_path, "project")
    )
    await coordinator.open()
    initial = await coordinator.commit(start())
    return coordinator, initial


async def wait_thread(event):
    assert await asyncio.wait_for(asyncio.to_thread(event.wait, 3), 4)


def block_directory_fsync(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = os.fsync

    def fsync(fd):
        original(fd)
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            entered.set()
            assert release.wait(5), "test did not release worker"

    monkeypatch.setattr(os, "fsync", fsync)
    return entered, release


@pytest.mark.asyncio
async def test_commit_publishes_only_after_fsync(tmp_path, monkeypatch):
    coordinator, initial = await opened(tmp_path)
    before = coordinator.snapshot()
    entered, release = block_directory_fsync(monkeypatch)
    command = StateCommand(
        "stop",
        dict(
            execution_id=initial.result["execution_id"],
            outcome="stopped",
            timestamp="later",
        ),
    )
    writer = asyncio.create_task(coordinator.commit(command))
    try:
        await wait_thread(entered)
        assert not writer.done()
        assert coordinator.snapshot() == before
        release.set()
        commit = await writer
        assert coordinator.snapshot() == commit.view
        assert commit.view.revision == before.revision + 1
    finally:
        release.set()
        await coordinator.close()


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_cancel_writer(tmp_path, monkeypatch):
    coordinator, initial = await opened(tmp_path)
    entered, release = block_directory_fsync(monkeypatch)
    writer = asyncio.create_task(
        coordinator.commit(
            StateCommand(
                "stop",
                dict(
                    execution_id=initial.result["execution_id"],
                    outcome="stopped",
                    timestamp="later",
                ),
            )
        )
    )
    try:
        await wait_thread(entered)
        writer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(writer, 1)
        closing = asyncio.create_task(coordinator.close())
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        await closing
        assert coordinator.snapshot().executions[0].stopped_at == "later"
        # Close released the actual OS writer authority only after publication.
        from bridge.state_coordinator import StateCoordinator, LazySQLiteStateRepository

        reopened = StateCoordinator(
            lambda: LazySQLiteStateRepository(tmp_path, "project")
        )
        await reopened.open()
        assert reopened.snapshot() == coordinator.snapshot()
        await reopened.close()
    finally:
        release.set()
        await coordinator.close()


@pytest.mark.asyncio
async def test_uncertain_commit_closes_admission(tmp_path, monkeypatch):
    coordinator, initial = await opened(tmp_path)
    before = coordinator.snapshot()
    original = os.fsync

    def fail_parent(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "private filesystem detail")
        original(fd)

    monkeypatch.setattr(os, "fsync", fail_parent)
    try:
        with pytest.raises(StateError, match="state_store_uncertain"):
            await coordinator.commit(
                StateCommand(
                    "stop",
                    dict(
                        execution_id=initial.result["execution_id"],
                        outcome="stopped",
                        timestamp="later",
                    ),
                )
            )
        transaction_id = coordinator.uncertain_transaction_id
        assert transaction_id is not None
        assert not coordinator.admission_open
        assert coordinator.health == "state_store_uncertain"
        assert coordinator.snapshot() == before
        with pytest.raises(StateError, match="state_store_uncertain"):
            await coordinator.commit(start(2))
        monkeypatch.setattr(os, "fsync", original)
        await coordinator.reconcile()
        assert coordinator.admission_open
        assert coordinator.uncertain_transaction_id is None
        assert coordinator.snapshot().revision == before.revision + 1
        assert coordinator.snapshot().executions[0].stopped_at == "later"
        # This is reconciliation, not a retry: one stop revision only.
        commit = await coordinator.commit(start(2))
        assert commit.view.revision == before.revision + 2
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_heartbeat_and_replay_during_slow_write(tmp_path, monkeypatch):
    coordinator, initial = await opened(tmp_path)
    sid = initial.result["session_id"]
    record = RequestRecord(
        sid,
        "request",
        initial.result["execution_id"],
        "agent",
        "task",
        hashlib.sha256(b"task").hexdigest(),
        str(uuid4()),
        1,
        "accepted",
        COMPLETION_ALLOWANCE_BYTES,
    )
    await coordinator.commit(StateCommand("accept", {"request": record}))
    await coordinator.commit(
        StateCommand(
            "terminal",
            dict(
                session_id=sid,
                request_id="request",
                packet=dict(
                    request_id="request",
                    agent_id="agent",
                    task="task",
                    output="answer",
                    nested={"n": 1},
                ),
            ),
        )
    )
    entered, release = block_directory_fsync(monkeypatch)
    writer = asyncio.create_task(
        coordinator.commit(
            StateCommand(
                "stop",
                dict(
                    execution_id=initial.result["execution_id"],
                    outcome="stopped",
                    timestamp="later",
                ),
            )
        )
    )
    try:
        await wait_thread(entered)
        ticks = []

        async def heartbeat():
            for i in range(5):
                ticks.append(i)
                await asyncio.sleep(0)

        await asyncio.wait_for(heartbeat(), 1)
        assert len(ticks) == 5
        replay = coordinator.replay(sid, 0)
        assert replay.entries[0]["output_id"] == "1"
        replay.entries[0]["nested"]["n"] = 99
        copied = coordinator.snapshot()
        copied.terminals[0].packet["nested"]["n"] = 88
        assert coordinator.replay(sid, 0).entries[0]["nested"]["n"] == 1
        assert coordinator.find_request(sid, "request").disposition == "terminal"
        assert coordinator.find_request(sid, "missing") is None
        assert not writer.done()
        release.set()
        await writer
    finally:
        release.set()
        await coordinator.close()


@pytest.mark.asyncio
async def test_backend_switch_is_not_migration(tmp_path):
    from bridge.state_coordinator import (
        StateCoordinator,
        LazySQLiteStateRepository,
        VolatileStateRepository,
    )

    disk, saved = await opened(tmp_path)
    await disk.close()
    memory = StateCoordinator(lambda: VolatileStateRepository("project"))
    await memory.open()
    assert memory.snapshot() is None
    volatile = await memory.commit(start())
    assert volatile.result["session_id"] != saved.result["session_id"]
    await memory.close()
    disk = StateCoordinator(lambda: LazySQLiteStateRepository(tmp_path, "project"))
    await disk.open()
    assert disk.snapshot() == saved.view
    await disk.close()


@pytest.mark.asyncio
async def test_missing_store_read_does_not_initialize(tmp_path):
    from bridge.state_coordinator import StateCoordinator, LazySQLiteStateRepository

    coordinator = StateCoordinator(
        lambda: LazySQLiteStateRepository(tmp_path, "project")
    )
    await coordinator.open()
    try:
        assert coordinator.snapshot() is None
        assert list(tmp_path.iterdir()) == []
        with pytest.raises(Exception) as error:
            coordinator.replay(str(uuid4()), 0)
        assert error.value.code == "session_unavailable"
        await coordinator.commit(start())
        assert (tmp_path / "plaza/application-state/state.sqlite3").exists()
    finally:
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_number", [errno.ENOSPC, errno.EROFS])
async def test_known_failure_preserves_view_and_closes_admission(
    tmp_path, monkeypatch, error_number
):
    coordinator, initial = await opened(tmp_path)
    before = coordinator.snapshot()

    def fail_write(*args):
        raise OSError(error_number, "private storage detail")

    monkeypatch.setattr(os, "write", fail_write)
    try:
        with pytest.raises(StateError, match="state_store_failed"):
            await coordinator.commit(
                StateCommand(
                    "stop",
                    dict(
                        execution_id=initial.result["execution_id"],
                        outcome="stopped",
                        timestamp="later",
                    ),
                )
            )
        assert coordinator.snapshot() == before
        assert not coordinator.admission_open
        with pytest.raises(StateError, match="state_store_failed"):
            await coordinator.commit(start())
    finally:
        await coordinator.close()


@pytest.mark.asyncio
async def test_second_bridge_busy_until_owned_close(tmp_path):
    from bridge.state_coordinator import StateCoordinator, LazySQLiteStateRepository

    first, _ = await opened(tmp_path)
    second = StateCoordinator(lambda: LazySQLiteStateRepository(tmp_path, "project"))
    try:
        with pytest.raises(StateError, match="state_store_busy"):
            await second.open()
        assert not second.admission_open
    finally:
        await second.close()
        await first.close()


@pytest.mark.asyncio
async def test_pending_close_cancellation_still_owns_worker(tmp_path, monkeypatch):
    coordinator, initial = await opened(tmp_path)
    entered, release = block_directory_fsync(monkeypatch)
    writer = asyncio.create_task(
        coordinator.commit(
            StateCommand(
                "stop",
                dict(
                    execution_id=initial.result["execution_id"],
                    outcome="stopped",
                    timestamp="later",
                ),
            )
        )
    )
    await wait_thread(entered)
    closing = asyncio.create_task(coordinator.close())
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await writer
    with pytest.raises(asyncio.CancelledError):
        await closing
    await coordinator.close()


@pytest.mark.asyncio
async def test_repository_lifetime_stays_on_one_worker(tmp_path):
    from bridge.state_coordinator import StateCoordinator, LazySQLiteStateRepository

    calls = []

    class Tracked(LazySQLiteStateRepository):
        def __init__(self):
            calls.append(("create", threading.get_ident()))
            super().__init__(tmp_path, "project")

        def load(self):
            calls.append(("load", threading.get_ident()))
            return super().load()

        def apply(self, command):
            calls.append(("apply", threading.get_ident()))
            return super().apply(command)

        def close(self):
            calls.append(("close", threading.get_ident()))
            return super().close()

    coordinator = StateCoordinator(Tracked)
    await coordinator.open()
    await coordinator.commit(start())
    await coordinator.close()
    assert [name for name, _ in calls] == ["create", "load", "apply", "close"]
    assert len({ident for _, ident in calls}) == 1
    assert calls[0][1] != threading.get_ident()


@pytest.mark.asyncio
async def test_cancelled_uncertain_write_fences_already_queued_command(
    tmp_path, monkeypatch
):
    coordinator, initial = await opened(tmp_path)
    before = coordinator.snapshot()
    entered, release = threading.Event(), threading.Event()
    original = os.fsync

    def fail_parent(fd):
        original(fd)
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            entered.set()
            assert release.wait(5)
            raise OSError(errno.EIO, "uncertain parent fsync")

    monkeypatch.setattr(os, "fsync", fail_parent)
    stop = StateCommand(
        "stop",
        dict(
            execution_id=initial.result["execution_id"],
            outcome="stopped",
            timestamp="later",
        ),
    )
    writer = asyncio.create_task(coordinator.commit(stop))
    try:
        await wait_thread(entered)
        writer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await writer
        queued = asyncio.create_task(coordinator.commit(start(2)))
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(StateError, match="state_store_uncertain"):
            await queued
        assert coordinator.snapshot() == before
        assert coordinator.uncertain_transaction_id == 2  # Start was transaction 1.
        monkeypatch.setattr(os, "fsync", original)
        await coordinator.reconcile()
        assert len(coordinator.snapshot().executions) == 1
        assert coordinator.snapshot().revision == before.revision + 1
    finally:
        release.set()
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["project_id", "instance_id", "revision", "known_failure_revision"]
)
async def test_untrusted_reconciliation_keeps_admission_closed(
    tmp_path, monkeypatch, change
):
    from dataclasses import replace
    from bridge.state_coordinator import StateCoordinator, LazySQLiteStateRepository

    class Untrusted(LazySQLiteStateRepository):
        def reconcile(self):
            view = super().reconcile()
            if change == "known_failure_revision":
                return replace(view, revision=view.revision + 1)
            return replace(
                view, **{change: 999 if change == "revision" else "different"}
            )

    coordinator = StateCoordinator(lambda: Untrusted(tmp_path, "project"))
    await coordinator.open()
    initial = await coordinator.commit(start())
    before = coordinator.snapshot()
    original = os.fsync

    def fail(fd):
        if change != "known_failure_revision" and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "private")
        if change == "known_failure_revision":
            raise OSError(errno.ENOSPC, "private")
        original(fd)

    monkeypatch.setattr(os, "fsync", fail)
    try:
        with pytest.raises(StateError):
            await coordinator.commit(
                StateCommand(
                    "stop",
                    dict(
                        execution_id=initial.result["execution_id"],
                        outcome="stopped",
                        timestamp="later",
                    ),
                )
            )
        monkeypatch.setattr(os, "fsync", original)
        with pytest.raises(StateError, match="state_store_invalid"):
            await coordinator.reconcile()
        assert not coordinator.admission_open
        assert coordinator.snapshot() == before
    finally:
        await coordinator.close()


def test_explicit_memory_imports_no_disk_image_adapter():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from uuid import uuid4
from bridge.state_coordinator import VolatileStateRepository
from bridge.application_state import StateCommand
repository = VolatileStateRepository("project")
assert repository.load() is None
repository.apply(StateCommand("start", dict(domain_id="engineering", expected_domain_revision=0,
    boot_id=str(uuid4()), execution_id=str(uuid4()), timestamp="now")))
repository.close()
assert "bridge.state_image" not in sys.modules
assert "bridge.project_files" not in sys.modules
""",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_close_drains_reconciliation_waiting_for_pending_writer(
    tmp_path, monkeypatch
):
    coordinator, initial = await opened(tmp_path)
    entered, release = block_directory_fsync(monkeypatch)
    writer = asyncio.create_task(
        coordinator.commit(
            StateCommand(
                "stop",
                dict(
                    execution_id=initial.result["execution_id"],
                    outcome="stopped",
                    timestamp="later",
                ),
            )
        )
    )
    await wait_thread(entered)
    reconciling = asyncio.create_task(coordinator.reconcile())
    await asyncio.sleep(0)
    closing = asyncio.create_task(coordinator.close())
    await asyncio.sleep(0)
    release.set()
    try:
        await writer
        await reconciling
        await closing
        assert coordinator.snapshot().revision == initial.view.revision + 1
        assert not coordinator.admission_open
    finally:
        release.set()
        await coordinator.close()
