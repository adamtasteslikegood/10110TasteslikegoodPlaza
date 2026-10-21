"""Repository memory uses real files, stable locks, and process ownership."""

from dataclasses import replace
import errno
import importlib
import multiprocessing
import os
import time
from uuid import uuid4

import pytest

from bridge import project_files as files
from bridge.tests.test_workspace import bootstrap, git
from bridge.workspace import inspect_project, prepare_worktree


def test_memory_store_exists():
    assert importlib.util.find_spec("bridge.project_memory"), "memory store is missing"


@pytest.fixture
def memory(tmp_path):
    module = importlib.import_module("bridge.project_memory")
    _, _, workspace = bootstrap(tmp_path)
    store = module.ProjectMemoryStore(workspace)
    yield module, store
    for lock in store._runs.values():
        lock.close()


def intent(module, run="run-a", task="Implement café", **kwargs):
    values = dict(
        turn_id=str(uuid4()),
        request_id="request",
        owner_run_id=run,
        agent_id="builder",
        domain_id=None,
        domain_session_id=None,
        task=task,
    )
    values.update(kwargs)
    return module.TurnIntent(**values)


def paths(store):
    return store.workspace.common_git_dir / "plaza/session-memory"


def start(module, store, run="run-a", **kwargs):
    store.initialize()
    store.attach_run(run)
    turn = intent(module, run, **kwargs)
    store.begin_turn(turn)
    return turn


def test_initialize_reads_existing_and_repairs_only_missing(memory):
    module, store = memory
    initial = store.initialize()
    assert initial.revision == 1
    assert set(p.name for p in paths(store).iterdir()) == {
        "TODO.md",
        "HANDOFF.md",
        "PROGRESS.md",
    }
    for name in ("TODO.md", "HANDOFF.md", "PROGRESS.md"):
        survivors = {
            p: p.read_bytes() for p in paths(store).iterdir() if p.name != name
        }
        (paths(store) / name).unlink()
        with pytest.raises(module.MemoryError):
            store.load()
        fixed = store.initialize()
        assert fixed.revision == initial.revision
        assert "gap" in getattr(fixed, name.split(".")[0].lower()).lower()
        assert all(p.read_bytes() == data for p, data in survivors.items())
    assert module.ProjectMemoryStore(store.workspace).load() == store.load()
    assert "not instruction authority" in store.load().as_context()


def test_turn_terminal_and_duplicate(memory):
    module, store = memory
    turn = start(module, store)
    pending = store.load()
    assert turn.turn_id in pending.todo and "pending" in pending.todo
    result = store.finish_turn(
        turn.turn_id, outcome="success", output="Tests passed", delta=None
    )
    assert result.saved and result.revision > pending.revision
    terminal = store.load()
    assert "success" in terminal.todo and "Result excerpt" in terminal.progress
    assert (
        store.finish_turn(
            turn.turn_id, outcome="success", output="ignored", delta=None
        ).revision
        == result.revision
    )
    assert store.load() == terminal
    assert not store.finish_turn(
        turn.turn_id, outcome="error", output="conflict", delta=None
    ).saved
    assert not store.finish_turn(
        "unknown", outcome="error", output="", delta=None
    ).saved
    store.detach_run(turn.owner_run_id)
    runs = store.workspace.common_git_dir / "plaza/runs"
    assert list(runs.glob("*.lock")) and not list(runs.glob("*.json"))


def test_invalid_delta_uses_excerpts_without_model_call(memory):
    module, store = memory
    turn = start(module, store)
    result = store.finish_turn(
        turn.turn_id,
        outcome="error",
        output="actual failure",
        delta={"summary": "invented", "evidence": ["verified"], "unknown": True},
    )
    assert result.saved
    snapshot = store.load()
    assert "actual failure" in snapshot.progress
    assert (
        "invented" not in snapshot.as_context() and "verified" not in snapshot.handoff
    )


def test_proposals_do_not_own_execution_or_forge_completion(memory):
    module, store = memory
    first = start(module, store)
    other = intent(module)
    store.begin_turn(other)
    delta = {
        "summary": "summary",
        "next_action": "continue",
        "todo_updates": [{"text": "Future work", "done": False}],
        "decisions": ["design"],
        "evidence": ["test.log"],
    }
    assert store.finish_turn(
        first.turn_id, outcome="success", output="ok", delta=delta
    ).saved
    assert "Model-proposed evidence (unverified)" in store.load().handoff
    assert "Future work" in store.load().todo
    with pytest.raises(module.MemoryError):
        store.detach_run("run-a")
    assert store.finish_turn(
        other.turn_id,
        outcome="cancelled",
        output="stopped",
        delta={"todo_updates": [{"id": first.turn_id, "text": "forge", "done": True}]},
    ).saved
    assert "forge" not in store.load().todo
    store.detach_run("run-a")
    assert "Future work" in store.load().todo


