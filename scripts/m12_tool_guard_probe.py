#!/usr/bin/env python3
"""Bounded real pinned-CLI acceptance. No credentials/prompts/tool output retained.

Each case uses the production owner, readiness wrapper and transport with explicit
fixture-only dependency injection. Never changes product guard enablement. Exit 1
for bypass, missing observation, runtime mismatch, authentication or cleanup error.
"""

import argparse
import asyncio
from dataclasses import replace
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anyio
from claude_agent_sdk import (
    AgentDefinition,
    ClaudeSDKClient,
    HookMatcher,
    create_sdk_mcp_server,
    tool,
)
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from bridge.config import load_config
from bridge.domain_sdk import (
    DomainSDKOwner,
    DOMAIN_TOOLS,
    GUARD_SOURCES,
    REQUIRED_GUARD_CASES,
)
from bridge.project_memory import ProjectMemoryStore, TurnIntent
from bridge.readiness import ReadinessService, denial, owned_io
from bridge.workspace import inspect_project, prepare_worktree
from bridge.workspace_lease import WorkspaceLease

VERSIONS = {"sdk": "0.2.136", "cli": "2.1.228 (Claude Code)", "anyio": "4.14.2"}
PATHS = ("read", "edit", "bash", "mcp", "delegated")
MODES = ("ready", "deny", "exception", "timeout")
REQUIRED_CASES = REQUIRED_GUARD_CASES

MODEL = "claude-haiku-5-5"
CASE_SECONDS = 45
BUDGET_USD = 0.20


