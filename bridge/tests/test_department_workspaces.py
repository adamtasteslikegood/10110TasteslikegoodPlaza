from dataclasses import replace
import pytest
from bridge.workspace import (
    inspect_project,
    prepare_worktree,
    load_workspace,
    WorkspaceError,
)
from bridge.workspace_lease import WorkspaceLease
from bridge.tests.test_workspace import repository
from bridge.config import default_config
from bridge.project_service import ProjectService


def test_departments_have_distinct_persistent_ownership(tmp_path):
    project = inspect_project(repository(tmp_path))
    core = prepare_worktree(
        project, domain_id="core", runtime_root=tmp_path / "runtime"
    )
    engineering = prepare_worktree(
        project, domain_id="engineering", runtime_root=tmp_path / "runtime"
    )
    assert core.worktree_path != engineering.worktree_path
    assert core.branch != engineering.branch
    assert core.workspace_id != engineering.workspace_id
    assert (
        load_workspace(
            project, domain_id="engineering", runtime_root=tmp_path / "runtime"
        )
        == engineering
    )
    with pytest.raises(WorkspaceError):
        WorkspaceLease.acquire(core, domain_id="engineering", domain_session_id="wrong")


@pytest.mark.asyncio
async def test_project_memory_precedes_lazy_department_preparation(tmp_path):
    root = repository(tmp_path)
    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="run",
    )
    await service.start()
    await service._bootstrap_task
    assert service.snapshot()["stage"] == "ready"
    assert service.require_memory().load().revision >= 0
    assert not (root / ".git/plaza/workspaces").exists()
    assert service.workspace_snapshot("core")["workspace_id"] is None
    core = await service.prepare_domain("core")
    assert core.domain_id == "core"
    await service.close()


def legacy_workspace(tmp_path):
    import json
    from bridge.tests.test_workspace import git

    project = inspect_project(repository(tmp_path))
    workspace = prepare_worktree(project, runtime_root=tmp_path / "runtime")
    record = project.common_git_dir / "plaza/workspaces/core.json"
    value = json.loads(record.read_text())
    legacy_path = workspace.worktree_path.parent.parent / "execution"
    git(
        workspace.worktree_path,
        "worktree",
        "move",
        str(workspace.worktree_path),
        str(legacy_path),
    )
    workspace = replace(workspace, worktree_path=legacy_path)
    value["worktree_path"] = str(legacy_path)
    value.pop("domain_id")
    value["schema_version"] = 1
    value["branch"] = f"plaza/workspace-{project.project_id}"
    git(workspace.worktree_path, "branch", "-m", value["branch"])
    legacy = project.common_git_dir / "plaza/workspace.json"
    legacy.write_text(json.dumps(value))
    record.unlink()
    return project, workspace, value


def test_dirty_legacy_adoption_preserves_identity_commits_and_memory(tmp_path):
    import json
    from bridge.tests.test_workspace import git
    from bridge.project_memory import ProjectMemoryStore

    project, old, value = legacy_workspace(tmp_path)
    (old.worktree_path / "tracked.txt").write_text("new commit")
    git(old.worktree_path, "commit", "-am", "retain")
    (old.worktree_path / "dirty.txt").write_text("precious edit")
    head = git(old.worktree_path, "rev-parse", "HEAD")
    memory = ProjectMemoryStore(project)
    memory.initialize()
    before = {
        p.name: p.read_bytes()
        for p in (project.common_git_dir / "plaza/session-memory").glob("*.md")
    }
    core = prepare_worktree(project, runtime_root=tmp_path / "runtime")
    assert core.workspace_id == old.workspace_id
    assert core.worktree_path == old.worktree_path
    assert core.branch == value["branch"]
    assert git(core.worktree_path, "rev-parse", "HEAD") == head
    assert (core.worktree_path / "dirty.txt").read_text() == "precious edit"
    assert (
        json.loads((project.common_git_dir / "plaza/workspace.json").read_text())[
            "state"
        ]
        == "migrated"
    )
    assert {
        p.name: p.read_bytes()
        for p in (project.common_git_dir / "plaza/session-memory").glob("*.md")
    } == before
    assert load_workspace(project, runtime_root=tmp_path / "runtime") == core
    from bridge.workspace import _read_record

    with pytest.raises(WorkspaceError):
        _read_record(project.common_git_dir, None)


