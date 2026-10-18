"""Real loopback service and disk archives, with deterministic offline providers.

These cases fail if archive bounds alter replies/history, writer failures escape
request handling, recovery stops retrying, or bodies leak into diagnostic events.
Crash/OS-lock release and orphan startup are covered by test_log_storage's real
subprocess cases; do not duplicate those expensive process fixtures here.
"""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import errno
import hashlib
import json

import pytest
import websockets

from bridge.config import load_config
from bridge.log_storage import RunLogWriter, iter_jsonl
from bridge.observability import BridgeRecorder
from bridge.server import BridgeServer
import bridge.log_storage as storage

SECRET = "integration-credential-sentinel"
BODY = "private-task-body"
LARGE_REPLY = "full provider reply \U0001f680\n" * 1500


@pytest.fixture
def config_factory(tmp_path):
    def make(**overrides):
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps(
                {
                    "LOG_DIR": "archive",
                    "LOG_LEVEL": "DEBUG",
                    "TRANSCRIPT_MAX_RECORD_BYTES": 4096,
                    "TRANSCRIPT_MAX_FILE_BYTES": 8192,
                    "LOG_MAX_TOTAL_BYTES": 200000,
                    **overrides,
                }
            )
        )
        return load_config(path, environ={})

    return make


@pytest.fixture
def provider(offline_clients):
    client, _, _ = offline_clients
    calls = []

    def reply(**kwargs):
        calls.append(deepcopy(kwargs))
        task = kwargs["messages"][-1]["content"]
        text = LARGE_REPLY if "large" in task else f"answer:{task}"
        return text

    client.reply.side_effect = reply
    return calls


@asynccontextmanager
async def service(config, *, writer=None):
    recorder = BridgeRecorder(
        config, "integration", writer=writer, redactions=(SECRET,)
    )
    server = BridgeServer(config=config, recorder=recorder)
    try:
        async with websockets.serve(server._handle_connection, "127.0.0.1", 0) as ws:
            port = ws.sockets[0].getsockname()[1]
            yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()


async def ask(socket, agent, task, request_id):
    await socket.send(
        json.dumps({"agent_id": agent, "task": task, "request_id": request_id})
    )
    response = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
    assert response == {
        "agent_id": agent,
        "task": task,
        "output": LARGE_REPLY if "large" in task else f"answer:{task}",
        "status": "ok",
        "request_id": request_id,
    }
    return response


def read_records(root, pattern):
    diagnostics = []
    records = [
        record
        for path in sorted(root.glob(pattern))
        for record in iter_jsonl(path, on_diagnostic=diagnostics.append)
    ]
    assert diagnostics == []
    return sorted(records, key=lambda record: record["seq"])


def assert_agent_stream(directory, agent_id, requests):
    # Inspect physical segment/line order before any global sequence sorting.
    records = [
        record
        for segment in sorted(directory.glob("transcript-*.jsonl"))
        for record in iter_jsonl(segment, on_diagnostic=pytest.fail)
    ]
    assert [(record["request_id"], record["role"]) for record in records] == [
        (request, role) for request in requests for role in ("user", "assistant")
    ]
    assert {record["agent_id"] for record in records} == {agent_id}
    sequences = [record["seq"] for record in records]
    assert all(before < after for before, after in zip(sequences, sequences[1:]))


def assert_private_diagnostics(root, stderr):
    events = read_records(root, "runs/*/events-*.jsonl")
    encoded = json.dumps(events) + stderr
    assert BODY not in encoded
    assert SECRET not in encoded
    assert LARGE_REPLY[:50] not in encoded
    assert all("content" not in event and "task" not in event for event in events)
    assert SECRET not in " ".join(str(path) for path in root.rglob("*"))
    assert SECRET not in "".join(
        path.read_text() for path in root.rglob("*") if path.is_file()
    )


