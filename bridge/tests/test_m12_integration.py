"""Complete offline project/domain lifetimes over real sockets and temporary Git."""

import asyncio
from copy import deepcopy
import json
import sys

import pytest

from bridge.tests.m12_harness import Lifetime, Provider, baseline, identity, until
from bridge.tests.test_workspace import repository
from bridge.tests.test_workspace_lease import child_script
from bridge.workspace_lease import observe_reservation
from scripts.m12_stages import StageError, StageValidator


def stage_records():
    bound = dict(project_id="P", workspace_id="W")
    domain = dict(bound, domain_id="engineering", domain_session_id="G")
    payloads = [
        (
            "referral_rendered",
            dict(
                request_id="referral",
                agent_id="security-auditor",
                assistant="Chief Architect",
            ),
        ),
        ("chief_ready", dict(project_id="P", request_id="chief", assistant="approved")),
        (
            "domain_running",
            dict(domain, request_id="run", agent_id="backend-architect"),
        ),
        (
            "background_ack",
            dict(
                domain,
                request_id="background",
                state="background",
                execution_state="running",
                radius=48,
                distance=90,
                panel_hidden=True,
            ),
        ),
        (
            "npc_rendered",
            dict(
                domain,
                request_id="npc",
                agent_id="security-auditor",
                assistant="gull",
                execution_state="running",
            ),
        ),
        (
            "domain_rendered",
            dict(
                domain,
                request_id="resume",
                refocus_request_id="refocus",
                output_id="1",
                output="ibis",
                status="success",
                rendered_text="G / 1 ibis",
                rendered_unique_results=1,
            ),
        ),
        ("stop_ack", dict(domain, request_id="stop", state="inactive")),
    ]
    return [
        dict(
            schema_version=1,
            run_id="R",
            producer="godot",
            scenario="a_initial",
            seq=i,
            stage=stage,
            payload=payload,
        )
        for i, (stage, payload) in enumerate(payloads, 1)
    ]


@pytest.mark.parametrize(
    "case",
    [
        "wrong_run",
        "wrong_producer",
        "wrong_scenario",
        "bool_version",
        "bool_seq",
        "float_seq",
        "unknown_stage",
        "out_of_order",
        "extra_envelope",
        "extra_payload",
        "missing_payload",
        "empty_id",
        "wrong_project",
        "wrong_workspace",
        "wrong_generation",
        "wrong_domain",
        "inside_anchor",
        "bool_radius",
        "nan_distance",
        "panel_visible",
        "not_background",
        "domain_finished_early",
        "duplicate_request",
        "duplicate_result",
        "bool_result_count",
        "not_rendered",
        "bad_output_id",
        "stop_not_inactive",
        "duplicate_stage",
        "missing_stage",
    ],
)
def test_stage_gate_rejects_untrusted_or_incomplete_observations(case):
    records = deepcopy(stage_records())
    validator = StageValidator("R", "godot")
    if case == "wrong_run":
        records[0]["run_id"] = "other"
    elif case == "wrong_producer":
        records[0]["producer"] = "other"
    elif case == "wrong_scenario":
        records[0]["scenario"] = "b_isolation"
    elif case == "bool_version":
        records[0]["schema_version"] = True
    elif case == "bool_seq":
        records[0]["seq"] = True
    elif case == "float_seq":
        records[0]["seq"] = 1.0
    elif case == "unknown_stage":
        records[0]["stage"] = "release"
    elif case == "out_of_order":
        records[3], records[4] = records[4], records[3]
    elif case == "extra_envelope":
        records[0]["extra"] = "value"
    elif case == "extra_payload":
        records[0]["payload"]["extra"] = "value"
    elif case == "missing_payload":
        records[0]["payload"].pop("assistant")
    elif case == "empty_id":
        records[0]["payload"]["request_id"] = ""
    elif case == "wrong_project":
        records[3]["payload"]["project_id"] = "other"
    elif case == "wrong_workspace":
        records[3]["payload"]["workspace_id"] = "other"
    elif case == "wrong_generation":
        records[3]["payload"]["domain_session_id"] = "other"
    elif case == "wrong_domain":
        records[3]["payload"]["domain_id"] = "core"
    elif case == "inside_anchor":
        records[3]["payload"]["distance"] = 48
    elif case == "bool_radius":
        records[3]["payload"]["radius"] = True
    elif case == "nan_distance":
        records[3]["payload"]["distance"] = float("nan")
    elif case == "panel_visible":
        records[3]["payload"]["panel_hidden"] = False
    elif case == "not_background":
        records[3]["payload"]["state"] = "active"
    elif case == "domain_finished_early":
        records[4]["payload"]["execution_state"] = "idle"
    elif case == "duplicate_request":
        records[4]["payload"]["request_id"] = "run"
    elif case == "duplicate_result":
        records[5]["payload"]["rendered_unique_results"] = 2
    elif case == "bool_result_count":
        records[5]["payload"]["rendered_unique_results"] = True
    elif case == "not_rendered":
        records[5]["payload"]["rendered_text"] = "missing"
    elif case == "bad_output_id":
        records[5]["payload"]["output_id"] = "²"
    elif case == "stop_not_inactive":
        records[6]["payload"]["state"] = "stopping"
    elif case == "duplicate_stage":
        records.insert(1, records[0])
    elif case == "missing_stage":
        records.pop()
    with pytest.raises(StageError):
        for record in records:
            validator.accept(record)
        validator.finish()
    if case not in (
        "duplicate_result",
        "bool_result_count",
        "not_rendered",
        "bad_output_id",
        "stop_not_inactive",
        "missing_stage",
    ):
        assert not validator.may_release


