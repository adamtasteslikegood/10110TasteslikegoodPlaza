#!/usr/bin/env python3
"""Bounded, offline M13 measurements and source-bound owner acceptance receipts.

No provider, authentication mutation, project reset, import or real project write.
Each performance profile runs in a fresh process against disposable state only.
Desktop receipts are explicit human attestations, never inferred from test passes.
"""

import argparse
import asyncio
from dataclasses import astuple
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bridge.application_state import MAX_IMAGE_BYTES, RequestRecord, StateCommand
from bridge.sqlite_state import SQLiteStateRepository, initial_image
from bridge.state_coordinator import StateCoordinator
from bridge.state_image import StateImage
from bridge.tool_guard_evidence import GUARD_SOURCES, PERMISSION_MODES
from scripts.evidence_output import FreshEvidenceOutput

MAX_REPORT_BYTES = 256 * 1024
PROFILES = ("representative", "dense", "boundary")
DESKTOP_CASES = (
    "stop_restart_exact_history_no_execution",
    "explicit_start_fresh_execution_same_application",
    "end_attribution_restart_new_application",
    "first_run_bounded_recap_once",
    "fresh_game_ended_history_and_surface_handoff",
    "crash_accepted_not_executed_no_retry",
    "crash_dispatched_interrupted_no_retry",
    "commit_before_delivery_exact_replay",
    "failed_storage_unsaved_closed_admission_recovery",
    "stale_controls_and_second_writer_denied",
    "explicit_memory_sqlite_discontinuity",
    "orderly_shutdown_releases_ownership",
)


def source_names(root):
    """Bind runtime plus the executable tests that define completeness."""
    names = set(GUARD_SOURCES) | {
        "requirements.txt",
        "package.json",
        "project.godot",
        "data/agents.json",
    }
    for folder in ("bridge", "scripts", "scenes", "autoload", "tests"):
        for path in (root / folder).rglob("*"):
            # Acceptance reports are evidence, not implementation/configuration;
            # exclude the fixed guard envelope to avoid binding artifacts to artifacts.
            if path == root / "bridge/tool_guard_acceptance.json":
                continue
            if path.is_file() and path.suffix in {".py", ".gd", ".tscn", ".json"}:
                names.add(path.relative_to(root).as_posix())
    return sorted(names)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def executable(path):
    resolved = Path(shutil.which(str(path)) or path).resolve(strict=True)
    result = subprocess.run(
        [str(resolved), "--version"], capture_output=True, timeout=10, check=True
    )
    if len(result.stdout) > 1024:
        raise ValueError("Oversized runtime version")
    return {"version": result.stdout.decode().strip(), "sha256": sha(resolved)}


def binding(root, engine):
    """Exact local source, installed dependency, CLI, Python/SQLite, OS and engine."""
    import claude_agent_sdk

    dependencies = {}
    for line in (root / "requirements.txt").read_text().splitlines():
        if "==" in line and not line.startswith("#"):
            name, pinned = line.split("==", 1)
            installed = importlib.metadata.version(name)
            if installed != pinned:
                raise ValueError(
                    "Installed dependency differs from requirements: " + name
                )
            dependencies[name] = installed
    return dict(
        sources={name: sha(root / name) for name in source_names(root)},
        dependencies=dependencies,
        runtime=dict(
            python=platform.python_version(),
            implementation=platform.python_implementation(),
            sqlite=sqlite3.sqlite_version,
            os=platform.system(),
            release=platform.release(),
            machine=platform.machine(),
            sdk=importlib.metadata.version("claude-agent-sdk"),
            cli=executable(Path(claude_agent_sdk.__file__).parent / "_bundled/claude"),
        ),
        engine=executable(engine),
    )


