"""Defense-in-depth allowlist for the PM scripts' Atlassian targets.

This repo's PM tooling may only touch the plaza-game Jira project (PLZG) on
tasteslikegood.atlassian.net. The deprecated TO project and the cookbook's
KAN/RCP projects are read-only for cross-project rollups. The -dev service
site (tasteslikegood-dev.atlassian.net) and its frozen TOSVC project are
never valid.

Call these validators wherever a site URL or Jira project key is about to be
used (config load, request construction). They raise AtlassianGuardError with
a loud, descriptive message — they never silently correct.

Standard-library only, so it stays importable before project dependencies are
installed.
"""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urlsplit

ALLOWED_ATLASSIAN_SITE = "tasteslikegood.atlassian.net"

ALLOWED_JIRA_PROJECT_KEYS = ("PLZG",)

READ_ONLY_JIRA_PROJECT_KEYS = ("PLZG", "TO", "KAN", "RCP")

_SERVICE_SITE = "tasteslikegood-dev.atlassian.net"


class AtlassianGuardError(RuntimeError):
    """Raised when PM tooling is pointed at a disallowed Atlassian site or project."""


def _extract_host(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "://" in value:
        host = urlsplit(value).hostname or ""
    else:
        host = urlsplit(f"//{value}").hostname or ""
    return host.lower().rstrip(".")


def validate_atlassian_site(url_or_host: str) -> str:
    host = _extract_host(url_or_host)
    if host == ALLOWED_ATLASSIAN_SITE:
        return host

    if host == _SERVICE_SITE or host.endswith("." + _SERVICE_SITE):
        raise AtlassianGuardError(
            f"BLOCKED: Atlassian site {host!r} (from {url_or_host!r}) is the service-site "
            f"shell, NOT this repo's work-item site.\n"
            f"This repo's PM tooling may ONLY talk to: {ALLOWED_ATLASSIAN_SITE}\n"
            f"Fix ATLASSIAN_URL in .env."
        )

    raise AtlassianGuardError(
        f"BLOCKED: Atlassian site {host or url_or_host!r} is not on this repo's allowlist.\n"
        f"This repo's PM tooling may ONLY talk to: {ALLOWED_ATLASSIAN_SITE}\n"
        f"Fix ATLASSIAN_URL in .env."
    )


def validate_jira_project_key(key: str, *, read_only: bool = False) -> str:
    normalized = (key or "").strip().upper()
    allowed = READ_ONLY_JIRA_PROJECT_KEYS if read_only else ALLOWED_JIRA_PROJECT_KEYS
    if normalized in allowed:
        return normalized

    if read_only:
        raise AtlassianGuardError(
            f"BLOCKED: Jira project key {key!r} is not on this repo's read-only "
            f"allowlist {list(READ_ONLY_JIRA_PROJECT_KEYS)}.\n"
            f"Rollups/briefings may read PLZG (plaza game), TO (deprecated), "
            f"KAN and RCP (cookbook) on {ALLOWED_ATLASSIAN_SITE}."
        )

    raise AtlassianGuardError(
        f"BLOCKED: Jira project key {key!r} is not on this repo's write allowlist "
        f"{list(ALLOWED_JIRA_PROJECT_KEYS)}.\n"
        f"This repo's tooling may only file/update items in PLZG (plaza game) "
        f"on {ALLOWED_ATLASSIAN_SITE}.\n"
        f"TO is deprecated (read-only until archival). KAN and RCP belong to "
        f"the cookbook repo and are readable only via read_only=True rollup paths."
    )


def validate_jira_project_keys(
    keys: Iterable[str], *, read_only: bool = False
) -> list[str]:
    return [validate_jira_project_key(key, read_only=read_only) for key in keys]