@pytest.mark.parametrize("obstacle", ["live", "unclean", "partial"])
def test_legacy_unsafe_adoption_never_replaces_or_lends_tree(tmp_path, obstacle):
    from bridge import project_files as files
    import json

    project, old, value = legacy_workspace(tmp_path)
    (old.worktree_path / "dirty.txt").write_text("retain")
    lock = None
    if obstacle == "live":
        lock = files.FileLock.acquire(old.git_dir / "plaza-execution.lock")
    elif obstacle == "unclean":
        (old.git_dir / "plaza-unclean.json").write_text("{}")
    else:
        value.update(schema_version=2, domain_id="core")
        (project.common_git_dir / "plaza/workspaces/core.json").write_text(
            json.dumps(value)
        )
    try:
        for domain in ("core", "engineering"):
            with pytest.raises(WorkspaceError):
                prepare_worktree(
                    project, domain_id=domain, runtime_root=tmp_path / "runtime"
                )
        assert (old.worktree_path / "dirty.txt").read_text() == "retain"
        assert not (
            project.common_git_dir / "plaza/workspaces/engineering.json"
        ).exists()
    finally:
        if lock:
            lock.close()


@pytest.mark.asyncio
async def test_capacity_is_distinct_and_retained_through_uncertain_idle_stop(
    tmp_path, monkeypatch
):
    from bridge.domain_session import DomainSession
    from bridge.tests.domain_fakes import FakeOwner

    root = repository(tmp_path)
    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="capacity-run",
    )
    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", FakeOwner)
    await service.start()
    await service._bootstrap_task
    core = DomainSession(
        "core", "first", config=service._config, project_service=service
    )
    other = DomainSession(
        "engineering", "second", config=service._config, project_service=service
    )
    await core.start()
    with pytest.raises(WorkspaceError, match="capacity") as error:
        await other.start()
    assert error.value.code == "capacity_limit"
    assert service.workspace_snapshot("engineering")["workspace_id"] is None
    core._owner.clean = False
    await core.stop()
    assert service._capacity_owner is core and core._lease.held
    core._owner.clean = True
    await core.stop()
    assert service._capacity_owner is None and not core._lease.held
    third = DomainSession(
        "engineering", "third", config=service._config, project_service=service
    )
    await third.start()
    assert third._workspace.worktree_path != core._workspace.worktree_path
    await third.stop()
    await other.stop()
    await service.close()


@pytest.mark.asyncio
async def test_wrong_department_readiness_denies_before_memory_admission(tmp_path):
    from bridge.readiness import ReadinessService
    from bridge.project_memory import ProjectMemoryStore, TurnIntent

    project = inspect_project(repository(tmp_path))
    core = prepare_worktree(project, runtime_root=tmp_path / "runtime")
    memory = ProjectMemoryStore(project)
    original = memory.initialize()
    memory.attach_run("run")
    ready = ReadinessService(core, tmp_path / "runtime", memory)
    try:
        with pytest.raises(WorkspaceError):
            await ready.prepare_turn(
                TurnIntent(
                    "turn",
                    "request",
                    "run",
                    "builder",
                    "engineering",
                    "session",
                    "work",
                    core.workspace_id,
                )
            )
        assert memory.load() == original
    finally:
        memory.detach_run("run")


