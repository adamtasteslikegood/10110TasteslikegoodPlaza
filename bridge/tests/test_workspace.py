"""Existing repository bootstrap uses real Git and preserves operator edits."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from bridge import workspace as ws
from bridge import project_files as files
from bridge.workspace import (
    WorkspaceError,
    inspect_project,
    prepare_worktree,
    validate_workspace,
)


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def repository(tmp_path, name="source"):
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    (root / "tracked.txt").write_text("committed\n")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "seed")
    return root


def bootstrap(tmp_path):
    root = repository(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    return root, runtime, prepare_worktree(inspect_project(root), runtime_root=runtime)


def test_bootstrap_reuses_dirty_worktree(tmp_path):
    root = repository(tmp_path)
    (root / "tracked.txt").write_text("source unsaved\n")
    (root / "secret.txt").write_text("source only")
    before = (git(root, "rev-parse", "HEAD"), git(root, "status", "--porcelain"))
    project = inspect_project(root)
    first = prepare_worktree(project, runtime_root=root)
    key = hashlib.sha256(os.fsencode(project.common_git_dir)).hexdigest()[:16]
    assert first.project_id == key
    assert (
        first.worktree_path
        == tmp_path / ".plaza-worktrees" / f"source-{key}" / "execution"
    )
    assert first.branch == f"plaza/workspace-{key}"
    assert (first.worktree_path / "tracked.txt").read_text() == "committed\n"
    assert not (first.worktree_path / "secret.txt").exists()
    (first.worktree_path / "retained.txt").write_text("unsaved work")
    again = prepare_worktree(project, runtime_root=root)
    assert again == first
    assert (again.worktree_path / "retained.txt").read_text() == "unsaved work"
    assert (
        git(root, "rev-parse", "HEAD"),
        git(root, "status", "--porcelain"),
    ) == before
    record = json.loads((project.common_git_dir / "plaza/workspace.json").read_text())
    assert record["schema_version"] == 1 and record["state"] == "ready"
    assert record["workspace_id"] == first.workspace_id


def test_distinct_clones_do_not_share_project(tmp_path):
    root = repository(tmp_path)
    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(root), str(clone))
    assert inspect_project(root).project_id != inspect_project(clone).project_id


def test_linked_source_reuses_recorded_identity_and_location(tmp_path):
    root, runtime, first = bootstrap(tmp_path)
    linked = tmp_path / "different-name"
    git(root, "worktree", "add", "-b", "linked", str(linked))
    project = inspect_project(linked)
    assert project.project_id == first.project_id
    again = prepare_worktree(project, runtime_root=runtime)
    assert again.worktree_path == first.worktree_path
    assert again.workspace_id == first.workspace_id
    assert again.project_root == linked
    assert again.source_identity == project.root_identity
    assert again.source_identity != first.source_identity


def checkout_sentinels(tmp_path, root):
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    (root / "tracked.txt").write_text("unsaved source sentinel\n")
    (root / "source-only.txt").write_text("UNCOMMITTED-SECRET\n")
    (runtime / "sentinel.txt").write_text("runtime unchanged\n")
    script = tmp_path / "checkout-command.py"
    script.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\nimport sys\n"
        f"source = Path({str(root)!r})\n"
        f"runtime = Path({str(runtime)!r})\n"
        "(source / 'tracked.txt').write_text('executable changed source\\n')\n"
        "(runtime / 'sentinel.txt').write_text('executable changed runtime\\n')\n"
        "secret = (source / 'source-only.txt').read_bytes()\n"
        "Path('copied-source.txt').write_bytes(secret)\n"
        "sys.stdout.buffer.write(secret)\n"
    )
    script.chmod(0o700)
    return runtime, script


def source_state_without_review_filter(root):
    return (
        git(root, "rev-parse", "HEAD"),
        git(
            root,
            "-c",
            "filter.review.process=",
            "-c",
            "filter.review.clean=",
            "-c",
            "filter.review.required=false",
            "status",
            "--porcelain",
        ),
    )


def assert_checkout_sentinels(root, runtime, work, before):
    assert (root / "tracked.txt").read_text() == "unsaved source sentinel\n"
    assert (runtime / "sentinel.txt").read_text() == "runtime unchanged\n"
    assert (root / "source-only.txt").read_text() == "UNCOMMITTED-SECRET\n"
    assert source_state_without_review_filter(root) == before
    assert (work.worktree_path / "tracked.txt").read_text() == "committed\n"
    assert not (work.worktree_path / "source-only.txt").exists()
    assert not (work.worktree_path / "copied-source.txt").exists()


@pytest.mark.parametrize("custom_path", [False, True])
def test_bootstrap_never_executes_post_checkout_hook(tmp_path, custom_path):
    root = repository(tmp_path)
    runtime, script = checkout_sentinels(tmp_path, root)
    hooks = root / ".git/hooks"
    if custom_path:
        hooks = tmp_path / "configured-hooks"
        hooks.mkdir()
        git(root, "config", "core.hooksPath", str(hooks))
    hook = hooks / "post-checkout"
    hook.write_bytes(script.read_bytes())
    hook.chmod(0o700)
    before = source_state_without_review_filter(root)
    original_config = (root / ".git/config").read_bytes()
    work = prepare_worktree(inspect_project(root), runtime_root=runtime)
    assert_checkout_sentinels(root, runtime, work, before)
    assert (root / ".git/config").read_bytes() == original_config


@pytest.mark.parametrize("driver", ["smudge", "process"])
@pytest.mark.parametrize("scope", ["local", "global", "execution_include"])
def test_bootstrap_never_executes_external_checkout_filter(
    tmp_path, monkeypatch, driver, scope
):
    root = repository(tmp_path)
    (root / ".gitattributes").write_text("tracked.txt filter=review\n")
    git(root, "add", ".gitattributes")
    git(root, "commit", "-m", "filter attribute")
    runtime, script = checkout_sentinels(tmp_path, root)
    config_path = root / ".git/config"
    if scope != "local":
        xdg = tmp_path / "xdg"
        (xdg / "git").mkdir(parents=True)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
        config_path = xdg / "git/config"
        if scope == "execution_include":
            config_path.write_text(
                f'[includeIf "gitdir:{root}/.git/worktrees/"]\n\tpath = {xdg}/filter-config\n'
            )
            config_path = xdg / "filter-config"
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    git(root, "config", "--file", str(config_path), f"filter.review.{driver}", command)
    git(root, "config", "--file", str(config_path), "filter.review.required", "true")
    before = source_state_without_review_filter(root)
    original_config = config_path.read_bytes()
    work = None
    error = None
    try:
        work = prepare_worktree(inspect_project(root), runtime_root=runtime)
    except WorkspaceError as caught:
        error = caught
    # These assertions precede the success assertion to expose actual side effects
    # even when Git aborts on the intentionally invalid process-filter protocol.
    assert (root / "tracked.txt").read_text() == "unsaved source sentinel\n"
    assert (runtime / "sentinel.txt").read_text() == "runtime unchanged\n"
    assert error is None
    assert_checkout_sentinels(root, runtime, work, before)
    assert config_path.read_bytes() == original_config


def test_unused_global_lfs_filter_does_not_block_ordinary_project(
    tmp_path, monkeypatch
):
    root = repository(tmp_path)
    xdg = tmp_path / "xdg"
    (xdg / "git").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    config_path = xdg / "git/config"
    git(
        root,
        "config",
        "--file",
        str(config_path),
        "filter.lfs.process",
        "missing-git-lfs filter-process",
    )
    git(root, "config", "--file", str(config_path), "filter.lfs.required", "true")
    work = prepare_worktree(inspect_project(root), runtime_root=root)
    assert (work.worktree_path / "tracked.txt").read_text() == "committed\n"


@pytest.mark.parametrize("driver", ["clean", "process", "fsmonitor"])
def test_git_without_filters_status_preserves_sentinels(tmp_path, driver):
    root, runtime, work = bootstrap(tmp_path)
    runtime, script = checkout_sentinels(tmp_path, root)
    (work.worktree_path / ".gitattributes").write_text("tracked.txt filter=review\n")
    (work.worktree_path / "tracked.txt").write_text(
        "execution edited with different byte count\n"
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    key = "core.fsmonitor" if driver == "fsmonitor" else f"filter.review.{driver}"
    git(root, "config", key, command)
    before = (root / ".git/config").read_bytes()
    status = ws.git_without_filters(work.worktree_path, "status", "--porcelain")
    assert "tracked.txt" in status
    assert (root / "tracked.txt").read_text() == "unsaved source sentinel\n"
    assert (runtime / "sentinel.txt").read_text() == "runtime unchanged\n"
    assert not (work.worktree_path / "copied-source.txt").exists()
    assert (root / ".git/config").read_bytes() == before


def replace_source_preserving_common(root):
    before = root.stat()
    common = (root / ".git").stat()
    moved = root.with_name("moved-source")
    root.rename(moved)
    root.mkdir()
    (moved / ".git").rename(root / ".git")
    assert (root.stat().st_dev, root.stat().st_ino) != (before.st_dev, before.st_ino)
    assert ((root / ".git").stat().st_dev, (root / ".git").stat().st_ino) == (
        common.st_dev,
        common.st_ino,
    )


def test_source_binding_identity_survives_same_common_directory_replacement(tmp_path):
    root, runtime, work = bootstrap(tmp_path)
    original = inspect_project(root)
    replace_source_preserving_common(root)
    replacement = inspect_project(root)
    assert replacement.project_id == original.project_id
    assert replacement.root_identity != original.root_identity
    with pytest.raises(WorkspaceError) as error:
        validate_workspace(work, runtime_root=runtime)
    assert error.value.code == "workspace_invalid"
    assert work.source_identity == original.root_identity
    rebound = prepare_worktree(replacement, runtime_root=runtime)
    assert rebound.source_identity == replacement.root_identity
    assert rebound.workspace_id == work.workspace_id
    assert rebound.worktree_path == work.worktree_path
    record = json.loads((work.common_git_dir / "plaza/workspace.json").read_text())
    assert "source_identity" not in record


@pytest.mark.parametrize(
    "kind", ["empty", "non_git", "unborn", "nested", "bare", "missing", "file"]
)
def test_inspection_classifies_without_mutating_source(tmp_path, kind):
    root = tmp_path / "project"
    if kind != "missing":
        root.mkdir()
    if kind == "file":
        root.rmdir()
        root.write_text("sentinel")
    elif kind == "non_git":
        (root / "sentinel").write_text("preserved")
    elif kind == "unborn":
        git(root, "init", "-b", "main")
    elif kind == "bare":
        git(root, "init", "--bare")
    elif kind == "nested":
        parent = repository(tmp_path, "parent")
        root = parent / "nested"
        root.mkdir()
    if kind in ("empty", "non_git", "unborn"):
        project = inspect_project(root)
        assert project.head_commit is None
        with pytest.raises(WorkspaceError) as error:
            prepare_worktree(project, runtime_root=tmp_path / "runtime")
        assert error.value.code == "workspace_not_ready"
    else:
        with pytest.raises(WorkspaceError) as error:
            inspect_project(root)
        assert error.value.code == "workspace_invalid"


@pytest.mark.parametrize(
    "damage",
    [
        "detached",
        "branch",
        "missing",
        "locked",
        "foreign",
        "identity",
        "record",
        "symlink_record",
        "hardlink_record",
    ],
)
def test_invalid_workspace_never_falls_back(tmp_path, damage):
    root, runtime, work = bootstrap(tmp_path)
    record = work.common_git_dir / "plaza/workspace.json"
    source_before = git(root, "status", "--porcelain")
    if damage == "detached":
        git(work.worktree_path, "checkout", "--detach")
    elif damage == "branch":
        git(work.worktree_path, "checkout", "-b", "foreign")
    elif damage == "missing":
        work.worktree_path.rename(work.worktree_path.with_name("saved"))
    elif damage == "locked":
        git(root, "worktree", "lock", str(work.worktree_path))
    elif damage == "foreign":
        (work.git_dir / "gitdir").write_text(str(root / ".git") + "\n")
    elif damage == "identity":
        value = json.loads(record.read_text())
        value["common_identity"] = [0, 0]
        record.write_text(json.dumps(value))
    elif damage == "record":
        record.write_text("{}")
    elif damage == "symlink_record":
        saved = record.with_name("saved.json")
        record.rename(saved)
        record.symlink_to(saved)
    else:
        os.link(record, record.with_name("alias.json"))
    with pytest.raises(WorkspaceError) as error:
        validate_workspace(work, runtime_root=runtime)
    assert error.value.code == "workspace_invalid"
    with pytest.raises(WorkspaceError):
        prepare_worktree(inspect_project(root), runtime_root=runtime)
    assert git(root, "status", "--porcelain") == source_before


@pytest.mark.parametrize("overlap", ["equal", "parent", "child", "symlink"])
def test_execution_cannot_overlap_runtime(tmp_path, overlap):
    root, runtime, work = bootstrap(tmp_path)
    selected = {
        "equal": work.worktree_path,
        "parent": work.worktree_path.parent,
        "child": work.worktree_path / "sub",
        "symlink": tmp_path / "alias",
    }[overlap]
    if overlap == "symlink":
        selected.symlink_to(work.worktree_path, target_is_directory=True)
    with pytest.raises(WorkspaceError, match="disjoint"):
        validate_workspace(work, runtime_root=selected)


@pytest.mark.parametrize("occupied", ["path", "branch", "symlink", "stale"])
def test_bootstrap_never_adopts_occupied_slot(tmp_path, occupied):
    root = repository(tmp_path)
    project = inspect_project(root)
    destination = (
        tmp_path / ".plaza-worktrees" / f"source-{project.project_id}" / "execution"
    )
    if occupied == "branch":
        git(root, "branch", f"plaza/workspace-{project.project_id}")
    elif occupied == "symlink":
        (tmp_path / ".plaza-worktrees").symlink_to(root, target_is_directory=True)
    elif occupied == "stale":
        git(
            root,
            "worktree",
            "add",
            "-b",
            f"plaza/workspace-{project.project_id}",
            str(destination),
        )
        destination.rename(tmp_path / "saved")
    else:
        destination.mkdir(parents=True)
        (destination / "sentinel").write_text("retain")
    with pytest.raises(WorkspaceError) as error:
        prepare_worktree(project, runtime_root=root)
    assert error.value.code == "workspace_invalid"
    if occupied == "path":
        assert (destination / "sentinel").read_text() == "retain"


def test_interrupted_bootstrap_is_durably_marked_before_git(tmp_path, monkeypatch):
    root = repository(tmp_path)
    project = inspect_project(root)
    original = ws._git

    def interrupted(path, *args, **kwargs):
        if args[:2] == ("worktree", "add"):
            marker = json.loads(
                (project.common_git_dir / "plaza/workspace.json").read_text()
            )
            assert marker["state"] == "creating"
            raise OSError("simulated interruption")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(ws, "_git", interrupted)
    with pytest.raises(WorkspaceError):
        prepare_worktree(project, runtime_root=root)
    monkeypatch.setattr(ws, "_git", original)
    with pytest.raises(WorkspaceError) as error:
        prepare_worktree(project, runtime_root=root)
    assert error.value.code == "workspace_invalid"
    assert len(git(root, "worktree", "list", "--porcelain").split("worktree ")) == 2


def test_concurrent_bootstrap_cannot_create_two_workspaces(tmp_path):
    root = repository(tmp_path)
    script = """
