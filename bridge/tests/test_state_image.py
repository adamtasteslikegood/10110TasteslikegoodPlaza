"""Application images retain ownership and evidence across lifecycle failures."""

from dataclasses import FrozenInstanceError
import errno
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
from uuid import UUID

import pytest


def module(name):
    assert importlib.util.find_spec(name), f"{name} implementation is missing"
    return importlib.import_module(name)


class RequiredModule:
    def __init__(self, name):
        self.name = name

    def __getattr__(self, attribute):
        return getattr(module(self.name), attribute)


@pytest.fixture
def api():
    return RequiredModule("bridge.state_image"), RequiredModule(
        "bridge.application_state"
    )


@pytest.fixture
def git_dir(tmp_path):
    path = tmp_path / "common.git"
    path.mkdir()
    return path


def state_dir(git_dir):
    return git_dir / "plaza/application-state"


def seed(instance_id):
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE seed (instance_id TEXT NOT NULL)")
        connection.execute("INSERT INTO seed VALUES (?)", (instance_id,))
        connection.commit()
        return connection.serialize()


def initialized(api, git_dir):
    image_module, _ = api
    return image_module.StateImage.open(
        git_dir, "project-a", initialize=True, initial_image=seed
    )


def artifacts(git_dir):
    return {
        path.name: path.read_bytes()
        for path in state_dir(git_dir).iterdir()
        if path.is_file()
    }


def assert_error(api, code, operation, *, uncertain=False):
    with pytest.raises(api[1].StateError) as caught:
        operation()
    assert caught.value.code == code
    assert caught.value.uncertain is uncertain
    assert str(caught.value) == code
    return caught.value


def test_missing_read_does_not_initialize(api, git_dir):
    assert api[0].StateImage.open(git_dir, "project-a") is None
    assert list(git_dir.iterdir()) == []


def test_initialize_and_reopen_preserves_one_instance_and_private_modes(api, git_dir):
    identities = []

    def factory(instance_id):
        identities.append(instance_id)
        return seed(instance_id)

    image = api[0].StateImage.open(
        git_dir, "project-a", initialize=True, initial_image=factory
    )
    try:
        assert identities == [image.instance_id]
        UUID(image.instance_id)
        with sqlite3.connect(":memory:") as connection:
            connection.deserialize(image.read())
            assert connection.execute("SELECT instance_id FROM seed").fetchone() == (
                image.instance_id,
            )
        manifest = json.loads((state_dir(git_dir) / "manifest.json").read_bytes())
        assert manifest == {
            "version": 1,
            "project_id": "project-a",
            "instance_id": image.instance_id,
            "state": "ready",
        }
        for directory in (git_dir / "plaza", state_dir(git_dir)):
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        for path in state_dir(git_dir).iterdir():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert path.stat().st_nlink == 1
        instance_id, before = image.instance_id, artifacts(git_dir)
    finally:
        image.close()
    reopened = api[0].StateImage.open(git_dir, "project-a", initialize=True)
    try:
        assert reopened.instance_id == instance_id
        assert reopened.read() == before["state.sqlite3"]
        assert artifacts(git_dir) == before
    finally:
        reopened.close()
    assert (state_dir(git_dir) / "writer.lock").exists()


def test_second_writer_busy(api, git_dir):
    image = initialized(api, git_dir)
    lock_inode = (state_dir(git_dir) / "writer.lock").stat().st_ino
    try:
        assert_error(
            api,
            "state_store_busy",
            lambda: api[0].StateImage.open(git_dir, "project-a"),
        )
        assert (state_dir(git_dir) / "writer.lock").stat().st_ino == lock_inode
    finally:
        image.close()
    reopened = api[0].StateImage.open(git_dir, "project-a")
    reopened.close()


@pytest.mark.parametrize("initialize", [False, True])
@pytest.mark.parametrize(
    "condition",
    [
        "manifest_without_image",
        "image_before_ready",
        "missing_after_ready",
        "orphan_image",
    ],
)
def test_incomplete_artifacts_block_recreation(api, git_dir, initialize, condition):
    image = initialized(api, git_dir)
    image.close()
    directory = state_dir(git_dir)
    if condition in {"manifest_without_image", "image_before_ready"}:
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["state"] = "initializing"
        manifest_path.write_text(json.dumps(manifest))
    if condition in {"manifest_without_image", "missing_after_ready"}:
        (directory / "state.sqlite3").unlink()
    if condition == "orphan_image":
        (directory / "manifest.json").unlink()
    before = artifacts(git_dir)
    assert_error(
        api,
        "state_store_invalid",
        lambda: api[0].StateImage.open(
            git_dir, "project-a", initialize=initialize, initial_image=seed
        ),
    )
    assert artifacts(git_dir) == before


