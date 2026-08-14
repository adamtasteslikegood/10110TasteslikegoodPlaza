#!/usr/bin/env python3
"""Two-line Claude Code statusline for 10110 TastesLike Plaza.

Line 1: [Model] project-folder | branch  wt:name  PR #N state
Line 2: ██████░░░░ 42% | $1.23 | 5h: 24% 7d: 41% | 12m 34s
"""

import os
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
    return f"  {color}PR #{num} {state_label}{cc_session.RESET}"


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
    project = os.path.basename(ws["current_dir"]) if ws["current_dir"] else "?"
    parts = [f"{cc_session.CYAN}[{model_name}]{cc_session.RESET} {project}"]

    if git["branch"]:
        parts.append(f"| {git['branch']}")

    if wt:
        parts.append(f"{cc_session.YELLOW}wt:{wt['name']}{cc_session.RESET}")

    pr_text = pr_segment(pr)
    if pr_text:
        parts.append(pr_text.strip())

    print(" ".join(parts))

    # Line 2: resource gauges
    bar, pct_label = build_context_bar(ctx["used_pct"])
    cost_str = f"{cc_session.YELLOW}${cost['cost_usd']:.2f}{cc_session.RESET}"
    duration = cc_session.format_duration(cost["duration_ms"])

    gauge_parts = [f"{bar} {pct_label}", cost_str]

    if rl:
        rl_parts = []
        if rl["five_hour_pct"] is not None:
            rl_parts.append(f"5h: {rl['five_hour_pct']:.0f}%")
        if rl["seven_day_pct"] is not None:
            rl_parts.append(f"7d: {rl['seven_day_pct']:.0f}%")
        if rl_parts:
            gauge_parts.append(" ".join(rl_parts))

    gauge_parts.append(duration)

    print(" | ".join(gauge_parts))


if __name__ == "__main__":
    main()
