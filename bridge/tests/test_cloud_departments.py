"""Cloud placement: the setting, a second capacity pool, several departments at once."""

import asyncio
from dataclasses import replace
import hashlib
import json

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from bridge.cloud_git import mark_cloud
from bridge.cloud_owner import CloudOwner
from bridge.cloud_runner import RunnerDown
from bridge.config import ConfigError, default_config, load_config
from bridge.domain_manager import DomainManager
from bridge.domain_protocol import ERROR_MESSAGES
from bridge.project_service import ProjectService
from bridge.relay_claims import RelayClaims
from bridge.state_coordinator import StateCoordinator, VolatileStateRepository
from bridge.tests.cloud_fakes import FakeRunner
from bridge.tests.domain_fakes import (
    FakeOwner,
    FakeProjectService,
    collect_until,
    context,
)
from bridge.tests.test_cloud_git import (  # noqa: F401 (fixtures)
    commit as cloud_commit,
    file_protocol,
    isolated_home,
    path_origin,
)
from bridge.tests.test_relay_claims import FakeWork
from bridge.tests.test_workspace import git, repository
from bridge.workspace import WorkspaceError

CLOUD = {
    "PLAZA_CLOUD_DOMAINS": "core, engineering",
    "PLAZA_CLOUD_RUNNER_URL": "https://runner.example",
}


def test_cloud_domains_is_a_set_and_off_by_default():
    assert load_config(environ=CLOUD).cloud_domains == {"core", "engineering"}
    settings = load_config(environ={})
    assert settings.cloud_domains == frozenset()
    assert settings.cloud_domain_limit == 3
    assert settings.cloud_runner_url == ""


def test_effective_settings_stay_json_for_the_log_manifest():
    assert load_config(environ=CLOUD).effective_settings()["CLOUD_DOMAINS"] == [
        "core",
        "engineering",
    ]
    assert load_config(environ={}).effective_settings()["CLOUD_DOMAINS"] == []
    json.dumps(load_config(environ={}).effective_settings())
    json.dumps(load_config(environ=CLOUD).effective_settings())


def test_the_cloud_limit_reads_from_the_environment():
    settings = load_config(environ=dict(CLOUD, PLAZA_CLOUD_DOMAIN_LIMIT="10"))
    assert settings.cloud_domain_limit == 10
    assert (
        load_config(environ={"PLAZA_CLOUD_DOMAIN_LIMIT": "1"}).cloud_domain_limit == 1
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"PLAZA_CLOUD_DOMAINS": "core,,design"},
        {"PLAZA_CLOUD_DOMAINS": "Core"},
        {"PLAZA_CLOUD_DOMAINS": "core,core"},
        {"PLAZA_CLOUD_DOMAIN_LIMIT": "0"},
        {"PLAZA_CLOUD_DOMAIN_LIMIT": "11"},
        {"PLAZA_CLOUD_DOMAIN_LIMIT": "true"},
        {"PLAZA_CLOUD_DOMAIN_LIMIT": "2.5"},
        {"PLAZA_CLOUD_RUNNER_URL": ""},
        {"PLAZA_CLOUD_RUNNER_URL": "   "},
    ],
)
def test_a_bad_cloud_setting_is_refused(changes):
    with pytest.raises(ConfigError, match=r"CLOUD_\w+ must"):
        load_config(environ=dict(CLOUD, **changes))


def test_a_bad_cloud_setting_in_the_file_is_refused(tmp_path):
    selected = tmp_path / "config.json"
    for values in (
        {"CLOUD_DOMAINS": ["core"], "CLOUD_RUNNER_URL": "https://runner.example"},
        {"CLOUD_DOMAINS": "core", "CLOUD_RUNNER_URL": None},
        {"CLOUD_DOMAIN_LIMIT": "3"},
    ):
        selected.write_text(json.dumps(values), encoding="utf-8")
        with pytest.raises(ConfigError, match=r"CLOUD_\w+ must"):
            load_config(selected, environ={})


