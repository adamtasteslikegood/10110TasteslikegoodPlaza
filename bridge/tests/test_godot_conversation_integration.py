"""Provider-free acceptance: real Godot HUD/client and real Python bridge."""

import asyncio
import json
import os
from pathlib import Path
import shutil
from unittest.mock import AsyncMock, MagicMock

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
import pytest
import websockets

from bridge.server import BridgeServer

ROOT = Path(__file__).resolve().parents[2]
MARKER = "godot_bridge_integration: OK — 38 checks passed."


@pytest.mark.asyncio
async def test_delayed_replies_failure_and_fresh_reconnect(
    tmp_path, runtime_config, offline_clients, monkeypatch
):
    godot = shutil.which(os.environ.get("GODOT_BIN", "godot"))
    if not godot:
        if os.environ.get("PLAZA_REQUIRE_GODOT"):
            pytest.fail("Godot is required for this integration gate")
        pytest.skip("Godot unavailable; the Godot CI job requires this integration")
    scene = ROOT / "tests/godot_bridge_integration.tscn"
    assert scene.is_file(), "real client/bridge integration scene must exist"
    progress = tmp_path / "progress"
    release_first = asyncio.Event()
    cancelled = asyncio.Event()
    drained = asyncio.Event()
    calls = []
    clients = []
    disconnected = []
    sockets = []
    handlers_done = []
    api = MagicMock(side_effect=AssertionError("default SDK must never use API"))
    monkeypatch.setattr("bridge.conversation_api.AsyncAnthropic", api)

    def factory(*, options):
        client = AsyncMock()
        index = len(clients)
        clients.append(client)

        async def receive():
            messages = json.loads(client.query.call_args.args[0].split("\n", 1)[1])[
                "messages"
            ]
            calls.append(messages)
            task = messages[-1]["content"]
            if task == "delayed A 雪":
                await asyncio.wait_for(release_first.wait(), 15)
                output = "late A success 雪"
            elif task == "fail B":
                raise RuntimeError("B independent failure")
            elif task == "disconnect pending":
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            elif task == "fresh context":
                assert cancelled.is_set() and drained.is_set()
                assert sockets[0] in handlers_done
                output = "fresh reply " + "雪" * 1000
            else:
                raise AssertionError(f"unexpected submitted task: {task!r}")
            yield AssistantMessage(
                content=[TextBlock(text=output)], model=options.model
            )
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id=f"observed-integration-{index}",
                result=output,
            )

        async def disconnect():
            await asyncio.sleep(0)  # Cleanup must be awaited, including cancellation.
            disconnected.append(client)
            if index == 2:
                assert cancelled.is_set()
                drained.set()

        client.receive_response = receive
        client.disconnect.side_effect = disconnect
        return client

    monkeypatch.setattr("bridge.conversation_sdk.ClaudeSDKClient", factory)
    server = BridgeServer(config=runtime_config)

    async def handle(socket):
        sockets.append(socket)
        try:
            await server._handle_connection(socket)
        finally:
            handlers_done.append(socket)

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
            await until(lambda: progress.read_text() == "busy")
            await until(lambda: len(calls) == 1)
            release_first.set()
            await until(lambda: progress.read_text() == "disconnect")
            await until(lambda: len(calls) == 3)
            await sockets[0].close(code=1012, reason="deterministic reconnect")
            await asyncio.wait_for(drained.wait(), 5)
            await until(lambda: sockets[0] in handlers_done)
            assert cancelled.is_set()
            stdout, _ = await asyncio.wait_for(output_task, 20)
            output = stdout.decode()
            assert process.returncode == 0, output
            assert MARKER in output, output
            assert "SCRIPT ERROR" not in output and "ERROR:" not in output, output
            assert len(sockets) == 2
            assert len(clients) == len(disconnected) == len(calls) == 4
            for client in clients:
                client.connect.assert_awaited_once()
                client.query.assert_awaited_once()
                client.disconnect.assert_awaited_once()
            api.assert_not_called()
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
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        server.close()
