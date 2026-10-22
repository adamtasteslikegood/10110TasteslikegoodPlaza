"""SDK calls live in one owning task; callers never cancel that task directly."""

import asyncio
import importlib
from types import SimpleNamespace

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage

from bridge.config import load_config


class Client:
    def __init__(self, *, options, transport):
        self.options, self.transport = options, transport
        self.calls = []
        self.connect_gate = None
        self.receive_gate = None
        self.cleanup_gate = None
        self.disconnect_error = False
        self.entered = asyncio.Event()
        self.receiving = asyncio.Event()
        self.cleaning = asyncio.Event()
        self.messages = [AssistantMessage([TextBlock("partial")], "model"), terminal()]

    def note(self, name):
        self.calls.append((name, asyncio.current_task()))

    async def connect(self):
        self.note("connect")
        self.entered.set()
        if self.connect_gate:
            await self.connect_gate.wait()

    async def query(self, prompt):
        self.note("query")
        self.prompt = prompt

    async def receive_response(self):
        self.note("receive")
        self.receiving.set()
        if self.receive_gate:
            await self.receive_gate.wait()
        for message in self.messages:
            yield message

    async def disconnect(self):
        self.note("disconnect")
        self.cleaning.set()
        if self.cleanup_gate:
            await self.cleanup_gate.wait()
        if self.disconnect_error:
            raise RuntimeError("private")


def terminal(**changes):
    values = dict(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="session",
    )
    values.update(changes)
    return ResultMessage(**values)


@pytest.fixture
def owner(tmp_path):
    module = importlib.import_module("bridge.domain_sdk")
    clients = []
    workspace = SimpleNamespace(worktree_path=tmp_path)

    class Ready:
        async def check_tool(self, *args, **kwargs):
            return None

        def pre_tool_hook(self, lease):
            async def hook(*args):
                return {}

            return hook

    def factory(**kwargs):
        client = Client(**kwargs)
        clients.append(client)
        return client

    instance = module.DomainSDKOwner(
        load_config(environ={}), workspace, object(), Ready(), client_factory=factory
    )
    return instance, clients


async def run(owner):
    return await owner.execute(
        agent_id="builder", definition="Build", task="task", prior_project_notes="notes"
    )


@pytest.mark.asyncio
async def test_sdk_calls_have_one_owner_task(owner):
    sdk, clients = owner
    await sdk.start()
    assert (await run(sdk)).output == "partial"
    assert (await run(sdk)).status == "success"
    assert (await sdk.stop()).clean
    client = clients[0]
    assert len({task for _, task in client.calls}) == 1
    assert client.calls[0][1] is not asyncio.current_task()
    assert client.options.cwd == str(sdk.workspace.worktree_path)
    assert client.options.hooks["PreToolUse"][0].matcher == ".*"
    assert client.options.tools == ["Read", "Edit", "Bash"]
    assert "notes" in client.prompt


@pytest.mark.asyncio
async def test_stop_preempts_connect(owner):
    sdk, clients = owner
    factory = sdk.client_factory

    def blocked(**kwargs):
        client = factory(**kwargs)
        client.connect_gate = asyncio.Event()
        return client

    sdk.client_factory = blocked
    start = asyncio.create_task(sdk.start())
    while not clients:
        await asyncio.sleep(0)
    await clients[0].entered.wait()
    assert (await sdk.stop()).clean
    with pytest.raises(RuntimeError):
        await start
    assert [name for name, _ in clients[0].calls] == ["connect", "disconnect"]


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_cleanup(owner):
    sdk, clients = owner
    await sdk.start()
    client = clients[0]
    client.receive_gate, client.cleanup_gate = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(run(sdk))
    await client.receiving.wait()
    task.cancel()
    await client.cleaning.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    client.cleanup_gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await sdk.stop()).clean


@pytest.mark.asyncio
async def test_query_stop_and_busy_no_queue(owner):
    sdk, clients = owner
    await sdk.start()
    clients[0].receive_gate = asyncio.Event()
    task = asyncio.create_task(run(sdk))
    await clients[0].receiving.wait()
    with pytest.raises(RuntimeError, match="busy"):
        await run(sdk)
    assert (await sdk.stop()).clean
    assert (await task).status == "cancelled"


