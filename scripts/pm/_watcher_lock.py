"""Single-writer lock for the PM daemon's Confluence file watcher.

Why this exists
---------------
Every agent session (Claude Code, Copilot CLI, each background job, each git
worktree) spawns its own `pm_daemon.py` as an MCP stdio child. That is correct
for the MCP *tools* — each session needs its own server on its own pipes.

It is very wrong for the *watcher*. Each daemon also started a `watchdog`
Observer over the workspace, so N concurrent sessions meant N observers all
watching the same `specs/*.md` and all racing to PUT the same Confluence pages
on every save. Observed in the wild: 13 daemons, 13 observers. Duplicate and
interleaved Confluence writes are the failure mode, and version conflicts on the
page are how it surfaces.

The fix: the watcher is a singleton, elected by an exclusive `flock`. Every
daemon still serves MCP tools; only the lock holder runs an Observer.

Why flock and not a PID file
----------------------------
The kernel releases an `flock` when the holding process dies, however it dies —
SIGKILL, crash, machine losing power. There is no stale-lock cleanup path to get
wrong, which is exactly the bug a PID file would reintroduce (a dead session's
PID file blocking the watcher forever). The tradeoff is that flock is per-machine
and does not work across NFS, which is fine: the watcher is a local process
watching a local checkout.

Scope: the lock lives in the MAIN checkout, not the worktree. Worktrees share one
Confluence space, so the watcher must be a singleton across all of them; a
per-worktree lock would elect one watcher per worktree and reintroduce the race.

Standard-library only, so it stays importable before project dependencies are
installed (same constraint as _atlassian_guard.py).
"""

from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path
from typing import IO, Optional

LOCK_RELPATH = Path(".claude") / "pm-daemon-watcher.lock"

# Escape hatch: set to a truthy value to force a daemon to skip the watcher
# entirely (serve MCP tools only), regardless of who holds the lock.
DISABLE_ENV = "PM_DAEMON_DISABLE_WATCHER"


def watcher_disabled() -> bool:
    return (os.environ.get(DISABLE_ENV) or "").strip().lower() not in (
        "",
        "0",
        "false",
        "no",
    )


def resolve_main_checkout(start_dir: str | os.PathLike[str]) -> Path:
    """Return the primary checkout for `start_dir`, even from inside a worktree.

    `--git-common-dir` resolves to the shared `.git` of the main checkout from any
    linked worktree, and to the repo's own `.git` in the main checkout. Its parent
    is therefore the main working tree in both cases. Falls back to `start_dir`
    outside a repo (or if git is unavailable), which keeps the lock local rather
    than failing.
    """
    start = Path(start_dir)
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(start),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        common = (out.stdout or "").strip()
        if out.returncode == 0 and common:
            parent = Path(common).parent
            if parent.is_dir():
                return parent
    except Exception:
        pass
    return start


def lock_path_for(start_dir: str | os.PathLike[str]) -> Path:
    return resolve_main_checkout(start_dir) / LOCK_RELPATH


def acquire_watcher_lock(start_dir: str | os.PathLike[str]) -> Optional[IO]:
    """Try to become the single watcher for this checkout.

    Returns an open file handle on success — the CALLER MUST KEEP IT ALIVE for as
    long as it wants the lock, because closing the handle (or the process exiting)
    releases it. Returns None if another daemon already holds the lock, or if the
    watcher is disabled by env var.

    Never raises: a daemon that cannot take the lock must still come up and serve
    its MCP tools. Failing to watch is a degraded mode, not a fatal one.
    """
    if watcher_disabled():
        return None

    path = lock_path_for(start_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+")
    except OSError:
        return None

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Held by another live daemon. Expected and benign.
        handle.close()
        return None

    # Record who won, for humans debugging "why isn't my save syncing".
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n")
        handle.flush()
    except OSError:
        pass  # The lock is what matters; the annotation is a nicety.

    return handle


def read_lock_holder(start_dir: str | os.PathLike[str]) -> Optional[int]:
    """PID recorded in the lock file, or None. For diagnostics only.

    This is advisory: the PID is whatever the holder last wrote. Do not use it to
    decide whether the lock is free — that is what acquire_watcher_lock is for.
    """
    try:
        raw = lock_path_for(start_dir).read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def release_watcher_lock(handle: Optional[IO]) -> None:
    """Release the lock. Safe to call with None or an already-closed handle."""
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError):
        pass
    try:
        handle.close()
    except OSError:
        pass