@pytest.mark.asyncio
async def test_two_connections_agents_keep_wire_context_and_ordered_bounded_archives(
    config_factory, provider, capsys
):
    config = config_factory(TRANSCRIPT_MAX_FILE_BYTES=4096)
    # Six interleaved exchanges distinguish connection-local and agent-local
    # history. A large Unicode answer must survive unmodified into turn two.
    async with service(config) as uri:
        async with websockets.connect(uri) as first, websockets.connect(uri) as second:
            await ask(first, "alpha", BODY + "-large", "a1")
            await ask(first, "beta-" + SECRET, BODY + SECRET + "-beta", "b1")
            await ask(second, "alpha", BODY + "-other", "c1")
            await ask(first, "alpha", BODY + "-follow", "a2")
            await ask(first, "beta-" + SECRET, BODY + "-follow-beta", "b2")
            await ask(second, "alpha", BODY + "-follow-other", "c2")

    assert [len(call["messages"]) for call in provider] == [1, 1, 1, 3, 3, 3]
    for index, initial in ((3, 0), (4, 1), (5, 2)):
        first_task = provider[initial]["messages"][0]["content"]
        assert provider[index]["messages"] == [
            {"role": "user", "content": first_task},
            {
                "role": "assistant",
                "content": LARGE_REPLY if initial == 0 else f"answer:{first_task}",
            },
            provider[index]["messages"][-1],
        ]
    root = config.log_dir
    agents = next(root.glob("runs/*/agents"))
    beta_path = "redacted-" + hashlib.sha256(("beta-" + SECRET).encode()).hexdigest()
    assert {directory.name for directory in agents.iterdir()} == {"alpha", beta_path}
    assert_agent_stream(agents / "alpha", "alpha", ("a1", "c1", "a2", "c2"))
    assert_agent_stream(agents / beta_path, "beta-[REDACTED]", ("b1", "b2"))
    transcripts = read_records(root, "runs/*/agents/*/transcript-*.jsonl")
    assert len(transcripts) == 12
    requests = [record["request_id"] for record in transcripts]
    assert requests == [
        item
        for request in ("a1", "b1", "c1", "a2", "b2", "c2")
        for item in (request, request)
    ]
    assert [record["role"] for record in transcripts] == ["user", "assistant"] * 6
    by_id = {record["request_id"]: record for record in transcripts}
    assert by_id["a1"]["connection_id"] == by_id["b2"]["connection_id"]
    assert by_id["a1"]["connection_id"] != by_id["c1"]["connection_id"]
    assert by_id["c1"]["connection_id"] == by_id["c2"]["connection_id"]
    assert by_id["a1"]["truncated"] is True
    assert by_id["a1"]["original_content_bytes"] == len(LARGE_REPLY.encode())
    assert by_id["a1"]["content"].endswith("[truncated]")
    events = read_records(root, "runs/*/events-*.jsonl")
    assert sum(record["event"] == "connection_opened" for record in events) == 2
    assert sum(record["event"] == "connection_closed" for record in events) == 2
    assert sum(record["event"] == "request_completed" for record in events) == 6
    all_records = transcripts + events
    assert len({record["seq"] for record in all_records}) == len(all_records)
    assert len({record["run_id"] for record in all_records}) == 1
    manifest = json.loads(next(root.glob("runs/*/manifest.json")).read_text())
    assert manifest["status"] == "closed" and manifest["ended_at"]
    assert manifest["settings"] == config.effective_settings()
    assert manifest["run_id"] == transcripts[0]["run_id"]
    assert list(root.glob("runs/*/events-0002.jsonl"))  # real rotation
    for path in root.rglob("*.jsonl"):
        assert path.stat().st_size <= config.transcript_max_file_bytes
        assert all(len(line) <= 4096 for line in path.read_bytes().splitlines(True))
    assert_private_diagnostics(root, capsys.readouterr().err)


