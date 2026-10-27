"""Acceptance must reject incomplete records and independently observed bypasses."""

from copy import deepcopy
import hashlib
import importlib
from pathlib import Path

import pytest


def module():
    return importlib.import_module("scripts.m12_tool_guard_probe")


@pytest.mark.asyncio
async def test_real_probe_fixture_prepares_bound_turn_and_cleans_up(
    tmp_path, monkeypatch
):
    from dataclasses import replace
    from bridge.readiness import ReadinessService
    from bridge.workspace import WorkspaceError
    from bridge.workspace_lease import WorkspaceLease, observe_reservation

    probe = module()

    def unexpected_provider(*args, **kwargs):
        raise AssertionError("Fixture setup must not construct an SDK owner/client")

    monkeypatch.setattr(probe, "DomainSDKOwner", unexpected_provider)
    monkeypatch.setattr(probe, "ClaudeSDKClient", unexpected_provider)
    workspace, memory, lease, runtime, token = probe.fixture(tmp_path)
    turn = None
    prepared = False
    try:
        assert workspace.domain_id == lease.domain_id == "core"
        lease.validate()
        assert (workspace.worktree_path / "read.txt").read_text() == token
        assert (workspace.worktree_path / "edit.txt").read_text() == "BEFORE\n"
        turn = probe.probe_turn("read_ready", workspace, lease)
        assert turn.domain_id == workspace.domain_id
        assert turn.workspace_id == workspace.workspace_id
        assert turn.domain_session_id == lease.domain_session_id
        service = ReadinessService(workspace, runtime, memory)
        previous = memory.load()
        snapshot = await service.prepare_turn(turn)
        prepared = True
        assert snapshot.revision > previous.revision
        assert (
            await service.check_tool(
                lease,
                cwd=str(workspace.worktree_path),
                tool_name="Read",
                tool_use_id="local",
            )
            == snapshot
        )
        with pytest.raises(WorkspaceError, match="Turn workspace binding changed"):
            await service.prepare_turn(replace(turn, domain_id="probe"))
        with pytest.raises(WorkspaceError, match="Invalid domain reservation"):
            WorkspaceLease.acquire(
                workspace, domain_id="probe", domain_session_id="wrong-domain"
            )
    finally:
        if prepared:
            saved = memory.finish_turn(
                turn.turn_id,
                outcome="cancelled",
                output="Offline fixture check",
                delta=None,
            )
        memory.detach_run("probe-run")
        lease.release(cleanup_confirmed=True)
    assert not lease.held
    assert saved.saved
    assert observe_reservation(workspace) is None
    assert not (workspace.git_dir / "plaza-unclean.json").exists()


