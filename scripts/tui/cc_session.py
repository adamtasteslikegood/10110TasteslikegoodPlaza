#!/usr/bin/env python3
"""Shared parser for Claude Code's statusline stdin JSON.

Claude Code pipes a JSON object to statusline scripts via stdin on every
update (assistant message, /compact, permission change, timer tick).
This module reads that JSON and provides null-safe accessors for each
field group. See scripts/tui/statusline-schema.json for the full schema.
"""

import json
import os
import subprocess
import sys
import time

CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def parse_session():
    return json.load(sys.stdin)


def get_model(data):
    model = data.get("model", {})
    return model.get("id", "unknown"), model.get("display_name", "Unknown")


def get_context(data):
    cw = data.get("context_window", {})
    return {
        "used_pct": cw.get("used_percentage") or 0,
        "remaining_pct": cw.get("remaining_percentage") or 0,
        "total_input": cw.get("total_input_tokens") or 0,
        "total_output": cw.get("total_output_tokens") or 0,
        "window_size": cw.get("context_window_size") or 200000,
    }


def get_cost(data):
    cost = data.get("cost", {})
    return {
        "cost_usd": cost.get("total_cost_usd") or 0,
        "duration_ms": cost.get("total_duration_ms") or 0,
        "api_duration_ms": cost.get("total_api_duration_ms") or 0,
        "lines_added": cost.get("total_lines_added") or 0,
        "lines_removed": cost.get("total_lines_removed") or 0,
    }


def get_rate_limits(data):
    rl = data.get("rate_limits")
    if rl is None:
        return None
    five = rl.get("five_hour", {})
    seven = rl.get("seven_day", {})
    return {
        "five_hour_pct": five.get("used_percentage"),
        "seven_day_pct": seven.get("used_percentage"),
    }


def get_workspace(data):
    ws = data.get("workspace", {})
    repo = ws.get("repo") or {}
    return {
        "current_dir": ws.get("current_dir") or data.get("cwd", ""),
        "project_dir": ws.get("project_dir", ""),
        "repo_owner": repo.get("owner"),
        "repo_name": repo.get("name"),
        "git_worktree": ws.get("git_worktree"),
    }


_GIT_CACHE_MAX_AGE = 5


def get_git_status(data):
    raw_id = str(data.get("session_id", "unknown"))
    safe_id = "".join(ch for ch in raw_id if ch.isalnum() or ch in ("-", "_"))
    cache_file = f"/tmp/statusline-git-cache-{safe_id or 'unknown'}"

    stale = True
    if os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        stale = age > _GIT_CACHE_MAX_AGE

    if stale:
        try:
            subprocess.check_output(
                ["git", "rev-parse", "--git-dir"], stderr=subprocess.DEVNULL
            )
            branch = subprocess.check_output(
                ["git", "branch", "--show-current"], text=True
            ).strip()
            staged_out = subprocess.check_output(
                ["git", "diff", "--cached", "--numstat"], text=True
            ).strip()
            modified_out = subprocess.check_output(
                ["git", "diff", "--numstat"], text=True
            ).strip()
            staged_count = len(staged_out.split("\n")) if staged_out else 0
            modified_count = len(modified_out.split("\n")) if modified_out else 0
            with open(cache_file, "w") as f:
                f.write(f"{branch}|{staged_count}|{modified_count}")
        except Exception:
            with open(cache_file, "w") as f:
                f.write("|0|0")

    try:
        with open(cache_file) as f:
            parts = f.read().strip().split("|")
        return {
            "branch": parts[0] if parts[0] else "",
            "staged_count": int(parts[1]) if len(parts) > 1 and parts[1] else 0,
            "modified_count": int(parts[2]) if len(parts) > 2 and parts[2] else 0,
        }
    except Exception:
        return {"branch": "", "staged_count": 0, "modified_count": 0}


def get_pr(data):
    pr = data.get("pr")
    if pr is None:
        return None
    return {
        "number": pr.get("number"),
        "url": pr.get("url"),
        "review_state": pr.get("review_state"),
    }


def get_worktree(data):
    wt = data.get("worktree")
    if wt is None:
        return None
    return {
        "name": wt.get("name"),
        "path": wt.get("path"),
        "branch": wt.get("branch"),
        "original_cwd": wt.get("original_cwd"),
        "original_branch": wt.get("original_branch"),
    }


def format_duration(ms):
    total_sec = int(ms) // 1000
    mins = total_sec // 60
    secs = total_sec % 60
    return f"{mins}m {secs}s"
