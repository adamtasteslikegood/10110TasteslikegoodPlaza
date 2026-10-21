"""Session-length cooperative exclusion and durable evidence of unclean execution."""

import os
from pathlib import Path
import re
import threading
from uuid import uuid4

from bridge import project_files as files
from bridge.workspace import (
    ExecutionWorkspace,
    WorkspaceError,
    _decode,
    _encode,
    validate_workspace,
)

_guard = threading.Lock()
_owners: dict[Path, "WorkspaceLease"] = {}


def _cleanup_error():
    return WorkspaceError(
        "cleanup_failed", "Workspace requires confirmed cleanup or operator inspection"
    )


class WorkspaceLease:
    """Keep ownership through idle/completion/disconnect until confirmed teardown."""

    def __init__(
        self,
        workspace: ExecutionWorkspace,
        domain_id: str,
        domain_session_id: str,
        lock: files.FileLock,
    ):
        self.workspace = workspace
        self.domain_id = domain_id
        self.domain_session_id = domain_session_id
        self.held = True
        self._lock = lock
        self._marker = workspace.git_dir / "plaza-unclean.json"
        self._record = dict(
            schema_version=1,
            workspace_id=workspace.workspace_id,
            domain_id=domain_id,
            domain_session_id=domain_session_id,
            lease_id=str(uuid4()),
        )

    @classmethod
    def acquire(
        cls, workspace: ExecutionWorkspace, *, domain_id: str, domain_session_id: str
    ) -> "WorkspaceLease":
        try:
            invalid = (
                not isinstance(domain_id, str)
                or re.fullmatch(r"[a-zA-Z0-9_-]+", domain_id) is None
                or len(domain_id.encode("utf-8")) > 128
                or not isinstance(domain_session_id, str)
                or not domain_session_id
                or len(domain_session_id.encode("utf-8")) > 128
            )
        except UnicodeError:
            invalid = True
        if invalid:
            raise WorkspaceError(
                "workspace_invalid", "Invalid domain reservation identifiers"
            )
        with _guard:
            owner = _owners.get(workspace.git_dir)
            if owner is not None:
                raise WorkspaceError(
                    "workspace_busy",
                    f"Workspace is reserved by domain {owner.domain_id}",
                )
            validate_workspace(
                workspace, runtime_root=Path(__file__).resolve().parent.parent
            )
            try:
                lock = files.FileLock.acquire(
                    workspace.git_dir / "plaza-execution.lock"
                )
            except BlockingIOError:
                domain = None
                try:
                    marker = _decode(
                        files.read_regular(
                            workspace.git_dir / "plaza-unclean.json", max_bytes=4096
                        )
                    )
                    candidate = marker.get("domain_id")
                    if (
                        isinstance(candidate, str)
                        and len(candidate) <= 128
                        and re.fullmatch(r"[a-zA-Z0-9_-]+", candidate)
                    ):
                        domain = candidate
                except (OSError, ValueError):
                    pass
                message = (
                    f"Workspace is reserved by domain {domain}"
                    if domain
                    else "Workspace is reserved by another bridge domain"
                )
                raise WorkspaceError("workspace_busy", message) from None
            except OSError:
                raise _cleanup_error() from None
            lease = cls(workspace, domain_id, domain_session_id, lock)
            try:
                if os.path.lexists(lease._marker):
                    raise _cleanup_error()
                # No SDK startup permission exists until both file and directory fsync.
                files.atomic_replace(lease._marker, _encode(lease._record))
                lease.validate()
            except BaseException as error:
                lock.close()
                lease.held = False
                if isinstance(error, WorkspaceError):
                    raise
                if isinstance(error, (OSError, ValueError)):
                    raise _cleanup_error() from None
                raise
            _owners[workspace.git_dir] = lease
            return lease

    def validate(self) -> None:
        if not self.held:
            raise _cleanup_error()
        try:
            self._lock.validate()
            if (
                _decode(files.read_regular(self._marker, max_bytes=4096))
                != self._record
            ):
                raise _cleanup_error()
        except (OSError, ValueError):
            raise _cleanup_error() from None
        validate_workspace(
            self.workspace, runtime_root=Path(__file__).resolve().parent.parent
        )

    def release(self, *, cleanup_confirmed: bool) -> None:
        with _guard:
            if not self.held:
                return
            if cleanup_confirmed is not True:
                raise _cleanup_error()
            try:
                self._lock.validate()
                if (
                    _decode(files.read_regular(self._marker, max_bytes=4096))
                    != self._record
                ):
                    raise _cleanup_error()
                files.durable_unlink(self._marker)
            except (OSError, ValueError):
                # Directory-fsync failure after unlink is uncertain too. Recreate
                # evidence if possible, retaining OS and in-process ownership.
                if not os.path.lexists(self._marker):
                    try:
                        files.atomic_replace(self._marker, _encode(self._record))
                    except OSError:
                        pass
                raise _cleanup_error() from None
            self._lock.close()
            self.held = False
            if _owners.get(self.workspace.git_dir) is self:
                del _owners[self.workspace.git_dir]
