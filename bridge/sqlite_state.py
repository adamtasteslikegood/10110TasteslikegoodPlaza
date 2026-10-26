"""Worker-owned bounded SQLite images; durable replacement precedes publication.

There are no live SQLite files, migrations, runtime objects or SDK calls here.
The coordinator owns threading and admission after uncertain image replacement.
"""

from copy import deepcopy
from dataclasses import astuple
import hashlib
import json
import sqlite3
from uuid import UUID, uuid4

from bridge.application_state import (
    COMPLETION_ALLOWANCE_BYTES,
    MAX_DOMAINS,
    MAX_IMAGE_BYTES,
    MAX_OUTPUT_BYTES,
    MAX_REPLAY_OUTPUT_BYTES,
    MAX_SESSIONS,
    MAX_TASK_BYTES,
    MAX_TERMINAL_PACKET_BYTES,
    MAX_TERMINALS_PER_SESSION,
    DomainRecord,
    ExecutionRecord,
    RequestRecord,
    SessionRecord,
    StateCommand,
    StateCommit,
    StateError,
    StateView,
    TerminalRecord,
)
from bridge.domain_protocol import DomainCommandError, valid_domain
from bridge.domain_store import ReplayWindow
from bridge.state_image import StateImage

APPLICATION_ID = 0x504C5A41
SCHEMA_VERSION = 1
MAX_INTEGER = 2**63 - 1

# SQL is fixed and compared byte-for-byte on load, including all constraints and
# indexes. No image-supplied SQL, views, triggers or extension functions run.
SCHEMA = (
    """CREATE TABLE metadata (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        schema_version INTEGER NOT NULL CHECK(schema_version=1),
        project_id TEXT NOT NULL, instance_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision>=0))""",
    """CREATE TABLE domains (
        domain_id TEXT PRIMARY KEY NOT NULL,
        current_session_id TEXT REFERENCES sessions(session_id)
            DEFERRABLE INITIALLY DEFERRED,
        domain_revision INTEGER NOT NULL CHECK(domain_revision>=0))""",
    """CREATE TABLE sessions (
        session_id TEXT PRIMARY KEY NOT NULL,
        domain_id TEXT NOT NULL REFERENCES domains(domain_id),
        created_at TEXT NOT NULL, ended_at TEXT, ended_by TEXT,
        high_water_mark INTEGER NOT NULL CHECK(high_water_mark>=0),
        CHECK((ended_at IS NULL AND ended_by IS NULL) OR
            (ended_at IS NOT NULL AND ended_by IN ('user','bridge'))))""",
    """CREATE UNIQUE INDEX one_open_session ON sessions(domain_id)
        WHERE ended_at IS NULL""",
    """CREATE TABLE executions (
        execution_id TEXT PRIMARY KEY NOT NULL,
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        boot_id TEXT NOT NULL, started_at TEXT NOT NULL,
        stopped_at TEXT, outcome TEXT,
        CHECK((stopped_at IS NULL AND outcome IS NULL) OR
            (stopped_at IS NOT NULL AND outcome IS NOT NULL)),
        UNIQUE(execution_id,session_id))""",
    """CREATE UNIQUE INDEX one_live_execution ON executions(session_id)
        WHERE stopped_at IS NULL""",
    """CREATE TABLE requests (
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        request_id TEXT NOT NULL, execution_id TEXT NOT NULL,
        agent_id TEXT NOT NULL, task TEXT NOT NULL, task_digest TEXT NOT NULL,
        turn_id TEXT NOT NULL, memory_revision INTEGER NOT NULL CHECK(memory_revision>=0),
        disposition TEXT NOT NULL CHECK(disposition IN
            ('accepted','dispatched','terminal','recovered')),
        allowance_bytes INTEGER NOT NULL,
        CHECK((disposition IN ('accepted','dispatched') AND allowance_bytes=2097152)
            OR (disposition IN ('terminal','recovered') AND allowance_bytes=0)),
        PRIMARY KEY(session_id,request_id),
        FOREIGN KEY(execution_id,session_id)
            REFERENCES executions(execution_id,session_id) ON DELETE CASCADE)""",
    """CREATE UNIQUE INDEX one_unfinished_request ON requests(session_id)
        WHERE disposition IN ('accepted','dispatched')""",
    """CREATE TABLE terminals (
        session_id TEXT NOT NULL, request_id TEXT NOT NULL,
        output_id INTEGER NOT NULL CHECK(output_id>0), packet TEXT NOT NULL,
        output_bytes INTEGER NOT NULL CHECK(output_bytes>=0),
        PRIMARY KEY(session_id,output_id), UNIQUE(session_id,request_id),
        FOREIGN KEY(session_id,request_id)
            REFERENCES requests(session_id,request_id) ON DELETE CASCADE)""",
)