def test_stage_gate_releases_only_after_correlated_ordered_prerequisites():
    validator = StageValidator("R", "godot")
    for index, record in enumerate(stage_records(), 1):
        receipt = validator.accept(record)
        assert validator.may_release == (index == 5)
        assert receipt["receipt_seq"] == index and receipt["received_utc"]
    assert len(validator.finish()) == 7


@pytest.mark.asyncio
async def test_closed_origin_replay_and_stale_generation(
    tmp_path, monkeypatch, offline_clients
):
    root = repository(tmp_path, "project-a")
    (root / "tracked.txt").write_text("source unsaved sentinel")
    (root / "untracked.txt").write_text("source untracked sentinel")
    provider = Provider()
    async with Lifetime(tmp_path, root, monkeypatch, provider) as life:
        source_before = baseline(root)
        runtime_before = (life.runtime / "sentinel").read_bytes()
        assert life.marker.exists()
        a, b = await life.socket(), await life.socket()
        generation = await a.start()
        work = life.service.require_workspace("engineering")
        await a.run(generation)
        await until(lambda: provider.clients[0].receiving.is_set())
        await b.send("domain_status", "observer")
        assert (await b.reply("observer"))["domain_session_id"] == generation
        await a.socket.close()
        await until(lambda: len(life.server._connections) == 1)
        assert observe_reservation(work)["domain_session_id"] == generation
        assert not provider.owners[0]._worker.done()
        provider.release.set()
        session = life.server.domains._sessions["engineering"][0]
        await until(lambda: len(session.replay(0)) - 1 == 1)
        # A terminal remains bound to A's closed sink; B receives no unsolicited push.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(b.socket.recv(), 0.05)
        terminal = (await b.replay(generation))[0]
        assert terminal == session.replay(0)[0]
        assert terminal["status"] == "success" and terminal["memory"]["saved"]
        assert (await b.replay(generation, "again")) == [terminal]
        assert (
            len(provider.queries)
            == len(provider.writes)
            == len(session.replay(0)) - 1
            == 1
        )
        await b.send("deactivate_domain", "stop", generation)
        assert (await b.reply("stop"))["state"] == "inactive"
        life.assert_released()
        old_execution = terminal["execution_id"]
        newer = await b.start("new-start")
        assert newer == generation and len(provider.owners) == 2
        for index, kind in enumerate(
            ("domain_query", "background_domain", "refocus_domain", "deactivate_domain")
        ):
            extra = (
                dict(agent_id="backend-architect", task="stale must not execute")
                if kind == "domain_query"
                else {}
            )
            request = f"stale-{index}"
            await b.send(kind, request, generation, execution_id=old_execution, **extra)
            assert (await b.reply(request))["error_type"] == "stale_execution"
        assert await b.replay(generation, "old-history") == [terminal]
        await b.send("domain_status", "new-status")
        state = await b.reply("new-status")
        assert state["domain_session_id"] == newer and state["state"] == "active"
        assert len(provider.queries) == 1
        await b.send("deactivate_domain", "new-stop", newer)
        assert (await b.reply("new-stop"))["state"] == "inactive"
        life.assert_released()
        assert baseline(root) == source_before
        assert (life.runtime / "sentinel").read_bytes() == runtime_before
        result = work.worktree_path / "integration-result.txt"
        assert result.read_bytes() == b"domain sentinel ibis"
        memory_before = life.service.require_memory().load()
        assert "ibis" in memory_before.as_context()
        assert (
            len(list((work.common_git_dir / "plaza/session-memory").glob("*.md"))) == 3
        )
    life.assert_closed()
    assert identity(terminal)[0:2] == (work.project_id, work.workspace_id)