async def _service(tmp_path, monkeypatch, **settings):
    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", FakeOwner)
    monkeypatch.setattr("bridge.domain_session.CloudOwner", FakeOwner)
    config = replace(
        default_config(),
        workspace_root_dir=repository(tmp_path),
        cloud_runner_url="https://runner.example",
        **settings,
    )
    service = ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="cloud-run"
    )
    await service.start()
    await service._bootstrap_task
    return service


def _session(service, domain_id, generation, **kwargs):
    from bridge.domain_session import DomainSession

    return DomainSession(
        domain_id,
        generation,
        config=service._config,
        project_service=service,
        **kwargs,
    )


async def _close(service, *sessions):
    for session in sessions:
        await session.stop()
    await service.close()


@pytest.mark.asyncio
async def test_two_cloud_departments_and_one_local_are_active_at_once(
    tmp_path, monkeypatch
):
    service = await _service(
        tmp_path, monkeypatch, cloud_domains=frozenset({"core", "engineering"})
    )
    runner = object()
    core = _session(service, "core", "first", cloud=runner)
    engineering = _session(service, "engineering", "second", cloud=runner)
    design = _session(service, "design", "third", cloud=runner)
    for session in (core, engineering, design):
        await session.start()
    assert [s.snapshot()["state"] for s in (core, engineering, design)] == [
        "active"
    ] * 3
    assert [s.runs_on for s in (core, engineering, design)] == [
        "cloud",
        "cloud",
        "local",
    ]
    assert core._owner.healthy and engineering._owner.healthy
    assert design._owner.healthy
    # Every department keeps its own worktree and lease.
    paths = {s._workspace.worktree_path for s in (core, engineering, design)}
    assert len(paths) == 3
    assert all(s._lease.held for s in (core, engineering, design))
    # A cloud session's owner gets the runner and a 32-hex conversation key.
    assert core._owner.runner is runner
    assert core._owner.conversation == hashlib.sha256(b"first").hexdigest()[:32]
    assert engineering._owner.conversation == hashlib.sha256(b"second").hexdigest()[:32]
    assert design._owner.runner is None and design._owner.conversation is None
    await _close(service, core, engineering, design)
    assert service.capacity_snapshot("core")["available"]
    assert service.capacity_snapshot("design")["available"]


@pytest.mark.asyncio
async def test_the_local_limit_is_still_one(tmp_path, monkeypatch):
    service = await _service(
        tmp_path, monkeypatch, cloud_domains=frozenset({"core", "engineering"})
    )
    design = _session(service, "design", "first")
    marketing = _session(service, "marketing", "second")
    await design.start()
    with pytest.raises(WorkspaceError, match="capacity") as error:
        await marketing.start()
    assert error.value.code == "capacity_limit"
    assert service.workspace_snapshot("marketing")["workspace_id"] is None
    assert service.capacity_snapshot("marketing") == dict(
        limit=1,
        available=False,
        domain_id="design",
        domain_session_id="first",
        pool="local",
    )
    # The cloud pool is untouched by the local holder.
    assert service.capacity_snapshot("core") == dict(
        limit=3, available=True, domain_id=None, domain_session_id=None, pool="cloud"
    )
    await _close(service, design, marketing)


@pytest.mark.asyncio
async def test_the_cloud_limit_is_its_own(tmp_path, monkeypatch):
    service = await _service(
        tmp_path,
        monkeypatch,
        cloud_domains=frozenset({"core", "engineering"}),
        cloud_domain_limit=1,
    )
    core = _session(service, "core", "first")
    engineering = _session(service, "engineering", "second")
    design = _session(service, "design", "third")
    await core.start()
    with pytest.raises(WorkspaceError, match="capacity") as error:
        await engineering.start()
    assert error.value.code == "capacity_limit"
    assert service.capacity_snapshot("engineering") == dict(
        limit=1,
        available=False,
        domain_id="core",
        domain_session_id="first",
        pool="cloud",
    )
    await design.start()
    assert design.snapshot()["state"] == "active"
    assert core.snapshot()["state"] == "active"
    await _close(service, core, engineering, design)


