#!/usr/bin/env python3
"""Condense a Claude Code transcript (JSONL) into a compact digest for summarization.

A full transcript is far too large to hand to a model verbatim — it is dominated
by tool results (file contents, command output, search dumps). This strips the
transcript down to the signal a session summary actually needs:

  * what the human asked for (verbatim — this is the highest-value signal)
  * what the assistant said it did (prose only; tool calls are reduced to names)
  * which files were touched (from Edit/Write/NotebookEdit tool inputs)
  * which commands ran (from Bash tool inputs, first line only)

Tool RESULTS are dropped entirely. They are the bulk of the bytes and almost
never carry decisions.

Standard-library only, so it stays runnable from a hook with no venv and no
project dependencies installed (same constraint as _atlassian_guard.py).

Usage:
    python3 transcript_digest.py --transcript <path.jsonl> [--max-chars 40000]
    python3 transcript_digest.py --transcript <path.jsonl> --json   # structured
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Tool inputs worth recording, and the field that names the thing acted upon.
_FILE_TOOLS = {
    "Edit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
}
_TRUNCATE_ASSISTANT = 1500  # chars of assistant prose kept per turn
_TRUNCATE_USER = 4000  # chars of a user turn kept (asks are worth more)

# The transcript records a LOT of things as role="user" that the human never said.
# Left in, they masquerade as the ask: an injected SKILL.md body (thousands of
# chars) or a <bash-stdout> dump reads to the summarizer as "what Adam wanted".
# Observed in the wild — a digest whose HUMAN turns were mostly a skill file.

# Wrappers whose CONTENT is pure noise: drop the whole turn.
_NOISE_TAGS = (
    "system-reminder",
    "local-command-caveat",
    "local-command-stdout",
    "local-command-stderr",
    "bash-stdout",
    "bash-stderr",
)
_NOISE_BLOCK_RE = re.compile(
    r"<(" + "|".join(_NOISE_TAGS) + r")>.*?</\1>", re.DOTALL | re.IGNORECASE
)
# An unterminated wrapper (truncated transcript line) still shouldn't leak.
_NOISE_OPEN_RE = re.compile(
    r"<(" + "|".join(_NOISE_TAGS) + r")>.*", re.DOTALL | re.IGNORECASE
)

# A skill body injected into the conversation. Not the human talking.
_SKILL_INJECTION_RE = re.compile(r"^\s*Base directory for this skill:", re.IGNORECASE)

# These ARE real user actions, worth one compact line each.
_SLASH_CMD_RE = re.compile(
    r"<command-name>\s*/?([^<\s]+)\s*</command-name>", re.IGNORECASE
)
_SLASH_ARGS_RE = re.compile(
    r"<command-args>(.*?)</command-args>", re.DOTALL | re.IGNORECASE
)
_BASH_INPUT_RE = re.compile(
    r"<bash-input>(.*?)</bash-input>", re.DOTALL | re.IGNORECASE
)
# Anything else in angle-tag form we didn't name explicitly.
_ANY_TAG_RE = re.compile(r"</?[a-z][a-z0-9-]*>", re.IGNORECASE)


def clean_user_text(text: str) -> str:
    """Reduce a role=user turn to what the HUMAN actually contributed.

    Returns "" when the turn was entirely harness-injected, so the caller can
    drop it rather than count it as an ask.
    """
    if not text or _SKILL_INJECTION_RE.match(text):
        return ""

    # Real user actions first — these survive as one line each.
    actions: list[str] = []
    cmd = _SLASH_CMD_RE.search(text)
    if cmd:
        args = _SLASH_ARGS_RE.search(text)
        arg_text = args.group(1).strip() if args else ""
        actions.append(f"/{cmd.group(1)}{' ' + arg_text if arg_text else ''}")
    for match in _BASH_INPUT_RE.finditer(text):
        line = match.group(1).strip()
        if line:
            actions.append(f"$ {line}")

    # Then strip every noise wrapper and see if any prose is left.
    stripped = _NOISE_BLOCK_RE.sub("", text)
    stripped = _NOISE_OPEN_RE.sub("", stripped)
    stripped = _SLASH_CMD_RE.sub("", stripped)
    stripped = _SLASH_ARGS_RE.sub("", stripped)
    stripped = _BASH_INPUT_RE.sub("", stripped)
    stripped = re.sub(
        r"<command-message>.*?</command-message>", "", stripped, flags=re.DOTALL | re.I
    )
    stripped = _ANY_TAG_RE.sub("", stripped).strip()

    parts = actions + ([stripped] if stripped else [])
    return "\n".join(parts).strip()


def _text_from_content(content: Any) -> str:
    """Pull the plain-text blocks out of a message's content field.

    Content is either a bare string or a list of typed blocks. We keep only
    `text` blocks; `tool_use` / `tool_result` / `thinking` blocks are handled
    separately or dropped.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    return "\n".join(p for p in parts if p.strip())