@pytest.mark.asyncio
async def test_failed_start_releases_capacity_and_owned_workspace(
    tmp_path, monkeypatch
):
    from bridge.domain_session import DomainSession
    from bridge.tests.domain_fakes import FakeOwner

    class FailingOwner(FakeOwner):
        async def start(self):
            raise RuntimeError("startup failed")

    service = ProjectService(
        replace(default_config(), workspace_root_dir=repository(tmp_path)),
        runtime_root=tmp_path / "runtime",
        owner_run_id="failed-run",
    )
    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", FailingOwner)
    await service.start()
    await service._bootstrap_task
    session = DomainSession(
        "core", "failed", config=service._config, project_service=service
    )
    with pytest.raises(RuntimeError, match="startup failed"):
        await session.start()
    assert service._capacity_owner is None
    assert not session._lease.held
    assert service.workspace_snapshot("core")["reservation"] is None
    await session.stop()
    await service.close()


@pytest.mark.asyncio
async def test_cancelled_provisioning_drains_before_return_and_shutdown(
    tmp_path, monkeypatch
):
    import asyncio
    import threading
    from bridge import project_service as module

    service = ProjectService(
        replace(default_config(), workspace_root_dir=repository(tmp_path)),
        runtime_root=tmp_path / "runtime",
        owner_run_id="cancel-run",
    )
    await service.start()
    await service._bootstrap_task
    entered, release = threading.Event(), threading.Event()
    original = module.prepare_worktree

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "prepare_worktree", blocked)
    task = asyncio.create_task(service.prepare_domain("core"))
    while not entered.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0)
    closing = asyncio.create_task(service.close())
    await asyncio.sleep(0)
    assert not task.done() and not closing.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await closing
    assert service.require_workspace().domain_id == "core"
    assert not service._attached


def test_old_memory_records_remain_readable_and_new_turns_attribute_workspace(tmp_path):
    from bridge.project_memory import ProjectMemoryStore, TurnIntent

    project = inspect_project(repository(tmp_path))
    memory = ProjectMemoryStore(project)
    memory.initialize()
    memory.attach_run("memory-run")
    memory.begin_turn(
        TurnIntent(
            "old", "old-request", "memory-run", "builder", None, None, "old task"
        )
    )
    assert memory.finish_turn(
        "old", outcome="success", output="old result", delta=None
    ).saved
    documents = project.common_git_dir / "plaza/session-memory"
    for path in documents.glob("*.md"):
        path.write_text(
            path.read_text()
            .replace(',"workspace_id":null', "")
            .replace(',"agent_id":null', "")
        )
    assert "old result" in memory.load().progress
    workspace = prepare_worktree(
        project, domain_id="engineering", runtime_root=tmp_path / "runtime"
    )
    memory.begin_turn(
        TurnIntent(
            "new",
            "new-request",
            "memory-run",
            "builder",
            "engineering",
            "session",
            "new task",
            workspace.workspace_id,
        )
    )
    assert memory.finish_turn(
        "new", outcome="success", output="new result", delta=None
    ).saved
    snapshot = memory.load()
    assert (
        workspace.workspace_id in snapshot.todo
        and workspace.workspace_id in snapshot.progress
    )
    assert '"agent_id":"builder"' in snapshot.progress
    assert len(list(documents.glob("*.md"))) == 3
    memory.detach_run("memory-run")


@pytest.mark.asyncio
async def test_restart_observes_both_departments_without_provisioning(
    tmp_path, monkeypatch
):
    from bridge import project_service as module

    root = repository(tmp_path)
    config = replace(default_config(), workspace_root_dir=root)
    first = ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="first"
    )
    await first.start()
    await first._bootstrap_task
    core = await first.prepare_domain("core")
    engineering = await first.prepare_domain("engineering")
    memory = first.require_memory().load()
    await first.close()

    def forbidden(*args, **kwargs):
        raise AssertionError("Observation must never provision")

    monkeypatch.setattr(module, "prepare_worktree", forbidden)
    second = ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="second"
    )
    await second.start()
    await second._bootstrap_task
    assert second.require_workspace("core") == core
    assert second.require_workspace("engineering") == engineering
    assert second.require_memory().load() == memory
    assert second.workspace_snapshot("design")["workspace_id"] is None
    assert (await second.refresh_snapshot("engineering"))[
        "workspace_id"
    ] == engineering.workspace_id
    await second.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("restart", [False, True])
