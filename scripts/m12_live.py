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
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
RESULT = "m12-result.txt"
STAGE_SECONDS = 100
DRAIN_SECONDS = 35
INSTRUMENTATION = (
    "same SDK class: forward init/connect/query/receive_response/disconnect once; "
    "allowlisted options and messages only; original default factory; "
    "unchanged owner construction observed at domain_session binding; "
    "delegating dispatch emission and loopback ephemeral listener observation"
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


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


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


def inspect_service(service, owners, observer):
    snapshot = service.snapshot()
    out = dict(snapshot=snapshot, clients=observer.records, owners=[])
    if snapshot["stage"] == "ready":
        from bridge.workspace_lease import observe_reservation

        work = service.require_workspace()
        marker = (
            work.common_git_dir
            / "plaza/runs"
            / (sha(service.owner_run_id.encode()) + ".json")
        )
        out.update(
            workspace={
                key: str(getattr(work, key))
                for key in (
                    "project_id",
                    "workspace_id",
                    "project_root",
                    "worktree_path",
                    "common_git_dir",
                    "git_dir",
                    "branch",
                    "initial_commit",
                )
            },
            notes=note_snapshot(service),
            memory_marker=str(marker),
            memory_marker_exists=marker.exists(),
            lease_marker_exists=(work.git_dir / "plaza-unclean.json").exists(),
            reservation=observe_reservation(work),
            source=baseline(work.project_root),
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


async def bridge_child(config_path, control, run_id):
    """Isolated instrumentation; no factory/provider/guard replacement."""
    import websockets
    from bridge.config import load_config
    from bridge.domain_sdk import DomainSDKOwner
    from bridge.log_storage import RunLogWriter
    from bridge.observability import BridgeRecorder
    from bridge.project_service import ProjectService
    from bridge.server import BridgeServer
    import bridge.server as server_module
    import bridge.domain_session as session_module

    control = Path(control)
    config = load_config(Path(config_path))
    service = ProjectService(config, runtime_root=ROOT, owner_run_id=run_id)
    writer = RunLogWriter(config, "M12 live acceptance")
    server = BridgeServer(
        config=config,
        project_service=service,
        recorder=BridgeRecorder(config, "M12 live acceptance", writer=writer),
    )
    stop, ready = asyncio.Event(), asyncio.Event()
    owners, listeners, commands, emitted = [], [], [], []
    actual_serve, original_binding = websockets.serve, session_module.DomainSDKOwner

    def listen(handler, host, port):
        listener = actual_serve(handler, "127.0.0.1", 0)
        listeners.append(listener)
        return listener

    def owner(*args, **kwargs):
        require("client_factory" not in kwargs, "live factory override forbidden")
        value = DomainSDKOwner(*args, **kwargs)
        owners.append(value)
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
                    state=inspect_service(service, owners, observer),
                ),
            )
            sequence = 0
            while not stop.is_set() and not serving.done():
                if (control / "stop").exists():
                    require((control / "stop").read_text() == run_id, "foreign Stop")
                    stop.set()
                    break
                sequence += 1
                state = inspect_service(service, owners, observer)
                state.update(
                    run_id=run_id, seq=sequence, commands=commands, emitted=emitted
                )
                write_json(control / "state.json", state)
                await asyncio.sleep(0.025)
            await serving
            final = inspect_service(service, owners, observer)
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


