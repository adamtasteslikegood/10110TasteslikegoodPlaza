"""Offline M12 composition: real ownership/lifecycle, disposable provider seams."""

import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import websockets
from claude_agent_sdk import AssistantMessage, TextBlock

from bridge.config import default_config
from bridge.domain_sdk import DomainSDKOwner
from bridge.log_storage import RunLogWriter
from bridge.observability import BridgeRecorder
from bridge.project_service import ProjectService
from bridge.server import BridgeServer
from bridge.tests.test_domain_sdk import Client, terminal
from bridge.tests.test_workspace import repository
from bridge.workspace import git_without_filters
from bridge.workspace_lease import observe_reservation


async def until(predicate, timeout=15):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def baseline(root):
    """Inspect only fixture repositories, with filter-disabled bounded Git."""
    tracked = git_without_filters(root, "ls-files", "-z").split("\0")
    return (
        git_without_filters(root, "rev-parse", "HEAD"),
        git_without_filters(root, "status", "--porcelain=v1", "-z"),
        {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in tracked
            if name
        },
        {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()},
    )


def identity(packet):
    return tuple(
        packet[key]
        for key in (
            "project_id",
            "workspace_id",
            "domain_id",
            "domain_session_id",
            "output_id",
        )
    )


class Provider:
    """Cancellable SDK fake; never opens a subprocess or provider transport."""

    def __init__(self):
        self.clients, self.owners, self.queries, self.writes = [], [], [], []
        self.release = asyncio.Event()
        self.connect_release = None
        self.before_write = None

    def owner(self, *args):
        owner = DomainSDKOwner(*args, client_factory=self.client)
        self.owners.append(owner)
        return owner

    def client(self, **kwargs):
        provider = self

        class FakeClient(Client):
            async def query(self, prompt):
                await super().query(prompt)
                self.command = json.loads(prompt)
                provider.queries.append(self.command)

            async def receive_response(self):
                self.note("receive")
                self.receiving.set()
                await provider.release.wait()
                command = self.command
                if command["task"] == "execute integration sentinel":
                    if provider.before_write is not None:
                        provider.before_write()
                    for matcher in self.options.hooks["PreToolUse"]:
                        for hook in matcher.hooks:
                            assert (
                                await asyncio.create_task(
                                    hook(
                                        dict(
                                            hook_event_name="PreToolUse",
                                            cwd=self.options.cwd,
                                            tool_name="Write",
                                            tool_use_id="fixture-write",
                                            tool_input={},
                                        ),
                                        "fixture-write",
                                        {},
                                    )
                                )
                                == {}
                            )
                    result = Path(self.options.cwd) / "integration-result.txt"
                    with result.open("x") as handle:
                        handle.write("domain sentinel ibis")
                    provider.writes.append((result, asyncio.get_running_loop().time()))
                    output = "domain sentinel ibis"
                else:
                    output = "Readback from prior notes: " + (
                        "ibis"
                        if "ibis" in command["prior_project_notes"]
                        else "isolated"
                    )
                yield AssistantMessage([TextBlock(output)], self.options.model)
                yield terminal(result=output)

        client = FakeClient(**kwargs)
        client.connect_gate = self.connect_release
        self.clients.append(client)
        return client


class Socket:
    def __init__(self, socket, domain_id="engineering"):
        self.socket, self.packets = socket, []
        self.domain_id = domain_id

    async def send(self, kind, request_id, generation=None, **extra):
        command = dict(type=kind, request_id=request_id)
        if kind != "describe_workspace":
            command["domain_id"] = self.domain_id
        if generation is not None:
            command["domain_session_id"] = generation
        command.update(extra)
        await self.socket.send(json.dumps(command))
        return command

    async def receive(self, predicate):
        async with asyncio.timeout(15):
            while True:
                packet = json.loads(await self.socket.recv())
                self.packets.append(packet)
                if predicate(packet):
                    return packet

    async def reply(self, request_id, **expected):
        return await self.receive(
            lambda p: p.get("request_id") == request_id
            and all(p.get(k) == v for k, v in expected.items())
        )

    async def start(self, request_id="start"):
        await self.send("activate_domain", request_id)
        activating = await self.reply(request_id, state="activating")
        active = await self.reply(request_id, state="active")
        assert activating["domain_session_id"] == active["domain_session_id"]
        return active["domain_session_id"]

    async def run(
        self, generation, request_id="run", task="execute integration sentinel"
    ):
        await self.send(
            "domain_query",
            request_id,
            generation,
            agent_id=(
                "systems-architect" if self.domain_id == "core" else "backend-architect"
            ),
            task=task,
        )
        return await self.reply(request_id, type="domain_accepted")

    async def replay(self, generation, request_id="replay"):
        offset = len(self.packets)
        await self.send("resume", request_id, generation, cursor="0")
        await self.reply(request_id, type="resume_complete")
        return [p for p in self.packets[offset:] if p["type"] == "domain_result"]


