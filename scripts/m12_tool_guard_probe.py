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
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
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

from scripts.evidence_output import FreshEvidenceOutput

from bridge.application_state import StateCommand, StateError
from bridge.domain_manager import DomainManager
from bridge.domain_protocol import DomainCommandError
from bridge.domain_session import DomainSession, _ExecutionReadiness
from bridge.state_coordinator import StateCoordinator, LazySQLiteStateRepository
from bridge.config import default_config
from bridge.domain_sdk import (
    DomainSDKOwner,
    DOMAIN_TOOLS,
    GUARD_SOURCES,
    REQUIRED_GUARD_CASES,
)
from bridge.tool_guard_evidence import (
    VERSIONS,
    REQUIRED_CASES,
    MODEL,
    CASE_SECONDS,
    BUDGET_USD,
    case_errors,
    validate_evidence,
    PERMISSION_MODES,
)
from bridge.project_memory import ProjectMemoryStore, TurnIntent
from bridge.readiness import ReadinessService, denial, owned_io
from bridge.workspace import inspect_project, prepare_worktree
from bridge.workspace_lease import WorkspaceLease


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
        workspace, domain_id=workspace.domain_id, domain_session_id=uuid4().hex
    )
    return workspace, memory, lease, runtime, token


def probe_turn(name, workspace, lease):
    return TurnIntent(
        uuid4().hex,
        name,
        "probe-run",
        "probe",
        workspace.domain_id,
        lease.domain_session_id,
        "Disposable tool guard probe",
        workspace_id=workspace.workspace_id,
    )


class ApplicationGate:
    """Disposable actual state owner and manager authority behind installed hooks.

    Failure injection is confined to this image's durable replacement boundary.
    Both coordinator health and the manager's current execution are production
    checks; the campaign never substitutes a synthetic permission denial.
    """

    def __init__(self, name, config, workspace):
        self.name, self.config, self.workspace = name, config, workspace
        self.coordinator = StateCoordinator(
            lambda: LazySQLiteStateRepository(
                workspace.common_git_dir, workspace.project_id
            )
        )
        self.manager = DomainManager(
            config,
            SimpleNamespace(owner_run_id="probe-run"),
            state_coordinator=self.coordinator,
        )
        self.session = None
        self._transitioned = False
        self.observations = dict(
            reason=None,
            timing="during_readiness" if "during" in name else "before_hook",
            installed_callback=False,
            transition_observed=False,
            readiness_await_entered=False,
            transition_before_readiness_return=False,
        )

    async def open(self):
        await self.coordinator.open()
        await self._start(0)

    async def _start(self, revision):
        commit = await self.coordinator.commit(
            StateCommand(
                "start",
                dict(
                    domain_id=self.workspace.domain_id,
                    expected_domain_revision=revision,
                    boot_id=str(uuid4()),
                    execution_id=str(uuid4()),
                    timestamp="probe-start",
                ),
            )
        )
        session = DomainSession(
            self.workspace.domain_id,
            commit.result["session_id"],
            config=self.config,
            project_service=self.manager._service,
            execution_id=commit.result["execution_id"],
            coordinator=self.coordinator,
            authority_check=self.manager._check_authority,
        )
        self.manager._sessions.setdefault(session.domain_id, []).append(session)
        if self.session is None:
            self.session = session

    def check(self):
        try:
            self.session._require_state_ready()
        except (StateError, DomainCommandError) as error:
            self.observations["reason"] = error.code
            raise

    def wrap(self, readiness):
        return _ExecutionReadiness(readiness, self.check)

    def observe_installed(self, callback):
        # The caller captures this from options.hooks before installing the
        # observation wrapper. No independently recreated readiness callback.
        self.observations["installed_callback"] = (
            getattr(callback, "__func__", None) is DomainSDKOwner._pre_tool_hook
            and isinstance(getattr(callback, "__self__", None), DomainSDKOwner)
            and isinstance(callback.__self__.readiness, _ExecutionReadiness)
        )

    async def transition(self):
        if self._transitioned:
            return
        self._transitioned = True
        before = self.coordinator.snapshot()
        stop = StateCommand(
            "stop",
            dict(
                execution_id=self.session.execution_id,
                outcome="stopped",
                timestamp="probe-stop",
            ),
        )
        if "storage" in self.name:
            image = self.coordinator._repository._image
            original = image.replace

            def fail_replace(data):
                raise StateError("state_store_failed")

            image.replace = fail_replace
            try:
                try:
                    await self.coordinator.commit(stop)
                except StateError as error:
                    if error.code != "state_store_failed":
                        raise
                else:
                    raise AssertionError("Expected actual coordinator commit failure")
            finally:
                image.replace = original
            self.observations["transition_observed"] = (
                not self.coordinator.admission_open
                and self.coordinator.health == "state_store_failed"
                and self.coordinator.snapshot() == before
            )
        else:
            stopped = await self.coordinator.commit(stop)
            revision = next(
                d.domain_revision
                for d in stopped.view.domains
                if d.domain_id == self.session.domain_id
            )
            await self._start(revision)
            current = self.manager._current(self.session.domain_id)
            self.observations["transition_observed"] = (
                self.coordinator.admission_open
                and current is not self.session
                and current.domain_session_id == self.session.domain_session_id
                and current.execution_id != self.session.execution_id
                and any(
                    e.execution_id == current.execution_id
                    for e in self.coordinator.snapshot().executions
                )
            )

    async def before_hook(self):
        if "during" not in self.name:
            await self.transition()

    async def during_readiness(self):
        if "during" in self.name:
            self.observations["readiness_await_entered"] = True
            # Await real worker commits while the original readiness callback
            # remains on stack, then return its pre-transition ready snapshot.
            await self.transition()
            self.observations["transition_before_readiness_return"] = True

    async def close(self):
        await self.coordinator.close()


