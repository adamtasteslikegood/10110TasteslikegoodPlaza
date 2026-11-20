"""Cloud placement: the setting, a second capacity pool, several departments at once."""

import asyncio
from dataclasses import replace
import hashlib
import json

import pytest

from bridge.config import ConfigError, default_config, load_config
from bridge.project_service import ProjectService
from bridge.tests.domain_fakes import FakeOwner
from bridge.tests.test_workspace import repository
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
