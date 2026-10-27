"""Anchored, single-writer SQLite image storage, independent of its schema.

The caller supplies a serialized seed whose schema binds the supplied instance
UUID. A durable initializing marker precedes that seed; incomplete state is never
recreated. Keep this owner alive until every worker using it has drained.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Callable
from uuid import UUID, uuid4

from bridge import project_files as files
from bridge.application_state import MAX_IMAGE_BYTES, StateError

MANIFEST_MAX_BYTES = 4096


def _identity(info):
    return info.st_dev, info.st_ino


def _private(info, mode):
    if stat.S_IMODE(info.st_mode) != mode:
        raise StateError("state_store_invalid")


def _runtime_supported():
    if not all(
        callable(getattr(sqlite3.Connection, name, None))
        for name in ("serialize", "deserialize")
    ):
        raise StateError("state_store_unsupported")
    if os.name != "posix" or not all(
        hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY")
    ):
        raise StateError("state_store_unsupported")


class StateImage:
    """Own a stable OS lock and directory anchor until explicitly closed."""

    def __init__(self, path: Path, project_id: str, stack: ExitStack, parent: int):
        self.path = path
        self.project_id = project_id
        self.instance_id = ""
        self._stack = stack
        self._parent = parent
        self._directory_identity = _identity(os.fstat(parent))
        self._lock = None
        self._ready = False

    @classmethod
    def open(
        cls,
        common_git_dir: Path,
        project_id: str,
        *,
        initialize: bool = False,
        initial_image: Callable[[str], bytes] | None = None,
    ) -> "StateImage | None":
        """Open existing state or explicitly initialize a genuinely absent store."""
        stack = ExitStack()
        owner = None
        path = Path(common_git_dir) / "plaza/application-state"
        try:
            # Probe without creating even a lock or directory for missing status.
            try:
                parent = stack.enter_context(files.directory(path))
            except FileNotFoundError:
                # The configured common Git directory itself must already exist.
                with files.directory(Path(common_git_dir)):
                    pass
                if not initialize:
                    return None
                _runtime_supported()
                if not callable(initial_image):
                    raise StateError("state_store_invalid")
                parent = stack.enter_context(files.directory(path, create=True))
            owner = cls(path, project_id, stack, parent)
            owner._validate_directory()
            manifest, image = owner._artifacts()
            if manifest is None and image is None:
                if not initialize:
                    return None
                _runtime_supported()
                if not callable(initial_image):
                    raise StateError("state_store_invalid")
            elif manifest is None or image is None:
                raise StateError("state_store_invalid")
            else:
                _runtime_supported()
            owner._lock = files.FileLock.acquire(path / "writer.lock")
            owner._validate()
            # Recheck under writer exclusion: another initializer may have won.
            manifest, image = owner._artifacts()
            if manifest is None and image is None:
                if not initialize or not callable(initial_image):
                    raise StateError("state_store_invalid")
                owner.instance_id = str(uuid4())
                try:
                    data = initial_image(owner.instance_id)
                except StateError:
                    raise
                except Exception:
                    raise StateError("state_store_failed") from None
                owner._check_data(data)
                owner._write_manifest("initializing")
                owner._replace("state.sqlite3", data)
                owner._write_manifest("ready")
                owner._ready = True
            elif manifest is None or image is None:
                raise StateError("state_store_invalid")
            else:
                owner.instance_id = owner._load_manifest()
                owner._ready = True
                owner.read()
            result = owner
            owner = None
            stack = None
            return result
        except BlockingIOError:
            raise StateError("state_store_busy") from None
        except StateError:
            raise
        except (OSError, ValueError, TypeError):
            raise StateError("state_store_invalid") from None
        finally:
            if owner is not None:
                owner.close()
            elif stack is not None:
                stack.close()

    def _validate_directory(self):
        if self._parent is None:
            raise StateError("state_store_invalid")
        # Both metadata directories are private; do not chmod existing evidence.
        with files.directory(self.path.parent) as plaza:
            _private(os.fstat(plaza), 0o700)
        with files.directory(self.path) as current:
            _private(os.fstat(current), 0o700)
            if _identity(os.fstat(current)) != self._directory_identity:
                raise StateError("state_store_invalid")

    def _stat(self, name, *, missing=False):
        info = files._check(self._parent, name, missing=missing)
        if info is not None:
            _private(info, 0o600)
        return info

    def _artifacts(self):
        return (
            self._stat("manifest.json", missing=True),
            self._stat("state.sqlite3", missing=True),
        )

    def _validate(self):
        self._validate_directory()
        if self._lock is None:
            raise StateError("state_store_invalid")
        self._lock.validate()
        current = self._stat("writer.lock")
        if _identity(current) != _identity(os.fstat(self._lock._fd)):
            raise StateError("state_store_invalid")
        if self._ready:
            self._stat("state.sqlite3")
            if self._load_manifest() != self.instance_id:
                raise StateError("state_store_invalid")

    def _read(self, name, limit):
        self._stat(name)
        fd = files._open(self._parent, name, os.O_RDONLY)
        with os.fdopen(fd, "rb") as source:
            data = source.read(limit + 1)
        if len(data) > limit:
            raise StateError("state_store_quota")
        return data

    def _load_manifest(self):
        try:
            # Duplicate fields must not silently override an identity or state.
            def fields(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate manifest field")
                    result[key] = value
                return result

            value = json.loads(
                self._read("manifest.json", MANIFEST_MAX_BYTES),
                object_pairs_hook=fields,
            )
            if not isinstance(value, dict) or set(value) != {
                "version",
                "project_id",
                "instance_id",
                "state",
            }:
                raise ValueError("invalid manifest")
            if type(value["version"]) is not int:
                raise ValueError("invalid version")
            if value["version"] != 1:
                raise StateError("state_store_unsupported")
            if value["project_id"] != self.project_id or value["state"] != "ready":
                raise ValueError("invalid identity or incomplete initialization")
            if str(UUID(value["instance_id"])) != value["instance_id"]:
                raise ValueError("invalid instance")
            return value["instance_id"]
        except StateError:
            raise
        except (ValueError, TypeError, AttributeError, RecursionError):
            raise StateError("state_store_invalid") from None

    def _write_manifest(self, state):
        data = json.dumps(
            {
                "version": 1,
                "project_id": self.project_id,
                "instance_id": self.instance_id,
                "state": state,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(data) > MANIFEST_MAX_BYTES:
            raise StateError("state_store_invalid")
        self._replace("manifest.json", data)

    @staticmethod
    def _check_data(data):
        if not isinstance(data, bytes) or not data:
            raise StateError("state_store_invalid")
        if len(data) > MAX_IMAGE_BYTES:
            raise StateError("state_store_quota")

    def read(self) -> bytes:
        """Read bounded image bytes; schema/integrity validation is the repository's."""
        try:
            self._validate()
            data = self._read("state.sqlite3", MAX_IMAGE_BYTES)
            self._validate()
            return data
        except StateError:
            raise
        except OSError:
            raise StateError("state_store_invalid") from None

    def replace(self, data: bytes) -> None:
        """Durably replace an image; never remove evidence after a failed write."""
        self._check_data(data)
        self._replace("state.sqlite3", data)

    def confirm_durable(self) -> None:
        """Settle uncertain replacement without rewriting bytes or releasing lock.

        A readable renamed image is not proof of crash durability. Synchronize
        its no-follow file descriptor, then the retained directory descriptor;
        validate lifetime anchors and the current image inode around both syncs.
        """
        try:
            self._validate()
            self._stat("state.sqlite3")
            fd = files._open(self._parent, "state.sqlite3", os.O_RDONLY)
        except StateError:
            raise
        except OSError:
            raise StateError("state_store_invalid") from None
        try:
            identity = _identity(os.fstat(fd))
            os.fsync(fd)
            self._validate()
            if _identity(self._stat("state.sqlite3")) != identity:
                raise StateError("state_store_invalid")
            os.fsync(self._parent)
            self._validate()
            if _identity(self._stat("state.sqlite3")) != identity:
                raise StateError("state_store_invalid")
        except OSError:
            raise StateError("state_store_uncertain", uncertain=True) from None
        finally:
            os.close(fd)

    def _replace(self, name, data):
        try:
            self._validate()
            self._stat(name, missing=True)
        except StateError:
            raise
        except OSError:
            raise StateError("state_store_invalid") from None
        # Use project_files' no-follow opens against the lifetime directory
        # anchor, so a swapped pathname cannot redirect the actual write.
        temporary = f".{name}.{uuid4().hex}.tmp"
        renaming = False
        try:
            fd = files._open(
                self._parent, temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
            )
            try:
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short application state write")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            self._validate()
            self._stat(name, missing=True)
            renaming = True
            os.replace(
                temporary, name, src_dir_fd=self._parent, dst_dir_fd=self._parent
            )
            os.fsync(self._parent)
            self._validate()
        except (OSError, StateError):
            raise StateError(
                "state_store_uncertain" if renaming else "state_store_failed",
                uncertain=renaming,
            ) from None

    def close(self) -> None:
        """Release writer exclusion only when all owned operations have settled."""
        if self._lock is not None:
            self._lock.close()
            self._lock = None
        if self._parent is not None:
            self._stack.close()
            self._parent = None
