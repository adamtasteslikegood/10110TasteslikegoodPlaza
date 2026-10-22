"""Actual CLI signals and owned handler lifetimes, without provider access."""

import asyncio
from contextlib import asynccontextmanager, closing
import json
import os
from pathlib import Path
import signal
import sys

import pytest
import websockets

from bridge import bridge as cli
from bridge import project_files
from bridge.log_storage import iter_jsonl
from bridge.tests.m12_harness import until
from bridge.tests.test_workspace import repository

ROOT = Path(__file__).resolve().parents[2]

# Only test seams: ephemeral loopback binding, transport prohibition, observation,
# and a gated/failing filesystem detach. The real __main__ composition runs.
CHILD = """
import asyncio
import json
from pathlib import Path
import runpy
import sys
import time

import httpx
import anyio
from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
from bridge import server
from bridge import conversation_sdk
from bridge.agent_bindings import BindingRegistry
from bridge.project_memory import ProjectMemoryStore
from bridge.project_service import ProjectService

async def forbidden_async(*args, **kwargs):
    raise AssertionError('provider transport forbidden in CLI shutdown fixture')

def forbidden_sync(*args, **kwargs):
    raise AssertionError('provider transport forbidden in CLI shutdown fixture')

SubprocessCLITransport.connect = forbidden_async
httpx.AsyncHTTPTransport.handle_async_request = forbidden_async
httpx.HTTPTransport.handle_request = forbidden_sync
server.LISTEN_HOST = '127.0.0.1'
server.LISTEN_PORT = 0
mode, fixture = sys.argv[2], Path(sys.argv[3])
listeners = []
original_listen = server.websockets.serve

def listen(*args, **kwargs):
    listener = original_listen(*args, **kwargs)
    listeners.append(listener)
    return listener

server.websockets.serve = listen
original_bootstrap = ProjectService._bootstrap

async def bootstrap(self):
    await original_bootstrap(self)
    assert self.snapshot()['stage'] == 'ready', self.snapshot()['stage']
    print('CLI_PROJECT_READY', flush=True)

ProjectService._bootstrap = bootstrap
original_event = server.BridgeServer._event

def event(self, name, *args, **kwargs):
    original_event(self, name, *args, **kwargs)
    if name == 'bridge_started':
        port = listeners[0].server.sockets[0].getsockname()[1]
        (fixture / 'address').write_text(f'ws://127.0.0.1:{port}')
        print('CLI_LISTENING', flush=True)
    elif name == 'connection_closed':
        (fixture / 'connection-closed').touch()

server.BridgeServer._event = event
original_detach = ProjectMemoryStore.detach_run

def detach(self, owner_run_id):
    if mode == 'failure':
        raise OSError('synthetic detach failure')
    if mode == 'hold':
        (fixture / 'draining').touch()
        deadline = time.monotonic() + 10
        while not (fixture / 'release').exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('CLI fixture drain was not released')
            time.sleep(0.01)
    original_detach(self, owner_run_id)

ProjectMemoryStore.detach_run = detach
if not mode.startswith('npc-'):
    runpy.run_path(sys.argv[1], run_name='__main__')
else:
    # A real owned local subprocess and an unrelated sibling. Only the former
    # is handed to the SDK transport; fixture cleanup always joins both.
    processes, unrelated = [], []
    original_registry = BindingRegistry.__init__

    def registry(self, **kwargs):
        kwargs['extras'] = {'fixture-extra': dict(
            execution_kind='extra', domain_id=None, definition='Synthetic NPC')}
        original_registry(self, **kwargs)

    BindingRegistry.__init__ = registry

    async def failed_close(self):
        raise OSError('private-cleanup-sentinel')

    if mode != 'npc-clean':
        SubprocessCLITransport.close = failed_close

    class Client:
        def __init__(self, *, options, transport=None):
            self._transport = transport or SubprocessCLITransport('', options)

        async def connect(self):
            code = ('import sys; sys.stdin.buffer.read()' if mode == 'npc-clean'
                    else 'import time; time.sleep(60)')
            process = await anyio.open_process([sys.executable, '-c', code])
            processes.append(process)
            self._transport._process = process
            self._transport._stdin_stream = process.stdin
            unrelated.append(await anyio.open_process(
                [sys.executable, '-c', 'import time; time.sleep(60)']))

        async def query(self, prompt):
            pass

        async def receive_response(self):
            (fixture / 'npc-receiving').touch()
            if mode == 'npc-cancel':
                await asyncio.Future()
            if mode == 'npc-query-error':
                raise RuntimeError('private-operation-sentinel')
            yield AssistantMessage([TextBlock('synthetic answer')], 'synthetic')
            yield ResultMessage(subtype='success', duration_ms=1, duration_api_ms=1,
                is_error=False, num_turns=1, session_id='synthetic',
                result='synthetic answer')

        async def disconnect(self):
            (fixture / 'npc-disconnecting').touch()
            while not (fixture / 'release-npc').exists():
                await asyncio.sleep(0.01)
            if mode != 'npc-clean':
                raise OSError('private-cleanup-sentinel')
            await self._transport.close()

    conversation_sdk.ClaudeSDKClient = Client

    async def exercise():
        from bridge.bridge import _serve_cli
        try:
            await _serve_cli()
        finally:
            (fixture / 'npc-observation.json').write_text(json.dumps(dict(
                owned_returncodes=[p.returncode for p in processes],
                unrelated_returncodes=[p.returncode for p in unrelated])))
            for process in processes + unrelated:
                if process.returncode is None:
                    process.kill()
                await process.wait()

    asyncio.run(exercise())
"""


