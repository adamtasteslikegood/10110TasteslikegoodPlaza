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
    domain = dict(**identity, domain_id="core", domain_session_id="generation")
    payloads = [
        dict(
            request_id="r1",
            agent_id="security-auditor",
            assistant="Chief Architect referral",
        ),
        dict(project_id="project", request_id="r2", assistant="approved"),
        dict(**domain, request_id="r3", agent_id="systems-architect"),
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
            agent_id="fixture-extra-a",
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
        "project_setup",
        "project_setup",
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
        if kind in ("query", "project_setup"):
            packet.update(
                type=kind if kind == "project_setup" else "response",
                status="ok",
                output=payload["assistant"],
            )
            wire["commands"][-1]["agent_id"] = (
                "systems-architect" if stage == "chief_ready" else payload["agent_id"]
            )
        elif kind == "domain_query":
            wire["commands"][-1].update(
                agent_id=payload["agent_id"], domain_id=payload["domain_id"]
            )
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
    """Synthetic test-only proof; retained historical reports remain immutable."""
    from m12_live_fixture import synthetic_proof

    return synthetic_proof()


def test_runner_exists_and_complete_observed_proof_passes():
    assert module().validate_evidence(evidence()) == []


def extra_status_wire(agent_id="fixture-extra-a"):
    return dict(
        commands=[
            dict(type="agent_status", request_id="extra-status", agent_id=agent_id)
        ],
        emitted=[
            dict(
                type="agent_status",
                request_id="extra-status",
                agent_id=agent_id,
                execution_kind="extra",
                domain_id=None,
            )
        ],
    )


@pytest.mark.parametrize("agent_id", ["fixture-extra-a", "fixture-extra-b"])
def test_wire_preserves_explicit_extra_null_domain(agent_id):
    mod = module()
    wire = extra_status_wire(agent_id)
    assert mod._proof_wire(wire) == wire
    sanitized = mod.sanitize_evidence(dict(initial=dict(wire=wire)))
    assert sanitized["initial"]["wire"] == wire
    assert mod._proof_wire(sanitized["initial"]["wire"]) == wire


@pytest.mark.parametrize(
    "damage",
    [
        "working",
        "missing_kind",
        "unknown_extra",
        "domain_state",
        "domain_result",
        "command",
        "extra_has_domain",
        "null_session",
    ],
)
def test_wire_null_domain_is_limited_to_explicit_extra_status(damage):
    mod = module()
    wire = extra_status_wire()
    packet = wire["emitted"][0]
    if damage == "working":
        packet["execution_kind"] = "working"
    elif damage == "missing_kind":
        del packet["execution_kind"]
    elif damage == "unknown_extra":
        packet["agent_id"] = "systems-architect"
    elif damage in ("domain_state", "domain_result"):
        packet["type"] = damage
    elif damage == "command":
        wire["commands"][0] = packet.copy()
    elif damage == "extra_has_domain":
        packet["domain_id"] = "core"
    elif damage == "null_session":
        packet["domain_session_id"] = None
    with pytest.raises(mod.AcceptanceError):
        mod._proof_wire(wire)


def test_complete_proof_includes_extra_status_packets():
    record = evidence()
    for name, packets in extra_status_wire().items():
        record["initial"]["wire"][name][:0] = packets
    assert module().validate_evidence(record) == []
    assert module().validate_evidence(module().sanitize_evidence(record)) == []


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
        permission_mode="dontAsk",
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
                json.dumps(
                    dict(
                        type="describe_workspace",
                        protocol_version=2,
                        request_id="native",
                    )
                )
            )
            packet = json.loads(await native.recv())
            assert packet["request_id"] == "native" and packet["stage"] == "ready"
        state = life.ready["state"]
        assert state["snapshot"]["stage"] == "ready"
        assert state["memory_marker_exists"]
        assert not state["clients"]
        assert state["workspace"] is None
        assert state["project"]["project_root"] == str(project)
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
        cwd=None,
        model="model",
        permission_mode="dontAsk",
        max_turns=1,
        max_budget_usd=None,
        tools=[],
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


def test_legacy_setup_cannot_satisfy_typed_chief_proof():
    mod = module()
    stages, wire = fake_stages_and_wire()
    command = wire["commands"][0]
    command.pop("type")
    command.update(agent_id="security-auditor", task="prepare project")
    wire["emitted"][0]["status"] = "ok"
    with pytest.raises(mod.AcceptanceError):
        mod.corroborate(wire, stages[0])


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
        domain_id="core",
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