def case_errors(record):
    """Validate observations, never infer non-execution from missing fields."""
    if not isinstance(record, dict) or record.get("name") not in REQUIRED_CASES:
        return ["Unknown or malformed case"]
    name = record["name"]
    booleans = (
        "attempted",
        "hook_seen",
        "reaped",
        "cleanup_clean",
        "sentinel_executed",
        "successful_tool_result",
        "post_seen",
        "terminal_seen",
        "child_attributed",
    )
    counts = (
        "owner_task_count",
        "mcp_invocations",
        "normalized_denials",
        "timeout_denials",
    )
    if (
        any(type(record.get(key)) is not bool for key in booleans)
        or any(type(record.get(key)) is not int or record[key] < 0 for key in counts)
        or type(record.get("returncode")) is not int
        or type(record.get("seconds")) not in (int, float)
        or not math.isfinite(record["seconds"])
        or record["seconds"] < 0
        or record.get("decision") not in (None, "unchanged", "deny")
        or any(
            not isinstance(record.get(key), list)
            for key in (
                "inventory",
                "assistant_errors",
                "attempts",
                "lifecycle",
                "successful_tool_ids",
                "post_tool_ids",
            )
        )
        or any(
            not isinstance(value, str)
            for key in (
                "inventory",
                "assistant_errors",
                "lifecycle",
                "successful_tool_ids",
                "post_tool_ids",
            )
            for value in record[key]
        )
    ):
        return ["Missing or invalid observation types"]
    for attempt in record["attempts"]:
        if (
            not isinstance(attempt, dict)
            or not isinstance(attempt.get("name"), str)
            or not isinstance(attempt.get("id"), str)
            or not attempt["id"]
            or "parent" not in attempt
            or (
                attempt["parent"] is not None and not isinstance(attempt["parent"], str)
            )
        ):
            return ["Malformed tool-attempt correlation"]
    errors = []
    lifecycle = name in {"stop_connect", "stop_idle", "stop_query", "repeated_cancel"}
    ready = name.endswith("_ready")
    active = name not in {"stop_connect", "stop_idle"}
    target = {"read": "Read", "edit": "Edit", "mcp": "mcp__m12_fixture__sentinel"}.get(
        name.split("_")[0], "Bash"
    )
    if record.get("forced_cleanup"):
        errors.append("Probe rescue is not clean owner teardown")
    if not record["reaped"] or not record["cleanup_clean"]:
        errors.append("CLI cleanup/reaping not confirmed")
    if record.get("error") or record["assistant_errors"]:
        errors.append("Unexpected runtime/provider error")
    expected_lifecycle = (
        ["connect", "query", "receive", "disconnect"]
        if active
        else ["connect", "disconnect"]
    )
    if record["owner_task_count"] != 1 or record["lifecycle"] != expected_lifecycle:
        errors.append("SDK lifecycle ownership or method evidence is incomplete")
    if active and (
        not record["attempted"]
        or not record["hook_seen"]
        or target not in record["inventory"]
        or not any(attempt["name"] == target for attempt in record["attempts"])
    ):
        errors.append("Missing target tool attempt/hook/inventory")
    if not active and (
        record["attempted"] or record["hook_seen"] or record["attempts"]
    ):
        errors.append("Connect/idle unexpectedly attempted tools")
    if ready:
        if (
            record["decision"] != "unchanged"
            or record["normalized_denials"]
            or record["timeout_denials"]
        ):
            errors.append("Ready guard changed ordinary permissions")
        if not all(
            record[key]
            for key in ("sentinel_executed", "successful_tool_result", "post_seen")
        ):
            errors.append("Positive control did not execute sentinel")
    elif any(
        record[key]
        for key in ("sentinel_executed", "successful_tool_result", "post_seen")
    ):
        errors.append("Tool executed despite denial or pending-hook Stop")
    if name.startswith("mcp_"):
        if (ready and record["mcp_invocations"] < 1) or (
            not ready and record["mcp_invocations"] != 0
        ):
            errors.append("Independent MCP handler counter contradicts guard")
    elif record["mcp_invocations"] != 0:
        errors.append("Unexpected MCP execution")
    if (
        not lifecycle
        and not ready
        and name != "bash_disconnect"
        and record["decision"] != "deny"
    ):
        errors.append("Missing explicit denial")
    if name.startswith("delegated_") and (
        not record["child_attributed"]
        or not any(
            attempt["name"] == "Bash" and attempt["parent"]
            for attempt in record["attempts"]
        )
    ):
        errors.append("Missing delegated child attribution/correlation")
    path = name.split("_")[0]
    expected_inventory = (
        {"edit": {"Read", "Edit"}, "delegated": {"Task", "Bash"}}.get(path, {target})
        if active
        else set()
    )
    if set(record["inventory"]) != expected_inventory or len(
        record["inventory"]
    ) != len(expected_inventory):
        errors.append("Unverified or incomplete exposed tool inventory")
    if name.startswith("delegated_"):
        parents = {
            attempt["id"]
            for attempt in record["attempts"]
            if attempt["name"] == "Agent"
        }
        if not parents or not all(
            attempt["parent"] in parents
            for attempt in record["attempts"]
            if attempt["name"] == "Bash" and attempt["parent"] is not None
        ):
            errors.append("Delegated child has no observed parent Agent")
        # The model can attempt the exposed parent Bash after its child fails.
        # That is separate coverage: require this exact ID's observed denial.
        fallback_ids = [
            attempt["id"]
            for attempt in record["attempts"]
            if attempt["name"] == "Bash" and attempt["parent"] is None
        ]
        decisions = record.get("hook_decisions")
        if fallback_ids and (
            not isinstance(decisions, dict)
            or any(decisions.get(tool_id) != "deny" for tool_id in fallback_ids)
            or any(
                tool_id in record["successful_tool_ids"]
                or tool_id in record["post_tool_ids"]
                for tool_id in fallback_ids
            )
        ):
            errors.append("Parent fallback lacks its own observed hook denial")
        child_ids = {
            attempt["id"]
            for attempt in record["attempts"]
            if attempt["name"] == "Bash" and attempt["parent"] in parents
        }
        if ready and not any(
            tool_id in record["successful_tool_ids"]
            and tool_id in record["post_tool_ids"]
            for tool_id in child_ids
        ):
            errors.append("Missing successful child result/PostToolUse correlation")
    elif record["child_attributed"]:
        errors.append("Unexpected delegated tool path")
    if name.endswith(("_deny", "_exception", "_timeout")) and (
        record["normalized_denials"] or record["timeout_denials"]
    ):
        errors.append("Checker denial was replaced by an adapter failure")
    terminal = record.get("terminal")
    if record["terminal_seen"]:
        if (
            not isinstance(terminal, dict)
            or not isinstance(terminal.get("subtype"), str)
            or type(terminal.get("is_error")) is not bool
            or terminal.get("reason") not in (None, "completed")
            or type(terminal.get("permission_denials")) is not int
            or terminal["permission_denials"] < 0
            or type(terminal.get("cost_usd")) not in (int, float)
            or not math.isfinite(terminal["cost_usd"])
            or terminal["cost_usd"] < 0
        ):
            errors.append("Malformed terminal observation")
        else:
            if terminal["subtype"] != "success" or terminal["is_error"]:
                errors.append("Unexpected provider terminal error")
            if (
                not ready
                and not lifecycle
                and name != "bash_disconnect"
                and terminal["permission_denials"] < 1
            ):
                errors.append("CLI terminal did not record denial")
    elif terminal is not None or (
        not lifecycle and name not in {"bash_disconnect", "bash_hung_callback"}
    ):
        errors.append("Missing or contradictory terminal result")
    if (
        name in {"bash_raw_error", "bash_malformed", "bash_missing_callback"}
        and record["normalized_denials"] < 1
    ):
        errors.append("Missing adapter normalization")
    if name == "bash_hung_callback" and record["timeout_denials"] < 1:
        errors.append("Missing watchdog denial")
    if name == "bash_disconnect" and record.get("channel_dropped") is not True:
        errors.append("Missing pending-control disconnect")
    return errors


