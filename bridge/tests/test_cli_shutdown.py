"""Actual CLI signals and owned handler lifetimes, without provider access."""

import asyncio
from contextlib import asynccontextmanager, closing
import json
import os
from pathlib import Path
import signal
import sys

import pytest

from bridge import bridge as cli
from bridge import project_files
from bridge.log_storage import iter_jsonl
from bridge.tests.m12_harness import until
from bridge.tests.test_workspace import repository

ROOT = Path(__file__).resolve().parents[2]

# Only test seams: ephemeral loopback binding, transport prohibition, observation,
# and a gated/failing filesystem detach. The real __main__ composition runs.
CHILD = """
from pathlib import Path
import runpy
import sys
import time

import httpx
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
from bridge import server
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
        print('CLI_LISTENING', flush=True)

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
runpy.run_path(sys.argv[1], run_name='__main__')
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
        if child.returncode is None:
            try:
                child.kill()
            except ProcessLookupError:
                pass
        await asyncio.wait_for(child.communicate(), 5)


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