@pytest.mark.asyncio
async def test_the_cloud_pool_names_its_earliest_holder(tmp_path, monkeypatch):
    service = await _service(
        tmp_path,
        monkeypatch,
        cloud_domains=frozenset({"core", "engineering", "research"}),
        cloud_domain_limit=2,
    )
    core = _session(service, "core", "first")
    engineering = _session(service, "engineering", "second")
    await core.start()
    assert service.capacity_snapshot("research") == dict(
        limit=2, available=True, domain_id=None, domain_session_id=None, pool="cloud"
    )
    await engineering.start()
    assert service.capacity_snapshot("research") == dict(
        limit=2,
        available=False,
        domain_id="core",
        domain_session_id="first",
        pool="cloud",
    )
    await core.stop()
    assert service.capacity_snapshot("research")["available"]
    await _close(service, engineering)


@pytest.mark.asyncio
async def test_a_stopped_cloud_department_frees_its_place(tmp_path, monkeypatch):
    service = await _service(
        tmp_path,
        monkeypatch,
        cloud_domains=frozenset({"core", "engineering"}),
        cloud_domain_limit=1,
    )
    core = _session(service, "core", "first")
    refused = _session(service, "engineering", "second")
    await core.start()
    with pytest.raises(WorkspaceError, match="capacity"):
        await refused.start()
    # An uncertain stop keeps the place, as a local department does.
    core._owner.clean = False
    await core.stop()
    assert not service.capacity_snapshot("engineering")["available"]
    core._owner.clean = True
    await core.stop()
    assert service.capacity_snapshot("engineering")["available"]
    assert not core._lease.held
    engineering = _session(service, "engineering", "third")
    await engineering.start()
    assert engineering.snapshot()["state"] == "active"
    await _close(service, refused, engineering)


@pytest.mark.asyncio
async def test_only_a_cloud_department_says_where_it_runs(tmp_path, monkeypatch):
    service = await _service(tmp_path, monkeypatch, cloud_domains=frozenset({"core"}))
    cloud_session = _session(service, "core", "first")
    local_session = _session(service, "design", "second")
    assert "runs_on" not in cloud_session.snapshot()  # inactive
    await cloud_session.start()
    await local_session.start()
    assert cloud_session.snapshot()["runs_on"] == "cloud"
    assert "runs_on" not in local_session.snapshot()
    assert service.runs_on("core") == "cloud"
    assert service.runs_on("design") == "local"
    await cloud_session.stop()
    assert "runs_on" not in cloud_session.snapshot()  # inactive again
    await _close(service, local_session)


@pytest.mark.asyncio
async def test_without_cloud_domains_a_department_is_as_before(tmp_path, monkeypatch):
    service = await _service(tmp_path, monkeypatch)
    core = _session(service, "core", "first")
    assert service.runs_on("core") == "local"
    assert core.runs_on == "local"
    await core.start()
    assert set(core.snapshot()) == {
        "type",
        "protocol_version",
        "project_id",
        "workspace_id",
        "domain_id",
        "domain_session_id",
        "execution_id",
        "state",
        "execution_state",
    }
    assert core._owner.runner is None
    # The capacity snapshot reaches agent_status: with no cloud department it
    # keeps exactly its four keys.
    assert service.capacity_snapshot("engineering") == dict(
        limit=1,
        available=False,
        domain_id="core",
        domain_session_id="first",
    )
    assert service.capacity_snapshot() == service.capacity_snapshot("core")
    await _close(service, core)


