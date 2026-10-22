"""Run the paid supervisor paths with offline SDK methods and real Godot/Git.

These are test-only SDK responses, never acceptance artifacts. Production child
entrypoint, observation, lifecycle and runner choreography execute unchanged.
"""

import asyncio
import json
import os
from pathlib import Path
import shlex
import shutil
from types import SimpleNamespace
from uuid import uuid4

import pytest
from claude_agent_sdk import ClaudeSDKClient, AssistantMessage, TextBlock, SystemMessage
from claude_agent_sdk.types import ToolUseBlock, ToolResultBlock, UserMessage

from bridge.tests.test_domain_sdk import terminal
from scripts import m12_live as live


@pytest.mark.asyncio
@pytest.mark.parametrize("permission_mode", ["dontAsk", "bypassPermissions"])
async def test_live_choreography_typed_setup_start_extra_restart_isolation(
    tmp_path, monkeypatch, permission_mode
):
    if not shutil.which(os.environ.get("GODOT_BIN", "godot")):
        if os.environ.get("PLAZA_REQUIRE_GODOT"):
            pytest.fail("Godot is required")
        pytest.skip("Godot unavailable")

    def init(client, *, options, transport=None):
        client.options = options
        client._transport = transport or SimpleNamespace(
            _process=SimpleNamespace(returncode=None)
        )
        if transport is not None:
            transport.process = SimpleNamespace(returncode=None)

    async def connect(client):
        pass

    async def query(client, prompt):
        client.prompt = prompt

    async def receive(client):
        domain = bool(client.options.tools)
        session = uuid4().hex
        yield SystemMessage(
            subtype="init",
            data=dict(tools=list(client.options.tools or []), session_id=session),
        )
        if domain:
            command = json.loads(client.prompt)
            if "Command: " in command["task"]:
                tool_id = uuid4().hex
                yield AssistantMessage(
                    [ToolUseBlock(id=tool_id, name="Bash", input={})],
                    client.options.model,
                )
                child = await asyncio.create_subprocess_exec(
                    *shlex.split(command["task"].split("Command: ", 1)[1]),
                    cwd=client.options.cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(child.communicate(), 20)
                assert child.returncode == 0, stderr.decode()
                receipt = json.loads(stdout.decode().split("M12_RECEIPT ", 1)[1])
                yield UserMessage(
                    content=[
                        ToolResultBlock(
                            tool_use_id=tool_id, content=stdout.decode(), is_error=False
                        )
                    ]
                )
                answer = receipt["nonce"]
                text = json.dumps(
                    dict(
                        answer=answer,
                        memory_delta=dict(
                            summary=answer,
                            next_action="Read prior notes without rerunning completed work",
                        ),
                    )
                )
            else:
                import re

                match = re.search(r"m12-[a-f0-9]{32}", command["prior_project_notes"])
                text = json.dumps(dict(answer=match.group() if match else "isolated"))
        else:
            payload = json.loads(client.prompt.split("\n", 1)[1])
            content = payload["messages"][-1]["content"]
            try:
                proposal = json.loads(content)
            except ValueError:
                proposal = {}
            if "proposal_id" in proposal:
                text = json.dumps(
                    dict(
                        proposal_id=proposal["proposal_id"],
                        digest=proposal["digest"],
                        approved=True,
                        reason="Approved offline exact proposal",
                    )
                )
            else:
                text = "Independent extra acknowledges the player."
        yield AssistantMessage([TextBlock(text)], client.options.model)
        yield terminal(result=text, session_id=session)

    async def disconnect(client):
        transport = client._transport
        process = getattr(transport, "process", None) or transport._process
        process.returncode = 0

    for name, method in dict(
        __init__=init,
        connect=connect,
        query=query,
        receive_response=receive,
        disconnect=disconnect,
    ).items():
        monkeypatch.setattr(ClaudeSDKClient, name, method)
    # No production acceptance is installed. Offline-only methods never launch SDK transport.
    monkeypatch.setattr(
        "bridge.domain_sdk._verify_runtime", lambda mode: "/offline/claude"
    )
    for name in set(os.environ) - set(live.bridge_environment()):
        monkeypatch.delenv(name)
    original_spawn = live.Child.spawn

    async def spawn(command, log_path, *, env=None, cwd=None):
        if "--child" not in command:
            return await original_spawn(command, log_path, env=env, cwd=cwd)
        task = asyncio.create_task(
            live.bridge_child(command[3], command[5], command[7])
        )
        process = SimpleNamespace(pid=os.getpid(), returncode=None)

        async def join(seconds):
            await asyncio.wait_for(asyncio.shield(task), seconds)
            process.returncode = 0
            return 0

        return SimpleNamespace(process=process, forced=False, join=join)

    monkeypatch.setattr(live.Child, "spawn", spawn)
    project = tmp_path / "project-a"
    project.mkdir()
    (project / "PLAZA_AGENTS.md").write_text("Offline project guidance")
    report = dict(lifetimes=[])
    life = live.LiveLifetime(
        tmp_path / "initial", project, "a_initial", permission_mode=permission_mode
    )
    try:
        await life.start()
        await live.initial(life, report)
    finally:
        report["lifetimes"].append(await life.stop())
    report["initial"]["notes"] = live.post_close_notes(life)
    live._proof_wire(report["initial"]["wire"])
    live._proof_wire(live.sanitize_evidence(report)["initial"]["wire"])
    assert report["initial"]["start"]["query_count"] == 0
    assert report["initial"]["context"]["facts"]["domain_id"] == "core"
    life = live.LiveLifetime(
        tmp_path / "restart", project, "a_restart", permission_mode=permission_mode
    )
    try:
        await life.start()
        await live.readback(life, report, "a_restart")
    finally:
        await life.stop()
    from bridge.tests.test_workspace import repository

    (tmp_path / "isolation").mkdir()
    other = repository(tmp_path / "isolation")
    (other / "PLAZA_AGENTS.md").write_text("Independent project guidance")
    life = live.LiveLifetime(
        tmp_path / "other", other, "b_isolation", permission_mode=permission_mode
    )
    try:
        await life.start()
        await live.readback(life, report, "b_isolation")
    finally:
        await life.stop()
    assert report["isolation"]["start"]["query_count"] == 0
    for name in ("initial", "restart", "isolation"):
        live._proof_admission(report[name], permission_mode)