async def test_lazy_start_accepts_new_source_commits(tmp_path, monkeypatch, restart):
    from bridge.domain_session import DomainSession
    from bridge.tests.domain_fakes import FakeOwner
    from bridge.tests.test_workspace import git

    root = repository(tmp_path)
    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="advance-run",
    )
    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", FakeOwner)
    await service.start()
    await service._bootstrap_task
    sessions = []
    original = None
    try:
        if restart:
            first = DomainSession(
                "core", "before", config=service._config, project_service=service
            )
            sessions.append(first)
            await first.start()
            original = first._workspace
            (original.worktree_path / "retained.txt").write_text(
                "unsaved department work"
            )
            await first.stop()
            assert not first._lease.held and service._capacity_owner is None
        (root / "tracked.txt").write_text("normal new source commit")
        git(root, "commit", "-am", "advance source")
        current = git(root, "rev-parse", "HEAD")
        session = DomainSession(
            "core", "after", config=service._config, project_service=service
        )
        sessions.append(session)
        await session.start()
        workspace = session._workspace
        assert workspace.domain_id == "core"
        if original:
            assert workspace == original
            assert (
                workspace.worktree_path / "retained.txt"
            ).read_text() == "unsaved department work"
            assert (
                git(workspace.worktree_path, "rev-parse", "HEAD")
                == original.initial_commit
            )
        else:
            assert workspace.initial_commit == current
            assert (
                workspace.worktree_path / "tracked.txt"
            ).read_text() == "normal new source commit"
    finally:
        for session in sessions:
            await session.stop()
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("substitute", ["root", "common"])
async def test_lazy_start_rejects_substituted_repository_identity(tmp_path, substitute):
    import shutil

    root = repository(tmp_path)
    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="substitution-run",
    )
    await service.start()
    await service._bootstrap_task
    target = root if substitute == "root" else root / ".git"
    copy, backup = tmp_path / "replacement", tmp_path / "original"
    shutil.copytree(target, copy)
    target.rename(backup)
    copy.rename(target)
    try:
        with pytest.raises(WorkspaceError) as error:
            await service.prepare_domain("core")
        assert error.value.code == "workspace_invalid"
        assert not (root / ".git/plaza/workspaces").exists()
    finally:
        target.rename(copy)
        backup.rename(target)
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("obstacle", [None, "malformed", "live", "unclean", "partial"])
async def test_legacy_character_status_allows_only_safe_explicit_adoption(
    tmp_path, monkeypatch, obstacle
):
    import json
    from bridge import project_files as files
    from bridge.server import BridgeServer
    from bridge.tests.domain_fakes import FakeOwner

    project, old, value = legacy_workspace(tmp_path)
    legacy = project.common_git_dir / "plaza/workspace.json"
    record = project.common_git_dir / "plaza/workspaces/core.json"
    lock = None
    if obstacle == "malformed":
        legacy.write_text("{}")
    elif obstacle == "live":
        lock = files.FileLock.acquire(old.git_dir / "plaza-execution.lock")
    elif obstacle == "unclean":
        (old.git_dir / "plaza-unclean.json").write_text("{}")
    elif obstacle == "partial":
        record.write_text(
            json.dumps({**value, "schema_version": 2, "domain_id": "core"})
        )
    (old.worktree_path / "dirty.txt").write_text("retain")
    config = replace(default_config(), workspace_root_dir=project.root)
    service = ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="legacy-status"
    )
    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", FakeOwner)
    server = BridgeServer(config=config, project_service=service)
    try:
        await service.start()
        await service._bootstrap_task
        before = {
            p: p.read_bytes() for p in project.common_git_dir.rglob("*") if p.is_file()
        }
        packet = (
            await server.dispatch(
                dict(
                    type="agent_status",
                    agent_id="systems-architect",
                    request_id="observe",
                )
            )
        )[0]
        await assert_legacy_status_controls(tmp_path, packet, obstacle is None)
        assert packet["capabilities"]["can_start"] is (obstacle is None)
        assert not packet["capabilities"]["can_run"]
        assert {
            p: p.read_bytes() for p in project.common_git_dir.rglob("*") if p.is_file()
        } == before
        assert not service._workspaces and not server.domains._sessions
        if obstacle is None:
            assert packet["workspace"]["stage"] == "migration_pending"
            assert packet["workspace"]["workspace_id"] == old.workspace_id
            response = await server.dispatch(
                dict(type="activate_domain", domain_id="core", request_id="start")
            )
            assert response[-1]["state"] == "active"
            adopted = service.require_workspace("core")
            assert adopted.workspace_id == old.workspace_id
            assert adopted.worktree_path == old.worktree_path
            assert adopted.branch == value["branch"]
            assert json.loads(legacy.read_text())["state"] == "migrated"
        else:
            assert packet["workspace"]["stage"] == "failed"
        assert (old.worktree_path / "dirty.txt").read_text() == "retain"
    finally:
        await server.domains.shutdown()
        await service.close()
        if lock:
            lock.close()