@asynccontextmanager
async def child_runtime(tmp_path, mode):
    root = repository(tmp_path)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            dict(
                LOG_DIR=str(tmp_path / "logs"),
                WORKSPACE_ROOT_DIR=str(root),
                INSTALL_CONTEXT_DIR=str(tmp_path / "context"),
            )
        )
    )
    home = tmp_path / "home"
    home.mkdir()
    # Deliberately allowlist the child environment and give it an empty home:
    # no ambient provider credentials, .env, CLI auth, or model network access.
    environment = dict(
        PATH=os.defpath,
        HOME=str(home),
        PYTHONPATH=str(ROOT),
        BRIDGE_CONFIG_PATH=str(config),
    )
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        CHILD,
        str(ROOT / "bridge/bridge.py"),
        mode,
        str(tmp_path),
        cwd=tmp_path,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(10):
            ready = set()
            while ready != {b"CLI_LISTENING\n", b"CLI_PROJECT_READY\n"}:
                line = await child.stdout.readline()
                assert line, (await child.stderr.read()).decode()
                ready.add(line)
        manifest = next((tmp_path / "logs").glob("runs/*/manifest.json"))
        owner = next((root / ".git/plaza/runs").glob("*.json"))
        yield child, manifest, owner
    finally:
        # A failing assertion must never leave a real child or blocked worker.
        (tmp_path / "release").touch()
        (tmp_path / "release-npc").touch()
        if mode.startswith("npc-") and child.returncode is None:
            try:
                child.send_signal(signal.SIGTERM)
                await asyncio.wait_for(child.wait(), 10)
            except (ProcessLookupError, TimeoutError):
                pass
        if child.returncode is None:
            try:
                child.kill()
            except ProcessLookupError:
                pass
        await asyncio.wait_for(child.communicate(), 5)


@pytest.mark.skipif(os.name != "posix", reason="real POSIX signals and project IO")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["npc-cancel", "npc-finished", "npc-query-error", "npc-clean"]
)
async def test_cli_npc_cleanup_failure_retains_owner_and_open_manifest(tmp_path, mode):
    async with child_runtime(tmp_path, mode) as (child, manifest, owner):
        async with websockets.connect((tmp_path / "address").read_text()) as socket:
            await socket.send(
                json.dumps(dict(agent_id="fixture-extra", task="synthetic task"))
            )
            await until(lambda: (tmp_path / "npc-receiving").exists())
            if mode == "npc-cancel":
                child.send_signal(signal.SIGTERM)
            await until(lambda: (tmp_path / "npc-disconnecting").exists())
            assert json.loads(manifest.read_text())["status"] == "open"
            assert owner.exists()
            with pytest.raises(BlockingIOError):
                with closing(
                    project_files.FileLock.acquire(owner.with_suffix(".lock"))
                ):
                    pass
            (tmp_path / "release-npc").touch()
            if mode != "npc-cancel":
                response = json.loads(await asyncio.wait_for(socket.recv(), 5))
                assert response["status"] == ("ok" if mode == "npc-clean" else "error")
                assert "private-" not in json.dumps(response)
        if mode != "npc-cancel":
            # The failed request AND its connection have retired before stop.
            await until(lambda: (tmp_path / "connection-closed").exists())
            child.send_signal(signal.SIGTERM)
        _, stderr = await asyncio.wait_for(child.communicate(), 10)
        failed = mode != "npc-clean"
        assert (child.returncode != 0) == failed, stderr.decode()
        record = json.loads(manifest.read_text())
        assert record["status"] == ("open" if failed else "closed")
        assert (record["ended_at"] is None) == failed
        assert owner.exists() == failed
        observed = json.loads((tmp_path / "npc-observation.json").read_text())
        assert len(observed["owned_returncodes"]) == 1
        assert observed["owned_returncodes"][0] is not None
        assert observed["unrelated_returncodes"] == [None]
        assert "private-" not in stderr.decode()