@pytest.mark.asyncio
async def test_disconnect_failure_retains_uncertain_cleanup(owner):
    sdk, clients = owner
    await sdk.start()
    clients[0].disconnect_error = True
    cleanup = await sdk.stop()
    assert not cleanup.clean and cleanup.error_type == "RuntimeError"
    with pytest.raises(RuntimeError):
        await run(sdk)
    with pytest.raises(RuntimeError):
        await sdk.start()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "messages",
    [
        [],
        [terminal(subtype="error_max_turns")],
        [terminal(is_error=True)],
        [terminal(stop_reason="max_tokens")],
        [terminal(terminal_reason="max_budget_usd")],
    ],
)
async def test_sdk_terminal_errors_keep_partial_text(owner, messages):
    sdk, clients = owner
    await sdk.start()
    clients[0].messages = [AssistantMessage([TextBlock("partial")], "model"), *messages]
    result = await run(sdk)
    assert result.status == "error" and result.output == "partial"
    assert (await sdk.stop()).clean


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("plain", ("plain", None)),
        (
            '{"answer":"yes","memory_delta":{"summary":"done"}}',
            ("yes", {"summary": "done"}),
        ),
        ('{"answer":"yes","memory_delta":5}', ("yes", None)),
        ('{"answer":5}', ('{"answer":5}', None)),
    ],
)
def test_decode_project_reply(raw, expected):
    module = importlib.import_module("bridge.conversation_backend")
    assert module.decode_project_reply(raw) == expected


@pytest.mark.asyncio
async def test_broken_transport_rejects_further_queries(owner):
    sdk, clients = owner
    await sdk.start()
    clients[0].messages = []
    assert (await run(sdk)).reason == "missing_terminal"
    with pytest.raises(RuntimeError):
        await run(sdk)
    assert (await sdk.stop()).clean
    assert sum(name == "connect" for name, _ in clients[0].calls) == 1


@pytest.mark.asyncio
async def test_stopped_before_scope_publication_never_connects(owner):
    sdk, clients = owner
    start = asyncio.create_task(sdk.start())
    await asyncio.sleep(0)
    assert (await sdk.stop()).clean
    with pytest.raises(RuntimeError):
        await start
    assert not clients


@pytest.mark.asyncio
async def test_installed_domain_transport_reaps_harmless_child(owner):
    import os
    import sys
    import anyio

    sdk, clients = owner
    processes = []

    class LocalClient(Client):
        async def connect(self):
            self.note("connect")
            process = await anyio.open_process(
                [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"]
            )
            processes.append(process)
            self.transport.inner._process = process
            self.transport.inner._stdin_stream = process.stdin
            self.transport.process = process

        async def disconnect(self):
            self.note("disconnect")
            await self.transport.close()

    def factory(**kwargs):
        client = LocalClient(**kwargs)
        client.receive_gate = asyncio.Event()
        clients.append(client)
        return client

    sdk.client_factory = factory
    await sdk.start()
    task = asyncio.create_task(run(sdk))
    await clients[0].receiving.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await sdk.stop()).clean and processes[0].returncode == 0
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)
    assert len({task for _, task in clients[0].calls}) == 1


@pytest.mark.asyncio
async def test_terminal_result_utf8_output_is_bounded(owner):
    sdk, clients = owner
    await sdk.start()
    clients[0].messages = [terminal(result="é" * (256 * 1024))]
    outcome = await run(sdk)
    assert len(outcome.output.encode()) <= 256 * 1024
    assert outcome.status == "error"
    assert (await sdk.stop()).clean


