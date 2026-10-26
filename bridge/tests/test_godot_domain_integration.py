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
@pytest.mark.parametrize(
    "live_mode,delay_return_refocus",
    [(False, False), (True, False), (False, True)],
    ids=["normal", "live-shaped", "delayed-return"],
)
async def test_empty_project_physical_background_npc_and_rendered_replay(
    tmp_path, monkeypatch, offline_clients, live_mode, delay_return_refocus
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
    async with Lifetime(
        tmp_path, root, monkeypatch, provider, reviewer=review, domain_id="core"
    ) as life:
        release_return = asyncio.Event()
        held_refocus = {}
        dispatch = life.server.dispatch

        async def gate_return(command, *args, **kwargs):
            if (
                delay_return_refocus
                and command.get("type") == "refocus_domain"
                and (control / "05-npc_rendered.json").exists()
            ):
                assert not held_refocus, "only the final return Refocus is held"
                held_refocus.update(command)
                await asyncio.wait_for(release_return.wait(), 5)
            return await dispatch(command, *args, **kwargs)

        monkeypatch.setattr(life.server, "dispatch", gate_return)
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
        if live_mode:
            env["PLAZA_M12_LIVE"] = "1"
            (control / "task.txt").write_text("execute integration sentinel")
        if delay_return_refocus:
            env["PLAZA_M12_TEST_RETURN_GATE"] = "1"
        else:
            env.pop("PLAZA_M12_TEST_RETURN_GATE", None)
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
        generation = ""
        try:
            for seq, stage in enumerate(STAGES, 1):
                path = control / f"{seq:02d}-{stage}.json"
                if stage == "domain_rendered" and delay_return_refocus:
                    marker = control / "return-refocus-waiting.json"
                    await until(
                        lambda: (marker.exists() and held_refocus)
                        or process.returncode is not None
                    )
                    assert marker.exists() and held_refocus, (await output_task)[
                        0
                    ].decode()
                    waiting = json.loads(marker.read_text())
                    assert waiting["run_id"] == life.run_id
                    assert waiting["refocus_request_id"] == held_refocus["request_id"]
                    assert (
                        waiting["domain_session_id"]
                        == held_refocus["domain_session_id"]
                        == generation
                    )
                    assert any(
                        p.get("request_id") == waiting["previous_resume_request_id"]
                        and p.get("type") == "resume_complete"
                        and p.get("domain_session_id") == generation
                        for p in life.emitted
                    ), "an earlier replay must already be complete while fresh Refocus waits"
                    print("CONTROLLED_RETURN " + json.dumps(waiting, sort_keys=True))
                    release_return.set()
                    await until(
                        lambda: any(
                            c["request_id"] == held_refocus["request_id"]
                            for c in life.commands
                        )
                    )
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
                    assert command["type"] == "project_setup"
                    assert wire[-1]["output"] == payload["assistant"]
                    assert not reviews and not (root / ".git").exists()
                    assert "Chief Architect" in payload["assistant"]
                elif stage == "chief_ready":
                    assert command["agent_id"] == "systems-architect"
                    assert command["type"] == "project_setup"
                    assert wire[-1]["output"] == payload["assistant"]
                    assert len(reviews) == 1
                    snapshot = life.service.snapshot()
                    assert snapshot["stage"] == "ready"
                    assert snapshot["architect_decision"]["approved"]
                    assert snapshot["project_id"] == payload["project_id"]
                    assert snapshot["workspace_id"] is None
                    assert not provider.queries
                    assert git(root, "branch", "--show-current") == "main"
                    notes = Path(snapshot["memory"]["path"])
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
                    generation = payload["domain_session_id"]
                    snapshot = life.service.workspace_snapshot("core")
                    assert snapshot["workspace_id"] == payload["workspace_id"]
                    work = life.service.require_workspace("core")
                    assert work.worktree_path != root and work.branch.startswith(
                        "plaza/workspace-"
                    )
                    assert git(root, "rev-parse", "HEAD") == work.initial_commit
                    assert (
                        git(work.worktree_path, "branch", "--show-current")
                        == work.branch
                    )
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
                    session = life.server.domains._sessions["core"][0]
                    assert session.snapshot()["state"] == "background"
                    assert session.snapshot()["execution_state"] == "running"
                    background_time = receipt["received_monotonic"]
                elif stage == "npc_rendered":
                    assert wire[-1]["output"] == payload["assistant"]
                    assert validator.may_release and not provider.writes
                    assert payload["agent_id"] == "fixture-extra-a"
                    assert payload["assistant"] == "unrelated core NPC reply gull"
                    assert conversation.reply.call_args.kwargs["messages"] == [
                        {
                            "role": "user",
                            "content": (
                                "In one short sentence, acknowledge this unrelated core conversation."
                                if live_mode
                                else "unrelated core conversation"
                            ),
                        }
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
                    assert life.commands.index(refocus) < life.commands.index(
                        command
                    ), "rendered replay must use a fresh Resume admitted after its Refocus"
                    assert (
                        refocus["domain_session_id"]
                        == command["domain_session_id"]
                        == payload["domain_session_id"]
                    )
                    refocus_acks = [
                        p
                        for p in life.emitted
                        if p.get("type") == "domain_state"
                        and p.get("request_id") == refocus["request_id"]
                        and p.get("domain_session_id") == payload["domain_session_id"]
                    ]
                    assert (
                        refocus_acks
                    ), "rendered replay requires its exact Refocus ack"
                    assert life.emitted.index(refocus_acks[-1]) < life.emitted.index(
                        wire[-1]
                    ), "exact Refocus ack must precede the selected Resume terminal"
                    if delay_return_refocus:
                        print(
                            "CORRELATED_RETURN "
                            + json.dumps(
                                {
                                    "refocus_request_id": refocus["request_id"],
                                    "resume_request_id": command["request_id"],
                                    "domain_session_id": payload["domain_session_id"],
                                    "refocus_command_index": life.commands.index(
                                        refocus
                                    ),
                                    "resume_command_index": life.commands.index(
                                        command
                                    ),
                                    "refocus_ack_index": life.emitted.index(
                                        refocus_acks[-1]
                                    ),
                                    "resume_terminal_index": life.emitted.index(
                                        wire[-1]
                                    ),
                                },
                                sort_keys=True,
                            )
                        )
                    terminal = session.replay(0)[0]
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
                        == len(session.replay(0)) - 1
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
            if live_mode:
                assert output.count("godot_domain_live_visible_npc: OK") == 1, output
            print(output)
        except BaseException:
            if process.returncode is None:
                process.kill()
            print((await output_task)[0].decode())
            raise
        finally:
            release_return.set()
            provider.release.set()
            if process.returncode is None:
                process.kill()
            await output_task
    life.assert_closed()
    await restart_and_isolation(
        tmp_path, root, monkeypatch, work, memory_before, result_bytes
    )
