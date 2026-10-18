"""Recorder correlation, standard diagnostics, and best-effort failure boundaries."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import json
import logging

import pytest

from bridge.config import default_config
from bridge.log_storage import iter_jsonl
from bridge.observability import BridgeRecorder, RequestContext


def config(tmp_path, **overrides):
    return replace(default_config(), log_dir=tmp_path / "logs", **overrides)


def context(**overrides):
    values = dict(
        connection_id="conn-1",
        request_id="req-1",
        agent_id="agent",
        engine="conversation",
        model="model",
    )
    values.update(overrides)
    return RequestContext(**values)


def records(cfg, pattern="*.jsonl"):
    result = []
    for path in cfg.log_dir.rglob(pattern):
        errors = []
        result.extend(iter_jsonl(path, on_diagnostic=errors.append))
        assert not errors
    return sorted(result, key=lambda row: row["seq"])


class FaultWriter:
    """Injected storage boundary; real writer behavior is covered on disk below."""

    run_id = "test-run"

    def __init__(self, results=()):
        self.results = iter(results)
        self.rows = []
        self.closed = []

    def append(self, kind, record, *, agent_id=None):
        result = next(self.results, True)
        if isinstance(result, BaseException):
            raise result
        if result:
            self.rows.append((kind, record, agent_id))
        return result

    def close(self, *, clean=True):
        self.closed.append(clean)


def test_context_is_frozen_and_records_correlate_without_invented_ids(tmp_path):
    cfg = config(tmp_path)
    recorder = BridgeRecorder(cfg, "plaza")
    ctx = context()
    with pytest.raises(FrozenInstanceError):
        ctx.request_id = "changed"
    assert recorder.message(ctx, "user", "question", "input")
    assert recorder.message(ctx, "assistant", "answer", "success")
    assert recorder.message(ctx, "error", "provider failure", "failure")
    assert recorder.event("request_completed", ctx, outcome="success", duration_ms=12.5)
    recorder.close()
    rows = records(cfg)
    assert [row["seq"] for row in rows] == [1, 2, 3, 4]
    assert len({row["run_id"] for row in rows}) == 1
    for row in rows:
        assert row["schema_version"] == 1
        assert row["timestamp"].endswith("+00:00")
        for key in ("connection_id", "request_id", "agent_id", "engine", "model"):
            assert row[key] == getattr(ctx, key)
        assert not {"domain_id", "output_id", "provider_session_id"} & row.keys()
    assert [(r["role"], r["outcome"]) for r in rows[:3]] == [
        ("user", "input"),
        ("assistant", "success"),
        ("error", "failure"),
    ]
    assert "content" not in rows[3]
    assert rows[3]["duration_ms"] == 12.5


def test_optional_ids_present_only_when_available(tmp_path):
    cfg = config(tmp_path)
    recorder = BridgeRecorder(cfg, "plaza")
    ctx = context(connection_id=None, model=None, domain_id="domain")
    assert recorder.message(
        ctx,
        "assistant",
        "done",
        "success",
        output_id="out",
        provider_session_id="session",
    )
    assert recorder.event("domain_transition", ctx, domain_state="complete")
    assert recorder.event("bridge_started")
    recorder.close()
    rows = records(cfg)
    assert rows[0]["domain_id"] == "domain"
    assert rows[0]["output_id"] == "out"
    assert rows[0]["provider_session_id"] == "session"
    assert "connection_id" not in rows[0] and "model" not in rows[0]
    assert rows[1]["domain_state"] == "complete"
    assert "request_id" not in rows[2]


@pytest.mark.parametrize(
    "level,expected",
    [
        ("DEBUG", [True, True, True, True]),
        ("INFO", [False, True, True, True]),
        ("WARNING", [False, False, True, True]),
        ("ERROR", [False, False, False, True]),
    ],
)
def test_logging_filters_events_but_not_transcripts_or_manifest(
    tmp_path, capsys, level, expected
):
    cfg = config(tmp_path, log_level=level)
    recorder = BridgeRecorder(cfg, "plaza")
    names = ["engine_routing", "bridge_started", "recording_warning", "request_failed"]
    assert [recorder.event(name) for name in names] == expected
    assert recorder.message(context(), "assistant", "private answer", "success")
    recorder.close()
    assert [r["event"] for r in records(cfg, "events-*.jsonl")] == [
        name for name, included in zip(names, expected) if included
    ]
    assert len(records(cfg, "transcript-*.jsonl")) == 1
    manifest = json.loads(next(cfg.log_dir.rglob("manifest.json")).read_text())
    assert manifest["status"] == "closed"
    stderr = capsys.readouterr().err
    for name, included in zip(names, expected):
        assert (name in stderr) == included
    assert "private answer" not in stderr


def test_disabled_transcripts_preserve_lifecycle_and_error_events(tmp_path):
    cfg = config(tmp_path, transcripts_enabled=False)
    recorder = BridgeRecorder(cfg, "plaza")
    assert not recorder.message(context(), "user", "private input", "input")
    assert recorder.event("bridge_started")
    assert recorder.event("request_failed", context(), outcome="failure")
    recorder.close()
    assert len(records(cfg)) == 2
    assert not list(cfg.log_dir.rglob("transcript-*.jsonl"))


def test_disk_redaction_precedes_fitting_without_mutating_live_content(
    tmp_path, capsys
):
    cfg = config(tmp_path, transcript_max_record_bytes=4096)
    secret = "fake-provider-credential-" + "x" * 5000
    body = "provider error with " + secret
    ctx = context(request_id=secret)
    recorder = BridgeRecorder(cfg, "plaza", redactions=("", secret))
    assert recorder.message(ctx, "error", body, "failure")
    assert recorder.event("request_failed", ctx, outcome="failure")
    recorder.close()
    rows = records(cfg)
    assert rows[0]["content"] == "provider error with [REDACTED]"
    assert rows[0]["request_id"] == "[REDACTED]"
    assert "truncated" not in rows[0]
    assert secret in body and ctx.request_id == secret
    assert all(secret not in path.read_text() for path in cfg.log_dir.rglob("*.jsonl"))
    stderr = capsys.readouterr().err
    assert secret not in stderr and "provider error with" not in stderr
    assert "[REDACTED]" in stderr


def test_all_metadata_strings_redacted_and_no_sdk_or_environment_capture(
    tmp_path, monkeypatch
):
    secret = "fake-secret"
    monkeypatch.setenv("SENSITIVE_OPTIONS", secret)
    writer = FaultWriter()
    recorder = BridgeRecorder(
        config(tmp_path), "plaza", writer=writer, redactions=(secret,)
    )
    ctx = context(engine=secret, model=secret, domain_id=secret, connection_id=secret)
    assert recorder.event("request_completed", ctx, outcome=secret, domain_state=secret)
    assert recorder.message(
        ctx, "assistant", secret, secret, output_id=secret, provider_session_id=secret
    )
    recorder.close()
    serialized = json.dumps(writer.rows)
    assert secret not in serialized
    assert "SENSITIVE_OPTIONS" not in serialized
    assert set(writer.rows[0][1]) == {
        "event",
        "connection_id",
        "request_id",
        "agent_id",
        "engine",
        "model",
        "domain_id",
        "outcome",
        "domain_state",
    }


@pytest.mark.parametrize(
    "failure",
    [
        False,
        OSError("private fake-credential"),
        RuntimeError("private fake-credential"),
    ],
)
def test_failed_capture_is_false_retries_and_recovers_visibly(
    tmp_path, capsys, failure
):
    writer = FaultWriter([failure, failure, True, failure, True])
    recorder = BridgeRecorder(config(tmp_path), "plaza", writer=writer)
    assert not recorder.message(context(), "user", "private", "input")
    assert not recorder.event("request_failed")
    first = capsys.readouterr().err
    assert first.count("recording suspended") == 1
    assert "fake-credential" not in first and "private" not in first
    assert recorder.message(context(), "assistant", "private", "success")
    assert "recording recovered" in capsys.readouterr().err
    assert not recorder.event("request_failed")
    assert "recording suspended" in capsys.readouterr().err
    assert recorder.event("request_completed")
    assert "recording recovered" in capsys.readouterr().err
    recorder.close()


@pytest.mark.parametrize(
    "signal", [KeyboardInterrupt(), SystemExit(), asyncio.CancelledError()]
)
@pytest.mark.parametrize("method", ["event", "message", "close"])
def test_exit_and_cancellation_are_never_swallowed(tmp_path, signal, method):
    writer = FaultWriter([signal])
    recorder = BridgeRecorder(config(tmp_path), "plaza", writer=writer)
    if method == "close":

        def fail_close(**kwargs):
            raise signal

        writer.close = fail_close
    with pytest.raises(type(signal)):
        if method == "event":
            recorder.event("request_failed")
        elif method == "message":
            recorder.message(context(), "user", "input", "input")
        else:
            recorder.close()
    recorder.close()


def test_close_is_idempotent_isolates_failure_and_disables_writes(tmp_path, capsys):
    writer = FaultWriter()

    def fail_close(**kwargs):
        writer.closed.append(kwargs["clean"])
        raise RuntimeError("private provider error")

    writer.close = fail_close
    recorder = BridgeRecorder(config(tmp_path), "plaza", writer=writer)
    recorder.close(clean=False)
    recorder.close()
    assert writer.closed == [False]
    assert not recorder.event("bridge_started")
    assert not recorder.message(context(), "user", "input", "input")
    assert "private provider error" not in capsys.readouterr().err


def test_parallel_workers_preserve_per_worker_order_and_global_sequence(tmp_path):
    cfg = config(tmp_path)
    recorder = BridgeRecorder(cfg, "plaza")

    def work(worker):
        ctx = context(request_id=f"req-{worker}")
        return all(
            recorder.message(ctx, "assistant", str(index), "success")
            for index in range(15)
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(work, range(4)))
    recorder.close()
    rows = records(cfg)
    assert [r["seq"] for r in rows] == list(range(1, 61))
    for worker in range(4):
        assert [r["content"] for r in rows if r["request_id"] == f"req-{worker}"] == [
            str(i) for i in range(15)
        ]


def test_owned_logging_has_no_root_or_provider_changes_and_no_duplicate_output(
    tmp_path, capsys
):
    root = logging.getLogger()
    provider = logging.getLogger("anthropic")
    state = (root.level, list(root.handlers), provider.level, list(provider.handlers))
    for _ in range(3):
        writer = FaultWriter()
        recorder = BridgeRecorder(
            config(tmp_path, log_level="DEBUG"), "plaza", writer=writer
        )
        assert recorder.event("engine_routing")
        recorder.close()
        assert len(writer.rows) == 1
    assert capsys.readouterr().err.count("engine_routing") == 3
    assert (root.level, root.handlers, provider.level, provider.handlers) == state


def test_recursive_writer_callback_does_not_recurse_or_claim_capture(tmp_path, capsys):
    writer = FaultWriter()
    recorder = BridgeRecorder(config(tmp_path), "plaza", writer=writer)
    original = writer.append
    nested = []

    def append(*args, **kwargs):
        nested.append(recorder.event("request_failed"))
        nested.append(recorder.message(context(), "error", "private", "failure"))
        return original(*args, **kwargs)

    writer.append = append
    assert recorder.event("request_completed")
    recorder.close()
    assert nested == [False, False]
    assert len(writer.rows) == 1
    assert "private" not in capsys.readouterr().err


def test_unstructured_logging_and_provider_exception_text_are_not_captured(
    tmp_path, capsys
):
    writer = FaultWriter()
    recorder = BridgeRecorder(
        config(tmp_path, log_level="DEBUG"), "plaza", writer=writer
    )
    # The owned adapter accepts only records created by the structured facade.
    try:
        raise RuntimeError("private body fake-credential")
    except RuntimeError:
        recorder._logger.exception("private body fake-credential")
    assert writer.rows == []
    assert "fake-credential" not in capsys.readouterr().err
    recorder.close()


def test_context_subclass_cannot_add_message_bodies_to_metadata(tmp_path, capsys):
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class ProviderContext(RequestContext):
        task_body: str = "private task body"
        sdk_options: str = "fake-credential"

    writer = FaultWriter()
    recorder = BridgeRecorder(config(tmp_path), "plaza", writer=writer)
    ctx = ProviderContext(None, "req", "agent", "conversation", None)
    assert recorder.event("request_completed", ctx)
    assert recorder.message(ctx, "assistant", "safe reply", "success")
    recorder.close()
    assert all(
        "task_body" not in row and "sdk_options" not in row for _, row, _ in writer.rows
    )
    stderr = capsys.readouterr().err
    assert "private task body" not in stderr and "fake-credential" not in stderr


def test_writer_construction_failure_is_isolated_and_retry_recovers(
    tmp_path, capsys, monkeypatch
):
    from bridge import observability

    writer = FaultWriter()
    attempts = []

    def create(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise RuntimeError("provider error fake-credential")
        return writer

    monkeypatch.setattr(observability, "RunLogWriter", create)
    recorder = BridgeRecorder(
        config(tmp_path), "fake-credential", redactions=("fake-credential",)
    )
    assert "fake-credential" not in capsys.readouterr().err
    assert recorder.event("bridge_started")
    assert attempts[-1][1] == "[REDACTED]"
    assert "recording recovered" in capsys.readouterr().err
    recorder.close()


def test_close_removes_only_owned_handlers(tmp_path):
    recorder = BridgeRecorder(config(tmp_path), "plaza", writer=FaultWriter())
    external = logging.NullHandler()
    recorder._logger.addHandler(external)
    owned = (recorder._archive, recorder._stderr)
    recorder.close()
    assert recorder._logger.handlers == [external]
    assert all(handler not in recorder._logger.handlers for handler in owned)


def test_real_unavailable_writer_recovers_after_competitor_closes(tmp_path, capsys):
    from bridge.log_storage import RunLogWriter

    cfg = config(tmp_path)
    owner = RunLogWriter(cfg, "owner")
    recorder = BridgeRecorder(cfg, "plaza")
    assert not recorder.event("bridge_started")
    assert not recorder.message(context(), "user", "private input", "input")
    assert "suspended" in capsys.readouterr().err
    owner.close()
    assert recorder.event("bridge_started")
    assert recorder.message(context(), "assistant", "reply", "success")
    assert "recovered" in capsys.readouterr().err
    recorder.close()
    assert len(records(cfg)) == 2


def test_agent_path_redaction_is_stable_distinct_and_preserves_capture(
    tmp_path, capsys
):
    cfg = config(
        tmp_path,
        transcript_max_record_bytes=4096,
        transcript_max_file_bytes=8192,
        log_max_total_bytes=32768,
    )
    secrets = ("fake-secret-one", "fake-secret-two")
    agents = (secrets[0], secrets[1], f"prefix-{secrets[0]}-suffix", "ordinary-agent")
    contexts = [
        context(agent_id=agent, request_id=f"req-{index}")
        for index, agent in enumerate(agents)
    ]
    recorder = BridgeRecorder(cfg, "plaza", redactions=secrets)
    body = "large safe reply " * 1000
    for ctx in contexts:
        assert recorder.message(ctx, "user", "question", "input")
        assert recorder.event("request_completed", ctx, outcome="success")
        assert recorder.message(ctx, "assistant", body, "success")
    recorder.close()

    paths = list(cfg.log_dir.rglob("*"))
    assert all(
        secret not in str(path.relative_to(cfg.log_dir))
        for path in paths
        for secret in secrets
    )
    assert all(
        secret.encode() not in path.read_bytes()
        for path in paths
        if path.is_file()
        for secret in secrets
    )
    stderr = capsys.readouterr().err
    assert all(secret not in stderr for secret in secrets)
    assert [ctx.agent_id for ctx in contexts] == list(agents)
    assert body == "large safe reply " * 1000

    folders = {}
    for path in cfg.log_dir.rglob("transcript-*.jsonl"):
        errors = []
        rows = list(iter_jsonl(path, on_diagnostic=errors.append))
        assert not errors
        assert path.stat().st_size <= cfg.transcript_max_file_bytes
        assert all(
            len(line) <= cfg.transcript_max_record_bytes
            for line in path.read_bytes().splitlines(keepends=True)
        )
        for row in rows:
            folders.setdefault(row["request_id"], set()).add(path.parent.name)
    assert set(folders) == {ctx.request_id for ctx in contexts}
    assert all(len(names) == 1 for names in folders.values())
    aliases = [next(iter(folders[ctx.request_id])) for ctx in contexts]
    assert len(set(aliases)) == len(agents)
    assert aliases[-1] == "ordinary-agent"
    assert len(records(cfg, "transcript-*.jsonl")) == 8
    assert (
        sum(
            path.stat().st_size
            for path in paths
            if path.is_file() and path.name != ".writer.lock"
        )
        <= cfg.log_max_total_bytes
    )
