"""Deterministic foreign-reader contention must not reject admission or observation."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import fcntl
import multiprocessing
import os
import threading

import pytest

from bridge import project_files as files
from bridge.project_memory import ProjectMemoryStore, TurnIntent
from bridge.tests.test_workspace import bootstrap
from bridge.workspace import inspect_project, prepare_worktree
from bridge.workspace_lease import WorkspaceLease, observe_reservation


def _reader(workspace, kind, connection):
    """Pause the real reader after it has acquired its real cross-process lock."""
    try:
        if kind == "execution":
            from bridge import workspace_lease

            original = workspace_lease._observe_marker

            def paused(*args):
                connection.send("locked")
                assert connection.recv() == "release"
                return original(*args)

            workspace_lease._observe_marker = paused
            result = observe_reservation(workspace)
            assert result is None
        else:
            store = ProjectMemoryStore(workspace)
            original = store._read

            def paused(*args, **kwargs):
                connection.send("locked")
                assert connection.recv() == "release"
                return original(*args, **kwargs)

            store._read = paused
            store.load()
        connection.send("done")
    except BaseException as error:
        connection.send(repr(error))
        raise
    finally:
        connection.close()


@contextmanager
def paused_reader(workspace, kind):
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_reader, args=(workspace, kind, child))
    process.start()
    child.close()
    try:
        assert parent.poll(10), "reader did not acquire lock"
        assert parent.recv() == "locked"
        yield parent
        assert parent.poll(10), "reader did not complete"
        assert parent.recv() == "done"
        process.join(10)
        assert process.exitcode == 0
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
        process.join(10)


def after_contention(monkeypatch, path, reader, operation, before_release=None):
    """Release the reader only after the contender actually hits its OS lock."""
    original = fcntl.flock
    identity = path.stat()
    blocked = threading.Event()

    def flock(fd, flags):
        try:
            return original(fd, flags)
        except BlockingIOError:
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                blocked.set()
            raise

    monkeypatch.setattr(fcntl, "flock", flock)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(operation)
        try:
            assert blocked.wait(5), "contender did not encounter the held lock"
            if before_release is not None:
                before_release()
        finally:
            reader.send("release")
        return pending.result(timeout=5)


@pytest.mark.parametrize("action", ["prepare", "legacy", "lease", "observe"])
def test_foreign_observer_does_not_reject_execution_admission(
    tmp_path, monkeypatch, action
):
    if action == "legacy":
        from bridge.tests.test_department_workspaces import legacy_workspace

        project, work, value = legacy_workspace(tmp_path)
        work = replace(work, branch=value["branch"])
        root, runtime = project.root, tmp_path / "runtime"
    else:
        root, runtime, work = bootstrap(tmp_path)
    (work.worktree_path / "precious.txt").write_text("unsaved")
    before = {p: p.read_bytes() for p in work.git_dir.rglob("*") if p.is_file()}
    lease = None
    with paused_reader(work, "execution") as reader:

        def operation():
            nonlocal lease
            if action in ("prepare", "legacy"):
                return prepare_worktree(inspect_project(root), runtime_root=runtime)
            if action == "lease":
                lease = WorkspaceLease.acquire(
                    work, domain_id="core", domain_session_id="test"
                )
                return lease.workspace
            return observe_reservation(work)

        try:
            result = after_contention(
                monkeypatch, work.git_dir / "plaza-execution.lock", reader, operation
            )
            if action == "observe":
                assert result is None
                assert {
                    p: p.read_bytes() for p in work.git_dir.rglob("*") if p.is_file()
                } == before
            else:
                assert result.workspace_id == work.workspace_id
                assert result.worktree_path == work.worktree_path
            assert (work.worktree_path / "precious.txt").read_text() == "unsaved"
        finally:
            if lease is not None:
                lease.release(cleanup_confirmed=True)


@pytest.mark.parametrize("action", ["load", "begin", "finish"])
def test_foreign_memory_reader_serializes_short_operations(
    tmp_path, monkeypatch, action
):
    _, _, work = bootstrap(tmp_path)
    store = ProjectMemoryStore(work)
    initial = store.initialize()
    store.attach_run("run")
    turn = TurnIntent("turn", "request", "run", "builder", None, None, "task")
    if action == "finish":
        store.begin_turn(turn)
    try:
        with paused_reader(work, "memory") as reader:

            def operation():
                if action == "load":
                    return store.load()
                if action == "begin":
                    return store.begin_turn(turn)
                return store.finish_turn(
                    "turn", outcome="success", output="done", delta=None
                )

            result = after_contention(
                monkeypatch,
                work.common_git_dir / "plaza/memory.lock",
                reader,
                operation,
            )
            if action == "load":
                assert result == initial
            elif action == "begin":
                assert "pending" in result.todo and turn.turn_id in result.todo
            else:
                assert result.saved
                assert "done" in store.load().progress
    finally:
        store.finish_turn(
            "turn", outcome="cancelled", output="fixture cleanup", delta=None
        )
        store.detach_run("run")


@pytest.mark.parametrize("action", ["prepare", "lease", "observe"])
def test_unknown_marker_free_owner_remains_bounded_and_fail_closed(
    tmp_path, monkeypatch, action
):
    import time
    from bridge.workspace import WorkspaceError

    root, runtime, work = bootstrap(tmp_path)
    monkeypatch.setattr(files, "SHORT_LOCK_SECONDS", 0.04)
    with paused_reader(work, "execution") as reader:
        started = time.monotonic()
        try:
            with pytest.raises(WorkspaceError) as error:
                if action == "prepare":
                    prepare_worktree(inspect_project(root), runtime_root=runtime)
                elif action == "lease":
                    WorkspaceLease.acquire(
                        work, domain_id="core", domain_session_id="test"
                    )
                else:
                    observe_reservation(work)
            assert error.value.code == (
                "cleanup_failed" if action == "observe" else "workspace_busy"
            )
            assert time.monotonic() - started < 2
            assert not (work.git_dir / "plaza-unclean.json").exists()
        finally:
            reader.send("release")


def test_durable_owner_and_unclean_marker_never_wait_or_clear(tmp_path, monkeypatch):
    import json
    from bridge.workspace import WorkspaceError

    root, runtime, work = bootstrap(tmp_path)
    marker = work.git_dir / "plaza-unclean.json"
    lock = files.FileLock.acquire(work.git_dir / "plaza-execution.lock")
    marker.write_text(
        json.dumps(
            dict(
                schema_version=1,
                workspace_id=work.workspace_id,
                domain_id="core",
                domain_session_id="foreign",
                lease_id="foreign",
            )
        )
    )
    before = marker.read_bytes()
    monkeypatch.setattr(
        files.time,
        "sleep",
        lambda _: pytest.fail("durable ownership must fail immediately"),
    )
    try:
        assert observe_reservation(work) == dict(
            domain_id="core", domain_session_id="foreign", cleanup_failed=False
        )
        with pytest.raises(WorkspaceError) as error:
            WorkspaceLease.acquire(work, domain_id="core", domain_session_id="other")
        assert error.value.code == "workspace_busy"
        with pytest.raises(WorkspaceError) as error:
            prepare_worktree(inspect_project(root), runtime_root=runtime)
        assert error.value.code == "workspace_busy"
    finally:
        lock.close()
    assert observe_reservation(work)["cleanup_failed"]
    with pytest.raises(WorkspaceError) as error:
        WorkspaceLease.acquire(work, domain_id="core", domain_session_id="other")
    assert error.value.code == "cleanup_failed"
    assert marker.read_bytes() == before


def test_default_lifetime_lock_is_still_nonblocking(tmp_path, monkeypatch):
    path = tmp_path / "lifetime.lock"
    held = files.FileLock.acquire(path)
    monkeypatch.setattr(
        files.time, "sleep", lambda _: pytest.fail("lifetime locks must not wait")
    )
    try:
        with pytest.raises(BlockingIOError):
            files.FileLock.acquire(path)
    finally:
        held.close()


def test_memory_lock_wait_shares_operation_deadline_and_does_not_write(
    tmp_path, monkeypatch
):
    from bridge.project_memory import MemoryError

    _, _, work = bootstrap(tmp_path)
    store = ProjectMemoryStore(work)
    store.initialize()
    before = {p: p.read_bytes() for p in store._directory.iterdir()}
    held = files.FileLock.acquire(work.common_git_dir / "plaza/memory.lock")
    clock = [0.0]
    monkeypatch.setattr(files.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        files.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    try:
        with pytest.raises(MemoryError):
            store.load()
        assert 1.0 <= clock[0] < 1.01
        assert {p: p.read_bytes() for p in store._directory.iterdir()} == before
    finally:
        held.close()


@pytest.mark.asyncio
async def test_cancelled_memory_admission_drains_contended_worker(
    tmp_path, monkeypatch
):
    import asyncio
    from bridge.readiness import owned_io

    _, _, work = bootstrap(tmp_path)
    store = ProjectMemoryStore(work)
    store.initialize()
    store.attach_run("run")
    turn = TurnIntent("turn", "request", "run", "builder", None, None, "task")
    original = fcntl.flock
    blocked = threading.Event()

    def flock(fd, flags):
        try:
            return original(fd, flags)
        except BlockingIOError:
            blocked.set()
            raise

    try:
        with paused_reader(work, "memory") as reader:
            monkeypatch.setattr(fcntl, "flock", flock)
            task = asyncio.create_task(owned_io(store.begin_turn, turn))
            try:
                assert await asyncio.to_thread(blocked.wait, 5)
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done(), "cancellation must drain the admitted worker"
            finally:
                reader.send("release")
            with pytest.raises(asyncio.CancelledError):
                await task
            assert turn.turn_id in store.load().todo
            assert store.finish_turn(
                "turn", outcome="cancelled", output="not executed", delta=None
            ).saved
    finally:
        store.detach_run("run")


@pytest.mark.parametrize("action", ["observe", "lease"])
def test_lock_replacement_during_wait_never_grants_authority(
    tmp_path, monkeypatch, action
):
    from bridge.workspace import WorkspaceError

    _, _, work = bootstrap(tmp_path)
    path = work.git_dir / "plaza-execution.lock"

    def substitute():
        path.rename(path.with_suffix(".original"))
        path.write_bytes(b"")

    def operation():
        if action == "observe":
            return observe_reservation(work)
        return WorkspaceLease.acquire(work, domain_id="core", domain_session_id="test")

    with paused_reader(work, "execution") as reader:
        with pytest.raises(WorkspaceError) as error:
            after_contention(monkeypatch, path, reader, operation, substitute)
        assert error.value.code == "cleanup_failed"
        assert not (work.git_dir / "plaza-unclean.json").exists()
