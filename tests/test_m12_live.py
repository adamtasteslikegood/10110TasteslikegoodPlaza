"""Acceptance fails closed; fake providers/children never spend model budget."""

import asyncio
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def module():
    assert (
        Path(__file__).parents[1] / "scripts/m12_live.py"
    ).is_file(), "bounded M12 live runner must exist"
    return importlib.import_module("scripts.m12_live")


def fake_stages_and_wire():
    from scripts.m12_stages import StageValidator, STAGES

    identity = dict(project_id="project", workspace_id="workspace")
    domain = dict(**identity, domain_id="engineering", domain_session_id="generation")
    payloads = [
        dict(
            request_id="r1",
            agent_id="security-auditor",
            assistant="Chief Architect referral",
        ),
        dict(**identity, request_id="r2", assistant="approved"),
        dict(**domain, request_id="r3", agent_id="backend-architect"),
        dict(
            **domain,
            request_id="r4",
            state="background",
            execution_state="running",
            radius=40,
            distance=80,
            panel_hidden=True
        ),
        dict(
            **domain,
            request_id="r5",
            agent_id="security-auditor",
            assistant="unrelated",
            execution_state="running"
        ),
        dict(
            **domain,
            request_id="r6",
            refocus_request_id="refocus",
            output_id="1",
            output="m12-nonce",
            status="success",
            rendered_text="generation output 1 m12-nonce",
            rendered_unique_results=1
        ),
        dict(**domain, request_id="r7", state="inactive"),
    ]
    kinds = [
        "query",
        "query",
        "domain_query",
        "background_domain",
        "query",
        "resume",
        "deactivate_domain",
    ]
    validator = StageValidator("run", "godot")
    wire = dict(commands=[], emitted=[])
    for seq, (stage, payload, kind) in enumerate(zip(STAGES, payloads, kinds), 1):
        validator.accept(
            dict(
                schema_version=1,
                run_id="run",
                scenario="a_initial",
                producer="godot",
                seq=seq,
                stage=stage,
                payload=payload,
            )
        )
        wire["commands"].append(dict(type=kind, request_id=payload["request_id"]))
        packet = dict(**domain, request_id=payload["request_id"], status="success")
        if kind == "query":
            packet.update(type="response", status="ok", output=payload["assistant"])
            wire["commands"][-1]["agent_id"] = (
                "systems-architect" if stage == "chief_ready" else payload["agent_id"]
            )
        elif kind == "domain_query":
            packet.update(type="domain_accepted")
        elif kind == "resume":
            packet.update(type="resume_complete")
            wire["commands"].append(dict(type="refocus_domain", request_id="refocus"))
            wire["emitted"].extend(
                [
                    dict(**domain, type="domain_state", request_id="refocus"),
                    dict(
                        **domain,
                        type="domain_result",
                        output_id="1",
                        output="m12-nonce"
                    ),
                ]
            )
        else:
            packet.update(
                type="domain_state", state=payload["state"], execution_state="running"
            )
        wire["emitted"].append(packet)
    return validator.receipts, wire


def evidence():
    stages, wire = fake_stages_and_wire()
    return dict(
        schema_version=1,
        run_id="run",
        completed=True,
        errors=[],
        initial=dict(
            stages=stages,
            wire=wire,
            checks={key: True for key in module().INITIAL_CHECKS},
            query_count=1,
            result_count=1,
            rendered_count=1,
            tool_receipts=[
                dict(
                    cwd="/execution",
                    result="m12-result.txt",
                    nonce="m12-nonce",
                    sha256="a" * 64,
                    written_utc="2026-10-21T00:00:03+00:00",
                )
            ],
            nonce="m12-nonce",
            result_sha256="a" * 64,
            worktree_path="/execution",
            released_monotonic=3.0,
            background_monotonic=1.0,
            npc_monotonic=2.0,
        ),
        restart=dict(
            checks={key: True for key in module().RESTART_CHECKS},
            query_count=1,
            tool_count=0,
        ),
        isolation=dict(
            checks={key: True for key in module().ISOLATION_CHECKS},
            query_count=1,
            tool_count=0,
        ),
        lifetimes=[
            dict(
                scenario=s,
                run_id=s,
                child_returncode=0,
                cli_returncodes=[0],
                forced=False,
                closed=True,
                ended_at="2026-10-21T00:00:04+00:00",
                memory_marker_before=True,
                memory_marker_after=False,
                lease_marker_after=False,
                reservation_after=None,
                owners=[
                    dict(
                        clean=True,
                        worker_done=True,
                        transport_closed=True,
                        hook_tasks=0,
                        returncode=0,
                        lifecycle=["connect", "query", "receive", "disconnect"],
                        task_count=1,
                    )
                ],
            )
            for s in ("a_initial", "a_restart", "b_isolation")
        ],
        binding=dict(
            commit="a" * 40,
            source_sha256={"scripts/m12_live.py": "b" * 64},
            runtime_before={"head": "a"},
            runtime_after={"head": "a"},
        ),
        instrumentation=module().INSTRUMENTATION,
        versions={
            "sdk": "0.2.136",
            "anyio": "4.14.2",
            "cli": "2.1.228 (Claude Code)",
            "godot": "4.7.1",
        },
        auth_mode="api_key",
        desktop_accepted=False,
    )


