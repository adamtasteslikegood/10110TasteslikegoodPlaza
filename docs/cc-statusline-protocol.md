---
doc_id: CC-STATUSLINE-PROTOCOL
title: Claude Code Statusline Protocol Reference
tier: 4
authority: research
status: ACTIVE
doc_set_version: 0.2.13
last_updated: 2026-08
owner: adamtasteslikegood
derives_from: []
enforcement: n/a
gates: []
---

> **Authority: none.** Tier 4 `research`, off the D-027 enforcement scale.
> This documents Anthropic's shipped Claude Code statusline feature; it
> asserts nothing about this repository's code or state, and is
> authoritative over nothing. See `doc-registry.json` for the reason.

# Claude Code Statusline Protocol Reference

This document describes the JSON protocol Claude Code uses to communicate
session state to statusline scripts. It is the reference for the scripts
in `scripts/tui/` and the contract the bridge layer (Layer 3) will adopt.

**Source:** `https://code.claude.com/docs/en/statusline`

**Full schema:** `scripts/tui/statusline-schema.json`

## Protocol Summary

Claude Code runs a configured shell command, pipes a JSON object to its
stdin, and displays whatever the script prints to stdout. The script runs
on session start and on every assistant message, `/compact`, permission
mode change, vim mode toggle, and `refreshInterval` timer tick. Debounced
at 300ms.

## Field Inventory with Bridge Relevance

| Field | Type | Always Present | Bridge Relevance |
|---|---|---|---|
| `session_id` | string | Yes | Session routing — cache keys, bridge session IDs |
| `model.id` | string | Yes | Model tier for bridge routing |
| `model.display_name` | string | Yes | HUD display |
| `workspace.current_dir` | string | Yes | Workspace identity |
| `workspace.project_dir` | string | Yes | Launch directory |
| `workspace.repo.*` | object | No (git+origin) | Repository identity |
| `workspace.git_worktree` | string | No (worktrees) | Multi-session awareness |
| `cost.total_cost_usd` | number | Yes (default 0) | Token/cost tracking in game HUD |
| `cost.total_duration_ms` | number | Yes (default 0) | Session timer |
| `cost.total_lines_added` | number | Yes (default 0) | Activity gauge |
| `context_window.used_percentage` | number | Nullable | Context gauge in game HUD |
| `context_window.context_window_size` | number | Yes | Max capacity |
| `rate_limits.five_hour.*` | object | No (Pro/Max) | Subscription-aware HUD |
| `rate_limits.seven_day.*` | object | No (Pro/Max) | Subscription-aware HUD |
| `effort.level` | string | No (model-dep) | Effort display |
| `pr.number`, `pr.url` | number, string | No (when PR) | Dev workflow |
| `pr.review_state` | string | No | PR review indicator |
| `worktree.*` | object | No (--worktree) | Multi-session awareness |
| `agent.name` | string | No (--agent) | Agent identity in game |

## Null/Absent Categories

CC's fields fall into three categories the bridge must handle identically:

1. **Always present** — `model`, `workspace.current_dir`, `session_id`, `cost.*`
   (values default to 0), `context_window.*` (structure present, values nullable)
2. **Absent when not applicable** — `pr`, `worktree`, `rate_limits`, `agent`,
   `vim`, `effort`. Key is missing from JSON entirely.
3. **Null before first response** — `context_window.used_percentage`,
   `context_window.current_usage`. Key exists but value is `null`.

## Subagent Statusline Protocol

The `subagentStatusLine` setting receives a different JSON shape: an object
with a `tasks` array. Each task has `id`, `name`, `label`, `type`, `status`,
`description`, `model`, `effort`, `contextWindowSize`, `tokenCount`, `cwd`,
`startTime`, and `tokenSamples`.

The script outputs one JSON line per row to stdout:
`{"id": "<task_id>", "content": "<ANSI formatted row text>"}`.

Omitting a task ID keeps the default rendering for that row.

*Last updated: August 2026*