@pytest.mark.skipif(os.name != "posix", reason="real POSIX signals and project IO")
@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [signal.SIGINT, signal.SIGTERM])
async def test_cli_requested_signal_closes_manifest(tmp_path, requested):
    async with child_runtime(tmp_path, "normal") as (child, manifest, owner):
        child.send_signal(requested)
        _, stderr = await asyncio.wait_for(child.communicate(), 10)
        assert child.returncode == 0, stderr.decode()
        closed = json.loads(manifest.read_text())
        assert closed["status"] == "closed" and closed["ended_at"]
        assert not owner.exists()


@pytest.mark.skipif(os.name != "posix", reason="real POSIX signals and project IO")
@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [signal.SIGINT, signal.SIGTERM])
async def test_cli_requested_signal_drains_repeated_stop_then_closes_manifest(
    tmp_path, requested
):
    async with child_runtime(tmp_path, "hold") as (child, manifest, owner):
        child.send_signal(requested)
        await until(
            lambda: (tmp_path / "draining").exists() or child.returncode is not None
        )
        assert child.returncode is None
        assert json.loads(manifest.read_text())["status"] == "open"
        assert owner.exists()
        with pytest.raises(BlockingIOError):
            with closing(project_files.FileLock.acquire(owner.with_suffix(".lock"))):
                pass
        # These remain idempotent stop requests while owned IO is still draining.
        child.send_signal(signal.SIGINT)
        child.send_signal(signal.SIGTERM)
        (tmp_path / "release").touch()
        _, stderr = await asyncio.wait_for(child.communicate(), 10)
        assert child.returncode == 0, stderr.decode()
        closed = json.loads(manifest.read_text())
        assert closed["status"] == "closed" and closed["ended_at"]
        assert not owner.exists()
        with closing(project_files.FileLock.acquire(owner.with_suffix(".lock"))):
            pass
        records = [
            row
            for path in manifest.parent.glob("events-*.jsonl")
            for row in iter_jsonl(path, on_diagnostic=pytest.fail)
        ]
        stopped = [row for row in records if row["event"] == "bridge_stopped"]
        assert len(stopped) == 1 and stopped[0]["outcome"] == "success"


@pytest.mark.skipif(os.name != "posix", reason="real POSIX signals and project IO")
@pytest.mark.asyncio
async def test_cli_requested_signal_with_detach_failure_leaves_manifest_open(tmp_path):
    async with child_runtime(tmp_path, "failure") as (child, manifest, owner):
        child.send_signal(signal.SIGTERM)
        _, stderr = await asyncio.wait_for(child.communicate(), 10)
        assert child.returncode != 0, stderr.decode()
        incomplete = json.loads(manifest.read_text())
        assert incomplete["status"] == "open" and incomplete["ended_at"] is None
        assert owner.exists()
        with closing(project_files.FileLock.acquire(owner.with_suffix(".lock"))):
            pass  # The OS reaped the failed child's lock; no clean detach claimed.
        records = [
            row
            for path in manifest.parent.glob("events-*.jsonl")
            for row in iter_jsonl(path, on_diagnostic=pytest.fail)
        ]
        stopped = [row for row in records if row["event"] == "bridge_stopped"]
        assert len(stopped) == 1 and stopped[0]["outcome"] == "failure"


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("outcome", ["normal", "error", "cancel"])
async def test_cli_restores_prior_handlers_on_every_exit(
    monkeypatch, fallback, outcome
):
    loop = asyncio.get_running_loop()
    previous = {
        number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)
    }
    inherited = []

    def handler(number, frame):
        inherited.append(number)

    for number in previous:
        signal.signal(number, handler)
    if fallback:

        def unsupported(*args):
            raise NotImplementedError

        monkeypatch.setattr(loop, "add_signal_handler", unsupported)

    async def serving(*, stop_event):
        # A custom prior handler makes this safe even if installation regresses.
        loop.call_soon(signal.raise_signal, signal.SIGINT)
        await asyncio.wait_for(stop_event.wait(), 1)
        if outcome == "error":
            raise RuntimeError("synthetic serve failure")
        if outcome == "cancel":
            raise asyncio.CancelledError("arbitrary cancellation")

    monkeypatch.setattr(cli, "serve", serving)
    try:
        if outcome == "normal":
            await cli._serve_cli()
        else:
            expected = RuntimeError if outcome == "error" else asyncio.CancelledError
            with pytest.raises(expected):
                await cli._serve_cli()
        assert inherited == []
        assert all(signal.getsignal(number) is handler for number in previous)
    finally:
        for number, prior in previous.items():
            signal.signal(number, prior)


@pytest.mark.asyncio
async def test_cli_in_worker_thread_preserves_main_thread_signal_ownership(monkeypatch):
    previous = {
        number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)
    }
    entered = []

    async def serving(*, stop_event):
        entered.append(stop_event)

    monkeypatch.setattr(cli, "serve", serving)
    await asyncio.wait_for(asyncio.to_thread(cli.main), 3)
    assert len(entered) == 1 and isinstance(entered[0], asyncio.Event)
    assert all(signal.getsignal(number) is prior for number, prior in previous.items())
