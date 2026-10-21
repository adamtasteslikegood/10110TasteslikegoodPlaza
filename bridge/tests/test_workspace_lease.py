"""Session reservations exclude processes and survive uncertain teardown."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from bridge import project_files
from bridge.workspace import WorkspaceError, prepare_worktree, inspect_project
from bridge.workspace_lease import WorkspaceLease
from bridge.tests.test_workspace import bootstrap, git, replace_source_preserving_common


def child_script(work):
    value = asdict(work)
    value = {
        key: str(val) if isinstance(val, Path) else val for key, val in value.items()
    }
    return f"""
import json
from pathlib import Path
from bridge.workspace import ExecutionWorkspace, WorkspaceError
from bridge.workspace_lease import WorkspaceLease
value = json.loads({json.dumps(json.dumps(value))})
for key in ('project_root', 'common_git_dir', 'worktree_path', 'git_dir'):
    value[key] = Path(value[key])
value['source_identity'] = tuple(value['source_identity'])
work = ExecutionWorkspace(**value)
try:
    lease = WorkspaceLease.acquire(work, domain_id='other', domain_session_id='child')
    print('acquired', flush=True)
except WorkspaceError as error:
    print(error.code, flush=True)
"""


def test_session_lease_blocks_other_process(tmp_path):
    root, runtime, work = bootstrap(tmp_path)
    lease = WorkspaceLease.acquire(
        work, domain_id="engineering", domain_session_id="session-1"
    )
    try:
        assert lease.held and lease.workspace == work
        assert (
            lease.domain_id == "engineering" and lease.domain_session_id == "session-1"
        )
        lease.validate()
        path = work.git_dir / "plaza-execution.lock"
        inode = path.stat().st_ino
        result = subprocess.run(
            [sys.executable, "-c", child_script(work)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "workspace_busy"
        with pytest.raises(WorkspaceError) as error:
            WorkspaceLease.acquire(
                work, domain_id="same-process", domain_session_id="session-2"
            )
        assert error.value.code == "workspace_busy"
        assert "engineering" in str(error.value)
    finally:
        lease.release(cleanup_confirmed=True)
    assert not lease.held
    assert path.stat().st_ino == inode
    again = WorkspaceLease.acquire(
        work, domain_id="next", domain_session_id="session-3"
    )
    again.release(cleanup_confirmed=True)
    assert path.stat().st_ino == inode


def test_replaced_source_binding_prevents_reservation(tmp_path):
    root, runtime, work = bootstrap(tmp_path)
    replace_source_preserving_common(root)
    with pytest.raises(WorkspaceError) as error:
        lease = WorkspaceLease.acquire(
            work, domain_id="domain", domain_session_id="session"
        )
        # Clean up a wrongly admitted lease before reporting a failing assertion.
        lease.release(cleanup_confirmed=True)
    assert error.value.code == "workspace_invalid"
    assert not (work.git_dir / "plaza-unclean.json").exists()


def test_replaced_source_binding_fails_held_lease_validation(tmp_path):
    root, runtime, work = bootstrap(tmp_path)
    lease = WorkspaceLease.acquire(
        work, domain_id="domain", domain_session_id="session"
    )
    try:
        replace_source_preserving_common(root)
        with pytest.raises(WorkspaceError) as error:
            lease.validate()
        assert error.value.code == "workspace_invalid"
    finally:
        lease.release(cleanup_confirmed=True)


@pytest.mark.parametrize("phase", ["file", "directory"])
def test_marker_fsync_failure_prevents_acquisition(tmp_path, monkeypatch, phase):
    root, runtime, work = bootstrap(tmp_path)
    original = os.fsync
    original_replace = project_files.atomic_replace
    in_marker_write = False

    def replace(path, data):
        nonlocal in_marker_write
        in_marker_write = path.name == "plaza-unclean.json"
        try:
            return original_replace(path, data)
        finally:
            in_marker_write = False

    failures = []

    def fail(fd):
        is_file = stat.S_ISREG(os.fstat(fd).st_mode)
        if in_marker_write and is_file == (phase == "file"):
            failures.append(fd)
            raise OSError("marker fsync failed")
        return original(fd)

    monkeypatch.setattr(os, "fsync", fail)
    monkeypatch.setattr(project_files, "atomic_replace", replace)
    with pytest.raises(WorkspaceError) as error:
        WorkspaceLease.acquire(work, domain_id="domain", domain_session_id="session")
    assert error.value.code == "cleanup_failed"
    assert len(failures) == 1
    monkeypatch.setattr(os, "fsync", original)
    if phase == "directory":
        assert (work.git_dir / "plaza-unclean.json").exists()
        with pytest.raises(WorkspaceError) as error:
            WorkspaceLease.acquire(work, domain_id="next", domain_session_id="next")
        assert error.value.code == "cleanup_failed"


def test_busy_process_identifies_owner_domain(tmp_path):
    root, runtime, work = bootstrap(tmp_path)
    lease = WorkspaceLease.acquire(
        work, domain_id="engineering", domain_session_id="session"
    )
    try:
        script = child_script(work).replace(
            "print(error.code, flush=True)", "print(str(error), flush=True)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, result.stderr
        assert "engineering" in result.stdout
    finally:
        lease.release(cleanup_confirmed=True)


def test_bootstrap_does_not_mutate_reserved_or_unclean_execution(tmp_path):
    root, runtime, work = bootstrap(tmp_path)
    lease = WorkspaceLease.acquire(
        work, domain_id="engineering", domain_session_id="session"
    )
    record = work.common_git_dir / "plaza/workspace.json"
    before = record.read_bytes()
    try:
        with pytest.raises(WorkspaceError) as error:
            prepare_worktree(inspect_project(root), runtime_root=runtime)
        assert error.value.code == "workspace_busy"
        assert record.read_bytes() == before
    finally:
        lease.release(cleanup_confirmed=True)


def test_killed_owner_blocks_reuse(tmp_path):
    root, runtime, work = bootstrap(tmp_path)
    script = child_script(work) + "\nimport time\ntime.sleep(60)\n"
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "acquired"
    finally:
        child.kill()
        child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()
    inode = (work.git_dir / "plaza-execution.lock").stat().st_ino
    with pytest.raises(WorkspaceError) as error:
        WorkspaceLease.acquire(work, domain_id="next", domain_session_id="new")
    assert error.value.code == "cleanup_failed"
    assert (work.git_dir / "plaza-execution.lock").stat().st_ino == inode


def test_uncertain_cleanup_retains_ownership_and_marker(tmp_path):
    root, runtime, work = bootstrap(tmp_path)
    lease = WorkspaceLease.acquire(
        work, domain_id="domain", domain_session_id="session"
    )
    with pytest.raises(WorkspaceError) as error:
        lease.release(cleanup_confirmed=False)
    assert error.value.code == "cleanup_failed" and lease.held
    with pytest.raises(WorkspaceError) as error:
        WorkspaceLease.acquire(work, domain_id="other", domain_session_id="other")
    assert error.value.code == "workspace_busy"
    lease.release(cleanup_confirmed=True)


def test_marker_unlink_failure_retains_reservation(tmp_path, monkeypatch):
    root, runtime, work = bootstrap(tmp_path)
    lease = WorkspaceLease.acquire(
        work, domain_id="domain", domain_session_id="session"
    )
    original = project_files.durable_unlink

    def fail(path):
        raise OSError("unlink failed")

    monkeypatch.setattr(project_files, "durable_unlink", fail)
    with pytest.raises(WorkspaceError) as error:
        lease.release(cleanup_confirmed=True)
    assert error.value.code == "cleanup_failed" and lease.held
    monkeypatch.setattr(project_files, "durable_unlink", original)
    lease.release(cleanup_confirmed=True)


def test_lease_validation_checks_actual_branch_and_marker(tmp_path):
    root, runtime, work = bootstrap(tmp_path)
    lease = WorkspaceLease.acquire(
        work, domain_id="domain", domain_session_id="session"
    )
    try:
        git(work.worktree_path, "checkout", "-b", "changed")
        with pytest.raises(WorkspaceError) as error:
            lease.validate()
        assert error.value.code == "workspace_invalid"
        git(work.worktree_path, "checkout", work.branch)
        marker = work.git_dir / "plaza-unclean.json"
        original = marker.read_bytes()
        marker.write_text("{}")
        with pytest.raises(WorkspaceError) as error:
            lease.validate()
        assert error.value.code == "cleanup_failed"
        marker.write_bytes(original)
    finally:
        lease.release(cleanup_confirmed=True)


@pytest.mark.parametrize(
    "domain,session",
    [
        ("../invalid", "session"),
        ("", "s"),
        ("ok", ""),
        ("d" * 129, "s"),
        ("d", "é" * 65),
        ("d", "\ud800"),
    ],
)
def test_invalid_lease_identifiers_have_no_execution_marker(tmp_path, domain, session):
    root, runtime, work = bootstrap(tmp_path)
    with pytest.raises(WorkspaceError):
        WorkspaceLease.acquire(work, domain_id=domain, domain_session_id=session)
    assert not (work.git_dir / "plaza-unclean.json").exists()


def test_observation_never_creates_lock_and_free_marker_is_unclean(
    tmp_path, monkeypatch
):
    from bridge.workspace_lease import observe_reservation
    from bridge.tests.test_workspace import bootstrap

    _, _, workspace = bootstrap(tmp_path)
    lock = workspace.git_dir / "plaza-execution.lock"
    lock.unlink()  # Only this fixture's known unheld bootstrap inode.
    monkeypatch.setattr(
        "bridge.project_files.os.fsync",
        lambda _: pytest.fail("read-only observation fsync"),
    )
    assert observe_reservation(workspace) is None
    assert not lock.exists()
    marker = workspace.git_dir / "plaza-unclean.json"
    import json

    marker.write_text(
        json.dumps(
            dict(
                schema_version=1,
                workspace_id=workspace.workspace_id,
                domain_id="old",
                domain_session_id="generation",
                lease_id="old",
            )
        )
    )
    assert observe_reservation(workspace)["cleanup_failed"] is True
    assert not lock.exists()