async def run_case(name, cli, permission_mode):
    config = probe_config(permission_mode)
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
    if name in {"stop_query", "repeated_cancel"}:
        mode = "lifecycle_io"
    target = {
        "read": "Read",
        "edit": "Edit",
        "bash": "Bash",
        "mcp": "mcp__m12_fixture__sentinel",
        "delegated": "Bash",
    }[path]
    tasks = set()
    hook_entered, connected = asyncio.Event(), asyncio.Event()
    disconnected = asyncio.Event()
    io_entered, io_release, io_finished = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def blocked_hook_read():
        io_entered.set()
        if not io_release.wait(10):
            raise RuntimeError("Disposable hook IO release timed out")
        io_finished.set()

    with tempfile.TemporaryDirectory(prefix="m12-guard-") as temp:
        workspace, memory, lease, runtime, token = await owned_io(fixture, Path(temp))
        sentinel = workspace.worktree_path / "sentinel"
        command = "touch " + str(sentinel)
        owner = None
        clients = []
        target_ids = set()
        application = None
        guard = None

        class FixtureReadiness(ReadinessService):
            async def check_tool(self, lease, **kwargs):
                snapshot = await super().check_tool(lease, **kwargs)
                if kwargs["tool_name"] != target:
                    return snapshot
                if application is not None:
                    await application.during_readiness()
                if mode == "lifecycle_io":
                    await owned_io(blocked_hook_read)
                if mode == "deny":
                    raise ValueError("Fixture readiness denial")
                if mode == "exception":
                    raise RuntimeError("Fixture checker error")
                if mode == "timeout":
                    await asyncio.sleep(60)
                return snapshot

        service = FixtureReadiness(workspace, runtime, memory)
        if name in {
            "bash_storage_fault",
            "bash_stale_execution",
            "bash_storage_during_readiness",
            "bash_stale_during_readiness",
        }:
            application = ApplicationGate(name, config, workspace)
            await application.open()
            await owned_io(lease.release, cleanup_confirmed=True)
            lease = await owned_io(
                WorkspaceLease.acquire,
                workspace,
                domain_id=workspace.domain_id,
                domain_session_id=application.session.domain_session_id,
            )
            service = application.wrap(service)
            record["application_gate"] = application.observations

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
            if application is not None:
                await application.before_hook()
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
                nonlocal guard
                guard = options.hooks["PreToolUse"][0].hooks[0]
                if application is not None:
                    application.observe_installed(guard)
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
                            permissionMode=permission_mode,
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
                disconnected.set()

        owner = DomainSDKOwner(
            config,
            workspace,
            lease,
            service,
            client_factory=ObservedClient,
        )
        turn = probe_turn(name, workspace, lease)
        prompts = {
            "read": f'Invoke Read exactly once on {workspace.worktree_path / "read.txt"}.',
            "edit": f'Invoke Read on {workspace.worktree_path / "edit.txt"}, then invoke Edit exactly once on that file replacing BEFORE with AFTER.',
            "bash": f"Invoke Bash exactly once with this exact harmless command: {command}",
            "mcp": 'Invoke mcp__m12_fixture__sentinel exactly once with case_id="probe".',
            "delegated": f'Invoke Agent exactly once with subagent_type="probe-worker" in foreground. Its task: invoke Bash once with this exact harmless command: {command}. Do not invoke Bash yourself.',
        }
        pending = None
        stopping = None
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
                            while not io_entered.is_set():
                                await asyncio.sleep(0.001)
                            if name == "repeated_cancel":
                                pending.cancel()
                                await disconnected.wait()
                                pending.cancel()
                                await asyncio.sleep(0)
                                record["stop_waited_for_hook_worker"] = (
                                    not pending.done() and not io_finished.is_set()
                                )
                                io_release.set()
                                try:
                                    await pending
                                except asyncio.CancelledError:
                                    pass
                            else:
                                stopping = asyncio.create_task(owner.stop())
                                await disconnected.wait()
                                await asyncio.sleep(0)
                                record["stop_waited_for_hook_worker"] = (
                                    not stopping.done() and not io_finished.is_set()
                                )
                                io_release.set()
                                await stopping
                                outcome = await pending
                        else:
                            outcome = await pending
        except BaseException as error:
            record["error"] = type(error).__name__
        finally:
            with anyio.CancelScope(shield=True):
                io_release.set()
                cleanup = await owner.stop()
                if stopping is not None:
                    await stopping
                record["cleanup_clean"] = cleanup.clean
                record["hook_tasks_remaining"] = owner._hook_tasks.active_count
                if mode == "lifecycle_io":
                    record["hook_worker_entered"] = io_entered.is_set()
                    record["hook_worker_finished"] = io_finished.is_set()
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
                if application is not None:
                    await application.close()
                await owned_io(memory.detach_run, "probe-run")
                if cleanup.clean:
                    await owned_io(lease.release, cleanup_confirmed=True)
                # If cleanup fails the process returns failure; do not claim
                # release or remove operational evidence in a product worktree.
    record["seconds"] = round(time.monotonic() - started, 3)
    record["errors"] = case_errors(record)
    return record


