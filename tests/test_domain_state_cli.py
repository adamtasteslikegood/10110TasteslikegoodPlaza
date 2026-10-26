"""Offline maintenance exercises the actual project lock and SQLite images."""

from dataclasses import asdict
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from uuid import uuid4

import pytest

from bridge.application_state import MAX_IMAGE_BYTES, RequestRecord, StateCommand
from bridge.sqlite_state import SQLiteStateRepository, initial_image
from bridge.state_image import StateImage
from bridge.workspace import inspect_project

ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-10-26T12:00:00Z"


@pytest.fixture
def cli():
    class RequiredCLI:
        def __getattr__(self, name):
            assert importlib.util.find_spec(
                "scripts.domain_state"
            ), "maintenance CLI missing"
            return getattr(importlib.import_module("scripts.domain_state"), name)

    if importlib.util.find_spec("scripts.domain_state"):
        return importlib.import_module("scripts.domain_state")
    return RequiredCLI()


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(root)], check=True, capture_output=True
    )
    project = inspect_project(root)
    image = StateImage.open(
        project.common_git_dir,
        project.project_id,
        initialize=True,
        initial_image=lambda instance: initial_image(project.project_id, instance),
    )
    repo = SQLiteStateRepository(image)
    yield root, project, image, repo
    repo.close()
    image.close()


def apply(repo, kind, **payload):
    return repo.apply(StateCommand(kind, payload))


def start(repo, domain="core"):
    return apply(
        repo,
        "start",
        domain_id=domain,
        expected_domain_revision=0,
        boot_id=str(uuid4()),
        execution_id=str(uuid4()),
        timestamp=STAMP,
    ).result


def complete(repo, active, output="retained é answer"):
    task = "Review private task\n"
    record = RequestRecord(
        active["session_id"],
        "run-1",
        active["execution_id"],
        "systems-architect",
        task,
        hashlib.sha256(task.encode()).hexdigest(),
        str(uuid4()),
        1,
        "accepted",
        2 * 1024 * 1024,
    )
    apply(repo, "accept", request=record)
    apply(
        repo,
        "terminal",
        session_id=record.session_id,
        request_id=record.request_id,
        packet={
            "type": "domain_result",
            "request_id": record.request_id,
            "domain_session_id": record.session_id,
            "execution_id": record.execution_id,
            "agent_id": record.agent_id,
            "task": task,
            "output": output,
            "memory": {"saved": True},
        },
    )


def end(repo, active):
    revision = apply(
        repo,
        "stop",
        execution_id=active["execution_id"],
        outcome="stopped",
        timestamp=STAMP,
    ).result["domain_revision"]
    apply(
        repo,
        "end",
        session_id=active["session_id"],
        expected_domain_revision=revision,
        actor="user",
        timestamp=STAMP,
    )


def release(store):
    store[3].close()
    store[2].close()


def invoke(cli, store, command, session, output):
    flag = "--output" if command == "export" else "--backup"
    return cli.main(
        ["--workspace", str(store[0]), command, "--session", session, flag, str(output)]
    )


@pytest.mark.parametrize(
    "operation,flag", [("export", "--output"), ("delete-ended", "--backup")]
)
def test_cli_refuses_live_writer(cli, store, tmp_path, operation, flag):
    assert importlib.util.find_spec("scripts.domain_state"), "maintenance CLI missing"
    active = start(store[3])
    target = tmp_path / "export.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/domain_state.py"),
            "--workspace",
            str(store[0]),
            operation,
            "--session",
            active["session_id"],
            flag,
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert result.stderr.strip() == "state_store_busy"
    assert not target.exists()


@pytest.mark.parametrize("stopped", [False, True])
def test_delete_requires_ended_and_backup(cli, store, tmp_path, capsys, stopped):
    active = start(store[3])
    if stopped:
        apply(
            store[3],
            "stop",
            execution_id=active["execution_id"],
            outcome="stopped",
            timestamp=STAMP,
        )
    before = store[2].read()
    release(store)
    backup = tmp_path / "backup.json"
    assert invoke(cli, store, "delete-ended", active["session_id"], backup) == 1
    assert capsys.readouterr().err.strip() == "session_not_ended"
    assert not backup.exists()
    assert (store[2].path / "state.sqlite3").read_bytes() == before