def test_runner_exists_and_complete_fake_observation_passes():
    assert module().validate_evidence(evidence()) == []


@pytest.mark.parametrize(
    "key",
    [
        "initial",
        "restart",
        "isolation",
        "lifetimes",
        "binding",
        "versions",
        "instrumentation",
        "completed",
    ],
)
def test_partial_evidence_fails(key):
    record = evidence()
    del record[key]
    assert module().validate_evidence(record)


@pytest.mark.parametrize(
    "record",
    [None, {}, [], "pass", {"completed": True}, {"accepted": True, "errors": []}],
)
def test_missing_malformed_and_claim_only_evidence_fails(record):
    assert module().validate_evidence(record)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("initial", "query_count", 2),
        ("initial", "result_count", 0),
        ("initial", "rendered_count", True),
        ("initial", "tool_receipts", []),
        ("initial", "released_monotonic", 1.5),
        ("restart", "tool_count", 1),
        ("restart", "query_count", 0),
        ("isolation", "tool_count", 1),
    ],
)
def test_incomplete_or_reexecuted_flow_fails(section, field, value):
    record = evidence()
    record[section][field] = value
    assert module().validate_evidence(record)


@pytest.mark.parametrize(
    "field,value",
    [
        ("child_returncode", 1),
        ("forced", True),
        ("closed", False),
        ("ended_at", None),
        ("memory_marker_before", False),
        ("memory_marker_after", True),
        ("lease_marker_after", True),
        ("reservation_after", {}),
    ],
)
def test_unclean_or_nonzero_child_fails(field, value):
    record = evidence()
    record["lifetimes"][0][field] = value
    assert module().validate_evidence(record)


@pytest.mark.parametrize(
    "field,value",
    [
        ("clean", False),
        ("worker_done", False),
        ("transport_closed", False),
        ("hook_tasks", 1),
        ("returncode", -15),
        ("task_count", 2),
        ("lifecycle", ["connect", "query", "receive"]),
    ],
)
def test_incomplete_sdk_cleanup_fails(field, value):
    record = evidence()
    record["lifetimes"][0]["owners"][0][field] = value
    assert module().validate_evidence(record)


def test_unknown_or_secret_fields_do_not_enter_published_evidence():
    record = evidence()
    record["env"] = {"ANTHROPIC_API_KEY": "top-secret"}
    record["initial"]["options"] = {"token": "top-secret"}
    result = module().sanitize_evidence(record)
    assert "top-secret" not in json.dumps(result)
    assert "env" not in result and "options" not in result["initial"]
    assert module().validate_evidence(result) == []


def test_missing_checks_and_nonboolean_claims_fail():
    for section in ("initial", "restart", "isolation"):
        record = evidence()
        key = next(iter(record[section]["checks"]))
        del record[section]["checks"][key]
        assert module().validate_evidence(record)
        record = evidence()
        record[section]["checks"][key] = 1
        assert module().validate_evidence(record)


def test_nonce_release_requires_actual_corroboration_and_absence(tmp_path):
    mod = module()
    gate = mod.NonceGate(tmp_path / "release", tmp_path / "m12-result.txt")
    with pytest.raises(mod.AcceptanceError):
        gate.release(background=None, npc=None)
    assert not gate.release_path.exists()
    gate.result_path.write_text("forged")
    with pytest.raises(mod.AcceptanceError):
        gate.release(background=1.0, npc=2.0)
    assert not gate.release_path.exists()
    assert gate.result_path.read_text() == "forged"


