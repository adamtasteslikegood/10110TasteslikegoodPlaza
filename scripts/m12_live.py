#!/usr/bin/env python3
"""Bounded paid M12 acceptance; one attempt, preserved external artifacts.

Run deliberately with --output PATH. No retries, evidence activation or desktop
acceptance. Internal --child mode composes the real serve(stop_event) lifecycle.
"""

import argparse
import asyncio
from contextlib import AbstractContextManager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.evidence_output import FreshEvidenceOutput

ROOT = Path(__file__).resolve().parents[1]
RESULT = "m12-result.txt"
STAGE_SECONDS = 100
DRAIN_SECONDS = 35
INSTRUMENTATION = (
    "same SDK class: forward init/connect/query/receive_response/disconnect once; "
    "allowlisted options and messages only; original default factory; "
    "unchanged owner construction observed at domain_session binding; "
    "delegating dispatch emission and loopback ephemeral listener observation; "
    "explicit fixture-extra-a/fixture-extra-b registry; owner execute context diagnostics only"
)
# Fingerprint the exercised production paths and physical driver; never refresh old reports.
from bridge.domain_sdk import GUARD_SOURCES

LIVE_SOURCES = tuple(
    dict.fromkeys(
        (
            *GUARD_SOURCES,
            "scripts/m12_live.py",
            "scripts/m12_stages.py",
            "tests/godot_domain_integration.gd",
            "tests/godot_domain_integration.tscn",
            "tests/character_fixture.gd",
            "bridge/context.py",
            "bridge/context/GAME_CONTEXT.md",
            "bridge/context/WORK_CONTEXT.md",
            "bridge/agent_bindings.py",
            "bridge/agent_bindings.json",
            "bridge/extras.json",
            "bridge/server.py",
            "bridge/project_service.py",
            "bridge/project_memory.py",
            "bridge/workspace.py",
            "bridge/workspace_lease.py",
            "bridge/domain_session.py",
            "bridge/domain_manager.py",
            "bridge/domain_protocol.py",
            "bridge/interaction_protocol.py",
            "bridge/conversation_backend.py",
            "bridge/conversation_sdk.py",
            "bridge/repository_setup.py",
            "bridge/agents.py",
            "bridge/agents/systems-architect.md",
            "scenes/bridge/ws_client.gd",
            "scenes/bridge/domain_store.gd",
            "scenes/bridge/domain_surface.gd",
            "scenes/hud/dialogue_panel.gd",
            "scenes/hud/dialogue_panel.tscn",
            "scenes/hud/domain_panel.gd",
            "scenes/hud/domain_panel.tscn",
            "autoload/GameEvents.gd",
            "autoload/AgentRegistry.gd",
            "scenes/main.tscn",
            "project.godot",
            "data/agents.json",
        )
    )
)

INITIAL_CHECKS = (
    "referral_no_review",
    "real_chief_approved",
    "main_seed",
    "three_notes",
    "separate_paths",
    "source_unchanged",
    "runtime_unchanged",
    "absent_before",
    "background_corroborated",
    "npc_corroborated",
    "sdk_only_result",
    "tool_cwd",
    "same_plain_output",
    "one_rendered_result",
    "memory_saved",
    "stop_inactive",
    "lease_released",
)
RESTART_CHECKS = (
    "fresh_owner",
    "same_workspace",
    "same_memory",
    "no_automatic_query",
    "notes_in_query",
    "nonce_not_in_task",
    "notes_readback",
    "result_unchanged",
    "stop_inactive",
)
ISOLATION_CHECKS = (
    "different_identity",
    "own_three_notes",
    "no_a_notes",
    "no_a_nonce_in_query",
    "isolated_readback",
    "a_unchanged",
    "no_automatic_query",
    "stop_inactive",
)


class AcceptanceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def godot_binary():
    binary = shutil.which(os.environ.get("GODOT_BIN", "godot"))
    require(binary is not None, "requested Godot executable unavailable")
    return binary


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def read_result(execution):
    """Read only the bounded regular result at the canonical execution location."""
    execution = Path(execution).absolute()
    directory_fd = result_fd = None
    try:
        require(
            execution.resolve(strict=True) == execution,
            "result parent is not canonical",
        )
        directory_fd = os.open(execution, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        parent = os.fstat(directory_fd)
        current_parent = execution.stat(follow_symlinks=False)
        require(
            (parent.st_dev, parent.st_ino)
            == (current_parent.st_dev, current_parent.st_ino),
            "result parent changed",
        )
        before = os.stat(RESULT, dir_fd=directory_fd, follow_symlinks=False)
        require(
            stat.S_ISREG(before.st_mode), "result must be a regular non-symlink file"
        )
        result_fd = os.open(
            RESULT, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
        )
        opened = os.fstat(result_fd)
        require(
            stat.S_ISREG(opened.st_mode)
            and (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino)
            and opened.st_size <= 65536,
            "result file changed or exceeds its bound",
        )
        chunks, size = [], 0
        while True:
            chunk = os.read(result_fd, min(8192, 65537 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            require(size <= 65536, "result file exceeds its bound")
        after = os.fstat(result_fd)
        current = os.stat(RESULT, dir_fd=directory_fd, follow_symlinks=False)
        require(
            (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            )
            == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            and (current.st_dev, current.st_ino) == (after.st_dev, after.st_ino)
            and execution.resolve(strict=True) == execution
            and execution.stat(follow_symlinks=False) == current_parent,
            "result location or content changed while reading",
        )
        return b"".join(chunks)
    except OSError as error:
        raise AcceptanceError("result location is unavailable or unsafe") from error
    finally:
        if result_fd is not None:
            os.close(result_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def read_json(path):
    require(
        path.is_file() and path.stat().st_size <= 4 * 1024 * 1024,
        "missing/oversized JSON artifact",
    )

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    return json.loads(
        path.read_text(),
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(
            AcceptanceError("nonfinite JSON")
        ),
    )


class NonceGate:
    def __init__(self, release_path, result_path):
        self.release_path, self.result_path = Path(release_path), Path(result_path)
        self.released_monotonic = None
        self.released_utc = None

    def assert_absent(self):
        require(
            not self.release_path.exists() and not self.result_path.exists(),
            "release/result existed before release",
        )

    def release(self, *, background, npc):
        require(
            all(
                type(v) in (int, float) and math.isfinite(v) and v > 0
                for v in (background, npc)
            ),
            "release requires corroborated background and rendered NPC receipts",
        )
        self.assert_absent()
        nonce = "m12-" + uuid4().hex
        with self.release_path.open("x") as handle:
            handle.write(nonce)
        self.released_monotonic, self.released_utc = time.monotonic(), utc()
        return nonce


class Child:
    """Outer process deadline remains effective even if owned asyncio drain hangs."""

    def __init__(self, process, log):
        self.process, self.log, self.forced = process, log, False

    @classmethod
    async def spawn(cls, command, log_path, *, env=None, cwd=None):
        log = Path(log_path).open("xb")
        try:
            process = await asyncio.create_subprocess_exec(
                *map(str, command),
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                env=env,
                cwd=cwd,
            )
        except BaseException:
            log.close()
            raise
        return cls(process, log)

    async def join(self, seconds):
        try:
            async with asyncio.timeout(seconds):
                await self.process.wait()
        except TimeoutError:
            self.forced = True
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                async with asyncio.timeout(2):
                    await self.process.wait()
            except TimeoutError:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                async with asyncio.timeout(5):
                    await self.process.wait()
        finally:
            self.log.close()
        return self.process.returncode


class SDKObserver(AbstractContextManager):
    """Observe the original class object, retaining factory identity and options."""

    def __init__(self, *, client_class=None, domain_transport=None):
        from claude_agent_sdk import ClaudeSDKClient
        from bridge.guarded_transport import GuardedTransport

        self.client_class = client_class or ClaudeSDKClient
        self.domain_transport = domain_transport or (
            lambda value: isinstance(value, GuardedTransport)
        )
        self.records, self.instances, self.originals = [], {}, {}
        self.tasks = {}
        self.processes = {}

    def note(self, instance, operation):
        record = self.instances[id(instance)]
        task = asyncio.current_task()
        self.tasks.setdefault(task, len(self.tasks) + 1)
        record["lifecycle"].append(operation)
        record["task_ids"].append(self.tasks[task])
        return record

    def __enter__(self):
        cls, observer = self.client_class, self
        for name in ("__init__", "connect", "query", "receive_response", "disconnect"):
            self.originals[name] = getattr(cls, name)

        def init(instance, *args, **kwargs):
            observer.originals["__init__"](instance, *args, **kwargs)
            options = kwargs.get("options")
            transport = kwargs.get("transport")
            record = dict(
                client_id=uuid4().hex,
                domain=observer.domain_transport(transport),
                cwd=options.cwd,
                model=options.model,
                permission_mode=options.permission_mode,
                max_turns=options.max_turns,
                max_budget_usd=options.max_budget_usd,
                tools=list(options.tools or []),
                lifecycle=[],
                task_ids=[],
                query_count=0,
                queries=[],
                attempts=[],
                successful_tool_ids=[],
                tool_receipts=[],
                terminals=[],
                provider_session_ids=[],
            )
            observer.instances[id(instance)] = record
            observer.records.append(record)

        async def connect(instance, *args, **kwargs):
            observer.note(instance, "connect")
            result = await observer.originals["connect"](instance, *args, **kwargs)
            transport = getattr(instance, "_transport", None)
            process = getattr(transport, "process", None) or getattr(
                transport, "_process", None
            )
            observer.processes[id(instance)] = process
            return result

        async def query(instance, prompt, *args, **kwargs):
            record = observer.note(instance, "query")
            record["query_count"] += 1
            if record["domain"]:
                command = json.loads(prompt)
                notes = command.get("prior_project_notes", "")
                # Only disposable notes/task are observed. Never options/env or
                # arbitrary SDK payloads. The private note text is not published.
                record["queries"].append(
                    dict(
                        task=command.get("task", ""),
                        notes=notes,
                        notes_sha256=sha(notes.encode()),
                        received_utc=utc(),
                    )
                )
            return await observer.originals["query"](instance, prompt, *args, **kwargs)

        async def receive(instance, *args, **kwargs):
            record = observer.note(instance, "receive")
            async for message in observer.originals["receive_response"](
                instance, *args, **kwargs
            ):
                observer.message(record, message)
                yield message

        async def disconnect(instance, *args, **kwargs):
            observer.note(instance, "disconnect")
            result = await observer.originals["disconnect"](instance, *args, **kwargs)
            process = observer.processes.get(id(instance))
            observer.instances[id(instance)]["returncode"] = (
                process.returncode if process else None
            )
            return result

        for name, method in dict(
            __init__=init,
            connect=connect,
            query=query,
            receive_response=receive,
            disconnect=disconnect,
        ).items():
            setattr(cls, name, method)
        return self

    def __exit__(self, *exc):
        for name, method in self.originals.items():
            setattr(self.client_class, name, method)

    def message(self, record, message):
        from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage
        from claude_agent_sdk.types import ToolUseBlock, ToolResultBlock, UserMessage

        if isinstance(message, SystemMessage) and message.subtype == "init":
            record["inventory"] = message.data.get("tools", [])
            session = message.data.get("session_id")
            if session:
                record["provider_session_ids"].append(session)
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    record["attempts"].append(
                        dict(
                            name=block.name,
                            id=block.id,
                            parent=message.parent_tool_use_id,
                            received_utc=utc(),
                        )
                    )
        if isinstance(message, (AssistantMessage, UserMessage)) and isinstance(
            message.content, list
        ):
            for block in message.content:
                if isinstance(block, ToolResultBlock) and block.is_error is not True:
                    record["successful_tool_ids"].append(block.tool_use_id)
                    content = block.content
                    if isinstance(content, list):
                        content = "\n".join(
                            str(v.get("text", ""))
                            for v in content
                            if isinstance(v, dict)
                        )
                    if isinstance(content, str):
                        for line in content.splitlines():
                            if line.startswith("M12_RECEIPT "):
                                receipt = json.loads(line.removeprefix("M12_RECEIPT "))
                                fields = {
                                    "cwd",
                                    "result",
                                    "nonce",
                                    "sha256",
                                    "written_utc",
                                }
                                require(
                                    isinstance(receipt, dict)
                                    and set(receipt) == fields,
                                    "invalid tool receipt",
                                )
                                record["tool_receipts"].append(receipt)
        if isinstance(message, ResultMessage):
            record["terminals"].append(
                dict(
                    subtype=message.subtype,
                    is_error=message.is_error,
                    reason=message.terminal_reason,
                    cost_usd=message.total_cost_usd,
                    permission_denials=len(message.permission_denials or []),
                    errors=bool(message.errors),
                )
            )


def baseline(root):
    from bridge.workspace import git_without_filters

    names = git_without_filters(root, "ls-files", "-z").split("\0")
    return dict(
        head=git_without_filters(root, "rev-parse", "HEAD"),
        status=git_without_filters(root, "status", "--porcelain=v1", "-z"),
        tracked_sha256={
            name: sha((root / name).read_bytes())
            for name in names
            if name and (root / name).is_file()
        },
    )


def note_snapshot(service):
    snapshot = service.require_memory().load()
    return dict(
        revision=snapshot.revision,
        context=snapshot.as_context(),
        sha256={
            name: sha(getattr(snapshot, name).encode())
            for name in ("todo", "handoff", "progress")
        },
    )


def context_observation(packet):
    """Keep only revisions and execution identity; never persist guidance bodies."""
    facts = json.loads(packet.runtime)
    return dict(
        sources=packet.diagnostics(),
        facts={
            key: facts[key]
            for key in (
                "source_root",
                "agent_id",
                "execution_kind",
                "domain_id",
                "tools",
                "permission_mode",
                "interaction",
                "execution_capacity",
            )
        },
        project_id=facts["project"]["project_id"],
        workspace_id=facts["workspace"]["workspace_id"],
    )


def inspect_service(service, owners, observer):
    snapshot = service.snapshot()
    out = dict(snapshot=snapshot, clients=observer.records, owners=[])
    if snapshot["stage"] == "ready":
        from bridge.workspace import inspect_project
        from bridge.workspace_lease import observe_reservation

        project = inspect_project(Path(snapshot["project_path"]))
        marker = (
            project.common_git_dir
            / "plaza/runs"
            / (sha(service.owner_run_id.encode()) + ".json")
        )
        out.update(
            project=dict(
                project_id=project.project_id,
                project_root=str(project.root),
                common_git_dir=str(project.common_git_dir),
            ),
            workspace=None,
            notes=note_snapshot(service),
            memory_marker=str(marker),
            memory_marker_exists=marker.exists(),
            lease_marker_exists=False,
            reservation=None,
            source=baseline(project.root),
        )
        if service.workspace_snapshot("core")["workspace_id"] is not None:
            work = service.require_workspace("core")
            out.update(
                workspace={
                    key: str(getattr(work, key))
                    for key in (
                        "project_id",
                        "domain_id",
                        "workspace_id",
                        "project_root",
                        "worktree_path",
                        "common_git_dir",
                        "git_dir",
                        "branch",
                        "initial_commit",
                    )
                },
                lease_marker_exists=(work.git_dir / "plaza-unclean.json").exists(),
                reservation=observe_reservation(work),
            )
    for owner in owners:
        transport = owner.transport
        process = transport.process if transport else None
        out["owners"].append(
            dict(
                clean=owner._cleanup.clean,
                worker_done=bool(owner._worker and owner._worker.done()),
                transport_closed=bool(transport and transport.closed),
                hook_tasks=len(owner._hook_tasks._tasks),
                returncode=process.returncode if process else None,
            )
        )
    return out


async def inspect_observation(service, owners, observer):
    """A short memory checkpoint lock is not a failed model task or a retry."""
    from bridge.project_memory import MemoryError

    async with asyncio.timeout(2):
        while True:
            try:
                return inspect_service(service, owners, observer)
            except MemoryError:
                # Only read-only observation is repeated. Permanent damage still
                # fails this bounded deadline; no command/provider is resubmitted.
                await asyncio.sleep(0.025)


async def bridge_child(config_path, control, run_id):
    """Isolated instrumentation; no factory/provider/guard replacement."""
    import websockets
    from bridge.config import load_config
    from bridge.agent_bindings import BindingRegistry
    from bridge.domain_sdk import DomainSDKOwner
    from bridge.log_storage import RunLogWriter
    from bridge.observability import BridgeRecorder
    from bridge.project_service import ProjectService
    from bridge.server import BridgeServer
    import bridge.server as server_module
    import bridge.domain_session as session_module

    control = Path(control)
    config = load_config(Path(config_path))
    selected = read_json(Path(config_path))
    require(
        config.workspace_root_dir == Path(selected["WORKSPACE_ROOT_DIR"])
        and config.domain_dangerously_skip_permissions
        == selected["DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS"]
        and config.install_context_dir == Path(selected["INSTALL_CONTEXT_DIR"])
        and config.project_guidance_file == "PLAZA_AGENTS.md"
        and config.conversation_backend == "claude_code"
        and config.domain_tier == "haiku"
        and config.model_for("haiku") == "claude-haiku-5-5"
        and config.domain_max_turns == 8
        and config.domain_max_budget_usd == 0.35
        and config.conversation_max_output_tokens == 1536
        and config.conversation_timeout_seconds == 65,
        "environment changed disposable project/backend/model/caps",
    )
    service = ProjectService(config, runtime_root=ROOT, owner_run_id=run_id)
    writer = RunLogWriter(config, "M12 live acceptance")
    server = BridgeServer(
        config=config,
        project_service=service,
        bindings=BindingRegistry(
            extras={
                agent: {
                    "execution_kind": "extra",
                    "domain_id": None,
                    "definition": "An independent Plaza visitor. Acknowledge the player briefly. You have no tools.",
                }
                for agent in ("fixture-extra-a", "fixture-extra-b")
            }
        ),
        recorder=BridgeRecorder(config, "M12 live acceptance", writer=writer),
    )
    stop, ready = asyncio.Event(), asyncio.Event()
    owners, listeners, commands, emitted = [], [], [], []
    starts, contexts = [], []
    actual_serve, original_binding = websockets.serve, session_module.DomainSDKOwner

    def listen(handler, host, port, **kwargs):
        listener = actual_serve(handler, "127.0.0.1", 0, **kwargs)
        listeners.append(listener)
        return listener

    def owner(*args, **kwargs):
        require("client_factory" not in kwargs, "live factory override forbidden")
        value = DomainSDKOwner(*args, **kwargs)
        owners.append(value)
        original_execute = value.execute

        async def execute(**kwargs):
            contexts.append(context_observation(kwargs["context_packet"]))
            return await original_execute(**kwargs)

        value.execute = execute
        return value

    original_event, original_dispatch = server._event, server.dispatch

    def event(name, *args, **kwargs):
        original_event(name, *args, **kwargs)
        if name == "bridge_started":
            ready.set()

    async def dispatch(command, *args, **kwargs):
        commands.append(dict(command))
        emit = kwargs.get("emit")
        if emit is not None:

            async def observed(packet):
                emitted.append(dict(packet))
                if (
                    command.get("type") == "activate_domain"
                    and packet.get("state") == "active"
                ):
                    starts.append(
                        dict(
                            request_id=command["request_id"],
                            project_id=packet["project_id"],
                            workspace_id=packet["workspace_id"],
                            domain_id=packet["domain_id"],
                            domain_session_id=packet["domain_session_id"],
                            query_count=sum(
                                c["query_count"]
                                for c in observer.records
                                if c["domain"]
                            ),
                        )
                    )
                await emit(packet)

            kwargs["emit"] = observed
        return await original_dispatch(command, *args, **kwargs)

    server._event, server.dispatch = event, dispatch
    server_module.websockets = SimpleNamespace(serve=listen)
    session_module.DomainSDKOwner = owner
    failure = None
    try:
        with SDKObserver() as observer:
            serving = asyncio.create_task(server.serve(stop_event=stop))
            await asyncio.wait_for(ready.wait(), 10)
            await service._bootstrap_task
            port = listeners[0].server.sockets[0].getsockname()[1]
            write_json(
                control / "ready.json",
                dict(
                    run_id=run_id,
                    pid=os.getpid(),
                    url=f"ws://127.0.0.1:{port}",
                    archive_run_id=writer.run_id,
                    owner_run_id=run_id,
                    state=await inspect_observation(service, owners, observer),
                ),
            )
            sequence = 0
            while not stop.is_set() and not serving.done():
                if (control / "stop").exists():
                    require((control / "stop").read_text() == run_id, "foreign Stop")
                    stop.set()
                    break
                sequence += 1
                state = await inspect_observation(service, owners, observer)
                state.update(
                    run_id=run_id,
                    seq=sequence,
                    commands=commands,
                    emitted=emitted,
                    starts=starts,
                    contexts=contexts,
                )
                write_json(control / "state.json", state)
                await asyncio.sleep(0.025)
            await serving
            final = await inspect_observation(service, owners, observer)
            final.update(
                run_id=run_id,
                archive_run_id=writer.run_id,
                commands=commands,
                emitted=emitted,
            )
            write_json(control / "closed.json", final)
    except BaseException as error:
        failure = error
        write_json(
            control / "child-error.json",
            dict(run_id=run_id, error_type=type(error).__name__),
        )
    finally:
        server_module.websockets = SimpleNamespace(serve=actual_serve)
        session_module.DomainSDKOwner = original_binding
    if failure:
        raise failure


async def wait_file(path, children, seconds=STAGE_SECONDS):
    async with asyncio.timeout(seconds):
        while not path.exists():
            require(
                all(child.process.returncode is None for child in children),
                "child exited before required artifact: " + path.name,
            )
            await asyncio.sleep(0.025)
    return read_json(path)


def bridge_environment():
    environment = dict(os.environ)
    for name in (
        "PLAZA_REQUIRE_GODOT",
        "PLAZA_TEST_BRIDGE_URL",
        "PLAZA_TEST_PROGRESS",
        "PLAZA_M12_CONTROL",
        "PLAZA_M12_RUN_ID",
        "PLAZA_M12_LIVE",
    ):
        environment.pop(name, None)
    return environment


class LiveLifetime:
    def __init__(self, directory, project, scenario, *, permission_mode="dontAsk"):
        require(
            permission_mode in ("dontAsk", "bypassPermissions"),
            "invalid permission mode",
        )
        self.directory, self.project, self.scenario = directory, project, scenario
        self.run_id = uuid4().hex
        self.directory.mkdir()
        self.control = directory / "control"
        self.control.mkdir()
        self.config = directory / "config.json"
        context = directory / "context"
        context.mkdir()
        (context / "WORK_CONTEXT.md").write_text(
            "Disposable M12 acceptance. Follow explicit tasks only.\n"
        )
        write_json(
            self.config,
            dict(
                CONFIG_VERSION=1,
                DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS=permission_mode
                == "bypassPermissions",
                INSTALL_CONTEXT_DIR=str(context),
                PROJECT_GUIDANCE_FILE="PLAZA_AGENTS.md",
                WORKSPACE_ROOT_DIR=str(project),
                LOG_DIR=str(directory / "logs"),
                DOMAIN_TIER="haiku",
                DOMAIN_MAX_TURNS=8,
                DOMAIN_MAX_BUDGET_USD=0.35,
                CONVERSATION_MAX_OUTPUT_TOKENS=1536,
                CONVERSATION_TIMEOUT_SECONDS=65,
            ),
        )
        self.child = None
        self.ready = None
        self.closed = None

    async def start(self):
        self.child = await Child.spawn(
            [
                sys.executable,
                __file__,
                "--child",
                str(self.config),
                "--control",
                str(self.control),
                "--run-id",
                self.run_id,
            ],
            self.directory / "bridge.log",
            env=bridge_environment(),
            cwd=ROOT,
        )
        self.ready = await wait_file(self.control / "ready.json", [self.child], 20)
        require(
            self.ready["run_id"] == self.run_id
            and self.ready["pid"] == self.child.process.pid,
            "foreign bridge ready",
        )
        return self

    def state(self):
        state = read_json(self.control / "state.json")
        require(state["run_id"] == self.run_id, "foreign bridge state")
        return state

    async def stop(self):
        if not self.child:
            return None
        (self.control / "stop").write_text(self.run_id)
        code = await self.child.join(DRAIN_SECONDS)
        closed_path = self.control / "closed.json"
        if not closed_path.exists():
            return dict(
                scenario=self.scenario,
                run_id=self.run_id,
                child_returncode=code,
                forced=self.child.forced,
                closed=False,
            )
        self.closed = read_json(closed_path)
        require(self.closed["run_id"] == self.run_id, "foreign bridge closure")
        manifests = list((self.directory / "logs/runs").glob("*/manifest.json"))
        manifests = [read_json(p) for p in manifests]
        manifests = [
            m for m in manifests if m.get("run_id") == self.ready["archive_run_id"]
        ]
        manifest = manifests[0] if len(manifests) == 1 else {}
        domain_clients = [r for r in self.closed["clients"] if r["domain"]]
        owners = self.closed["owners"]
        for observed, client in zip(owners, domain_clients):
            observed.update(
                lifecycle=client["lifecycle"], task_count=len(set(client["task_ids"]))
            )
        self.cleanup_evidence = dict(
            scenario=self.scenario,
            run_id=self.run_id,
            child_returncode=code,
            forced=self.child.forced,
            closed=manifest.get("status") == "closed",
            ended_at=manifest.get("ended_at"),
            memory_marker_before=getattr(self, "marker_before", False),
            memory_marker_after=self.closed.get("memory_marker_exists"),
            lease_marker_after=self.closed.get("lease_marker_exists"),
            reservation_after=self.closed.get("reservation", {}),
            owners=owners,
            archive_run_id=self.ready["archive_run_id"],
            cli_returncodes=[r.get("returncode") for r in self.closed["clients"]],
        )
        return self.cleanup_evidence


def corroborate(state, receipt):
    payload, stage = receipt["payload"], receipt["stage"]
    command = next(
        (c for c in state["commands"] if c.get("request_id") == payload["request_id"]),
        None,
    )
    packets = [
        p for p in state["emitted"] if p.get("request_id") == payload["request_id"]
    ]
    require(command and packets, "stage lacks independent bridge command/reply")
    expected = dict(
        referral_rendered="project_setup",
        chief_ready="project_setup",
        domain_running="domain_query",
        background_ack="background_domain",
        npc_rendered="query",
        domain_rendered="resume",
        stop_ack="deactivate_domain",
    )
    if stage == "npc_rendered":
        require(
            payload["agent_id"] == "fixture-extra-a",
            "independent explicit extra required",
        )
    if stage == "domain_running":
        require(
            payload["agent_id"] == command.get("agent_id") == "systems-architect"
            and payload["domain_id"] == command.get("domain_id") == "core",
            "working Core representative mismatch",
        )
    if stage in ("referral_rendered", "chief_ready", "npc_rendered"):
        expected_agent = (
            "systems-architect" if stage == "chief_ready" else payload["agent_id"]
        )
        require(
            command.get("type")
            in ((None, "query") if stage == "npc_rendered" else ("project_setup",))
            and command.get("agent_id") == expected_agent,
            "stage NPC command mismatch",
        )
    else:
        require(command.get("type") == expected[stage], "stage command kind mismatch")
    if stage in ("referral_rendered", "chief_ready", "npc_rendered"):
        require(
            any(
                p.get("output") == payload["assistant"]
                and p.get("status") == "ok"
                and (stage == "npc_rendered" or p.get("type") == "project_setup")
                for p in packets
            ),
            "rendered NPC differs from bridge",
        )
    elif stage == "domain_running":
        require(
            any(
                p.get("type") == "domain_accepted"
                and p["domain_session_id"] == payload["domain_session_id"]
                for p in packets
            ),
            "domain acceptance mismatch",
        )
    elif stage in ("background_ack", "stop_ack"):
        require(
            any(
                p.get("type") == "domain_state"
                and p["state"] == payload["state"]
                and p["domain_session_id"] == payload["domain_session_id"]
                for p in packets
            ),
            "control acknowledgment mismatch",
        )
        if stage == "background_ack":
            require(
                any(p.get("execution_state") == "running" for p in packets),
                "background execution no longer running",
            )
    else:
        require(
            any(p.get("type") == "resume_complete" for p in packets),
            "missing replay completion",
        )
        refocus = payload["refocus_request_id"]
        require(
            any(
                c.get("request_id") == refocus and c.get("type") == "refocus_domain"
                for c in state["commands"]
            ),
            "missing refocus command",
        )
        require(
            any(
                p.get("request_id") == refocus
                and p.get("type") == "domain_state"
                and p.get("domain_session_id") == payload["domain_session_id"]
                for p in state["emitted"]
            ),
            "missing refocus acknowledgment",
        )
        terminals = [
            p
            for p in state["emitted"]
            if p.get("type") == "domain_result"
            and p.get("output_id") == payload["output_id"]
        ]
        require(
            terminals
            and all(
                p.get("output") == payload["output"]
                and all(
                    p.get(k) == payload[k]
                    for k in (
                        "project_id",
                        "workspace_id",
                        "domain_id",
                        "domain_session_id",
                    )
                )
                for p in terminals
            ),
            "rendered terminal mismatch",
        )
    return command, packets


def assert_answer_matches(output, expected):
    """Assert meaning without changing the product's preserved terminal bytes."""
    require(
        isinstance(output, str) and len(output.encode()) <= 65536,
        "invalid semantic answer",
    )
    if output == expected:
        return True
    text = output.strip()
    if text.startswith("```"):
        match = re.fullmatch(r"```json\n([\s\S]*)\n```", text)
        require(match is not None and text.count("```") == 2, "invalid answer fence")
        text = match.group(1)
    from bridge.workspace import _decode

    try:
        envelope = _decode(text.encode())
    except (ValueError, RecursionError, UnicodeError):
        raise AcceptanceError(
            "answer is not exact plain text or one complete JSON object"
        ) from None
    require(
        isinstance(envelope.get("answer"), str) and envelope["answer"] == expected,
        "semantic answer mismatch",
    )
    return True


def tool_task(release):
    # This program is text supplied to the real SDK. The harness never executes it.
    program = f"""import os,time,pathlib,json,hashlib,datetime
release=pathlib.Path({str(release)!r})
result=pathlib.Path({RESULT!r})
assert not result.exists()
deadline=time.monotonic()+90
while not release.exists():
    assert time.monotonic()<deadline, "release deadline"
    time.sleep(.1)
nonce=release.read_text()
assert nonce.startswith("m12-")
with result.open("x") as handle: handle.write(nonce)
receipt=dict(cwd=os.getcwd(),result=str(result),nonce=nonce,sha256=hashlib.sha256(result.read_bytes()).hexdigest(),written_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
print("M12_RECEIPT "+json.dumps(receipt))"""
    command = (
        shlex.quote(sys.executable)
        + " -c "
        + shlex.quote("exec(" + repr(program) + ")")
    )
    return (
        "Run this exact bounded Bash command once (timeout 100000 ms); do not create the result by any other tool, do not retry it. It waits for an external supervisor. Then return only one JSON object without Markdown fences or surrounding prose, with answer equal to the nonce from M12_RECEIPT, and memory_delta with summary equal to that exact nonce and next_action 'Read prior notes without rerunning completed work'. Command: "
        + command
    )


class Plain:
    def __init__(self, socket):
        self.socket, self.packets = socket, []

    async def send(self, kind, request, generation=None, **extra):
        command = dict(type=kind, request_id=request, domain_id="core", **extra)
        if generation:
            command["domain_session_id"] = generation
        await self.socket.send(json.dumps(command))

    async def reply(self, request, **expected):
        async with asyncio.timeout(STAGE_SECONDS):
            while True:
                packet = json.loads(await self.socket.recv())
                self.packets.append(packet)
                if packet.get("request_id") == request and all(
                    packet.get(k) == v for k, v in expected.items()
                ):
                    return packet


async def initial(life, report):
    import websockets
    from scripts.m12_stages import StageValidator, STAGES

    validator = StageValidator(life.run_id, "godot")
    control = life.control
    task_path = control / "task.txt"
    release_path = control / "release"
    task_path.write_text(tool_task(release_path))
    env = dict(
        os.environ,
        PLAZA_M12_LIVE="1",
        PLAZA_M12_CONTROL=str(control),
        PLAZA_M12_RUN_ID=life.run_id,
        PLAZA_TEST_BRIDGE_URL=life.ready["url"],
    )
    godot = await Child.spawn(
        [
            godot_binary(),
            "--headless",
            "--path",
            ROOT,
            "tests/godot_domain_integration.tscn",
        ],
        life.directory / "godot.log",
        env=env,
        cwd=ROOT,
    )
    result = report["initial"] = dict(
        checks={},
        query_count=0,
        result_count=0,
        rendered_count=0,
        tool_receipts=[],
        scene_run_id=life.run_id,
    )
    checks = result["checks"]
    gate = work = source_before = None
    try:
        for seq, stage in enumerate(STAGES, 1):
            record = await wait_file(
                control / f"{seq:02d}-{stage}.json", [life.child, godot]
            )
            receipt = validator.accept(record)
            async with asyncio.timeout(5):
                while True:
                    state = life.state()
                    if any(
                        p.get("request_id") == receipt["payload"]["request_id"]
                        for p in state["emitted"]
                    ):
                        break
                    require(
                        life.child.process.returncode is None,
                        "bridge exited before corroboration",
                    )
                    await asyncio.sleep(0.025)
            command, packets = corroborate(state, receipt)
            payload = receipt["payload"]
            if stage == "referral_rendered":
                require(
                    state["snapshot"]["architect_decision"] is None
                    and not (life.project / ".git").exists(),
                    "referral initialized/reviewed project",
                )
                checks["referral_no_review"] = True
            elif stage == "chief_ready":
                snapshot = state["snapshot"]
                require(
                    snapshot["stage"] == "ready"
                    and snapshot["architect_decision"]["approved"] is True,
                    "Chief not approved",
                )
                require(
                    state["workspace"] is None
                    and not any(c["domain"] for c in state["clients"]),
                    "Chief eagerly prepared work",
                )
                from bridge.workspace import git_without_filters

                require(
                    git_without_filters(life.project, "branch", "--show-current")
                    == "main",
                    "seed branch mismatch",
                )
                require(
                    len(
                        list(
                            (
                                Path(state["project"]["common_git_dir"])
                                / "plaza/session-memory"
                            ).glob("*.md")
                        )
                    )
                    == 3,
                    "missing canonical notes",
                )
                checks.update(
                    real_chief_approved=True, main_seed=True, three_notes=True
                )
                source_before = state["source"]
                result.update(
                    source_before=source_before, bootstrap_notes=state["notes"]
                )
                life.marker_before = state["memory_marker_exists"]
                require(life.marker_before, "memory ownership was not attached")
            elif stage == "domain_running":
                work = state["workspace"]
                from bridge.workspace import git_without_filters

                require(
                    work["domain_id"] == "core"
                    and work["initial_commit"] == source_before["head"]
                    and git_without_filters(
                        Path(work["worktree_path"]), "branch", "--show-current"
                    )
                    == work["branch"]
                    and Path(
                        git_without_filters(
                            Path(work["worktree_path"]),
                            "rev-parse",
                            "--absolute-git-dir",
                        )
                    )
                    == Path(work["git_dir"]),
                    "Core worktree Git identity mismatch",
                )
                paths = [
                    life.project.resolve(),
                    ROOT.resolve(),
                    Path(work["worktree_path"]).resolve(),
                    control.resolve(),
                ]
                require(
                    all(
                        a != b and a not in b.parents and b not in a.parents
                        for i, a in enumerate(paths)
                        for b in paths[i + 1 :]
                    ),
                    "overlapping source/runtime/execution/control",
                )
                clients = [c for c in state["clients"] if c["domain"]]
                require(
                    len(clients) == 1 and clients[0]["query_count"] == 1,
                    "expected exactly one SDK tool task",
                )
                require(
                    len(state["starts"]) == 1
                    and state["starts"][0]["query_count"] == 0,
                    "Start submitted a model task",
                )
                result.update(
                    worktree_path=work["worktree_path"],
                    workspace=work,
                    start=state["starts"][0],
                )
                checks["separate_paths"] = True
                gate = NonceGate(release_path, Path(work["worktree_path"]) / RESULT)
                gate.assert_absent()
                checks["absent_before"] = True
            elif stage == "background_ack":
                gate.assert_absent()
                result["background_monotonic"] = receipt["received_monotonic"]
                checks["background_corroborated"] = True
            elif stage == "npc_rendered":
                require(
                    validator.may_release and payload["agent_id"] == "fixture-extra-a",
                    "wrong unrelated NPC/release order",
                )
                gate.assert_absent()
                result["npc_monotonic"] = receipt["received_monotonic"]
                checks["npc_corroborated"] = True
                result["nonce"] = gate.release(
                    background=result["background_monotonic"],
                    npc=result["npc_monotonic"],
                )
                result.update(
                    released_monotonic=gate.released_monotonic,
                    released_utc=gate.released_utc,
                )
            elif stage == "domain_rendered":
                clients = [c for c in state["clients"] if c["domain"]]
                require(len(clients) == 1, "extra SDK owner")
                client = clients[0]
                result.update(
                    query_count=client["query_count"],
                    tool_receipts=client["tool_receipts"],
                    sdk=client,
                    context=state["contexts"][0],
                )
                data = read_result(gate.result_path.parent)
                require(
                    data.decode() == result["nonce"], "result file differs from nonce"
                )
                assert_answer_matches(payload["output"], result["nonce"])
                require(
                    len(client["attempts"]) == 1
                    and client["attempts"][0]["name"] == "Bash"
                    and client["attempts"][0]["id"] in client["successful_tool_ids"],
                    "missing single successful actual SDK Bash action",
                )
                require(
                    len(client["tool_receipts"]) == 1, "missing exact SDK tool receipt"
                )
                tool = client["tool_receipts"][0]
                require(
                    tool["cwd"] == work["worktree_path"] == client["cwd"]
                    and tool["result"] == RESULT
                    and tool["nonce"] == result["nonce"]
                    and tool["sha256"] == sha(data)
                    and tool["written_utc"] > gate.released_utc,
                    "tool CWD/content/timing receipt mismatch",
                )
                checks.update(sdk_only_result=True, tool_cwd=True)
                result.update(
                    result_sha256=sha(data),
                    rendered_count=payload["rendered_unique_results"],
                    output=payload["output"],
                    terminal_identity={
                        k: payload[k]
                        for k in (
                            "project_id",
                            "workspace_id",
                            "domain_id",
                            "domain_session_id",
                            "output_id",
                        )
                    },
                )
                async with websockets.connect(life.ready["url"]) as socket:
                    plain = Plain(socket)
                    await plain.send("domain_status", "plain-status")
                    status = await plain.reply("plain-status", type="domain_state")
                    require(
                        status["domain_session_id"] == payload["domain_session_id"],
                        "plain status generation differs",
                    )
                    await plain.send(
                        "resume",
                        "plain-resume",
                        payload["domain_session_id"],
                        cursor="0",
                    )
                    await plain.reply("plain-resume", type="resume_complete")
                    terminals = [
                        p for p in plain.packets if p.get("type") == "domain_result"
                    ]
                    require(
                        len(terminals) == 1
                        and terminals[0]["output"] == payload["output"]
                        and all(
                            terminals[0][k] == v
                            for k, v in result["terminal_identity"].items()
                        ),
                        "plain output/identity differs",
                    )
                    require(
                        terminals[0].get("memory", {}).get("saved") is True,
                        "terminal memory save failed",
                    )
                    result["result_count"] = len(terminals)
                    checks.update(
                        same_plain_output=True,
                        one_rendered_result=True,
                        memory_saved=True,
                    )
            elif stage == "stop_ack":
                require(
                    state["reservation"] is None
                    and state["lease_marker_exists"] is False,
                    "Stop retained lease",
                )
                require(
                    state["source"] == source_before, "source modified by execution"
                )
                checks.update(
                    stop_inactive=True, lease_released=True, source_unchanged=True
                )
                require(
                    result["nonce"] in state["notes"]["context"]
                    and "Read prior notes without rerunning completed work"
                    in state["notes"]["context"]
                    and "success" in state["notes"]["context"],
                    "memory lacks successful nonce outcome or next action",
                )
                result.update(source_after=state["source"], notes=state["notes"])
            (control / f"ack-{seq}").write_text(life.run_id)
        validator.finish()
        result["stages"] = validator.receipts
        result["wire"] = {k: state[k] for k in ("commands", "emitted")}
        code = await godot.join(15)
        output = (life.directory / "godot.log").read_text()
        require(
            code == 0
            and not godot.forced
            and re.search(
                r"^godot_domain_integration: OK — [1-9][0-9]* checks passed\.$",
                output,
                re.M,
            )
            and "SCRIPT ERROR" not in output
            and "ERROR:" not in output,
            "Godot failed/incomplete",
        )
        result["godot_returncode"] = code
    finally:
        if godot.process.returncode is None:
            await godot.join(0.01)


async def readback(life, report, scenario):
    import websockets

    before = life.ready["state"]
    require(before["snapshot"]["stage"] == "ready", "readback project not ready")
    require(not before["clients"], "automatic SDK invocation on restart")
    life.marker_before = before["memory_marker_exists"]
    a = report["initial"]
    if scenario == "b_isolation":
        require(before["workspace"] is None, "B eagerly provisioned before Start")
    async with websockets.connect(life.ready["url"]) as socket:
        plain = Plain(socket)
        await plain.send("activate_domain", "readback-start")
        active = await plain.reply("readback-start", state="active")
    async with asyncio.timeout(5):
        while True:
            prepared = life.state()
            if prepared.get("starts"):
                break
            await asyncio.sleep(0.025)
    require(
        len(prepared["starts"]) == 1 and prepared["starts"][0]["query_count"] == 0,
        "Start submitted a model task",
    )
    work = prepared["workspace"]
    key = "restart" if scenario == "a_restart" else "isolation"
    record = report[key] = dict(
        checks={"no_automatic_query": True},
        query_count=0,
        tool_count=0,
        workspace=work,
        start=prepared["starts"][0],
        notes_before=before["notes"],
    )
    checks = record["checks"]
    if key == "restart":
        require(
            work == a["workspace"] and before["notes"] == a["notes"],
            "restart workspace/notes changed",
        )
        checks.update(
            fresh_owner=life.run_id != report["lifetimes"][0]["run_id"],
            same_workspace=True,
            same_memory=True,
        )
        task = "Without tools or file changes, read the supplied prior project notes. Return only one JSON object without Markdown fences or surrounding prose, with answer equal to the exact completed M12 nonce beginning m12-. Do not rerun any earlier task."
    else:
        require(
            all(
                work[k] != a["workspace"][k]
                for k in ("project_id", "workspace_id", "common_git_dir")
            ),
            "repository B shares A identity",
        )
        require(
            a["nonce"] not in before["notes"]["context"]
            and "M12 bounded acceptance" not in before["notes"]["context"],
            "A notes leaked into B",
        )
        require(
            len(
                list(
                    (Path(work["common_git_dir"]) / "plaza/session-memory").glob("*.md")
                )
            )
            == 3,
            "B notes missing",
        )
        checks.update(different_identity=True, own_three_notes=True, no_a_notes=True)
        task = "Without tools or file changes, inspect only supplied prior project notes. If there is no completed M12 nonce, return only one JSON object without Markdown fences or surrounding prose, with answer 'isolated'. Do not invent a nonce or rerun work."
    async with websockets.connect(life.ready["url"]) as socket:
        plain = Plain(socket)
        generation = active["domain_session_id"]
        await plain.send(
            "domain_query",
            "readback-run",
            generation,
            agent_id="systems-architect",
            task=task,
        )
        await plain.reply("readback-run", type="domain_accepted")
        terminal = await plain.reply("readback-run", type="domain_result")
        require(
            terminal["status"] == "success"
            and terminal.get("memory", {}).get("saved") is True,
            "readback failed",
        )
        expected = a["nonce"] if key == "restart" else "isolated"
        assert_answer_matches(terminal["output"], expected)
        async with asyncio.timeout(5):
            while True:
                state = life.state()
                if any(
                    p.get("request_id") == "readback-run"
                    and p.get("type") == "domain_result"
                    for p in state["emitted"]
                ):
                    break
                await asyncio.sleep(0.025)
        clients = [c for c in state["clients"] if c["domain"]]
        require(len(clients) == 1, "unexpected readback clients")
        client = clients[0]
        # The checkpoint above includes this exact terminal; earlier snapshots
        # may precede even a very fast offline or cached provider query.
        require(
            client["query_count"] == 1 and not client["attempts"],
            "readback used tools or repeated query",
        )
        query = client["queries"][0]
        require(a["nonce"] not in query["task"], "nonce supplied in readback task")
        if key == "restart":
            require(
                a["nonce"] in query["notes"], "A notes not loaded into fresh invocation"
            )
            checks.update(
                notes_in_query=True,
                nonce_not_in_task=True,
                notes_readback=True,
                result_unchanged=sha(read_result(Path(a["worktree_path"])))
                == a["result_sha256"],
            )
        else:
            require(a["nonce"] not in query["notes"], "A nonce in B invocation")
            checks.update(no_a_nonce_in_query=True, isolated_readback=True)
        record.update(
            query_count=client["query_count"],
            tool_count=len(client["attempts"]),
            sdk=client,
            context=state["contexts"][0],
            output=terminal["output"],
        )
        await plain.send("deactivate_domain", "readback-stop", generation)
        require(
            (await plain.reply("readback-stop", state="inactive"))["state"]
            == "inactive",
            "readback Stop not confirmed",
        )
        checks["stop_inactive"] = True


def _proof_fields(value, fields, label):
    require(isinstance(value, dict) and set(fields) <= value.keys(), label + " fields")
    return value


def _proof_text(value, label, limit=128, empty=False, nul=False):
    require(
        isinstance(value, str)
        and (empty or bool(value))
        and len(value.encode()) <= limit
        and (nul or "\x00" not in value),
        label,
    )
    return value


def _proof_integer(value, label, minimum=0):
    require(type(value) is int and minimum <= value <= 2**63 - 1, label)
    return value


def _proof_number(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, label)
    return value


def _proof_hash(value, label, length=64):
    require(
        isinstance(value, str)
        and re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is not None,
        label,
    )
    return value


def _proof_utc(value):
    _proof_text(value, "UTC timestamp")
    parsed = datetime.fromisoformat(value)
    require(
        parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0,
        "timestamp must be UTC",
    )
    return parsed


def _proof_path(value):
    _proof_text(value, "absolute canonical path", 4096)
    path = Path(value)
    require(
        path.is_absolute() and str(path) == value and ".." not in path.parts,
        "absolute canonical path",
    )
    return path


def _proof_bounded(record):
    """Bound traversal before interpreting nested, possibly malformed JSON data."""
    stack, nodes, size = [(record, 0)], 0, 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        require(nodes <= 100000 and depth <= 20, "proof structural bound")
        if isinstance(item, dict):
            require(
                len(item) <= 10000 and all(isinstance(k, str) for k in item),
                "proof object bound",
            )
            stack.extend((v, depth + 1) for v in item.values())
            stack.extend((k, depth + 1) for k in item)
        elif isinstance(item, list):
            require(len(item) <= 10000, "proof list bound")
            stack.extend((v, depth + 1) for v in item)
        elif isinstance(item, str):
            count = len(item.encode())
            require(count <= 1024 * 1024, "proof string bound")
            size += count
        else:
            require(
                item is None or type(item) in (int, float, bool), "proof JSON scalar"
            )
            if type(item) is float:
                require(math.isfinite(item), "proof finite number")
        require(size <= 4 * 1024 * 1024, "proof byte bound")


def _proof_hashes(value, *, names=None):
    require(isinstance(value, dict) and len(value) <= 10000, "hash mapping")
    if names is not None:
        require(set(value) == set(names), "hash inventory")
    for name, digest in value.items():
        _proof_text(name, "hash name", 4096)
        path = Path(name)
        require(
            not path.is_absolute() and ".." not in path.parts and str(path) == name,
            "relative hash path",
        )
        _proof_hash(digest, "SHA-256")
    return value


def _proof_baseline(value):
    _proof_fields(value, ("head", "status", "tracked_sha256"), "baseline")
    _proof_hash(value["head"], "baseline HEAD", 40)
    _proof_text(value["status"], "baseline status", 1024 * 1024, empty=True, nul=True)
    _proof_hashes(value["tracked_sha256"])
    return value


def _proof_notes(value):
    _proof_fields(value, ("revision", "sha256"), "notes")
    _proof_integer(value["revision"], "memory revision", 1)
    _proof_hashes(value["sha256"], names=("todo", "handoff", "progress"))
    if "context" in value:
        _proof_text(value["context"], "private notes context", 131072)
    return {k: value[k] for k in ("revision", "sha256")}


def _proof_workspace(value):
    _proof_fields(
        value,
        (
            "project_id",
            "workspace_id",
            "domain_id",
            "project_root",
            "worktree_path",
            "common_git_dir",
            "git_dir",
            "branch",
            "initial_commit",
        ),
        "workspace",
    )
    for key in ("project_id", "workspace_id", "branch"):
        _proof_text(value[key], "workspace " + key)
    _proof_hash(value["initial_commit"], "initial commit", 40)
    paths = {
        key: _proof_path(value[key])
        for key in ("project_root", "worktree_path", "common_git_dir", "git_dir")
    }
    root, execution = paths["project_root"], paths["worktree_path"]
    require(
        root != execution
        and root not in execution.parents
        and execution not in root.parents,
        "source/execution disjoint",
    )
    require(
        execution.name == "execution"
        and execution.parent.name == value["domain_id"] == "core"
        and execution.parent.parent.parent == root.parent / ".plaza-worktrees"
        and execution.parent.parent.name.endswith("-" + value["project_id"]),
        "sibling execution location",
    )
    require(
        paths["common_git_dir"] == root / ".git"
        and paths["git_dir"].parent == paths["common_git_dir"] / "worktrees"
        and re.fullmatch(r"execution[0-9]*", paths["git_dir"].name) is not None,
        "workspace Git locations",
    )
    require(
        value["branch"] == "plaza/workspace-" + value["project_id"] + "-core",
        "execution branch binding",
    )
    return value


def _proof_cleanup(lifetimes, *, complete=False, started=None, ended=None):
    require(
        isinstance(lifetimes, list) and 1 <= len(lifetimes) <= 3, "bridge lifetimes"
    )
    if complete:
        require(
            len(lifetimes) == 3
            and [r.get("scenario") for r in lifetimes]
            == ["a_initial", "a_restart", "b_isolation"],
            "lifetime scenarios",
        )
    run_ids, archive_ids, previous = set(), set(), started
    for item in lifetimes:
        _proof_fields(
            item,
            (
                "scenario",
                "run_id",
                "archive_run_id",
                "child_returncode",
                "forced",
                "closed",
                "ended_at",
                "memory_marker_before",
                "memory_marker_after",
                "lease_marker_after",
                "reservation_after",
                "owners",
                "cli_returncodes",
            ),
            "lifetime",
        )
        require(
            item["scenario"] in ("a_initial", "a_restart", "b_isolation"),
            "lifetime scenario",
        )
        for key, seen in (("run_id", run_ids), ("archive_run_id", archive_ids)):
            _proof_text(item[key], "lifetime " + key)
            require(item[key] not in seen, "fresh lifetime identity")
            seen.add(item[key])
        require(
            type(item["child_returncode"]) is int
            and item["child_returncode"] == 0
            and item["forced"] is False,
            "nonzero/forced bridge child",
        )
        finished = _proof_utc(item["ended_at"])
        require(
            item["closed"] is True
            and (previous is None or finished > previous)
            and (ended is None or finished <= ended),
            "closed manifest ordering",
        )
        previous = finished
        require(
            item["memory_marker_before"] is True
            and item["memory_marker_after"] is False
            and item["lease_marker_after"] is False
            and item["reservation_after"] is None,
            "ownership cleanup",
        )
        codes = item["cli_returncodes"]
        require(
            isinstance(codes, list)
            and len(codes) == (3 if item["scenario"] == "a_initial" else 1)
            and all(type(c) is int and c == 0 for c in codes),
            "nonzero/missing CLI child",
        )
        require(
            isinstance(item["owners"], list) and len(item["owners"]) == 1,
            "one actual owner",
        )
        owner = _proof_fields(
            item["owners"][0],
            (
                "clean",
                "worker_done",
                "transport_closed",
                "hook_tasks",
                "returncode",
                "task_count",
                "lifecycle",
            ),
            "owner cleanup",
        )
        require(
            all(owner[k] is True for k in ("clean", "worker_done", "transport_closed")),
            "SDK cleanup flags",
        )
        for key, expected in (("hook_tasks", 0), ("returncode", 0), ("task_count", 1)):
            require(
                type(owner[key]) is int and owner[key] == expected, "SDK cleanup " + key
            )
        require(
            owner["lifecycle"] == ["connect", "query", "receive", "disconnect"],
            "final SDK lifecycle",
        )


def _proof_admission(section, permission_mode):
    work = section["workspace"]
    start = _proof_fields(
        section.get("start"),
        (
            "request_id",
            "project_id",
            "workspace_id",
            "domain_id",
            "domain_session_id",
            "query_count",
        ),
        "explicit Start",
    )
    for key in ("request_id", "domain_session_id"):
        _proof_text(start[key], "Start " + key)
    require(
        type(start["query_count"]) is int and start["query_count"] == 0,
        "Start must query zero models",
    )
    require(
        all(start[k] == work[k] for k in ("project_id", "workspace_id", "domain_id")),
        "Start workspace identity",
    )
    context = _proof_fields(
        section.get("context"),
        ("sources", "facts", "project_id", "workspace_id"),
        "current context",
    )
    require(
        all(context[k] == work[k] for k in ("project_id", "workspace_id")),
        "context workspace identity",
    )
    require(
        context["facts"]
        == dict(
            source_root=work["project_root"],
            agent_id="systems-architect",
            execution_kind="domain",
            domain_id="core",
            tools=["Read", "Edit", "Bash"],
            permission_mode=permission_mode,
            interaction="explicit_run",
            execution_capacity=1,
        ),
        "context execution facts",
    )
    sources = context["sources"]
    require(isinstance(sources, list) and len(sources) == 6, "context sources")
    scopes = (
        "shipped",
        "installation",
        "shipped",
        "installation",
        "project",
        "runtime",
    )
    names = (
        "GAME_CONTEXT.md",
        "GAME_CONTEXT.md",
        "WORK_CONTEXT.md",
        "WORK_CONTEXT.md",
        "PLAZA_AGENTS.md",
        "bridge-runtime",
    )
    require(
        len({source.get("identity") for source in sources}) == 6,
        "distinct context identities",
    )
    for index, (source, scope, name) in enumerate(zip(sources, scopes, names)):
        require(
            isinstance(source, dict)
            and set(source) == {"identity", "scope", "revision"},
            "bounded context diagnostic",
        )
        require(source["scope"] == scope, "context source scope")
        _proof_text(source["identity"], "context identity", 4096)
        require(Path(source["identity"]).name == name, "context source name")
        if index == 4:
            require(
                source["identity"] == work["project_root"] + "/PLAZA_AGENTS.md",
                "project guidance source",
            )
        if index == 5:
            require(source["identity"] == "bridge-runtime", "runtime source")
        if index != 1 or source["revision"] is not None:
            _proof_hash(source["revision"], "context revision")


def _proof_sdk(value, workspace, *, initial, started, ended):
    _proof_fields(
        value,
        (
            "client_id",
            "domain",
            "cwd",
            "model",
            "permission_mode",
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
        ),
        "SDK observation",
    )
    _proof_text(value["client_id"], "SDK client identity")
    require(
        value["domain"] is True and value["cwd"] == workspace["worktree_path"],
        "SDK workspace binding",
    )
    require(
        value["model"] == "claude-haiku-5-5"
        and type(value["max_turns"]) is int
        and value["max_turns"] == 8
        and type(value["max_budget_usd"]) in (int, float)
        and value["max_budget_usd"] == 0.35,
        "SDK configured model/caps",
    )
    require(
        value["tools"] == ["Read", "Edit", "Bash"]
        and isinstance(value["inventory"], list)
        and sorted(value["inventory"]) == ["Bash", "Edit", "Read"],
        "SDK tool inventory",
    )
    require(
        type(value["query_count"]) is int and value["query_count"] == 1,
        "SDK query count",
    )
    # These snapshots precede Stop. They do not replace the final owner/CLI proof.
    lifecycle = value["lifecycle"]
    require(
        lifecycle
        in (
            ["connect", "query", "receive"],
            ["connect", "query", "receive", "disconnect"],
        ),
        "pre-Stop SDK lifecycle",
    )
    tasks = value["task_ids"]
    require(
        isinstance(tasks, list)
        and len(tasks) == len(lifecycle)
        and all(type(t) is int and t > 0 for t in tasks)
        and len(set(tasks)) == 1,
        "SDK one-task ownership",
    )
    if "returncode" in value:
        require(
            value["returncode"] is None
            or type(value["returncode"]) is int
            and value["returncode"] == 0,
            "observed SDK exit",
        )
    sessions = value["provider_session_ids"]
    require(
        isinstance(sessions, list)
        and 1 <= len(sessions) <= 4
        and len(set(sessions)) == len(sessions),
        "provider session identities",
    )
    for session in sessions:
        _proof_text(session, "provider session ID")
    for key in ("attempts", "successful_tool_ids", "tool_receipts", "terminals"):
        require(
            isinstance(value[key], list) and len(value[key]) <= 1, "bounded SDK " + key
        )
    require(
        len(value["attempts"]) == int(initial)
        and len(value["successful_tool_ids"]) == int(initial)
        and len(value["tool_receipts"]) == int(initial),
        "SDK tool execution count",
    )
    if initial:
        attempt = _proof_fields(
            value["attempts"][0],
            ("name", "id", "parent", "received_utc"),
            "SDK tool attempt",
        )
        _proof_text(attempt["id"], "tool ID")
        require(
            attempt["name"] == "Bash"
            and attempt["parent"] is None
            and value["successful_tool_ids"] == [attempt["id"]],
            "successful sole SDK Bash identity",
        )
        require(
            started <= _proof_utc(attempt["received_utc"]) <= ended,
            "tool observation UTC",
        )
        require(len(value["terminals"]) == 1, "initial SDK terminal")
    for terminal in value["terminals"]:
        _proof_fields(
            terminal,
            (
                "subtype",
                "is_error",
                "reason",
                "cost_usd",
                "permission_denials",
                "errors",
            ),
            "SDK terminal",
        )
        require(
            terminal["subtype"] == "success"
            and terminal["is_error"] is False
            and terminal["reason"] in (None, "completed")
            and terminal["errors"] is False
            and type(terminal["permission_denials"]) is int
            and terminal["permission_denials"] == 0,
            "successful SDK terminal",
        )
        if terminal["cost_usd"] is not None:
            _proof_number(terminal["cost_usd"], "terminal cost")
    if "queries" in value:
        require(
            isinstance(value["queries"], list) and len(value["queries"]) == 1,
            "private SDK query count",
        )
        query = _proof_fields(
            value["queries"][0],
            ("task", "notes", "notes_sha256", "received_utc"),
            "private SDK query",
        )
        _proof_text(query["task"], "private query task", 65536)
        _proof_text(query["notes"], "private query notes", 131072, empty=True)
        require(
            query["notes_sha256"] == sha(query["notes"].encode())
            and started <= _proof_utc(query["received_utc"]) <= ended,
            "private query hash/UTC",
        )
    return value


def _proof_wire(value):
    _proof_fields(value, ("commands", "emitted"), "wire")
    for name in ("commands", "emitted"):
        require(
            isinstance(value[name], list) and 1 <= len(value[name]) <= 256,
            "wire packet bound",
        )
        for packet in value[name]:
            _proof_fields(packet, ("request_id",), "wire packet")
            _proof_text(packet["request_id"], "wire request ID")
            for key in (
                "type",
                "agent_id",
                "domain_id",
                "domain_session_id",
                "output_id",
            ):
                if key in packet:
                    _proof_text(packet[key], "wire " + key)
            for key in ("project_id", "workspace_id"):
                if packet.get(key) is not None:
                    _proof_text(packet[key], "wire " + key)
            if "output" in packet:
                _proof_text(packet["output"], "wire output", 262144, empty=True)
    return value


def _proof_plain_replay(wire, stages, identity):
    """Require the runner's separate status/resume exchange and full replay."""

    def one(packets, request_id, label):
        matches = [
            (index, packet)
            for index, packet in enumerate(packets)
            if packet["request_id"] == request_id
        ]
        require(len(matches) == 1, "single plain replay " + label)
        return matches[0]

    commands, packets = wire["commands"], wire["emitted"]
    status_at, status = one(commands, "plain-status", "status command")
    resume_at, resume = one(commands, "plain-resume", "resume command")
    run_id = next(s for s in stages if s["stage"] == "domain_running")["payload"][
        "request_id"
    ]
    run_at, _ = one(commands, run_id, "original Run command")
    scene_resume = next(s for s in stages if s["stage"] == "domain_rendered")[
        "payload"
    ]["request_id"]
    scene_at, _ = one(commands, scene_resume, "scene resume command")
    stop_id = next(s for s in stages if s["stage"] == "stop_ack")["payload"][
        "request_id"
    ]
    stop_at, _ = one(commands, stop_id, "Stop command")
    require(
        run_at < scene_at < status_at < resume_at < stop_at,
        "independent plain command ordering",
    )
    require(
        status.get("type") == "domain_status"
        and resume.get("type") == "resume"
        and resume.get("domain_session_id") == identity["domain_session_id"],
        "independent plain command kind/generation",
    )
    for command in (status, resume):
        require(
            command.get("domain_id") == identity["domain_id"]
            and all(
                key not in command or command[key] == identity[key]
                for key in ("project_id", "workspace_id", "domain_session_id")
            ),
            "independent plain command identity",
        )
    status_reply_at, status_reply = one(packets, "plain-status", "status reply")
    complete_at, complete = one(packets, "plain-resume", "replay completion")
    for packet, kind in ((status_reply, "domain_state"), (complete, "resume_complete")):
        require(
            packet.get("type") == kind
            and all(
                packet.get(key) == identity[key]
                for key in (
                    "project_id",
                    "workspace_id",
                    "domain_id",
                    "domain_session_id",
                )
            )
            and packet.get("state") == "active"
            and packet.get("execution_state") == "idle",
            "independent plain reply kind/identity/state",
        )
    terminals = [
        (index, packet)
        for index, packet in enumerate(packets)
        if packet.get("type") == "domain_result"
    ]
    require(len(terminals) == 2, "original and independent replay terminal")
    (original_at, original), (replayed_at, replayed) = terminals
    # Replay preserves the original Run request ID, including the saved memory.
    require(
        original["request_id"] == run_id and replayed == original,
        "exact original/replayed terminal identity/output/memory",
    )
    scene_complete_at, _ = one(packets, scene_resume, "scene replay completion")
    stop_reply_at, _ = one(packets, stop_id, "Stop reply")
    require(
        original_at
        < scene_complete_at
        < status_reply_at
        < replayed_at
        < complete_at
        < stop_reply_at,
        "complete independent plain replay ordering",
    )


def _validate_proof(record):
    from scripts.m12_stages import StageValidator

    _proof_fields(
        record,
        (
            "schema_version",
            "run_id",
            "completed",
            "errors",
            "started_utc",
            "ended_utc",
            "auth_mode",
            "permission_mode",
            "desktop_accepted",
            "instrumentation",
            "versions",
            "binding",
            "caps",
            "initial",
            "restart",
            "isolation",
            "lifetimes",
        ),
        "evidence",
    )
    require(
        type(record["schema_version"]) is int
        and record["schema_version"] == 1
        and record["completed"] is True
        and record["errors"] == [],
        "incomplete/error evidence",
    )
    require(record.get("accepted", True) is True, "report is not accepted")
    _proof_text(record["run_id"], "supervisor identity")
    require(
        record["permission_mode"] in ("dontAsk", "bypassPermissions")
        and record["auth_mode"] in ("api_key", "native_cli")
        and record["desktop_accepted"] is False
        and record["instrumentation"] == INSTRUMENTATION,
        "auth/platform/instrumentation disclosure",
    )
    started, ended = _proof_utc(record["started_utc"]), _proof_utc(record["ended_utc"])
    require(ended > started, "run UTC ordering")
    _proof_cleanup(record["lifetimes"], complete=True, started=started, ended=ended)
    versions = _proof_fields(
        record["versions"],
        ("sdk", "anyio", "cli", "godot", "python", "platform", "cli_sha256"),
        "versions",
    )
    require(
        versions["sdk"] == "0.2.136"
        and versions["anyio"] == "4.14.2"
        and versions["cli"] == "2.1.228 (Claude Code)",
        "pinned dependency versions",
    )
    for key in ("godot", "python", "platform"):
        _proof_text(versions[key], "version " + key)
    _proof_hash(versions["cli_sha256"], "CLI binary SHA-256")
    expected_caps = dict(
        domain_max_turns=8,
        domain_max_budget_usd=0.35,
        max_domain_queries=3,
        npc_max_turns=1,
        npc_deadline_seconds=65,
        automatic_retries=0,
    )
    require(
        record["caps"] == expected_caps
        and all(type(record["caps"][k]) is type(v) for k, v in expected_caps.items()),
        "declared caps",
    )
    binding = _proof_fields(
        record["binding"],
        ("commit", "source_sha256", "runtime_before", "runtime_after"),
        "source binding",
    )
    _proof_hash(binding["commit"], "source commit", 40)
    before, after = _proof_baseline(binding["runtime_before"]), _proof_baseline(
        binding["runtime_after"]
    )
    require(
        before == after and before["head"] == binding["commit"],
        "unchanged runtime HEAD/status/hashes",
    )
    names = LIVE_SOURCES
    _proof_hashes(binding["source_sha256"], names=names)
    require(
        all(
            before["tracked_sha256"].get(name) == binding["source_sha256"][name]
            for name in names
        ),
        "source fingerprints match recorded runtime",
    )
    sections, clients, sessions = [], set(), set()
    for name, checks in (
        ("initial", INITIAL_CHECKS),
        ("restart", RESTART_CHECKS),
        ("isolation", ISOLATION_CHECKS),
    ):
        section = _proof_fields(
            record[name], ("checks", "query_count", "output", "workspace", "sdk"), name
        )
        require(
            isinstance(section["checks"], dict)
            and set(section["checks"]) == set(checks)
            and all(v is True for v in section["checks"].values()),
            name + " checks",
        )
        require(
            type(section["query_count"]) is int and section["query_count"] == 1,
            name + " query count",
        )
        work = _proof_workspace(section["workspace"])
        _proof_admission(section, record["permission_mode"])
        sdk = _proof_sdk(
            section["sdk"],
            work,
            initial=name == "initial",
            started=started,
            ended=ended,
        )
        require(
            sdk["client_id"] not in clients
            and not (set(sdk["provider_session_ids"]) & sessions),
            "fresh SDK invocations",
        )
        require(
            sdk["permission_mode"] == record["permission_mode"],
            "SDK permission mode binding",
        )
        clients.add(sdk["client_id"])
        sessions.update(sdk["provider_session_ids"])
        _proof_text(section["output"], name + " output", 65536)
        if name != "initial":
            _proof_fields(
                section,
                ("tool_count", "notes_before", "notes_after"),
                name + " readback",
            )
            require(
                type(section["tool_count"]) is int and section["tool_count"] == 0,
                "readback tool count",
            )
            old, new = _proof_notes(section["notes_before"]), _proof_notes(
                section["notes_after"]
            )
            require(
                new["revision"] > old["revision"], "readback memory revision ordering"
            )
        sections.append(section)
    initial, restart, isolated = sections
    _proof_fields(
        initial,
        (
            "scene_run_id",
            "result_count",
            "rendered_count",
            "godot_returncode",
            "nonce",
            "result_sha256",
            "worktree_path",
            "terminal_identity",
            "source_before",
            "source_after",
            "bootstrap_notes",
            "notes",
            "stages",
            "wire",
            "tool_receipts",
            "released_monotonic",
            "released_utc",
            "background_monotonic",
            "npc_monotonic",
        ),
        "initial",
    )
    require(
        type(initial["godot_returncode"]) is int and initial["godot_returncode"] == 0,
        "Godot exit 0",
    )
    require(
        all(
            type(initial[k]) is int and initial[k] == 1
            for k in ("result_count", "rendered_count")
        ),
        "one produced/rendered result",
    )
    nonce = _proof_text(initial["nonce"], "nonce")
    require(
        re.fullmatch(r"m12-[0-9a-f]{32}", nonce) is not None
        and sha(nonce.encode()) == initial["result_sha256"],
        "exact nonce content SHA-256",
    )
    _proof_hash(initial["result_sha256"], "result SHA-256")
    require(
        initial["worktree_path"] == initial["workspace"]["worktree_path"]
        and restart["workspace"] == initial["workspace"],
        "reused execution workspace",
    )
    require(
        all(
            isolated["workspace"][k] != initial["workspace"][k]
            for k in (
                "project_id",
                "workspace_id",
                "project_root",
                "worktree_path",
                "common_git_dir",
                "git_dir",
            )
        ),
        "independent repository identity",
    )
    source_before, source_after = _proof_baseline(
        initial["source_before"]
    ), _proof_baseline(initial["source_after"])
    require(
        source_before == source_after
        and source_before["head"] == initial["workspace"]["initial_commit"],
        "post-bootstrap source unchanged",
    )
    bootstrap, final_notes = _proof_notes(initial["bootstrap_notes"]), _proof_notes(
        initial["notes"]
    )
    require(
        final_notes["revision"] > bootstrap["revision"]
        and _proof_notes(restart["notes_before"]) == final_notes,
        "restart uses final initial notes",
    )
    require(
        _proof_notes(isolated["notes_before"])["sha256"]
        not in (final_notes["sha256"], restart["notes_after"]["sha256"]),
        "independent B notes",
    )
    for section, expected in (
        (initial, nonce),
        (restart, nonce),
        (isolated, "isolated"),
    ):
        assert_answer_matches(section["output"], expected)
        if "queries" in section["sdk"]:
            query = section["sdk"]["queries"][0]
            require(nonce not in query["task"], "nonce excluded from submitted task")
            require(
                (nonce in query["notes"]) is (section is restart),
                "private prior-notes nonce isolation",
            )
    stages, wire = initial["stages"], _proof_wire(initial["wire"])
    require(
        isinstance(stages, list)
        and len(stages) == 7
        and initial["scene_run_id"] == record["lifetimes"][0]["run_id"],
        "complete bound scene recipe",
    )
    validator = StageValidator(initial["scene_run_id"], "godot")
    previous_mono, previous_utc = -1, started
    for index, stage in enumerate(stages, 1):
        _proof_fields(
            stage,
            ("receipt_seq", "received_monotonic", "received_utc"),
            "stage receipt",
        )
        mono, stamp = _proof_number(
            stage["received_monotonic"], "receipt monotonic"
        ), _proof_utc(stage["received_utc"])
        require(
            type(stage["receipt_seq"]) is int
            and stage["receipt_seq"] == index
            and mono > previous_mono
            and previous_utc <= stamp <= ended,
            "stage receipt ordering",
        )
        previous_mono, previous_utc = mono, stamp
        validator.accept(
            {
                k: stage[k]
                for k in (
                    "schema_version",
                    "run_id",
                    "scenario",
                    "producer",
                    "seq",
                    "stage",
                    "payload",
                )
            }
        )
        corroborate(wire, stage)
    validator.finish()
    require(
        all(
            validator.binding[k] == initial["workspace"][k]
            for k in ("project_id", "workspace_id")
        ),
        "scene workspace identity",
    )
    start = initial["start"]
    starts = [c for c in wire["commands"] if c.get("type") == "activate_domain"]
    require(
        len(starts) == 1
        and starts[0]["request_id"] == start["request_id"]
        and starts[0].get("domain_id") == "core",
        "explicit Start command",
    )
    running = next(s for s in stages if s["stage"] == "domain_running")["payload"]
    require(
        start["domain_session_id"] == running["domain_session_id"],
        "Start/Run generation",
    )
    require(
        any(
            p.get("request_id") == start["request_id"]
            and p.get("type") == "domain_state"
            and p.get("state") == "active"
            and p.get("execution_state") == "idle"
            and all(
                p.get(k) == start[k]
                for k in (
                    "project_id",
                    "workspace_id",
                    "domain_id",
                    "domain_session_id",
                )
            )
            for p in wire["emitted"]
        ),
        "Start idle acknowledgment",
    )
    require(
        wire["commands"].index(starts[0])
        < next(
            i
            for i, c in enumerate(wire["commands"])
            if c.get("request_id") == running["request_id"]
        ),
        "Start before Run",
    )
    rendered = next(s for s in stages if s["stage"] == "domain_rendered")["payload"]
    identity = _proof_fields(
        initial["terminal_identity"],
        ("project_id", "workspace_id", "domain_id", "domain_session_id", "output_id"),
        "terminal identity",
    )
    require(
        identity == {k: rendered[k] for k in identity}
        and rendered["output"] == initial["output"],
        "recorded/rendered terminal parity",
    )
    require(
        rendered["rendered_text"].count(
            "[%s · systems-architect · output %s ·"
            % (identity["domain_session_id"], identity["output_id"])
        )
        == 1,
        "one actual rendered header",
    )
    terminals = [p for p in wire["emitted"] if p.get("type") == "domain_result"]
    require(bool(terminals), "recorded terminal evidence")
    for packet in terminals:
        require(
            all(packet.get(k) == v for k, v in identity.items())
            and packet.get("output") == initial["output"]
            and packet.get("status") == "success",
            "raw terminal/identity parity",
        )
        saved = _proof_fields(
            packet.get("memory"), ("saved", "revision", "error_type"), "terminal memory"
        )
        require(
            saved["saved"] is True
            and saved["error_type"] is None
            and bootstrap["revision"]
            < _proof_integer(saved["revision"], "saved revision", 1)
            < final_notes["revision"],
            "saved terminal memory revision",
        )
    _proof_plain_replay(wire, stages, identity)
    for field in ("background_monotonic", "npc_monotonic"):
        _proof_number(initial[field], "causal receipt monotonic")
    require(
        initial["background_monotonic"]
        == next(s for s in stages if s["stage"] == "background_ack")[
            "received_monotonic"
        ]
        and initial["npc_monotonic"]
        == next(s for s in stages if s["stage"] == "npc_rendered")[
            "received_monotonic"
        ],
        "causal stage receipt binding",
    )
    released_mono = _proof_number(initial["released_monotonic"], "release monotonic")
    released_utc = _proof_utc(initial["released_utc"])
    require(
        initial["npc_monotonic"]
        < released_mono
        < next(s for s in stages if s["stage"] == "domain_rendered")[
            "received_monotonic"
        ]
        and _proof_utc(
            next(s for s in stages if s["stage"] == "npc_rendered")["received_utc"]
        )
        <= released_utc,
        "causal release order",
    )
    require(
        isinstance(initial["tool_receipts"], list)
        and len(initial["tool_receipts"]) == 1
        and initial["tool_receipts"] == initial["sdk"]["tool_receipts"],
        "SDK tool receipt parity",
    )
    tool = _proof_fields(
        initial["tool_receipts"][0],
        ("cwd", "result", "nonce", "sha256", "written_utc"),
        "tool receipt",
    )
    require(
        tool["cwd"] == initial["worktree_path"]
        and tool["result"] == RESULT
        and tool["nonce"] == nonce
        and tool["sha256"] == initial["result_sha256"],
        "tool CWD/content binding",
    )
    require(
        released_utc
        < _proof_utc(tool["written_utc"])
        <= _proof_utc(
            next(s for s in stages if s["stage"] == "domain_rendered")["received_utc"]
        )
        and _proof_utc(initial["sdk"]["attempts"][0]["received_utc"])
        <= _proof_utc(tool["written_utc"])
        and _proof_utc(
            next(s for s in stages if s["stage"] == "stop_ack")["received_utc"]
        )
        < _proof_utc(record["lifetimes"][0]["ended_at"]),
        "tool attempt/write/release/Stop UTC ordering",
    )


def validate_evidence(record):
    """Validate complete bounded observations, including historical source binding."""
    try:
        _proof_bounded(record)
        _validate_proof(record)
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        OverflowError,
        RecursionError,
    ) as error:
        return [
            (
                str(error)
                if isinstance(error, AcceptanceError)
                else "malformed evidence proof"
            )
        ]
    return []


def sanitize_evidence(record):
    """Explicit recursive allowlists; arbitrary options/env/prompts never escape."""
    top = (
        "schema_version",
        "run_id",
        "completed",
        "errors",
        "accepted",
        "started_utc",
        "ended_utc",
        "auth_mode",
        "permission_mode",
        "desktop_accepted",
        "instrumentation",
        "versions",
        "binding",
        "artifacts",
        "limits",
        "cost_category",
        "caps",
    )
    result = {k: record[k] for k in top if k in record}
    # These nested structures are built from local schema primitives, not SDK
    # options or arbitrary provider dictionaries.
    for section in ("initial", "restart", "isolation"):
        data = record.get(section)
        if isinstance(data, dict):
            keys = (
                "checks",
                "query_count",
                "result_count",
                "rendered_count",
                "tool_count",
                "tool_receipts",
                "nonce",
                "result_sha256",
                "worktree_path",
                "scene_run_id",
                "released_monotonic",
                "released_utc",
                "background_monotonic",
                "npc_monotonic",
                "output",
                "terminal_identity",
                "godot_returncode",
                "workspace",
                "start",
                "context",
                "source_before",
                "source_after",
            )
            result[section] = {k: data[k] for k in keys if k in data}
            for name in ("bootstrap_notes", "notes", "notes_before", "notes_after"):
                if name in data:
                    result[section][name] = {
                        k: data[name][k]
                        for k in ("revision", "sha256")
                        if k in data[name]
                    }
            if "stages" in data:
                from scripts.m12_stages import FIELDS

                result[section]["stages"] = [
                    {
                        **{
                            k: stage[k]
                            for k in (
                                "schema_version",
                                "run_id",
                                "scenario",
                                "producer",
                                "seq",
                                "stage",
                                "receipt_seq",
                                "received_monotonic",
                                "received_utc",
                            )
                            if k in stage
                        },
                        "payload": {
                            k: v
                            for k, v in stage.get("payload", {}).items()
                            if k in FIELDS.get(stage.get("stage"), set())
                        },
                    }
                    for stage in data["stages"]
                ]
            if "wire" in data:
                fields = {
                    "type",
                    "request_id",
                    "agent_id",
                    "project_id",
                    "workspace_id",
                    "domain_id",
                    "domain_session_id",
                    "state",
                    "execution_state",
                    "status",
                    "output",
                    "output_id",
                    "memory",
                }
                result[section]["wire"] = {
                    name: [
                        {k: v for k, v in packet.items() if k in fields}
                        for packet in data["wire"].get(name, [])
                    ]
                    for name in ("commands", "emitted")
                }
            if "sdk" in data:
                sdk = data["sdk"]
                allowed = (
                    "client_id",
                    "domain",
                    "cwd",
                    "model",
                    "permission_mode",
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
                    "returncode",
                )
                result[section]["sdk"] = {k: sdk[k] for k in allowed if k in sdk}
    if "lifetimes" in record:
        result["lifetimes"] = [
            {
                k: v
                for k, v in life.items()
                if k
                in (
                    "scenario",
                    "run_id",
                    "child_returncode",
                    "forced",
                    "closed",
                    "ended_at",
                    "memory_marker_before",
                    "memory_marker_after",
                    "lease_marker_after",
                    "reservation_after",
                    "owners",
                    "archive_run_id",
                    "cli_returncodes",
                )
            }
            for life in record["lifetimes"]
        ]

    def pick(value, keys):
        return (
            {key: value[key] for key in keys if key in value}
            if isinstance(value, dict)
            else {}
        )

    def hashes(value):
        return (
            {
                key: item
                for key, item in value.items()
                if isinstance(key, str)
                and isinstance(item, str)
                and re.fullmatch(r"[a-f0-9]{64}", item)
            }
            if isinstance(value, dict)
            else {}
        )

    def baseline_fields(value):
        item = pick(value, ("head", "status", "tracked_sha256"))
        if "tracked_sha256" in item:
            item["tracked_sha256"] = hashes(item["tracked_sha256"])
        return item

    receipt_fields = ("cwd", "result", "nonce", "sha256", "written_utc")
    owner_fields = (
        "clean",
        "worker_done",
        "transport_closed",
        "hook_tasks",
        "returncode",
        "lifecycle",
        "task_count",
    )
    if "binding" in result:
        result["binding"] = pick(
            result["binding"],
            ("commit", "source_sha256", "runtime_before", "runtime_after"),
        )
        for key in ("runtime_before", "runtime_after"):
            if key in result["binding"]:
                result["binding"][key] = baseline_fields(result["binding"][key])
        if "source_sha256" in result["binding"]:
            result["binding"]["source_sha256"] = hashes(
                result["binding"]["source_sha256"]
            )
    if "versions" in result:
        result["versions"] = pick(
            result["versions"],
            ("sdk", "anyio", "cli", "godot", "python", "platform", "cli_sha256"),
        )
    if "caps" in result:
        result["caps"] = pick(
            result["caps"],
            (
                "domain_max_turns",
                "domain_max_budget_usd",
                "max_domain_queries",
                "npc_max_turns",
                "npc_deadline_seconds",
                "automatic_retries",
            ),
        )
    for section, check_keys in (
        ("initial", INITIAL_CHECKS),
        ("restart", RESTART_CHECKS),
        ("isolation", ISOLATION_CHECKS),
    ):
        item = result.get(section, {})
        if "checks" in item:
            item["checks"] = pick(item["checks"], check_keys)
        if "tool_receipts" in item:
            item["tool_receipts"] = [
                pick(value, receipt_fields) for value in item["tool_receipts"]
            ]
        for key in ("source_before", "source_after"):
            if key in item:
                item[key] = baseline_fields(item[key])
        if "start" in item:
            item["start"] = pick(
                item["start"],
                (
                    "request_id",
                    "project_id",
                    "workspace_id",
                    "domain_id",
                    "domain_session_id",
                    "query_count",
                ),
            )
        if "context" in item:
            context = pick(
                item["context"], ("project_id", "workspace_id", "facts", "sources")
            )
            context["facts"] = pick(
                context.get("facts"),
                (
                    "source_root",
                    "agent_id",
                    "execution_kind",
                    "domain_id",
                    "tools",
                    "permission_mode",
                    "interaction",
                    "execution_capacity",
                ),
            )
            context["sources"] = [
                pick(source, ("identity", "scope", "revision"))
                for source in context.get("sources", [])
            ]
            item["context"] = context
        if "workspace" in item:
            item["workspace"] = pick(
                item["workspace"],
                (
                    "project_id",
                    "workspace_id",
                    "domain_id",
                    "project_root",
                    "worktree_path",
                    "common_git_dir",
                    "git_dir",
                    "branch",
                    "initial_commit",
                ),
            )
        for key in ("bootstrap_notes", "notes", "notes_before", "notes_after"):
            if key in item and "sha256" in item[key]:
                item[key]["sha256"] = pick(
                    item[key]["sha256"], ("todo", "handoff", "progress")
                )
        if "wire" in item:
            for packets in item["wire"].values():
                for packet in packets:
                    if "memory" in packet:
                        packet["memory"] = pick(
                            packet["memory"], ("saved", "revision", "error_type")
                        )
        if "sdk" in item:
            sdk = item["sdk"]
            sdk["tool_receipts"] = [
                pick(value, receipt_fields) for value in sdk.get("tool_receipts", [])
            ]
            sdk["attempts"] = [
                pick(value, ("name", "id", "parent", "received_utc"))
                for value in sdk.get("attempts", [])
            ]
            sdk["terminals"] = [
                pick(
                    value,
                    (
                        "subtype",
                        "is_error",
                        "reason",
                        "cost_usd",
                        "permission_denials",
                        "errors",
                    ),
                )
                for value in sdk.get("terminals", [])
            ]
    for item in result.get("lifetimes", []):
        if "owners" in item:
            item["owners"] = [pick(value, owner_fields) for value in item["owners"]]
    return result


def post_close_notes(life):
    require(
        life.child.process.returncode == 0
        and not life.child.forced
        and life.closed
        and life.closed.get("run_id") == life.run_id
        and not validate_lifetimes([life.cleanup_evidence]),
        "post-close notes require validated normal cleanup",
    )
    return life.closed["notes"]


def assert_a_unchanged(workspace, expected_notes, expected_result_hash):
    from bridge.project_memory import ProjectMemoryStore

    actual = ProjectMemoryStore(workspace).load()
    require(
        actual.as_context() == expected_notes["context"]
        and sha(read_result(workspace.worktree_path)) == expected_result_hash,
        "repository A changed after its final closed snapshot",
    )
    return True


async def main(output):
    with FreshEvidenceOutput(output) as destination:
        return await _run(destination)


async def _run(output):
    from bridge.domain_sdk import _verify_runtime
    from bridge.workspace import git_without_filters
    import claude_agent_sdk

    artifacts = Path(tempfile.mkdtemp(prefix="plaza-m12-live-"))
    report = dict(
        schema_version=1,
        run_id=uuid4().hex,
        completed=False,
        errors=[],
        started_utc=utc(),
        instrumentation=INSTRUMENTATION,
        lifetimes=[],
        artifacts=str(artifacts),
        desktop_accepted=False,
        auth_mode="api_key" if os.environ.get("ANTHROPIC_API_KEY") else "native_cli",
        cost_category=(
            "paid API-key SDK calls"
            if os.environ.get("ANTHROPIC_API_KEY")
            else "native CLI billing not inferred"
        ),
        caps=dict(
            domain_max_turns=8,
            domain_max_budget_usd=0.35,
            max_domain_queries=3,
            npc_max_turns=1,
            npc_deadline_seconds=65,
            automatic_retries=0,
        ),
        limits=[
            "Linux headless acceptance only; laptop binary and desktop acceptance remain open",
            "cooperative worktree/guard isolation, not a host/network sandbox",
        ],
    )
    life = None
    try:
        from bridge.config import load_config

        permission_mode = load_config().domain_permission_mode
        report["permission_mode"] = permission_mode
        cli = _verify_runtime(permission_mode)
        runtime_before = baseline(ROOT)
        report["binding"] = dict(
            commit=git_without_filters(ROOT, "rev-parse", "HEAD"),
            source_sha256={
                name: sha((ROOT / name).read_bytes()) for name in LIVE_SOURCES
            },
            runtime_before=runtime_before,
        )
        report["versions"] = dict(
            sdk=importlib.metadata.version("claude-agent-sdk"),
            anyio=importlib.metadata.version("anyio"),
            cli=subprocess.run(
                [cli, "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip(),
            godot=subprocess.run(
                [godot_binary(), "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip(),
            python=sys.version.split()[0],
            platform=sys.platform,
            cli_sha256=sha(Path(cli).read_bytes()),
        )
        project = artifacts / "project-a"
        project.mkdir()
        (project / "PLAZA_AGENTS.md").write_text(
            "Disposable acceptance project. Execute only explicit tasks.\n"
        )
        life = LiveLifetime(
            artifacts / "a-initial",
            project,
            "a_initial",
            permission_mode=permission_mode,
        )
        await life.start()
        await initial(life, report)
        report["lifetimes"].append(await life.stop())
        report["initial"]["notes"] = post_close_notes(life)
        life = None
        report["initial"]["checks"]["runtime_unchanged"] = (
            baseline(ROOT) == runtime_before
        )
        require(not validate_lifetimes(report["lifetimes"]), "initial cleanup failed")
        life = LiveLifetime(
            artifacts / "a-restart",
            project,
            "a_restart",
            permission_mode=permission_mode,
        )
        await life.start()
        await readback(life, report, "a_restart")
        report["lifetimes"].append(await life.stop())
        report["restart"]["notes_after"] = post_close_notes(life)
        life = None
        require(not validate_lifetimes(report["lifetimes"]), "restart cleanup failed")
        a_notes = report["restart"]["notes_after"]
        other = artifacts / "project-b"
        other.mkdir()
        (other / "PLAZA_AGENTS.md").write_text(
            "Independent acceptance project B. Execute only explicit tasks.\n"
        )
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
                "isolated fixture",
            ),
        ):
            subprocess.run(
                ["git", "-C", str(other), *args],
                check=True,
                capture_output=True,
                timeout=5,
            )
        life = LiveLifetime(
            artifacts / "b-isolation",
            other,
            "b_isolation",
            permission_mode=permission_mode,
        )
        await life.start()
        await readback(life, report, "b_isolation")
        report["lifetimes"].append(await life.stop())
        report["isolation"]["notes_after"] = post_close_notes(life)
        life = None
        a = report["initial"]
        from bridge.workspace import inspect_project, load_workspace

        workspace = load_workspace(inspect_project(project), runtime_root=ROOT)
        report["isolation"]["checks"]["a_unchanged"] = assert_a_unchanged(
            workspace, a_notes, a["result_sha256"]
        )
        report["binding"]["runtime_after"] = baseline(ROOT)
        report["completed"] = True
    except BaseException as error:
        # Only the exception class plus bounded local acceptance reason is public.
        # Provider errors/logs stay in preserved private artifacts.
        report["errors"].append(
            str(error) if isinstance(error, AcceptanceError) else type(error).__name__
        )
    finally:
        if life and life.child:
            try:
                report["lifetimes"].append(await life.stop())
            except BaseException as error:
                report["errors"].append("teardown: " + type(error).__name__)
                if life.child.process.returncode is None:
                    await life.child.join(0.01)
        report["ended_utc"] = utc()
        report["errors"] = list(
            dict.fromkeys(report["errors"] + validate_evidence(report))
        )
        report["accepted"] = not report["errors"]
        sanitized = sanitize_evidence(report)
        output.publish_json(sanitized)
        print(
            json.dumps(
                dict(
                    accepted=report["accepted"],
                    errors=report["errors"],
                    output=str(output.path),
                    artifacts=str(artifacts),
                )
            ),
            flush=True,
        )
    return 0 if report["accepted"] else 1


def validate_lifetimes(lifetimes):
    """Validate actual final cleanup independently of pre-Stop observations."""
    try:
        _proof_bounded(lifetimes)
        _proof_cleanup(lifetimes)
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        OverflowError,
        RecursionError,
    ) as error:
        return [
            (
                str(error)
                if isinstance(error, AcceptanceError)
                else "malformed cleanup proof"
            )
        ]
    return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--control", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        require(args.control and args.run_id, "internal child binding required")
        asyncio.run(bridge_child(args.child, args.control, args.run_id))
    else:
        parser.error("--output is required") if not args.output else None
        raise SystemExit(asyncio.run(main(args.output.absolute())))
