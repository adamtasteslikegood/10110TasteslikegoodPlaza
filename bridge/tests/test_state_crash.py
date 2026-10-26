"""Real process deaths across initialization and production Run commit boundaries."""

import asyncio
from dataclasses import replace
import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest

from bridge.config import default_config
from bridge.project_service import ProjectService
from bridge.server import BridgeServer
from bridge.project_memory import ProjectMemoryStore, TurnIntent
from bridge.readiness import owned_io
from bridge.workspace import inspect_project
from bridge.tests.test_workspace import repository

BOUNDARIES = (
    "initializing_manifest",
    "image_before_ready",
    "notes_pending_before_accept",
    "accepted_before_dispatch",
    "dispatch_before_sdk",
    "notes_complete_before_terminal",
    "terminal_commit_before_delivery",
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary,notes_unavailable,reopen_backend",
    [(b, False, "sqlite") for b in BOUNDARIES]
    + [
        ("accepted_before_dispatch", True, "sqlite"),
        ("accepted_before_dispatch", False, "memory"),
    ],
)
async def test_killed_server_recovers_once_without_tools(
    tmp_path, monkeypatch, boundary, notes_unavailable, reopen_backend
):
    root = repository(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    signal = tmp_path / "boundary.json"
    # Child environment never inherits credentials, including a nonstandard key name.
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(
            part in k.upper()
            for part in ("TOKEN", "KEY", "SECRET", "CREDENTIAL", "ANTHROPIC", "OPENAI")
        )
    }
    with (tmp_path / "child.log").open("w+") as log:
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "bridge.tests.state_crash_child",
                str(root),
                str(runtime),
                boundary,
                str(signal),
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            async with asyncio.timeout(15):
                while not signal.exists() and child.poll() is None:
                    await asyncio.sleep(0.01)
            if not signal.exists():
                log.seek(0)
                pytest.fail(log.read())
            reached = json.loads(signal.read_text())
        finally:
            child.kill()
            await asyncio.to_thread(child.wait)
    assert child.returncode < 0
    if notes_unavailable:
        (root / ".git/plaza/session-memory/TODO.md").write_text("unavailable notes")
    protected = (
        boundary
        in {
            "accepted_before_dispatch",
            "dispatch_before_sdk",
            "notes_complete_before_terminal",
        }
        and not notes_unavailable
    )

    def turn_items(memory):
        with memory._operation() as (check, _):
            state, _, _, _ = memory._read(check)
            return {i["turn_id"]: i for i in state["items"] if i["kind"] == "turn"}

    original_notes = None
    if protected:
        original_notes = await owned_io(
            turn_items, ProjectMemoryStore(inspect_project(root))
        )
    sqlite_path = root / ".git/plaza/application-state/state.sqlite3"
    original_sqlite = sqlite_path.read_bytes() if reopen_backend == "memory" else None

    def forbidden(*args, **kwargs):
        raise AssertionError("Recovery may not construct an SDK owner")

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", forbidden)
    saved = None
    for _ in range(2):
        config = replace(
            default_config(),
            workspace_root_dir=root,
            domain_state_backend=reopen_backend,
        )
        service = ProjectService(
            config, runtime_root=runtime, owner_run_id=str(uuid4())
        )
        server = BridgeServer(config=config, project_service=service)
        await service.start()
        await service._bootstrap_task
        await server._ensure_application_state()
        try:
            if boundary in BOUNDARIES[:2]:
                assert (
                    server.application_state_status()["error_type"]
                    == "state_store_invalid"
                )
                continue
            assert server.application_state is not None
            view = server.application_state.snapshot()
            if protected:
                turn_id = (
                    view.requests[0].turn_id
                    if view is not None
                    else next(iter(original_notes))
                )
                assert (await owned_io(turn_items, service.require_memory()))[
                    turn_id
                ] == original_notes[turn_id]
                extra = TurnIntent(
                    str(uuid4()),
                    str(uuid4()),
                    service.owner_run_id,
                    "story-weaver",
                    None,
                    None,
                    "Independent legacy extra",
                )
                await service.prepare_memory_turn(extra)
                assert (
                    await owned_io(
                        service.require_memory().finish_turn,
                        extra.turn_id,
                        outcome="success",
                        output="extra done",
                        delta=None,
                    )
                ).saved
                assert (await owned_io(turn_items, service.require_memory()))[
                    turn_id
                ] == original_notes[turn_id]
            if reopen_backend == "memory":
                assert view is None
                assert server.domains.snapshot("engineering")["saved_sessions"] == []
                assert sqlite_path.read_bytes() == original_sqlite
                assert list((root / ".git/worktrees").glob("*/plaza-unclean.json"))
                continue
            assert view is not None and all(e.stopped_at for e in view.executions)
            if boundary == "notes_pending_before_accept":
                assert not view.requests and not view.terminals
            else:
                assert len(view.terminals) == 1 and view.terminals[0].output_id == 1
                packet = view.terminals[0].packet
                if boundary == "terminal_commit_before_delivery":
                    assert packet == reached["packet"]
                else:
                    assert packet["reason"] == (
                        "not_executed"
                        if boundary == "accepted_before_dispatch"
                        else "interrupted"
                    )
                if saved is not None:
                    assert packet == saved
                saved = packet
            assert reached["calls"] == (
                ["execute"] if boundary in BOUNDARIES[-2:] else []
            )
            # A free OS lock does not erase the crashed SDK's unclean marker.
            workspace = service._workspaces.get("engineering")
            if notes_unavailable:
                assert service.snapshot()["stage"] == "failed"
                assert service.capacity_snapshot()["available"] is True
                assert list((root / ".git/worktrees").glob("*/plaza-unclean.json"))
            else:
                assert workspace is not None
                assert (workspace.git_dir / "plaza-unclean.json").exists()
            if boundary == "accepted_before_dispatch" and not notes_unavailable:
                markers = {
                    path: path.read_bytes()
                    for path in (root / ".git/worktrees").glob("*/plaza-unclean.json")
                }
                current = server.domains.snapshot("engineering")
                assert not server.domains._sessions
                reply = await server.dispatch(
                    dict(
                        type="end_domain_session",
                        protocol_version=2,
                        request_id=str(uuid4()),
                        domain_id="engineering",
                        domain_session_id=current["domain_session_id"],
                        expected_domain_revision=current["domain_revision"],
                    )
                )
                assert reply[-1]["error_type"] == "cleanup_failed"
                assert server.application_state.snapshot() == view
                assert (
                    server.domains.snapshot("engineering")["domain_session_id"]
                    == current["domain_session_id"]
                )
                assert all(s.ended_at is None for s in view.sessions)
                assert {p: p.read_bytes() for p in markers} == markers
                assert not service._domain_tasks
        finally:
            await server._shutdown()