class LiveLifetime:
    def __init__(self, directory, project, scenario):
        self.directory, self.project, self.scenario = directory, project, scenario
        self.run_id = uuid4().hex
        self.directory.mkdir()
        self.control = directory / "control"
        self.control.mkdir()
        self.config = directory / "config.json"
        write_json(
            self.config,
            dict(
                CONFIG_VERSION=1,
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
        return dict(
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
        referral_rendered="query",
        chief_ready="query",
        domain_running="domain_query",
        background_ack="background_domain",
        npc_rendered="query",
        domain_rendered="resume",
        stop_ack="deactivate_domain",
    )
    if stage in ("referral_rendered", "chief_ready", "npc_rendered"):
        expected_agent = (
            "systems-architect" if stage == "chief_ready" else payload["agent_id"]
        )
        require(
            command.get("type") in (None, "query")
            and command.get("agent_id") == expected_agent,
            "stage NPC command mismatch",
        )
    else:
        require(command.get("type") == expected[stage], "stage command kind mismatch")
    if stage in ("referral_rendered", "chief_ready", "npc_rendered"):
        require(
            any(
                p.get("output") == payload["assistant"] and p.get("status") == "ok"
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
        "Run this exact bounded Bash command once (timeout 100000 ms); do not create the result by any other tool, do not retry it. It waits for an external supervisor. Then return JSON with answer equal to the nonce from M12_RECEIPT, and memory_delta with summary equal to that exact nonce and next_action 'Read prior notes without rerunning completed work'. Command: "
        + command
    )


class Plain:
    def __init__(self, socket):
        self.socket, self.packets = socket, []

    async def send(self, kind, request, generation=None, **extra):
        command = dict(type=kind, request_id=request, domain_id="engineering", **extra)
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
            shutil.which("godot"),
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
        checks={}, query_count=0, result_count=0, rendered_count=0, tool_receipts=[]
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
                snapshot, work = state["snapshot"], state["workspace"]
                require(
                    snapshot["stage"] == "ready"
                    and snapshot["architect_decision"]["approved"] is True,
                    "Chief not approved",
                )
                checks["real_chief_approved"] = True
                from bridge.workspace import git_without_filters

                require(
                    git_without_filters(life.project, "branch", "--show-current")
                    == "main"
                    and work["initial_commit"] == state["source"]["head"]
                    and git_without_filters(
                        Path(work["worktree_path"]), "branch", "--show-current"
                    )
                    == work["branch"],
                    "seed/worktree mismatch",
                )
                checks["main_seed"] = True
                require(
                    len(
                        list(
                            (
                                Path(work["common_git_dir"]) / "plaza/session-memory"
                            ).glob("*.md")
                        )
                    )
                    == 3,
                    "missing canonical notes",
                )
                checks["three_notes"] = True
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
                checks["separate_paths"] = True
                source_before = state["source"]
                result.update(
                    worktree_path=work["worktree_path"],
                    workspace=work,
                    source_before=source_before,
                    bootstrap_notes=state["notes"],
                )
                gate = NonceGate(release_path, Path(work["worktree_path"]) / RESULT)
                gate.assert_absent()
                checks["absent_before"] = True
                life.marker_before = state["memory_marker_exists"]
                require(life.marker_before, "memory ownership was not attached")
            elif stage == "domain_running":
                clients = [c for c in state["clients"] if c["domain"]]
                require(
                    len(clients) == 1 and clients[0]["query_count"] == 1,
                    "expected exactly one SDK tool task",
                )
                gate.assert_absent()
            elif stage == "background_ack":
                gate.assert_absent()
                result["background_monotonic"] = receipt["received_monotonic"]
                checks["background_corroborated"] = True
            elif stage == "npc_rendered":
                require(
                    validator.may_release and payload["agent_id"] == "security-auditor",
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
                )
                data = gate.result_path.read_bytes()
                require(
                    data.decode() == result["nonce"]
                    and payload["output"] == result["nonce"],
                    "result content/terminal differs from nonce",
                )
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
    work, a = before["workspace"], report["initial"]
    key = "restart" if scenario == "a_restart" else "isolation"
    record = report[key] = dict(
        checks={"no_automatic_query": True},
        query_count=0,
        tool_count=0,
        workspace=work,
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
        task = "Without tools or file changes, read the supplied prior project notes. Return JSON with answer equal to the exact completed M12 nonce beginning m12-. Do not rerun any earlier task."
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
        task = "Without tools or file changes, inspect only supplied prior project notes. If there is no completed M12 nonce, return JSON with answer 'isolated'. Do not invent a nonce or rerun work."
    async with websockets.connect(life.ready["url"]) as socket:
        plain = Plain(socket)
        await plain.send("activate_domain", "readback-start")
        active = await plain.reply("readback-start", state="active")
        generation = active["domain_session_id"]
        await plain.send(
            "domain_query",
            "readback-run",
            generation,
            agent_id="backend-architect",
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
        require(terminal["output"] == expected, "notes-derived readback incorrect")
        state = life.state()
        clients = [c for c in state["clients"] if c["domain"]]
        require(len(clients) == 1, "unexpected readback clients")
        client = clients[0]
        # State file can trail the final response by one observation; query and
        # tool observations necessarily precede terminal emission.
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
                result_unchanged=sha((Path(a["worktree_path"]) / RESULT).read_bytes())
                == a["result_sha256"],
            )
        else:
            require(a["nonce"] not in query["notes"], "A nonce in B invocation")
            checks.update(no_a_nonce_in_query=True, isolated_readback=True)
        record.update(
            query_count=client["query_count"],
            tool_count=len(client["attempts"]),
            sdk=client,
            output=terminal["output"],
        )
        await plain.send("deactivate_domain", "readback-stop", generation)
        require(
            (await plain.reply("readback-stop", state="inactive"))["state"]
            == "inactive",
            "readback Stop not confirmed",
        )
        checks["stop_inactive"] = True
    record["notes_after"] = life.state()["notes"]


def validate_evidence(record):
    errors = []

    def check(ok, label):
        if not ok:
            errors.append(label)

    if not isinstance(record, dict):
        return ["evidence must be an object"]
    check(
        type(record.get("schema_version")) is int and record.get("schema_version") == 1,
        "schema",
    )
    check(
        record.get("completed") is True and record.get("errors") == [],
        "incomplete/errors",
    )
    check(
        record.get("instrumentation") == INSTRUMENTATION, "instrumentation disclosure"
    )
    for section, keys in (
        ("initial", INITIAL_CHECKS),
        ("restart", RESTART_CHECKS),
        ("isolation", ISOLATION_CHECKS),
    ):
        data = record.get(section)
        if not isinstance(data, dict):
            errors.append(section + " missing")
            continue
        checks = data.get("checks", {})
        check(
            isinstance(checks, dict)
            and set(checks) == set(keys)
            and all(checks.get(k) is True for k in keys),
            section + " checks",
        )
        check(
            type(data.get("query_count")) is int and data["query_count"] == 1,
            section + " query count",
        )
        if section != "initial":
            check(
                type(data.get("tool_count")) is int and data["tool_count"] == 0,
                section + " tool count",
            )
    data = record.get("initial", {})
    if isinstance(data, dict):
        for key in ("result_count", "rendered_count"):
            check(type(data.get(key)) is int and data[key] == 1, key)
        try:
            from scripts.m12_stages import StageValidator

            stages = data.get("stages")
            wire = data.get("wire")
            require(
                isinstance(stages, list)
                and len(stages) == 7
                and isinstance(wire, dict),
                "missing complete stage/wire evidence",
            )
            validator = StageValidator(record["run_id"], "godot")
            for stage in stages:
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
        except (ValueError, TypeError, KeyError, IndexError):
            errors.append("invalid or uncorroborated scene evidence")
        receipts = data.get("tool_receipts")
        check(
            isinstance(receipts, list) and len(receipts) == 1,
            "single actual tool receipt",
        )
        if (
            isinstance(receipts, list)
            and len(receipts) == 1
            and isinstance(receipts[0], dict)
        ):
            tool = receipts[0]
            check(
                tool.get("cwd") == data.get("worktree_path")
                and tool.get("nonce") == data.get("nonce")
                and tool.get("sha256") == data.get("result_sha256")
                and tool.get("result") == RESULT,
                "tool receipt binding",
            )
        times = [
            data.get(k)
            for k in ("background_monotonic", "npc_monotonic", "released_monotonic")
        ]
        check(
            (
                all(type(v) in (int, float) and math.isfinite(v) for v in times)
                and times[2] > times[1] > times[0]
                if all(type(v) in (int, float) for v in times)
                else False
            ),
            "causal release order",
        )
    lifetimes = record.get("lifetimes")
    check(isinstance(lifetimes, list) and len(lifetimes) == 3, "three bridge lifetimes")
    if isinstance(lifetimes, list):
        check(
            [r.get("scenario") for r in lifetimes if isinstance(r, dict)]
            == ["a_initial", "a_restart", "b_isolation"],
            "lifetime scenarios",
        )
        for item in lifetimes:
            if not isinstance(item, dict):
                errors.append("malformed lifetime")
                continue
            check(
                type(item.get("child_returncode")) is int
                and item["child_returncode"] == 0
                and item.get("forced") is False,
                "nonzero/forced bridge child",
            )
            check(
                item.get("closed") is True
                and isinstance(item.get("ended_at"), str)
                and bool(item["ended_at"]),
                "missing/open manifest",
            )
            check(
                item.get("memory_marker_before") is True
                and item.get("memory_marker_after") is False
                and item.get("lease_marker_after") is False
                and "reservation_after" in item
                and item["reservation_after"] is None,
                "ownership cleanup",
            )
            codes = item.get("cli_returncodes")
            check(
                isinstance(codes, list)
                and bool(codes)
                and all(type(code) is int and code == 0 for code in codes),
                "nonzero/missing CLI child",
            )
            owners = item.get("owners")
            check(isinstance(owners, list) and len(owners) == 1, "one actual owner")
            if isinstance(owners, list):
                for owner in owners:
                    check(
                        isinstance(owner, dict)
                        and all(
                            owner.get(k) is True
                            for k in ("clean", "worker_done", "transport_closed")
                        )
                        and type(owner.get("hook_tasks")) is int
                        and owner["hook_tasks"] == 0
                        and type(owner.get("returncode")) is int
                        and owner["returncode"] == 0
                        and type(owner.get("task_count")) is int
                        and owner["task_count"] == 1
                        and owner.get("lifecycle")
                        == ["connect", "query", "receive", "disconnect"],
                        "SDK nonzero/unclean/lifecycle",
                    )
    binding = record.get("binding")
    check(
        isinstance(binding, dict)
        and bool(binding.get("commit"))
        and bool(binding.get("source_sha256"))
        and binding.get("runtime_before") == binding.get("runtime_after")
        and "runtime_before" in binding,
        "source/runtime binding",
    )
    check(
        isinstance(record.get("versions"), dict)
        and all(record["versions"].get(k) for k in ("sdk", "anyio", "cli", "godot")),
        "versions",
    )
    return errors


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
                "released_monotonic",
                "released_utc",
                "background_monotonic",
                "npc_monotonic",
                "output",
                "terminal_identity",
                "godot_returncode",
                "workspace",
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
        if "workspace" in item:
            item["workspace"] = pick(
                item["workspace"],
                (
                    "project_id",
                    "workspace_id",
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


async def main(output):
    from bridge.domain_sdk import _verify_runtime, GUARD_SOURCES
    from bridge.workspace import git_without_filters
    import claude_agent_sdk

    require(
        not output.exists(),
        "output already exists; preserve evidence and choose a fresh path",
    )
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
        cli = _verify_runtime()
        runtime_before = baseline(ROOT)
        report["binding"] = dict(
            commit=git_without_filters(ROOT, "rev-parse", "HEAD"),
            source_sha256={
                name: sha((ROOT / name).read_bytes())
                for name in (
                    *GUARD_SOURCES,
                    "scripts/m12_live.py",
                    "scripts/m12_stages.py",
                    "tests/godot_domain_integration.gd",
                )
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
                [shutil.which("godot"), "--version"],
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
        life = LiveLifetime(artifacts / "a-initial", project, "a_initial")
        await life.start()
        await initial(life, report)
        report["lifetimes"].append(await life.stop())
        life = None
        report["initial"]["checks"]["runtime_unchanged"] = (
            baseline(ROOT) == runtime_before
        )
        require(not validate_lifetimes(report["lifetimes"]), "initial cleanup failed")
        life = LiveLifetime(artifacts / "a-restart", project, "a_restart")
        await life.start()
        await readback(life, report, "a_restart")
        report["lifetimes"].append(await life.stop())
        life = None
        require(not validate_lifetimes(report["lifetimes"]), "restart cleanup failed")
        a_notes = report["restart"]["notes_after"]
        other = artifacts / "project-b"
        other.mkdir()
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
        life = LiveLifetime(artifacts / "b-isolation", other, "b_isolation")
        await life.start()
        await readback(life, report, "b_isolation")
        report["lifetimes"].append(await life.stop())
        life = None
        a = report["initial"]
        from bridge.workspace import inspect_project, load_workspace
        from bridge.project_memory import ProjectMemoryStore

        workspace = load_workspace(inspect_project(project), runtime_root=ROOT)
        current_notes = ProjectMemoryStore(workspace).load()
        report["isolation"]["checks"]["a_unchanged"] = (
            current_notes.as_context() == a_notes["context"]
            and sha((Path(a["worktree_path"]) / RESULT).read_bytes())
            == a["result_sha256"]
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
        write_json(output, sanitized)
        print(
            json.dumps(
                dict(
                    accepted=report["accepted"],
                    errors=report["errors"],
                    output=str(output),
                    artifacts=str(artifacts),
                )
            ),
            flush=True,
        )
    return 0 if report["accepted"] else 1


def validate_lifetimes(lifetimes):
    # Apply the same cleanup rules at each boundary before another paid lifetime.
    fake = {"lifetimes": lifetimes}
    return [
        e
        for e in validate_evidence(fake)
        if e
        in (
            "nonzero/forced bridge child",
            "missing/open manifest",
            "ownership cleanup",
            "nonzero/missing CLI child",
            "one actual owner",
            "SDK nonzero/unclean/lifecycle",
        )
    ]


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
        raise SystemExit(asyncio.run(main(args.output.resolve())))