@pytest.mark.parametrize(
    "kind",
    [
        "external-symlink",
        "dangling-symlink",
        "directory",
        "fifo",
        "oversize",
        "symlink-parent",
    ],
)
def test_result_reader_rejects_wrong_location_or_nonregular_file(tmp_path, kind):
    import os

    mod = module()
    execution = tmp_path / "execution"
    execution.mkdir()
    result = execution / mod.RESULT
    if kind == "external-symlink":
        external = tmp_path / "outside"
        external.write_bytes(b"m12-nonce")
        result.symlink_to(external)
    elif kind == "dangling-symlink":
        result.symlink_to(tmp_path / "missing")
    elif kind == "directory":
        result.mkdir()
    elif kind == "fifo":
        os.mkfifo(result)
    elif kind == "oversize":
        result.write_bytes(b"x" * 65537)
    else:
        actual = tmp_path / "actual"
        actual.mkdir()
        execution.rmdir()
        execution.symlink_to(actual, target_is_directory=True)
        result.write_bytes(b"m12-nonce")
    with pytest.raises(mod.AcceptanceError):
        mod.read_result(execution)


def test_result_reader_accepts_exact_regular_file(tmp_path):
    mod = module()
    (tmp_path / mod.RESULT).write_bytes(b"m12-nonce")
    assert mod.read_result(tmp_path) == b"m12-nonce"


def test_final_preservation_rejects_matching_nonce_outside_execution(tmp_path):
    mod = module()
    from bridge.tests.test_workspace import repository
    from bridge.workspace import inspect_project, prepare_worktree
    from bridge.project_memory import ProjectMemoryStore

    project = repository(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    work = prepare_worktree(inspect_project(project), runtime_root=runtime)
    snapshot = ProjectMemoryStore(work).initialize()
    external = tmp_path / "external-result"
    external.write_bytes(b"m12-nonce")
    (work.worktree_path / mod.RESULT).symlink_to(external)
    with pytest.raises(mod.AcceptanceError):
        mod.assert_a_unchanged(
            work, {"context": snapshot.as_context()}, mod.sha(b"m12-nonce")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "destination",
    ["missing-parent", "existing", "dangling-symlink", "unwritable-parent"],
)
async def test_live_rejects_invalid_output_before_runtime_or_child(
    tmp_path, monkeypatch, destination
):
    from bridge import domain_sdk

    mod = module()
    output = tmp_path / "report.json"
    if destination == "unwritable-parent":
        if not Path("/proc").is_dir():
            pytest.skip("requires the read-only Linux proc filesystem")
        output = Path("/proc") / (tmp_path.name + "-m12-report.json")
    elif destination == "missing-parent":
        output = tmp_path / "missing" / "report.json"
    elif destination == "existing":
        output.write_bytes(b"prior evidence")
    else:
        output.symlink_to(tmp_path / "missing-target")
    entered = []

    def runtime():
        entered.append("runtime")
        raise AssertionError("invalid output entered runtime")

    monkeypatch.setattr(domain_sdk, "_verify_runtime", runtime)

    async def start(*args):
        entered.append("child")
        raise AssertionError("invalid output entered child")

    monkeypatch.setattr(mod.LiveLifetime, "start", start)
    with pytest.raises((OSError, ValueError)):
        await mod.main(output)
    assert not entered
    if destination == "existing":
        assert output.read_bytes() == b"prior evidence"


def test_result_reader_rejects_symlink_substitution_at_open(tmp_path, monkeypatch):
    import os

    mod = module()
    result = tmp_path / mod.RESULT
    result.write_bytes(b"m12-nonce")
    external = tmp_path / "external"
    external.write_bytes(b"m12-nonce")
    actual_open = os.open
    substituted = []

    def substitute(path, flags, *args, **kwargs):
        if path == mod.RESULT and kwargs.get("dir_fd") is not None:
            result.unlink()
            result.symlink_to(external)
            substituted.append(True)
        return actual_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", substitute)
    with pytest.raises(mod.AcceptanceError):
        mod.read_result(tmp_path)
    assert substituted == [True] and result.is_symlink()
    assert external.read_bytes() == b"m12-nonce"


@pytest.mark.asyncio
async def test_live_plain_start_uses_core_without_implicit_query():
    from unittest.mock import AsyncMock

    socket = SimpleNamespace(send=AsyncMock())
    await module().Plain(socket).send(
        "activate_domain", "start", expected_domain_revision="7"
    )
    assert json.loads(socket.send.call_args.args[0]) == dict(
        type="activate_domain",
        protocol_version=2,
        request_id="start",
        domain_id="core",
        expected_domain_revision="7",
    )


@pytest.mark.asyncio
async def test_live_inspection_does_not_provision_ready_project(tmp_path):
    from dataclasses import replace
    from bridge.config import default_config
    from bridge.project_service import ProjectService
    from bridge.tests.test_workspace import repository

    root = repository(tmp_path)
    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="observer",
    )
    await service.start()
    await service._bootstrap_task
    try:
        state = module().inspect_service(service, [], SimpleNamespace(records=[]))
        assert state["workspace"] is None
        assert state["project"]["project_root"] == str(root)
        assert state["notes"]["revision"] >= 0
        assert state["memory_marker_exists"]
        assert service.workspace_snapshot("core")["stage"] == "unprepared"
    finally:
        await service.close()