def _invalid():
    raise StateError("state_store_invalid")


def _text(value, limit=128, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        _invalid()
    if len(value.encode("utf-8")) > limit:
        _invalid()


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        _invalid()


def _integer(value):
    if type(value) is not int or not 0 <= value <= MAX_INTEGER:
        _invalid()


def _bound_text(value, limit):
    if not isinstance(value, str):
        _invalid()
    if len(value.encode("utf-8")) > limit:
        raise StateError("state_store_quota")


def _connect():
    connection = sqlite3.connect(":memory:")
    try:
        # Some Python builds omit extension loading entirely, which is already
        # stricter than disabling it. serialize/deserialize are mandatory.
        if hasattr(connection, "enable_load_extension"):
            connection.enable_load_extension(False)
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=MEMORY")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_IMAGE_BYTES)
        return connection
    except Exception:
        connection.close()
        raise


def _create(connection):
    connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    for statement in SCHEMA:
        connection.execute(statement)


def _schema_objects(connection):
    return connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
    ).fetchall()


def _expected_schema():
    connection = _connect()
    try:
        _create(connection)
        return _schema_objects(connection)
    finally:
        connection.close()


def initial_image(project_id: str, instance_id: str) -> bytes:
    """Create schema v1 bound to the manifest's single generated instance UUID."""
    connection = None
    try:
        _text(project_id)
        _uuid(instance_id)
        connection = _connect()
        _create(connection)
        connection.execute(
            "INSERT INTO metadata VALUES (1,1,?,?,0)", (project_id, instance_id)
        )
        connection.commit()
        data = connection.serialize()
        if len(data) > MAX_IMAGE_BYTES:
            raise StateError("state_store_quota")
        return data
    except StateError:
        raise
    except (ValueError, TypeError, UnicodeError):
        raise StateError("state_store_invalid") from None
    except (sqlite3.Error, AttributeError):
        raise StateError("state_store_unsupported") from None
    finally:
        if connection is not None:
            connection.close()


def replay_session(view: StateView, session_id: str, cursor: int) -> ReplayWindow:
    """Read retained IDs without appending loaded history into a fresh store."""
    if type(cursor) is not int or cursor < 0:
        raise DomainCommandError()
    session = next((s for s in view.sessions if s.session_id == session_id), None)
    if session is None:
        raise DomainCommandError("session_unavailable")
    terminals = sorted(
        (t for t in view.terminals if t.session_id == session_id),
        key=lambda t: t.output_id,
    )
    earliest = terminals[0].output_id if terminals else session.high_water_mark + 1
    return ReplayWindow(
        [deepcopy(t.packet) for t in terminals if cursor < t.output_id],
        session.high_water_mark,
        earliest if terminals else None,
        cursor < earliest - 1,
    )


def _request_valid(record):
    _uuid(record.session_id)
    _uuid(record.execution_id)
    _uuid(record.turn_id)
    _text(record.request_id)
    _text(record.agent_id)
    _bound_text(record.task, MAX_TASK_BYTES)
    if not record.task.strip():
        _invalid()
    if hashlib.sha256(record.task.encode("utf-8")).hexdigest() != record.task_digest:
        _invalid()
    _integer(record.memory_revision)
    if record.disposition not in {"accepted", "dispatched", "terminal", "recovered"}:
        _invalid()
    allowance = (
        COMPLETION_ALLOWANCE_BYTES
        if record.disposition in {"accepted", "dispatched"}
        else 0
    )
    if type(record.allowance_bytes) is not int or record.allowance_bytes != allowance:
        _invalid()


