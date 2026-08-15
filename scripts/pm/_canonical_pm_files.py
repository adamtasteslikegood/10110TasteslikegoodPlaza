"""Single source of truth for which planning docs sync to Confluence.

Adapted from the cookbook's _canonical_pm_files.py for the plaza-game project.
This repo uses sprint charters (specs/sprint-*-charter.md) instead of the
cookbook's SPRINT_*_PLAN.md files, and its planning docs live under specs/.

Resolution happens at CALL time against a root, never at import time — a new
charter created mid-session must be picked up without a restart.

STDLIB ONLY — the SessionStart hook imports this module directly and must keep
working with the system python3, outside any venv.
"""

from fnmatch import fnmatch
from pathlib import Path

CURATED_PM_FILES = [
    "specs/roadmap.md",
    "specs/task-tracker.md",
]

SPRINT_GLOBS = ["specs/sprint-*-charter.md"]

BRIEFING_SUMMARY_FILES = [
    "specs/roadmap.md",
    "specs/task-tracker.md",
]

_CURATED_BASENAMES = frozenset(Path(p).name for p in CURATED_PM_FILES)
_SPRINT_BASENAME_GLOBS = frozenset(Path(p).name for p in SPRINT_GLOBS)


def could_be_canonical(name: str) -> bool:
    return name in _CURATED_BASENAMES or any(
        fnmatch(name, pattern) for pattern in _SPRINT_BASENAME_GLOBS
    )


CANONICAL_PAGE_TITLES = {
    "roadmap.md": "Project Roadmap",
    "task-tracker.md": "Task Tracker",
}


def _charter_sort_key(relative_path: str) -> tuple:
    stem = Path(relative_path).name
    middle = stem.replace("sprint-", "").replace("-charter.md", "")
    return (0, int(middle), "") if middle.isdigit() else (1, 0, stem)


def canonical_pm_files(root=".") -> list:
    root_path = Path(root)
    ordered = []
    seen = set()

    def _add(relative_path: str) -> None:
        if relative_path not in seen and (root_path / relative_path).is_file():
            seen.add(relative_path)
            ordered.append(relative_path)

    for relative_path in CURATED_PM_FILES:
        _add(relative_path)

    globbed = []
    for pattern in SPRINT_GLOBS:
        for match in root_path.glob(pattern):
            if match.is_file():
                globbed.append(match.relative_to(root_path).as_posix())
    for relative_path in sorted(set(globbed), key=_charter_sort_key):
        _add(relative_path)

    return [Path(relative_path) for relative_path in ordered]


def page_title_for(filepath) -> str:
    name = Path(filepath).name
    return CANONICAL_PAGE_TITLES.get(
        name,
        name.replace(".md", "").replace("-", " ").title(),
    )