# Keep the plan's named crash-boundary cases independently selectable.
def test_manifest_without_image_blocks(api, git_dir):
    image = initialized(api, git_dir)
    image.close()
    (state_dir(git_dir) / "state.sqlite3").unlink()
    assert_error(api, "state_store_invalid", lambda: initialized(api, git_dir))


def test_image_before_ready_blocks(api, git_dir):
    image = initialized(api, git_dir)
    image.close()
    path = state_dir(git_dir) / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["state"] = "initializing"
    path.write_text(json.dumps(manifest))
    before = artifacts(git_dir)
    assert_error(api, "state_store_invalid", lambda: initialized(api, git_dir))
    assert artifacts(git_dir) == before


def test_missing_after_ready_blocks(api, git_dir):
    image = initialized(api, git_dir)
    image.close()
    (state_dir(git_dir) / "state.sqlite3").unlink()
    before = artifacts(git_dir)
    assert_error(api, "state_store_invalid", lambda: initialized(api, git_dir))
    assert artifacts(git_dir) == before


def test_orphan_image_blocks(api, git_dir):
    image = initialized(api, git_dir)
    image.close()
    (state_dir(git_dir) / "manifest.json").unlink()
    before = artifacts(git_dir)
    assert_error(api, "state_store_invalid", lambda: initialized(api, git_dir))
    assert artifacts(git_dir) == before


@pytest.mark.parametrize("name", ["state.sqlite3", "manifest.json", "writer.lock"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "public_mode"])
def test_unsafe_inode_rejected(api, git_dir, tmp_path, name, kind):
    image = initialized(api, git_dir)
    image.close()
    path = state_dir(git_dir) / name
    original = path.read_bytes()
    outside = tmp_path / "precious"
    outside.write_bytes(original)
    if kind == "public_mode":
        path.chmod(0o644)
    else:
        path.unlink()
        if kind == "symlink":
            path.symlink_to(outside)
        elif kind == "hardlink":
            os.link(outside, path)
        else:
            os.mkfifo(path)
    assert_error(api, "state_store_invalid", lambda: initialized(api, git_dir))
    assert outside.read_bytes() == original


@pytest.mark.parametrize("name", ["plaza", "plaza/application-state"])
def test_symlink_parent_rejected(api, git_dir, name):
    image = initialized(api, git_dir)
    image.close()
    path = git_dir / name
    displaced = path.with_name(path.name + "-original")
    path.rename(displaced)
    path.symlink_to(displaced, target_is_directory=True)
    assert_error(api, "state_store_invalid", lambda: initialized(api, git_dir))


@pytest.mark.parametrize("operation", ["read", "replace"])
@pytest.mark.parametrize("swap", ["parent", "lock"])
def test_owned_inode_swap_blocks_operations(api, git_dir, operation, swap):
    image = initialized(api, git_dir)
    before = image.read()
    directory = state_dir(git_dir)
    if swap == "parent":
        displaced = directory.with_name("displaced")
        directory.rename(displaced)
        directory.mkdir(mode=0o700)
        for name, value in artifacts_at(displaced).items():
            (directory / name).write_bytes(value)
            (directory / name).chmod(0o600)
    else:
        lock = directory / "writer.lock"
        lock.rename(directory / "original.lock")
        lock.touch(mode=0o600)
    try:
        assert_error(
            api,
            "state_store_invalid",
            lambda: image.read() if operation == "read" else image.replace(seed("new")),
        )
        assert (directory / "state.sqlite3").read_bytes() == before
        if swap == "parent":
            assert (displaced / "state.sqlite3").read_bytes() == before
    finally:
        image.close()


def artifacts_at(directory):
    return {path.name: path.read_bytes() for path in directory.iterdir()}


def test_replace_is_durable_bounded_and_preserves_lock(api, git_dir):
    image = initialized(api, git_dir)
    lock = state_dir(git_dir) / "writer.lock"
    inode = lock.stat().st_ino
    replacement = seed("replacement")
    try:
        image.replace(replacement)
        assert image.read() == replacement
        assert lock.stat().st_ino == inode
        assert {p.name for p in state_dir(git_dir).iterdir()} == {
            "state.sqlite3",
            "manifest.json",
            "writer.lock",
        }
        assert_error(
            api,
            "state_store_quota",
            lambda: image.replace(b"x" * (64 * 1024 * 1024 + 1)),
        )
        assert image.read() == replacement
    finally:
        image.close()
    reopened = api[0].StateImage.open(git_dir, "project-a")
    assert reopened.read() == replacement
    reopened.close()
    reopened.close()
    assert_error(api, "state_store_invalid", reopened.read)


