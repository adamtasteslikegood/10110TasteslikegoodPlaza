"""Provider-free acceptance: real Godot HUD/client and real Python bridge."""

import asyncio
from copy import deepcopy
import os
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from bridge.server import BridgeServer

ROOT = Path(__file__).resolve().parents[2]
MARKER = "godot_bridge_integration: OK — 35 checks passed."


@pytest.mark.asyncio
async def test_delayed_replies_failure_and_fresh_reconnect(
    tmp_path, runtime_config, offline_clients
):
    godot = shutil.which(os.environ.get("GODOT_BIN", "godot"))
    if not godot:
        if os.environ.get("PLAZA_REQUIRE_GODOT"):
            pytest.fail("Godot is required for this integration gate")
        pytest.skip("Godot unavailable; the Godot CI job requires this integration")
    scene = ROOT / "tests/godot_bridge_integration.tscn"
    assert scene.is_file(), "real client/bridge integration scene must exist"
    progress = tmp_path / "progress"
    release_first, release_disconnected = threading.Event(), threading.Event()
    calls = []
    sockets = []
    provider, _, _ = offline_clients

    def create(**kwargs):
        calls.append(deepcopy(kwargs["messages"]))
        task = kwargs["messages"][-1]["content"]
        if task == "delayed A 雪":
            assert release_first.wait(15), "scene never queued independent B"
            output = "late A success 雪"
        elif task == "fail B":
            raise RuntimeError("B independent failure")
        elif task == "disconnect pending":
            assert release_disconnected.wait(15), "disconnect was never exercised"
            output = "must never enter fresh thread"
        elif task == "fresh context":
            output = "fresh reply " + "雪" * 1000
        else:
            raise AssertionError(f"unexpected submitted task: {task!r}")
        return SimpleNamespace(content=[SimpleNamespace(text=output)])

    provider.messages.create.side_effect = create
    server = BridgeServer(config=runtime_config)

    async def handle(socket):
        sockets.append(socket)
        try:
            await server._handle_connection(socket)
        except ConnectionClosed:
            # Expected: the blocked request finishes after its socket was closed.
            pass

    async def until(predicate):
        async with asyncio.timeout(15):
            while not predicate():
                await asyncio.sleep(0.01)

    process = None
    try:
        async with websockets.serve(handle, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            env = {
                **os.environ,
                "PLAZA_TEST_BRIDGE_URL": f"ws://127.0.0.1:{port}",
                "PLAZA_TEST_PROGRESS": str(progress),
            }
            process = await asyncio.create_subprocess_exec(
                godot,
                "--headless",
                "--path",
                str(ROOT),
                str(scene.relative_to(ROOT)),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output_task = asyncio.create_task(process.communicate())
            await until(lambda: progress.exists() or process.returncode is not None)
            assert process.returncode is None, (await output_task)[0].decode()
            await until(lambda: progress.read_text() == "queued")
            await until(lambda: len(calls) == 1)
            release_first.set()
            await until(lambda: progress.read_text() == "disconnect")
            await until(lambda: len(calls) == 3)
            await sockets[0].close(code=1012, reason="deterministic reconnect")
            release_disconnected.set()
            stdout, _ = await asyncio.wait_for(output_task, 20)
            output = stdout.decode()
            assert process.returncode == 0, output
            assert MARKER in output, output
            assert "SCRIPT ERROR" not in output and "ERROR:" not in output, output
            assert len(sockets) == 2
            assert calls[0] == [{"role": "user", "content": "delayed A 雪"}]
            assert calls[1] == [{"role": "user", "content": "fail B"}]
            assert calls[2] == [
                {"role": "user", "content": "delayed A 雪"},
                {"role": "assistant", "content": "late A success 雪"},
                {"role": "user", "content": "disconnect pending"},
            ]
            # No archive, draft, prior response, or pending-task replay on reconnect.
            assert calls[3] == [{"role": "user", "content": "fresh context"}]
            print(output)
    finally:
        release_first.set()
        release_disconnected.set()
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        server.close()
