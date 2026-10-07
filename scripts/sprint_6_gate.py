#!/usr/bin/env python3
"""Acceptance checks for Sprint 6, one subcommand per loop-plan task.

``specs/sprint-6-loop-plan.json`` names these as each task's ``acceptance.cmd``.
The sprint has two gates, and the reason this file exists is that before it
neither half of the sprint goal was proven by a command:

* **Gate A** -- the office is walkable. ``tests/smoke_test.tscn`` checked three
  rooms' worth of nodes and never moved a body through a doorway.
* **Gate B** -- the bridge carries a live conversation. The smoke test emits
  ``agent_response_received`` with a literal string, so M8's "done" was asserted
  by a simulated reply. ``live`` asks a real model two turns, from Godot and
  from a client that has never heard of Godot (``D-005`` swap test).

Each check asks the system that owns the fact: Jira for the board, Godot for
the scene, the bridge for the conversation. The Jira client, the credential
handling and the exit codes are ``sprint_5_gate.py``'s, imported rather than
copied, so a fix to one is a fix to both.

Identifiers are NOT held here. The sprint, the board, the ticket keys, the room
ids and every path are read from the loop plan.

Stdlib only. Exit codes: 0 pass, 1 the check failed, 2 it could not be run --
which includes a Gate B that could not authenticate. A gate that cannot reach
the model has not shown the bridge is broken, and must not read as if it had.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sprint_5_gate as base  # noqa: E402
from sprint_5_gate import GateError, GateFailure, require, task  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = REPO_ROOT / "specs" / "sprint-6-loop-plan.json"
REGISTRY_PATH = REPO_ROOT / "specs" / "meta" / "doc-registry.json"

# What the Godot scenes print for this gate to read. A scene's exit code says
# whether ITS assertions held; these lines say WHAT it looked at, so a test that
# stops checking a room turns the gate red instead of staying quietly green.
PROBE_LINE = re.compile(r"^PROBE (rooms|doorways|locked_corridors): ?(.*)$", re.M)
REACHABLE_LINE = re.compile(r"^SMOKE rooms_reachable: ?(.*)$", re.M)
BLOCKED_LINE = re.compile(r"^SMOKE corridors_blocked: ?(.*)$", re.M)

# A ticket moved to In Progress and Done in the same breath records a
# bookkeeping click, not work. Twenty of the 41 cycle times measured on
# 2026-10-06 were under an hour, which is what kept the forecast blackout shut.
MIN_CYCLE = timedelta(hours=1)
GODOT_TIMEOUT_SECONDS = 180
# Three tries of two model turns from two clients, with room to spare. A stalled
# bridge or socket must end as a failed gate, not a gate that never answers.
LIVE_TIMEOUT_SECONDS = 900


def load_plan() -> dict:
    return base.load_json(PLAN_PATH)


def inputs(plan: dict, task_id: str) -> dict:
    return task(plan, task_id).get("acceptance_inputs", {})


def split_ids(text: str) -> set:
    return {part.strip() for part in text.split(",") if part.strip()}


# --------------------------------------------------------------------------
# Godot
# --------------------------------------------------------------------------


def run_godot(scene: str) -> "tuple[int, str]":
    """Run one headless scene; return its exit code and everything it printed."""
    require((REPO_ROOT / scene).is_file(), f"{scene} does not exist")
    godot = shutil.which("godot")
    if godot is None:
        raise GateError("godot is not on PATH")
    try:
        result = subprocess.run(
            [godot, "--headless", scene],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=GODOT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateFailure(f"{scene} did not exit in {GODOT_TIMEOUT_SECONDS}s") from exc
    return result.returncode, f"{result.stdout}{result.stderr}"


def probe(plan: dict) -> dict:
    """What the running main scene declares: rooms, doorways, locked corridors."""
    scene = inputs(plan, "T2").get("probe_scene")
    require(bool(scene), "T2 declares no probe_scene")
    code, output = run_godot(scene)
    require(code == 0, f"{scene} exited {code}:\n{output.strip()[-800:]}")
    found = {kind: split_ids(ids) for kind, ids in PROBE_LINE.findall(output)}
    for kind in ("rooms", "doorways", "locked_corridors"):
        require(kind in found, f"{scene} printed no 'PROBE {kind}:' line")
    return found


def check_t2(plan: dict) -> str:
    """Every room the plan names exists in the running scene."""
    rooms = inputs(plan, "T2").get("rooms")
    require(isinstance(rooms, list) and bool(rooms), "T2 names no rooms")
    found = probe(plan)
    missing = sorted(set(rooms) - found["rooms"])
    require(not missing, f"rooms not in the running scene: {missing}")
    return f"all {len(rooms)} room(s) present"


def check_t3(plan: dict) -> str:
    """Every room has a doorway, and enough corridors are locked."""
    rooms = inputs(plan, "T2").get("rooms", [])
    spec = inputs(plan, "T3")
    minimum = spec.get("min_locked_corridors")
    require(isinstance(minimum, int), "T3 declares no min_locked_corridors")
    found = probe(plan)
    # The room a player starts in is entered by no doorway.
    need = set(rooms) - {spec.get("start_room")}
    undoored = sorted(need - found["doorways"])
    require(not undoored, f"rooms with no doorway trigger: {undoored}")
    locked = len(found["locked_corridors"])
    require(locked >= minimum, f"{locked} locked corridor(s), need {minimum}")
    return f"{len(need)} doorway(s), {locked} locked corridor(s)"


def check_t4(plan: dict) -> str:
    """Gate A: the smoke test passes AND says it walked into every room."""
    rooms = inputs(plan, "T2").get("rooms", [])
    scene = inputs(plan, "T4").get("smoke_scene")
    require(bool(scene), "T4 declares no smoke_scene")
    code, output = run_godot(scene)
    require(code == 0, f"{scene} exited {code}:\n{output.strip()[-800:]}")
    match = REACHABLE_LINE.search(output)
    require(match is not None, f"{scene} printed no 'SMOKE rooms_reachable:' line")
    unreached = sorted(set(rooms) - split_ids(match.group(1)))
    require(not unreached, f"rooms the smoke test did not walk into: {unreached}")
    # A corridor in the `locked_corridors` group is a declaration. Whether it
    # stops anyone is behaviour, and only a body walked into it shows that.
    minimum = inputs(plan, "T3").get("min_locked_corridors")
    require(isinstance(minimum, int), "T3 declares no min_locked_corridors")
    blocked = BLOCKED_LINE.search(output)
    require(blocked is not None, f"{scene} printed no 'SMOKE corridors_blocked:' line")
    # Only corridors the running scene declares locked count. Otherwise the
    # test could print two names of its own and be believed.
    declared = probe(plan)["locked_corridors"]
    reported = split_ids(blocked.group(1))
    undeclared = sorted(reported - declared)
    require(
        not undeclared,
        f"smoke test reports corridors the scene does not declare locked: "
        f"{undeclared}",
    )
    stopped = len(reported)
    require(
        stopped >= minimum,
        f"the smoke test was stopped by {stopped} locked corridor(s), need {minimum}",
    )
    return (
        f"smoke test green, {len(rooms)} room(s) reachable, "
        f"{stopped} locked corridor(s) held"
    )


# --------------------------------------------------------------------------
# Gate B
# --------------------------------------------------------------------------


def run_live(plan: dict) -> "tuple[int, str]":
    """Run the live runner; return its exit code (0 or 1) and its output.

    The runner is T5's deliverable and does not exist until T5 lands; until
    then this FAILS, which is the truthful answer to "is the bridge proven?".
    Its exit 2 -- no credential -- is raised as could-not-run, so it stays a 2
    here and can never close the sprint.
    """
    spec = inputs(plan, "T5")
    runner = spec.get("live_runner")
    require(bool(runner), "T5 declares no live_runner")
    require((REPO_ROOT / runner).is_file(), f"{runner} does not exist yet (T5)")
    try:
        result = subprocess.run(
            [sys.executable, runner],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=LIVE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateFailure(f"{runner} did not exit in {LIVE_TIMEOUT_SECONDS}s") from exc
    output = f"{result.stdout}{result.stderr}".strip()
    if result.returncode == 2:
        raise GateError(f"{runner} could not run:\n{output[-800:]}")
    return result.returncode, output


def check_t5(plan: dict) -> str:
    """The live path answers real requests from both clients.

    Recall is NOT asked for here. The conversation path is stateless when this
    sprint opens, so the runner is expected to exit 1 on turn 2 until T6 fixes
    it; what T5 has to show is that the runner exists, reached a real model
    from Godot and from the plain client, and wrote down what came back.
    """
    run_live(plan)
    return check_transcript(plan, require_recall=False)


def check_live(plan: dict) -> str:
    """Gate B: two real turns through the bridge, in-engine and without Godot."""
    code, output = run_live(plan)
    runner = inputs(plan, "T5").get("live_runner")
    require(code == 0, f"{runner} failed:\n{output[-800:]}")
    return check_transcript(plan)


def check_transcript(plan: dict, require_recall: bool = True) -> str:
    """The transcript shows real replies and, for Gate B, a conversation."""
    spec = inputs(plan, "T5")
    rel = spec.get("transcript")
    require(bool(rel), "T5 declares no transcript path")
    transcript = base.load_json(REPO_ROOT / rel)
    nonce = transcript.get("nonce")
    require(isinstance(nonce, str) and len(nonce) >= 8, f"{rel}: nonce missing")
    forbidden = spec.get("simulated_reply", "")
    clients = transcript.get("clients")
    require(isinstance(clients, dict), f"{rel}: clients missing")
    names = spec.get("clients")
    # One client proves the bridge works for that client. D-005 is about the
    # second one, so a plan naming fewer than two has no Gate B to pass.
    require(
        isinstance(names, list) and len(set(names)) >= 2,
        "T5 must name at least two distinct clients",
    )
    for name in names:
        turns = (clients.get(name) or {}).get("turns")
        require(
            isinstance(turns, list) and len(turns) == 2,
            f"{rel}: client {name!r} must record exactly two turns",
        )
        for index, turn in enumerate(turns, 1):
            reply = turn.get("received")
            require(
                isinstance(reply, str) and bool(reply.strip()),
                f"{rel}: {name} turn {index} has no reply",
            )
            require(
                not forbidden or reply.strip() != forbidden,
                f"{rel}: {name} turn {index} is the simulated reply",
            )
        # Wording varies run to run, so nothing about it is asserted. What must
        # hold is that turn 2 returns a value only turn 1 carried, and that
        # turn 2's own request did not hand it over.
        require(nonce in turns[0].get("sent", ""), f"{rel}: {name} never sent nonce")
        require(
            nonce not in turns[1].get("sent", ""),
            f"{rel}: {name} repeated the nonce in turn 2, which proves nothing",
        )
        require(
            not require_recall or nonce in turns[1]["received"],
            f"{rel}: {name} turn 2 did not recall the nonce -- no conversation",
        )
    outcome = "nonce recalled" if require_recall else "real replies, recall not asked"
    return f"{rel}: {len(names)} client(s), {outcome}"


def check_t6(plan: dict) -> str:
    """Gate B green, with the defects it found counted against the bound."""
    spec = inputs(plan, "T6")
    limit = spec.get("max_defects")
    defects = spec.get("defects")
    require(isinstance(limit, int), "T6 declares no max_defects")
    # A missing list is not an empty one: "found nothing" has to be written down.
    require(isinstance(defects, list), "T6 must record its defects list, even if []")
    require(
        len(defects) <= limit,
        f"{len(defects)} defects fixed in T6, bound is {limit} -- file and escalate",
    )
    return f"{check_live(plan)}; {len(defects)} defect(s) fixed, bound {limit}"


# --------------------------------------------------------------------------
# Jira
# --------------------------------------------------------------------------


def check_t1(plan: dict) -> str:
    """Charter and plan are governed, and Jira holds the sprint as planned."""
    base.governed_count()
    spec = inputs(plan, "T1")
    for rel in spec.get("files", []):
        require((REPO_ROOT / rel).is_file(), f"{rel} is missing")
    registry = base.load_json(REGISTRY_PATH)
    governed = {d["doc_id"] for d in registry.get("documents", [])}
    require(
        spec.get("charter_doc_id") in governed,
        f"{spec.get('charter_doc_id')} is not in the doc registry",
    )

    jira = plan.get("jira", {})
    sprint_id, board_id, epic = (
        jira.get("sprint_id"),
        jira.get("board_id"),
        jira.get("epic"),
    )
    require(
        isinstance(sprint_id, int) and isinstance(board_id, int) and bool(epic),
        "the loop plan must declare jira.sprint_id, jira.board_id and jira.epic",
    )
    sprint = base.jira_get(f"/rest/agile/1.0/sprint/{sprint_id}")
    require(
        sprint.get("originBoardId") == board_id,
        f"sprint {sprint_id} belongs to board {sprint.get('originBoardId')}, "
        f"not {board_id}",
    )
    expected = sorted(t["jira"] for t in plan.get("tasks", []) if t.get("jira"))
    in_sprint = set(base.jira_search(f"sprint = {sprint_id}"))
    absent = sorted(set(expected) - in_sprint)
    require(not absent, f"task tickets not in sprint {sprint_id}: {absent}")
    children = set(base.jira_search(f"parent = {epic}"))
    orphans = sorted(set(expected) - children)
    require(not orphans, f"task tickets not under epic {epic}: {orphans}")
    return (
        f"sprint {sprint_id} ({sprint.get('name')}, {sprint.get('state')}) on board "
        f"{board_id} holds all {len(expected)} task ticket(s) under {epic}"
    )


def parse_jira_time(value: str) -> datetime:
    # Jira writes 2026-10-06T13:50:57.123-0700; fromisoformat wants -07:00.
    return datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value))


def cycle(key: str) -> "tuple[datetime | None, datetime | None]":
    """When ``key`` first entered In Progress and when it last became Done."""
    started = resolved = None
    start_at = 0
    while True:
        page = base.jira_get(
            f"/rest/api/3/issue/{key}/changelog",
            {"startAt": start_at, "maxResults": 100},
        )
        values = page.get("values")
        if not isinstance(values, list):
            raise GateError(f"{key}: changelog response carried no values list")
        for history in values:
            when = parse_jira_time(history["created"])
            for item in history.get("items", []):
                if item.get("field") != "status":
                    continue
                if item.get("toString") == "In Progress" and started is None:
                    started = when
                if item.get("toString") == "Done":
                    resolved = when
        start_at += len(values)
        if page.get("isLast", True) or not values:
            return started, resolved


def check_flow(plan: dict) -> str:
    """Every finished task ticket shows work started before it was closed."""
    own = task(plan, "T7").get("jira")
    keys = sorted(
        t["jira"] for t in plan.get("tasks", []) if t.get("jira") and t["jira"] != own
    )
    live = base.issues_by_key(keys)
    not_done = sorted(k for k in keys if live.get(k, {}).get("category") != "done")
    require(not not_done, f"task tickets not Done in Jira: {not_done}")
    for key in keys:
        started, resolved = cycle(key)
        require(started is not None, f"{key}: never entered In Progress")
        require(resolved is not None, f"{key}: no transition to Done recorded")
        require(
            resolved - started >= MIN_CYCLE,
            f"{key}: started and resolved {resolved - started} apart -- a "
            "bookkeeping transition, not a cycle time",
        )
    return f"{len(keys)} task ticket(s) Done with a real started-to-resolved gap"


def check_acceptance(plan: dict) -> str:
    """The transcript is committed, from this sprint, and accepted by the owner.

    "From this sprint" means captured after the sprint opened. The window's END
    is deliberately not enforced: it is Jira's required date, not a forecast
    (charter §1.3), and a sprint that runs past it is still this sprint. Failing
    the close for being late would be the gate asserting a date nobody promised.
    """
    rel = inputs(plan, "T5").get("transcript", "")
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel],
            capture_output=True,
            cwd=REPO_ROOT,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateError(f"git ls-files did not answer for {rel}") from exc
    require(tracked.returncode == 0, f"{rel} is not committed")
    transcript = base.load_json(REPO_ROOT / rel)
    window = plan.get("jira", {}).get("window", {})
    try:
        captured = datetime.fromisoformat(transcript.get("captured_at", ""))
        opens = datetime.fromisoformat(window.get("start", ""))
    except (TypeError, ValueError) as exc:
        raise GateFailure(
            f"{rel}: captured_at or the plan's jira.window.start is not a timestamp"
        ) from exc
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    if opens.tzinfo is None:
        opens = opens.replace(tzinfo=timezone.utc)
    require(captured >= opens, f"{rel}: captured before this sprint opened")
    # Only the owner sets this. The gate can check the flag; it cannot check
    # who set it, and the charter says so rather than pretending otherwise.
    require(
        transcript.get("owner_read") is True,
        f"{rel}: owner_read is not true -- the owner has not accepted it",
    )
    return f"{rel} committed, captured after the sprint opened, accepted by the owner"


def check_t7(plan: dict) -> str:
    """Sprint close: both gates, the transcript accepted, the flow data honest."""
    parts = [
        check_t1(plan),
        check_t4(plan),
        check_live(plan),
        check_acceptance(plan),
        check_flow(plan),
        base.check_snapshot(),
    ]
    return "; ".join(parts)


CHECKS = {
    "t1": check_t1,
    "t2": check_t2,
    "t3": check_t3,
    "t4": check_t4,
    "t5": check_t5,
    "live": check_live,
    "t6": check_t6,
    "t7": check_t7,
}


def main(argv: list) -> int:
    if len(argv) != 2 or argv[1] not in CHECKS:
        print(f"usage: sprint_6_gate.py {{{'|'.join(CHECKS)}}}", file=sys.stderr)
        return 2
    name = argv[1]
    try:
        summary = CHECKS[name](load_plan())
    except GateFailure as exc:
        print(f"Sprint 6 {name.upper()} FAILED: {exc}", file=sys.stderr)
        return 1
    except GateError as exc:
        print(f"Sprint 6 {name.upper()} could not run: {exc}", file=sys.stderr)
        return 2
    print(f"Sprint 6 {name.upper()} OK: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
