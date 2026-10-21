"""Acceptance fails closed; fake providers/children never spend model budget."""

import asyncio
import importlib
import json
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
    """Complete immutable observed proof, copied for no-provider mutations."""
    return json.loads(
        (
            Path(__file__).parents[1] / "specs/evidence/m12-live-2026-10-21.json"
        ).read_text()
    )


def test_runner_exists_and_complete_observed_proof_passes():
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
        import websockets
        from websockets.exceptions import InvalidStatus

        with pytest.raises(InvalidStatus) as rejected:
            async with websockets.connect(
                life.ready["url"], origin="http://attacker.invalid"
            ):
                pass
        assert rejected.value.response.status_code == 403
        async with websockets.connect(life.ready["url"]) as native:
            await native.send(
                json.dumps(dict(type="describe_workspace", request_id="native"))
            )
            packet = json.loads(await native.recv())
            assert packet["request_id"] == "native" and packet["stage"] == "ready"
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


def test_scene_is_bound_to_initial_child_not_supervisor_identity():
    record = evidence()
    record["run_id"] = "separate-supervisor"
    assert module().validate_evidence(record) == []


def test_scene_binding_cannot_name_another_child():
    record = evidence()
    record["initial"]["scene_run_id"] = "foreign"
    assert module().validate_evidence(record)


def test_bridge_child_env_removes_only_harness_names_and_preserves_runtime_bindings(
    monkeypatch,
):
    monkeypatch.setenv("PLAZA_REQUIRE_GODOT", "1")
    monkeypatch.setenv("PLAZA_M12_LIVE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://fixture-proxy")
    monkeypatch.setenv("SSL_CERT_FILE", "/fixture-ca")
    monkeypatch.setenv("PLAZA_DOMAIN_MAX_BUDGET_USD", "50")
    env = module().bridge_environment()
    assert "PLAZA_REQUIRE_GODOT" not in env and "PLAZA_M12_LIVE" not in env
    assert env["ANTHROPIC_API_KEY"] == "fixture-secret"
    assert env["HTTPS_PROXY"] == "http://fixture-proxy"
    assert env["SSL_CERT_FILE"] == "/fixture-ca"
    assert env["PLAZA_DOMAIN_MAX_BUDGET_USD"] == "50"


@pytest.mark.asyncio
async def test_config_override_cannot_redirect_live_child_outside_disposable_project(
    tmp_path, monkeypatch
):
    mod = module()
    project = tmp_path / "disposable"
    project.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("PLAZA_WORKSPACE_ROOT_DIR", str(other))
    life = mod.LiveLifetime(tmp_path / "life", project, "a_initial")
    try:
        with pytest.raises(mod.AcceptanceError):
            await life.start()
    finally:
        closed = await life.stop()
    assert closed["child_returncode"] != 0 and closed["closed"] is False
    assert not (project / ".git").exists() and not (other / ".git").exists()


def test_post_stop_memory_baseline_uses_actual_closed_child_checkpoint():
    mod = module()
    closed_notes = dict(revision=11, context="final Stop checkpoint", sha256={})
    life = SimpleNamespace(
        run_id="run",
        child=SimpleNamespace(forced=False, process=SimpleNamespace(returncode=0)),
        closed=dict(run_id="run", notes=closed_notes),
        cleanup_evidence=evidence()["lifetimes"][0],
        state=lambda: dict(notes=dict(revision=10, context="before Stop")),
    )
    assert mod.post_close_notes(life) == closed_notes
    assert mod.post_close_notes(life)["revision"] != life.state()["notes"]["revision"]
    life.child.process.returncode = None
    with pytest.raises(mod.AcceptanceError):
        mod.post_close_notes(life)


