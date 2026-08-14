#!/usr/bin/env python3
"""Two-line Claude Code statusline for 10110 TastesLike Plaza.

Line 1: 🏢 [Model] 🔗 repo-link | 🌿 branch +2~3  🔀 wt:name  🔶 PR #N state
Line 2: 🧠 ██████░░░░ 42% | 💰 $1.23 | ⚡5h ██░░░░ 24% | 📅7d ●●░░░░░ 41% | ⏱ 12m 34s
"""

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_session  # noqa: E402


def build_context_bar(pct, width=10):
    if pct is None or pct == 0:
        bar = "░" * width
        return f"{cc_session.DIM}{bar}{cc_session.RESET}", "--"

    pct = int(pct)
    if pct >= 90:
        color = cc_session.RED
    elif pct >= 70:
        color = cc_session.YELLOW
    else:
        color = cc_session.GREEN

    filled = pct * width // 100
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return f"{color}{bar}{cc_session.RESET}", f"{pct}%"


def rate_limit_5h(pct):
    if pct is None:
        return ""
    pct = int(pct)
    width = 6
    filled = pct * width // 100
    empty = width - filled
    if pct >= 80:
        color = cc_session.RED
    elif pct >= 60:
        color = cc_session.YELLOW
    else:
        color = cc_session.GREEN
    bar = "█" * filled + "░" * empty
    return f"⚡5h {color}{bar}{cc_session.RESET} {pct}%"


def rate_limit_7d(pct):
    if pct is None:
        return ""
    pct = int(pct)
    total = 7
    filled = pct * total // 100
    empty = total - filled
    if pct >= 80:
        color = cc_session.RED
    elif pct >= 60:
        color = cc_session.YELLOW
    else:
        color = cc_session.GREEN
    dots = f"{color}{'●' * filled}{'○' * empty}{cc_session.RESET}"
    return f"📅7d {dots} {pct}%"


def repo_link():
    try:
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        remote = re.sub(r"^git@github\.com:", "https://github.com/", remote)
        remote = re.sub(r"\.git$", "", remote)
        name = os.path.basename(remote)
        return f"\033]8;;{remote}\a{name}\033]8;;\a"
    except Exception:
        return None


def git_dirty(git_info):
    parts = []
    staged = git_info.get("staged_count", 0)
    modified = git_info.get("modified_count", 0)
    if staged:
        parts.append(f"{cc_session.GREEN}+{staged}{cc_session.RESET}")
    if modified:
        parts.append(f"{cc_session.YELLOW}~{modified}{cc_session.RESET}")
    return "".join(parts)


def pr_segment(pr_info):
    if pr_info is None:
        return ""
    num = pr_info.get("number", "")
    state = pr_info.get("review_state", "pending")
    color_map = {
        "approved": cc_session.GREEN,
        "changes_requested": cc_session.RED,
    }
    color = color_map.get(state, cc_session.YELLOW)
    state_label = state.replace("_", " ") if state else "pending"
    emoji = {"approved": "✅", "changes_requested": "🔴"}.get(state, "🔶")
    return f"  {emoji} {color}PR #{num} {state_label}{cc_session.RESET}"


def main():
    data = cc_session.parse_session()

    _, model_name = cc_session.get_model(data)
    ws = cc_session.get_workspace(data)
    ctx = cc_session.get_context(data)
    cost = cc_session.get_cost(data)
    rl = cc_session.get_rate_limits(data)
    git = cc_session.get_git_status(data)
    pr = cc_session.get_pr(data)
    wt = cc_session.get_worktree(data)

    # Line 1: identity and git state
    link = repo_link()
    if link:
        project_label = f"🔗 {link}"
    else:
        project = os.path.basename(ws["current_dir"]) if ws["current_dir"] else "?"
        project_label = f"📁 {project}"
    parts = [f"🏢 {cc_session.CYAN}[{model_name}]{cc_session.RESET} {project_label}"]

    if git["branch"]:
        dirty = git_dirty(git)
        dirty_suffix = f" {dirty}" if dirty else ""
        parts.append(f"| 🌿 {git['branch']}{dirty_suffix}")

    if wt:
        parts.append(f"{cc_session.YELLOW}🔀 wt:{wt['name']}{cc_session.RESET}")

    pr_text = pr_segment(pr)
    if pr_text:
        parts.append(pr_text.strip())

    print(" ".join(parts))

    # Line 2: resource gauges
    bar, pct_label = build_context_bar(ctx["used_pct"])
    cost_str = f"💰 {cc_session.YELLOW}${cost['cost_usd']:.2f}{cc_session.RESET}"
    duration = cc_session.format_duration(cost["duration_ms"])

    gauge_parts = [f"🧠 {bar} {pct_label}", cost_str]

    if rl:
        five_str = rate_limit_5h(rl["five_hour_pct"])
        seven_str = rate_limit_7d(rl["seven_day_pct"])
        if five_str:
            gauge_parts.append(five_str)
        if seven_str:
            gauge_parts.append(seven_str)

    gauge_parts.append(f"⏱ {duration}")

    print(" | ".join(gauge_parts))


if __name__ == "__main__":
    main()