def complete_case(name="bash_deny"):
    lifecycle = name in {"stop_connect", "stop_idle", "stop_query", "repeated_cancel"}
    ready = name.endswith("_ready")
    path = name.split("_")[0]
    target = {"read": "Read", "edit": "Edit", "mcp": "mcp__m12_fixture__sentinel"}.get(
        path, "Bash"
    )
    active = name not in {"stop_connect", "stop_idle"}
    terminal = not lifecycle and name != "bash_disconnect"
    result = dict(
        name=name,
        attempted=active,
        hook_seen=active,
        reaped=True,
        cleanup_clean=True,
        sentinel_executed=ready,
        successful_tool_result=ready,
        successful_tool_ids=["tool-id"] if ready else [],
        post_tool_ids=["tool-id"] if ready else [],
        post_seen=ready,
        decision=(
            "unchanged"
            if ready
            else ("deny" if not lifecycle and name != "bash_disconnect" else None)
        ),
        terminal_seen=terminal,
        owner_task_count=1,
        hook_tasks_remaining=0,
        child_attributed=path == "delegated",
        mcp_invocations=1 if path == "mcp" and ready else 0,
        normalized_denials=(
            1
            if name in {"bash_raw_error", "bash_malformed", "bash_missing_callback"}
            else 0
        ),
        timeout_denials=1 if name == "bash_hung_callback" else 0,
        assistant_errors=[],
        inventory=[target] if active else [],
        returncode=0,
        seconds=1.0,
        attempts=(
            [
                {
                    "name": target,
                    "id": "tool-id",
                    "parent": "agent-parent" if path == "delegated" else None,
                }
            ]
            if active
            else []
        ),
        lifecycle=(
            ["connect", "query", "receive", "disconnect"]
            if active
            else ["connect", "disconnect"]
        ),
        errors=[],
    )
    if path == "edit":
        result["inventory"] = ["Read", "Edit"]
    elif path == "delegated":
        result["inventory"] = ["Task", "Bash"]
        result["attempts"].append(
            {"name": "Agent", "id": "agent-parent", "parent": None}
        )
    if name in {"stop_query", "repeated_cancel"}:
        result.update(
            hook_worker_entered=True,
            hook_worker_finished=True,
            stop_waited_for_hook_worker=True,
        )
    if terminal:
        result["terminal"] = dict(
            subtype="success",
            is_error=False,
            reason="completed",
            cost_usd=0.01,
            permission_denials=0 if ready else 1,
        )
    if name in {
        "bash_storage_fault",
        "bash_stale_execution",
        "bash_storage_during_readiness",
        "bash_stale_during_readiness",
    }:
        during = "during" in name
        result["application_gate"] = dict(
            reason="state_store_failed" if "storage" in name else "stale_execution",
            timing="during_readiness" if during else "before_hook",
            installed_callback=True,
            transition_observed=True,
            readiness_await_entered=during,
            transition_before_readiness_return=during,
        )
    if name == "bash_disconnect":
        result["channel_dropped"] = True
    return result


def complete_evidence():
    mod = module()
    root = Path(mod.__file__).resolve().parents[1]
    return dict(
        permission_mode="dontAsk",
        versions=mod.VERSIONS,
        production_tools=list(mod.DOMAIN_TOOLS),
        model=mod.MODEL,
        cli_sha256="a" * 64,
        case_deadline_seconds=45,
        case_budget_usd=0.2,
        max_queries=31,
        watchdog_seconds=7,
        checker_seconds=5,
        matcher_seconds=10,
        source_sha256={
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in mod.GUARD_SOURCES
        },
        cases=[complete_case(name) for name in mod.REQUIRED_CASES],
    )


def test_complete_matrix_is_accepted_before_mutations():
    assert module().validate_evidence(complete_evidence()) == []


@pytest.mark.parametrize(
    "field",
    [
        "attempted",
        "hook_seen",
        "reaped",
        "cleanup_clean",
        "sentinel_executed",
        "successful_tool_result",
        "post_seen",
        "terminal_seen",
        "owner_task_count",
        "child_attributed",
        "mcp_invocations",
        "normalized_denials",
        "timeout_denials",
        "assistant_errors",
        "inventory",
        "returncode",
        "attempts",
        "lifecycle",
        "seconds",
        "terminal",
    ],
)
def test_missing_case_observation_fails(field):
    record = complete_case()
    del record[field]
    assert module().case_errors(record), field


@pytest.mark.parametrize(
    "field,value",
    [
        ("reaped", 1),
        ("cleanup_clean", "true"),
        ("sentinel_executed", 0),
        ("owner_task_count", True),
        ("mcp_invocations", False),
        ("timeout_denials", -1),
        ("seconds", float("nan")),
        ("returncode", None),
        ("attempts", {}),
        ("lifecycle", []),
        ("inventory", []),
        ("assistant_errors", None),
        ("decision", {}),
    ],
)
def test_wrong_case_types_or_incomplete_observations_fail(field, value):
    record = complete_case()
    record[field] = value
    assert module().case_errors(record)


@pytest.mark.parametrize(
    "name",
    [
        "read_deny",
        "edit_deny",
        "bash_deny",
        "mcp_deny",
        "delegated_deny",
        "stop_connect",
        "stop_idle",
        "stop_query",
        "repeated_cancel",
    ],
)
@pytest.mark.parametrize(
    "field", ["sentinel_executed", "successful_tool_result", "post_seen"]
)
def test_any_execution_on_denial_or_stop_fails(name, field):
    record = complete_case(name)
    assert module().case_errors(record) == []
    record[field] = True
    assert module().case_errors(record)