def acceptance_fixture(module):
    """Synthetic schema fixture; this never writes or activates live evidence."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "tests/test_m12_tool_guard_probe.py"
    spec = importlib.util.spec_from_file_location("guard_test_fixtures", path)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    evidence = fixtures.complete_evidence()
    evidence.update(accepted=True, errors=[])
    return evidence


def envelope(record):
    from copy import deepcopy

    second = deepcopy(record)
    second["permission_mode"] = "bypassPermissions"
    return {
        "schema_version": 1,
        "records": {"dontAsk": record, "bypassPermissions": second},
    }


def test_acceptance_manifest_requires_versions_cases_inventory_and_exact_sources(
    tmp_path,
):
    import hashlib
    import json

    module = importlib.import_module("bridge.domain_sdk")
    evidence = acceptance_fixture(module)
    evidence["source_sha256"] = {}
    for name in module.GUARD_SOURCES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture source")
        evidence["source_sha256"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    module.check_acceptance(envelope(evidence), tmp_path, "dontAsk")
    for field, value in [
        ("accepted", False),
        ("versions", {}),
        ("production_tools", ["Bash"]),
        ("cases", []),
        ("source_sha256", {}),
    ]:
        changed = json.loads(json.dumps(evidence))
        changed[field] = value
        with pytest.raises(RuntimeError):
            module.check_acceptance(envelope(changed), tmp_path, "dontAsk")
    (tmp_path / module.GUARD_SOURCES[0]).write_text("changed source")
    with pytest.raises(RuntimeError):
        module.check_acceptance(envelope(evidence), tmp_path, "dontAsk")


def test_runtime_missing_acceptance_manifest_fails_closed(monkeypatch, tmp_path):
    module = importlib.import_module("bridge.domain_sdk")
    monkeypatch.setattr(
        module, "ACCEPTANCE_PATH", tmp_path / "missing.json", raising=False
    )
    with pytest.raises(RuntimeError, match="acceptance"):
        module._verify_runtime("dontAsk")


@pytest.mark.asyncio
async def test_connect_cancel_closes_retained_transport_before_sdk_query_exists(owner):
    """Pinned SDK disconnect omits transport close until _query exists."""
    import os
    import sys
    import anyio

    sdk, clients = owner
    processes = []
    entered = asyncio.Event()

    class PartialSDK(Client):
        async def connect(self):
            self.note("connect")
            process = await anyio.open_process(
                [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"]
            )
            processes.append(process)
            self.transport.inner._process = process
            self.transport.inner._stdin_stream = process.stdin
            self.transport.process = process
            entered.set()
            await asyncio.Event().wait()

        async def disconnect(self):
            self.note("disconnect")  # Exactly the SDK's pre-_query no-close path.

    def factory(**kwargs):
        client = PartialSDK(**kwargs)
        clients.append(client)
        return client

    sdk.client_factory = factory
    task = asyncio.create_task(sdk.start())
    await entered.wait()
    cleanup = await sdk.stop()
    with pytest.raises(RuntimeError):
        await task
    try:
        assert cleanup.clean and processes[0].returncode == 0
        with pytest.raises(ProcessLookupError):
            os.kill(processes[0].pid, 0)
        assert len({task for _, task in clients[0].calls}) == 1
    finally:
        # Fixture rescue never makes the failing assertion pass.
        await clients[0].transport.close()


@pytest.mark.parametrize("mutation", ["stripped", "executed", "limit", "terminal"])
def test_runtime_acceptance_recomputes_complete_observations(mutation, tmp_path):
    import hashlib

    module = importlib.import_module("bridge.domain_sdk")
    evidence = acceptance_fixture(module)
    for name in module.GUARD_SOURCES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic test source")
        evidence["source_sha256"][name] = hashlib.sha256(
            target.read_bytes()
        ).hexdigest()
    module.check_acceptance(envelope(evidence), tmp_path, "dontAsk")
    if mutation == "stripped":
        evidence["cases"] = [
            {"name": c["name"], "errors": []} for c in evidence["cases"]
        ]
    elif mutation == "executed":
        evidence["cases"][1]["sentinel_executed"] = True
    elif mutation == "limit":
        del evidence["case_deadline_seconds"]
    else:
        evidence["cases"][0]["terminal"] = None
    with pytest.raises(RuntimeError, match="acceptance"):
        module.check_acceptance(envelope(evidence), tmp_path, "dontAsk")


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_caller", ["stop", "execute"])
async def test_installed_query_close_drains_hook_io_through_repeated_cancel(
    tmp_path, cancel_caller
):
    import sys
    import threading
    import anyio
    from claude_agent_sdk._internal.query import Query
    from bridge.domain_sdk import DomainSDKOwner
    from bridge.readiness import ReadinessService, owned_io

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    disconnected = asyncio.Event()
    clients = []

    def blocked_read():
        entered.set()
        assert release.wait(10), "test fixture never released its worker"
        finished.set()

    class Ready(ReadinessService):
        async def check_tool(self, lease, **kwargs):
            if kwargs["tool_name"] != "__startup__":
                await owned_io(blocked_read)

    class InstalledQueryClient(Client):
        async def connect(self):
            self.note("connect")
            process = await anyio.open_process(
                [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"]
            )
            self.transport.inner._process = process
            self.transport.inner._stdin_stream = process.stdin
            self.transport.process = process
            self.query_obj = Query(self.transport, True)
            self.query_obj.hook_callbacks["hook_0"] = self.options.hooks["PreToolUse"][
                0
            ].hooks[0]

        async def query(self, prompt):
            self.note("query")
            self.query_obj._spawn_control_request_handler(
                {
                    "type": "control_request",
                    "request_id": "r",
                    "request": {
                        "subtype": "hook_callback",
                        "callback_id": "hook_0",
                        "tool_use_id": "t",
                        "input": {
                            "hook_event_name": "PreToolUse",
                            "tool_name": "Read",
                            "tool_use_id": "t",
                            "cwd": self.options.cwd,
                        },
                    },
                }
            )

        async def receive_response(self):
            self.note("receive")
            await asyncio.Event().wait()
            yield None

        async def disconnect(self):
            self.note("disconnect")
            await self.query_obj.close()
            self.query_obj.close_receive_stream()
            disconnected.set()

    def factory(**kwargs):
        client = InstalledQueryClient(**kwargs)
        clients.append(client)
        return client

    workspace = SimpleNamespace(worktree_path=tmp_path)
    sdk = DomainSDKOwner(
        load_config(environ={}),
        workspace,
        object(),
        Ready(workspace, tmp_path, None),
        client_factory=factory,
    )
    pending = stopping = None
    try:
        await sdk.start()
        pending = asyncio.create_task(run(sdk))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        handler = next(iter(clients[0].query_obj._child_tasks))
        if cancel_caller == "execute":
            pending.cancel()
        stopping = asyncio.create_task(sdk.stop())
        await asyncio.sleep(0)
        caller = stopping if cancel_caller == "stop" else pending
        caller.cancel()
        await disconnected.wait()
        caller.cancel()
        await asyncio.sleep(0)
        assert sdk.transport.process.returncode == 0
        assert not finished.is_set() and not handler.done()
        assert not stopping.done(), "clean Stop preceded detached hook IO settlement"
        assert not caller.done(), "repeated cancellation abandoned the hook worker"
        release.set()
        assert (await stopping).clean
        if cancel_caller == "execute":
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            await pending
        assert finished.is_set() and handler.done()
        assert len({task for _, task in clients[0].calls}) == 1
    finally:
        release.set()
        if stopping is not None:
            await asyncio.gather(stopping, return_exceptions=True)
        else:
            await sdk.stop()
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        for client in clients:
            for handle in list(client.query_obj._child_tasks):
                try:
                    await handle.wait()
                except Exception:
                    pass  # Closed-channel response is expected during fixture teardown.


@pytest.mark.asyncio
async def test_each_mailbox_query_carries_current_context(owner):
    from bridge.context import ContextPacket

    sdk, clients = owner
    await sdk.start()
    try:
        for text in ("first context", "second context"):
            packet = ContextPacket(
                text, "work", '{"tools": ["Read", "Edit", "Bash"]}', ()
            )
            await sdk.execute(
                agent_id="builder",
                definition="role",
                task="task",
                prior_project_notes="prior data",
                context_packet=packet,
            )
            import json

            command = json.loads(clients[0].prompt)
            assert text in command["current_context"]
            assert command["prior_project_notes"] == "prior data"
        assert len(clients) == 1
    finally:
        await sdk.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("skip,mode", [(False, "dontAsk"), (True, "bypassPermissions")])
async def test_production_start_verifies_actual_mode_before_connect(
    owner, monkeypatch, skip, mode
):
    from dataclasses import replace

    module = importlib.import_module("bridge.domain_sdk")
    sdk, clients = owner
    sdk.config = replace(sdk.config, domain_dangerously_skip_permissions=skip)
    monkeypatch.setattr(module, "ClaudeSDKClient", sdk.client_factory)
    verified = []

    def reject(permission_mode):
        verified.append(permission_mode)
        raise RuntimeError("synthetic missing acceptance")

    monkeypatch.setattr(module, "_verify_runtime", reject)
    with pytest.raises(RuntimeError):
        await sdk.start()
    assert verified == [mode]
    assert not clients
    assert (await sdk.stop()).clean