def test_live_mode_and_disposable_context_are_written_to_every_lifetime(tmp_path):
    life = module().LiveLifetime(
        tmp_path / "life",
        tmp_path / "project",
        "test",
        permission_mode="bypassPermissions",
    )
    config = json.loads(life.config.read_text())
    assert config["DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS"] is True
    assert Path(config["INSTALL_CONTEXT_DIR"]).is_relative_to(tmp_path)


def test_live_resolves_requested_godot(tmp_path, monkeypatch):
    binary = tmp_path / "godot"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o700)
    monkeypatch.setenv("GODOT_BIN", str(binary))
    assert module().godot_binary() == str(binary)


def test_live_corroborates_typed_chief_setup():
    stage = dict(
        stage="chief_ready",
        payload=dict(project_id="p", request_id="r", assistant="approved"),
    )
    wire = dict(
        commands=[
            dict(type="project_setup", agent_id="systems-architect", request_id="r")
        ],
        emitted=[
            dict(type="project_setup", request_id="r", status="ok", output="approved")
        ],
    )
    assert module().corroborate(wire, stage)[0] == wire["commands"][0]


def test_historical_live_evidence_is_not_current_amendment_proof():
    historical = json.loads(
        (
            Path(__file__).parents[1] / "specs/evidence/m12-live-2026-10-21.json"
        ).read_text()
    )
    assert module().validate_evidence(historical)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_start",
        "start_query",
        "start_identity",
        "missing_context",
        "context_mode",
        "context_agent",
        "context_revision",
        "context_scope",
        "context_workspace",
        "extra_is_catalog",
        "wrong_run_agent",
    ],
)
def test_amendment_proof_requires_start_context_and_character_contract(damage):
    record = evidence()
    assert module().validate_evidence(record) == []
    initial = record["initial"]
    if damage == "missing_start":
        del initial["start"]
    elif damage == "start_query":
        initial["start"]["query_count"] = 1
    elif damage == "start_identity":
        initial["start"]["workspace_id"] = "other"
    elif damage == "missing_context":
        del initial["context"]
    elif damage == "context_mode":
        initial["context"]["facts"]["permission_mode"] = "bypassPermissions"
    elif damage == "context_agent":
        initial["context"]["facts"]["agent_id"] = "security-auditor"
    elif damage == "context_revision":
        initial["context"]["sources"][0]["revision"] = None
    elif damage == "context_scope":
        initial["context"]["sources"][0]["scope"] = "project"
    elif damage == "context_workspace":
        initial["context"]["workspace_id"] = "other"
    elif damage == "extra_is_catalog":
        stage = initial["stages"][4]
        stage["payload"]["agent_id"] = "security-auditor"
        for collection in initial["wire"].values():
            for packet in collection:
                if packet.get("request_id") == stage["payload"]["request_id"]:
                    packet["agent_id"] = "security-auditor"
    else:
        initial["stages"][2]["payload"]["agent_id"] = "security-auditor"
    assert module().validate_evidence(record)


def test_live_fingerprints_exist_and_cover_actual_context_and_ui():
    mod = module()
    assert all((mod.ROOT / name).is_file() for name in mod.LIVE_SOURCES)
    assert {
        "bridge/bridge.py",
        "bridge/context.py",
        "bridge/project_service.py",
        "scenes/bridge/domain_surface.gd",
        "scenes/hud/transcript_clipboard.gd",
        "tests/character_fixture.gd",
    } <= set(mod.LIVE_SOURCES)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["dontAsk", "bypassPermissions"])
async def test_live_checks_actual_selected_mode_before_start(
    tmp_path, monkeypatch, mode
):
    from dataclasses import replace
    from bridge.config import default_config
    import bridge.domain_sdk as sdk

    config = replace(
        default_config(),
        domain_dangerously_skip_permissions=mode == "bypassPermissions",
    )
    monkeypatch.setattr("bridge.config.load_config", lambda: config)
    seen = []

    def verify(selected):
        seen.append(selected)
        raise module().AcceptanceError("offline preflight sentinel")

    monkeypatch.setattr(sdk, "_verify_runtime", verify)
    output = tmp_path / "out.json"
    assert await module().main(output) == 1
    assert seen == [mode]
    report = json.loads(output.read_text())
    assert report["permission_mode"] == mode and not report["accepted"]
    assert report["lifetimes"] == []