def test_mcp_handler_entry_is_execution_even_if_sentinel_write_failed():
    record = complete_case("mcp_deny")
    record["mcp_invocations"] = 1
    assert module().case_errors(record)


@pytest.mark.parametrize(
    "field,value",
    [
        ("decision", "deny"),
        ("decision", "allow"),
        ("sentinel_executed", False),
        ("successful_tool_result", False),
        ("post_seen", False),
    ],
)
def test_ready_requires_execution_and_unchanged_ordinary_permissions(field, value):
    record = complete_case("bash_ready")
    record[field] = value
    assert module().case_errors(record)


def test_delegated_and_adapter_observations_cannot_be_omitted():
    for name, field in [
        ("delegated_deny", "child_attributed"),
        ("bash_raw_error", "normalized_denials"),
        ("bash_malformed", "normalized_denials"),
        ("bash_missing_callback", "normalized_denials"),
        ("bash_hung_callback", "timeout_denials"),
        ("bash_disconnect", "channel_dropped"),
    ]:
        record = complete_case(name)
        record[field] = 0
        assert module().case_errors(record)


def test_forced_rescue_and_terminal_errors_cannot_pass():
    record = complete_case("stop_connect")
    record["forced_cleanup"] = True
    assert module().case_errors(record)
    record = complete_case()
    record["terminal"]["is_error"] = True
    assert module().case_errors(record)


@pytest.mark.parametrize(
    "field",
    [
        "versions",
        "production_tools",
        "model",
        "cli_sha256",
        "case_deadline_seconds",
        "case_budget_usd",
        "max_queries",
        "watchdog_seconds",
        "checker_seconds",
        "matcher_seconds",
        "source_sha256",
        "cases",
    ],
)
def test_missing_manifest_field_fails(field):
    evidence = complete_evidence()
    del evidence[field]
    assert module().validate_evidence(evidence)


def test_duplicate_missing_stale_and_malformed_evidence_fails():
    mod = module()
    evidence = complete_evidence()
    evidence["cases"].pop()
    assert mod.validate_evidence(evidence)
    evidence = complete_evidence()
    evidence["cases"][-1] = deepcopy(evidence["cases"][0])
    assert mod.validate_evidence(evidence)
    evidence = complete_evidence()
    evidence["source_sha256"][mod.GUARD_SOURCES[0]] = "0" * 64
    assert mod.validate_evidence(evidence)
    for bad in [None, [], {"cases": [None]}, {"cases": {}}, {"cases": "bad"}]:
        assert mod.validate_evidence(bad)


def test_unverified_exposed_tool_fails_inventory_coverage():
    record = complete_case()
    record["inventory"].append("EndConversation")
    assert module().case_errors(record)


def test_delegated_parent_must_correlate_and_non_delegated_cannot_claim_child():
    record = complete_case("delegated_deny")
    record["attempts"][0]["parent"] = "unobserved-parent"
    assert module().case_errors(record)
    record = complete_case()
    record["child_attributed"] = True
    assert module().case_errors(record)


def test_wrapper_denial_cannot_be_substituted_by_adapter_error():
    record = complete_case("bash_exception")
    record["normalized_denials"] = 1
    assert module().case_errors(record)


def test_parent_bash_fallback_does_not_erase_correlated_child_denial():
    record = complete_case("delegated_timeout")
    record["attempts"].append({"name": "Bash", "id": "parent-fallback", "parent": None})
    record["terminal"]["permission_denials"] = 2
    record["hook_decisions"] = {"parent-fallback": "deny"}
    assert module().case_errors(record) == []
    record["attempts"][0]["parent"] = "unknown-child-parent"
    assert module().case_errors(record)
    record["attempts"][0]["parent"] = None
    record["hook_decisions"]["tool-id"] = "deny"
    assert module().case_errors(record)


def test_parent_bash_fallback_requires_its_own_observed_hook_denial():
    record = complete_case("delegated_timeout")
    record["attempts"].append({"name": "Bash", "id": "parent-fallback", "parent": None})
    assert module().case_errors(record)
    record["hook_decisions"] = {"unrelated": "deny"}
    assert module().case_errors(record)