def _packet(record, packet, output_id):
    if not isinstance(packet, dict):
        _invalid()
    expected = {
        "request_id": record.request_id,
        "agent_id": record.agent_id,
        "task": record.task,
    }
    if any(packet.get(k) != v for k, v in expected.items()):
        _invalid()
    for key, value in (
        ("domain_session_id", record.session_id),
        ("execution_id", record.execution_id),
    ):
        if key in packet and packet[key] != value:
            _invalid()
    _bound_text(packet.get("output"), MAX_OUTPUT_BYTES)
    result = deepcopy(packet)
    result["output_id"] = str(output_id)
    encoded = json.dumps(
        result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(encoded.encode("utf-8")) > MAX_TERMINAL_PACKET_BYTES:
        raise StateError("state_store_quota")
    # Reject values that json.dumps silently coerces, e.g. nonstring dict keys or
    # tuples, so the committed view is the same before and after reopening.
    if json.loads(encoded) != result:
        _invalid()
    return result, encoded, len(result["output"].encode("utf-8"))


def _stored_packet(packet):
    # Bound persisted text before the decoder and TerminalRecord's deep copy.
    # The character check also bounds the temporary UTF-8 encoding allocation.
    if (
        not isinstance(packet, str)
        or len(packet) > MAX_TERMINAL_PACKET_BYTES
        or len(packet.encode("utf-8")) > MAX_TERMINAL_PACKET_BYTES
    ):
        _invalid()
    return json.loads(packet)


class SQLiteStateRepository:
    """Use only on the owning worker. The caller retains StateImage ownership."""

    def __init__(self, image: StateImage):
        self.image = image
        self._connection = None
        candidate = None
        try:
            data = image.read()
            if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE_BYTES:
                _invalid()
            candidate = _connect()
            candidate.deserialize(data)
            self._validate(candidate)
            self._connection = candidate
            candidate = None
        except StateError:
            raise
        except (sqlite3.Error, ValueError, TypeError, OverflowError, RecursionError):
            raise StateError("state_store_invalid") from None
        finally:
            if candidate is not None:
                candidate.close()

    def _view(self, connection):
        project_id, instance_id, revision = connection.execute(
            "SELECT project_id,instance_id,revision FROM metadata"
        ).fetchone()
        domains = tuple(
            DomainRecord(*row)
            for row in connection.execute("SELECT * FROM domains ORDER BY domain_id")
        )
        sessions = tuple(
            SessionRecord(*row)
            for row in connection.execute("SELECT * FROM sessions ORDER BY session_id")
        )
        executions = tuple(
            ExecutionRecord(*row)
            for row in connection.execute(
                "SELECT * FROM executions ORDER BY execution_id"
            )
        )
        requests = tuple(
            RequestRecord(*row)
            for row in connection.execute(
                "SELECT * FROM requests ORDER BY session_id,request_id"
            )
        )
        terminals = tuple(
            TerminalRecord(sid, rid, oid, _stored_packet(packet), size)
            for sid, rid, oid, packet, size in connection.execute(
                "SELECT * FROM terminals ORDER BY session_id,output_id"
            )
        )
        return StateView(
            project_id,
            instance_id,
            revision,
            domains,
            sessions,
            executions,
            requests,
            terminals,
        )

    def _validate(self, connection):
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise StateError("state_store_unsupported")
        if (
            version != SCHEMA_VERSION
            or connection.execute("PRAGMA application_id").fetchone()[0]
            != APPLICATION_ID
            or _schema_objects(connection) != _expected_schema()
        ):
            _invalid()
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            _invalid()
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            _invalid()
        if connection.execute("SELECT count(*) FROM metadata").fetchone()[0] != 1:
            _invalid()
        # Reject row explosions before constructing records/decoding JSON.
        for table, maximum in (
            ("domains", MAX_DOMAINS),
            ("sessions", MAX_SESSIONS),
            ("terminals", MAX_SESSIONS * MAX_TERMINALS_PER_SESSION),
            ("requests", MAX_SESSIONS * MAX_TERMINALS_PER_SESSION + MAX_DOMAINS),
        ):
            if (
                connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                > maximum
            ):
                _invalid()
        view = self._view(connection)
        _text(view.project_id)
        _uuid(view.instance_id)
        _integer(view.revision)
        if (
            view.project_id != self.image.project_id
            or view.instance_id != self.image.instance_id
        ):
            _invalid()
        sessions = {s.session_id: s for s in view.sessions}
        domains = {d.domain_id: d for d in view.domains}
        executions = {e.execution_id: e for e in view.executions}
        requests = {(r.session_id, r.request_id): r for r in view.requests}
        terminals = {(t.session_id, t.request_id): t for t in view.terminals}
        unfinished_domains = set()
        for domain in view.domains:
            if not valid_domain(domain.domain_id):
                _invalid()
            _integer(domain.domain_revision)
            if domain.current_session_id is not None:
                current = sessions[domain.current_session_id]
                if (
                    current.domain_id != domain.domain_id
                    or current.ended_at is not None
                ):
                    _invalid()
        for session in view.sessions:
            _uuid(session.session_id)
            _text(session.created_at)
            _integer(session.high_water_mark)
            if session.ended_at is None:
                if domains[session.domain_id].current_session_id != session.session_id:
                    _invalid()
            else:
                _text(session.ended_at)
                if session.ended_by not in {"user", "bridge"}:
                    _invalid()
            retained = [t for t in view.terminals if t.session_id == session.session_id]
            if (
                len(retained) > MAX_TERMINALS_PER_SESSION
                or sum(t.output_bytes for t in retained) > MAX_REPLAY_OUTPUT_BYTES
            ):
                _invalid()
            ids = [t.output_id for t in retained]
            if ids and (
                ids[-1] != session.high_water_mark
                or any(right != left + 1 for left, right in zip(ids, ids[1:]))
            ):
                _invalid()
        for execution in view.executions:
            _uuid(execution.execution_id)
            _uuid(execution.boot_id)
            _text(execution.started_at)
            if execution.stopped_at is None:
                if sessions[execution.session_id].ended_at is not None:
                    _invalid()
            else:
                _text(execution.stopped_at)
                _text(execution.outcome)
        for record in view.requests:
            _request_valid(record)
            if executions[record.execution_id].session_id != record.session_id:
                _invalid()
            terminal = terminals.get((record.session_id, record.request_id))
            if record.disposition in {"accepted", "dispatched"}:
                domain = sessions[record.session_id].domain_id
                if (
                    terminal is not None
                    or domain in unfinished_domains
                    or sessions[record.session_id].ended_at is not None
                ):
                    _invalid()
                unfinished_domains.add(domain)
            elif terminal is None:
                _invalid()
        for terminal in view.terminals:
            _integer(terminal.output_id)
            record = requests[(terminal.session_id, terminal.request_id)]
            packet, _, size = _packet(record, terminal.packet, terminal.output_id)
            if packet != terminal.packet or size != terminal.output_bytes:
                _invalid()
        # The allowance is an admission promise, not proof of free disk space.
        if (
            len(connection.serialize()) + sum(r.allowance_bytes for r in view.requests)
            > MAX_IMAGE_BYTES
        ):
            _invalid()

    def load(self) -> StateView:
        if self._connection is None:
            _invalid()
        return self._view(self._connection)

    def apply(self, command: StateCommand) -> StateCommit:
        if self._connection is None:
            _invalid()
        candidate = None
        try:
            candidate = _connect()
            candidate.deserialize(self._connection.serialize())
            candidate.execute("BEGIN")
            result, changed = getattr(self, "_" + command.kind)(
                candidate, **command.payload
            )
            if not changed:
                return StateCommit(self.load(), result)
            if (
                candidate.execute("SELECT revision FROM metadata").fetchone()[0]
                >= MAX_INTEGER
            ):
                raise StateError("state_store_quota")
            candidate.execute("UPDATE metadata SET revision=revision+1")
            candidate.commit()
            if command.kind == "delete_ended":
                # VACUUM internally attaches its transient database. Both it
                # and the main database remain in memory; callers cannot attach
                # another database outside this fixed compaction statement.
                previous_limit = candidate.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 1)
                try:
                    candidate.execute("VACUUM")
                finally:
                    candidate.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, previous_limit)
            data = candidate.serialize()
            allowance = candidate.execute(
                "SELECT coalesce(sum(allowance_bytes),0) FROM requests"
            ).fetchone()[0]
            if len(data) + allowance > MAX_IMAGE_BYTES:
                raise StateError("state_store_quota")
            view = self._view(candidate)
            self.image.replace(data)
            self._connection.close()
            self._connection, candidate = candidate, None
            return StateCommit(view, result)
        except StateError:
            raise
        except (
            sqlite3.Error,
            ValueError,
            TypeError,
            AttributeError,
            KeyError,
            OverflowError,
            RecursionError,
        ):
            raise StateError("state_store_invalid") from None
        finally:
            if candidate is not None:
                candidate.close()

    @staticmethod
    def _session(connection, session_id):
        _uuid(session_id)
        row = connection.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            _invalid()
        return SessionRecord(*row)

    @staticmethod
    def _request(connection, session_id, request_id):
        _uuid(session_id)
        _text(request_id)
        row = connection.execute(
            "SELECT * FROM requests WHERE session_id=? AND request_id=?",
            (session_id, request_id),
        ).fetchone()
        if row is None:
            _invalid()
        return RequestRecord(*row)

    @staticmethod
    def _bump(connection, domain_id):
        revision = connection.execute(
            "SELECT domain_revision FROM domains WHERE domain_id=?", (domain_id,)
        ).fetchone()[0]
        if revision >= MAX_INTEGER:
            raise StateError("state_store_quota")
        connection.execute(
            "UPDATE domains SET domain_revision=domain_revision+1 WHERE domain_id=?",
            (domain_id,),
        )
        return connection.execute(
            "SELECT domain_revision FROM domains WHERE domain_id=?", (domain_id,)
        ).fetchone()[0]

    def _start(
        self,
        connection,
        *,
        domain_id,
        expected_domain_revision,
        boot_id,
        execution_id,
        timestamp,
    ):
        if not valid_domain(domain_id):
            _invalid()
        _integer(expected_domain_revision)
        _uuid(boot_id)
        _uuid(execution_id)
        _text(timestamp)
        domain = connection.execute(
            "SELECT * FROM domains WHERE domain_id=?", (domain_id,)
        ).fetchone()
        revision = domain[2] if domain else 0
        if expected_domain_revision != revision:
            _invalid()
        if domain is None:
            if (
                connection.execute("SELECT count(*) FROM domains").fetchone()[0]
                >= MAX_DOMAINS
            ):
                raise StateError("state_store_quota")
            connection.execute("INSERT INTO domains VALUES (?,NULL,0)", (domain_id,))
        session_id = domain[1] if domain else None
        if session_id is None:
            if (
                connection.execute("SELECT count(*) FROM sessions").fetchone()[0]
                >= MAX_SESSIONS
            ):
                raise StateError("state_store_quota")
            session_id = str(uuid4())
            connection.execute(
                "INSERT INTO sessions VALUES (?,?,?,NULL,NULL,0)",
                (session_id, domain_id, timestamp),
            )
            connection.execute(
                "UPDATE domains SET current_session_id=? WHERE domain_id=?",
                (session_id, domain_id),
            )
        elif (
            connection.execute(
                "SELECT 1 FROM executions WHERE session_id=? AND stopped_at IS NULL",
                (session_id,),
            ).fetchone()
            or connection.execute(
                "SELECT 1 FROM requests WHERE session_id=? AND disposition IN ('accepted','dispatched')",
                (session_id,),
            ).fetchone()
        ):
            raise StateError("state_store_busy")
        connection.execute(
            "INSERT INTO executions VALUES (?,?,?,?,NULL,NULL)",
            (execution_id, session_id, boot_id, timestamp),
        )
        revision = self._bump(connection, domain_id)
        return (
            dict(
                session_id=session_id,
                execution_id=execution_id,
                domain_revision=revision,
            ),
            True,
        )

    def _accept(self, connection, *, request):
        if not isinstance(request, RequestRecord):
            _invalid()
        _request_valid(request)
        if request.disposition != "accepted":
            _invalid()
        session = self._session(connection, request.session_id)
        existing = connection.execute(
            "SELECT * FROM requests WHERE session_id=? AND request_id=?",
            (request.session_id, request.request_id),
        ).fetchone()
        if existing:
            existing = RequestRecord(*existing)
            if (existing.task, existing.agent_id, existing.task_digest) != (
                request.task,
                request.agent_id,
                request.task_digest,
            ):
                _invalid()
            return {"request": existing}, False
        execution = connection.execute(
            "SELECT session_id,stopped_at FROM executions WHERE execution_id=?",
            (request.execution_id,),
        ).fetchone()
        if session.ended_at is not None or execution != (request.session_id, None):
            _invalid()
        if connection.execute(
            "SELECT 1 FROM requests JOIN sessions USING(session_id) WHERE domain_id=? AND disposition IN ('accepted','dispatched')",
            (session.domain_id,),
        ).fetchone():
            raise StateError("state_store_busy")
        connection.execute(
            "INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?)", astuple(request)
        )
        return {"request": request}, True

    def _dispatch(self, connection, *, session_id, request_id):
        record = self._request(connection, session_id, request_id)
        if record.disposition != "accepted":
            return {"request": record}, False
        execution = connection.execute(
            "SELECT stopped_at FROM executions WHERE execution_id=?",
            (record.execution_id,),
        ).fetchone()
        if execution[0] is not None:
            _invalid()
        connection.execute(
            "UPDATE requests SET disposition='dispatched' WHERE session_id=? AND request_id=?",
            (session_id, request_id),
        )
        return {"request": self._request(connection, session_id, request_id)}, True

    def _terminal(self, connection, *, session_id, request_id, packet):
        return self._save_terminal(
            connection, session_id, request_id, packet, "terminal"
        )

    def _save_terminal(self, connection, session_id, request_id, packet, disposition):
        record = self._request(connection, session_id, request_id)
        old = connection.execute(
            "SELECT output_id,packet FROM terminals WHERE session_id=? AND request_id=?",
            (session_id, request_id),
        ).fetchone()
        if old:
            result, _, _ = _packet(record, packet, old[0])
            if result != json.loads(old[1]):
                _invalid()
            return {"terminal": result}, False
        if record.disposition not in {"accepted", "dispatched"}:
            _invalid()
        session = self._session(connection, session_id)
        if session.high_water_mark >= MAX_INTEGER:
            raise StateError("state_store_quota")
        output_id = session.high_water_mark + 1
        result, encoded, output_bytes = _packet(record, packet, output_id)
        connection.execute(
            "UPDATE sessions SET high_water_mark=? WHERE session_id=?",
            (output_id, session_id),
        )
        connection.execute(
            "UPDATE requests SET disposition=?,allowance_bytes=0 WHERE session_id=? AND request_id=?",
            (disposition, session_id, request_id),
        )
        connection.execute(
            "INSERT INTO terminals VALUES (?,?,?,?,?)",
            (session_id, request_id, output_id, encoded, output_bytes),
        )
        count, size = connection.execute(
            "SELECT count(*),coalesce(sum(output_bytes),0) FROM terminals WHERE session_id=?",
            (session_id,),
        ).fetchone()
        while count > MAX_TERMINALS_PER_SESSION or size > MAX_REPLAY_OUTPUT_BYTES:
            oldest_id, oldest_size = connection.execute(
                "SELECT request_id,output_bytes FROM terminals WHERE session_id=? ORDER BY output_id LIMIT 1",
                (session_id,),
            ).fetchone()
            # Only the completed request correlated with an expired terminal is
            # removed. Unfinished acceptance is never retention fodder.
            connection.execute(
                "DELETE FROM requests WHERE session_id=? AND request_id=? AND disposition IN ('terminal','recovered')",
                (session_id, oldest_id),
            )
            count -= 1
            size -= oldest_size
        return {"terminal": result}, True

    def _stop(self, connection, *, execution_id, outcome, timestamp):
        _uuid(execution_id)
        _text(outcome)
        _text(timestamp)
        row = connection.execute(
            "SELECT session_id,stopped_at FROM executions WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
        if row is None:
            _invalid()
        session = self._session(connection, row[0])
        revision = connection.execute(
            "SELECT domain_revision FROM domains WHERE domain_id=?",
            (session.domain_id,),
        ).fetchone()[0]
        if row[1] is not None:
            return {"domain_revision": revision}, False
        connection.execute(
            "UPDATE executions SET stopped_at=?,outcome=? WHERE execution_id=?",
            (timestamp, outcome, execution_id),
        )
        return {"domain_revision": self._bump(connection, session.domain_id)}, True

    def _end(
        self, connection, *, session_id, expected_domain_revision, actor, timestamp
    ):
        session = self._session(connection, session_id)
        _integer(expected_domain_revision)
        _text(timestamp)
        if actor not in {"user", "bridge"}:
            _invalid()
        revision = connection.execute(
            "SELECT domain_revision FROM domains WHERE domain_id=?",
            (session.domain_id,),
        ).fetchone()[0]
        if revision != expected_domain_revision:
            _invalid()
        if session.ended_at is not None:
            return {"domain_revision": revision}, False
        if (
            connection.execute(
                "SELECT 1 FROM executions WHERE session_id=? AND stopped_at IS NULL",
                (session_id,),
            ).fetchone()
            or connection.execute(
                "SELECT 1 FROM requests WHERE session_id=? AND disposition IN ('accepted','dispatched')",
                (session_id,),
            ).fetchone()
        ):
            raise StateError("state_store_busy")
        connection.execute(
            "UPDATE sessions SET ended_at=?,ended_by=? WHERE session_id=?",
            (timestamp, actor, session_id),
        )
        connection.execute(
            "UPDATE domains SET current_session_id=NULL WHERE domain_id=?",
            (session.domain_id,),
        )
        return {"domain_revision": self._bump(connection, session.domain_id)}, True

    def _recover(self, connection, *, session_id, request_id, packet, timestamp):
        _text(timestamp)
        record = self._request(connection, session_id, request_id)
        result, changed = self._save_terminal(
            connection, session_id, request_id, packet, "recovered"
        )
        stopped = connection.execute(
            "UPDATE executions SET stopped_at=?,outcome='recovered' WHERE execution_id=? AND stopped_at IS NULL",
            (timestamp, record.execution_id),
        ).rowcount
        changed = changed or bool(stopped)
        if changed:
            self._bump(connection, self._session(connection, session_id).domain_id)
        return result, changed

    def _delete_ended(self, connection, *, session_ids):
        if (
            not isinstance(session_ids, (tuple, list))
            or len(session_ids) > MAX_SESSIONS
        ):
            _invalid()
        if len(set(session_ids)) != len(session_ids):
            _invalid()
        for session_id in session_ids:
            if self._session(connection, session_id).ended_at is None:
                _invalid()
        for session_id in session_ids:
            connection.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        return {"deleted_session_ids": tuple(session_ids)}, bool(session_ids)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
