"""Fresh Godot processes discover real SQLite history without starting work."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from bridge.tests.m12_harness import Lifetime, Provider, until
from bridge.tests.test_workspace import repository

ROOT = Path(__file__).resolve().parents[2]


async def game(
    url, *, expected="Readback from prior notes: isolated", status_first=False
):
    godot = shutil.which(os.environ.get("GODOT_BIN", "godot"))
    if not godot:
        if os.environ.get("PLAZA_REQUIRE_GODOT"):
            pytest.fail("Godot is required")
        pytest.skip("Godot unavailable")
    process = await asyncio.create_subprocess_exec(
        godot,
        "--headless",
        "--path",
        str(ROOT),
        "tests/godot_history_reopen.tscn",
        env={
            **os.environ,
            "PLAZA_TEST_BRIDGE_URL": url,
            "PLAZA_HISTORY_EXPECTED": expected,
            "PLAZA_HISTORY_STATUS_FIRST": "1" if status_first else "0",
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 20)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    text = output.decode()
    assert (
        process.returncode == 0 and "SCRIPT ERROR" not in text and "ERROR:" not in text
    ), text
    rows = [
        line.removeprefix("HISTORY_REOPEN ")
        for line in text.splitlines()
        if line.startswith("HISTORY_REOPEN ")
    ]
    assert len(rows) == 1, text
    return json.loads(rows[0])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ended,delayed_bootstrap",
    [(False, False), (True, False), (False, True)],
    ids=["open-application-new-execution", "ended-only", "preparing-to-ready"],
)
async def test_fresh_game_reopens_committed_history_without_start_or_query(
    tmp_path, monkeypatch, offline_clients, ended, delayed_bootstrap
):
    root = repository(tmp_path, "saved-project")
    first = tmp_path / "first"
    first.mkdir()
    provider = Provider()
    provider.release.set()
    async with Lifetime(first, root, monkeypatch, provider, domain_id="core") as life:
        socket = await life.socket()
        application = await socket.start()
        accepted = await socket.run(application, task="read previous notes")
        terminal = await socket.reply("run", type="domain_result")
        assert terminal["output_id"] == "1"
        await socket.send("deactivate_domain", "stop", application)
        await socket.reply("stop", type="domain_state")
        if ended:
            await socket.send("end_domain_session", "end", application)
            assert (await socket.reply("end", type="domain_state"))[
                "domain_session_id"
            ] is None
        before = len(life.commands)
        initial = await game(life.url)
        assert not any(
            c["type"] in {"activate_domain", "domain_query"}
            for c in life.commands[before:]
        )
        assert initial["selected_session_id"] == application
        assert initial["output_ids"] == ["1"] and len(provider.queries) == 1
    second = tmp_path / "second"
    second.mkdir()
    restored = Provider()
    life = Lifetime(
        second,
        root,
        monkeypatch,
        restored,
        domain_id="core",
        wait_bootstrap=not delayed_bootstrap,
    )
    release = asyncio.Event()
    if delayed_bootstrap:
        original_bootstrap = life.service._bootstrap

        async def held_bootstrap():
            await release.wait()
            await original_bootstrap()

        monkeypatch.setattr(life.service, "_bootstrap", held_bootstrap)
    async with life:
        execution = ""
        if not ended and not delayed_bootstrap:
            # An explicit other client starts B before this fresh game connects.
            socket = await life.socket()
            assert await socket.start("explicit-B") == application
            execution = life.server.domains.snapshot("core")["execution_id"]
            assert execution != accepted["execution_id"]
        before = len(life.commands)
        if delayed_bootstrap:
            observer = asyncio.create_task(game(life.url))
            try:
                await until(
                    lambda: any(
                        p.get("type") == "agent_status"
                        and p.get("execution_kind") == "working"
                        for p in life.emitted
                    )
                )
                assert life.service.snapshot()["stage"] == "preparing"
                assert not restored.clients and not restored.queries
                release.set()
                await life.service._bootstrap_task
                reopened = await observer
            finally:
                release.set()
                if not observer.done():
                    observer.cancel()
                    await asyncio.gather(observer, return_exceptions=True)
        else:
            reopened = await game(life.url)
        assert not any(
            c["type"] in {"activate_domain", "domain_query"}
            for c in life.commands[before:]
        )
        assert reopened["selected_session_id"] == application
        assert reopened["domain_session_id"] == ("" if ended else application)
        assert reopened["execution_id"] == execution
        assert reopened["result_executions"] == [terminal["execution_id"]]
        assert (
            reopened["output_ids"] == ["1"]
            and reopened["selected_received_cursor"] == "1"
        )
        assert reopened["read_only"] is ended
        assert not reopened["focus"]
        assert not restored.queries
        if ended:
            assert (
                not restored.clients
                and reopened["run_disabled"]
                and reopened["end_disabled"]
            )
        elif delayed_bootstrap:
            assert not restored.clients and reopened["state"] == "inactive"
            assert reopened["run_disabled"] and not reopened["end_disabled"]
        else:
            assert len(restored.clients) == 1 and reopened["state"] == "active"
            assert not reopened["run_disabled"] and not reopened["end_disabled"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial_backend,advanced_memory,final_backend",
    [
        ("sqlite", False, "sqlite"),
        ("memory", False, "memory"),
        ("memory", True, "memory"),
        ("memory", False, "sqlite"),
    ],
    ids=[
        "sqlite-memory-sqlite",
        "memory-reset-zero",
        "memory-reset-advanced",
        "memory-new-sqlite",
    ],
)
async def test_kept_game_survives_backend_and_memory_process_discontinuities(
    tmp_path,
    monkeypatch,
    offline_clients,
    initial_backend,
    advanced_memory,
    final_backend,
):
    root = repository(tmp_path, "kept-project")
    control = tmp_path / "control"
    control.mkdir()
    godot = shutil.which(os.environ.get("GODOT_BIN", "godot"))
    if not godot:
        pytest.skip("Godot unavailable")
    process = await asyncio.create_subprocess_exec(
        godot,
        "--headless",
        "--path",
        str(ROOT),
        "tests/godot_history_continuity.tscn",
        env={**os.environ, "PLAZA_CONTINUITY_CONTROL": str(control)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output_task = asyncio.create_task(process.communicate())

    async def step(life, number, cursor):
        observer_socket = await life.socket()
        await observer_socket.send("domain_status", f"trusted-state-{number}")
        current = await observer_socket.reply(
            f"trusted-state-{number}", type="domain_state"
        )
        instruction = dict(
            url=life.url,
            revision=current["domain_revision"],
            application=current["domain_session_id"] or "",
            continuity_id=current["state_store"].get("continuity_id"),
            cursor=cursor,
        )
        temporary = control / f"step-{number}.json.tmp"
        temporary.write_text(json.dumps(instruction))
        temporary.replace(control / f"step-{number}.json")
        receipt = control / f"observed-{number}.json"
        await until(
            lambda: receipt.exists() or process.returncode is not None, timeout=15
        )
        assert receipt.exists(), (await output_task)[0].decode()
        return json.loads(receipt.read_text())

    try:
        first = tmp_path / "first-kept"
        first.mkdir()
        provider = Provider()
        provider.release.set()
        async with Lifetime(
            first,
            root,
            monkeypatch,
            provider,
            domain_id="core",
            state_backend=initial_backend,
        ) as life:
            socket = await life.socket()
            application = await socket.start()
            await socket.run(application, task="read previous notes")
            await socket.reply("run", type="domain_result")
            await socket.send("deactivate_domain", "stop", application)
            await socket.reply("stop", type="domain_state")
            if initial_backend == "sqlite":
                await socket.send("end_domain_session", "end", application)
                await socket.reply("end", type="domain_state")
            before = len(life.commands)
            initial = await step(life, 1, "1")
            transient = await step(life, 2, "1")
            assert (
                transient["snapshot"]["state_store"]
                == initial["snapshot"]["state_store"]
            )
            assert (
                transient["snapshot"]["domain_revision"]
                == initial["snapshot"]["domain_revision"]
            )
            assert (
                transient["snapshot"]["unsaved_results"][0]["output"]
                == "unsaved continuity text"
            )
            assert not transient["focus"]
            assert not any(
                c["type"] in {"activate_domain", "domain_query"}
                for c in life.commands[before:]
            )
            assert len(provider.queries) == 1
        second = tmp_path / "second-kept"
        second.mkdir()
        provider = Provider()
        async with Lifetime(
            second,
            root,
            monkeypatch,
            provider,
            domain_id="core",
            state_backend="memory",
        ) as life:
            if advanced_memory:
                seed = await life.socket()
                for turn in range(2):
                    generation = await seed.start(f"other-start-{turn}")
                    await seed.send(
                        "deactivate_domain", f"other-stop-{turn}", generation
                    )
                    await seed.reply(f"other-stop-{turn}", type="domain_state")
            before_observation = len(life.commands)
            client_count = len(provider.clients)
            reset = await step(life, 3, "0")
            assert reset["snapshot"]["domain_revision"] == (
                "4" if advanced_memory else "0"
            )
            assert (
                not reset["snapshot"]["results"]
                and not reset["snapshot"]["unsaved_results"]
            )
            assert (
                reset["start_enabled"]
                and len(provider.clients) == client_count
                and not provider.queries
            )
            await asyncio.sleep(0.1)
            assert len(life.commands) - before_observation <= 7
            assert not any(
                c["type"] in {"activate_domain", "domain_query"}
                for c in life.commands[before_observation:]
            )
        third = tmp_path / "third-kept"
        third.mkdir()
        provider = Provider()
        async with Lifetime(
            third,
            root,
            monkeypatch,
            provider,
            domain_id="core",
            state_backend=final_backend,
        ) as life:
            restored = await step(
                life,
                4,
                (
                    "1"
                    if final_backend == "sqlite" and initial_backend == "sqlite"
                    else "0"
                ),
            )
            assert (
                restored["start_enabled"]
                and not provider.clients
                and not provider.queries
            )
            assert not restored["focus"]
            assert len(life.commands) <= 9
            if final_backend == "sqlite" and initial_backend == "sqlite":
                assert restored["snapshot"]["results"][0]["output_id"] == "1"
                assert restored["snapshot"]["domain_revision"] == "3"
            else:
                assert restored["snapshot"]["domain_revision"] == "0"
                if final_backend == "memory":
                    assert (
                        restored["snapshot"]["state_store"]["continuity_id"]
                        != reset["snapshot"]["state_store"]["continuity_id"]
                    )
            (control / "explicit-start").write_text("explicit user action")
            await until(
                lambda: (control / "started.json").exists()
                or process.returncode is not None
            )
            assert (control / "started.json").exists(), (await output_task)[0].decode()
            starts = [c for c in life.commands if c["type"] == "activate_domain"]
            assert (
                len(starts) == 1
                and starts[0]["expected_domain_revision"]
                == restored["snapshot"]["domain_revision"]
            )
            assert len(provider.clients) == 1 and not provider.queries
            output, _ = await asyncio.wait_for(output_task, 5)
            assert (
                process.returncode == 0 and b"godot_history_continuity: OK" in output
            ), output.decode()
    finally:
        if process.returncode is None:
            process.kill()
        await output_task


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["lower-B", "higher-B", "same-A"])
async def test_kept_game_preserves_cache_owner_through_unavailable_storage(
    tmp_path, monkeypatch, offline_clients, replacement
):
    """Real server/client, with a disposable SQLite repository-owner test seam."""
    from uuid import uuid4
    from bridge.application_state import StateCommand
    from bridge.state_coordinator import StateCoordinator, LazySQLiteStateRepository

    root = repository(tmp_path, "unavailable-project")
    control = tmp_path / "unavailable-control"
    control.mkdir()
    godot = shutil.which(os.environ.get("GODOT_BIN", "godot"))
    if not godot:
        if os.environ.get("PLAZA_REQUIRE_GODOT"):
            pytest.fail("Godot is required")
        pytest.skip("Godot unavailable")
    process = await asyncio.create_subprocess_exec(
        godot,
        "--headless",
        "--path",
        str(ROOT),
        "tests/godot_history_continuity.tscn",
        env={**os.environ, "PLAZA_CONTINUITY_CONTROL": str(control)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output_task = asyncio.create_task(process.communicate())

    async def step(life, number, cursor, *, retained=None):
        observer = await life.socket()
        await observer.send("domain_status", f"owner-observation-{number}")
        current = await observer.reply(
            f"owner-observation-{number}", type="domain_state"
        )
        expected = retained or current
        instruction = dict(
            url=life.url,
            revision=expected["domain_revision"],
            application=expected["domain_session_id"] or "",
            continuity_id=current["state_store"]["continuity_id"],
            cursor=cursor,
        )
        temporary = control / f"step-{number}.json.tmp"
        temporary.write_text(json.dumps(instruction))
        temporary.replace(control / f"step-{number}.json")
        receipt = control / f"observed-{number}.json"
        await until(
            lambda: receipt.exists() or process.returncode is not None, timeout=15
        )
        assert receipt.exists(), (await output_task)[0].decode()
        return json.loads(receipt.read_text()), current

    try:
        first = tmp_path / "owner-A"
        first.mkdir()
        provider = Provider()
        provider.release.set()
        async with Lifetime(
            first, root, monkeypatch, provider, domain_id="core"
        ) as life:
            socket = await life.socket()
            application = await socket.start()
            await socket.run(application, task="read previous notes")
            await socket.reply("run", type="domain_result")
            await socket.send("deactivate_domain", "stop-A", application)
            await socket.reply("stop-A", type="domain_state")
            await socket.send("end_domain_session", "end-A", application)
            await socket.reply("end-A", type="domain_state")
            initial, old_authority = await step(life, 1, "1")
            transient, _ = await step(life, 2, "1")
            assert old_authority["domain_revision"] == "3"
            assert (
                transient["snapshot"]["unsaved_results"][0]["output"]
                == "unsaved continuity text"
            )
            old_identity = initial["snapshot"]["state_store"]["continuity_id"]
        second = tmp_path / "owner-unavailable"
        second.mkdir()
        provider = Provider()
        life = Lifetime(second, root, monkeypatch, provider, domain_id="core")

        async def unavailable_open():
            life.server._state_error = "state_store_invalid"

        monkeypatch.setattr(life.server, "_open_application_state", unavailable_open)
        async with life:
            unavailable, wire = await step(life, 3, "1", retained=old_authority)
            assert wire["state_store"]["continuity_id"] is None
            assert (
                unavailable["snapshot"]["authority_unavailable"]
                and not unavailable["start_enabled"]
            )
            assert (
                len(unavailable["snapshot"]["results"])
                == len(unavailable["snapshot"]["unsaved_results"])
                == 1
            )
            assert not provider.clients and not provider.queries
            assert len(life.commands) <= 7
        third = tmp_path / "owner-recovered"
        third.mkdir()
        provider = Provider()
        life = Lifetime(third, root, monkeypatch, provider, domain_id="core")
        if replacement != "same-A":
            replacement_common = tmp_path / "disposable-replacement-common.git"
            replacement_common.mkdir()

            async def replacement_open():
                binding = await life.service.application_state_binding()
                assert binding is not None
                _, project_id = binding
                coordinator = StateCoordinator(
                    lambda: LazySQLiteStateRepository(replacement_common, project_id),
                    boot_id=life.server.domains.boot_id,
                )
                life.server.application_state = coordinator
                await coordinator.open()
                for turn in range(1 if replacement == "lower-B" else 4):
                    execution = str(uuid4())
                    await coordinator.commit(
                        StateCommand(
                            "start",
                            dict(
                                domain_id="core",
                                expected_domain_revision=turn * 2,
                                boot_id=life.server.domains.boot_id,
                                execution_id=execution,
                                timestamp="now",
                            ),
                        )
                    )
                    await coordinator.commit(
                        StateCommand(
                            "stop",
                            dict(
                                execution_id=execution,
                                outcome="stopped",
                                timestamp="now",
                            ),
                        )
                    )
                await life.service.observe_application_state(coordinator.snapshot())

            monkeypatch.setattr(
                life.server, "_open_application_state", replacement_open
            )
        async with life:
            recovered, authority = await step(
                life, 4, "1" if replacement == "same-A" else "0"
            )
            snapshot = recovered["snapshot"]
            assert not snapshot["authority_unavailable"] and recovered["start_enabled"]
            assert (
                not recovered["focus"] and not provider.clients and not provider.queries
            )
            if replacement == "same-A":
                assert snapshot["state_store"]["continuity_id"] == old_identity
                assert len(snapshot["results"]) == len(snapshot["unsaved_results"]) == 1
            else:
                assert snapshot["state_store"]["continuity_id"] != old_identity
                assert snapshot["domain_revision"] == (
                    "2" if replacement == "lower-B" else "8"
                )
                assert not snapshot["results"] and not snapshot["unsaved_results"]
                assert snapshot["selected_received_cursor"] == "0"
            assert len(life.commands) <= 9
            (control / "explicit-start").write_text("explicit user Start")
            await until(
                lambda: (control / "started.json").exists()
                or process.returncode is not None
            )
            assert (control / "started.json").exists(), (await output_task)[0].decode()
            starts = [
                packet
                for packet in life.commands
                if packet["type"] == "activate_domain"
            ]
            assert (
                len(starts) == 1
                and starts[0]["expected_domain_revision"]
                == authority["domain_revision"]
            )
            assert len(provider.clients) == 1 and not provider.queries
            output, _ = await asyncio.wait_for(output_task, 5)
            assert (
                process.returncode == 0 and b"godot_history_continuity: OK" in output
            ), output.decode()
    finally:
        if process.returncode is None:
            process.kill()
        await output_task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary,reason,explanation",
    [
        ("accepted_before_dispatch", "not_executed", "The task was not executed."),
        ("dispatch_before_sdk", "interrupted", "The execution outcome is unknown"),
    ],
)
async def test_real_crash_recovery_reaches_both_game_surfaces_after_repeated_reopen(
    tmp_path, monkeypatch, offline_clients, boundary, reason, explanation
):
    root = repository(tmp_path, "crash-project")
    runtime = tmp_path / "crashed-runtime"
    runtime.mkdir()
    signal = tmp_path / "boundary.json"
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
                "core",
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            await until(lambda: signal.exists() or child.poll() is not None)
            if not signal.exists():
                log.seek(0)
                pytest.fail(log.read())
            assert json.loads(signal.read_text())["calls"] == []
        finally:
            child.kill()
            await asyncio.to_thread(child.wait)
    frozen = None
    image_bytes = None
    for reopening in range(2):
        directory = tmp_path / f"reopen-{reopening}"
        directory.mkdir()
        provider = Provider()
        async with Lifetime(
            directory, root, monkeypatch, provider, domain_id="core"
        ) as life:
            await life.server._ensure_application_state()
            view = life.server.application_state.snapshot()
            terminal = view.terminals[0].packet
            assert terminal["reason"] == reason and terminal["recovered"] is True
            assert terminal["output_id"] == "1"
            if frozen is not None:
                assert terminal == frozen
            frozen = terminal
            reopened = await game(
                life.url, expected=explanation, status_first=bool(reopening)
            )
            assert reopened["results"] == [terminal]
            assert reopened["selected_received_cursor"] == "1"
            assert (
                explanation in reopened["answer"]
                and explanation in reopened["pane_answer"]
            )
            assert reopened["run_disabled"] and reopened["pane_run_disabled"]
            assert reopened["start_disabled"] and reopened["pane_start_disabled"]
            assert not provider.clients and not provider.queries
            assert not any(
                c["type"] in {"activate_domain", "domain_query"} for c in life.commands
            )
        current = (root / ".git/plaza/application-state/state.sqlite3").read_bytes()
        if image_bytes is not None:
            assert current == image_bytes
        image_bytes = current


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["missing-worktree", "invalid-registration"])
@pytest.mark.parametrize(
    "status_first", [False, True], ids=["character-first", "status-first"]
)
async def test_saved_history_survives_unavailable_current_workspace(
    tmp_path, monkeypatch, offline_clients, damage, status_first
):
    root = repository(tmp_path, "unavailable-project")
    first = tmp_path / "save"
    first.mkdir()
    provider = Provider()
    provider.release.set()
    async with Lifetime(first, root, monkeypatch, provider, domain_id="core") as life:
        socket = await life.socket()
        application = await socket.start()
        await socket.run(application, task="read previous notes")
        terminal = await socket.reply("run", type="domain_result")
        await socket.send("deactivate_domain", "stop", application)
        await socket.reply("stop", type="domain_state")
        workspace = life.service.require_workspace("core")
    image = root / ".git/plaza/application-state/state.sqlite3"
    before = image.read_bytes()
    if damage == "missing-worktree":
        workspace.worktree_path.rename(tmp_path / "unavailable-worktree")
    else:
        (workspace.worktree_path / ".git").write_text("invalid worktree registration\n")
    second = tmp_path / "inspect"
    second.mkdir()
    provider = Provider()
    async with Lifetime(second, root, monkeypatch, provider, domain_id="core") as life:
        assert life.service.workspace_snapshot("core")["workspace_id"] is None
        assert life.service.workspace_snapshot("core")["stage"] == "failed"
        reopened = await game(life.url, status_first=status_first)
        observations = [
            c["type"]
            for c in life.commands
            if c["type"] in {"domain_status", "agent_status"}
        ]
        assert observations[0] == ("domain_status" if status_first else "agent_status")
        assert reopened["results"] == [terminal]
        assert reopened["selected_received_cursor"] == "1"
        assert "Readback from prior notes: isolated" in reopened["pane_answer"]
        assert reopened["run_disabled"] and reopened["pane_run_disabled"]
        assert reopened["start_disabled"] and reopened["pane_start_disabled"]
        assert not provider.clients and not provider.queries
        assert not any(
            c["type"] in {"activate_domain", "domain_query"} for c in life.commands
        )
    assert image.read_bytes() == before
