#!/usr/bin/env python3
"""Verify Jira issue references in a set of markdown files.

Scans each file for KAN-<n> issue keys, hits the Jira REST API to confirm
each one exists, and prints a per-file report. Plaza-related issues
(KAN-34 and KAN-39..KAN-51) are excluded from verification by default —
they belong to the TLG Plaza game scope, not the cookbook.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILES = [
    "docs/agile/SCRUM_BOOTSTRAP_AND_BOARD_PLAN.md",
    "docs/agile/SPRINT_0_PLAN.md",
    "docs/ATLASSIAN_PM_LINK.md",
]
PLAZA_KEYS = {f"KAN-{n}" for n in [34, *range(39, 52)]}
ISSUE_RE = re.compile(r"\bKAN-(\d+)\b")


def load_env(env_path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def jira_get(base_url: str, headers: dict[str, str], key: str) -> tuple[int, dict | None]:
    url = f"{base_url}/rest/api/3/issue/{key}?fields=summary,status,issuetype"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except urllib.error.URLError as e:
        print(f"  network error verifying {key}: {e}", file=sys.stderr)
        return 0, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Markdown files to scan (defaults to scrum-master's new files)")
    parser.add_argument("--include-plaza", action="store_true", help="Also verify Plaza issues (KAN-34, KAN-39..KAN-51)")
    args = parser.parse_args()

    env_file = REPO_ROOT / ".env"
    env = {**os.environ, **load_env(env_file)}
    url = env.get("ATLASSIAN_URL", "").strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    email = env.get("ATLASSIAN_EMAIL", "").strip()
    token = env.get("ATLASSIAN_API_TOKEN", "").strip()
    if not (url and email and token):
        print("Missing ATLASSIAN_URL / ATLASSIAN_EMAIL / ATLASSIAN_API_TOKEN in .env", file=sys.stderr)
        return 2
    base_url = f"https://{url}"
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json", "User-Agent": "tlg-link-check/1.0"}

    files = [REPO_ROOT / f for f in (args.files or DEFAULT_FILES)]

    seen: dict[str, list[str]] = {}
    for f in files:
        if not f.exists():
            print(f"WARN: missing file {f}", file=sys.stderr)
            continue
        for m in ISSUE_RE.finditer(f.read_text()):
            key = f"KAN-{m.group(1)}"
            seen.setdefault(key, [])
            rel = str(f.relative_to(REPO_ROOT))
            if rel not in seen[key]:
                seen[key].append(rel)

    if not seen:
        print("No KAN-* references found.")
        return 0

    in_scope = sorted(seen.keys(), key=lambda k: int(k.split("-", 1)[1]))
    skipped = []
    if not args.include_plaza:
        skipped = [k for k in in_scope if k in PLAZA_KEYS]
        in_scope = [k for k in in_scope if k not in PLAZA_KEYS]

    print(f"\nScanned {len([f for f in files if f.exists()])} file(s); {len(seen)} unique KAN refs found.")
    if skipped:
        print(f"Skipped {len(skipped)} Plaza ref(s): {', '.join(skipped)}")
    print(f"Verifying {len(in_scope)} cookbook ref(s) against {base_url} ...\n")

    ok, broken, other = [], [], []
    details: dict[str, dict] = {}
    for key in in_scope:
        status, body = jira_get(base_url, headers, key)
        if status == 200 and body:
            ok.append(key)
            details[key] = {
                "summary": body.get("fields", {}).get("summary", ""),
                "status": body.get("fields", {}).get("status", {}).get("name", ""),
                "type": body.get("fields", {}).get("issuetype", {}).get("name", ""),
            }
        elif status == 404:
            broken.append(key)
        else:
            other.append((key, status))

    width = max((len(k) for k in in_scope), default=8)
    for key in ok:
        d = details[key]
        srcs = ", ".join(seen[key])
        print(f"  OK     {key:<{width}}  [{d['type']:<5} {d['status']:<11}] {d['summary'][:60]}  <- {srcs}")
    for key in broken:
        srcs = ", ".join(seen[key])
        print(f"  404    {key:<{width}}  (not found)  <- {srcs}")
    for key, code in other:
        srcs = ", ".join(seen[key])
        print(f"  HTTP{code:<3} {key:<{width}}  (verification error)  <- {srcs}")

    print(f"\nSummary: {len(ok)} ok, {len(broken)} missing, {len(other)} errors, {len(skipped)} plaza-skipped")
    return 0 if not broken and not other else 1


if __name__ == "__main__":
    sys.exit(main())