def validate_report(
    report, expected, *, kind, permission_mode=None, authentication=None
):
    if not isinstance(report, dict):
        return ["Malformed report"]
    errors = []
    if (
        report.get("schema_version") != 1
        or type(report.get("schema_version")) is not int
    ):
        errors.append("Wrong report schema")
    if report.get("kind") != kind or kind not in ("desktop", "performance"):
        errors.append("Wrong report kind")
    if report.get("binding") != expected:
        errors.append("Stale source or mismatched runtime/dependency/OS/engine binding")
    if not expected.get("engine", {}).get("version", "").startswith("4.7.1."):
        errors.append("Required pinned Godot 4.7.1 is unverified")
    if report.get("backend") != "sqlite":
        errors.append("Expected SQLite backend")
    if kind == "desktop":
        if report.get("permission_mode") not in PERMISSION_MODES or (
            permission_mode is not None
            and report.get("permission_mode") != permission_mode
        ):
            errors.append("Missing or mismatched permission mode")
        if report.get("authentication") not in ("oauth", "api_key") or (
            authentication is not None
            and report.get("authentication") != authentication
        ):
            errors.append("Missing or mismatched explicit authentication path")
        cases = report.get("cases")
        if not isinstance(cases, list):
            return errors + ["Incomplete desktop acceptance"]
        if (
            len(cases) != len(DESKTOP_CASES)
            or any(not isinstance(c, dict) for c in cases)
            or any(not isinstance(c.get("name"), str) for c in cases)
            or {c.get("name") for c in cases} != set(DESKTOP_CASES)
            or any(
                c.get("passed") is not True
                or not isinstance(c.get("observed"), str)
                or not 1 <= len(c["observed"].encode()) <= 2048
                for c in cases
            )
        ):
            errors.append("Incomplete or duplicated desktop acceptance")
    else:
        profiles = report.get("profiles")
        if not isinstance(profiles, list) or len(profiles) != 3:
            return errors + ["Incomplete performance profiles"]
        if any(
            not isinstance(p, dict) or not isinstance(p.get("profile"), str)
            for p in profiles
        ) or {p.get("profile") for p in profiles} != set(PROFILES):
            return errors + ["Incomplete or duplicated performance profiles"]
        for measured in profiles:
            errors.extend(measurement_errors(measured))
    return errors