def test_delegated_ready_needs_child_execution_ids_not_parent_execution():
    record = complete_case("delegated_ready")
    record["successful_tool_ids"] = ["parent-fallback"]
    record["post_tool_ids"] = ["parent-fallback"]
    assert module().case_errors(record)


def test_denied_parent_fallback_cannot_have_result_or_post_effect():
    record = complete_case("delegated_ready")
    record["attempts"].append({"name": "Bash", "id": "parent-fallback", "parent": None})
    record["hook_decisions"] = {"parent-fallback": "deny"}
    record["successful_tool_ids"] = ["tool-id"]
    record["post_tool_ids"] = ["tool-id"]
    assert module().case_errors(record) == []
    record["successful_tool_ids"].append("parent-fallback")
    assert module().case_errors(record)
    record["successful_tool_ids"] = ["tool-id"]
    record["post_tool_ids"].append("parent-fallback")
    assert module().case_errors(record)


def test_probe_and_activation_use_identical_strict_validator():
    from bridge import domain_sdk, tool_guard_evidence

    assert module().validate_evidence is tool_guard_evidence.validate_evidence
    assert domain_sdk.validate_evidence is tool_guard_evidence.validate_evidence
    assert "bridge/tool_guard_evidence.py" in tool_guard_evidence.GUARD_SOURCES


@pytest.mark.parametrize(
    "field",
    [
        "hook_tasks_remaining",
        "hook_worker_entered",
        "hook_worker_finished",
        "stop_waited_for_hook_worker",
    ],
)
def test_lifecycle_requires_observed_hook_io_settlement(field):
    record = complete_case("stop_query")
    record.update(
        hook_tasks_remaining=0,
        hook_worker_entered=True,
        hook_worker_finished=True,
        stop_waited_for_hook_worker=True,
    )
    assert module().case_errors(record) == []
    del record[field]
    assert module().case_errors(record)


@pytest.mark.parametrize("field", ["successful_tool_ids", "post_tool_ids"])
def test_execution_ids_cannot_contradict_false_execution_summary(field):
    record = complete_case("bash_deny")
    record[field] = ["tool-id"]
    assert module().case_errors(record)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "destination",
    ["missing-parent", "existing", "dangling-symlink", "unwritable-parent"],
)
async def test_guard_rejects_invalid_output_before_case(
    tmp_path, monkeypatch, destination
):
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

    async def run_case(name, cli, permission_mode):
        entered.append(name)
        return complete_case(name)

    monkeypatch.setattr(mod, "run_case", run_case)
    with pytest.raises((OSError, ValueError)):
        await mod.main(output, "dontAsk")
    assert not entered
    if destination == "existing":
        assert output.read_bytes() == b"prior evidence"


@pytest.mark.asyncio
async def test_guard_preserves_incomplete_report_after_case_exception(
    tmp_path, monkeypatch
):
    import json

    mod = module()
    entered = []

    async def run_case(name, cli, permission_mode):
        entered.append(name)
        raise RuntimeError("private case diagnostic")

    monkeypatch.setattr(mod, "run_case", run_case)
    output = tmp_path / "failed.json"
    assert await mod.main(output, "dontAsk") == 1
    report = json.loads(output.read_bytes())
    assert entered == ["read_ready"] and report["accepted"] is False
    assert report["cases"] == [] and report["errors"]
    assert "private case diagnostic" not in output.read_text()


@pytest.mark.asyncio
async def test_guard_stages_completed_case_before_entering_next(tmp_path, monkeypatch):
    import json

    mod = module()
    entered, snapshots = [], []

    async def run_case(name, cli, permission_mode):
        entered.append(name)
        if len(entered) == 2:
            staged = list(tmp_path.glob(".report.json.*.tmp"))
            assert len(staged) == 1
            snapshots.append(staged[0].read_bytes())
        record = complete_case(name)
        if len(entered) == 2:
            record["errors"] = ["injected stop after two cases"]
        return record

    monkeypatch.setattr(mod, "run_case", run_case)
    output = tmp_path / "report.json"
    assert await mod.main(output, "dontAsk") == 1
    assert (
        snapshots and snapshots[0]
    ), "completed paid-case observations must be staged before the next case"
    assert [case["name"] for case in json.loads(snapshots[0])["cases"]] == [
        "read_ready"
    ]
    assert [case["name"] for case in json.loads(output.read_bytes())["cases"]] == [
        "read_ready",
        "read_deny",
    ]