from pathlib import Path
import sys
from bridge.workspace import *
try:
    work = prepare_worktree(inspect_project(Path(sys.argv[1])), runtime_root=Path(sys.argv[1]))
    print(work.workspace_id)
except WorkspaceError as error:
    print(error.code)
"""
    before = git(root, "status", "--porcelain")
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda _: subprocess.run(
                    [sys.executable, "-c", script, str(root)],
                    capture_output=True,
                    text=True,
                    timeout=40,
                ),
                range(2),
            )
        )
    for result in results:
        assert result.returncode == 0, result.stderr
    outputs = {result.stdout.strip() for result in results}
    outputs.discard("workspace_busy")
    assert len(outputs) == 1
    assert len(git(root, "worktree", "list", "--porcelain").split("worktree ")) == 3
    assert git(root, "status", "--porcelain") == before


def test_inspection_sanitizes_git_overrides_and_accepts_symlink(tmp_path, monkeypatch):
    root = repository(tmp_path)
    other = repository(tmp_path, "other")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    project = inspect_project(alias)
    assert project.root == root
    assert project.common_git_dir == root / ".git"


def test_detached_source_never_creates_execution(tmp_path):
    root = repository(tmp_path)
    git(root, "checkout", "--detach")
    project = inspect_project(root)
    assert project.source_branch is None
    with pytest.raises(WorkspaceError) as error:
        prepare_worktree(project, runtime_root=root)
    assert error.value.code == "workspace_invalid"
    assert not (tmp_path / ".plaza-worktrees").exists()


def test_selected_execution_cannot_be_reused_as_its_own_source(tmp_path):
    root, runtime, work = bootstrap(tmp_path)
    with pytest.raises(WorkspaceError) as error:
        prepare_worktree(inspect_project(work.worktree_path), runtime_root=runtime)
    assert error.value.code == "workspace_invalid"


def test_replaced_source_directory_invalidates_inspection(tmp_path):
    root = repository(tmp_path)
    project = inspect_project(root)
    root.rename(tmp_path / "saved")
    repository(tmp_path)
    with pytest.raises(WorkspaceError) as error:
        prepare_worktree(project, runtime_root=root)
    assert error.value.code == "workspace_invalid"


def test_git_commands_have_finite_timeouts(tmp_path, monkeypatch):
    root = repository(tmp_path)
    project = inspect_project(root)
    original = subprocess.run
    timeouts = []

    def run(args, **kwargs):
        if args[0] == "git":
            bootstrap_command = ("worktree" in args and "add" in args) or any(
                command in args for command in ("read-tree", "checkout-index")
            )
            timeouts.append((bootstrap_command, kwargs["timeout"]))
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    prepare_worktree(project, runtime_root=root)
    assert timeouts and all(
        timeout == (30 if creation else 5) for creation, timeout in timeouts
    )


@pytest.mark.parametrize("operation", ["read", "replace", "unlink", "lock"])
@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "fifo", "parent_symlink"])
def test_managed_files_reject_unsafe_paths(tmp_path, operation, unsafe):
    target = tmp_path / "target"
    target.write_bytes(b"safe")
    path = tmp_path / "managed"
    if unsafe == "symlink":
        path.symlink_to(target)
    elif unsafe == "hardlink":
        os.link(target, path)
    elif unsafe == "fifo":
        os.mkfifo(path)
    else:
        (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
        path = tmp_path / "alias/target"
    with pytest.raises(OSError):
        if operation == "read":
            files.read_regular(path, max_bytes=10)
        elif operation == "replace":
            files.atomic_replace(path, b"changed")
        elif operation == "unlink":
            files.durable_unlink(path)
        else:
            files.FileLock.acquire(path)
    assert target.read_bytes() == b"safe"


def test_managed_atomic_files_are_bounded_durable_and_lock_inode_stable(
    tmp_path, monkeypatch
):
    events = []
    original = os.fsync
    monkeypatch.setattr(
        os, "fsync", lambda fd: (events.append(os.fstat(fd).st_mode), original(fd))[-1]
    )
    path = tmp_path / "record"
    files.atomic_replace(path, b"abc")
    assert len(events) == 2
    assert files.read_regular(path, max_bytes=3) == b"abc"
    with pytest.raises(OSError):
        files.read_regular(path, max_bytes=2)
    lock_path = tmp_path / "lock"
    first = files.FileLock.acquire(lock_path)
    inode = lock_path.stat().st_ino
    with pytest.raises(BlockingIOError):
        files.FileLock.acquire(lock_path)
    first.close()
    second = files.FileLock.acquire(lock_path)
    second.close()
    assert lock_path.stat().st_ino == inode
    files.durable_unlink(path)
    assert not path.exists()
