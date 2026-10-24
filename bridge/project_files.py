"""Durable project metadata primitives with POSIX, no-follow directory anchors.

Locks default to nonblocking; short operations can opt into a bounded wait.
Their files are never replaced or removed. Callers
must keep the returned lock alive for the whole protected operation/session.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import time
from uuid import uuid4


def _supported() -> None:
    if os.name != "posix" or not all(
        hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY")
    ):
        raise OSError("safe project file operations unavailable")


@contextmanager
def directory(path: Path, *, create: bool = False):
    """Anchor an absolute directory, refusing symlinks in every component."""
    _supported()
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise OSError("project metadata path must be absolute")
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                else:
                    os.fsync(fd)
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _regular(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OSError("unsafe project metadata file")


def _check(parent: int, name: str, *, missing: bool = False):
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        if missing:
            return None
        raise
    _regular(info)
    return info


def _open(parent: int, name: str, flags: int) -> int:
    fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
    try:
        info = os.fstat(fd)
        _regular(info)
        current = _check(parent, name)
        if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
            raise OSError("project metadata changed while opening")
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_regular(path: Path, *, max_bytes: int) -> bytes:
    """Read a bounded, singly linked regular file without following symlinks."""
    with directory(path.parent) as parent:
        fd = _open(parent, path.name, os.O_RDONLY)
        with os.fdopen(fd, "rb") as source:
            result = source.read(max_bytes + 1)
            if len(result) > max_bytes:
                raise OSError("project metadata exceeds byte limit")
            return result


def atomic_replace(path: Path, data: bytes) -> None:
    """Fsync new bytes, rename within the anchored parent, then fsync parent."""
    with directory(path.parent) as parent:
        _check(parent, path.name, missing=True)
        temporary = f".{path.name}.{uuid4().hex}.tmp"
        fd = _open(parent, temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short project metadata write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        # Failed writes intentionally leave their temporary for operator inspection.
        _check(parent, path.name, missing=True)
        os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)


def durable_unlink(path: Path) -> None:
    """Remove only a safe regular file and make its removal durable."""
    with directory(path.parent) as parent:
        _check(parent, path.name)
        os.unlink(path.name, dir_fd=parent)
        os.fsync(parent)


# Short metadata operations may serialize; lifetime ownership must stay fail-fast.
SHORT_LOCK_SECONDS = 1.0


def lock_exclusive(fd: int, *, deadline=None, stop_waiting=None) -> None:
    """Acquire atomically, waiting only for explicitly bounded short contention.

    No lock is held while waiting. Only EWOULDBLOCK is retryable; callers retain
    their inode/marker validation and own/drain the whole blocking operation.
    """
    try:
        import fcntl
    except ImportError:
        raise OSError("OS project locking unavailable") from None

    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if deadline is None or (stop_waiting is not None and stop_waiting()):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(0.01, remaining))
            if time.monotonic() >= deadline:
                raise


class FileLock:
    """An OS lock on a stable inode; descriptor closure releases exclusion."""

    def __init__(self, path: Path, fd: int):
        self.path = path
        self._fd = fd

    @classmethod
    def acquire(cls, path: Path, *, deadline=None, stop_waiting=None) -> "FileLock":
        _supported()
        with directory(path.parent) as parent:
            fd = _open(parent, path.name, os.O_RDWR | os.O_CREAT)
            try:
                lock_exclusive(fd, deadline=deadline, stop_waiting=stop_waiting)
                os.fsync(parent)
                result = cls(path, fd)
                result.validate()
                return result
            except BaseException:
                os.close(fd)
                raise

    def validate(self) -> None:
        if self._fd is None:
            raise OSError("project lock is closed")
        with directory(self.path.parent) as parent:
            current = _check(parent, self.path.name)
            owned = os.fstat(self._fd)
            _regular(owned)
            if (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
                raise OSError("project lock inode changed")

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