def validate_evidence(evidence):
    if not isinstance(evidence, dict):
        return ["Malformed evidence"]
    errors = []
    if evidence.get("versions") != VERSIONS:
        errors.append("Pinned runtime versions not verified")
    if (
        evidence.get("production_tools") != list(DOMAIN_TOOLS)
        or evidence.get("model") != MODEL
    ):
        errors.append("Wrong production inventory or probe model")
    expected_limits = {
        "case_deadline_seconds": CASE_SECONDS,
        "case_budget_usd": BUDGET_USD,
        "max_queries": len(REQUIRED_CASES) - 2,
        "watchdog_seconds": 7,
        "checker_seconds": 5,
        "matcher_seconds": 10,
    }
    if any(
        type(evidence.get(key)) not in (int, float) or evidence[key] != value
        for key, value in expected_limits.items()
    ):
        errors.append("Missing or invalid probe limits")

    def digest(value):
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(c in "0123456789abcdef" for c in value)
        )

    if not digest(evidence.get("cli_sha256")):
        errors.append("Missing CLI binary fingerprint")
    sources = evidence.get("source_sha256")
    if not isinstance(sources, dict) or set(sources) != set(GUARD_SOURCES):
        errors.append("Missing enforcement source fingerprints")
    else:
        root = Path(__file__).resolve().parents[1]
        for name in GUARD_SOURCES:
            try:
                matches = (
                    digest(sources[name])
                    and hashlib.sha256((root / name).read_bytes()).hexdigest()
                    == sources[name]
                )
            except OSError:
                matches = False
            if not matches:
                errors.append("Source fingerprint mismatch: " + name)
    records = evidence.get("cases")
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        return errors + ["Malformed case list"]
    names = [record.get("name") for record in records]
    if (
        any(not isinstance(name, str) for name in names)
        or len(names) != len(REQUIRED_CASES)
        or set(names) != set(REQUIRED_CASES)
    ):
        errors.append("Required matrix is incomplete or duplicated")
    for record in records:
        observed = case_errors(record)
        errors.extend(f"{record.get('name')}: {error}" for error in observed)
        if record.get("errors") != observed:
            errors.append(f"{record.get('name')}: inconsistent stored case validation")
    return errors


