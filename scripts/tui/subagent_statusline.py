#!/usr/bin/env python3
"""Subagent statusline renderer for Claude Code.

Receives all visible subagent rows as a JSON object with a tasks array.
Outputs one JSON line per task: {"id": "...", "content": "..."}.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_session  # noqa: E402

MODEL_SHORT = {
    "claude-opus-4-6": "O4.6",
    "claude-opus-4-8": "O4.8",
    "claude-opus-5": "O5",
    "claude-sonnet-5": "S5",
    "claude-sonnet-4-5": "S4.5",
    "claude-haiku-4-5": "H4.5",
    "claude-fable-5": "F5",
}


def shorten_model(model_id):
    if not model_id:
        return "?"
    if model_id in MODEL_SHORT:
        return MODEL_SHORT[model_id]
    for prefix, short in MODEL_SHORT.items():
        if model_id.startswith(prefix):
            return short
    parts = model_id.replace("claude-", "").split("-")
    return parts[0][0].upper() + ".".join(parts[1:]) if len(parts) > 1 else model_id


def build_mini_bar(token_count, context_size, width=5):
    if not context_size or not token_count:
        return f"{cc_session.DIM}{'░' * width}{cc_session.RESET}", "--"

    pct = int(token_count * 100 / context_size)
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


def status_segment(status):
    emoji_map = {
        "completed": "✅",
        "running": "🔄",
    }
    color_map = {
        "completed": cc_session.GREEN,
        "running": cc_session.YELLOW,
    }
    emoji = emoji_map.get(status, "⏳")
    color = color_map.get(status, cc_session.DIM)
    return f"{emoji} {color}{status or 'queued'}{cc_session.RESET}"


def render_task(task):
    name = task.get("label") or task.get("name") or "agent"
    model_id = task.get("model", "")
    model_short = shorten_model(model_id)
    token_count = task.get("tokenCount")
    context_size = task.get("contextWindowSize")
    effort = task.get("effort")
    status = task.get("status")

    bar, pct_label = build_mini_bar(token_count, context_size)

    parts = [f"🤖 {name} [{model_short}] {bar} {pct_label}"]

    if effort:
        effort_labels = {"xhigh": "🔥 xhigh", "high": "🔥 high", "medium": "⚙️ med"}
        parts.append(str(effort_labels.get(effort, str(effort))))

    parts.append(status_segment(status))

    return " | ".join(parts)


def main():
    data = json.load(sys.stdin)
    tasks = data.get("tasks", [])

    for task in tasks:
        task_id = task.get("id")
        if not task_id:
            continue
        content = render_task(task)
        print(json.dumps({"id": task_id, "content": content}))


if __name__ == "__main__":
    main()