def test_other_clone_has_no_prior_context(memory, tmp_path):
    module, store = memory
    start(module, store, task="PRIVATE ORIGINAL")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(store.workspace.project_root), str(clone))
    workspace = prepare_worktree(
        inspect_project(clone), runtime_root=tmp_path / "runtime"
    )
    assert (
        "PRIVATE ORIGINAL"
        not in module.ProjectMemoryStore(workspace).initialize().as_context()
    )
    linked = tmp_path / "linked"
    git(store.workspace.project_root, "worktree", "add", "-b", "linked", str(linked))
    workspace = prepare_worktree(
        inspect_project(linked), runtime_root=tmp_path / "runtime"
    )
    assert "PRIVATE ORIGINAL" in module.ProjectMemoryStore(workspace).load().todo


def _process_turn(workspace, run, ready, finish, output):
    from bridge import project_memory as module

    store = module.ProjectMemoryStore(workspace)
    store.attach_run(run)
    turn = intent(module, run, task=run)
    store.begin_turn(turn)
    ready.put(turn.turn_id)
    finish.wait(10)
    result = store.finish_turn(turn.turn_id, outcome="success", output=run, delta=None)
    output.put(result.saved)
    if result.saved:
        store.detach_run(run)


def test_two_process_checkpoint_merge(memory):
    module, store = memory
    store.initialize()
    ctx = multiprocessing.get_context("spawn")
    workers = []
    try:
        for run in ("process-a", "process-b"):
            ready, output, finish = ctx.Queue(), ctx.Queue(), ctx.Event()
            process = ctx.Process(
                target=_process_turn, args=(store.workspace, run, ready, finish, output)
            )
            process.start()
            turn_id = ready.get(timeout=10)
            workers.append((process, finish, output, turn_id))
        revision = store.load().revision
        for process, finish, output, _ in workers:
            finish.set()
            assert output.get(timeout=10)
            process.join(10)
            assert process.exitcode == 0
        snapshot = store.load()
        assert snapshot.revision > revision
        assert all(
            turn_id in snapshot.todo and turn_id in snapshot.progress
            for _, _, _, turn_id in workers
        )
    finally:
        for process, _, _, _ in workers:
            if process.is_alive():
                process.kill()
            process.join(10)


def test_other_live_run_is_not_marked_interrupted(memory):
    module, store = memory
    live = start(module, store)
    ctx = multiprocessing.get_context("spawn")
    ready, output, finish = ctx.Queue(), ctx.Queue(), ctx.Event()
    process = ctx.Process(
        target=_process_turn, args=(store.workspace, "dead-run", ready, finish, output)
    )
    process.start()
    try:
        dead = ready.get(timeout=10)
        process.kill()
        process.join(10)
        reader = module.ProjectMemoryStore(store.workspace)
        assert "interrupted" not in reader.load().todo
        snapshot = reader.initialize()
        lines = snapshot.todo.splitlines()
        assert "pending" in next(line for line in lines if live.turn_id in line)
        assert "interrupted" in next(line for line in lines if dead in line)
    finally:
        if process.is_alive():
            process.kill()
        process.join(10)


def test_utf8_full_file_and_entry_bounds(memory):
    module, store = memory
    store.initialize()
    store.attach_run("run-a")
    for _ in range(30):
        turn = intent(module, task="é" * 32768)
        store.begin_turn(turn)
        assert store.finish_turn(
            turn.turn_id,
            outcome="success",
            output="é" * 10000,
            delta={"summary": "é" * 1024},
        ).saved
    snapshot = store.load()
    assert len(snapshot.todo.encode()) <= 16 * 1024
    assert snapshot.todo.count("plaza-item:") <= 64
    assert len(snapshot.handoff.encode()) <= 16 * 1024
    assert len(snapshot.progress.encode()) <= 32 * 1024
    assert snapshot.progress.count("plaza-outcome:") <= 12
    assert "omitted" in snapshot.progress.lower()
    assert "omitted" in snapshot.todo.lower()