def _tool_uses(content: Any) -> list[dict]:
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]


def _is_tool_result_turn(content: Any) -> bool:
    """A 'user' turn that is really just a tool result being fed back."""
    if not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def digest(transcript_path: Path, max_chars: int) -> dict:
    turns: list[str] = []
    files_touched: list[str] = []
    commands: list[str] = []
    tools_used: dict[str, int] = {}
    user_asks: list[str] = []

    with transcript_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = entry.get("type")
            message = entry.get("message") or {}
            content = message.get("content")

            if role == "user":
                # Skip tool-result echoes; keep only genuine human turns.
                if _is_tool_result_turn(content):
                    continue
                # Strip harness-injected content (skill bodies, command output,
                # reminders). What's left, if anything, is the human.
                text = clean_user_text(_text_from_content(content).strip())
                if not text:
                    continue
                text = text[:_TRUNCATE_USER]
                user_asks.append(text)
                turns.append(f"### HUMAN\n{text}")

            elif role == "assistant":
                prose = _text_from_content(content).strip()
                for tu in _tool_uses(content):
                    name = tu.get("name") or "?"
                    tools_used[name] = tools_used.get(name, 0) + 1
                    tin = tu.get("input") or {}
                    if not isinstance(tin, dict):
                        continue
                    if name in _FILE_TOOLS:
                        path = tin.get(_FILE_TOOLS[name])
                        if path and path not in files_touched:
                            files_touched.append(path)
                    elif name == "Bash":
                        cmd = (tin.get("command") or "").strip().splitlines()
                        if cmd:
                            first = cmd[0][:120]
                            if first not in commands:
                                commands.append(first)
                if prose:
                    turns.append(f"### ASSISTANT\n{prose[:_TRUNCATE_ASSISTANT]}")

    # Keep the head (original ask, framing) and the tail (what actually landed).
    # The middle of a long session is mostly exploration that the head and tail
    # already imply, so it is the first thing to sacrifice.
    body = "\n\n".join(turns)
    if len(body) > max_chars:
        head = body[: max_chars // 3]
        tail = body[-(2 * max_chars // 3) :]
        body = f"{head}\n\n[... middle of session elided for length ...]\n\n{tail}"

    return {
        "turns": body,
        "files_touched": files_touched,
        "commands": commands[:40],
        "tools_used": tools_used,
        "user_asks": user_asks,
        "turn_count": len(turns),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--max-chars", type=int, default=40000)
    ap.add_argument("--json", action="store_true", help="emit structured JSON")
    args = ap.parse_args()

    path = Path(args.transcript)
    if not path.exists():
        print(f"Transcript not found: {path}", file=sys.stderr)
        raise SystemExit(1)

    result = digest(path, args.max_chars)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    out = [result["turns"], "", "---", ""]
    if result["files_touched"]:
        out.append("FILES TOUCHED:")
        out += [f"  - {f}" for f in result["files_touched"]]
        out.append("")
    if result["commands"]:
        out.append("COMMANDS RUN (first line each):")
        out += [f"  - {c}" for c in result["commands"]]
        out.append("")
    if result["tools_used"]:
        summary = ", ".join(f"{k}×{v}" for k, v in sorted(result["tools_used"].items()))
        out.append(f"TOOLS USED: {summary}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