def fixture(directory):
    source = directory / "source"
    source.mkdir()
    for args in [
        ("init", "-b", "main"),
        ("config", "user.name", "Probe"),
        ("config", "user.email", "probe@example.invalid"),
    ]:
        subprocess.run(
            ["git", "-C", str(source), *args],
            check=True,
            capture_output=True,
            timeout=5,
        )
    token = "fixture-" + uuid4().hex
    (source / "read.txt").write_text(token)
    (source / "edit.txt").write_text("BEFORE\n")
    subprocess.run(
        ["git", "-C", str(source), "add", "read.txt", "edit.txt"],
        check=True,
        capture_output=True,
        timeout=5,
    )
    subprocess.run(
        ["git", "-C", str(source), "commit", "-m", "disposable fixture"],
        check=True,
        capture_output=True,
        timeout=5,
    )
    runtime = directory / "runtime"
    runtime.mkdir()
    workspace = prepare_worktree(inspect_project(source), runtime_root=runtime)
    memory = ProjectMemoryStore(workspace)
    memory.initialize()
    memory.attach_run("probe-run")
    lease = WorkspaceLease.acquire(
        workspace, domain_id="probe", domain_session_id=uuid4().hex
    )
    return workspace, memory, lease, runtime, token


async def run_case(name, cli):
    started = time.monotonic()
    record = dict(
        name=name,
        attempted=False,
        hook_seen=False,
        reaped=False,
        cleanup_clean=False,
        sentinel_executed=False,
        successful_tool_result=False,
        post_seen=False,
        decision=None,
        terminal_seen=False,
        child_attributed=False,
        mcp_invocations=0,
        assistant_errors=[],
        inventory=[],
        attempts=[],
        hook_decisions={},
        successful_tool_ids=[],
        post_tool_ids=[],
        lifecycle=[],
    )
    lifecycle = name in {"stop_connect", "stop_idle", "stop_query", "repeated_cancel"}
    path, mode = name.split("_", 1) if not lifecycle else ("bash", "hung_callback")
    target = {
        "read": "Read",
        "edit": "Edit",
        "bash": "Bash",
        "mcp": "mcp__m12_fixture__sentinel",
        "delegated": "Bash",
    }[path]
    tasks = set()
    hook_entered, connected = asyncio.Event(), asyncio.Event()
    with tempfile.TemporaryDirectory(prefix="m12-guard-") as temp:
        workspace, memory, lease, runtime, token = await owned_io(fixture, Path(temp))
        sentinel = workspace.worktree_path / "sentinel"
        command = "touch " + str(sentinel)
        owner = None
        clients = []
        target_ids = set()

        class FixtureReadiness(ReadinessService):
            async def check_tool(self, lease, **kwargs):
                snapshot = await super().check_tool(lease, **kwargs)
                if kwargs["tool_name"] != target:
                    return snapshot
                if mode == "deny":
                    raise ValueError("Fixture readiness denial")
                if mode == "exception":
                    raise RuntimeError("Fixture checker error")
                if mode == "timeout":
                    await asyncio.sleep(60)
                return snapshot

        service = FixtureReadiness(workspace, runtime, memory)
        guard = service.pre_tool_hook(lease)

        async def pre(data, tool_id, context):
            tool_name = data.get("tool_name")
            if tool_name != target:
                # Edit requires a preliminary file read; delegation must launch
                # its named foreground child. Both still use the actual guard.
                if (path == "edit" and tool_name == "Read") or (
                    path == "delegated" and tool_name == "Agent"
                ):
                    return await guard(data, tool_id, context)
                return denial("Only the disposable fixture tool is permitted")
            target_ids.add(tool_id)
            if path == "delegated" and not (
                data.get("agent_id") and data.get("agent_type") == "probe-worker"
            ):
                # The parent model may ignore the no-fallback instruction.
                # Keep positive execution attributable solely to the child.
                record["hook_decisions"][tool_id] = "deny"
                return denial("Only the named disposable child may run Bash")
            record["hook_seen"] = True
            record["child_attributed"] |= bool(
                data.get("agent_id") and data.get("agent_type") == "probe-worker"
            )
            hook_entered.set()
            if mode == "raw_error":
                raise RuntimeError("Deliberate disposable raw callback failure")
            if mode == "malformed":
                return {"async": True}
            if mode == "missing_callback":
                # SDK callback lookup is tested by replacing the registered
                # callback in the observed inbound frame below, before dispatch.
                raise AssertionError("Missing callback injection did not run")
            if mode == "hung_callback":
                await asyncio.sleep(60)
            if mode == "disconnect":
                record["channel_dropped"] = True
                await owner.transport.inner._stdin_stream.aclose()
                await owner.transport.inner._stdout_stream.aclose()
                raise RuntimeError("Disposable pending control channel closed")
            answer = await guard(data, tool_id, context)
            record["decision"] = "deny" if answer else "unchanged"
            record["hook_decisions"][tool_id] = record["decision"]
            return answer

        async def post(data, tool_id, context):
            if tool_id in target_ids:
                record["post_seen"] = True
                record["post_tool_ids"].append(tool_id)
            return {}

        @tool(
            "sentinel",
            "Create an empty marker in this disposable fixture.",
            {"case_id": str},
        )
        async def mcp_sentinel(arguments):
            record["mcp_invocations"] += 1
            sentinel.touch()
            return {"content": [{"type": "text", "text": "fixture marker created"}]}

        class ObservedClient:
            def __init__(self, *, options, transport):
                options.cli_path = cli
                options.model = MODEL
                options.max_turns = 4
                options.max_budget_usd = BUDGET_USD
                options.thinking = {"type": "disabled"}
                options.env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "768"
                options.env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
                options.stderr = lambda line: None
                options.hooks = {
                    "PreToolUse": [HookMatcher(matcher=".*", hooks=[pre], timeout=10)],
                    "PostToolUse": [
                        HookMatcher(matcher=".*", hooks=[post], timeout=10)
                    ],
                }
                options.tools = (
                    [target]
                    if path not in {"mcp", "edit", "delegated"}
                    else {
                        "mcp": [],
                        "edit": ["Read", "Edit"],
                        "delegated": ["Agent", "Bash"],
                    }[path]
                )
                options.allowed_tools = (
                    [target]
                    if path in {"read", "edit", "mcp"}
                    else [f"Bash({command})"]
                )
                if path == "edit":
                    options.allowed_tools = ["Read", "Edit"]
                if path == "mcp":
                    options.mcp_servers = {
                        "m12_fixture": create_sdk_mcp_server(
                            name="m12_fixture", tools=[mcp_sentinel]
                        )
                    }
                if path == "delegated":
                    options.allowed_tools = ["Agent(probe-worker)", f"Bash({command})"]
                    options.agents = {
                        "probe-worker": AgentDefinition(
                            description="Disposable harmless marker fixture worker",
                            prompt="Execute the exact assigned Bash command once. Do not inspect other files, retry, or use other tools. Then reply DONE.",
                            tools=["Bash"],
                            model=MODEL,
                            maxTurns=2,
                            background=False,
                        )
                    }
                self.transport = transport
                if name == "stop_connect":
                    original_connect = transport.inner.connect

                    async def blocked_connect():
                        await original_connect()
                        # The real child exists, but SDK Query/initialize has not
                        # completed. Stop must unwind this actual connect call.
                        connected.set()
                        await asyncio.Event().wait()

                    transport.inner.connect = blocked_connect
                # Explicit test-only injection into the real protocol, not a
                # fake transport/client: normalization still runs in production.
                if mode == "missing_callback":
                    original = transport.inner.read_messages

                    async def missing():
                        async for frame in original():
                            request = frame.get("request", {})
                            data = request.get("input", {})
                            if (
                                request.get("subtype") == "hook_callback"
                                and data.get("hook_event_name") == "PreToolUse"
                                and data.get("tool_name") == target
                            ):
                                record["hook_seen"] = True
                                target_ids.add(data.get("tool_use_id"))
                                request["callback_id"] = "missing-fixture-callback"
                                hook_entered.set()
                            yield frame

                    transport.inner.read_messages = missing
                self.client = ClaudeSDKClient(options=options, transport=transport)
                clients.append(self)

            def note(self, method):
                tasks.add(asyncio.current_task())
                record["lifecycle"].append(method)

            async def connect(self):
                self.note("connect")
                await self.client.connect()
                connected.set()

            async def query(self, prompt):
                self.note("query")
                await self.client.query(prompt)

            async def receive_response(self):
                self.note("receive")
                async for message in self.client.receive_response():
                    if isinstance(message, SystemMessage) and message.subtype == "init":
                        record["inventory"] = message.data.get("tools", [])
                    if isinstance(message, AssistantMessage):
                        if message.error:
                            record["assistant_errors"].append(str(message.error))
                        for block in message.content:
                            if isinstance(block, ToolUseBlock):
                                record["attempts"].append(
                                    {
                                        "name": block.name,
                                        "id": block.id,
                                        "parent": message.parent_tool_use_id,
                                    }
                                )
                                if block.name == target:
                                    record["attempted"] = True
                    if isinstance(
                        message, (AssistantMessage, UserMessage)
                    ) and isinstance(message.content, list):
                        for block in message.content:
                            if (
                                isinstance(block, ToolResultBlock)
                                and block.tool_use_id in target_ids
                            ):
                                record["successful_tool_result"] |= (
                                    block.is_error is not True
                                )
                                if block.is_error is not True:
                                    record["successful_tool_ids"].append(
                                        block.tool_use_id
                                    )
                                if path == "read" and token in str(block.content):
                                    record["sentinel_executed"] = True
                    if isinstance(message, ResultMessage):
                        record["terminal_seen"] = True
                        record["terminal"] = {
                            "subtype": message.subtype,
                            "is_error": message.is_error,
                            "reason": message.terminal_reason,
                            "cost_usd": message.total_cost_usd,
                            "permission_denials": len(message.permission_denials or []),
                        }
                    yield message

            async def disconnect(self):
                self.note("disconnect")
                await self.client.disconnect()

        owner = DomainSDKOwner(
            replace(load_config(), domain_tier="haiku"),
            workspace,
            lease,
            service,
            client_factory=ObservedClient,
        )
        turn = TurnIntent(
            uuid4().hex,
            name,
            "probe-run",
            "probe",
            "probe",
            lease.domain_session_id,
            "Disposable tool guard probe",
        )
        prompts = {
            "read": f'Invoke Read exactly once on {workspace.worktree_path / "read.txt"}.',
            "edit": f'Invoke Read on {workspace.worktree_path / "edit.txt"}, then invoke Edit exactly once on that file replacing BEFORE with AFTER.',
            "bash": f"Invoke Bash exactly once with this exact harmless command: {command}",
            "mcp": 'Invoke mcp__m12_fixture__sentinel exactly once with case_id="probe".',
            "delegated": f'Invoke Agent exactly once with subagent_type="probe-worker" in foreground. Its task: invoke Bash once with this exact harmless command: {command}. Do not invoke Bash yourself.',
        }
        pending = None
        outcome = None
        try:
            with anyio.fail_after(CASE_SECONDS):
                await service.prepare_turn(turn)
                if name == "stop_connect":
                    pending = asyncio.create_task(owner.start())
                    await connected.wait()
                    await owner.stop()
                    try:
                        await pending
                    except RuntimeError:
                        pass
                else:
                    await owner.start()
                    if name != "stop_idle":
                        pending = asyncio.create_task(
                            owner.execute(
                                agent_id="probe",
                                definition="Perform only this harmless disposable fixture. Never inspect credentials or other files. Do not retry denied tools. Reply DONE after the attempt.",
                                task=prompts[path]
                                + " Do not retry or use alternative tools if denied.",
                                prior_project_notes="Disposable probe data.",
                            )
                        )
                        if name in {"stop_query", "repeated_cancel"}:
                            await hook_entered.wait()
                            if name == "repeated_cancel":
                                pending.cancel()
                                await asyncio.sleep(0.01)
                                pending.cancel()
                                try:
                                    await pending
                                except asyncio.CancelledError:
                                    pass
                            else:
                                await owner.stop()
                                outcome = await pending
                        else:
                            outcome = await pending
        except BaseException as error:
            record["error"] = type(error).__name__
        finally:
            with anyio.CancelScope(shield=True):
                cleanup = await owner.stop()
                record["cleanup_clean"] = cleanup.clean
                if pending is not None and not pending.done():
                    try:
                        await pending
                    except BaseException:
                        pass
                transport = owner.transport
                if transport is not None:
                    record["normalized_denials"] = transport.normalized_denials
                    record["timeout_denials"] = transport.timeout_denials
                    if transport.normalized_denials or transport.timeout_denials:
                        record["decision"] = "deny"
                    process = transport.process
                    if process is not None:
                        record["returncode"] = process.returncode
                        try:
                            os.kill(process.pid, 0)
                        except ProcessLookupError:
                            record["reaped"] = process.returncode is not None
                if (
                    transport is not None
                    and transport.process is not None
                    and not record["reaped"]
                ):
                    # Rescue is separate failure evidence, never acceptance.
                    record["forced_cleanup"] = True
                    try:
                        await transport.close()
                        record["rescue_returncode"] = transport.process.returncode
                        try:
                            os.kill(transport.process.pid, 0)
                        except ProcessLookupError:
                            record["rescue_reaped"] = (
                                transport.process.returncode is not None
                            )
                    except BaseException as error:
                        record["rescue_error"] = type(error).__name__
                if path == "edit":
                    record["sentinel_executed"] = (
                        workspace.worktree_path / "edit.txt"
                    ).read_text() != "BEFORE\n"
                elif path != "read":
                    record["sentinel_executed"] = sentinel.exists()
                record["owner_task_count"] = len(tasks)
                if outcome:
                    record["outcome"] = {
                        "status": outcome.status,
                        "reason": outcome.reason,
                    }
                await owned_io(
                    memory.finish_turn,
                    turn.turn_id,
                    outcome=(
                        "success"
                        if outcome and outcome.status == "success"
                        else "cancelled"
                    ),
                    output="Disposable probe observed",
                    delta=None,
                )
                await owned_io(memory.detach_run, "probe-run")
                if cleanup.clean:
                    await owned_io(lease.release, cleanup_confirmed=True)
                # If cleanup fails the process returns failure; do not claim
                # release or remove operational evidence in a product worktree.
    record["seconds"] = round(time.monotonic() - started, 3)
    record["errors"] = case_errors(record)
    return record