@pytest.mark.parametrize(
    "unsafe",
    ["existing", "symlink", "hardlink", "directory", "parent_symlink", "dotdot"],
)
def test_export_rejects_unsafe_or_existing_path(cli, store, tmp_path, unsafe):
    active = start(store[3])
    before = store[2].read()
    release(store)
    protected = tmp_path / "protected"
    protected.write_bytes(b"operator data")
    target = tmp_path / "export.json"
    if unsafe == "existing":
        target.write_bytes(b"keep")
    elif unsafe == "symlink":
        target.symlink_to(protected)
    elif unsafe == "hardlink":
        os.link(protected, target)
    elif unsafe == "directory":
        target.mkdir()
    elif unsafe == "parent_symlink":
        parent = tmp_path / "linked"
        parent.symlink_to(tmp_path, target_is_directory=True)
        target = parent / "export.json"
    else:
        target = tmp_path / "project" / ".." / "export.json"
    assert invoke(cli, store, "export", active["session_id"], target) == 1
    assert protected.read_bytes() == b"operator data"
    assert (store[2].path / "state.sqlite3").read_bytes() == before
    if unsafe == "existing":
        assert target.read_bytes() == b"keep"


def test_export_versioned_records_hashes_private_and_no_image_mutation(
    cli, store, tmp_path
):
    active = start(store[3])
    complete(store[3], active)
    view = store[3].load()
    before = store[2].read()
    release(store)
    target = tmp_path / "export.json"
    assert invoke(cli, store, "export", active["session_id"], target) == 0
    data = target.read_bytes()
    saved = json.loads(data)
    assert saved["format_version"] == 1
    assert saved["schema_version"] == 1
    assert (saved["project_id"], saved["instance_id"], saved["state_revision"]) == (
        view.project_id,
        view.instance_id,
        view.revision,
    )
    assert saved["records"]["session"] == asdict(view.sessions[0])
    assert saved["records"]["terminals"][0]["packet"]["output"] == "retained é answer"
    assert saved["image_sha256"] == hashlib.sha256(before).hexdigest()
    canonical = json.dumps(
        saved["records"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    assert saved["records_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert b"\xc3\xa9" in data
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.stat().st_nlink == 1
    assert (store[2].path / "state.sqlite3").read_bytes() == before


def test_export_open_stopped_session_preserves_identity(cli, store, tmp_path):
    active = start(store[3])
    apply(
        store[3],
        "stop",
        execution_id=active["execution_id"],
        outcome="stopped",
        timestamp=STAMP,
    )
    before = store[2].read()
    release(store)
    target = tmp_path / "stopped.json"
    assert invoke(cli, store, "export", active["session_id"], target) == 0
    records = json.loads(target.read_bytes())["records"]
    assert records["session"]["ended_at"] is None
    assert records["executions"][0]["stopped_at"] == STAMP
    assert (store[2].path / "state.sqlite3").read_bytes() == before


def test_export_unreconciled_execution_is_observational(cli, store, tmp_path):
    active = start(store[3])
    before = store[2].read()
    release(store)
    target = tmp_path / "unreconciled.json"
    assert invoke(cli, store, "export", active["session_id"], target) == 0
    records = json.loads(target.read_bytes())["records"]
    assert records["session"]["ended_at"] is None
    assert records["executions"][0]["stopped_at"] is None
    assert (store[2].path / "state.sqlite3").read_bytes() == before


@pytest.mark.parametrize(
    "failure", ["existing", "write", "file_fsync", "directory_fsync"]
)
def test_backup_failure_leaves_image_unchanged(
    cli, store, tmp_path, monkeypatch, failure
):
    active = start(store[3])
    complete(store[3], active)
    end(store[3], active)
    before = store[2].read()
    release(store)
    backup = tmp_path / "backup.json"
    if failure == "existing":
        backup.write_bytes(b"keep")
    else:
        original_write, original_fsync = os.write, os.fsync

        def backup_fd(fd):
            return backup.exists() and os.fstat(fd).st_ino == backup.stat().st_ino

        def fail_write(fd, data):
            if failure == "write" and backup_fd(fd):
                original_write(fd, bytes(data[:7]))
                raise OSError("simulated output failure")
            return original_write(fd, data)

        def fail_fsync(fd):
            if failure == "file_fsync" and backup_fd(fd):
                raise OSError("simulated output fsync failure")
            if (
                failure == "directory_fsync"
                and backup.exists()
                and os.fstat(fd).st_ino == tmp_path.stat().st_ino
            ):
                raise OSError("simulated parent fsync failure")
            return original_fsync(fd)

        monkeypatch.setattr(os, "write", fail_write)
        monkeypatch.setattr(os, "fsync", fail_fsync)
    assert invoke(cli, store, "delete-ended", active["session_id"], backup) == 1
    assert (store[2].path / "state.sqlite3").read_bytes() == before
    if failure == "existing":
        assert backup.read_bytes() == b"keep"
    elif failure == "write":
        assert not backup.exists()


def test_delete_reopen_preserves_other_sessions(cli, store, tmp_path):
    removed = start(store[3])
    complete(store[3], removed, output="x" * (256 * 1024))
    end(store[3], removed)
    retained = start(store[3], "engineering")
    complete(store[3], retained)
    before, before_size = store[3].load(), len(store[2].read())
    release(store)
    backup = tmp_path / "backup.json"
    assert invoke(cli, store, "delete-ended", removed["session_id"], backup) == 0
    assert (
        json.loads(backup.read_bytes())["records"]["session"]["session_id"]
        == removed["session_id"]
    )
    image = StateImage.open(store[1].common_git_dir, store[1].project_id)
    repo = SQLiteStateRepository(image)
    try:
        after = repo.load()
        assert after.project_id == before.project_id
        assert after.instance_id == before.instance_id
        assert after.revision == before.revision + 1
        assert after.sessions == tuple(
            s for s in before.sessions if s.session_id != removed["session_id"]
        )
        assert after.terminals == tuple(
            t for t in before.terminals if t.session_id != removed["session_id"]
        )
        assert after.domains == before.domains
        assert len(image.read()) < before_size
        assert len(image.read()) <= MAX_IMAGE_BYTES
    finally:
        repo.close()
        image.close()


def test_export_cap_preflight_creates_no_file(
    cli, store, tmp_path, monkeypatch, capsys
):
    active = start(store[3])
    complete(store[3], active)
    release(store)
    target = tmp_path / "export.json"
    original_open = os.open

    def forbid_output_create(path, flags, *args, **kwargs):
        if path == target.name and flags & os.O_CREAT:
            raise AssertionError("preflight must reject before output creation")
        return original_open(path, flags, *args, **kwargs)

    # The record payload fits, but adding the envelope must fail preflight.
    monkeypatch.setattr(cli, "MAX_EXPORT_BYTES", 1500)
    monkeypatch.setattr(os, "open", forbid_output_create)
    assert invoke(cli, store, "export", active["session_id"], target) == 1
    assert capsys.readouterr().err.strip() == "state_store_quota"
    assert not target.exists()


@pytest.mark.parametrize(
    "value,cap,expected",
    [
        ("éé", 5, None),
        ("éé", 6, b'"\xc3\xa9\xc3\xa9"'),
        ("\n", 3, None),
        ("\n", 4, b'"\\n"'),
    ],
)
def test_export_ceiling_counts_utf8_and_json_escaping(
    cli, tmp_path, monkeypatch, value, cap, expected
):
    target = tmp_path / "bounded.json"
    monkeypatch.setattr(cli, "MAX_EXPORT_BYTES", cap)
    if expected is None:
        from bridge.application_state import StateError

        with pytest.raises(StateError) as caught:
            cli._write_export(target, value)
        assert caught.value.code == "state_store_quota"
        assert not target.exists()
    else:
        cli._write_export(target, value)
        assert target.read_bytes() == expected


def test_missing_store_is_not_initialized(cli, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(root)], check=True, capture_output=True
    )
    assert (
        cli.main(
            [
                "--workspace",
                str(root),
                "export",
                "--session",
                str(uuid4()),
                "--output",
                str(tmp_path / "out.json"),
            ]
        )
        == 1
    )
    assert not (root / ".git/plaza").exists()


def test_cli_calls_no_provider_or_sdk(cli, store, tmp_path, monkeypatch):
    assert importlib.util.find_spec("scripts.domain_state"), "maintenance CLI missing"
    active = start(store[3])
    release(store)
    import builtins

    original = builtins.__import__

    def offline_only(name, *args, **kwargs):
        if name.split(".")[0] in {"anthropic", "claude_agent_sdk"}:
            raise AssertionError("maintenance must remain provider-free")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", offline_only)
    importlib.reload(cli)
    assert (
        invoke(cli, store, "export", active["session_id"], tmp_path / "out.json") == 0
    )


def test_backup_parent_swap_during_final_fsync_prevents_delete(
    cli, store, tmp_path, monkeypatch
):
    active = start(store[3])
    end(store[3], active)
    before = store[2].read()
    release(store)
    parent = tmp_path / "exports"
    parent.mkdir()
    displaced = tmp_path / "displaced"
    backup = parent / "backup.json"
    original = os.fsync
    parent_inode = parent.stat().st_ino
    swapped = False

    def swap_parent(fd):
        nonlocal swapped
        if not swapped and backup.exists() and os.fstat(fd).st_ino == parent_inode:
            parent.rename(displaced)
            parent.mkdir()
            (parent / "backup.json").write_bytes(b"operator data")
            swapped = True
        return original(fd)

    monkeypatch.setattr(os, "fsync", swap_parent)
    assert invoke(cli, store, "delete-ended", active["session_id"], backup) == 1
    assert (parent / "backup.json").read_bytes() == b"operator data"
    assert (store[2].path / "state.sqlite3").read_bytes() == before