def test_actual_canonical_memory_change_after_baseline_fails_isolation(tmp_path):
    mod = module()
    from bridge.tests.test_workspace import repository
    from bridge.workspace import inspect_project, prepare_worktree
    from bridge.project_memory import ProjectMemoryStore

    project = repository(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    work = prepare_worktree(inspect_project(project), runtime_root=runtime)
    store = ProjectMemoryStore(work)
    snapshot = store.initialize()
    (work.worktree_path / mod.RESULT).write_text("fixture-result")
    expected = dict(context=snapshot.as_context())
    result_sha = mod.sha(b"fixture-result")
    assert mod.assert_a_unchanged(work, expected, result_sha)
    assert store.checkpoint_lifecycle(
        domain_id="engineering",
        domain_session_id="generation",
        event="unexpected after-A change",
    ).saved
    with pytest.raises(mod.AcceptanceError):
        mod.assert_a_unchanged(work, expected, result_sha)


@pytest.mark.parametrize(
    "output",
    [
        "m12-nonce",
        '{"answer":"m12-nonce"}',
        '```json\n{"answer":"m12-nonce","memory_delta":{"summary":"m12-nonce"}}\n```',
    ],
)
def test_semantic_answer_preserves_raw_plain_json_and_one_fenced_object(output):
    assert module().assert_answer_matches(output, "m12-nonce") is True


@pytest.mark.parametrize(
    "output",
    [
        "wrong",
        '{"answer":"wrong"}',
        '{"answer":7}',
        '{"answer":null}',
        '{"answer":"m12-nonce"',
        '{"answer":"m12-nonce"} trailing',
        'prose {"answer":"m12-nonce"}',
        'before ```json\n{"answer":"m12-nonce"}\n```',
        '```json\n{"answer":"m12-nonce"}\n``` after',
        '```json\n{"answer":"m12-nonce"}\n```\n```json\n{}\n```',
        '{"answer":"wrong","answer":"m12-nonce"}',
        '[{"answer":"m12-nonce"}]',
    ],
)
def test_wrong_malformed_or_surrounded_answer_cannot_pass_by_substring(output):
    with pytest.raises(module().AcceptanceError):
        module().assert_answer_matches(output, "m12-nonce")


PROOF_REMOVALS = (
    [
        (section, field)
        for section in ("initial", "restart", "isolation")
        for field in ("sdk", "workspace", "output")
    ]
    + [
        ("initial", field)
        for field in (
            "godot_returncode",
            "terminal_identity",
            "source_before",
            "source_after",
            "bootstrap_notes",
            "notes",
            "released_utc",
        )
    ]
    + [
        (section, field)
        for section in ("restart", "isolation")
        for field in ("notes_before", "notes_after")
    ]
    + [
        (section, "sdk", field)
        for section in ("initial", "restart", "isolation")
        for field in (
            "client_id",
            "domain",
            "cwd",
            "model",
            "max_turns",
            "max_budget_usd",
            "tools",
            "lifecycle",
            "task_ids",
            "query_count",
            "attempts",
            "successful_tool_ids",
            "tool_receipts",
            "terminals",
            "provider_session_ids",
            "inventory",
        )
    ]
    + [
        ("initial", "workspace", field)
        for field in (
            "project_id",
            "workspace_id",
            "project_root",
            "worktree_path",
            "common_git_dir",
            "git_dir",
            "branch",
            "initial_commit",
        )
    ]
    + [("restart", "notes_before", field) for field in ("revision", "sha256")]
    + [
        ("initial", "source_before", field)
        for field in ("head", "status", "tracked_sha256")
    ]
    + [
        ("initial", "tool_receipts", 0, field)
        for field in ("cwd", "result", "nonce", "sha256", "written_utc")
    ]
    + [
        ("binding", field)
        for field in ("commit", "source_sha256", "runtime_before", "runtime_after")
    ]
)


@pytest.mark.parametrize("path", PROOF_REMOVALS)
def test_complete_proof_cannot_lose_a_required_nested_observation(path):
    record = evidence()
    container = record
    for key in path[:-1]:
        container = container[key]
    del container[path[-1]]
    assert module().validate_evidence(record), path


@pytest.mark.parametrize(
    "path,value",
    [
        (("initial", "godot_returncode"), 17),
        (("initial", "godot_returncode"), False),
        (("initial", "output"), "wrong nonce"),
        (("restart", "output"), "wrong nonce"),
        (("isolation", "output"), "not isolated"),
        (("initial", "tool_receipts", 0, "written_utc"), "1900-01-01T00:00:00+00:00"),
        (("initial", "tool_receipts", 0, "written_utc"), "not a timestamp"),
        (("initial", "released_utc"), "2999-01-01T00:00:00+00:00"),
        (("initial", "background_monotonic"), 1.0),
        (("initial", "sdk", "cwd"), "/wrong"),
        (("restart", "sdk", "query_count"), 2),
        (("initial", "sdk", "successful_tool_ids"), ["another-tool"]),
        (("initial", "sdk", "inventory"), ["Read", "Edit"]),
        (("initial", "sdk", "attempts", 0, "name"), "Read"),
        (("initial", "sdk", "tool_receipts", 0, "sha256"), "a" * 64),
        (("initial", "sdk", "terminals", 0, "is_error"), True),
        (("initial", "sdk", "task_ids"), [1, 2, 3]),
        (("initial", "sdk", "max_budget_usd"), 99),
        (("restart", "notes_before", "revision"), 999),
        (("restart", "notes_after", "revision"), True),
        (("restart", "notes_before", "sha256", "todo"), "a" * 64),
        (("isolation", "notes_after", "revision"), 1),
        (("initial", "source_after", "status"), "changed"),
        (("initial", "source_before", "head"), "a" * 40),
        (("initial", "workspace", "branch"), "wrong-branch"),
        (("initial", "workspace", "project_id"), "foreign"),
        (("initial", "workspace", "initial_commit"), "x"),
        (("restart", "workspace", "worktree_path"), "/wrong"),
        (("initial", "terminal_identity", "output_id"), "9"),
        (
            ("binding",),
            dict(
                commit="x",
                source_sha256={"fake": "fake"},
                runtime_before=None,
                runtime_after=None,
            ),
        ),
        (("binding", "source_sha256"), {"fake": "a" * 64}),
        (("binding", "runtime_before", "head"), "x"),
        (("versions", "cli_sha256"), "x"),
        (("lifetimes", 0, "cli_returncodes"), [0]),
        (("lifetimes", 1, "run_id"), "14024affc2f743f59f07f959a6d99db9"),
        (("lifetimes", 0, "ended_at"), "1900-01-01T00:00:00+00:00"),
    ],
)
def test_complete_proof_reconciles_types_identities_content_time_and_source(
    path, value
):
    record = evidence()
    container = record
    for key in path[:-1]:
        container = container[key]
    container[path[-1]] = value
    assert module().validate_evidence(record), path


def test_pre_stop_sdk_snapshots_do_not_require_final_cleanup_observations():
    record = evidence()
    for section in ("initial", "restart", "isolation"):
        sdk = record[section]["sdk"]
        assert sdk["lifecycle"] == ["connect", "query", "receive"]
        assert "returncode" not in sdk
    assert not record["restart"]["sdk"]["terminals"]
    assert module().validate_evidence(record) == []


def test_fenced_semantic_answer_keeps_exact_stage_and_wire_output_parity():
    record = evidence()
    initial = record["initial"]
    raw = "```json\n" + json.dumps({"answer": initial["nonce"]}) + "\n```"
    previous = initial["output"]
    initial["output"] = raw
    stage = initial["stages"][5]["payload"]
    stage["output"] = raw
    stage["rendered_text"] = stage["rendered_text"].replace(previous, raw)
    for packet in initial["wire"]["emitted"]:
        if packet.get("type") == "domain_result":
            packet["output"] = raw
    assert module().validate_evidence(record) == []


@pytest.mark.parametrize(
    "damage",
    [
        "entire_plain_path",
        "status_command",
        "resume_command",
        "status_reply",
        "replayed_terminal",
        "resume_complete",
        "original_terminal",
        "wrong_status_command_id",
        "wrong_status_reply_id",
        "wrong_resume_command_id",
        "wrong_resume_complete_id",
        "wrong_original_run_id",
        "wrong_replayed_run_id",
        "wrong_status_domain",
        "wrong_resume_generation",
        "wrong_status_generation",
        "wrong_completion_generation",
        "wrong_status_state",
        "wrong_completion_execution_state",
        "different_replayed_memory",
        "duplicate_status_command",
        "duplicate_status_reply",
        "duplicate_resume_complete",
        "reversed_commands",
        "resume_command_after_stop",
        "replay_before_status",
        "replay_after_completion",
        "status_reply_before_original",
        "completion_after_stop",
    ],
)
def test_plain_client_requires_correlated_ordered_complete_independent_replay(damage):
    record = evidence()
    wire = record["initial"]["wire"]
    commands, emitted = wire["commands"], wire["emitted"]
    status_command = next(p for p in commands if p["request_id"] == "plain-status")
    resume_command = next(p for p in commands if p["request_id"] == "plain-resume")
    status_reply = next(p for p in emitted if p["request_id"] == "plain-status")
    completion = next(p for p in emitted if p["request_id"] == "plain-resume")
    original, replay = [p for p in emitted if p.get("type") == "domain_result"]
    # Use indices/identity: original and replay are intentionally equal packets.
    original_index, replay_index = [
        i for i, p in enumerate(emitted) if p.get("type") == "domain_result"
    ]
    if damage == "entire_plain_path":
        for name in ("commands", "emitted"):
            wire[name] = [
                p for p in wire[name] if not p["request_id"].startswith("plain-")
            ]
        wire["emitted"].pop(replay_index - 1)
    elif damage in ("status_command", "resume_command"):
        commands.remove(
            status_command if damage == "status_command" else resume_command
        )
    elif damage in ("status_reply", "resume_complete"):
        emitted.remove(status_reply if damage == "status_reply" else completion)
    elif damage in ("original_terminal", "replayed_terminal"):
        emitted.pop(original_index if damage == "original_terminal" else replay_index)
    elif damage.startswith("wrong_") and damage.endswith("_id"):
        {
            "wrong_status_command_id": status_command,
            "wrong_status_reply_id": status_reply,
            "wrong_resume_command_id": resume_command,
            "wrong_resume_complete_id": completion,
            "wrong_original_run_id": original,
            "wrong_replayed_run_id": replay,
        }[damage]["request_id"] = "unrelated-request"
    elif damage == "wrong_status_domain":
        status_command["domain_id"] = "unrelated-domain"
    elif damage.endswith("_generation"):
        {
            "wrong_resume_generation": resume_command,
            "wrong_status_generation": status_reply,
            "wrong_completion_generation": completion,
        }[damage]["domain_session_id"] = "unrelated-generation"
    elif damage == "wrong_status_state":
        status_reply["state"] = "inactive"
    elif damage == "wrong_completion_execution_state":
        completion["execution_state"] = "running"
    elif damage == "different_replayed_memory":
        replay["memory"]["revision"] -= 1
    elif damage.startswith("duplicate_"):
        packets, packet = {
            "duplicate_status_command": (commands, status_command),
            "duplicate_status_reply": (emitted, status_reply),
            "duplicate_resume_complete": (emitted, completion),
        }[damage]
        packets.append(packet.copy())
    elif damage == "reversed_commands":
        a, b = commands.index(status_command), commands.index(resume_command)
        commands[a], commands[b] = commands[b], commands[a]
    elif damage == "resume_command_after_stop":
        commands.remove(resume_command)
        commands.append(resume_command)
    elif damage in ("replay_before_status", "replay_after_completion"):
        emitted.pop(replay_index)
        at = (
            emitted.index(status_reply)
            if damage == "replay_before_status"
            else len(emitted)
        )
        emitted.insert(at, replay)
    elif damage == "status_reply_before_original":
        emitted.remove(status_reply)
        emitted.insert(original_index, status_reply)
    else:
        assert damage == "completion_after_stop"
        emitted.remove(completion)
        emitted.append(completion)
    assert module().validate_evidence(record), damage


def test_write_time_reconciliation_is_not_only_duplicate_receipt_equality():
    record = evidence()
    for receipt in (
        record["initial"]["tool_receipts"][0],
        record["initial"]["sdk"]["tool_receipts"][0],
    ):
        receipt["written_utc"] = "1900-01-01T00:00:00+00:00"
    assert module().validate_evidence(record)


def test_sdk_tool_attempt_cannot_follow_its_actual_file_write():
    record = evidence()
    initial = record["initial"]
    initial["sdk"]["attempts"][0]["received_utc"] = initial["stages"][5]["received_utc"]
    assert module().validate_evidence(record)


@pytest.mark.parametrize("mode", ["wrong_hash", "nonce_in_task", "nonce_in_b_notes"])
def test_private_query_observations_are_checked_when_present(mode):
    record = evidence()
    for name in ("initial", "restart", "isolation"):
        notes = record["initial"]["nonce"] if name == "restart" else "own project notes"
        record[name]["sdk"]["queries"] = [
            dict(
                task="read current notes",
                notes=notes,
                notes_sha256=module().sha(notes.encode()),
                received_utc=record["started_utc"],
            )
        ]
    assert module().validate_evidence(record) == []
    query = record["isolation" if mode == "nonce_in_b_notes" else "restart"]["sdk"][
        "queries"
    ][0]
    if mode == "wrong_hash":
        query["notes_sha256"] = "a" * 64
    elif mode == "nonce_in_task":
        query["task"] = record["initial"]["nonce"]
    else:
        query["notes"] = record["initial"]["nonce"]
        query["notes_sha256"] = module().sha(query["notes"].encode())
    assert module().validate_evidence(record)


@pytest.mark.parametrize("damage", ["too_deep", "too_many", "not_json", "nan"])
def test_malformed_or_oversized_proof_returns_failure_without_unbounded_traversal(
    damage,
):
    record = evidence()
    if damage == "too_deep":
        record["cycle"] = record
    elif damage == "too_many":
        record["extra"] = [0] * 10001
    elif damage == "not_json":
        record["extra"] = object()
    else:
        record["extra"] = float("nan")
    assert module().validate_evidence(record)
