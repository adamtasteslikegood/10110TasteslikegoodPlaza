"""Exclusive, bounded diagnostic archives; never used to restore model context.

All admission and mutations share a thread mutex and a lifetime OS writer lock.
Retention uses each closed file's mtime (oldest first, path as tie breaker).
Only manifest-proven runs and exact managed leaf names participate in retention.
POSIX directory descriptors anchor operations without following symlinks. On
platforms without those primitives recording fails closed, leaving service live.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
from typing import Literal
from uuid import uuid4

from bridge.config import BridgeConfig

_AGENT = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]*")
_RUN = re.compile(r"\d{8}T\d{12}Z-([0-9a-f]{32})")
_EVENT = re.compile(r"events-[0-9]{4,}\.jsonl")
_TRANSCRIPT = re.compile(r"transcript-[0-9]{4,}\.jsonl")
_TEMP = re.compile(r"manifest\.[0-9a-f]{32}\.tmp")
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)),
}


def _valid_agent(value: object) -> bool:
    return (
        isinstance(value, str)
        and _AGENT.fullmatch(value) is not None
        and value.upper() not in _RESERVED
    )


def _encode(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _regular(info: os.stat_result) -> bool:
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]
    os.fsync(fd)


@dataclass(frozen=True)
class _File:
    path: Path
    info: os.stat_result
    manifest: bool = False


class RunLogWriter:
    """Best-effort disk recorder; false means a record was not captured.

    Reserved stamp fields override caller values. Oversized string ``content``
    is shortened only in the disk copy. Other metadata is never silently dropped.
    Sequence numbers may have gaps after failed writes, but are never reused.
    """

    def __init__(
        self,
        config: BridgeConfig,
        project_label: str,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.config = config
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.run_id = uuid4().hex
        self.is_recording = False
        self._mutex = threading.Lock()
        self._root_fd: int | None = None
        self._lock_fd: int | None = None
        self._run: Path | None = None
        self._started = False
        self._closed = False
        self._seq = 0
        self._streams: dict[tuple[str, str | None], Path] = {}
        self._indices: dict[tuple[str, str | None], int] = {}
        self._last_diagnostic: str | None = None
        started = self._now()
        self._run_name = started.strftime("%Y%m%dT%H%M%S%fZ") + "-" + self.run_id
        self._manifest = {
            "schema_version": 1,
            "run_id": self.run_id,
            "started_at": started.isoformat(),
            "ended_at": None,
            "project_label": project_label,
            "settings": config.effective_settings(),
            "status": "open",
        }
        with self._mutex:
            try:
                self._start()
                self._recovered()
            except (OSError, ValueError, TypeError, NotImplementedError) as error:
                self._failed("startup", error)

    def _now(self) -> datetime:
        return self._clock().astimezone(timezone.utc)

    def _failed(self, operation: str, error: Exception) -> None:
        self.is_recording = False
        # Never echo record bodies, settings or exception text into diagnostics.
        message = f'bridge recording suspended: {operation} ({type(error).__name__}, errno={getattr(error, "errno", None)})'
        if message != self._last_diagnostic:
            print(message, file=sys.stderr)
            self._last_diagnostic = message

    def _recovered(self) -> None:
        if self._last_diagnostic is not None:
            print("bridge recording recovered", file=sys.stderr)
            self._last_diagnostic = None
        self.is_recording = True

    @staticmethod
    def _directory(parent: int, name: str, *, create: bool = False) -> int:
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
        return os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
        )

    def _parent(self, path: Path, *, create: bool = False) -> int:
        assert self._root_fd is not None
        fd = os.dup(self._root_fd)
        try:
            for part in path.parts[:-1]:
                new_fd = self._directory(fd, part, create=create)
                os.close(fd)
                fd = new_fd
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _open(self, path: Path, flags: int, *, create_parents: bool = False) -> int:
        parent = self._parent(path, create=create_parents)
        try:
            fd = os.open(
                path.name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent
            )
            if not _regular(os.fstat(fd)):
                os.close(fd)
                raise OSError("unsafe managed file")
            return fd
        finally:
            os.close(parent)

    def _stat(self, path: Path) -> os.stat_result:
        parent = self._parent(path)
        try:
            return os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        finally:
            os.close(parent)

    def _entries(self, path: Path) -> list[tuple[str, os.stat_result]]:
        parent = self._parent(path)
        try:
            fd = self._directory(parent, path.name)
        finally:
            os.close(parent)
        try:
            with os.scandir(fd) as entries:
                return [
                    (entry.name, entry.stat(follow_symlinks=False)) for entry in entries
                ]
        finally:
            os.close(fd)

    def _start(self) -> None:
        if self._started:
            self._check_manifest()
            return
        if self._root_fd is None:
            if os.name != "posix" or not all(
                hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY")
            ):
                raise OSError("safe directory operations unavailable")
            root = self.config.log_dir
            if not root.is_absolute():
                raise ValueError("log root must be canonical and absolute")
            fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for part in root.parts[1:]:
                    new_fd = self._directory(fd, part, create=True)
                    os.close(fd)
                    fd = new_fd
                self._root_fd = fd
            except BaseException:
                os.close(fd)
                raise
        if self._lock_fd is None:
            try:
                import fcntl
            except ImportError:
                raise OSError("OS locking unavailable") from None
            fd = self._open(Path(".writer.lock"), os.O_RDWR | os.O_CREAT)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException:
                os.close(fd)
                raise
            self._lock_fd = fd
        if self._run is None:
            runs_fd = self._directory(self._root_fd, "runs", create=True)
            try:
                os.mkdir(self._run_name, 0o700, dir_fd=runs_fd)
            finally:
                os.close(runs_fd)
            self._run = Path("runs") / self._run_name
        self._write_manifest(self._manifest)
        self._started = True

    def _read_manifest(self, path: Path) -> dict[str, object] | None:
        try:
            if not _regular(self._stat(path)):
                return None
        except FileNotFoundError:
            return None
        try:
            fd = self._open(path, os.O_RDONLY)
            with os.fdopen(fd, "rb") as source:
                value = json.load(source)
            match = _RUN.fullmatch(path.parent.name)
            if (
                isinstance(value, dict)
                and type(value.get("schema_version")) is int
                and value["schema_version"] == 1
                and match
                and value.get("run_id") == match[1]
            ):
                return value
        except (ValueError, UnicodeError):
            pass
        return None

    def _check_manifest(self) -> None:
        if self._read_manifest(self._run / "manifest.json") is None:
            raise OSError("managed manifest missing or unsafe")

    def _scan(self) -> list[_File]:
        files = []
        for name, info in self._entries(Path("runs")):
            if not stat.S_ISDIR(info.st_mode) or not _RUN.fullmatch(name):
                continue
            run = Path("runs") / name
            manifest = run / "manifest.json"
            owned = self._read_manifest(manifest) is not None
            # Only this writer knows provenance before its first atomic manifest.
            if not owned and not (run == self._run and not self._started):
                continue
            for leaf, child in self._entries(run):
                path = run / leaf
                if _regular(child) and (
                    (owned and (leaf == "manifest.json" or _EVENT.fullmatch(leaf)))
                    or _TEMP.fullmatch(leaf)
                ):
                    files.append(_File(path, child, leaf == "manifest.json"))
                elif owned and leaf == "agents" and stat.S_ISDIR(child.st_mode):
                    for agent, agent_info in self._entries(path):
                        if not _valid_agent(agent) or not stat.S_ISDIR(
                            agent_info.st_mode
                        ):
                            continue
                        for segment, segment_info in self._entries(path / agent):
                            if _TRANSCRIPT.fullmatch(segment) and _regular(
                                segment_info
                            ):
                                files.append(
                                    _File(path / agent / segment, segment_info)
                                )
        return files

    def _remove_empty_agents(self, run: Path) -> None:
        agents = run / "agents"
        try:
            info = self._stat(agents)
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(info.st_mode):
            return
        folders = [
            agents / name
            for name, info in self._entries(agents)
            if _valid_agent(name) and stat.S_ISDIR(info.st_mode)
        ]
        for folder in [*folders, agents]:
            parent = self._parent(folder)
            try:
                os.rmdir(folder.name, dir_fd=parent)
            except OSError:
                pass  # never remove unknown children, even inside managed folders
            finally:
                os.close(parent)

    def _unlink(self, item: _File) -> None:
        if item.manifest:
            self._remove_empty_agents(item.path.parent)
        parent = self._parent(item.path)
        try:
            current = os.stat(item.path.name, dir_fd=parent, follow_symlinks=False)
            if not _regular(current) or (current.st_dev, current.st_ino) != (
                item.info.st_dev,
                item.info.st_ino,
            ):
                raise OSError("managed file changed during pruning")
            os.unlink(item.path.name, dir_fd=parent)
        finally:
            os.close(parent)
        # rmdir only: unrelated children and symlinks cannot be traversed/deleted.
        folder = item.path.parent
        while folder not in (Path("runs"), self._run):
            parent = self._parent(folder)
            try:
                os.rmdir(folder.name, dir_fd=parent)
            except OSError:
                break
            finally:
                os.close(parent)
            folder = folder.parent

    def _admit(self, size: int) -> None:
        cutoff = self._now().timestamp() - self.config.log_max_age_days * 86400
        while True:
            files = self._scan()
            total = sum(item.info.st_size for item in files)
            active = set(self._streams.values())
            eligible = []
            for item in files:
                if item.path in active or item.path == self._run / "manifest.json":
                    continue
                if item.manifest and any(
                    other.path != item.path
                    and other.path.is_relative_to(item.path.parent)
                    for other in files
                ):
                    continue
                eligible.append(item)
            eligible.sort(key=lambda item: (item.info.st_mtime_ns, str(item.path)))
            expired = next(
                (item for item in eligible if item.info.st_mtime < cutoff), None
            )
            if expired is not None:
                self._unlink(expired)
            elif total + size <= self.config.log_max_total_bytes:
                return
            elif eligible:
                self._unlink(eligible[0])
            else:
                raise OSError("protected files exhaust quota")

    def _write_manifest(self, value: dict[str, object]) -> None:
        data = _encode(value)
        destination = self._run / "manifest.json"
        try:
            existing = self._stat(destination)
        except FileNotFoundError:
            if self._started:
                raise
        else:
            if not _regular(existing):
                raise OSError("unsafe manifest destination")
        self._admit(len(data))  # old manifest and new temporary coexist
        temporary = self._run / f"manifest.{uuid4().hex}.tmp"
        try:
            fd = self._open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            try:
                _write_all(fd, data)
            finally:
                os.close(fd)
            parent = self._parent(destination)
            try:
                os.replace(
                    temporary.name,
                    destination.name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                )
            finally:
                os.close(parent)
        finally:
            try:
                self._unlink(_File(temporary, self._stat(temporary)))
            except OSError:
                pass  # leftover managed temporary remains charged on the next scan

    def _record_bytes(self, record: dict[str, object]) -> bytes:
        value = dict(record)
        value.update(
            schema_version=1,
            seq=self._seq + 1,
            timestamp=self._now().isoformat(),
            run_id=self.run_id,
        )
        data = _encode(value)
        limit = self.config.transcript_max_record_bytes
        if len(data) <= limit:
            return data
        content = value.get("content")
        if not isinstance(content, str):
            raise ValueError("record metadata exceeds bound")
        value.update(
            truncated=True, original_content_bytes=len(content.encode("utf-8"))
        )
        marker = "\n[truncated]"
        value["content"] = marker
        if len(_encode(value)) > limit:
            raise ValueError("record metadata exceeds bound")
        low, high = 0, len(content)
        while low < high:
            middle = (low + high + 1) // 2
            value["content"] = content[:middle] + marker
            if len(_encode(value)) <= limit:
                low = middle
            else:
                high = middle - 1
        value["content"] = content[:low] + marker
        return _encode(value)

    def append(
        self,
        kind: Literal["event", "transcript"],
        record: dict[str, object],
        *,
        agent_id: str | None = None,
    ) -> bool:
        with self._mutex:
            if self._closed:
                return False
            try:
                if kind not in ("event", "transcript") or (
                    kind == "transcript" and not _valid_agent(agent_id)
                ):
                    raise ValueError("invalid stream path")
                data = self._record_bytes(record)
                self._start()
                key = (kind, agent_id if kind == "transcript" else None)
                path = self._streams.get(key)
                if (
                    path is not None
                    and self._stat(path).st_size + len(data)
                    > self.config.transcript_max_file_bytes
                ):
                    del self._streams[
                        key
                    ]  # seal before pruning/admitting its successor
                    path = None
                self._admit(len(data))
                if path is None:
                    number = self._indices.get(key, 0) + 1
                    self._indices[key] = number
                    path = (
                        self._run / f"events-{number:04d}.jsonl"
                        if kind == "event"
                        else self._run
                        / "agents"
                        / agent_id
                        / f"transcript-{number:04d}.jsonl"
                    )
                    fd = self._open(
                        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, create_parents=True
                    )
                    self._streams[key] = path
                else:
                    fd = self._open(path, os.O_WRONLY | os.O_APPEND)
                self._seq += 1
                try:
                    offset = os.fstat(fd).st_size
                    try:
                        _write_all(fd, data)
                    except OSError:
                        try:
                            os.ftruncate(fd, offset)
                        except OSError:
                            self._streams.pop(
                                key, None
                            )  # damaged tail is never appended to
                        raise
                finally:
                    os.close(fd)
                self._recovered()
                return True
            except (OSError, ValueError, TypeError, NotImplementedError) as error:
                self._failed("append", error)
                return False

    def close(self, *, clean: bool = True) -> None:
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            try:
                self._streams.clear()
                if clean and self._started:
                    self._check_manifest()
                    value = dict(
                        self._manifest,
                        ended_at=self._now().isoformat(),
                        status="closed",
                    )
                    self._write_manifest(value)
            except (OSError, ValueError, TypeError, NotImplementedError) as error:
                self._failed("close", error)
            finally:
                self.is_recording = False
                if self._lock_fd is not None:
                    os.close(self._lock_fd)
                    self._lock_fd = None
                if self._root_fd is not None:
                    os.close(self._root_fd)
                    self._root_fd = None


def _reject_constant(value: str) -> None:
    raise ValueError("nonstandard JSON constant")


def iter_jsonl(
    path: Path, *, on_diagnostic: Callable[[str], None]
) -> Iterator[dict[str, object]]:
    """Read complete objects, diagnosing corrupt lines without changing the file."""
    with path.open("rb") as source:
        for number, line in enumerate(source, 1):
            if not line.endswith(b"\n"):
                on_diagnostic(f"line {number}: incomplete final record ignored")
                continue
            try:
                value = json.loads(line, parse_constant=_reject_constant)
                if not isinstance(value, dict):
                    raise ValueError("not an object")
            except (ValueError, UnicodeError):
                on_diagnostic(f"line {number}: malformed record ignored")
                continue
            yield value
