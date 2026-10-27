"""Worker repository contracts exercised through actual anchored SQLite images."""

from dataclasses import replace
import hashlib
import importlib
import importlib.util
import json
import sqlite3
from uuid import uuid4

import pytest

from bridge.application_state import (
    COMPLETION_ALLOWANCE_BYTES,
    MAX_OUTPUT_BYTES,
    MAX_TASK_BYTES,
    RequestRecord,
    StateCommand,
    StateError,
)
from bridge.domain_protocol import DomainCommandError
from bridge.state_image import StateImage

STAMP = "2026-10-26T12:00:00Z"


@pytest.fixture
def api():
    assert importlib.util.find_spec("bridge.sqlite_state"), "SQLite repository missing"
    return importlib.import_module("bridge.sqlite_state")


@pytest.fixture
def owner(tmp_path, api):
    common = tmp_path / "common.git"
    common.mkdir()
    image = StateImage.open(
        common,
        "project-a",
        initialize=True,
        initial_image=lambda instance: api.initial_image("project-a", instance),
    )
    yield common, image
    image.close()


@pytest.fixture
def repo(owner, api):
    repository = api.SQLiteStateRepository(owner[1])
    yield repository
    repository.close()


def apply(repo, kind, **payload):
    return repo.apply(StateCommand(kind, payload))


def start(repo, domain="engineering", revision=0):
    return apply(
        repo,
        "start",
        domain_id=domain,
        expected_domain_revision=revision,
        boot_id=str(uuid4()),
        execution_id=str(uuid4()),
        timestamp=STAMP,
    ).result


def request(active, identity="one", task="work", **changes):
    return replace(
        RequestRecord(
            active["session_id"],
            identity,
            active["execution_id"],
            "backend-architect",
            task,
            hashlib.sha256(task.encode()).hexdigest(),
            str(uuid4()),
            1,
            "accepted",
            COMPLETION_ALLOWANCE_BYTES,
        ),
        **changes,
    )


def packet(record, output="done", **changes):
    return dict(
        type="domain_result",
        request_id=record.request_id,
        domain_session_id=record.session_id,
        execution_id=record.execution_id,
        agent_id=record.agent_id,
        task=record.task,
        output=output,
        memory={"saved": True},
        **changes,
    )


def complete(repo, active, identity="one", output="done", task="work"):
    record = request(active, identity, task)
    apply(repo, "accept", request=record)
    apply(repo, "dispatch", session_id=record.session_id, request_id=identity)
    return apply(
        repo,
        "terminal",
        session_id=record.session_id,
        request_id=identity,
        packet=packet(record, output),
    )


def error(code, callback):
    with pytest.raises(StateError) as caught:
        callback()
    assert caught.value.code == code
    assert str(caught.value) == code


def test_sqlite_reopen_exact_replay(repo, owner, api):
    active = start(repo)
    complete(repo, active, "one", "é")
    saved = complete(repo, active, "two").view
    repo.close()
    owner[1].close()
    reopened = StateImage.open(owner[0], "project-a")
    try:
        loaded = api.SQLiteStateRepository(reopened)
        assert loaded.load() == saved
        replay = api.replay_session(loaded.load(), active["session_id"], 0)
        assert [p["output_id"] for p in replay.entries] == ["1", "2"]
        assert replay.high_water_mark == 2
        assert replay.earliest_output_id == 1
        assert replay.history_gap is False
        assert loaded.load().instance_id == reopened.instance_id
        loaded.close()
    finally:
        reopened.close()


def test_count_trim_expires_completed_only(repo, api):
    active = start(repo)
    for i in range(258):
        complete(repo, active, str(i))
    pending = request(active, "unfinished")
    apply(repo, "accept", request=pending)
    view = repo.load()
    window = api.replay_session(view, active["session_id"], 0)
    assert [int(p["output_id"]) for p in window.entries] == list(range(3, 259))
    assert window.history_gap and window.high_water_mark == 258
    assert api.replay_session(view, active["session_id"], 2).history_gap is False
    assert {r.request_id for r in view.requests} == {
        *map(str, range(2, 258)),
        "unfinished",
    }
    assert next(r for r in view.requests if r.request_id == "unfinished") == pending