@pytest.mark.parametrize(
    "name,cap", [("TODO.md", 16384), ("HANDOFF.md", 16384), ("PROGRESS.md", 32768)]
)
def test_exact_full_file_cap_and_one_byte_over(memory, name, cap):
    module, store = memory
    store.initialize()
    path = paths(store) / name
    data = path.read_bytes()
    # Trailing blank lines are allowed grammar whitespace and count toward the cap.
    path.write_bytes(data + b"\n" * (cap - len(data)))
    assert store.load().revision == 1
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(module.MemoryError):
        store.load()
    with pytest.raises(module.MemoryError):
        store.initialize()
    assert path.stat().st_size == cap + 1


@pytest.mark.parametrize(
    "mutation", ["foreign", "utf8", "symlink", "hardlink", "schema"]
)
def test_unsafe_or_invalid_file_is_preserved(memory, tmp_path, mutation):
    module, store = memory
    store.initialize()
    path = paths(store) / "TODO.md"
    if mutation == "foreign":
        path.write_text(path.read_text().replace(store.workspace.project_id, "foreign"))
    elif mutation == "utf8":
        path.write_bytes(b"\xff")
    elif mutation == "schema":
        path.write_text(path.read_text().replace('"revision":1', '"revision":true'))
    else:
        target = tmp_path / "target"
        target.write_bytes(path.read_bytes())
        path.unlink()
        if mutation == "symlink":
            path.symlink_to(target)
        else:
            os.link(target, path)
    before = path.read_bytes()
    with pytest.raises(module.MemoryError):
        store.initialize()
    assert path.read_bytes() == before


@pytest.mark.parametrize("failure", [errno.EACCES, errno.ENOSPC])
def test_write_failure_reports_unsaved(memory, monkeypatch, failure):
    module, store = memory
    turn = start(module, store)
    before = store.load()

    def fail(*args, **kwargs):
        raise OSError(failure, "injected")

    monkeypatch.setattr(files, "atomic_replace", fail)
    result = store.finish_turn(turn.turn_id, outcome="success", output="ok", delta=None)
    assert not result.saved and result.error_type == "memory_unavailable"
    assert store.load() == before


@pytest.mark.parametrize("operation", ["replace", "fsync"])
def test_partial_revision_is_not_reinitialized(memory, monkeypatch, operation):
    module, store = memory
    turn = start(module, store)
    original = getattr(os, operation)
    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        # Second rename fails; fourth fsync is after TODO replaced (lock fsync first).
        if calls == (2 if operation == "replace" else 4):
            raise OSError(errno.ENOSPC, "injected")
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, operation, fail)
        result = store.finish_turn(
            turn.turn_id, outcome="success", output="ok", delta=None
        )
    assert not result.saved
    before = {p: p.read_bytes() for p in paths(store).glob("*.md")}
    with pytest.raises(module.MemoryError):
        store.load()
    with pytest.raises(module.MemoryError):
        store.initialize()
    assert all(p.read_bytes() == data for p, data in before.items())


def test_nonblocking_admission_and_late_write_failure(memory, monkeypatch):
    module, store = memory
    turn = start(module, store)
    lock = files.FileLock.acquire(store.workspace.common_git_dir / "plaza/memory.lock")
    try:
        started = time.monotonic()
        with pytest.raises(module.MemoryError):
            store.load()
        assert time.monotonic() - started < 0.5
    finally:
        lock.close()
    original = files.atomic_replace
    calls = []

    def slow(path, data):
        original(path, data)
        calls.append(path)
        time.sleep(1.05)

    monkeypatch.setattr(files, "atomic_replace", slow)
    result = store.finish_turn(turn.turn_id, outcome="success", output="ok", delta=None)
    assert not result.saved and result.error_type == "memory_deadline"
    assert len(calls) == 1
    count = len(calls)
    time.sleep(0.05)
    assert len(calls) == count


def test_active_capacity_rejects_without_dropping_work(memory):
    module, store = memory
    store.initialize()
    store.attach_run("run-a")
    ids = []
    for _ in range(65):
        turn = intent(module, task="x" * 512)
        before = store.load()
        try:
            store.begin_turn(turn)
        except module.MemoryError:
            assert store.load() == before
            break
        ids.append(turn.turn_id)
    else:
        pytest.fail("unbounded active admission")
    assert all(turn_id in store.load().todo for turn_id in ids)