@pytest.mark.parametrize("phase", ["manifest", "image"])
def test_initialization_crash_points_retain_inspection_evidence(
    api, git_dir, monkeypatch, phase
):
    original = os.replace

    def interrupted(source, destination, **kwargs):
        original(source, destination, **kwargs)
        if destination == ("manifest.json" if phase == "manifest" else "state.sqlite3"):
            raise OSError(errno.EIO, "private failure detail")

    monkeypatch.setattr(os, "replace", interrupted)
    assert_error(
        api, "state_store_uncertain", lambda: initialized(api, git_dir), uncertain=True
    )
    monkeypatch.setattr(os, "replace", original)
    directory = state_dir(git_dir)
    assert (
        json.loads((directory / "manifest.json").read_bytes())["state"]
        == "initializing"
    )
    assert (directory / "state.sqlite3").exists() is (phase == "image")
    before = artifacts(git_dir)
    assert_error(api, "state_store_invalid", lambda: initialized(api, git_dir))
    assert artifacts(git_dir) == before


@pytest.mark.parametrize("phase", ["write", "file_fsync", "rename", "parent_fsync"])
def test_failed_replacement_retains_old_or_new_image_and_owned_lock(
    api, git_dir, monkeypatch, phase
):
    image = initialized(api, git_dir)
    before = image.read()
    replacement = seed("replacement")
    original_write, original_fsync, original_replace = os.write, os.fsync, os.replace

    def write(fd, data):
        if phase == "write":
            raise OSError(errno.ENOSPC, "secret filesystem")
        return original_write(fd, data)

    def fsync(fd):
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if phase == ("parent_fsync" if is_directory else "file_fsync"):
            raise OSError(errno.EIO, "secret filesystem")
        return original_fsync(fd)

    def replace(source, destination, **kwargs):
        if phase == "rename":
            raise OSError(errno.EIO, "secret filesystem")
        return original_replace(source, destination, **kwargs)

    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    uncertain = phase in {"rename", "parent_fsync"}
    try:
        assert_error(
            api,
            "state_store_uncertain" if uncertain else "state_store_failed",
            lambda: image.replace(replacement),
            uncertain=uncertain,
        )
        assert image.read() == (replacement if phase == "parent_fsync" else before)
        assert (state_dir(git_dir) / "writer.lock").exists()
        if phase != "parent_fsync":
            assert list(state_dir(git_dir).glob(".*.tmp"))
    finally:
        image.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 2),
        ("project_id", "other"),
        ("instance_id", "not-a-uuid"),
        ("state", "unknown"),
    ],
)
def test_invalid_manifest_is_preserved(api, git_dir, field, value):
    image = initialized(api, git_dir)
    image.close()
    path = state_dir(git_dir) / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest[field] = value
    path.write_text(json.dumps(manifest))
    before = artifacts(git_dir)
    code = "state_store_unsupported" if field == "version" else "state_store_invalid"
    assert_error(api, code, lambda: initialized(api, git_dir))
    assert artifacts(git_dir) == before


def test_corrupt_image_is_returned_for_schema_validation_without_reset(api, git_dir):
    image = initialized(api, git_dir)
    image.close()
    (state_dir(git_dir) / "state.sqlite3").write_bytes(b"corrupt image evidence")
    reopened = initialized(api, git_dir)
    try:
        assert reopened.read() == b"corrupt image evidence"
    finally:
        reopened.close()


def test_initialization_requires_factory_and_supported_sqlite(
    api, git_dir, monkeypatch
):
    assert_error(
        api,
        "state_store_invalid",
        lambda: api[0].StateImage.open(git_dir, "project-a", initialize=True),
    )
    assert list(git_dir.iterdir()) == []
    monkeypatch.setattr(api[0].sqlite3, "Connection", object)
    assert_error(api, "state_store_unsupported", lambda: initialized(api, git_dir))
    assert list(git_dir.iterdir()) == []


def test_shared_packets_are_defensive_copies_and_command_kinds_are_closed(api):
    state = api[1]
    packet = {"output": "saved", "nested": {"items": [1]}}
    terminal = state.TerminalRecord("session", "request", 1, packet, 5)
    command = state.StateCommand("terminal", {"packet": packet})
    view = state.StateView("project", "instance", 1, (), (), (), (), (terminal,))
    commit = state.StateCommit(view, {"packet": packet})
    packet["nested"]["items"].append(2)
    assert terminal.packet["nested"]["items"] == [1]
    assert command.payload["packet"]["nested"]["items"] == [1]
    assert commit.result["packet"]["nested"]["items"] == [1]
    with pytest.raises(FrozenInstanceError):
        terminal.output_id = 2
    with pytest.raises(ValueError):
        state.StateCommand("unknown", {})