def test_trim_empty_preserves_highwater(repo, api, monkeypatch):
    # Production packet bounds prevent empty replay by a single oversized output;
    # lower only the retention budget to exercise that independent invariant.
    monkeypatch.setattr(api, "MAX_REPLAY_OUTPUT_BYTES", 0)
    active = start(repo)
    result = complete(repo, active)
    assert result.result["terminal"]["output_id"] == "1"
    assert result.view.terminals == result.view.requests == ()
    fresh = api.SQLiteStateRepository(repo.image)
    try:
        empty = api.replay_session(fresh.load(), active["session_id"], 0)
        assert empty.entries == [] and empty.high_water_mark == 1
        assert empty.earliest_output_id is None and empty.history_gap
        assert not api.replay_session(fresh.load(), active["session_id"], 1).history_gap
        assert complete(fresh, active, "next").result["terminal"]["output_id"] == "2"
    finally:
        fresh.close()


@pytest.mark.parametrize("cursor", [True, False, -1, 1.0, "1", None])
def test_replay_rejects_invalid_cursor(repo, api, cursor):
    active = start(repo)
    with pytest.raises(DomainCommandError) as caught:
        api.replay_session(repo.load(), active["session_id"], cursor)
    assert caught.value.code == "invalid_request"


def test_output_utf8_retention_ignores_metadata(repo, api):
    active = start(repo)
    for i in range(16):
        complete(repo, active, str(i), "é" * (MAX_OUTPUT_BYTES // 2), "t" * 1024)
    assert len(repo.load().terminals) == 16
    complete(repo, active, "extra", "x")
    window = api.replay_session(repo.load(), active["session_id"], 0)
    assert len(window.entries) == 16 and window.earliest_output_id == 2
    assert (
        sum(t.output_bytes for t in repo.load().terminals) == 15 * MAX_OUTPUT_BYTES + 1
    )


def test_duplicate_window_and_conflict(repo, api, monkeypatch):
    monkeypatch.setattr(api, "MAX_TERMINALS_PER_SESSION", 1)
    active = start(repo)
    record = request(active)
    first = apply(repo, "accept", request=record)
    assert apply(repo, "accept", request=record).view.revision == first.view.revision
    for changed in (
        replace(record, agent_id="other"),
        request(active, task="different"),
    ):
        error("state_store_invalid", lambda: apply(repo, "accept", request=changed))
    done = apply(
        repo,
        "terminal",
        session_id=record.session_id,
        request_id=record.request_id,
        packet=packet(record),
    )
    duplicate = apply(repo, "accept", request=record)
    assert duplicate.result["request"].disposition == "terminal"
    assert duplicate.view.revision == done.view.revision
    complete(repo, active, "two")
    assert (
        apply(repo, "accept", request=record).result["request"].disposition
        == "accepted"
    )


def test_limits_before_admission(repo, api, monkeypatch):
    active = start(repo)
    before = repo.load()
    for changed in (
        request(active, task="é" * (MAX_TASK_BYTES // 2 + 1)),
        request(active, allowance_bytes=0),
        request(active, memory_revision=True),
        request(active, task_digest="bad"),
    ):
        error(
            (
                "state_store_quota"
                if len(changed.task.encode()) > MAX_TASK_BYTES
                else "state_store_invalid"
            ),
            lambda: apply(repo, "accept", request=changed),
        )
        assert repo.load() == before
    record = request(active, task="é" * (MAX_TASK_BYTES // 2))
    apply(repo, "accept", request=record)
    error(
        "state_store_busy",
        lambda: apply(repo, "accept", request=request(active, "two")),
    )
    # Budget accounts for existing serialized pages plus all unfinished allowances.
    other = start(repo, "design")
    monkeypatch.setattr(
        api,
        "MAX_IMAGE_BYTES",
        len(repo.image.read()) + COMPLETION_ALLOWANCE_BYTES * 2 - 1,
    )
    error("state_store_quota", lambda: apply(repo, "accept", request=request(other)))
    assert len(repo.load().requests) == 1


def test_session_and_domain_limits_do_not_delete(repo):
    active = None
    for i in range(128):
        active = start(repo, revision=0 if i == 0 else 3 * i)
        apply(
            repo,
            "stop",
            execution_id=active["execution_id"],
            outcome="stopped",
            timestamp=STAMP,
        )
        apply(
            repo,
            "end",
            session_id=active["session_id"],
            expected_domain_revision=3 * i + 2,
            actor="user",
            timestamp=STAMP,
        )
    assert len(repo.load().sessions) == 128
    before = repo.load()
    error("state_store_quota", lambda: start(repo, revision=384))
    assert repo.load() == before


def test_ten_domains_limit(repo):
    for i in range(10):
        start(repo, f"domain-{i}")
    before = repo.load()
    error("state_store_quota", lambda: start(repo, "overflow"))
    assert len(repo.load().domains) == 10 and repo.load() == before


def test_packet_escaping_limit(repo):
    active = start(repo)
    record = request(active)
    apply(repo, "accept", request=record)
    base = packet(record, "é" * (MAX_OUTPUT_BYTES // 2))
    base["metadata"] = "\x00" * 300000
    # UTF-8 is used, rather than escaping every non-ASCII character.
    assert (
        len(json.dumps(base, ensure_ascii=False, separators=(",", ":")).encode())
        < 2 * 1024 * 1024
    )
    saved = apply(
        repo,
        "terminal",
        session_id=record.session_id,
        request_id=record.request_id,
        packet=base,
    )
    assert saved.view.terminals[0].output_bytes == MAX_OUTPUT_BYTES
    second = request(active, "two")
    apply(repo, "accept", request=second)
    large = packet(second, "\x00" * MAX_OUTPUT_BYTES)
    large["metadata"] = "\x00" * 100000
    before = repo.load()
    error(
        "state_store_quota",
        lambda: apply(
            repo,
            "terminal",
            session_id=second.session_id,
            request_id=second.request_id,
            packet=large,
        ),
    )
    assert repo.load() == before
    oversized = packet(second, "x" * (MAX_OUTPUT_BYTES + 1))
    error(
        "state_store_quota",
        lambda: apply(
            repo,
            "terminal",
            session_id=second.session_id,
            request_id=second.request_id,
            packet=oversized,
        ),
    )


def test_terminal_packet_exact_json_boundary(repo, api):
    active = start(repo)
    record = request(active)
    apply(repo, "accept", request=record)
    boundary = packet(record, metadata="", output_id="1")
    encoded_bytes = len(
        json.dumps(boundary, ensure_ascii=False, separators=(",", ":")).encode()
    )
    boundary["metadata"] = "x" * (api.MAX_TERMINAL_PACKET_BYTES - encoded_bytes)
    too_large = dict(boundary, metadata=boundary["metadata"] + "x")
    error(
        "state_store_quota",
        lambda: apply(
            repo,
            "terminal",
            session_id=record.session_id,
            request_id=record.request_id,
            packet=too_large,
        ),
    )
    saved = apply(
        repo,
        "terminal",
        session_id=record.session_id,
        request_id=record.request_id,
        packet=boundary,
    )
    assert saved.result["terminal"] == boundary


def test_exact_image_and_allowance_boundary(repo, api, monkeypatch):
    active = start(repo)
    size = len(repo.image.read())
    record = request(active)
    monkeypatch.setattr(api, "MAX_IMAGE_BYTES", size + COMPLETION_ALLOWANCE_BYTES - 1)
    error("state_store_quota", lambda: apply(repo, "accept", request=record))
    monkeypatch.setattr(api, "MAX_IMAGE_BYTES", size + COMPLETION_ALLOWANCE_BYTES)
    apply(repo, "accept", request=record)
    assert len(repo.image.read()) + COMPLETION_ALLOWANCE_BYTES == api.MAX_IMAGE_BYTES


def test_load_rejects_huge_highwater_without_materializing_range(
    repo, api, monkeypatch
):
    active = start(repo)
    complete(repo, active)
    connection = sqlite3.connect(":memory:")
    connection.deserialize(repo.image.read())
    connection.execute("UPDATE sessions SET high_water_mark=?", (api.MAX_INTEGER,))
    connection.commit()
    repo.image.replace(connection.serialize())
    connection.close()

    def bounded_range(*args):
        result = range(*args)
        assert (
            len(result) <= 256
        ), "corrupt highwater must not allocate an unbounded range"
        return result

    monkeypatch.setattr(api, "range", bounded_range, raising=False)
    error("state_store_invalid", lambda: api.SQLiteStateRepository(repo.image))


@pytest.mark.parametrize("character", ["x", "é"])
def test_load_rejects_oversized_packet_before_json_decode(
    repo, api, monkeypatch, character
):
    active = start(repo)
    complete(repo, active)
    before = repo.load()
    oversized = json.dumps(
        dict(
            before.terminals[0].packet,
            metadata=character
            * (api.MAX_TERMINAL_PACKET_BYTES // len(character.encode())),
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert len(oversized.encode()) > api.MAX_TERMINAL_PACKET_BYTES
    if character == "é":
        assert len(oversized) < api.MAX_TERMINAL_PACKET_BYTES
    connection = sqlite3.connect(":memory:")
    connection.deserialize(repo.image.read())
    connection.execute("UPDATE terminals SET packet=?", (oversized,))
    connection.commit()
    data = connection.serialize()
    connection.close()
    repo.image.replace(data)
    original_loads = json.loads

    def guarded_loads(value, *args, **kwargs):
        if isinstance(value, str):
            assert (
                len(value.encode()) <= api.MAX_TERMINAL_PACKET_BYTES
            ), "oversized stored packet reached JSON decoder"
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(api.json, "loads", guarded_loads)
    error("state_store_invalid", lambda: api.SQLiteStateRepository(repo.image))
    assert repo.image.read() == data and repo.load() == before


@pytest.mark.parametrize(
    "table,column", [("metadata", "revision"), ("domains", "domain_revision")]
)
def test_revision_exhaustion_preserves_committed_image(repo, api, table, column):
    active = start(repo)
    connection = sqlite3.connect(":memory:")
    connection.deserialize(repo.image.read())
    connection.execute(f"UPDATE {table} SET {column}=?", (api.MAX_INTEGER,))
    connection.commit()
    data = connection.serialize()
    connection.close()
    repo.image.replace(data)
    loaded = api.SQLiteStateRepository(repo.image)
    try:
        before = loaded.load()
        error(
            "state_store_quota",
            lambda: apply(
                loaded,
                "stop",
                execution_id=active["execution_id"],
                outcome="stopped",
                timestamp=STAMP,
            ),
        )
        assert loaded.load() == before and repo.image.read() == data
    finally:
        loaded.close()


@pytest.mark.parametrize(
    "damage",
    [
        "garbage",
        "project",
        "instance",
        "newer",
        "table",
        "view",
        "trigger",
        "foreignkey",
        "highwater",
        "request",
        "packet",
    ],
)
def test_load_rejects_foreign_or_corrupt_image(repo, api, damage):
    active = start(repo)
    complete(repo, active)
    original = repo.image.read()
    if damage == "garbage":
        candidate = b"not sqlite"
    else:
        connection = sqlite3.connect(":memory:")
        connection.deserialize(original)
        connection.execute("PRAGMA foreign_keys=OFF")
        changes = {
            "project": "UPDATE metadata SET project_id='foreign'",
            "instance": f"UPDATE metadata SET instance_id='{uuid4()}'",
            "newer": "PRAGMA user_version=2",
            "table": "CREATE TABLE surprise (x)",
            "view": "CREATE VIEW surprise AS SELECT 1",
            "trigger": "CREATE TRIGGER surprise AFTER INSERT ON domains BEGIN SELECT 1; END",
            "foreignkey": "UPDATE terminals SET request_id='missing'",
            "highwater": "UPDATE sessions SET high_water_mark=0",
            "request": "UPDATE requests SET disposition='accepted', allowance_bytes=2097152",
            "packet": "UPDATE terminals SET packet='{}'",
        }
        connection.execute(changes[damage])
        connection.commit()
        candidate = connection.serialize()
        connection.close()
    repo.image.replace(candidate)
    error(
        "state_store_unsupported" if damage == "newer" else "state_store_invalid",
        lambda: api.SQLiteStateRepository(repo.image),
    )
    assert repo.image.read() == candidate
    assert repo.load().terminals[0].output_id == 1


def test_delete_compacts_image(repo, owner, api, monkeypatch):
    active = start(repo)
    complete(repo, active, output="x" * MAX_OUTPUT_BYTES)
    before = len(repo.image.read())
    error(
        "state_store_invalid",
        lambda: apply(repo, "delete_ended", session_ids=[active["session_id"]]),
    )
    apply(
        repo,
        "stop",
        execution_id=active["execution_id"],
        outcome="stopped",
        timestamp=STAMP,
    )
    apply(
        repo,
        "end",
        session_id=active["session_id"],
        expected_domain_revision=2,
        actor="user",
        timestamp=STAMP,
    )
    files_before = {p.relative_to(owner[0]) for p in owner[0].rglob("*") if p.is_file()}
    observations = []
    original_connect = api._connect

    def observe_compaction():
        connection = original_connect()

        def trace(statement):
            if statement == "VACUUM":
                observations.append(
                    (
                        connection.getlimit(sqlite3.SQLITE_LIMIT_ATTACHED),
                        connection.execute("PRAGMA temp_store").fetchone()[0],
                        connection.execute("PRAGMA journal_mode").fetchone()[0],
                        connection.execute("PRAGMA database_list").fetchall(),
                    )
                )

        connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(api, "_connect", observe_compaction)
    # Deletion must compact before comparing the candidate against the quota.
    monkeypatch.setattr(api, "MAX_IMAGE_BYTES", before // 2)
    deleted = apply(repo, "delete_ended", session_ids=[active["session_id"]])
    assert deleted.result == {"deleted_session_ids": (active["session_id"],)}
    assert (
        deleted.view.sessions
        == deleted.view.executions
        == deleted.view.requests
        == deleted.view.terminals
        == ()
    )
    assert len(repo.image.read()) < before // 2
    assert observations == [(1, 2, "memory", [(0, "main", "")])]
    assert repo._connection.getlimit(sqlite3.SQLITE_LIMIT_ATTACHED) == 0
    assert {
        p.relative_to(owner[0]) for p in owner[0].rglob("*") if p.is_file()
    } == files_before
    assert api.SQLiteStateRepository(owner[1]).load() == deleted.view


def test_lifecycle_fences_end_and_recovers_once(repo):
    active = start(repo)
    error("state_store_invalid", lambda: start(repo))
    error(
        "state_store_busy",
        lambda: apply(
            repo,
            "end",
            session_id=active["session_id"],
            expected_domain_revision=1,
            actor="user",
            timestamp=STAMP,
        ),
    )
    record = request(active)
    apply(repo, "accept", request=record)
    recovered = apply(
        repo,
        "recover",
        session_id=record.session_id,
        request_id=record.request_id,
        packet=packet(record, "Not executed"),
        timestamp=STAMP,
    )
    assert recovered.view.executions[0].outcome == "recovered"
    assert recovered.view.requests[0].disposition == "recovered"
    assert recovered.view.domains[0].domain_revision == 2
    again = apply(
        repo,
        "recover",
        session_id=record.session_id,
        request_id=record.request_id,
        packet=packet(record, "Not executed"),
        timestamp=STAMP,
    )
    assert again == recovered
    error(
        "state_store_invalid",
        lambda: apply(
            repo,
            "recover",
            session_id=record.session_id,
            request_id=record.request_id,
            packet=packet(record, "changed"),
            timestamp=STAMP,
        ),
    )
    stopped = apply(
        repo,
        "stop",
        execution_id=active["execution_id"],
        outcome="stopped",
        timestamp=STAMP,
    )
    assert stopped.view.revision == recovered.view.revision
    ended = apply(
        repo,
        "end",
        session_id=record.session_id,
        expected_domain_revision=2,
        actor="bridge",
        timestamp=STAMP,
    )
    assert ended.view.sessions[0].ended_by == "bridge"
    assert (
        apply(
            repo,
            "end",
            session_id=record.session_id,
            expected_domain_revision=3,
            actor="bridge",
            timestamp=STAMP,
        ).view
        == ended.view
    )
    assert start(repo, revision=3)["session_id"] != record.session_id


def test_stopped_start_reuses_open_identity(repo):
    first = start(repo)
    apply(
        repo,
        "stop",
        execution_id=first["execution_id"],
        outcome="stopped",
        timestamp=STAMP,
    )
    second = start(repo, revision=2)
    assert second["session_id"] == first["session_id"]
    assert second["execution_id"] != first["execution_id"]
    assert len(repo.load().sessions) == 1


def test_recovery_preserves_committed_success_and_stops_execution_once(repo):
    active = start(repo)
    record = request(active)
    apply(repo, "accept", request=record)
    committed = apply(
        repo,
        "terminal",
        session_id=record.session_id,
        request_id=record.request_id,
        packet=packet(record, "success"),
    )
    recovered = apply(
        repo,
        "recover",
        session_id=record.session_id,
        request_id=record.request_id,
        packet=committed.result["terminal"],
        timestamp=STAMP,
    )
    assert recovered.view.terminals == committed.view.terminals
    assert recovered.view.requests == committed.view.requests
    assert recovered.result == committed.result
    assert recovered.view.executions[0].outcome == "recovered"
    assert recovered.view.executions[0].stopped_at == STAMP
    assert recovered.view.revision == committed.view.revision + 1
    assert recovered.view.domains[0].domain_revision == 2
    assert (
        apply(
            repo,
            "recover",
            session_id=record.session_id,
            request_id=record.request_id,
            packet=committed.result["terminal"],
            timestamp=STAMP,
        )
        == recovered
    )


def test_failed_candidate_never_publishes_and_copies_are_defensive(repo, monkeypatch):
    active = start(repo)
    record = request(active)
    apply(repo, "accept", request=record)
    before = repo.load()
    image = repo.image.read()
    original_replace = repo.image.replace

    def fail(_):
        raise StateError("state_store_failed")

    monkeypatch.setattr(repo.image, "replace", fail)
    error(
        "state_store_failed",
        lambda: apply(
            repo,
            "terminal",
            session_id=record.session_id,
            request_id=record.request_id,
            packet=packet(record),
        ),
    )
    assert repo.load() == before and repo.image.read() == image
    monkeypatch.setattr(repo.image, "replace", original_replace)
    source = packet(record)
    command = StateCommand(
        "terminal",
        dict(session_id=record.session_id, request_id=record.request_id, packet=source),
    )
    source["memory"]["saved"] = False
    saved = repo.apply(command)
    saved.result["terminal"]["memory"]["saved"] = False
    saved.view.terminals[0].packet["memory"]["saved"] = False
    assert repo.load().terminals[0].packet["memory"] == {"saved": True}


def test_uncertain_replace_keeps_prior_view_until_reopen(repo, api, monkeypatch):
    active = start(repo)
    record = request(active)
    apply(repo, "accept", request=record)
    before = repo.load()
    original_replace = repo.image.replace

    def uncertain(data):
        original_replace(data)
        raise StateError("state_store_uncertain", uncertain=True)

    monkeypatch.setattr(repo.image, "replace", uncertain)
    with pytest.raises(StateError) as caught:
        apply(
            repo,
            "terminal",
            session_id=record.session_id,
            request_id=record.request_id,
            packet=packet(record),
        )
    assert caught.value.code == "state_store_uncertain" and caught.value.uncertain
    assert repo.load() == before
    reopened = api.SQLiteStateRepository(repo.image)
    try:
        assert reopened.load().revision == before.revision + 1
        assert reopened.load().terminals[0].packet["output_id"] == "1"
    finally:
        reopened.close()


@pytest.mark.parametrize("actor", ["system", None, True])
def test_end_rejects_unknown_actor_without_mutation(repo, actor):
    active = start(repo)
    apply(
        repo,
        "stop",
        execution_id=active["execution_id"],
        outcome="stopped",
        timestamp=STAMP,
    )
    before, data = repo.load(), repo.image.read()
    error(
        "state_store_invalid",
        lambda: apply(
            repo,
            "end",
            session_id=active["session_id"],
            expected_domain_revision=2,
            actor=actor,
            timestamp=STAMP,
        ),
    )
    assert repo.load() == before and repo.image.read() == data