@pytest.mark.asyncio
async def test_pressure_prunes_sealed_segments_and_keeps_serving(
    config_factory, provider
):
    config = config_factory(TRANSCRIPT_MAX_FILE_BYTES=4096, LOG_MAX_TOTAL_BYTES=18000)
    seen = set()
    removed = set()
    async with service(config) as uri:
        sentinel = config.log_dir / "operator-notes.txt"
        sentinel.write_text("keep me")
        async with websockets.connect(uri) as socket:
            for index in range(24):
                await ask(socket, "alpha", f"{BODY}-large-{index}", str(index))
                current = set(config.log_dir.rglob("*.jsonl"))
                removed |= seen - current
                seen |= current
                managed = list(config.log_dir.rglob("*.jsonl")) + list(
                    config.log_dir.glob("runs/*/manifest*")
                )
                assert sum(path.stat().st_size for path in managed) <= 18000
                for path in current:
                    assert path.stat().st_size <= 4096
                    list(iter_jsonl(path, on_diagnostic=pytest.fail))
    assert removed  # retention deleted previously observed real segments
    assert sentinel.read_text() == "keep me"
    assert len(provider) == 24
    transcripts = read_records(config.log_dir, "runs/*/agents/*/transcript-*.jsonl")
    assert any(record["request_id"] == "23" for record in transcripts)
    assert not any(record["request_id"] == "0" for record in transcripts)
    assert read_records(config.log_dir, "runs/*/events-*.jsonl")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [errno.ENOSPC, errno.EACCES], ids=["diskfull", "readonly"]
)
async def test_failed_disk_writes_preserve_responses_context_and_recover(
    failure, config_factory, provider, monkeypatch, capsys
):
    config = config_factory()
    async with service(config) as uri:
        async with websockets.connect(uri) as socket:
            await ask(socket, "alpha", BODY + "-before", "before")

            def unavailable(fd, data):
                raise OSError(failure, f"{SECRET}:{BODY}")

            with monkeypatch.context() as fault:
                fault.setattr(storage, "_write_all", unavailable)
                await ask(socket, "alpha", BODY + SECRET, "lost")
            await ask(socket, "alpha", BODY + "-after", "after")
    assert [len(call["messages"]) for call in provider] == [1, 3, 5]
    assert provider[-1]["messages"][-2]["content"] == f"answer:{BODY}{SECRET}"
    records = read_records(config.log_dir, "runs/*/agents/*/transcript-*.jsonl")
    assert {record["request_id"] for record in records} == {"before", "after"}
    stderr = capsys.readouterr().err
    assert "recording suspended" in stderr and "recording recovered" in stderr
    assert_private_diagnostics(config.log_dir, stderr)


@pytest.mark.asyncio
async def test_contending_recorder_keeps_chat_then_recovers_a_distinct_run(
    config_factory, provider, capsys
):
    config = config_factory()
    owner = RunLogWriter(config, "other process owner")
    owner_run = owner.run_id
    try:
        async with service(config) as uri:
            async with websockets.connect(uri) as socket:
                await ask(socket, "alpha", BODY + SECRET, "contended")
                assert len(list(config.log_dir.glob("runs/*/manifest.json"))) == 1
                owner.close()
                await ask(socket, "alpha", BODY + "-recovered", "recovered")
    finally:
        owner.close()
    assert [len(call["messages"]) for call in provider] == [1, 3]
    records = read_records(config.log_dir, "runs/*/agents/*/transcript-*.jsonl")
    assert {record["request_id"] for record in records} == {"recovered"}
    assert records[0]["run_id"] != owner_run
    manifests = [
        json.loads(path.read_text())
        for path in config.log_dir.glob("runs/*/manifest.json")
    ]
    assert len(manifests) == 2 and all(item["status"] == "closed" for item in manifests)
    stderr = capsys.readouterr().err
    assert "recording suspended" in stderr and "recording recovered" in stderr
    assert_private_diagnostics(config.log_dir, stderr)


@pytest.mark.asyncio
async def test_disabled_transcripts_keep_events_wire_and_two_turn_context(
    config_factory, provider, capsys
):
    config = config_factory(TRANSCRIPTS_ENABLED=False)
    async with service(config) as uri:
        async with websockets.connect(uri) as socket:
            await ask(socket, "alpha", BODY + SECRET + "-large", "first")
            await ask(socket, "alpha", BODY + "-follow", "second")
    assert provider[1]["messages"][1] == {"role": "assistant", "content": LARGE_REPLY}
    assert not list(config.log_dir.rglob("transcript-*"))
    assert not list(config.log_dir.glob("runs/*/agents"))
    events = read_records(config.log_dir, "runs/*/events-*.jsonl")
    assert sum(record["event"] == "request_completed" for record in events) == 2
    assert_private_diagnostics(config.log_dir, capsys.readouterr().err)