def test_lifecycle_does_not_complete_turn(memory):
    module, store = memory
    turn = start(
        module, store, domain_id="architecture", domain_session_id="generation"
    )
    assert store.checkpoint_lifecycle(
        domain_id="architecture", domain_session_id="generation", event="background"
    ).saved
    assert "pending" in store.load().todo
    assert "background" in store.load().progress
    assert turn.turn_id in store.load().handoff


def test_pending_replay_preserves_multiline_intent(memory):
    module, store = memory
    turn = start(module, store, task="one\ntwo <tag> \\ literal")
    first = store.load()
    assert store.begin_turn(turn) == first
    with pytest.raises(module.MemoryError):
        store.begin_turn(replace(turn, task="different"))
    assert store.load() == first


@pytest.mark.parametrize(
    "delta",
    [
        {"summary": "é" * 1025},
        {"next_action": "é" * 513},
        {"todo_updates": [{"text": "é" * 257, "done": False}]},
        {"todo_updates": [{"text": "x", "done": 1}]},
        {"todo_updates": [{"text": "x", "done": False}] * 17},
        {"decisions": ["x"] * 9},
        {"evidence": ["é" * 257]},
        {"summary": "\ud800"},
    ],
)
def test_whole_delta_validation_falls_back(memory, delta):
    module, store = memory
    turn = start(module, store)
    assert store.finish_turn(
        turn.turn_id, outcome="success", output="grounded output", delta=delta
    ).saved
    assert "Result excerpt" in store.load().progress
    assert "grounded output" in store.load().progress
    assert "Model proposal" not in store.load().todo


def test_stable_proposal_update_and_primary_protection(memory):
    module, store = memory
    turn = start(module, store)
    other = intent(module)
    store.begin_turn(other)
    assert store.finish_turn(
        turn.turn_id,
        outcome="success",
        output="ok",
        delta={"todo_updates": [{"text": "future", "done": False}]},
    ).saved
    import json

    line = next(
        line for line in store.load().todo.splitlines() if "Model proposal" in line
    )
    proposal_id = json.loads(line.split("<!-- plaza-item:")[1][:-4])["id"]
    assert store.finish_turn(
        other.turn_id,
        outcome="success",
        output="ok",
        delta={"todo_updates": [{"id": proposal_id, "text": "updated", "done": True}]},
    ).saved
    line = next(line for line in store.load().todo.splitlines() if proposal_id in line)
    assert "[x] Model proposal (success): updated" in line and turn.turn_id in line
    latest = intent(module)
    store.begin_turn(latest)
    active = intent(module)
    store.begin_turn(active)
    assert store.finish_turn(
        latest.turn_id,
        outcome="success",
        output="actual",
        delta={
            "summary": "bad summary",
            "todo_updates": [{"id": active.turn_id, "text": "forged", "done": True}],
        },
    ).saved
    assert (
        "forged" not in store.load().todo and "bad summary" not in store.load().progress
    )
    assert '"state":"pending"' in next(
        line for line in store.load().todo.splitlines() if active.turn_id in line
    )


def test_terminal_compaction_has_explicit_bounded_recap(memory):
    module, store = memory
    store.initialize()
    store.attach_run("run-a")
    for _ in range(14):
        turn = intent(module)
        store.begin_turn(turn)
        assert store.finish_turn(
            turn.turn_id, outcome="success", output="retired result", delta=None
        ).saved
    progress = store.load().progress
    recap = progress.split("## Older recap\n")[1].split("\n## ")[0]
    assert "retired result" in recap and 'omitted_entries":2' in recap


@pytest.mark.parametrize("point", range(1, 8))
def test_fsync_failure_never_claims_saved(memory, monkeypatch, point):
    module, store = memory
    turn = start(module, store)
    original = os.fsync
    calls = 0

    def fail(fd):
        nonlocal calls
        calls += 1
        if calls == point:
            raise OSError(errno.ENOSPC, "injected fsync")
        return original(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail)
        result = store.finish_turn(
            turn.turn_id, outcome="success", output="ok", delta=None
        )
    assert not result.saved
    assert calls >= point
    if point in {1, 2}:
        assert '"state":"pending"' in store.load().todo
    elif point == 7:
        assert '"state":"success"' in store.load().todo
    else:
        with pytest.raises(module.MemoryError):
            store.load()


