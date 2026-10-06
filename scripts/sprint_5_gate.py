#!/usr/bin/env python3
"""Acceptance checks for Sprint 5, one subcommand per loop-plan task.

``specs/sprint-5-loop-plan.json`` names these as each task's ``acceptance.cmd``.
They were shell one-liners embedded in the JSON until review found that none of
them could be trusted:

* every Jira search read ONE page. ``/rest/api/3/search/jql`` returns 50 issues
  by default and the To Do column holds about a hundred, so "every To Do key is
  covered" was checked against half the column;
* T2 compared the triage evidence with the CURRENT To Do set, so an item closed
  without review simply left the query and the check passed -- the bulk-close
  the charter's R2 exists to prevent;
* T3 counted governed documents without asking which ones had left;
* T4's manifest was self-attesting: an omitted ``contradiction`` read as false
  and ``reviewed_commit`` was never compared with anything;
* T5 claimed a Jira sprint existed and checked only that two files did.

Each check below asks the system that owns the fact. Board state comes from
Jira, document content from git, the governed count from ``validate_specs.py``.

Identifiers are NOT held here. The sprint, the board and every ticket key are
read from the loop plan, which records what ``docs/delivery-coordinates.md``
(``D-026``) owns. Credentials come from ``./.env``, then the environment:
``ATLASSIAN_EMAIL`` plus ``ATLASSIAN_API_TOKEN``, or a pre-encoded base64 value.

Stdlib only. Exit codes: 0 pass, 1 the check failed, 2 it could not be run.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = REPO_ROOT / "specs" / "sprint-5-loop-plan.json"
REGISTRY_PATH = REPO_ROOT / "specs" / "meta" / "doc-registry.json"
TRIAGE_PATH = REPO_ROOT / "specs" / "evidence" / "sprint-5-triage.json"
CROSSCHECK_PATH = REPO_ROOT / "specs" / "evidence" / "sprint-5-doc-crosscheck.json"
CONFLICT_REGISTER_PATH = REPO_ROOT / "specs" / "meta" / "spec-drivers-v0.2.5.md"
SECTION_CITATION = re.compile(r"§\s?(\d+\.\d+)\b")
OPEN_CONFLICT_HEADING = re.compile(r"^### (\d+\.\d+) .*\*\*OPEN\*\*\s*$", re.M)

TOKEN_VARS = ("ATLASSIAN_API_TOKEN_BASE64", "ATLASSIAN_API_TOKEN_BASE64_USEREMAIL")
BUCKETS = ("done", "keep", "wont_do")
# The PLZG workflow has no Won't Do status, so a declined item is Done plus this
# label. Without the label a Won't Do is indistinguishable from finished work.
WONT_DO_LABEL = "wont-do"
# Systems a cross-check row may name as the owner it verified a claim against.
# `none` is for a document that makes no claim about state at all.
OWNING_SYSTEMS = ("git", "jira", "github", "ci", "none")


class GateFailure(Exception):
    """The check ran and the answer is no."""


class GateError(Exception):
    """The check could not be run."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def load_json(path: Path) -> dict:
    rel = path.relative_to(REPO_ROOT)
    if not path.is_file():
        raise GateFailure(f"{rel} does not exist")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateFailure(f"{rel} is not valid JSON: {exc}") from exc
    require(isinstance(data, dict), f"{rel} must be a JSON object")
    return data


def load_plan() -> dict:
    return load_json(PLAN_PATH)


def task(plan: dict, task_id: str) -> dict:
    for entry in plan.get("tasks", []):
        if entry.get("id") == task_id:
            return entry
    raise GateError(f"{PLAN_PATH.name} has no task {task_id}")


# --------------------------------------------------------------------------
# Jira
# --------------------------------------------------------------------------