def probe_config(permission_mode):
    if permission_mode not in PERMISSION_MODES:
        raise ValueError("Explicit permission mode is required")
    return replace(
        default_config(),
        domain_tier="haiku",
        domain_dangerously_skip_permissions=permission_mode == "bypassPermissions",
    )


async def main(output, permission_mode):
    with FreshEvidenceOutput(output) as destination:
        return await _run(destination, permission_mode)


async def _run(output, permission_mode):
    probe_config(permission_mode)
    import claude_agent_sdk

    cli = Path(claude_agent_sdk.__file__).parent / "_bundled/claude"
    evidence = {
        "permission_mode": permission_mode,
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
    failure = None
    try:
        if evidence["versions"] == VERSIONS:
            for name in REQUIRED_CASES:
                record = await run_case(name, str(cli), permission_mode)
                evidence["cases"].append(record)
                # Keep paid-case observations on disk during the next case;
                # the public destination is claimed only by final publication.
                output.checkpoint_json(evidence)
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
    except BaseException as error:
        # Preserve the partial matrix, without publishing private diagnostics.
        failure = "probe interrupted: " + type(error).__name__
    finally:
        evidence["errors"] = validate_evidence(evidence)
        if failure:
            evidence["errors"].append(failure)
        evidence["accepted"] = not evidence["errors"]
        output.publish_json(evidence)
    return 0 if evidence["accepted"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--permission-mode", required=True, choices=PERMISSION_MODES)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.output, args.permission_mode)))