def test_release_creates_only_nonce_never_agent_result(tmp_path):
    mod = module()
    gate = mod.NonceGate(tmp_path / "release", tmp_path / "m12-result.txt")
    nonce = gate.release(background=1.0, npc=2.0)
    assert nonce.startswith("m12-")
    assert gate.release_path.read_text() == nonce
    assert not gate.result_path.exists()
    with pytest.raises(mod.AcceptanceError):
        gate.release(background=1.0, npc=2.0)


@pytest.mark.asyncio
async def test_hung_owned_drain_has_hard_process_bound_and_preserves_fault(tmp_path):
    mod = module()
    marker = tmp_path / "ownership.json"
    child = await mod.Child.spawn(
        [
            sys.executable,
            "-c",
            "import pathlib,time,sys;pathlib.Path(sys.argv[1]).write_text('owned');time.sleep(60)",
            str(marker),
        ],
        tmp_path / "child.log",
    )
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.01)
    assert marker.exists()
    await child.join(0.05)
    assert child.forced and child.process.returncode != 0
    assert marker.read_text() == "owned"


@pytest.mark.asyncio
async def test_same_class_observer_forwards_unchanged_once_and_restores(tmp_path):
    mod = module()
    calls = []
    item = object()
    options = SimpleNamespace(
        cwd="/execution",
        model="model",
        max_turns=3,
        max_budget_usd=0.2,
        tools=["Read", "Edit", "Bash"],
        env={"SECRET": "never-retain"},
    )
    transport = object()

    class SDK:
        def __init__(self, *, options, transport=None):
            calls.append(("init", options, transport, asyncio.current_task()))

        async def connect(self):
            calls.append(("connect", asyncio.current_task()))

        async def query(self, prompt, **kwargs):
            calls.append(("query", prompt, kwargs, asyncio.current_task()))

        async def receive_response(self):
            calls.append(("receive", asyncio.current_task()))
            yield item

        async def disconnect(self):
            calls.append(("disconnect", asyncio.current_task()))

    original = {
        key: getattr(SDK, key)
        for key in ("__init__", "connect", "query", "receive_response", "disconnect")
    }
    observer = mod.SDKObserver(
        client_class=SDK, domain_transport=lambda value: value is transport
    )
    with observer:
        assert SDK is observer.client_class
        client = SDK(options=options, transport=transport)
        await client.connect()
        prompt = json.dumps(dict(task="read notes", prior_project_notes="safe note"))
        await client.query(prompt, session_id="unchanged")
        assert [v async for v in client.receive_response()] == [item]
        await client.disconnect()
    assert all(getattr(SDK, key) is value for key, value in original.items())
    assert [c[0] for c in calls] == [
        "init",
        "connect",
        "query",
        "receive",
        "disconnect",
    ]
    assert calls[0][1] is options and calls[0][2] is transport
    assert calls[2][1:3] == (prompt, {"session_id": "unchanged"})
    assert len({id(c[-1]) for c in calls}) == 1
    assert "never-retain" not in json.dumps(observer.records)
    assert observer.records[0]["query_count"] == 1


def test_production_sdk_factory_identity_and_bound_sources_unchanged():
    mod = module()
    from bridge import domain_sdk
    from claude_agent_sdk import ClaudeSDKClient

    assert (
        domain_sdk.DomainSDKOwner.__init__.__kwdefaults__["client_factory"]
        is ClaudeSDKClient
    )
    assert domain_sdk.ClaudeSDKClient is ClaudeSDKClient
    assert "readiness" not in mod.INSTRUMENTATION


