"""Source-bound offline measurements cannot stand in for live acceptance."""

from copy import deepcopy
import importlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def required_engine():
    if shutil.which("godot") is None:
        if os.environ.get("PLAZA_REQUIRE_GODOT"):
            pytest.fail("Required pinned Godot is unavailable")
        pytest.skip(
            "Godot not installed; required acceptance uses PLAZA_REQUIRE_GODOT=1"
        )


def probe():
    assert importlib.util.find_spec("scripts.m13_state_probe"), "state probe missing"
    return importlib.import_module("scripts.m13_state_probe")


def test_probe_binding_rejects_changed_sources_runtime_backend_and_missing_cases():
    api = probe()
    binding = api.binding(ROOT, "godot")
    report = dict(
        schema_version=1,
        kind="desktop",
        binding=binding,
        backend="sqlite",
        permission_mode="dontAsk",
        authentication="oauth",
        cases=[
            dict(name=name, passed=True, observed="Owner verified expected state")
            for name in api.DESKTOP_CASES
        ],
    )
    assert (
        api.validate_report(
            report,
            binding,
            kind="desktop",
            permission_mode="dontAsk",
            authentication="oauth",
        )
        == []
    )
    for key, changed in [
        ("sources", {}),
        ("runtime", {}),
        ("engine", {}),
        ("dependencies", {}),
    ]:
        bad = deepcopy(report)
        bad["binding"][key] = changed
        assert api.validate_report(bad, binding, kind="desktop")
    for key, value in [
        ("backend", "memory"),
        ("cases", report["cases"][:-1]),
        ("cases", report["cases"] + report["cases"][:1]),
        ("permission_mode", "unknown"),
        ("authentication", "unset-key"),
    ]:
        bad = deepcopy(report)
        bad[key] = value
        assert api.validate_report(bad, binding, kind="desktop")
    report["cases"][0]["passed"] = 1
    assert api.validate_report(report, binding, kind="desktop")


@pytest.mark.asyncio
async def test_blocked_durable_writer_reports_heartbeat_and_committed_replay_before_release(
    tmp_path,
):
    api = probe()
    measured = await api.measure(tmp_path, profile="representative", repeats=2)
    assert measured["image_bytes"] >= 1024 * 1024
    assert measured["populated_bytes"] > 0
    assert measured["commit_count"] == 2 and len(measured["commit_ms"]) == 2
    assert all(x >= 0 for x in measured["commit_ms"])
    assert measured["blocked_writer"]["writer_pending"] is True
    assert measured["blocked_writer"]["heartbeat_before_release"] >= 3
    assert measured["blocked_writer"]["replay_before_release"] >= 3
    assert measured["blocked_writer"]["committed_revision_unchanged"] is True
    assert measured["physical_image_replacements"] == 3
    assert measured["old_plus_new_image_bytes"] == 2 * measured["image_bytes"]
    assert measured["peak_rss_bytes"] >= measured["baseline_rss_bytes"] > 0
    assert len(measured["image_sha256"]) == 64
    assert measured["reopened_exact"] is True


def test_bounded_fresh_report_cli_rejects_incomplete_desktop_receipt(tmp_path):
    api = probe()
    output = tmp_path / "template.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/m13_state_probe.py"),
        "desktop-template",
        "--output",
        str(output),
        "--engine",
        "godot",
        "--permission-mode",
        "dontAsk",
        "--authentication",
        "oauth",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert all(item["passed"] is False for item in report["cases"])
    check = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/m13_state_probe.py"),
            "validate",
            "--report",
            str(output),
            "--kind",
            "desktop",
            "--engine",
            "godot",
            "--permission-mode",
            "dontAsk",
            "--authentication",
            "oauth",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert check.returncode == 1 and "incomplete" in check.stdout.lower()
    assert subprocess.run(command, capture_output=True, timeout=20).returncode != 0
    report["private"] = "x" * api.MAX_REPORT_BYTES
    output.write_text(json.dumps(report))
    check = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/m13_state_probe.py"),
            "validate",
            "--report",
            str(output),
            "--kind",
            "desktop",
            "--engine",
            "godot",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert check.returncode == 1 and "too large" in check.stdout.lower()


def test_malformed_case_names_reject_without_validator_crash():
    api = probe()
    current = api.binding(ROOT, "godot")
    for kind, records in [("desktop", "cases"), ("performance", "profiles")]:
        count = len(api.DESKTOP_CASES) if kind == "desktop" else 3
        bad = dict(
            schema_version=1,
            kind=kind,
            backend="sqlite",
            binding=current,
            permission_mode="dontAsk",
            authentication="oauth",
            **{records: [dict(name={}, profile={}) for _ in range(count)]}
        )
        assert api.validate_report(bad, current, kind=kind)


@pytest.mark.asyncio
async def test_performance_validation_rejects_missing_or_fabricated_measurements(
    tmp_path,
):
    api = probe()
    measured = await api.measure(tmp_path, profile="representative", repeats=2)
    assert api.measurement_errors(measured) == []
    for key, value in [
        ("image_sha256", "z" * 64),
        ("heartbeat_max_gap_ms", -1),
        ("process_overhead_bytes", -1),
    ]:
        wrong = deepcopy(measured)
        wrong[key] = value
        assert api.measurement_errors(wrong), key


def test_report_publication_enforces_same_byte_bound_as_reader(tmp_path, monkeypatch):
    api = probe()
    monkeypatch.setattr(api, "MAX_REPORT_BYTES", 10)
    destination = tmp_path / "oversized.json"
    assert (
        api.main(
            [
                "desktop-template",
                "--output",
                str(destination),
                "--engine",
                "godot",
                "--permission-mode",
                "dontAsk",
                "--authentication",
                "oauth",
            ]
        )
        == 1
    )
    assert not destination.exists()
