"""Shared Jira project-key resolution for the PM scripts.

Single source of truth so all PM scripts agree on which Jira projects to query.
Standard-library only.
"""

from __future__ import annotations

from typing import Callable, Optional

from _atlassian_guard import validate_jira_project_keys

DEFAULT_JIRA_PROJECTS = ["PLZG"]


def resolve_jira_projects(get: Callable[[str], Optional[str]]) -> list[str]:
    """Resolve the ordered, de-duplicated list of Jira project keys.

    ``get`` is a lookup callable such as ``os.environ.get``.
    Precedence: explicit ``JIRA_PROJECTS`` / ``ATLASSIAN_JIRA_PROJECTS`` (CSV)
    wins; else ``ATLASSIAN_JIRA_PROJECT_KEY``; else the repo default (PLZG).

    Every resolved key is validated against the read-only allowlist.
    """
    explicit = get("JIRA_PROJECTS") or get("ATLASSIAN_JIRA_PROJECTS")
    if explicit:
        parts = [part.strip() for part in explicit.split(",") if part.strip()]
    else:
        primary = get("ATLASSIAN_JIRA_PROJECT_KEY")
        if primary:
            parts = [primary]
        else:
            parts = list(DEFAULT_JIRA_PROJECTS)
    ordered: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part and part not in seen:
            ordered.append(part)
            seen.add(part)
    return validate_jira_project_keys(ordered or DEFAULT_JIRA_PROJECTS, read_only=True)