def test_live_context_observation_refreshes_without_instruction_bodies(tmp_path):
    from dataclasses import replace
    from bridge.config import default_config
    from bridge.context import compose_context, ContextError

    install = tmp_path / "install"
    install.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    guide = project / "PLAZA_AGENTS.md"
    guide.write_text("private first instructions")
    config = replace(
        default_config(), workspace_root_dir=project, install_context_dir=install
    )

    def observe():
        return module().context_observation(
            compose_context(
                config,
                agent_id="systems-architect",
                execution_kind="domain",
                domain_id="core",
                project=dict(project_id="p", stage="ready"),
                workspace=dict(workspace_id="w"),
                tools=["Read", "Edit", "Bash"],
                permission_mode="dontAsk",
                interaction="explicit_run",
            )
        )

    first = observe()
    guide.write_text("private revised instructions")
    second = observe()
    assert first["sources"][4]["revision"] != second["sources"][4]["revision"]
    assert "private" not in json.dumps(second)
    guide.unlink()
    guide.symlink_to(install)
    with pytest.raises(ContextError):
        observe()


@pytest.mark.asyncio
async def test_live_poll_waits_for_project_memory_writer_without_retrying_work(
    tmp_path,
):
    from dataclasses import replace
    from bridge.config import default_config
    from bridge.project_service import ProjectService
    from bridge.tests.test_workspace import repository
    from bridge import project_files

    root = repository(tmp_path)
    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="poll",
    )
    await service.start()
    await service._bootstrap_task
    lock = project_files.FileLock.acquire(root / ".git/plaza/memory.lock")

    async def release():
        await asyncio.sleep(0.05)
        lock.close()

    releasing = asyncio.create_task(release())
    try:
        state = await module().inspect_observation(
            service, [], SimpleNamespace(records=[])
        )
        assert state["workspace"] is None and state["notes"]["revision"] >= 0
    finally:
        await releasing
        await service.close()


@pytest.mark.parametrize(
    "damage", ["missing", "extra", "identity", "scope", "revision", "extensions"]
)
def test_first_run_proof_requires_one_bounded_application_recap(damage):
    record = evidence()
    assert module().validate_evidence(record) == []
    sources = record["initial"]["context"]["sources"]
    if damage == "missing":
        sources.pop(0)
    elif damage == "extra":
        sources.insert(0, dict(sources[0]))
    elif damage == "extensions":
        sources[0]["text"] = "unexpected recap body"
    else:
        sources[0][damage] = "wrong" if damage != "revision" else "not-a-digest"
    assert module().validate_evidence(record)


@pytest.mark.asyncio
async def test_live_capture_never_attaches_new_stop_to_older_physical_observation(
    monkeypatch,
):
    entered, release = asyncio.Event(), asyncio.Event()
    physical = dict(
        reservation={"owner": "execution-A"},
        lease_marker_exists=True,
        owners=[dict(clean=False, worker_done=False, transport_closed=False)],
    )
    emitted = []

    async def inspect(*args):
        snapshot = json.loads(json.dumps(physical))
        entered.set()
        await release.wait()
        return snapshot

    monkeypatch.setattr(module(), "inspect_observation", inspect)
    capturing = asyncio.create_task(
        module().capture_observation(
            None, [], None, commands=[], emitted=emitted, starts=[], contexts=[]
        )
    )
    await entered.wait()
    # The real backend releases physical ownership before emitting inactive.
    physical.update(
        reservation=None,
        lease_marker_exists=False,
        owners=[dict(clean=True, worker_done=True, transport_closed=True)],
    )
    emitted.append(dict(type="domain_state", request_id="exact-stop", state="inactive"))
    release.set()
    earlier = await capturing
    assert earlier["emitted"] == []
    assert (
        earlier["reservation"] == {"owner": "execution-A"}
        and earlier["lease_marker_exists"]
    )
    later = await module().capture_observation(
        None, [], None, commands=[], emitted=emitted, starts=[], contexts=[]
    )
    assert later["emitted"] == [
        dict(type="domain_state", request_id="exact-stop", state="inactive")
    ]
    assert later["reservation"] is None and not later["lease_marker_exists"]
    assert all(
        owner["clean"] and owner["worker_done"] and owner["transport_closed"]
        for owner in later["owners"]
    )
