#!/usr/bin/env python3
"""Offline, lock-respecting export and backed-up deletion of ended sessions.

Uses the same anchored image and repository as the bridge. Never initializes a
missing store, opens SQLite by pathname, imports an SDK or starts agent work.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import UUID

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge import project_files as files
from bridge.application_state import MAX_IMAGE_BYTES, StateCommand, StateError
from bridge.sqlite_state import SCHEMA_VERSION, SQLiteStateRepository
from bridge.state_image import StateImage
from bridge.workspace import WorkspaceError, inspect_project

# JSON escaping and record envelopes can exceed the serialized SQLite image.
MAX_EXPORT_BYTES = 8 * MAX_IMAGE_BYTES
ENCODER = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _chunks(value):
    """Encode incrementally, bounding the actual UTF-8 document contribution."""
    size = 0
    for text in ENCODER.iterencode(value):
        chunk = text.encode("utf-8")
        size += len(chunk)
        if size > MAX_EXPORT_BYTES:
            raise StateError("state_store_quota")
        yield chunk


def _export(view, session, image):
    session_id = session.session_id
    records = {
        "session": asdict(session),
        "executions": [
            asdict(r) for r in view.executions if r.session_id == session_id
        ],
        "requests": [asdict(r) for r in view.requests if r.session_id == session_id],
        "terminals": [asdict(r) for r in view.terminals if r.session_id == session_id],
    }
    digest = hashlib.sha256()
    for chunk in _chunks(records):
        digest.update(chunk)
    return {
        "format_version": 1,
        "schema_version": SCHEMA_VERSION,
        "project_id": view.project_id,
        "instance_id": view.instance_id,
        "state_revision": view.revision,
        "image_sha256": hashlib.sha256(image.read()).hexdigest(),
        "records_sha256": digest.hexdigest(),
        "records": records,
    }


def _identity(info):
    return info.st_dev, info.st_ino


def _write_export(path, value):
    """Preflight, exclusively create, then fsync file and anchored parent.

    A failed output is removed only if it still names our own created inode.
    Existing files and substituted paths are never overwritten or removed.
    """
    for _ in _chunks(value):
        pass
    path = Path(path)
    if ".." in path.parts or not path.name:
        raise StateError("state_output_invalid")
    path = path.absolute()
    try:
        with files.directory(path.parent) as parent:
            owned = None
            try:
                fd = files._open(
                    parent, path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                )
                try:
                    owned = _identity(os.fstat(fd))
                    for chunk in _chunks(value):
                        remaining = memoryview(chunk)
                        while remaining:
                            written = os.write(fd, remaining)
                            if written <= 0:
                                raise OSError("short export write")
                            remaining = remaining[written:]
                    os.fsync(fd)
                    if _identity(files._check(parent, path.name)) != owned:
                        raise OSError("export file changed")
                    with files.directory(path.parent) as current:
                        if _identity(os.fstat(current)) != _identity(os.fstat(parent)):
                            raise OSError("export parent changed")
                    os.fsync(parent)
                    if _identity(files._check(parent, path.name)) != owned:
                        raise OSError("export file changed")
                    with files.directory(path.parent) as current:
                        if _identity(os.fstat(current)) != _identity(os.fstat(parent)):
                            raise OSError("export parent changed")
                finally:
                    os.close(fd)
            except (OSError, StateError):
                if owned is not None:
                    try:
                        current = files._check(parent, path.name, missing=True)
                        if current is not None and _identity(current) == owned:
                            os.unlink(path.name, dir_fd=parent)
                            os.fsync(parent)
                    except OSError:
                        pass
                raise
    except FileExistsError:
        raise StateError("state_output_invalid") from None
    except OSError:
        raise StateError("state_store_failed") from None


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    operations = parser.add_subparsers(dest="operation", required=True)
    export = operations.add_parser("export", help="export retained session records")
    export.add_argument("--session", required=True)
    export.add_argument("--output", required=True, type=Path)
    delete = operations.add_parser(
        "delete-ended", help="back up, then delete an ended session"
    )
    delete.add_argument("--session", required=True)
    delete.add_argument("--backup", required=True, type=Path)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    image = repository = None
    try:
        try:
            if str(UUID(args.session)) != args.session:
                raise ValueError()
        except ValueError:
            raise StateError("session_unavailable") from None
        project = inspect_project(args.workspace)
        if project.common_git_dir is None or project.project_id is None:
            raise StateError("workspace_invalid")
        image = StateImage.open(project.common_git_dir, project.project_id)
        if image is None:
            raise StateError("state_store_missing")
        repository = SQLiteStateRepository(image)
        view = repository.load()
        session = next((s for s in view.sessions if s.session_id == args.session), None)
        if session is None:
            raise StateError("session_unavailable")
        if args.operation == "delete-ended" and session.ended_at is None:
            raise StateError("session_not_ended")
        output = args.output if args.operation == "export" else args.backup
        _write_export(output, _export(view, session, image))
        if args.operation == "delete-ended":
            repository.apply(
                StateCommand("delete_ended", {"session_ids": (args.session,)})
            )
        print(
            "session_exported"
            if args.operation == "export"
            else "ended_session_deleted"
        )
        return 0
    except (StateError, WorkspaceError) as error:
        print(error.code, file=sys.stderr)
        return 1
    except (OSError, ValueError, UnicodeError):
        print("state_store_failed", file=sys.stderr)
        return 1
    finally:
        if repository is not None:
            repository.close()
        if image is not None:
            image.close()


if __name__ == "__main__":
    raise SystemExit(main())
