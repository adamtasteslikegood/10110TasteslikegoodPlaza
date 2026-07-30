#!/usr/bin/env python3
"""Sprint 2 definition of done: nothing live routes to Jira ``TO``, and PLZG
can actually report flow.

``specs/sprint-2-charter.md`` section 1 defines done as two clauses, and this
script is the proving artifact for both. It exits 0 only when both hold.

**(a)** No executable script and no ``ACTIVE`` governed document references
project ``TO``. ``CHANGELOG.md`` and any ``status: SUPERSEDED`` document are
exempt -- they are history, and history is allowed to mention a deprecated
board.

**(b)** A committed PLZG snapshot yields ``wip > 0`` and a non-empty
``work_item_age``.

Clause (b) is the one that matters. Without it a rename-only sundown passes
green while flow remains unmeasurable -- the board reports ``wip = 0`` and an
empty age list, and nobody notices because clause (a) is satisfied by a rename.

Stdlib only, no ``pip install`` step, following the ``validate_specs.py`` idiom
so this can join CI as a sibling job.

Exit codes: 0 pass, 1 one or more clauses failed, 2 the check could not be run.
"""

from __future__ import annotations

import json
import re
import sys
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


def check_clause_b() -> list[Failure]:
    """The committed PLZG snapshot reports wip > 0 and a non-empty age list."""
    rel = SNAPSHOT_PATH.relative_to(REPO_ROOT)

    if not SNAPSHOT_PATH.is_file():
        return [Failure("b", str(rel), "committed PLZG snapshot is missing")]

    try:
        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Failure("b", str(rel), f"unreadable or invalid JSON: {exc}")]

    failures: list[Failure] = []

    wip = snapshot.get("counts", {}).get("wip")
    if not isinstance(wip, int):
        failures.append(
            Failure("b", str(rel), "counts.wip is missing or not an integer")
        )
    elif wip <= 0:
        failures.append(
            Failure(
                "b",
                str(rel),
                f"counts.wip is {wip}; flow is unmeasurable while nothing is In Progress",
            )
        )

    age = snapshot.get("work_item_age")
    if not isinstance(age, list):
        failures.append(
            Failure("b", str(rel), "work_item_age is missing or not a list")
        )
    elif not age:
        # This also covers "wip > 0 but no items named", which is the case that
        # matters: a snapshot claiming WIP without naming the items is not
        # evidence. An earlier revision guarded that separately and only ever
        # produced a duplicate message, since this branch fires first.
        failures.append(
            Failure(
                "b",
                str(rel),
                "work_item_age is empty; the board cannot report item age",
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
            "\nClause (b): the committed PLZG snapshot must report wip > 0 and a"
            "\n            non-empty work_item_age. See specs/sprint-2-charter.md section 1.",
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