@pytest.mark.asyncio
async def test_stop_during_real_owner_connect(tmp_path, monkeypatch, offline_clients):
    provider = Provider()
    provider.connect_release = asyncio.Event()
    async with Lifetime(tmp_path, repository(tmp_path), monkeypatch, provider) as life:
        a, b = await life.socket(), await life.socket()
        await a.send("activate_domain", "start")
        generation = (await a.reply("start", state="activating"))["domain_session_id"]
        await until(lambda: provider.clients and provider.clients[0].entered.is_set())
        trusted = life.service.workspace_snapshot("engineering")
        await a.send("activate_domain", "cross-domain", domain_id="design")
        busy = await a.reply("cross-domain")
        assert busy["error_type"] == "domain_busy" and busy["domain_id"] == "design"
        assert busy["project_id"] == trusted["project_id"]
        assert "workspace_id" not in busy  # Design never borrows Engineering identity.
        await a.send("background_domain", "busy-generation", generation)
        busy = await a.reply("busy-generation")
        assert busy["error_type"] == "domain_busy"
        assert busy["domain_session_id"] == generation
        assert busy["project_id"] == trusted["project_id"]
        assert busy["workspace_id"] == trusted["workspace_id"]
        await b.send("deactivate_domain", "stop", generation)
        assert (await b.reply("stop"))["state"] == "inactive"
        late = await a.reply("start")
        assert late["domain_session_id"] == generation
        assert late["type"] == "domain_error" and late["error_type"] == "sdk_error"
        assert not any(p.get("state") == "active" for p in a.packets)
        assert not provider.queries
        assert [name for name, _ in provider.clients[0].calls] == [
            "connect",
            "disconnect",
        ]
        life.assert_released()
    life.assert_closed()


@pytest.mark.asyncio
async def test_crashed_lease_refuses_service_and_never_constructs_sdk(
    tmp_path, monkeypatch, offline_clients
):
    provider = Provider()
    root = repository(tmp_path)
    async with Lifetime(tmp_path, root, monkeypatch, provider) as first:
        work = await first.service.prepare_domain("engineering")
    first.assert_closed()
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        child_script(work) + "\nimport time\ntime.sleep(60)\n",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert await asyncio.wait_for(child.stdout.readline(), 5) == b"acquired\n"
    finally:
        if child.returncode is None:
            child.kill()
        await child.communicate()
    marker = work.git_dir / "plaza-unclean.json"
    marker_bytes = marker.read_bytes()
    lock_inode = (work.git_dir / "plaza-execution.lock").stat().st_ino
    failed_dir = tmp_path / "failed"
    failed_dir.mkdir()
    async with Lifetime(failed_dir, root, monkeypatch, provider) as failed:
        assert failed.service.snapshot()["stage"] == "ready"
        assert failed.service.workspace_snapshot("engineering")["stage"] == "failed"
        assert (
            failed.service.workspace_snapshot("engineering")["reason"]
            == "cleanup_failed"
        )
        socket = await failed.socket()
        await socket.send("activate_domain", "refused")
        assert (await socket.reply("refused"))["type"] == "domain_error"
        assert not provider.clients and not provider.queries
    assert marker.read_bytes() == marker_bytes
    assert (work.git_dir / "plaza-execution.lock").stat().st_ino == lock_inode