def read_dotenv() -> dict:
    env = {}
    dotenv = REPO_ROOT / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def resolve_credential() -> "tuple[str | None, str | None]":
    """``(site, credential)`` from ./.env, else from the environment.

    ./.env WINS, and the two are NEVER MIXED. direnv exports .env into the shell
    and keeps exporting a value after it is deleted from the file, so the shell
    can hold a revoked token the file no longer names. Filling gaps field by
    field would let a stale shell email-and-token pair outrank a fresh base64
    value in the file. So the credential comes whole from whichever source is
    the first to hold a complete one; the environment is the fallback for a
    runner with no .env at all.
    """
    shell = {k: v for k, v in os.environ.items() if k.startswith("ATLASSIAN_")}
    file_env = read_dotenv()
    credential = basic_credential(file_env) or basic_credential(shell)
    site = file_env.get("ATLASSIAN_URL") or shell.get("ATLASSIAN_URL")
    return site, credential


def basic_credential(env: dict) -> str | None:
    """The Basic credential: email plus API token, else a pre-encoded value.

    Email plus token comes first because it is what Atlassian issues; the
    base64 variables are a derived copy, and a derived copy is the one left
    stale when the token is rotated.
    """
    email, api_token = env.get("ATLASSIAN_EMAIL"), env.get("ATLASSIAN_API_TOKEN")
    if email and api_token:
        return base64.b64encode(f"{email}:{api_token}".encode()).decode()
    return next((env[v] for v in TOKEN_VARS if env.get(v)), None)


_authenticated = False


