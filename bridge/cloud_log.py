"""The cloud departments' log: lines on the bridge process's stderr only.

A line can carry git's or the runner's own words, so it never goes to the
recorder's LOG_DIR archive (bridge/failure_diagnostics.py keeps provider and
tool text out of it). The logger has its own handler and does not propagate:
the root logger is untouched and a local-only bridge prints nothing new.
"""

import logging
import re
import sys
from typing import Callable

NAME = "bridge.cloud"
LIMIT = 300

# From the scheme to the last "@" before whitespace: userinfo may hold a "/".
# A path with an "@" loses its host too; over-scrubbing a log is the safe side.
USERINFO = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)\S*@")


class _Stderr(logging.StreamHandler):
    """Writes to the current sys.stderr, not the one there at import."""

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, value):
        pass


log = logging.getLogger(NAME)
if not any(handler.name == NAME for handler in log.handlers):
    _handler = _Stderr()
    _handler.set_name(NAME)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
    log.addHandler(_handler)
log.propagate = False
log.setLevel(logging.WARNING)


def remote(text, clean: Callable[[str], str] | None = None) -> str:
    """A remote string for a line: one line, scrubbed, at most LIMIT characters."""
    text = str(text)
    if clean is not None:
        text = clean(text)
    text = " ".join(text.split())
    return USERINFO.sub(r"\1", text)[:LIMIT]


def warn(department: str, step: str, what: str, *args) -> None:
    """One line: the department, the step that failed, then what happened."""
    log.warning("%s: %s: " + what, department, step, *args)