@pytest.mark.asyncio
async def test_the_manager_holds_two_cloud_departments_and_one_local(
    tmp_path, monkeypatch
):
    from bridge.domain_manager import DomainManager
    from bridge.state_coordinator import StateCoordinator, VolatileStateRepository
    from bridge.tests.domain_fakes import context

    service = await _service(
        tmp_path, monkeypatch, cloud_domains=frozenset({"core", "engineering"})
    )
    coordinator = StateCoordinator(
        lambda: VolatileStateRepository(service.snapshot()["project_id"])
    )
    await coordinator.open()
    runner = object()
    manager = DomainManager(
        service._config, service, state_coordinator=coordinator, cloud=runner
    )
    packets = []

    async def emit(packet):
        packets.append(packet)

    try:
        for domain in ("core", "engineering", "design"):
            await manager.handle(
                dict(
                    type="activate_domain",
                    protocol_version=2,
                    request_id=f"start-{domain}",
                    domain_id=domain,
                    expected_domain_revision=manager.snapshot(domain)[
                        "domain_revision"
                    ],
                ),
                context=context(f"start-{domain}"),
                emit=emit,
            )
        async with asyncio.timeout(3):
            while not all(
                manager.snapshot(d)["state"] == "active"
                for d in ("core", "engineering", "design")
            ):
                await asyncio.sleep(0.001)
        assert not [p for p in packets if p["type"] == "domain_error"]
        assert manager.snapshot("core")["runs_on"] == "cloud"
        assert manager.snapshot("engineering")["runs_on"] == "cloud"
        assert "runs_on" not in manager.snapshot("design")
        owners = [manager._current(d)._owner for d in ("core", "engineering")]
        assert all(owner.runner is runner for owner in owners)
        # The manager and the session both reserve: one place each, not two.
        assert service._cloud_capacity == [
            manager._current("core"),
            manager._current("engineering"),
        ]
        assert service._capacity_owner is manager._current("design")
    finally:
        await manager.shutdown()
        await coordinator.close()
        await service.close()


# --- Task 8: a cloud department reaches the session, serve() and the protocol ---


class GitRunner(FakeRunner):
    """FakeRunner that holds a conversation and, on each Run, pushes a commit to origin."""

    def __init__(self, tmp_path, origin):
        super().__init__()
        self.tmp_path, self.origin = tmp_path, origin
        self.held = None  # the conversation key the runner's instance holds
        self.branch = None
        self.run = 0
        self.pushed = None

    def create(self, name, repo, branch):
        self.branch = branch
        return super().create(name, repo, branch)

    def start_run(self, name, prompt, *, conversation, max_turns):
        run = super().start_run(
            name, prompt, conversation=conversation, max_turns=max_turns
        )
        self.held = conversation
        clone = self.tmp_path / f"cloud-{run}"
        source = str(self.origin)
        git(self.tmp_path, "clone", "-q", "-b", self.branch, source, str(clone))
        self.pushed = cloud_commit(clone, f"cloud-{run}.txt")
        git(clone, "push", "-q", "origin", self.branch)
        self.run = run
        return run

    def status(self, name):
        self.calls.append(("status", name))
        if not self.run:
            return dict(state="idle", conversation=self.held)
        return dict(
            state="succeeded",
            run=self.run,
            generation=1,
            conversation=self.held,
            result="Done.",
            pushed=dict(commit=self.pushed),
        )


