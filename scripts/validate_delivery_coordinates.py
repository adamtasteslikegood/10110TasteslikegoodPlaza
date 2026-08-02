#!/usr/bin/env python3
"""Sprint 2 definition of done: nothing live routes to Jira ``TO``, and PLZG
can actually report flow.

``specs/sprint-2-charter.md`` section 1 defines done as two clauses, and this
script is the proving artifact for both. It exits 0 only when both hold.

**(a)** No executable script and no ``ACTIVE`` governed document references
project ``TO``. ``CHANGELOG.md`` and any ``status: SUPERSEDED`` document are
exempt -- they are history, and history is allowed to mention a deprecated
board.

**(b)** A committed PLZG snapshot is FRESH and HONEST: its ``as_of`` falls
inside the sprint window it declares, that sprint has not ended, and its
``work_item_age`` names exactly as many items as ``counts.wip`` claims.

Clause (b) is the one that matters. Without it a rename-only sundown passes
green while flow stays unmeasurable, because clause (a) is satisfied by a
rename.

**Clause (b) no longer requires ``wip > 0``.** Owner ruling 2026-08-02, on
``PLZG-130``. It did, and that was the defect: a single-contributor board at
rest genuinely has zero WIP, so the rule did not test health, it tested
SNAPSHOT TIMING -- it demanded the snapshot be captured during a window that
only exists while someone is mid-task. Sprint 2 satisfied it with a ticket open
for six minutes whose subject was this very gate (``sprint-2-charter.md``
section 1.2). A gate that requires someone to be mid-task is a gate that rewards
a fake transition.

What replaces it keeps the anti-fabrication property without the incentive:
``wip`` may be any integer including 0, but ``work_item_age`` must AGREE with it.
A snapshot claiming three items in progress while naming none is not evidence,
and that mismatch is now the failure -- not the honest zero.

Stdlib only, no ``pip install`` step, following the ``validate_specs.py`` idiom
so this can join CI as a sibling job.

Exit codes: 0 pass, 1 one or more clauses failed, 2 the check could not be run.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SNAPSHOT_PATH = REPO_ROOT / "data" / "plzg-flow-snapshot.json"

# Trees whose .md files are governed documents (mirrors validate_specs.py).
GOVERNED_TREES = ("docs", "specs", "Docs")
GOVERNED_ROOT_FILES = ("README.md",)

# Executable scripts that could route a request at runtime. A doc naming TO is
# a stale claim; a *script* naming TO is an outage.
SCRIPT_GLOBS = ("*.py", "scripts/*.py", "scripts/*.sh")

# Files entitled to name the deprecated board, and why. Mentioning ``TO`` in
# order to say "do not use it" is the opposite of a violation, so a blanket
# text search would flag precisely the documents doing the right thing.
ENTITLED = {
    # History is allowed to mention a deprecated board.
    "CHANGELOG.md": "history",
    # D-026 designates this as the single origin of every Atlassian identifier,
    # including the record of what TO is and why nothing may be filed there.
    "docs/delivery-coordinates.md": "the D-026 coordinates authority",
    # Charters the sundown; it cannot describe the work without naming it.
    "specs/sprint-2-charter.md": "charters the TO sundown",
    # This checker's own patterns and docstring.
    "scripts/validate_delivery_coordinates.py": "the checker itself",
}
EXEMPT_STATUSES = {"SUPERSEDED", "HISTORICAL"}

# A git branch name is an immutable ref, not a board reference. This branch
# predates the migration and cannot be renamed without orphaning its history,
# so naming it is a statement about git, not about Jira.
BRANCH_REF = re.compile(r"feature/TO-\d+[\w.-]*")

# `TO` as a Jira project key: TO-123, project = "TO", 'TO' in backticks.
# Deliberately narrow -- the bare English word "to" must never match, and
# neither may TODO, TOOLS, or a word boundary inside another identifier.
TO_PATTERNS = (
    re.compile(r"\bTO-\d+\b"),
    re.compile(r"project\s*=\s*[\"']TO[\"']"),
    re.compile(r"`TO`"),
)


class Failure:
    def __init__(self, clause: str, where: str, detail: str) -> None:
        self.clause = clause
        self.where = where
        self.detail = detail

    def __str__(self) -> str:
        return f"  [{self.clause}] {self.where}: {self.detail}"


def frontmatter_status(text: str) -> str | None:
    """Return the ``status:`` value from YAML frontmatter, if any.

    Intentionally simple: this only needs one scalar, and validate_specs.py
    already owns real frontmatter validation. A file without frontmatter
    returns None and is treated as non-exempt -- failing closed, because an
    unparseable document is not evidence that it is history.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        if line.strip().startswith("status:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return None


def matches_to(line: str) -> str | None:
    """Return the offending ``TO`` reference on this line, if any.

    Git branch refs are stripped first: ``feature/TO-1-prototype-initialization``
    is a ref that cannot be renamed without orphaning history.
    """
    line = BRANCH_REF.sub("", line)
    for pattern in TO_PATTERNS:
        found = pattern.search(line)
        if found:
            return found.group(0)
    return None


def candidate_files() -> list[Path]:
    """Every governed document and executable script worth checking, deduped."""
    candidates: list[Path] = []
    for tree in GOVERNED_TREES:
        tree_path = REPO_ROOT / tree
        if tree_path.is_dir():
            candidates.extend(sorted(tree_path.rglob("*.md")))
    for name in GOVERNED_ROOT_FILES:
        candidates.append(REPO_ROOT / name)
    for glob in SCRIPT_GLOBS:
        candidates.extend(sorted(REPO_ROOT.glob(glob)))

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        if path.relative_to(REPO_ROOT).as_posix() not in ENTITLED:
            unique.append(path)
    return unique


def check_clause_a() -> list[Failure]:
    """No live script and no ACTIVE governed doc references project TO."""
    failures: list[Failure] = []

    for path in candidate_files():
        rel = path.relative_to(REPO_ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(Failure("a", str(rel), f"unreadable: {exc}"))
            continue

        if path.suffix == ".md" and frontmatter_status(text) in EXEMPT_STATUSES:
            continue

        for number, line in enumerate(text.splitlines(), start=1):
            hit = matches_to(line)
            if hit:
                failures.append(
                    Failure(
                        "a",
                        f"{rel}:{number}",
                        f"references deprecated Jira project TO ({hit!r})",
                    )
                )

    return failures


def parse_instant(value: str) -> "datetime | None":
    """Parse an ISO-8601 timestamp, or a bare date as midnight UTC.

    INSTANTS, NOT STRING PREFIXES (PLZG-144). Every sprint boundary on this
    board is 17:00 PT, which the Agile API returns as 00:00 UTC the NEXT day,
    so comparing ``as_of[:10]`` against ``sprint.end[:10]`` shifts every
    boundary by a day and reports a disagreement that does not exist. That
    already happened once, in a charter, and survived a check against Jira --
    querying the owning system is necessary and not sufficient if the value is
    then read in the wrong units.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def check_clause_b() -> list[Failure]:
    """The committed PLZG snapshot is fresh, and honest about what it reports."""
    rel = SNAPSHOT_PATH.relative_to(REPO_ROOT)

    if not SNAPSHOT_PATH.is_file():
        return [Failure("b", str(rel), "committed PLZG snapshot is missing")]

    try:
        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Failure("b", str(rel), f"unreadable or invalid JSON: {exc}")]

    failures: list[Failure] = []

    # FRESHNESS. This is the substance of PLZG-130: `as_of` was read only to be
    # printed, so the gate would have passed in 2027 still reporting a July 2026
    # board. Both halves are needed. "Inside its own window" catches a snapshot
    # whose timestamp and sprint disagree; "that sprint has ended" is what makes
    # the check expire, and without it a snapshot stays valid forever as long as
    # it is internally consistent.
    as_of = parse_instant(snapshot.get("as_of", ""))
    sprint = snapshot.get("sprint") or {}
    start = parse_instant(sprint.get("start", ""))
    end = parse_instant(sprint.get("end", ""))

    if as_of is None:
        failures.append(Failure("b", str(rel), "as_of is missing or not a timestamp"))
    elif start is None or end is None:
        failures.append(
            Failure(
                "b",
                str(rel),
                "sprint.start/sprint.end are missing or not dates, so the snapshot "
                "cannot be dated against a sprint window",
            )
        )
    else:
        # The window is inclusive of its end DAY: a sprint ending 2026-08-14
        # runs through that day, and a bare date parses as its midnight.
        window_end = end + timedelta(days=1)
        if not (start <= as_of < window_end):
            failures.append(
                Failure(
                    "b",
                    str(rel),
                    f"as_of {snapshot.get('as_of')} falls outside the sprint window it "
                    f"declares ({sprint.get('name')}: {sprint.get('start')} to "
                    f"{sprint.get('end')}) -- refresh the snapshot",
                )
            )
        elif datetime.now(timezone.utc) >= window_end:
            failures.append(
                Failure(
                    "b",
                    str(rel),
                    f"{sprint.get('name')} ended {sprint.get('end')}; this snapshot "
                    "describes a finished sprint and cannot report current flow -- "
                    "refresh it",
                )
            )

    # HONESTY. wip may be ANY integer, including 0 -- see the module docstring.
    # What must hold is that the two agree: a snapshot claiming N in progress
    # has to name N of them.
    wip = snapshot.get("counts", {}).get("wip")
    age = snapshot.get("work_item_age")

    if not isinstance(wip, int):
        failures.append(
            Failure("b", str(rel), "counts.wip is missing or not an integer")
        )
    if not isinstance(age, list):
        failures.append(
            Failure("b", str(rel), "work_item_age is missing or not a list")
        )
    if isinstance(wip, int) and isinstance(age, list) and len(age) != wip:
        failures.append(
            Failure(
                "b",
                str(rel),
                f"counts.wip is {wip} but work_item_age names {len(age)} item(s); a "
                "snapshot that claims work in progress must name it",
            )
        )

    return failures


def main() -> int:
    if not REPO_ROOT.joinpath(".git").exists():
        print(
            "validate_delivery_coordinates: not a repository checkout", file=sys.stderr
        )
        return 2

    failures = check_clause_a() + check_clause_b()

    if failures:
        print("Delivery-coordinate validation FAILED:\n", file=sys.stderr)
        for failure in failures:
            print(failure, file=sys.stderr)
        print(
            "\nClause (a): no live script or ACTIVE governed doc may reference Jira TO."
            "\nClause (b): the committed PLZG snapshot must be fresh -- as_of inside"
            "\n            the sprint window it declares, and that sprint not yet ended --"
            "\n            and honest, with work_item_age naming exactly counts.wip items."
            "\n            wip may be 0 (owner ruling 2026-08-02, PLZG-130).",
            file=sys.stderr,
        )
        return 1

    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    counts = snapshot.get("counts", {})
    print(
        "Delivery coordinates OK: no live TO reference outside history; "
        f"PLZG reports wip={counts.get('wip')} with "
        f"{len(snapshot.get('work_item_age', []))} item(s) aged "
        f"(snapshot as of {snapshot.get('as_of')})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