def test_evidence_requires_explicit_matching_permission_mode():
    evidence = complete_evidence()
    evidence.pop("permission_mode", None)
    assert module().validate_evidence(evidence)
    evidence["permission_mode"] = "bypassPermissions"
    assert module().validate_evidence(evidence, permission_mode="dontAsk")


def test_acceptance_envelope_retains_independent_modes():
    from bridge.tool_guard_evidence import acceptance_envelope
    from bridge.domain_sdk import check_acceptance

    records = []
    for mode in ("dontAsk", "bypassPermissions"):
        record = complete_evidence()
        record.update(permission_mode=mode, accepted=True, errors=[])
        records.append(record)
    envelope = acceptance_envelope(records)
    for mode in ("dontAsk", "bypassPermissions"):
        assert check_acceptance(envelope, None, mode)["permission_mode"] == mode
    changed = deepcopy(envelope)
    changed["records"]["bypassPermissions"]["cases"][1]["sentinel_executed"] = True
    with pytest.raises(RuntimeError):
        check_acceptance(changed, None, "bypassPermissions")
    with pytest.raises(ValueError):
        acceptance_envelope([records[0], records[0]])
    with pytest.raises(ValueError):
        acceptance_envelope(records[:1])


@pytest.mark.parametrize("mode", ["dontAsk", "bypassPermissions"])
def test_probe_mode_ignores_inherited_configuration(monkeypatch, mode):
    monkeypatch.setenv("BRIDGE_CONFIG_PATH", "/nonexistent/operator-config.json")
    monkeypatch.setenv("PLAZA_DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS", "invalid")
    assert module().probe_config(mode).domain_permission_mode == mode
    with pytest.raises(ValueError):
        module().probe_config(None)


def test_probe_cli_requires_mode_before_any_work(tmp_path):
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, module().__file__, "--output", str(tmp_path / "unused.json")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--permission-mode" in result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("damage", ["mode", "missing", "version", "stale", "runtime"])
def test_envelope_rejects_wrong_missing_stale_or_unverified_record(damage):
    from bridge.tool_guard_evidence import acceptance_envelope
    from bridge.domain_sdk import check_acceptance

    records = []
    for mode in ("dontAsk", "bypassPermissions"):
        record = complete_evidence()
        record.update(permission_mode=mode, accepted=True, errors=[])
        records.append(record)
    envelope = acceptance_envelope(records)
    if damage == "mode":
        envelope["records"]["bypassPermissions"]["permission_mode"] = "dontAsk"
    elif damage == "missing":
        del envelope["records"]["bypassPermissions"]
    elif damage == "version":
        envelope["schema_version"] = True
    elif damage == "stale":
        envelope["records"]["bypassPermissions"]["source_sha256"][
            "bridge/config.py"
        ] = ("0" * 64)
    else:
        envelope["records"]["bypassPermissions"]["versions"] = {}
    with pytest.raises(RuntimeError):
        check_acceptance(envelope, None, "bypassPermissions")


def test_application_state_sources_require_fresh_guard_evidence():
    from bridge.tool_guard_evidence import GUARD_SOURCES

    assert {
        "bridge/application_state.py",
        "bridge/state_image.py",
        "bridge/sqlite_state.py",
        "bridge/state_coordinator.py",
        "bridge/domain_run_state.py",
        "bridge/session_recovery.py",
        "bridge/session_recap.py",
        "bridge/context.py",
        "bridge/project_service.py",
        "bridge/server.py",
    } <= set(GUARD_SOURCES)


