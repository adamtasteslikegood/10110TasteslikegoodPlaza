"""Mandatory readiness uses real repository, lease and memory state."""

import asyncio
import importlib
import threading
from uuid import uuid4

import pytest

from bridge.project_memory import ProjectMemoryStore, TurnIntent
from bridge.tests.test_workspace import bootstrap, git
from bridge.workspace_lease import WorkspaceLease


@pytest.fixture
def ready(tmp_path):
    module = importlib.import_module("bridge.readiness")
    root, runtime, workspace = bootstrap(tmp_path)
    memory = ProjectMemoryStore(workspace)
    memory.initialize()
    memory.attach_run("test-run")
    lease = WorkspaceLease.acquire(
        workspace, domain_id="domain", domain_session_id="generation"
    )
    yield module.ReadinessService(workspace, runtime, memory), lease, root
    lease.release(cleanup_confirmed=True)
    for lock in memory._runs.values():
        lock.close()


def intent():
    return TurnIntent(
        str(uuid4()), "request", "test-run", "builder", None, None, "work"
    )


def hook_input(lease, **changes):
    data = dict(
        hook_event_name="PreToolUse",
        cwd=str(lease.workspace.worktree_path),
        tool_name="Bash",
        tool_use_id="tool",
    )
    data.update(changes)
    return data


@pytest.mark.asyncio
async def test_newer_npc_memory_revision_is_ready(ready):
    service, lease, _ = ready
    start = await service.prepare_turn(intent())
    later = await service.prepare_turn(intent())
    assert later.revision > start.revision
    assert await service.pre_tool_hook(lease)(hook_input(lease), "tool", {}) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid", ["cwd", "branch", "memory", "lease", "source", "input"]
)
async def test_tool_gate_denies_invalid_state(ready, invalid):
    service, lease, root = ready
    data = hook_input(lease)
    if invalid == "cwd":
        data["cwd"] = str(root)
    elif invalid == "branch":
        git(lease.workspace.worktree_path, "checkout", "--detach")
    elif invalid == "memory":
        (
            service.memory.workspace.common_git_dir / "plaza/session-memory/TODO.md"
        ).write_text("broken")
    elif invalid == "lease":
        lease.held = False
    elif invalid == "source":
        root.rename(root.with_name("old-source"))
        root.mkdir()
    else:
        data.pop("tool_use_id")
    try:
        result = await service.pre_tool_hook(lease)(data, "tool", {})
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    finally:
        lease.held = True
        if invalid == "source":
            root.rmdir()
            root.with_name("old-source").rename(root)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "timeout"])
async def test_hook_checker_failures_deny(ready, monkeypatch, failure):
    service, lease, _ = ready

    async def check(*args, **kwargs):
        if failure == "exception":
            raise RuntimeError("private")
        await asyncio.sleep(10)

    monkeypatch.setattr(service, "check_tool", check)
    monkeypatch.setattr(
        importlib.import_module("bridge.readiness"), "CHECK_TIMEOUT", 0.01
    )
    result = await service.pre_tool_hook(lease)(hook_input(lease), "tool", {})
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "private" not in str(result)


@pytest.mark.asyncio
async def test_cancelled_begin_drains_writer(ready, monkeypatch):
    service, _, _ = ready
    entered, release = threading.Event(), threading.Event()
    begin = service.memory.begin_turn

    def blocked(turn):
        entered.set()
        release.wait(2)
        return begin(turn)

    monkeypatch.setattr(service.memory, "begin_turn", blocked)
    task = asyncio.create_task(service.prepare_turn(intent()))
    while not entered.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0.01)
    task.cancel()
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "pending" in service.memory.load().todo


@pytest.mark.asyncio
async def test_hook_registry_retains_cancelled_io_and_bounds_new_admission(monkeypatch):
    from bridge.readiness import HookTasks, owned_io

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    shutdowns = []
    calls = []
    registry = HookTasks(lambda: shutdowns.append(True))
    monkeypatch.setattr(registry, "LIMIT", 1)

    def worker():
        calls.append(True)
        entered.set()
        assert release.wait(10), "fixture worker was not released"
        finished.set()

    async def callback(*args):
        await owned_io(worker)
        return {}

    hook = registry.wrap(callback)
    first = asyncio.create_task(hook({}, "first", {}))
    draining = None
    try:
        while not entered.is_set():
            await asyncio.sleep(0.001)
        first.cancel()  # Control ID may already have been settled by watchdog.
        await asyncio.sleep(0)
        assert not first.done() and registry.active_count == 1
        for _ in range(100):
            result = await hook({}, "later", {})
            assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert shutdowns == [True] and len(calls) == 1
        assert registry.active_count == 1
        draining = asyncio.create_task(registry.drain())
        await asyncio.sleep(0)
        assert not draining.done() and not finished.is_set()
        release.set()
        await draining
        assert finished.is_set() and first.done() and registry.active_count == 0
        assert (await hook({}, "after-close", {}))["hookSpecificOutput"][
            "permissionDecision"
        ] == "deny"
        assert len(calls) == 1
    finally:
        release.set()
        if draining:
            await draining
        await asyncio.gather(first, return_exceptions=True)
