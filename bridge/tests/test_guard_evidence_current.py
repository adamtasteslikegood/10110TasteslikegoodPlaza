"""The committed tool-guard evidence must match the guarded sources as committed.

The bridge refuses to start the real SDK when it does not (``_verify_runtime``),
and every other suite injects a stand-in client that skips that check. So a
change to a ``GUARD_SOURCES`` file fails here until the guard probe has been run
again in both modes and its evidence published (QUICKSTART, PLZG-309).
"""

import json
from pathlib import Path

import pytest

from bridge.domain_sdk import ACCEPTANCE_PATH, check_acceptance
from bridge.tool_guard_evidence import PERMISSION_MODES, validate_evidence

ROOT = Path(__file__).resolve().parents[2]


def _evidence():
    return json.loads(ACCEPTANCE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mode", PERMISSION_MODES)
def test_committed_guard_evidence_matches_the_guarded_sources(mode):
    record = _evidence()["records"][mode]
    stale = validate_evidence(record, ROOT, permission_mode=mode)
    assert stale == [], (
        "A guarded source changed without fresh guard evidence, so no real "
        "domain session can start. Run scripts/m12_tool_guard_probe.py in both "
        f"permission modes and publish the result: {stale}"
    )


@pytest.mark.parametrize("mode", PERMISSION_MODES)
def test_the_bridge_would_accept_the_committed_guard_evidence(mode):
    assert check_acceptance(_evidence(), ROOT, mode)["permission_mode"] == mode