@pytest.mark.asyncio
async def test_terminal_memory_storage_failure_preserves_result_and_unclean_run(
    tmp_path, monkeypatch, offline_clients
):
    from bridge import project_files
    from bridge.project_memory import MemoryError

    provider = Provider()
    life = Lifetime(tmp_path, repository(tmp_path), monkeypatch, provider)
    await life.__aenter__()
    try:
        socket = await life.socket()
        generation = await socket.start()
        await socket.run(generation)
        await until(lambda: provider.clients[0].receiving.is_set())
        confirmed = life.service.snapshot()["memory"]["revision"]
        original = project_files.atomic_replace
        documents = (
            life.service.require_workspace("engineering").common_git_dir
            / "plaza/session-memory"
        )
        fault_count = []

        def fault(path, *args, **kwargs):
            if path.parent == documents and path.suffix == ".md":
                fault_count.append(path)
                raise OSError("injected terminal storage failure")
            return original(path, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(project_files, "atomic_replace", fault)
            provider.release.set()
            terminal = await socket.reply("run", type="domain_result")
        assert fault_count
        assert (
            terminal["status"] == "success"
            and terminal["output"] == "domain sentinel ibis"
        )
        assert terminal["memory"]["saved"] is False
        assert life.service.snapshot()["memory"]["revision"] == confirmed
        await socket.send("describe_workspace", "unsaved")
        assert (await socket.reply("unsaved"))["memory"]["status"] == "unsaved"
        await socket.send(
            "domain_query",
            "run",
            generation,
            agent_id="backend-architect",
            task="execute integration sentinel",
        )
        assert await socket.reply("run", type="domain_result") == terminal
        assert await socket.replay(generation) == [terminal]
        assert len(provider.queries) == len(provider.writes) == 1
        assert provider.writes[0][0].read_text() == "domain sentinel ibis"
        await socket.send("deactivate_domain", "stop", generation)
        assert (await socket.reply("stop"))["state"] == "inactive"
        life.assert_released()
        with pytest.raises(MemoryError):
            await life.__aexit__(None, None, None)
        assert life.marker.exists()
        assert life.manifest()["status"] == "open"
        assert life.manifest()["ended_at"] is None
    finally:
        if not life.serving.done():
            await life.__aexit__(None, None, None)
        # Only dispose deliberately failed fixture handles after asserting evidence.
        for lock in life.service._memory._runs.values():
            lock.close()


@pytest.mark.asyncio
async def test_production_listener_rejects_supplied_origins_before_admission(
    tmp_path, monkeypatch
):
    import websockets
    from websockets.exceptions import InvalidStatus

    root = repository(tmp_path)
    provider = Provider()
    async with Lifetime(tmp_path, root, monkeypatch, provider) as life:
        for origin in ("http://attacker.invalid", "http://localhost:3000", "null"):
            with pytest.raises(InvalidStatus) as rejected:
                async with websockets.connect(life.url, origin=origin):
                    pass
            assert rejected.value.response.status_code == 403
        assert not life.server._connections and not life.commands
        native = await life.socket()
        await native.send("describe_workspace", "native-discovery")
        assert (await native.reply("native-discovery"))["project_id"]
        assert len(life.server._connections) == 1
        assert not provider.clients