@pytest.mark.asyncio
async def test_controlled_child_real_serve_closes_actual_manifest_without_provider(
    tmp_path,
):
    mod = module()
    project = tmp_path / "project"
    project.mkdir()
    import subprocess

    for args in (
        ("init", "-b", "main"),
        (
            "-c",
            "user.name=M12",
            "-c",
            "user.email=m12@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ),
    ):
        subprocess.run(
            ["git", "-C", str(project), *args], check=True, capture_output=True
        )
    life = mod.LiveLifetime(tmp_path / "lifetime", project, "test")
    try:
        await life.start()
        state = life.ready["state"]
        assert state["snapshot"]["stage"] == "ready"
        assert state["memory_marker_exists"]
        assert not state["clients"]
        assert state["workspace"]["project_root"] == str(project)
        life.marker_before = True
    finally:
        result = await life.stop()
    assert result["closed"] and result["ended_at"]
    assert result["child_returncode"] == 0 and not result["forced"]
    assert result["memory_marker_after"] is False
    assert not life.closed["clients"]


@pytest.mark.asyncio
async def test_tool_program_waits_for_gate_and_only_provider_child_creates_result(
    tmp_path,
):
    mod = module()
    release = tmp_path / "control" / "release"
    release.parent.mkdir()
    execution = tmp_path / "execution"
    execution.mkdir()
    command = mod.tool_task(release).split("Command: ", 1)[1]
    child = await mod.Child.spawn(
        ["bash", "-c", command], tmp_path / "tool.log", cwd=execution
    )
    gate = mod.NonceGate(release, execution / mod.RESULT)
    await asyncio.sleep(0.05)
    gate.assert_absent()
    nonce = gate.release(background=1.0, npc=2.0)
    assert await child.join(3) == 0
    assert (execution / mod.RESULT).read_text() == nonce
    receipt = json.loads(
        (tmp_path / "tool.log").read_text().removeprefix("M12_RECEIPT ")
    )
    assert receipt["cwd"] == str(execution) and receipt["nonce"] == nonce
    assert receipt["written_utc"] >= gate.released_utc


@pytest.mark.asyncio
async def test_observer_retains_actual_npc_process_exit_after_sdk_clears_transport():
    mod = module()
    process = SimpleNamespace(returncode=None)

    class SDK:
        def __init__(self, *, options):
            self._transport = None

        async def connect(self):
            self._transport = SimpleNamespace(_process=process)

        async def query(self, prompt):
            pass

        async def receive_response(self):
            if False:
                yield None

        async def disconnect(self):
            process.returncode = 7
            self._transport = None

    options = SimpleNamespace(
        cwd=None, model="model", max_turns=1, max_budget_usd=None, tools=[]
    )
    observer = mod.SDKObserver(client_class=SDK)
    with observer:
        client = SDK(options=options)
        await client.connect()
        await client.disconnect()
    assert observer.records[0]["returncode"] == 7


@pytest.mark.parametrize("field", ["stages", "wire"])
def test_stage_or_independent_wire_evidence_cannot_be_omitted(field):
    record = evidence()
    record["initial"].pop(field, None)
    assert module().validate_evidence(record)


def test_tool_task_survives_native_single_line_composer(tmp_path):
    assert "\n" not in module().tool_task(tmp_path / "release")


def test_nested_unknown_fields_are_allowlisted_before_publication():
    record = evidence()
    record["binding"]["environment"] = {"TOKEN": "secret-value"}
    record["initial"]["tool_receipts"][0]["token"] = "secret-value"
    record["lifetimes"][0]["owners"][0]["options"] = {"TOKEN": "secret-value"}
    record["initial"]["wire"]["emitted"][0]["env"] = {"TOKEN": "secret-value"}
    assert "secret-value" not in json.dumps(module().sanitize_evidence(record))


def test_legacy_npc_request_without_type_is_independently_corroborated():
    mod = module()
    stages, wire = fake_stages_and_wire()
    command = wire["commands"][0]
    command.pop("type")
    command.update(agent_id="security-auditor", task="prepare project")
    wire["emitted"][0]["status"] = "ok"
    assert mod.corroborate(wire, stages[0])[0] is command


@pytest.mark.asyncio
async def test_pre_setup_child_closure_is_reported_without_inventing_memory_attachment(
    tmp_path,
):
    mod = module()
    project = tmp_path / "empty"
    project.mkdir()
    life = mod.LiveLifetime(tmp_path / "lifetime", project, "a_initial")
    await life.start()
    assert life.ready["state"]["snapshot"]["stage"] == "needs_architect"
    result = await life.stop()
    assert result["closed"] and result["child_returncode"] == 0
    assert result["memory_marker_before"] is False
    assert result["memory_marker_after"] is None
    assert result["owners"] == []
    assert mod.validate_lifetimes([result])
