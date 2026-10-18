"""Bounded archive behavior, including real process locks and failed I/O."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from bridge.config import default_config
from bridge import log_storage as storage
from bridge.log_storage import RunLogWriter, iter_jsonl

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


def config(tmp_path, **overrides):
    return replace(
        default_config(),
        log_dir=tmp_path / "logs",
        transcript_max_record_bytes=4096,
        transcript_max_file_bytes=8192,
        log_max_total_bytes=32768,
        **overrides
    )


def run_dir(writer, cfg):
    return next(
        p for p in (cfg.log_dir / "runs").iterdir() if p.name.endswith(writer.run_id)
    )


def records(path):
    diagnostics = []
    result = list(iter_jsonl(path, on_diagnostic=diagnostics.append))
    assert not diagnostics
    return result


def all_bytes(root):
    return sum(
        p.stat().st_size
        for p in root.rglob("*")
        if p.is_file() and p.name != ".writer.lock"
    )


def manifest(writer, cfg):
    return json.loads((run_dir(writer, cfg) / "manifest.json").read_text())


def test_layout_manifest_stamps_and_clean_close(tmp_path):
    cfg = config(tmp_path)
    writer = RunLogWriter(cfg, "plaza", clock=lambda: NOW)
    assert writer.is_recording
    root = run_dir(writer, cfg)
    before = manifest(writer, cfg)
    assert before["schema_version"] == 1
    assert before["run_id"] == writer.run_id
    assert before["started_at"] == NOW.isoformat()
    assert before["ended_at"] is None
    assert before["status"] == "open"
    assert before["project_label"] == "plaza"
    assert before["settings"] == cfg.effective_settings()
    original = {"content": "héllo 👋", "seq": -1, "run_id": "spoofed"}
    snapshot = original.copy()
    assert writer.append("transcript", original, agent_id="systems-architect")
    assert writer.append("event", {"event": "done"})
    assert original == snapshot
    transcript = records(root / "agents/systems-architect/transcript-0001.jsonl")[0]
    event = records(root / "events-0001.jsonl")[0]
    assert (transcript["seq"], event["seq"]) == (1, 2)
    assert transcript["run_id"] == writer.run_id
    assert transcript["timestamp"] == NOW.isoformat()
    assert transcript["schema_version"] == 1
    writer.close()
    writer.close()
    after = manifest(writer, cfg)
    assert after["status"] == "closed"
    assert after["ended_at"] == NOW.isoformat()
    assert not writer.is_recording
    assert not writer.append("event", {})


def test_same_timestamp_has_unique_runs_and_unclean_close(tmp_path):
    cfg = config(tmp_path)
    first = RunLogWriter(cfg, "plaza", clock=lambda: NOW)
    first.close(clean=False)
    second = RunLogWriter(cfg, "plaza", clock=lambda: NOW)
    assert first.run_id != second.run_id
    assert manifest(first, cfg)["status"] == "open"
    second.close()


@pytest.mark.parametrize(
    "agent", [None, "", "..", "../x", "/tmp/x", "a/b", "x\\y", "x\n", "CON", "LPT1"]
)
def test_invalid_agent_has_no_append_filesystem_effects(tmp_path, capsys, agent):
    cfg = config(tmp_path)
    writer = RunLogWriter(cfg, "plaza")
    before = {p: p.read_bytes() for p in cfg.log_dir.rglob("*") if p.is_file()}
    assert not writer.append("transcript", {"content": "x"}, agent_id=agent)
    assert {p: p.read_bytes() for p in cfg.log_dir.rglob("*") if p.is_file()} == before
    assert capsys.readouterr().err
    writer.close()


@pytest.mark.parametrize("kind", ["event", "transcript"])
def test_utf8_escaping_truncation_rollover_and_no_input_mutation(tmp_path, kind):
    cfg = config(tmp_path)
    writer = RunLogWriter(cfg, "plaza")
    body = 'é😀"\\\n' * 3000
    record = {"content": body}
    for _ in range(6):
        assert writer.append(kind, record, agent_id="agent")
        assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
    files = list(run_dir(writer, cfg).rglob("*.jsonl"))
    assert len(files) >= 2
    for path in files:
        assert path.stat().st_size <= cfg.transcript_max_file_bytes
        for line in path.read_bytes().splitlines(keepends=True):
            assert line.endswith(b"\n")
            assert len(line) <= cfg.transcript_max_record_bytes
            parsed = json.loads(line)
            assert parsed["truncated"] is True
            assert parsed["original_content_bytes"] == len(body.encode())
            assert "[truncated]" in parsed["content"]
    assert record == {"content": body}
    writer.close()


def test_unfittable_metadata_skipped_visibly(tmp_path, capsys):
    cfg = config(tmp_path)
    writer = RunLogWriter(cfg, "plaza")
    assert not writer.append("event", {"metadata": "x" * 5000})
    assert not list(run_dir(writer, cfg).rglob("*.jsonl"))
    assert capsys.readouterr().err
    assert writer.append("event", {"event": "recovered"})
    assert "recover" in capsys.readouterr().err.lower()
    writer.close()


def test_threads_share_monotonic_sequence(tmp_path):
    cfg = config(tmp_path)
    writer = RunLogWriter(cfg, "plaza")
    with ThreadPoolExecutor(max_workers=5) as executor:
        assert all(executor.map(lambda _: writer.append("event", {}), range(80)))
    seq = [
        r["seq"]
        for p in sorted(run_dir(writer, cfg).glob("events-*.jsonl"))
        for r in records(p)
    ]
    assert seq == list(range(1, 81))
    writer.close()


CHILD = """
import sys, time
from pathlib import Path
from dataclasses import replace
from bridge.config import default_config
from bridge.log_storage import RunLogWriter
w = RunLogWriter(replace(default_config(), log_dir=Path(sys.argv[1])), 'child')
print(w.run_id, w.is_recording, flush=True)
time.sleep(60)
"""


def test_real_process_exclusion_independent_roots_and_crash_release(tmp_path):
    cfg = config(tmp_path)
    child = subprocess.Popen(
        [sys.executable, "-u", "-c", CHILD, str(cfg.log_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 8
        while (
            not list(cfg.log_dir.glob("runs/*/manifest.json"))
            and time.monotonic() < deadline
        ):
            assert child.poll() is None
            time.sleep(0.02)
        manifests = list(cfg.log_dir.glob("runs/*/manifest.json"))
        assert len(manifests) == 1
        first = json.loads(manifests[0].read_text())
        contender = RunLogWriter(cfg, "parent")
        assert not contender.is_recording
        assert not contender.append("event", {})
        assert len(list(cfg.log_dir.glob("runs/*"))) == 1
        independent = RunLogWriter(
            replace(cfg, log_dir=tmp_path / "other"), "independent"
        )
        assert independent.is_recording
        independent.close()
        child.kill()
        child.communicate(timeout=5)
        assert contender.append("event", {"event": "after-crash"})
        assert contender.run_id != first["run_id"]
        assert json.loads(manifests[0].read_text())["status"] == "open"
        contender.close()
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)


def test_sealed_current_segments_pruned_but_active_agents_protected(tmp_path):
    cfg = replace(
        config(tmp_path), log_max_total_bytes=12500, transcript_max_file_bytes=4096
    )
    writer = RunLogWriter(cfg, "plaza")
    assert writer.append("transcript", {"content": "a" * 3500}, agent_id="idle")
    idle = run_dir(writer, cfg) / "agents/idle/transcript-0001.jsonl"
    for _ in range(20):
        assert writer.append("event", {"content": "e" * 3500})
        assert idle.exists()
        assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
    assert len(list(run_dir(writer, cfg).glob("events-*.jsonl"))) <= 2
    assert not (run_dir(writer, cfg) / "events-0001.jsonl").exists()
    writer.close()


def test_protected_files_exhaust_quota_then_later_recover(tmp_path, capsys):
    cfg = replace(config(tmp_path), log_max_total_bytes=10000)
    writer = RunLogWriter(cfg, "plaza")
    assert writer.append("transcript", {"content": "x" * 3500}, agent_id="a")
    assert writer.append("transcript", {"content": "x" * 3500}, agent_id="b")
    assert not writer.append("transcript", {"content": "x" * 3500}, agent_id="c")
    assert not writer.is_recording
    assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
    assert capsys.readouterr().err
    assert writer.append("event", {})
    assert writer.is_recording
    writer.close()


def test_age_pruning_and_unknown_file_ownership(tmp_path):
    cfg = config(tmp_path)
    old = RunLogWriter(cfg, "old", clock=lambda: NOW - timedelta(days=30))
    assert old.append("event", {"event": "old"})
    old.close()
    old_root = run_dir(old, cfg)
    # Age uses file mtime, so completed files have their own retention clocks.
    for path in old_root.rglob("*"):
        if path.is_file():
            os.utime(path, (NOW.timestamp() - 30 * 86400,) * 2)
    unknown = old_root / "user.txt"
    unknown.write_text("preserve")
    fake = cfg.log_dir / "runs" / "unrecognized"
    fake.mkdir()
    (fake / "events-0001.jsonl").write_text("preserve")
    writer = RunLogWriter(cfg, "new", clock=lambda: NOW)
    assert not list(old_root.glob("events-*.jsonl"))
    assert unknown.read_text() == "preserve"
    assert (fake / "events-0001.jsonl").read_text() == "preserve"
    writer.close()


def test_oldest_first_retains_manifest_provenance_until_children_removed(tmp_path):
    cfg = replace(
        config(tmp_path), log_max_total_bytes=15000, transcript_max_file_bytes=4096
    )
    old = RunLogWriter(cfg, "old")
    for _ in range(2):
        assert old.append("event", {"content": "x" * 3800})
    old.close()
    old_root = run_dir(old, cfg)
    paths = sorted(old_root.glob("events-*"))
    # Force separate segments with explicit mtime ordering.
    assert paths
    os.utime(paths[0], (NOW.timestamp() - 100,) * 2)
    newer = RunLogWriter(cfg, "new")
    for _ in range(6):
        assert newer.append("event", {"content": "y" * 3800})
        if list(old_root.glob("events-*")):
            assert (old_root / "manifest.json").exists()
        assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
    assert not old_root.exists()
    newer.close()


@pytest.mark.parametrize(
    "target",
    ["runs", "events-0001.jsonl", "agents", "agent", "manifest.json", ".writer.lock"],
)
def test_symlinks_never_reached(tmp_path, target):
    cfg = config(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "sentinel"
    sentinel.write_text("untouched")
    if target in {"runs", ".writer.lock"}:
        cfg.log_dir.mkdir()
        (cfg.log_dir / target).symlink_to(external if target == "runs" else sentinel)
        writer = RunLogWriter(cfg, "plaza")
        assert not writer.is_recording
    else:
        writer = RunLogWriter(cfg, "plaza")
        root = run_dir(writer, cfg)
        if target == "agent":
            (root / "agents").mkdir()
            (root / "agents" / "agent").symlink_to(external, target_is_directory=True)
        elif target == "manifest.json":
            (root / target).unlink()
            (root / target).symlink_to(sentinel)
        else:
            (root / target).symlink_to(external if target == "agents" else sentinel)
        assert not writer.append(
            "transcript" if target in {"agents", "agent"} else "event",
            {},
            agent_id="agent",
        )
    writer.close()
    assert sentinel.read_text() == "untouched"
    assert list(external.iterdir()) == [sentinel]


def test_jsonl_reader_skips_bad_complete_and_incomplete_final_lines(tmp_path):
    path = tmp_path / "broken.jsonl"
    data = b'{"ok":1}\ninvalid\n[]\n\xff\n{"ok":2}\n{"unfinished":true}'
    path.write_bytes(data)
    diagnostics = []
    assert list(iter_jsonl(path, on_diagnostic=diagnostics.append)) == [
        {"ok": 1},
        {"ok": 2},
    ]
    assert len(diagnostics) == 4
    assert path.read_bytes() == data


@pytest.mark.parametrize("failure", ["create", "append", "flush", "replace"])
@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EACCES])
def test_io_failures_suspend_and_recover(tmp_path, monkeypatch, capsys, failure, code):
    cfg = config(tmp_path)
    writer = RunLogWriter(cfg, "plaza")
    module_name = {
        "create": "open",
        "append": "write",
        "flush": "fsync",
        "replace": "replace",
    }[failure]
    original = getattr(storage.os, module_name)

    def fail(*args, **kwargs):
        if failure != "create" or args[1] & os.O_CREAT:
            raise OSError(code, "injected")
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(storage.os, module_name, fail)
        if failure == "replace":
            writer.close()
            assert manifest(writer, cfg)["status"] == "open"
        else:
            assert not writer.append("event", {})
            assert not writer.is_recording
        assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
        assert capsys.readouterr().err
    if failure == "replace":
        writer = RunLogWriter(cfg, "retry")
    assert writer.append("event", {"event": "recovered"})
    writer.close()


def test_partial_write_and_failed_rollback_seals_segment(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    writer = RunLogWriter(cfg, "plaza")
    real_write = storage.os.write
    calls = 0

    def broken_write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, data[:12])
        raise OSError(errno.ENOSPC, "full")

    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "write", broken_write)
        patch.setattr(
            storage.os,
            "ftruncate",
            lambda *a: (_ for _ in ()).throw(OSError(errno.EACCES, "no rollback")),
        )
        assert not writer.append("event", {"event": "failed"})
    assert writer.append("event", {"event": "recovered"})
    paths = sorted(run_dir(writer, cfg).glob("events-*"))
    assert len(paths) == 2
    diagnostics = []
    assert list(iter_jsonl(paths[0], on_diagnostic=diagnostics.append)) == []
    assert diagnostics
    assert records(paths[1])[0]["event"] == "recovered"
    writer.close()


def test_atomic_manifest_temporary_bytes_are_admitted(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    real_write, real_replace = storage.os.write, storage.os.replace

    def check_write(*args, **kwargs):
        result = real_write(*args, **kwargs)
        assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
        return result

    replacements = []

    def check_replace(*args, **kwargs):
        replacements.append(all_bytes(cfg.log_dir))
        assert replacements[-1] <= cfg.log_max_total_bytes
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(storage.os, "write", check_write)
    monkeypatch.setattr(storage.os, "replace", check_replace)
    writer = RunLogWriter(cfg, "plaza")
    for _ in range(40):
        assert writer.append("event", {"content": "x" * 3500})
    writer.close()
    assert len(replacements) == 2
    assert manifest(writer, cfg)["status"] == "closed"


@pytest.mark.parametrize("failure", ["write", "fsync", "replace"])
def test_initial_manifest_failure_retries_without_abandoning_run(
    tmp_path, monkeypatch, failure
):
    cfg = config(tmp_path)
    with monkeypatch.context() as patch:

        def fail(*args, **kwargs):
            raise OSError(errno.ENOSPC, "initial manifest fault")

        patch.setattr(storage.os, failure, fail)
        writer = RunLogWriter(cfg, "plaza")
        assert not writer.is_recording
        assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
    assert writer.append("event", {"event": "recovered"})
    assert len(list((cfg.log_dir / "runs").iterdir())) == 1
    writer.close()


def test_initial_failed_temp_cleanup_stays_charged(tmp_path, monkeypatch):
    cfg = replace(
        config(tmp_path), log_max_total_bytes=4096, transcript_max_file_bytes=4096
    )
    with monkeypatch.context() as patch:

        def fail(*args, **kwargs):
            raise OSError(errno.EACCES, "temporary failure")

        patch.setattr(storage.os, "replace", fail)
        patch.setattr(storage.os, "unlink", fail)
        writer = RunLogWriter(cfg, "plaza")
        assert not writer.is_recording
        for _ in range(8):
            assert not writer.append("event", {})
            assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
    assert writer.append("event", {})
    writer.close()


def test_manifest_read_error_cannot_hide_owned_bytes(tmp_path, monkeypatch):
    cfg = replace(config(tmp_path), log_max_total_bytes=10000)
    old = RunLogWriter(cfg, "old")
    assert old.append("event", {"content": "x" * 3500})
    old.close()
    old_root = run_dir(old, cfg)
    writer = RunLogWriter(cfg, "new")
    real_open = storage.os.open
    old_inode = old_root.stat().st_ino

    def unreadable(path, flags, *args, **kwargs):
        parent = kwargs.get("dir_fd")
        if (
            path == "manifest.json"
            and parent is not None
            and os.fstat(parent).st_ino == old_inode
        ):
            raise OSError(errno.EACCES, "manifest read blocked")
        return real_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "open", unreadable)
        assert not writer.append("event", {"content": "x" * 3500})
        assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
    assert writer.append("event", {"content": "x" * 3500})
    writer.close()


def test_clean_up_empty_managed_agent_directories(tmp_path):
    cfg = config(tmp_path)
    old = RunLogWriter(cfg, "old")
    old.close()
    old_root = run_dir(old, cfg)
    (old_root / "agents" / "empty-agent").mkdir(parents=True)
    os.utime(old_root / "manifest.json", (NOW.timestamp() - 30 * 86400,) * 2)
    writer = RunLogWriter(cfg, "new", clock=lambda: NOW)
    assert not old_root.exists()
    writer.close()


def test_exact_encoded_record_and_file_boundary(tmp_path):
    cfg = replace(config(tmp_path), transcript_max_file_bytes=4096)
    writer = RunLogWriter(cfg, "plaza", clock=lambda: NOW)
    assert writer.append("event", {"content": "x" * 10000})
    first = run_dir(writer, cfg) / "events-0001.jsonl"
    assert first.stat().st_size == 4096
    assert writer.append("event", {"event": "next"})
    assert first.stat().st_size == 4096
    assert (run_dir(writer, cfg) / "events-0002.jsonl").exists()
    writer.close()


def test_manifest_replacement_requires_space_for_both_copies(
    tmp_path, monkeypatch, capsys
):
    cfg = replace(
        config(tmp_path), log_max_total_bytes=4096, transcript_max_file_bytes=4096
    )
    # Large immutable label makes both valid manifests unable to coexist.
    writer = RunLogWriter(cfg, "p" * 2000)
    assert writer.is_recording
    before = manifest(writer, cfg)
    writer.close()
    assert manifest(writer, cfg) == before
    assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
    assert capsys.readouterr().err
    replacement = RunLogWriter(cfg, "new")
    assert replacement.is_recording  # close released the lock despite quota failure
    replacement.close()


def test_age_uses_file_age_and_protects_active_streams(tmp_path):
    cfg = config(tmp_path)
    now = [NOW]
    writer = RunLogWriter(cfg, "plaza", clock=lambda: now[0])
    assert writer.append("transcript", {"content": "x"}, agent_id="active")
    active = run_dir(writer, cfg) / "agents/active/transcript-0001.jsonl"
    os.utime(active, (NOW.timestamp() - 30 * 86400,) * 2)
    now[0] += timedelta(days=40)
    assert writer.append("event", {})
    assert active.exists()
    writer.close(clean=False)


def test_unowned_lookalike_manifest_and_segments_survive_pruning(tmp_path):
    cfg = config(tmp_path)
    cfg.log_dir.mkdir()
    fake = cfg.log_dir / "runs" / ("20260101T000000000000Z-" + "a" * 32)
    fake.mkdir(parents=True)
    wrong_manifest = fake / "manifest.json"
    wrong_manifest.write_text(json.dumps({"schema_version": 1, "run_id": "b" * 32}))
    segment = fake / "events-0001.jsonl"
    segment.write_bytes(b"unrelated" * 1000)
    os.utime(segment, (0, 0))
    writer = RunLogWriter(cfg, "plaza", clock=lambda: NOW)
    for _ in range(10):
        assert writer.append("event", {"content": "x" * 3500})
    assert segment.read_bytes() == b"unrelated" * 1000
    assert wrong_manifest.exists()
    writer.close()


def test_unknown_names_and_symlink_children_survive_age_pruning(tmp_path):
    cfg = config(tmp_path)
    old = RunLogWriter(cfg, "old")
    assert old.append("event", {})
    old.close()
    root = run_dir(old, cfg)
    external = tmp_path / "outside"
    external.mkdir()
    sentinel = external / "events-0001.jsonl"
    sentinel.write_bytes(b"secret")
    (root / "events-0002.jsonl").symlink_to(sentinel)
    (root / "agents").symlink_to(external, target_is_directory=True)
    unknown = root / "events-1.jsonl"
    unknown.write_bytes(b"user")
    for path in (root / "manifest.json", root / "events-0001.jsonl"):
        os.utime(path, (0, 0))
    writer = RunLogWriter(cfg, "new")
    assert sentinel.read_bytes() == b"secret"
    assert unknown.read_bytes() == b"user"
    assert (root / "agents").is_symlink()
    assert (root / "events-0002.jsonl").is_symlink()
    writer.close()


def test_repeated_identical_failure_diagnostics_are_limited(tmp_path, capsys):
    writer = RunLogWriter(config(tmp_path), "plaza")
    for _ in range(5):
        assert not writer.append("event", {"metadata": "x" * 5000})
    assert capsys.readouterr().err.count("suspended") == 1
    assert writer.append("event", {})
    assert capsys.readouterr().err.count("recovered") == 1
    writer.close()


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EACCES])
def test_root_creation_failure_later_recovers(tmp_path, monkeypatch, code):
    cfg = config(tmp_path)
    real_mkdir = storage.os.mkdir

    def fail(name, *args, **kwargs):
        if name == "logs":
            raise OSError(code, "cannot create root")
        return real_mkdir(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "mkdir", fail)
        writer = RunLogWriter(cfg, "plaza")
        assert not writer.is_recording
        assert not cfg.log_dir.exists()
    assert writer.append("event", {})
    writer.close()


def test_effective_root_symlink_is_refused(tmp_path):
    cfg = config(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    cfg.log_dir.symlink_to(external, target_is_directory=True)
    writer = RunLogWriter(cfg, "plaza")
    assert not writer.is_recording
    assert not writer.append("event", {})
    writer.close()
    assert not list(external.iterdir())


def test_failed_partial_append_rolls_back_before_reusing_segment(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    writer = RunLogWriter(cfg, "plaza")
    assert writer.append("event", {"event": "before"})
    real_write = storage.os.write
    calls = 0

    def broken_write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, data[:7])
        raise OSError(errno.ENOSPC, "partial")

    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "write", broken_write)
        assert not writer.append("event", {"event": "failed"})
    assert writer.append("event", {"event": "after"})
    paths = list(run_dir(writer, cfg).glob("events-*"))
    assert len(paths) == 1
    rows = records(paths[0])
    assert [r["event"] for r in rows] == ["before", "after"]
    assert [r["seq"] for r in rows] == [1, 3]
    writer.close()


def test_fresh_segments_in_old_run_are_not_expired(tmp_path):
    cfg = config(tmp_path)
    old = RunLogWriter(cfg, "old", clock=lambda: NOW - timedelta(days=90))
    assert old.append("event", {})
    old.close()
    root = run_dir(old, cfg)
    os.utime(root / "manifest.json", (NOW.timestamp() - 90 * 86400,) * 2)
    os.utime(root / "events-0001.jsonl", (NOW.timestamp(),) * 2)
    writer = RunLogWriter(cfg, "new", clock=lambda: NOW)
    assert (root / "events-0001.jsonl").exists()
    assert (root / "manifest.json").exists()
    writer.close()


def test_unlink_failure_does_not_admit_over_quota_and_later_recovers(
    tmp_path, monkeypatch
):
    cfg = replace(
        config(tmp_path), transcript_max_file_bytes=4096, log_max_total_bytes=8192
    )
    writer = RunLogWriter(cfg, "plaza")
    assert writer.append("event", {"content": "x" * 3800})

    def fail(*args, **kwargs):
        raise OSError(errno.EACCES, "cannot prune")

    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "unlink", fail)
        assert not writer.append("event", {"content": "x" * 3800})
        assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
    assert writer.append("event", {"content": "x" * 3800})
    writer.close()


def test_reader_rejects_nonstandard_json_constants(tmp_path):
    path = tmp_path / "nonstandard.jsonl"
    path.write_bytes(b'{"value":NaN}\n{"value":Infinity}\n{"ok":true}\n')
    diagnostics = []
    assert list(iter_jsonl(path, on_diagnostic=diagnostics.append)) == [{"ok": True}]
    assert len(diagnostics) == 2


def test_unsupported_locking_suspends_without_run_creation(tmp_path, monkeypatch):
    import builtins

    original = builtins.__import__

    def without_fcntl(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError("no locking provider")
        return original(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", without_fcntl)
        writer = RunLogWriter(config(tmp_path), "plaza")
        assert not writer.is_recording
        assert not (tmp_path / "logs" / "runs").exists()
    assert writer.append("event", {})
    writer.close()


@pytest.mark.parametrize(
    "primitive", ["platform", "O_NOFOLLOW", "O_DIRECTORY", "dir_fd"]
)
def test_unsupported_platform_or_directory_primitive_suspends_safely(
    tmp_path, monkeypatch, capsys, primitive
):
    cfg = config(tmp_path)
    real_open = storage.os.open
    with monkeypatch.context() as patch:
        if primitive == "platform":
            patch.setattr(storage.os, "name", "nt")
        elif primitive == "dir_fd":

            def no_dir_fd(*args, **kwargs):
                if "dir_fd" in kwargs:
                    raise NotImplementedError("dir_fd unsupported")
                return real_open(*args, **kwargs)

            patch.setattr(storage.os, "open", no_dir_fd)
        else:
            patch.delattr(storage.os, primitive)
        writer = RunLogWriter(cfg, "plaza")
        assert not writer.is_recording
        assert not writer.append("event", {})
        writer.close()
        assert capsys.readouterr().err
    assert not cfg.log_dir.exists()


def test_initial_temp_bytes_remain_bounded_across_fresh_writers(tmp_path, monkeypatch):
    cfg = replace(
        config(tmp_path), log_max_total_bytes=4096, transcript_max_file_bytes=4096
    )

    def fail(*args, **kwargs):
        raise OSError(errno.EACCES, "leave initial manifest temporary")

    real_write = storage.os.write

    def bounded_write(*args, **kwargs):
        result = real_write(*args, **kwargs)
        assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
        return result

    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "write", bounded_write)
        patch.setattr(storage.os, "replace", fail)
        patch.setattr(storage.os, "unlink", fail)
        for _ in range(12):
            writer = RunLogWriter(cfg, "plaza")
            try:
                assert not writer.is_recording
                assert not writer.append("event", {})
                assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
            finally:
                writer.close(clean=False)
    assert len(list(cfg.log_dir.glob("runs/*"))) == 1


def test_fresh_writer_resumes_when_initial_temp_ownership_is_resolved(
    tmp_path, monkeypatch
):
    cfg = config(tmp_path)

    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "leave initial manifest temporary")

    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "replace", fail)
        patch.setattr(storage.os, "unlink", fail)
        original = RunLogWriter(cfg, "original")
        assert not original.is_recording
        original.close(clean=False)
    root = run_dir(original, cfg)
    temporary = next(root.glob("manifest.*.tmp"))
    before = temporary.read_bytes()
    unknown = root / "user-note.txt"
    unknown.write_text("preserve")
    fresh = RunLogWriter(cfg, "fresh")
    try:
        assert not fresh.is_recording
        assert not fresh.append("event", {})
        assert temporary.read_bytes() == before
        # An operator can inspect and finish this valid initial manifest. The
        # writer itself cannot infer that an orphan temporary is its property.
        temporary.replace(root / "manifest.json")
        assert fresh.append("event", {"event": "recovered"})
        assert unknown.read_text() == "preserve"
        assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
    finally:
        fresh.close()


def test_orphan_lookalikes_suspend_without_adopting_or_deleting(tmp_path, capsys):
    cfg = config(tmp_path)
    orphan = cfg.log_dir / "runs" / ("20260101T000000000000Z-" + "a" * 32)
    orphan.mkdir(parents=True)
    unknown = orphan / ("manifest." + "b" * 32 + ".tmp")
    unknown.write_bytes(b"user data with a coincidental managed-looking name")
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "sentinel"
    sentinel.write_bytes(b"outside")
    linked_run = cfg.log_dir / "runs" / ("20260101T000000000000Z-" + "c" * 32)
    linked_run.symlink_to(external, target_is_directory=True)
    link = orphan / ("manifest." + "d" * 32 + ".tmp")
    link.symlink_to(sentinel)
    writer = RunLogWriter(cfg, "plaza")
    try:
        assert not writer.is_recording
        assert not writer.append("event", {})
        diagnostic = capsys.readouterr().err
        assert "unresolved initial manifest temporary" in diagnostic
        assert diagnostic.count("suspended") == 1
        assert (
            unknown.read_bytes()
            == b"user data with a coincidental managed-looking name"
        )
        assert sentinel.read_bytes() == b"outside"
        assert linked_run.is_symlink() and link.is_symlink()
        unknown.unlink()  # user clears the ambiguous file; symlinks remain
        assert writer.append("event", {})
        assert "recovered" in capsys.readouterr().err
        assert sentinel.read_bytes() == b"outside"
        assert linked_run.is_symlink() and link.is_symlink()
    finally:
        writer.close()


def test_crash_before_first_manifest_suspends_fresh_writers(tmp_path):
    cfg = config(tmp_path)
    child_code = """