class Lifetime:
    """Delegating listener instrumentation leaves serve's actual drainage intact."""

    def __init__(
        self,
        tmp_path,
        root,
        monkeypatch,
        provider,
        *,
        reviewer=None,
        domain_id="engineering",
    ):
        self.domain_id = domain_id
        self.root = root
        self.runtime = tmp_path / "runtime"
        self.runtime.mkdir()
        (self.runtime / "sentinel").write_text("runtime unsaved")
        self.run_id = uuid.uuid4().hex
        self.config = replace(
            default_config(), workspace_root_dir=root, log_dir=tmp_path / "logs"
        )
        self.service = ProjectService(
            self.config,
            runtime_root=self.runtime,
            owner_run_id=self.run_id,
            reviewer=reviewer,
        )
        self.writer = RunLogWriter(self.config, "M12 disposable integration")
        self.recorder = BridgeRecorder(self.config, "M12 fixture", writer=self.writer)
        self.server = BridgeServer(
            config=self.config, project_service=self.service, recorder=self.recorder
        )
        self.stop = asyncio.Event()
        self.ready = asyncio.Event()
        self.listeners, self.sockets = [], []
        actual = websockets.serve

        def listen(handler, host, port, **kwargs):
            listener = actual(handler, "127.0.0.1", 0, **kwargs)
            self.listeners.append(listener)
            return listener

        monkeypatch.setattr("bridge.server.websockets", SimpleNamespace(serve=listen))
        monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", provider.owner)
        original = self.server._event

        def event(name, *args, **kwargs):
            original(name, *args, **kwargs)
            if name == "bridge_started":
                self.ready.set()

        self.server._event = event
        self.commands, self.emitted = [], []
        dispatch = self.server.dispatch

        async def observe(command, *args, **kwargs):
            self.commands.append(dict(command))
            emit = kwargs.get("emit")
            if emit is not None:

                async def observed_emit(packet):
                    self.emitted.append(dict(packet))
                    await emit(packet)

                kwargs["emit"] = observed_emit
            return await dispatch(command, *args, **kwargs)

        self.server.dispatch = observe
        self.provider = provider
        self.serving = None

    async def __aenter__(self):
        self.serving = asyncio.create_task(self.server.serve(stop_event=self.stop))
        await asyncio.wait_for(self.ready.wait(), 10)
        await self.service._bootstrap_task
        port = self.listeners[0].server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"
        return self

    async def socket(self):
        socket = await websockets.connect(self.url)
        self.sockets.append(socket)
        return Socket(socket, self.domain_id)

    @property
    def marker(self):
        common = self.service.require_memory().workspace.common_git_dir
        return (
            common
            / "plaza/runs"
            / (hashlib.sha256(self.run_id.encode()).hexdigest() + ".json")
        )

    def assert_released(self):
        workspace = self.service.require_workspace(self.domain_id)
        assert observe_reservation(workspace) is None
        assert self.service.workspace_snapshot(self.domain_id)["reservation"] is None
        assert not (workspace.git_dir / "plaza-unclean.json").exists()
        for owner in self.provider.owners:
            assert owner._worker.done() and owner.transport.closed
        for client in self.provider.clients:
            assert [c for c, _ in client.calls].count("disconnect") == 1
            assert len({task for _, task in client.calls}) == 1

    async def __aexit__(self, exc_type, exc, traceback):
        self.provider.release.set()
        if self.provider.connect_release is not None:
            self.provider.connect_release.set()
        self.stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(self.serving), 15)
        finally:
            for socket in self.sockets:
                await socket.close()

    def manifest(self):
        manifests = [
            json.loads(p.read_text())
            for p in self.config.log_dir.glob("runs/*/manifest.json")
        ]
        return next(p for p in manifests if p["run_id"] == self.writer.run_id)

    def assert_closed(self):
        assert not self.marker.exists()
        manifest = self.manifest()
        assert manifest["status"] == "closed" and manifest["ended_at"]


async def restart_and_isolation(
    tmp_path, root, monkeypatch, work, memory_before, result_bytes
):
    """Restart the exact physical-flow project, then switch to independent repo B."""
    result = work.worktree_path / "integration-result.txt"
    restart_dir = tmp_path / "restart"
    restart_dir.mkdir()
    readback = Provider()
    readback.release.set()
    async with Lifetime(
        restart_dir, root, monkeypatch, readback, domain_id=work.domain_id
    ) as restart:
        reused = restart.service.require_workspace(work.domain_id)
        assert reused == work
        assert restart.service.require_memory().load() == memory_before
        assert not readback.clients and not readback.queries
        socket = await restart.socket()
        gen = await socket.start()
        await socket.run(gen, task="read previous notes")
        fresh = await socket.reply("run", type="domain_result")
        assert fresh["output"] == "Readback from prior notes: ibis"
        assert "ibis" not in readback.queries[0]["task"]
        assert "ibis" in readback.queries[0]["prior_project_notes"]
        assert result.read_bytes() == result_bytes and not readback.writes
        assert len(readback.queries) == 1
        await socket.send("deactivate_domain", "stop", gen)
        assert (await socket.reply("stop"))["state"] == "inactive"
        restart.assert_released()
    restart.assert_closed()
    a_notes_after = restart.service._memory.load()

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = repository(other_dir, "project-b")
    isolated = Provider()
    isolated.release.set()
    async with Lifetime(
        other_dir, other, monkeypatch, isolated, domain_id=work.domain_id
    ) as second:
        socket = await second.socket()
        gen = await socket.start()
        b_work = second.service.require_workspace(work.domain_id)
        assert b_work.project_id != work.project_id
        assert b_work.workspace_id != work.workspace_id
        assert b_work.common_git_dir != work.common_git_dir
        assert "ibis" not in second.service.require_memory().load().as_context()
        documents = b_work.common_git_dir / "plaza/session-memory"
        assert len(list(documents.glob("*.md"))) == 3
        assert all("ibis" not in p.read_text() for p in documents.glob("*.md"))
        await socket.run(gen, task="read previous notes")
        assert (await socket.reply("run", type="domain_result"))["output"].endswith(
            "isolated"
        )
        assert "ibis" not in isolated.queries[0]["prior_project_notes"]
        await socket.send("deactivate_domain", "stop", gen)
        assert (await socket.reply("stop"))["state"] == "inactive"
        second.assert_released()
    second.assert_closed()
    assert result.read_bytes() == result_bytes
    assert restart.service._memory.load() == a_notes_after
