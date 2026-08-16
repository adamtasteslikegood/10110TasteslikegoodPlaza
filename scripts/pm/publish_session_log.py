#!/usr/bin/env python3
"""Publish a session log page to Confluence from a markdown file.

Adapted from the cookbook's publish_session_log.py. Uses raw urllib instead of
the cookbook's AtlassianClient so this repo doesn't need to carry the full
atlassian_pm_link.py module. Reads credentials from environment or .env.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from base64 import b64encode
from datetime import datetime, timezone
from pathlib import Path

from _confluence_format import markdown_to_storage


def _load_env(root: str = ".") -> dict[str, str]:
    env_file = Path(root) / ".env"
    vals: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    return {**vals, **os.environ}


def _request(method: str, url: str, auth: str, payload=None) -> dict:
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace") if exc.fp else ""
        raise RuntimeError(f"HTTP {exc.code}: {body[:500]}") from exc


def default_title(markdown_path: Path) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    stem = markdown_path.stem.replace("_", " ").replace("-", " ").strip()
    return (
        f"Session Log - {timestamp} - {stem}" if stem else f"Session Log - {timestamp}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish a markdown session log to Confluence."
    )
    parser.add_argument("--file", required=True, help="Markdown file to publish")
    parser.add_argument("--title", help="Confluence page title override")
    parser.add_argument("--parent-id", help="Parent page ID override")
    parser.add_argument("--root", default=".", help="Project root for .env lookup")
    args = parser.parse_args()

    markdown_path = Path(args.file).resolve()
    if not markdown_path.exists():
        raise SystemExit(f"Markdown file not found: {markdown_path}")

    env = _load_env(args.root)

    site = env.get("ATLASSIAN_URL", "")
    email = env.get("ATLASSIAN_EMAIL", "")
    token = env.get("ATLASSIAN_API_TOKEN", "")
    if not all([site, email, token]):
        missing = [
            k
            for k in ("ATLASSIAN_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN")
            if not env.get(k)
        ]
        raise SystemExit(f"Missing Atlassian credentials: {', '.join(missing)}")

    from _atlassian_guard import validate_atlassian_site

    validate_atlassian_site(site)

    auth = b64encode(f"{email}:{token}".encode()).decode()
    base = f"https://{site}"

    parent_id = (
        args.parent_id
        or env.get("ATLASSIAN_CONFLUENCE_SESSION_LOG_PARENT_PAGE_ID")
        or env.get("ATLASSIAN_CONFLUENCE_PARENT_PAGE_ID")
    )

    if not parent_id:
        raise SystemExit(
            "No parent page configured. Set ATLASSIAN_CONFLUENCE_SESSION_LOG_PARENT_PAGE_ID "
            "or ATLASSIAN_CONFLUENCE_PARENT_PAGE_ID in .env or environment."
        )

    parent = _request("GET", f"{base}/wiki/api/v2/pages/{parent_id}", auth)
    space_id = parent.get("spaceId")
    if not space_id:
        raise SystemExit(f"Could not resolve space from parent page {parent_id}")

    title = args.title or default_title(markdown_path)
    body = markdown_to_storage(markdown_path.read_text(encoding="utf-8"))

    payload = {
        "spaceId": space_id,
        "status": "current",
        "title": title,
        "body": {"representation": "storage", "value": body},
    }
    if parent_id:
        payload["parentId"] = parent_id

    created = _request("POST", f"{base}/wiki/api/v2/pages", auth, payload)
    page_id = str(created.get("id", "<unknown>"))
    print(f"Created Confluence session log page {page_id}: {title}")

    try:
        _request(
            "POST",
            f"{base}/wiki/rest/api/content/{page_id}/label",
            auth,
            [{"prefix": "global", "name": "agent-session-log"}],
        )
        print("Label: agent-session-log")
    except Exception as exc:
        print(f"Warning: agent-session-log label not applied: {exc}")


if __name__ == "__main__":
    main()