def measurement_errors(measured):
    errors = []
    integer_fields = (
        "image_bytes",
        "populated_bytes",
        "free_page_bytes",
        "baseline_rss_bytes",
        "peak_rss_bytes",
        "old_plus_new_image_bytes",
        "commit_count",
        "physical_image_replacements",
        "process_overhead_bytes",
    )
    if any(type(measured.get(k)) is not int or measured[k] < 0 for k in integer_fields):
        return ["Missing measured sizes/counts"]
    image = measured["image_bytes"]
    if (
        not 0 < image <= MAX_IMAGE_BYTES
        or measured["old_plus_new_image_bytes"] != 2 * image
    ):
        errors.append("Invalid image/transient disk measurement")
    if measured["physical_image_replacements"] != measured["commit_count"] + 1:
        errors.append("Physical atomic replacements missing")
    if measured["populated_bytes"] + measured["free_page_bytes"] != image:
        errors.append("Missing image occupancy")
    if measured.get("profile") == "boundary" and image != MAX_IMAGE_BYTES:
        errors.append("Exact 64 MiB boundary missing")
    if measured.get("profile") == "dense" and (
        image < 63 * 1024 * 1024 or measured["free_page_bytes"] > image // 100
    ):
        errors.append("Near-cap populated measurement missing")
    latencies = measured.get("commit_ms")
    if (
        not isinstance(latencies, list)
        or not 2 <= len(latencies) <= 20
        or measured["commit_count"] != len(latencies)
        or any(
            type(x) not in (int, float) or not math.isfinite(x) or x < 0
            for x in latencies
        )
    ):
        errors.append("Repeated commit observations missing")
    blocked = measured.get("blocked_writer", {})
    if not isinstance(blocked, dict) or (
        blocked.get("writer_pending") is not True
        or blocked.get("committed_revision_unchanged") is not True
        or type(blocked.get("heartbeat_before_release")) is not int
        or blocked.get("heartbeat_before_release", 0) < 3
        or type(blocked.get("replay_before_release")) is not int
        or blocked.get("replay_before_release", 0) < 3
    ):
        errors.append("Blocked writer responsiveness unproven")
    if measured.get("reopened_exact") is not True:
        errors.append("Reopen comparison missing")
    if (
        measured["peak_rss_bytes"] < measured["baseline_rss_bytes"]
        or measured["process_overhead_bytes"]
        != measured["peak_rss_bytes"] - measured["baseline_rss_bytes"]
    ):
        errors.append("Invalid peak RSS or process overhead")
    if (
        not isinstance(measured.get("image_sha256"), str)
        or len(measured["image_sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in measured["image_sha256"])
    ):
        errors.append("Image fingerprint missing")
    if (
        type(measured.get("heartbeat_max_gap_ms"))
        not in (
            float,
            int,
        )
        or not math.isfinite(measured["heartbeat_max_gap_ms"])
        or measured["heartbeat_max_gap_ms"] < 0
    ):
        errors.append("Heartbeat latency missing")
    return errors


def uid(name):
    return str(uuid5(NAMESPACE_URL, "plaza-m13-probe/" + name))


def fixture_data(instance, profile):
    """Populate valid v1 rows in memory; production repository validates on open.

    Dense: 10 applications, 160 results, 40 MiB output + 20 MiB duplicated task
    text + 3.125 MiB JSON escape overhead. Boundary adds free pages to the
    representative fixture; it is an image-I/O limit, not worst-case content.
    """
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(initial_image("probe-project", instance))
        dense = profile == "dense"
        for domain in range(10 if dense else 1):
            name = "core" if domain == 0 else "probe-" + str(domain)
            session, execution = uid(name), uid(name + "/execution")
            connection.execute("INSERT INTO domains VALUES (?,?,1)", (name, session))
            connection.execute(
                "INSERT INTO sessions VALUES (?,?,?,NULL,NULL,?)",
                (session, name, "probe-created", 16 if dense else 8),
            )
            connection.execute(
                "INSERT INTO executions VALUES (?,?,?,?,?,?)",
                (
                    execution,
                    session,
                    uid("boot"),
                    "probe-start",
                    "probe-stop" if domain else None,
                    "stopped" if domain else None,
                ),
            )
            for index in range(16 if dense else 8):
                request = str(index + 1)
                task = "Synthetic task " + "t" * ((65536 if dense else 1024) - 15)
                output = "\t" * (20480 if dense else 0) + "o" * (
                    (262144 - 20480) if dense else 131072
                )
                record = RequestRecord(
                    session,
                    request,
                    execution,
                    "probe",
                    task,
                    hashlib.sha256(task.encode()).hexdigest(),
                    uid(name + "/" + request),
                    1,
                    "terminal",
                    0,
                )
                packet = dict(
                    type="domain_result",
                    request_id=request,
                    domain_session_id=session,
                    execution_id=execution,
                    agent_id="probe",
                    task=task,
                    output=output,
                    output_id=request,
                    status="success",
                    reason="completed",
                    memory={"saved": True},
                )
                connection.execute(
                    "INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?)", astuple(record)
                )
                connection.execute(
                    "INSERT INTO terminals VALUES (?,?,?,?,?)",
                    (
                        session,
                        request,
                        index + 1,
                        json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                        len(output.encode()),
                    ),
                )
        connection.commit()
        if profile == "boundary":
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            target = MAX_IMAGE_BYTES // page_size
            connection.execute(f"PRAGMA max_page_count={target}")
            connection.execute("CREATE TABLE disposable_padding (value BLOB)")
            connection.commit()
            while connection.execute("PRAGMA page_count").fetchone()[0] < target:
                connection.execute(
                    "INSERT INTO disposable_padding VALUES (zeroblob(3000))"
                )
                connection.commit()
            connection.execute("DROP TABLE disposable_padding")
            connection.commit()
        data = connection.serialize()
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        free = connection.execute("PRAGMA freelist_count").fetchone()[0] * page_size
        return data, free
    finally:
        connection.close()


def peak_rss():
    # getrusage units differ on macOS. Profiles run in separate fresh processes.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


async def measure(directory, *, profile, repeats=5):
    if profile not in PROFILES or type(repeats) is not int or not 2 <= repeats <= 20:
        raise ValueError("Choose a known profile and 2..20 commits")
    baseline = peak_rss()
    entered, release = threading.Event(), threading.Event()
    images = []
    free_pages = []
    armed = [True]
    transient, replacements = [0], [0]

    class MeasuredImage:
        def __init__(self, image):
            self.image = image

        def __getattr__(self, name):
            return getattr(self.image, name)

        def replace(self, data):
            if armed[0]:
                armed[0] = False
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("Probe writer was not released")
            original = self.image._validate

            def observed_validate():
                original()
                total = 0
                for name in os.listdir(self.image._parent):
                    if name == "state.sqlite3" or (
                        name.startswith(".state.sqlite3.") and name.endswith(".tmp")
                    ):
                        total += os.stat(
                            name, dir_fd=self.image._parent, follow_symlinks=False
                        ).st_size
                transient[0] = max(transient[0], total)

            self.image._validate = observed_validate
            try:
                self.image.replace(data)
                replacements[0] += 1
            finally:
                self.image._validate = original

    def factory():
        directory.mkdir(parents=True, exist_ok=True)

        def create(instance):
            data, free = fixture_data(instance, profile)
            free_pages.append(free)
            return data

        image = StateImage.open(
            directory, "probe-project", initialize=True, initial_image=create
        )
        images.append(image)
        return SQLiteStateRepository(MeasuredImage(image))

    coordinator = StateCoordinator(factory)
    ticks, gaps = [], []
    running = [True]

    async def heartbeat():
        previous = time.perf_counter()
        while running[0]:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            gaps.append((now - previous) * 1000)
            ticks.append(now)
            previous = now

    heart = asyncio.create_task(heartbeat())
    try:
        await coordinator.open()
        session = uid("core")
        before = coordinator.snapshot()
        execution = uid("core/execution")
        command = StateCommand(
            "stop",
            dict(execution_id=execution, outcome="stopped", timestamp="probe-stop"),
        )
        writer = asyncio.create_task(coordinator.commit(command))
        if not await asyncio.wait_for(asyncio.to_thread(entered.wait, 5), 6):
            raise RuntimeError("Probe writer did not enter barrier")
        tick_start = len(ticks)
        replay_count = 0
        unchanged = True
        # Progress must occur while release is still closed; no sleep-after-I/O proof.
        for _ in range(5):
            await asyncio.sleep(0.01)
            window = coordinator.replay(session, 0)
            if len(window.entries) != (16 if profile == "dense" else 8):
                raise RuntimeError("Committed replay changed during blocked write")
            replay_count += 1
            unchanged &= coordinator.snapshot().revision == before.revision
        blocked = dict(
            writer_pending=not writer.done(),
            heartbeat_before_release=len(ticks) - tick_start,
            replay_before_release=replay_count,
            committed_revision_unchanged=unchanged,
        )
        release.set()
        await writer
        times = []
        revision = coordinator.snapshot().domains[0].domain_revision
        for index in range(repeats):
            if index % 2 == 0:
                execution = uid("repeat/" + str(index))
                command = StateCommand(
                    "start",
                    dict(
                        domain_id="core",
                        expected_domain_revision=revision,
                        boot_id=uid("boot"),
                        execution_id=execution,
                        timestamp="probe-start",
                    ),
                )
            else:
                command = StateCommand(
                    "stop",
                    dict(
                        execution_id=execution,
                        outcome="stopped",
                        timestamp="probe-stop",
                    ),
                )
            started = time.perf_counter()
            commit = await coordinator.commit(command)
            times.append((time.perf_counter() - started) * 1000)
            revision = next(
                d.domain_revision for d in commit.view.domains if d.domain_id == "core"
            )
        final = coordinator.snapshot()
        await coordinator.close()
        image = images.pop()
        image.close()
        reopened = StateImage.open(directory, "probe-project")
        try:
            repository = SQLiteStateRepository(reopened)
            exact = repository.load() == final
            page_size = repository._connection.execute("PRAGMA page_size").fetchone()[0]
            final_free = (
                repository._connection.execute("PRAGMA freelist_count").fetchone()[0]
                * page_size
            )
            repository.close()
            size, fingerprint = (
                len(reopened.read()),
                hashlib.sha256(reopened.read()).hexdigest(),
            )
        finally:
            reopened.close()
        result = dict(
            profile=profile,
            image_bytes=size,
            populated_bytes=size - final_free,
            free_page_bytes=final_free,
            commit_count=len(times),
            commit_ms=times,
            baseline_rss_bytes=baseline,
            peak_rss_bytes=peak_rss(),
            process_overhead_bytes=peak_rss() - baseline,
            old_plus_new_image_bytes=transient[0],
            physical_image_replacements=replacements[0],
            failed_remnants_bytes=0,
            blocked_writer=blocked,
            heartbeat_max_gap_ms=max(gaps, default=0.0),
            image_sha256=fingerprint,
            reopened_exact=exact,
        )
        problems = measurement_errors(result)
        if problems:
            raise ValueError("; ".join(problems))
        return result
    finally:
        release.set()
        await coordinator.close()
        for image in images:
            image.close()
        running[0] = False
        await heart


def save_report(output, report, *, final=False):
    encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("Report too large")
    if final:
        output.publish_json(report)
    else:
        output.checkpoint_json(report)


def read_report(path):
    with path.open("rb") as stream:
        data = stream.read(MAX_REPORT_BYTES + 1)
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("Report too large")
    return json.loads(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("performance", "desktop-template", "validate"):
        sub = commands.add_parser(name)
        sub.add_argument("--engine", default="godot")
        if name == "validate":
            sub.add_argument("--report", type=Path, required=True)
            sub.add_argument(
                "--kind", choices=("desktop", "performance"), required=True
            )
        else:
            sub.add_argument("--output", type=Path, required=True)
        if name in ("desktop-template", "validate"):
            sub.add_argument(
                "--permission-mode",
                choices=PERMISSION_MODES,
                required=name == "desktop-template",
            )
            sub.add_argument(
                "--authentication",
                choices=("oauth", "api_key"),
                required=name == "desktop-template",
            )
        else:
            sub.add_argument("--repeats", type=int, default=5, choices=range(2, 21))
    worker = commands.add_parser("profile-worker", help=argparse.SUPPRESS)
    worker.add_argument("--profile", choices=PROFILES, required=True)
    worker.add_argument("--repeats", type=int, default=5, choices=range(2, 21))
    args = parser.parse_args(argv)
    try:
        if args.command == "profile-worker":
            with tempfile.TemporaryDirectory(prefix="plaza-m13-state-") as temp:
                print(
                    json.dumps(
                        asyncio.run(
                            measure(
                                Path(temp) / "common.git",
                                profile=args.profile,
                                repeats=args.repeats,
                            )
                        ),
                        allow_nan=False,
                    )
                )
            return 0
        if args.command == "validate":
            report = read_report(args.report)
            errors = validate_report(
                report,
                binding(ROOT, args.engine),
                kind=args.kind,
                permission_mode=args.permission_mode,
                authentication=args.authentication,
            )
            print(json.dumps(dict(accepted=not errors, errors=errors)))
            return int(bool(errors))
        with FreshEvidenceOutput(args.output) as output:
            current = binding(ROOT, args.engine)
            report = dict(
                schema_version=1,
                kind="desktop" if args.command == "desktop-template" else "performance",
                binding=current,
                backend="sqlite",
            )
            if args.command == "desktop-template":
                report.update(
                    permission_mode=args.permission_mode,
                    authentication=args.authentication,
                    cases=[
                        dict(name=name, passed=False, observed="")
                        for name in DESKTOP_CASES
                    ],
                )
            else:
                report["profiles"] = []
                for profile in PROFILES:
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__)),
                            "profile-worker",
                            "--profile",
                            profile,
                            "--repeats",
                            str(args.repeats),
                        ],
                        capture_output=True,
                        timeout=180,
                        check=True,
                    )
                    if len(result.stdout) > MAX_REPORT_BYTES:
                        raise ValueError("Worker report too large")
                    report["profiles"].append(json.loads(result.stdout))
                    save_report(output, report)
                if binding(ROOT, args.engine) != current:
                    raise ValueError("Sources/runtime changed during measurement")
                errors = validate_report(report, current, kind="performance")
                if errors:
                    raise ValueError("; ".join(errors))
            save_report(output, report, final=True)
        print(
            json.dumps(
                dict(
                    written=True,
                    kind=report["kind"],
                    desktop_acceptance_pending=args.command == "desktop-template",
                )
            )
        )
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(
            json.dumps(
                dict(
                    accepted=False,
                    errors=[
                        (
                            str(error)
                            if isinstance(error, ValueError)
                            else type(error).__name__
                        )
                    ],
                )
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