def test_marker_failure_keeps_ownership_and_never_reuses_run(memory, monkeypatch):
    module, store = memory
    turn = start(module, store)
    assert store.finish_turn(
        turn.turn_id, outcome="success", output="", delta=None
    ).saved
    original = os.fsync
    calls = 0

    def fail(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.EACCES, "unlink directory sync")
        return original(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail)
        with pytest.raises(module.MemoryError):
            store.detach_run("run-a")
    runs = store.workspace.common_git_dir / "plaza/runs"
    assert list(runs.glob("*.json"))
    with pytest.raises(BlockingIOError):
        files.FileLock.acquire(next(runs.glob("*.lock")))
    store.detach_run("run-a")
    with pytest.raises(module.MemoryError):
        module.ProjectMemoryStore(store.workspace).attach_run("run-a")


def test_initialize_does_not_hide_torn_revision_when_neighbor_missing(memory):
    module, store = memory
    store.initialize()
    todo = paths(store) / "TODO.md"
    todo.write_text(todo.read_text().replace('"revision":1', '"revision":2'))
    (paths(store) / "HANDOFF.md").unlink()
    with pytest.raises(module.MemoryError):
        store.initialize()
    assert not (paths(store) / "HANDOFF.md").exists()


def test_run_marker_identity_and_symlink_are_not_proof_of_death(memory, tmp_path):
    module, store = memory
    start(module, store)
    token = store._runs["run-a"]
    token.close()  # Simulate an unclean owner exit without removing its marker.
    marker = next((store.workspace.common_git_dir / "plaza/runs").glob("*.json"))
    marker.write_text('{"project_id":"foreign","owner_run_id":"run-a"}')
    reader = module.ProjectMemoryStore(store.workspace)
    with pytest.raises(module.MemoryError):
        reader.initialize()
    marker.unlink()
    target = tmp_path / "marker"
    target.write_text("{}")
    marker.symlink_to(target)
    with pytest.raises(module.MemoryError):
        reader.initialize()
    assert '"state":"pending"' in reader.load().todo


@pytest.mark.parametrize("name", ["TODO.md", "HANDOFF.md", "PROGRESS.md"])
def test_truncated_grammar_is_a_public_memory_failure(memory, name):
    module, store = memory
    store.initialize()
    path = paths(store) / name
    path.write_text(path.read_text().splitlines()[0] + "\n")
    with pytest.raises(module.MemoryError):
        store.load()
    with pytest.raises(module.MemoryError):
        store.initialize()


def test_overly_nested_json_is_a_public_memory_failure(memory):
    module, store = memory
    store.initialize()
    path = paths(store) / "TODO.md"
    path.write_text(
        '<!-- plaza-memory:v1 {"nested":'
        + "[" * 5000
        + "0"
        + "]" * 5000
        + "} -->\n# TODO\n<!-- plaza-state:{} -->\n"
    )
    with pytest.raises(module.MemoryError):
        store.load()


def test_largest_valid_delta_remains_loadable(memory):
    module, store = memory
    turn = start(module, store)
    assert store.finish_turn(
        turn.turn_id,
        outcome="success",
        output="unused",
        delta={
            "summary": "é" * 1024,
            "next_action": "é" * 512,
            "todo_updates": [{"text": "é" * 256, "done": False} for _ in range(16)],
            "decisions": ["é" * 256] * 8,
            "evidence": ["é" * 256] * 8,
        },
    ).saved
    snapshot = store.load()
    assert "Model proposal summary:" in snapshot.progress
    assert len(snapshot.todo.encode()) <= 16384
    store.detach_run("run-a")
    assert module.ProjectMemoryStore(store.workspace).load() == snapshot


def test_progress_retains_terminal_evidence_and_next_action(memory):
    module, store = memory
    turn = start(module, store)
    assert store.finish_turn(
        turn.turn_id,
        outcome="success",
        output="ok",
        delta={
            "summary": "summary",
            "next_action": "inspect next",
            "evidence": ["result-log"],
        },
    ).saved
    progress = store.load().progress
    assert "result-log" in progress and "inspect next" in progress
    assert "unverified" in progress
    later = intent(module)
    store.begin_turn(later)
    assert store.finish_turn(
        later.turn_id, outcome="success", output="later", delta=None
    ).saved
    assert "result-log" in store.load().progress
    assert "Next action: None recorded" in store.load().progress