@pytest.mark.parametrize(
    "name,reason,timing",
    [
        ("bash_storage_fault", "state_store_failed", "before_hook"),
        ("bash_stale_execution", "stale_execution", "before_hook"),
        ("bash_storage_during_readiness", "state_store_failed", "during_readiness"),
        ("bash_stale_during_readiness", "stale_execution", "during_readiness"),
    ],
)
def test_application_gate_observations_are_required_and_reason_timing_bound(
    name, reason, timing
):
    mod = module()
    record = complete_case(name)
    record["application_gate"] = dict(
        reason=reason,
        timing=timing,
        installed_callback=True,
        transition_observed=True,
        readiness_await_entered=timing == "during_readiness",
        transition_before_readiness_return=timing == "during_readiness",
    )
    assert mod.case_errors(record) == []
    for key in record["application_gate"]:
        incomplete = deepcopy(record)
        del incomplete["application_gate"][key]
        assert mod.case_errors(incomplete), key
    wrong = deepcopy(record)
    wrong["application_gate"]["reason"] = "other"
    assert mod.case_errors(wrong)
    for field in ("normalized_denials", "timeout_denials"):
        wrong = deepcopy(record)
        wrong[field] = 1
        assert mod.case_errors(wrong), field


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "bash_storage_fault",
        "bash_stale_execution",
        "bash_storage_during_readiness",
        "bash_stale_during_readiness",
    ],
)
async def test_application_campaign_installs_real_session_gate_without_provider(
    tmp_path, name
):
    import asyncio
    from bridge.domain_sdk import DomainSDKOwner
    from bridge.readiness import ReadinessService
    from bridge.workspace_lease import WorkspaceLease
    from bridge.tests.test_domain_sdk import Client

    mod = module()
    assert hasattr(mod, "ApplicationGate"), "application campaign fixture missing"
    workspace, memory, lease, runtime, _ = mod.fixture(tmp_path)
    gate = mod.ApplicationGate(name, mod.probe_config("dontAsk"), workspace)
    sdk = None
    try:
        await gate.open()
        lease.release(cleanup_confirmed=True)
        lease = WorkspaceLease.acquire(
            workspace,
            domain_id=workspace.domain_id,
            domain_session_id=gate.session.domain_session_id,
        )
        turn = mod.probe_turn(name, workspace, lease)

        class Ready(ReadinessService):
            async def check_tool(self, lease, **kwargs):
                result = await super().check_tool(lease, **kwargs)
                if kwargs["tool_name"] == "Bash":
                    await gate.during_readiness()
                return result

        service = gate.wrap(Ready(workspace, runtime, memory))
        await service.prepare_turn(turn)
        clients = []

        def factory(**kwargs):
            gate.observe_installed(kwargs["options"].hooks["PreToolUse"][0].hooks[0])
            client = Client(**kwargs)
            clients.append(client)
            return client

        gate.observe_installed(lambda: None)
        assert gate.observations["installed_callback"] is False
        sdk = DomainSDKOwner(
            mod.probe_config("dontAsk"),
            workspace,
            lease,
            service,
            client_factory=factory,
        )
        await sdk.start()
        await gate.before_hook()
        callback = clients[0].options.hooks["PreToolUse"][0].hooks[0]
        answer = await asyncio.create_task(
            callback(
                dict(
                    hook_event_name="PreToolUse",
                    tool_use_id="case-tool",
                    tool_name="Bash",
                    cwd=str(workspace.worktree_path),
                    tool_input={"command": "true"},
                ),
                "case-tool",
                {},
            )
        )
        assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert gate.observations["reason"] == (
            "state_store_failed" if "storage" in name else "stale_execution"
        )
        assert gate.observations["transition_observed"] is True
        assert gate.observations["installed_callback"] is True
        assert gate.observations["readiness_await_entered"] is ("during" in name)
    finally:
        if sdk is not None:
            assert (await sdk.stop()).clean
        await gate.close()
        if "turn" in locals():
            memory.finish_turn(
                turn.turn_id,
                outcome="cancelled",
                output="Offline gate fixture",
                delta=None,
            )
        memory.detach_run("probe-run")
        if lease.held:
            lease.release(cleanup_confirmed=True)