async def assert_legacy_status_controls(tmp_path, packet, can_start):
    """Pass actual server output to both production Godot controls when available."""
    import asyncio
    import json
    import os
    from pathlib import Path
    import shutil

    binary = shutil.which(os.environ.get("GODOT_BIN", "godot"))
    if not binary:
        if os.environ.get("PLAZA_REQUIRE_GODOT"):
            pytest.fail("Godot is required for the status-to-controls regression")
        return
    fixture = tmp_path / "legacy-status.json"
    fixture.write_text(json.dumps(dict(packet=packet, can_start=can_start)))
    process = await asyncio.create_subprocess_exec(
        binary,
        "--headless",
        "--path",
        str(Path(__file__).resolve().parents[2]),
        "tests/legacy_character_status_test.tscn",
        "--quit-after",
        "30",
        env={**os.environ, "PLAZA_LEGACY_STATUS_FIXTURE": str(fixture)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 20)
        text = output.decode()
        assert process.returncode == 0, text
        assert "legacy_character_status_test: OK" in text, text
        assert "SCRIPT ERROR" not in text and "ERROR:" not in text, text
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


@pytest.mark.asyncio
async def test_legacy_status_revalidates_and_start_rejects_new_live_owner(tmp_path):
    from bridge import project_files as files
    from bridge.server import BridgeServer

    project, old, _ = legacy_workspace(tmp_path)
    config = replace(default_config(), workspace_root_dir=project.root)
    service = ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="legacy-race"
    )
    server = BridgeServer(config=config, project_service=service)
    lock = None
    try:
        await service.start()
        await service._bootstrap_task
        command = dict(
            type="agent_status", agent_id="systems-architect", request_id="observe"
        )
        assert (await server.dispatch(command))[0]["capabilities"]["can_start"]
        lock = files.FileLock.acquire(old.git_dir / "plaza-execution.lock")
        # Advisory eligibility must never bypass explicit Start's locked recheck.
        with pytest.raises(WorkspaceError) as error:
            await service.prepare_domain("core")
        assert error.value.code == "workspace_busy"
        assert not (project.common_git_dir / "plaza/workspaces/core.json").exists()
        assert not (await server.dispatch(command))[0]["capabilities"]["can_start"]
        lock.close()
        lock = None
        assert (await server.dispatch(command))[0]["capabilities"]["can_start"]
    finally:
        if lock:
            lock.close()
        await service.close()