def jira_get(endpoint: str, params: dict | None = None) -> dict:
    # Jira answers an unauthenticated SEARCH with 200 and an empty list, not a
    # 401. A revoked token therefore reads as "no issue matches", and every
    # check here would report a false finding instead of a failure to run.
    # Proving the credential once, against an endpoint that does refuse
    # anonymous callers, is what keeps "nothing found" meaning nothing found.
    global _authenticated
    if not _authenticated and endpoint != "/rest/api/3/myself":
        jira_get("/rest/api/3/myself")
        _authenticated = True
    site, token = resolve_credential()
    if not site or not token:
        raise GateError(
            "ATLASSIAN_URL plus either ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN, or "
            "one of " + " / ".join(TOKEN_VARS) + ", must be set in ./.env or the "
            "environment"
        )
    url = f"https://{site}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"Authorization": f"Basic {token}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise GateError(f"Jira answered {exc.code} for {endpoint}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GateError(f"Jira request to {endpoint} failed: {exc}") from exc


def jira_search(jql: str) -> dict:
    """Every issue matching ``jql``, keyed by issue key. Follows every page."""
    found: dict = {}
    token = None
    while True:
        params = {"jql": jql, "fields": "status,labels", "maxResults": 100}
        if token:
            params["nextPageToken"] = token
        page = jira_get("/rest/api/3/search/jql", params)
        issues = page.get("issues")
        if not isinstance(issues, list):
            raise GateError("Jira search response carried no issues list")
        for issue in issues:
            fields = issue.get("fields") or {}
            status = fields.get("status") or {}
            found[issue.get("key")] = {
                "status": status.get("name"),
                "category": (status.get("statusCategory") or {}).get("key"),
                "labels": fields.get("labels") or [],
            }
        token = page.get("nextPageToken")
        if not token:
            return found


def issues_by_key(keys: list) -> dict:
    if not keys:
        return {}
    found: dict = {}
    # Chunked so the JQL stays well inside the URL length Jira accepts.
    for start in range(0, len(keys), 50):
        chunk = ",".join(keys[start : start + 50])
        found.update(jira_search(f"key in ({chunk})"))
    return found


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def check_t1(plan: dict) -> str:
    """Every stale In Progress item named by the plan is Done in Jira."""
    inputs = task(plan, "T1").get("acceptance_inputs", {})
    done_keys = inputs.get("done", [])
    wont_do_keys = inputs.get("wont_do", [])
    expected = done_keys + wont_do_keys
    require(bool(expected), "T1 names no keys to check")

    live = issues_by_key(expected)
    not_done = sorted(k for k in expected if live.get(k, {}).get("category") != "done")
    require(not not_done, f"not Done in Jira: {not_done}")
    mislabeled = sorted(k for k in done_keys if WONT_DO_LABEL in live[k]["labels"])
    require(
        not mislabeled,
        f"listed as done but labelled {WONT_DO_LABEL}: {mislabeled}",
    )
    unlabeled = sorted(
        k for k in wont_do_keys if WONT_DO_LABEL not in live[k]["labels"]
    )
    require(
        not unlabeled,
        f"closed as Won't Do without the {WONT_DO_LABEL} label: {unlabeled}",
    )
    return f"{len(expected)} key(s) Done, {len(wont_do_keys)} of them labelled Won't Do"


def check_t2(plan: dict, require_complete: bool = False) -> str:
    """The triage evidence covers the pre-triage column and matches the board."""
    project = plan.get("jira", {}).get("project")
    require(bool(project), "the loop plan declares no jira.project")
    triage = load_json(TRIAGE_PATH)

    baseline = triage.get("baseline_keys")
    require(
        isinstance(baseline, list) and bool(baseline),
        "triage evidence must record baseline_keys, the non-Done set captured "
        "before any item was moved",
    )
    require(bool(triage.get("baseline_captured_at")), "baseline_captured_at is missing")

    rows = triage.get("items")
    require(isinstance(rows, list), "triage evidence has no items list")
    keys = [row.get("key") for row in rows]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    require(not duplicates, f"keys bucketed more than once: {duplicates}")
    for row in rows:
        require(
            row.get("bucket") in BUCKETS,
            f"{row.get('key')}: bucket must be one of {list(BUCKETS)}",
        )
        require(bool(row.get("reviewed_at")), f"{row.get('key')}: reviewed_at missing")
        require(bool(row.get("reason")), f"{row.get('key')}: reason missing")

    # Coverage is measured against the BASELINE. An item closed without review
    # leaves the To Do column, so the live column alone cannot show it was
    # skipped. Anything filed after the baseline is picked up by the live read.
    missing = sorted(set(baseline) - set(keys))
    require(not missing, f"baseline keys with no triage row: {missing}")
    # Every open item, not only To Do: Gate A is about all non-Done work, and an
    # In Progress ticket nobody triaged is exactly what T1 found seven of. The
    # sprint's own tickets are exempt -- they are the work, and T6's is open
    # while T6 runs. "Own" means a task ticket the PLAN names that Jira confirms
    # is in the sprint: sprint membership alone would let any backlog item skip
    # triage by being dragged into the sprint after the baseline.
    sprint_id = plan.get("jira", {}).get("sprint_id")
    require(isinstance(sprint_id, int), "the loop plan declares no jira.sprint_id")
    planned = {t["jira"] for t in plan.get("tasks", []) if t.get("jira")}
    own = planned & set(jira_search(f"sprint = {sprint_id}"))
    live_open = jira_search(f"project = {project} AND statusCategory != Done")
    unreviewed = sorted(set(live_open) - set(keys) - own)
    require(not unreviewed, f"open keys with no triage row: {unreviewed}")

    # The bucket has to be what actually happened on the board.
    live = issues_by_key(keys)
    for row in rows:
        key, bucket = row["key"], row["bucket"]
        state = live.get(key)
        require(state is not None, f"{key}: not found in Jira")
        closed = state["category"] == "done"
        if bucket == "keep":
            require(not closed, f"{key}: bucketed keep but is {state['status']}")
        else:
            require(closed, f"{key}: bucketed {bucket} but is {state['status']}")
        labelled = WONT_DO_LABEL in state["labels"]
        if bucket == "wont_do":
            require(
                labelled, f"{key}: bucketed wont_do without the {WONT_DO_LABEL} label"
            )
        elif bucket == "done":
            require(
                not labelled,
                f"{key}: bucketed done but carries the {WONT_DO_LABEL} label -- "
                "declined work is not completed work",
            )
    if require_complete:
        require(
            triage.get("review_complete") is True,
            "triage review_complete must be true",
        )
    return f"{len(rows)} triage row(s) cover {len(baseline)} baseline key(s)"


def governed_count() -> int:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_specs.py")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    output = f"{result.stdout}{result.stderr}".strip()
    require(result.returncode == 0, f"validate_specs.py failed:\n{output}")
    match = re.search(r"Spec validation passed: (\d+) governed", output)
    require(match is not None, f"could not read a governed count from:\n{output}")
    return int(match.group(1))


def check_t3(plan: dict) -> str:
    """The validator passes on no more than the planned number of documents."""
    limit = plan.get("governed_doc_limit")
    require(isinstance(limit, int), "the loop plan declares no governed_doc_limit")
    count = governed_count()
    require(count <= limit, f"{count} governed documents, limit is {limit}")

    # A count cannot tell WHICH documents left. Removing a decision's origin or
    # a derives_from target reaches the same number as removing a tier-4
    # summary, so the plan names every document that must stay and this checks
    # each is still governed. That is risk R1, enforced rather than advised.
    inputs = task(plan, "T3").get("acceptance_inputs", {})
    keep = inputs.get("must_stay_governed")
    require(
        isinstance(keep, list) and bool(keep),
        "T3 declares no must_stay_governed list",
    )
    registry = load_json(REGISTRY_PATH)
    governed = {d["doc_id"] for d in registry.get("documents", [])}
    removed = sorted(set(keep) - governed)
    require(not removed, f"documents that must stay governed were removed: {removed}")

    # Staying governed is half of what T3 asks of the retired charters; the
    # other half is that they stop claiming to be current. validate_specs.py
    # already holds the registry and the frontmatter to the same status, so
    # reading the registry is enough.
    retire = inputs.get("must_be_historical", [])
    status = {d["doc_id"]: d.get("status") for d in registry.get("documents", [])}
    still_active = sorted(d for d in retire if status.get(d) != "HISTORICAL")
    require(not still_active, f"documents not yet marked HISTORICAL: {still_active}")
    return (
        f"{count} governed document(s), limit {limit}; all {len(keep)} protected, "
        f"{len(retire)} retired"
    )


def open_conflict_sections() -> set:
    """Section numbers the open-conflict register currently holds OPEN."""
    if not CONFLICT_REGISTER_PATH.is_file():
        return set()
    text = CONFLICT_REGISTER_PATH.read_text(encoding="utf-8")
    return set(OPEN_CONFLICT_HEADING.findall(text))


def check_t4(plan: dict) -> str:
    """Every governed document was cross-checked at its current content."""
    registry = load_json(REGISTRY_PATH)
    manifest = load_json(CROSSCHECK_PATH)
    paths = {d["doc_id"]: d["path"] for d in registry.get("documents", [])}
    rows = manifest.get("reviewed_docs")
    require(isinstance(rows, list), "cross-check evidence has no reviewed_docs list")
    # A dict keeps the LAST row for a doc_id, so a recorded contradiction
    # followed by a clean row for the same document would vanish.
    ids = [row.get("doc_id") for row in rows]
    duplicates = sorted({i for i in ids if ids.count(i) > 1}, key=str)
    require(not duplicates, f"documents cross-checked more than once: {duplicates}")
    by_id = {row.get("doc_id"): row for row in rows}

    missing = sorted(set(paths) - set(by_id))
    require(not missing, f"governed documents with no cross-check row: {missing}")

    open_sections = open_conflict_sections()
    carried = set()
    for doc_id, path in sorted(paths.items()):
        row = by_id[doc_id]
        # Explicit, because an omitted key reads as "no contradiction".
        require(
            row.get("contradiction") is False,
            f"{doc_id}: contradiction must be recorded as false, got "
            f"{row.get('contradiction')!r}",
        )
        sources = row.get("verified_against")
        require(
            isinstance(sources, list)
            and bool(sources)
            and all(s in OWNING_SYSTEMS for s in sources),
            f"{doc_id}: verified_against must name one or more of "
            f"{list(OWNING_SYSTEMS)}",
        )
        # A disagreement the document labels as disputed is not hidden, but it is
        # not settled either. It may ride on a clean row only while the register
        # holds it OPEN; otherwise "recorded" is just a word in a note.
        conflicts = row.get("open_conflicts", [])
        require(
            isinstance(conflicts, list) and all(isinstance(c, str) for c in conflicts),
            f"{doc_id}: open_conflicts must be a list of register section numbers",
        )
        stale = sorted(set(conflicts) - open_sections)
        require(
            not stale,
            f"{doc_id}: open_conflicts names {stale}, not OPEN in the conflict register",
        )
        # The declaration is not trusted on its own: deleting it would silence the
        # gate while the document went on saying "open conflict §4.12". Whatever
        # OPEN section the document cites, its row must list. The register is
        # exempt -- it is where the sections live.
        doc_path = REPO_ROOT / path
        if doc_path.is_file() and doc_path != CONFLICT_REGISTER_PATH:
            cited = set(SECTION_CITATION.findall(doc_path.read_text(encoding="utf-8")))
            undeclared = sorted((cited & open_sections) - set(conflicts))
            require(
                not undeclared,
                f"{doc_id}: cites open conflict(s) {undeclared} that its row "
                "does not list in open_conflicts",
            )
        carried.update(conflicts)
        # A row is evidence about one version of the file. If the file changed
        # since, the row describes something that no longer exists.
        blob = subprocess.run(
            ["git", "hash-object", path], capture_output=True, text=True, cwd=REPO_ROOT
        )
        require(blob.returncode == 0, f"{doc_id}: cannot hash {path}")
        require(
            row.get("reviewed_blob") == blob.stdout.strip(),
            f"{doc_id}: {path} changed since it was reviewed -- re-check it",
        )
    summary = f"{len(paths)} governed document(s) cross-checked at current content"
    if carried:
        summary += f"; open conflict(s) still carried: {sorted(carried)}"
    return summary


def check_t5(plan: dict) -> str:
    """The charter and plan validate, and the Jira sprint really exists."""
    governed_count()
    for name in ("sprint-5-charter.md", "sprint-5-loop-plan.json"):
        require((REPO_ROOT / "specs" / name).is_file(), f"specs/{name} is missing")

    jira = plan.get("jira", {})
    sprint_id, board_id = jira.get("sprint_id"), jira.get("board_id")
    require(
        isinstance(sprint_id, int) and isinstance(board_id, int),
        "the loop plan must declare jira.sprint_id and jira.board_id",
    )
    sprint = jira_get(f"/rest/agile/1.0/sprint/{sprint_id}")
    require(
        sprint.get("originBoardId") == board_id,
        f"sprint {sprint_id} belongs to board {sprint.get('originBoardId')}, "
        f"not {board_id}",
    )
    expected = sorted(t["jira"] for t in plan.get("tasks", []) if t.get("jira"))
    in_sprint = jira_search(f"sprint = {sprint_id}")
    absent = sorted(set(expected) - set(in_sprint))
    require(not absent, f"task tickets not in sprint {sprint_id}: {absent}")
    return (
        f"sprint {sprint_id} ({sprint.get('name')}, {sprint.get('state')}) on board "
        f"{board_id} holds all {len(expected)} task ticket(s)"
    )


def check_snapshot() -> str:
    """The committed flow snapshot is fresh, by the gate that owns that rule."""
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "validate_delivery_coordinates.py"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    output = f"{result.stdout}{result.stderr}".strip()
    require(
        result.returncode == 0, f"validate_delivery_coordinates.py failed:\n{output}"
    )
    return "flow snapshot fresh"


def check_t6(plan: dict) -> str:
    """Sprint close: both gates, re-read from their owners."""
    parts = [
        check_t1(plan),
        check_t2(plan, require_complete=True),
        check_t3(plan),
        check_t4(plan),
        check_snapshot(),
    ]
    return "; ".join(parts)


CHECKS = {
    "t1": check_t1,
    "t2": check_t2,
    "t3": check_t3,
    "t4": check_t4,
    "t5": check_t5,
    "t6": check_t6,
}


def main(argv: list) -> int:
    if len(argv) != 2 or argv[1] not in CHECKS:
        print(f"usage: sprint_5_gate.py {{{'|'.join(CHECKS)}}}", file=sys.stderr)
        return 2
    name = argv[1]
    try:
        summary = CHECKS[name](load_plan())
    except GateFailure as exc:
        print(f"Sprint 5 {name.upper()} FAILED: {exc}", file=sys.stderr)
        return 1
    except GateError as exc:
        print(f"Sprint 5 {name.upper()} could not run: {exc}", file=sys.stderr)
        return 2
    print(f"Sprint 5 {name.upper()} OK: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
