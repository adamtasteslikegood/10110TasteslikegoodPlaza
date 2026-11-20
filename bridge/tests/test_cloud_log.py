"""The bridge.cloud logger: its own stderr handler, no propagation, scrubbed text."""

import importlib
import logging

from bridge import cloud_log


def handlers():
    return [
        h
        for h in logging.getLogger("bridge.cloud").handlers
        if h.name == "bridge.cloud"
    ]


def test_the_logger_does_not_propagate_and_leaves_the_root_alone(capsys):
    root = list(logging.getLogger().handlers)
    cloud_log.warn("engineering", "start", "runner refused: %s: %s", 422, "no")
    line = capsys.readouterr().err.strip()
    assert line.endswith("bridge.cloud engineering: start: runner refused: 422: no")
    assert line[:4].isdigit()  # the time comes first
    # (pytest 9 hooks its capture onto non-propagating loggers too, so caplog
    # cannot show propagation; the flag and the root's handlers can.)
    assert logging.getLogger("bridge.cloud").propagate is False
    assert logging.getLogger().handlers == root
    assert all(h.name != "bridge.cloud" for h in root)


def test_the_handler_is_attached_once(capsys):
    importlib.reload(cloud_log)
    importlib.reload(cloud_log)
    assert len(handlers()) == 1
    cloud_log.warn("engineering", "run", "push failed: %s", "denied")
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_remote_text_is_one_line_scrubbed_and_cut():
    text = (
        "a\n\tb  https://x-access-token:ghs_123@github.com/o/r.git SECRET " + "z" * 500
    )
    out = cloud_log.remote(text, lambda t: t.replace("SECRET", "***"))
    assert "\n" not in out and "\t" not in out
    assert "ghs_123" not in out and "x-access-token" not in out
    assert out.startswith("a b https://github.com/o/r.git *** z")
    assert len(out) == cloud_log.LIMIT
    assert cloud_log.remote(RuntimeError("plain")) == "plain"