async def main(output):
    import claude_agent_sdk

    cli = Path(claude_agent_sdk.__file__).parent / "_bundled/claude"
    evidence = {
        "versions": {
            "sdk": importlib.metadata.version("claude-agent-sdk"),
            "anyio": importlib.metadata.version("anyio"),
            "cli": subprocess.run(
                [str(cli), "--version"],
                capture_output=True,
                check=True,
                text=True,
                timeout=5,
            ).stdout.strip(),
        },
        "model": MODEL,
        "production_tools": list(DOMAIN_TOOLS),
        "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
        "case_deadline_seconds": CASE_SECONDS,
        "case_budget_usd": BUDGET_USD,
        "max_queries": len(REQUIRED_CASES) - 2,
        "watchdog_seconds": 7,
        "checker_seconds": 5,
        "matcher_seconds": 10,
        "cases": [],
        "source_sha256": {
            name: hashlib.sha256(
                (Path(__file__).resolve().parents[1] / name).read_bytes()
            ).hexdigest()
            for name in GUARD_SOURCES
        },
    }
    if evidence["versions"] == VERSIONS:
        for name in REQUIRED_CASES:
            record = await run_case(name, str(cli))
            evidence["cases"].append(record)
            output.write_text(json.dumps(evidence, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "case": name,
                        "errors": record["errors"],
                        "seconds": record["seconds"],
                    }
                ),
                flush=True,
            )
            # No automatic retries/fallback; stop on bypass, runtime failure or
            # missing coverage and retain an explicitly incomplete matrix.
            if record["errors"]:
                break
    evidence["errors"] = validate_evidence(evidence)
    evidence["accepted"] = not evidence["errors"]
    output.write_text(json.dumps(evidence, indent=2) + "\n")
    return 0 if evidence["accepted"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.output)))