class CloudService(FakeProjectService):
    """FakeProjectService whose ``cloud`` departments run in the cloud."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.cloud = {"engineering"}

    def runs_on(self, domain_id):
        return "cloud" if domain_id in self.cloud else "local"


@pytest_asyncio.fixture
async def bridge(tmp_path, monkeypatch, file_protocol):  # noqa: F811
    monkeypatch.setattr(CloudOwner, "POLL_SECONDS", 0)
    service = CloudService(tmp_path)
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    root = service.workspace.project_root
    git(root, "remote", "add", "origin", str(origin))
    git(root, "push", "-q", "origin", "main")
    contexts, owners = [], []

    class RecordedCloudOwner(CloudOwner):
        async def execute(self, **kwargs):
            contexts.append(kwargs.get("context_packet"))
            return await super().execute(**kwargs)

    def local(*args):
        owner = FakeOwner(*args)
        owners.append(owner)
        return owner

    monkeypatch.setattr("bridge.domain_session.CloudOwner", RecordedCloudOwner)
    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", local)
    monkeypatch.setattr(
        "bridge.domain_session.load_agent",
        lambda agent: "definition" if agent == "backend-architect" else None,
    )
    coordinator = StateCoordinator(
        lambda: VolatileStateRepository(service.workspace.project_id)
    )
    await coordinator.open()
    runner, work = GitRunner(tmp_path, origin), FakeWork()
    manager = DomainManager(
        default_config(),
        service,
        state_coordinator=coordinator,
        claims=RelayClaims(work, every=0.01),
        cloud=runner,
    )
    yield SimpleNamespace(
        manager=manager,
        service=service,
        runner=runner,
        work=work,
        contexts=contexts,
        owners=owners,
        origin=origin,
    )
    await manager.shutdown()
    await coordinator.close()
    service.close()


async def send(bridge, kind, request="request", **fields):
    """One command to engineering, as the game sends it; returns the packets."""
    packets = []
    current = bridge.manager.snapshot("engineering")
    if kind == "activate_domain":
        fields.setdefault("expected_domain_revision", current["domain_revision"])
    else:
        fields.setdefault("execution_id", current["execution_id"])
        fields.setdefault("domain_session_id", current["domain_session_id"])

    async def emit(packet):
        packets.append(packet)

    command = dict(
        type=kind,
        protocol_version=2,
        request_id=request,
        domain_id="engineering",
        **fields,
    )
    if kind == "domain_query":
        command.update(agent_id="backend-architect", task=f"Build {request}")
    await bridge.manager.handle(command, context=context(request), emit=emit)
    if kind == "domain_query":
        await collect_until(None, packets)
        session = bridge.manager._current("engineering")
        async with asyncio.timeout(3):
            while session._inflight is not None or any(
                not job.done() for job in session._jobs
            ):
                await asyncio.sleep(0.001)
            await session._claim.flush()
    return packets


def errors(packets):
    return [p["error_type"] for p in packets if p["type"] == "domain_error"]


@pytest.mark.asyncio
async def test_a_refused_cloud_start_frees_the_lease_the_claim_and_the_place(bridge):
    bridge.runner.script("create", RunnerDown("no answer"))
    packets = await send(bridge, "activate_domain", "start")
    assert errors(packets) == ["cloud_unavailable"]
    assert packets[-1]["message"] == ERROR_MESSAGES["cloud_unavailable"]
    assert "release" in bridge.work.ops()
    assert bridge.service.reservation is None
    assert bridge.service.capacity is None
    assert bridge.manager.snapshot("engineering")["state"] == "inactive"
    bridge.runner.script("create")  # the runner answers again
    packets = await send(bridge, "activate_domain", "again")
    assert not errors(packets)
    assert bridge.manager.snapshot("engineering")["state"] == "active"


@pytest.mark.asyncio
async def test_a_cloud_run_delivers_one_domain_result_and_checkpoints_the_pushed_commit(
    bridge,
):
    await send(bridge, "activate_domain", "start")
    packets = await send(bridge, "domain_query", "first")
    results = [p for p in packets if p["type"] == "domain_result"]
    assert len(results) == 1
    assert results[0]["status"] == "success"
    workspace = bridge.service.workspace
    assert git(workspace.worktree_path, "rev-parse", "HEAD") == bridge.runner.pushed
    checkpoints = [f for op, _, f in bridge.work.calls if op == "checkpoint"]
    assert checkpoints[-1]["commit"] == bridge.runner.pushed
    assert checkpoints[-1]["text"] == "success (completed): Build first"
    # The Start set the workspace up once; a Run does not redo it.
    assert [c[0] for c in bridge.runner.calls].count("create") == 1


@pytest.mark.asyncio
async def test_the_recap_goes_only_with_a_new_cloud_conversation(bridge):
    await send(bridge, "activate_domain", "start")
    await send(bridge, "domain_query", "first")
    await send(bridge, "domain_query", "second")
    bridge.runner.held = None  # a new instance, started from the branch
    await send(bridge, "domain_query", "third")
    assert len(bridge.contexts) == 3
    first, second, third = (packet.continuity for packet in bridge.contexts)
    assert first is not None
    assert second is None
    assert third is not None


@pytest.mark.asyncio
async def test_a_local_session_still_gets_its_recap_on_the_first_run_only(bridge):
    bridge.service.cloud = set()
    await send(bridge, "activate_domain", "start")
    for request in ("first", "second", "third"):
        await send(bridge, "domain_query", request)
    (owner,) = bridge.owners
    assert [c["context_packet"].continuity is not None for c in owner.calls] == [
        True,
        False,
        False,
    ]
    assert not bridge.contexts
    assert not [c for c in bridge.runner.calls if c[0] == "status"]


@pytest.mark.asyncio
async def test_a_half_made_cloud_setting_stops_the_bridge_at_startup(
    tmp_path, monkeypatch, capsys
):
    from bridge import server as server_module

    for name in ("RELAY_WORK_REPO", "PR_GATE_RELAY_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLOUD_RUNNER_SECRET_FILE", str(tmp_path / "missing"))
    settings = replace(
        default_config(),
        cloud_domains=frozenset({"core"}),
        cloud_runner_url="https://runner.example",
    )
    monkeypatch.setattr(server_module, "load_config", MagicMock(return_value=settings))
    server = MagicMock()
    monkeypatch.setattr(server_module, "BridgeServer", server)
    with pytest.raises(SystemExit) as error:
        await server_module.serve()
    assert error.value.code == 2
    server.assert_not_called()
    err = capsys.readouterr().err
    assert "Bridge configuration error" in err and "secret file" in err


@pytest.mark.asyncio
async def test_a_local_start_is_refused_until_the_last_cloud_run_is_back(
    bridge, caplog
):
    await send(bridge, "activate_domain", "start")
    workspace = bridge.service.workspace
    # The bridge died mid-run: the note says the cloud may be ahead.
    mark_cloud(workspace, unsynced=True)
    await send(bridge, "deactivate_domain", "stop")
    assert bridge.manager.snapshot("engineering")["state"] == "inactive"
    bridge.service.cloud = set()  # CLOUD_DOMAINS is empty now
    before = len(bridge.work.calls)
    packets = await send(bridge, "activate_domain", "local")
    assert errors(packets) == ["cloud_switch_refused"]
    assert packets[-1]["message"] == ERROR_MESSAGES["cloud_switch_refused"]
    assert "cloud switch refused: unsynced" in caplog.text
    assert "claim" not in [op for op, _, _ in bridge.work.calls[before:]]
    # The error packet can go out before the failed start's cleanup ends.
    async with asyncio.timeout(3):
        while not (bridge.service.reservation is None is bridge.service.capacity):
            await asyncio.sleep(0.001)
    assert not bridge.owners
    note = workspace.common_git_dir / "plaza/cloud" / "engineering.json"
    assert note.exists()
    mark_cloud(workspace, unsynced=False)
    packets = await send(bridge, "activate_domain", "back")
    assert not errors(packets)
    assert bridge.manager.snapshot("engineering")["state"] == "active"
    assert "runs_on" not in bridge.manager.snapshot("engineering")
    assert not note.exists()


@pytest.mark.asyncio
async def test_a_department_never_in_the_cloud_starts_with_no_switch_check(
    bridge, monkeypatch
):
    def refuse(*args, **kwargs):
        raise AssertionError("no git for a department with no cloud note")

    monkeypatch.setattr("bridge.cloud_git.git_without_filters", refuse)
    bridge.service.cloud = set()
    packets = await send(bridge, "activate_domain", "start")
    assert not errors(packets)
    assert bridge.manager.snapshot("engineering")["state"] == "active"
