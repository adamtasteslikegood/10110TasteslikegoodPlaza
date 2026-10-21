"""Physical production Main/native controls → real bridge → fake SDK → Git/memory."""

import asyncio
import json
import os
from pathlib import Path
import re
import shutil

import pytest

from bridge.tests.m12_harness import (
    Lifetime,
    Provider,
    baseline,
    identity,
    until,
    restart_and_isolation,
)
from bridge.tests.test_workspace import git
from scripts.m12_stages import StageValidator, STAGES

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_empty_project_physical_background_npc_and_rendered_replay(
    tmp_path, monkeypatch, offline_clients
):
    godot = shutil.which(os.environ.get("GODOT_BIN", "godot"))
    if not godot:
        if os.environ.get("PLAZA_REQUIRE_GODOT"):
            pytest.fail("Godot is required for M12 integration")
        pytest.skip("Godot unavailable; required in the Godot CI job")
    root = tmp_path / "empty-project"
    root.mkdir()
    control = tmp_path / "control"
    control.mkdir()
    reviews = []

    async def review(proposal):
        reviews.append(proposal)
        return dict(
            proposal_id=proposal.proposal_id,
            digest=proposal.digest,
            approved=True,
            reason="Approved deterministic seed",
        )

    conversation, _, _ = offline_clients
    conversation.reply.return_value = "unrelated core NPC reply gull"
    provider = Provider()
    process = output_task = None
    async with Lifetime(tmp_path, root, monkeypatch, provider, reviewer=review) as life:
        validator = StageValidator(life.run_id, "godot")
        assert life.service.snapshot()["stage"] == "needs_architect"
        scene = ROOT / "tests/godot_domain_integration.tscn"
        assert scene.is_file(), "complete physical M12 integration scene must exist"
        env = {
            **os.environ,
            "PLAZA_TEST_BRIDGE_URL": life.url,
            "PLAZA_M12_CONTROL": str(control),
            "PLAZA_M12_RUN_ID": life.run_id,
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
        try:
            for seq, stage in enumerate(STAGES, 1):
                path = control / f"{seq:02d}-{stage}.json"
                await until(lambda: path.exists() or process.returncode is not None)
                assert path.exists(), (await output_task)[0].decode()
                receipt = validator.accept(json.loads(path.read_text()))
                payload = receipt["payload"]
                command = next(
                    c for c in life.commands if c["request_id"] == payload["request_id"]
                )
                wire = [
                    p
                    for p in life.emitted
                    if p.get("request_id") == payload["request_id"]
                ]
                assert wire
                if stage == "referral_rendered":
                    assert command["agent_id"] == "security-auditor"
                    assert wire[-1]["output"] == payload["assistant"]
                    assert not reviews and not (root / ".git").exists()
                    assert "Chief Architect" in payload["assistant"]
                elif stage == "chief_ready":
                    assert command["agent_id"] == "systems-architect"
                    assert wire[-1]["output"] == payload["assistant"]
                    assert len(reviews) == 1
                    snapshot = life.service.snapshot()
                    assert snapshot["stage"] == "ready"
                    assert snapshot["architect_decision"]["approved"]
                    assert snapshot["project_id"] == payload["project_id"]
                    assert snapshot["workspace_id"] == payload["workspace_id"]
                    assert git(root, "branch", "--show-current") == "main"
                    work = life.service.require_workspace()
                    assert work.worktree_path != root and work.branch.startswith(
                        "plaza/workspace-"
                    )
                    assert git(root, "rev-parse", "HEAD") == work.initial_commit
                    assert (
                        git(work.worktree_path, "branch", "--show-current")
                        == work.branch
                    )
                    notes = work.common_git_dir / "plaza/session-memory"
                    assert len(list(notes.glob("*.md"))) == 3
                    assert (
                        "Approved deterministic seed"
                        in life.service.require_memory().load().progress
                    )
                    (root / "dirty-source.txt").write_text("source-only sentinel")
                    source_before = baseline(root)
                    runtime_before = (life.runtime / "sentinel").read_bytes()
                    assert life.marker.exists()
                elif stage == "domain_running":
                    assert command["type"] == "domain_query"
                    assert any(p["type"] == "domain_accepted" for p in wire)
                    await until(
                        lambda: provider.clients
                        and provider.clients[0].receiving.is_set()
                    )
                    assert len(provider.queries) == 1
                    assert provider.clients[0].options.cwd == str(work.worktree_path)
                elif stage == "background_ack":
                    assert command["type"] == "background_domain"
                    assert wire[-1]["type"] == "domain_state"
                    assert wire[-1]["domain_session_id"] == payload["domain_session_id"]
                    assert not provider.writes
                    session = life.server.domains._sessions["engineering"][0]
                    assert session.snapshot()["state"] == "background"
                    assert session.snapshot()["execution_state"] == "running"
                    background_time = receipt["received_monotonic"]
                elif stage == "npc_rendered":
                    assert wire[-1]["output"] == payload["assistant"]
                    assert validator.may_release and not provider.writes
                    assert payload["agent_id"] == "security-auditor"
                    assert payload["assistant"] == "unrelated core NPC reply gull"
                    assert conversation.reply.call_args.kwargs["messages"] == [
                        {"role": "user", "content": "unrelated core conversation"}
                    ]
                    npc_time = receipt["received_monotonic"]
                    provider.release.set()
                elif stage == "domain_rendered":
                    assert command["type"] == "resume"
                    assert wire[-1]["type"] == "resume_complete"
                    refocus = next(
                        c
                        for c in life.commands
                        if c["request_id"] == payload["refocus_request_id"]
                    )
                    assert refocus["type"] == "refocus_domain"
                    terminal = session._entries[0]
                    godot_identity = identity(payload)
                    assert godot_identity == identity(terminal)
                    assert payload["output"] == terminal["output"]
                    plain = await life.socket()
                    await plain.send("domain_status", "plain-status")
                    assert (await plain.reply("plain-status"))[
                        "domain_session_id"
                    ] == terminal["domain_session_id"]
                    replayed = await plain.replay(terminal["domain_session_id"])
                    assert (
                        replayed == [terminal]
                        and identity(replayed[0]) == godot_identity
                    )
                    assert (
                        len(provider.queries)
                        == len(provider.writes)
                        == len(session._entries)
                        == payload["rendered_unique_results"]
                        == 1
                    )
                    assert (
                        provider.writes[0][1] > background_time
                        and provider.writes[0][1] > npc_time
                    )
                    assert provider.writes[0][0].read_text() == terminal["output"]
                elif stage == "stop_ack":
                    assert (
                        command["type"] == "deactivate_domain"
                        and wire[-1]["state"] == "inactive"
                    )
                    life.assert_released()
                    assert baseline(root) == source_before
                    assert (life.runtime / "sentinel").read_bytes() == runtime_before
                    memory_before = life.service.require_memory().load()
                    result_bytes = provider.writes[0][0].read_bytes()
                # Barrier permits independent checks before the scene advances.
                (control / f"ack-{seq}").write_text(life.run_id)
            validator.finish()
            stdout, _ = await asyncio.wait_for(output_task, 15)
            output = stdout.decode()
            assert process.returncode == 0, output
            assert re.search(
                r"^godot_domain_integration: OK — [1-9][0-9]* checks passed\.$",
                output,
                re.M,
            ), output
            assert "SCRIPT ERROR" not in output and "ERROR:" not in output, output
            print(output)
        except BaseException:
            if process.returncode is None:
                process.kill()
            print((await output_task)[0].decode())
            raise
        finally:
            provider.release.set()
            if process.returncode is None:
                process.kill()
            await output_task
    life.assert_closed()
    await restart_and_isolation(
        tmp_path, root, monkeypatch, work, memory_before, result_bytes
    )