import sys, time
from pathlib import Path
from dataclasses import replace
from bridge.config import default_config
from bridge import log_storage

def pause_before_replace(*args, **kwargs):
    print('initial temporary ready', flush=True)
    time.sleep(60)
log_storage.os.replace = pause_before_replace
log_storage.RunLogWriter(replace(default_config(), log_dir=Path(sys.argv[1])), 'child')
"""
    child = subprocess.Popen(
        [sys.executable, "-u", "-c", child_code, str(cfg.log_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 8
        temporary = None
        while time.monotonic() < deadline:
            candidates = list(cfg.log_dir.glob("runs/*/manifest.*.tmp"))
            if candidates and candidates[0].stat().st_size:
                temporary = candidates[0]
                break
            assert child.poll() is None
            time.sleep(0.02)
        assert temporary is not None
        child.kill()
        child.communicate(timeout=5)
        before = temporary.read_bytes()
        assert not list(cfg.log_dir.glob("runs/*/manifest.json"))
        for _ in range(5):
            writer = RunLogWriter(cfg, "fresh")
            try:
                assert not writer.is_recording
                assert not writer.append("event", {})
                assert temporary.read_bytes() == before
                assert all_bytes(cfg.log_dir) <= cfg.log_max_total_bytes
            finally:
                writer.close(clean=False)
        assert len(list(cfg.log_dir.glob("runs/*"))) == 1
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
