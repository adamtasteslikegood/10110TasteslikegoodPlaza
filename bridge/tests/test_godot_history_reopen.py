"""Fresh Godot processes discover real SQLite history without starting work."""

import asyncio
import json
import os
from pathlib import Path
import shutil

import pytest

from bridge.tests.m12_harness import Lifetime, Provider, until
from bridge.tests.test_workspace import repository

ROOT = Path(__file__).resolve().parents[2]


async def game(url):
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
        env={**os.environ, "PLAZA_TEST_BRIDGE_URL": url},
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