@pytest.mark.parametrize("name", ["state.sqlite3", "manifest.json"])
@pytest.mark.parametrize("operation", ["read", "replace"])
def test_missing_owned_artifact_is_never_recreated(api, git_dir, name, operation):
    image = initialized(api, git_dir)
    path = state_dir(git_dir) / name
    path.unlink()
    before = artifacts(git_dir)
    try:
        assert_error(
            api,
            "state_store_invalid",
            lambda: image.read() if operation == "read" else image.replace(seed("new")),
        )
        assert artifacts(git_dir) == before
        assert not path.exists()
    finally:
        image.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("instance_id", "87bc0711-dff6-453a-9a6c-7709e0b95430"),
        ("state", "initializing"),
    ],
)
def test_owned_manifest_change_blocks_new_commit(api, git_dir, field, value):
    image = initialized(api, git_dir)
    path = state_dir(git_dir) / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest[field] = value
    path.write_text(json.dumps(manifest))
    before = artifacts(git_dir)
    try:
        assert_error(api, "state_store_invalid", lambda: image.replace(seed("new")))
        assert artifacts(git_dir) == before
    finally:
        image.close()


@pytest.mark.parametrize(
    "data,code",
    [
        (b'{"version":1,"version":1}', "state_store_invalid"),
        (b"\xff", "state_store_invalid"),
        (b"[" * 1500 + b"0" + b"]" * 1500, "state_store_invalid"),
        (b"x" * 4097, "state_store_quota"),
    ],
)
def test_malformed_manifest_has_bounded_public_error(api, git_dir, data, code):
    image = initialized(api, git_dir)
    image.close()
    (state_dir(git_dir) / "manifest.json").write_bytes(data)
    before = artifacts(git_dir)
    assert_error(api, code, lambda: initialized(api, git_dir))
    assert artifacts(git_dir) == before


def test_parent_swap_during_rename_cannot_redirect_commit(api, git_dir, monkeypatch):
    image = initialized(api, git_dir)
    directory = state_dir(git_dir)
    displaced = directory.with_name("displaced")
    replacement = seed("replacement")
    original_replace = os.replace

    def swap_then_replace(source, destination, **kwargs):
        directory.rename(displaced)
        directory.mkdir(mode=0o700)
        (directory / "state.sqlite3").write_bytes(b"precious unrelated destination")
        return original_replace(source, destination, **kwargs)

    monkeypatch.setattr(os, "replace", swap_then_replace)
    try:
        assert_error(
            api,
            "state_store_uncertain",
            lambda: image.replace(replacement),
            uncertain=True,
        )
        assert (
            directory / "state.sqlite3"
        ).read_bytes() == b"precious unrelated destination"
        assert (displaced / "state.sqlite3").read_bytes() == replacement
        assert (displaced / "writer.lock").exists()
    finally:
        image.close()


def test_successful_commit_fsyncs_image_before_rename_then_parent(
    api, git_dir, monkeypatch
):
    image = initialized(api, git_dir)
    original_fsync, original_replace = os.fsync, os.replace
    events = []

    def fsync(fd):
        events.append(
            "parent_fsync" if stat.S_ISDIR(os.fstat(fd).st_mode) else "image_fsync"
        )
        return original_fsync(fd)

    def replace(source, destination, **kwargs):
        events.append("rename")
        return original_replace(source, destination, **kwargs)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    try:
        image.replace(seed("replacement"))
        assert events == ["image_fsync", "rename", "parent_fsync"]
    finally:
        image.close()


def test_manifest_decoder_recursion_failure_is_typed_and_preserves_evidence(
    api, git_dir, monkeypatch
):
    image = initialized(api, git_dir)
    image.close()
    path = state_dir(git_dir) / "manifest.json"
    original_manifest = path.read_bytes()
    path.write_bytes(b"[" * 1500 + b"0" + b"]" * 1500)
    before = artifacts(git_dir)

    def recursion_failure(data, **kwargs):
        raise RecursionError("private decoder failure")

    # Python 3.12 decodes this nesting; inject the supported-runtime failure
    # deterministically instead of claiming a Python 3.11 runtime execution.
    with monkeypatch.context() as patch:
        patch.setattr(api[0].json, "loads", recursion_failure)
        assert_error(api, "state_store_invalid", lambda: initialized(api, git_dir))
    assert artifacts(git_dir) == before
    path.write_bytes(original_manifest)
    reopened = initialized(api, git_dir)
    reopened.close()
