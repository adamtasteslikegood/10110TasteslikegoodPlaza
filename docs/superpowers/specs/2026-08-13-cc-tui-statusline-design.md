# Claude Code TUI Statusline — Design Spec

> **One line:** Customize Claude Code's statusline and subagent statusline for this
> project using a shared Python parser module that doubles as a bridge-layer prototype.

**Source:** Anthropic's official statusline docs —
`https://code.claude.com/docs/en/statusline`

**Drives:** Developer experience for anyone working in this repo; bridge readiness
by prototyping the CC session data parser the bridge will need (Layer 3, M5–M8).

**Builds on:** D-005 (bridge has zero UI awareness — the statusline lives entirely
in Layer 2), D-006 (sync with timeout — the statusline demonstrates the same
"parse JSON, handle nulls, render" pattern the bridge uses).

**Approach chosen:** B (shared parser module + thin scripts). Chosen over A (single
file) because subagent statusline is in scope this pass, so two scripts already share
the parser. Chosen over C (configuration-driven segments) because B migrates to C
naturally when scope demands it — and the delta is ~60-80 lines of structure, not a
rewrite.

---

## §1 What Claude Code's Statusline Is

The statusline is a customizable bar at the bottom of the Claude Code TUI. It runs
any shell script you configure, pipes JSON session data to it via stdin, and displays
whatever the script prints to stdout.

**When it updates:** Once at session start, then on each assistant message, `/compact`,
permission mode change, vim mode toggle, and optionally on a `refreshInterval` timer.
Debounced at 300ms. If a new update fires while the script is running, the in-flight
run is cancelled.

**What it can output:** Plain text, ANSI color codes, OSC 8 clickable links, multiple
lines (each `print()` is a separate row).

**Subagent statusline:** A separate `subagentStatusLine` setting that receives all
visible subagent rows as a JSON object with a `tasks` array. Outputs one JSON line
per row: `{"id": "<task_id>", "content": "<formatted_text>"}`.

**Cost:** Zero API tokens. Runs locally. Temporarily hides during autocomplete,
help menu, and permission prompts.

---

## §2 File Layout

```
scripts/tui/
  cc_session.py              # Shared parser — CC stdin JSON → typed accessors
  statusline.py              # Main 2-line dashboard statusline
  subagent_statusline.py     # Subagent row renderer
  statusline-schema.json     # Committed copy of CC's full JSON schema

docs/
  cc-statusline-protocol.md  # Governed reference doc (tier 4, reference, ACTIVE)
                             # Embeds the schema, annotates bridge relevance per field
```

`scripts/tui/` is the home for all TUI customization scripts. Future customizations
(hooks, output styles, etc.) land here too. The directory is outside the governed
doc tree, so `validate_specs.py` does not check it.

The reference doc `docs/cc-statusline-protocol.md` lives inside the governed tree
with proper frontmatter (`doc_id`, `tier: 4`, `authority: reference`, `status: ACTIVE`),
registered in `specs/meta/doc-registry.json`.

---

## §3 The Shared Parser: `cc_session.py`

Stdlib only: `json`, `sys`, `os`, `subprocess`, `time`. No third-party dependencies.

### Interface

```python
def parse_session() -> dict:
    """Read CC's JSON from stdin. Entry point for all TUI scripts."""

def get_model(data: dict) -> tuple[str, str]:
    """(id, display_name). Always present."""

def get_context(data: dict) -> dict:
    """used_pct, remaining_pct, total_input, total_output, window_size.
    Handles null/absent with fallback to 0."""

def get_cost(data: dict) -> dict:
    """cost_usd, duration_ms, api_duration_ms, lines_added, lines_removed.
    All default to 0."""

def get_rate_limits(data: dict) -> dict | None:
    """five_hour_pct, seven_day_pct. Returns None if rate_limits absent
    (non-Pro/Max users). Each window independently nullable."""

def get_workspace(data: dict) -> dict:
    """current_dir, project_dir, repo_owner, repo_name, git_worktree.
    repo fields None outside a git repo with origin."""

def get_git_status(data: dict) -> dict:
    """branch, staged_count, modified_count. Cached for 5 seconds using
    data['session_id'] to key the cache file. Returns empty strings/zeros
    if not in a git repo."""

def get_pr(data: dict) -> dict | None:
    """number, url, review_state. None if no open PR."""

def get_worktree(data: dict) -> dict | None:
    """name, path, branch, original_cwd, original_branch. None if not
    in a --worktree session."""

def format_duration(ms: int) -> str:
    """Convert milliseconds to 'Xm Ys' string."""
```

### Design principles

- **Accessor functions, not a class.** The raw dict is always available. Accessors
  are convenience, not encapsulation. This keeps the module importable without
  ceremony and avoids premature abstraction (the B→C migration path adds dataclasses
  when warranted).
- **Null-safe by default.** Every accessor handles absent keys and null values with
  documented fallbacks. This matches CC's documented field semantics and is exactly
  the robustness the bridge parser needs.
- **Git caching.** `get_git_status()` caches to `/tmp/statusline-git-cache-{session_id}`
  with a 5-second TTL. The `session_id` ensures concurrent sessions in different repos
  don't cross-contaminate. Cache check uses `os.path.getmtime()`.

---

## §4 Main Statusline: `statusline.py`

Two-line dashboard. Each `print()` creates a separate row.

### Line 1 — Identity and git state

```
[Opus 4.6] 10110TasteslikegoodPlaza | dev  PR #198 pending
```

| Segment | Source field | Color | Absent behavior |
|---|---|---|---|
| Model name | `model.display_name` | Cyan | Never absent |
| Project folder | `workspace.current_dir` (basename) | Default | Never absent |
| Git branch | Subprocess (cached) | Default | Omitted if not in git repo |
| Worktree name | `worktree.name` | Yellow | Omitted if not in worktree |
| PR status | `pr.number`, `pr.review_state` | Green/yellow/red by state | Omitted if no open PR |

### Line 2 — Resource gauges

```
████████░░ 42% | $1.23 | 5h: 24% 7d: 41% | 12m 34s
```

| Segment | Source field | Color | Absent behavior |
|---|---|---|---|
| Context bar | `context_window.used_percentage` | Green <70%, yellow 70-89%, red 90%+ | Shows `--` pre-first-response |
| Context percentage | Same | Same color as bar | Shows `--` |
| Session cost | `cost.total_cost_usd` | Yellow | Shows `$0.00` |
| Rate limits | `rate_limits.five_hour.used_percentage`, `.seven_day.used_percentage` | Default | Entire segment omitted (Pro/Max only) |
| Duration | `cost.total_duration_ms` | Default | Shows `0m 0s` |

### ANSI color codes used

```
Cyan:   \033[36m    (model name)
Green:  \033[32m    (context bar <70%, PR approved)
Yellow: \033[33m    (context bar 70-89%, cost, PR pending, worktree)
Red:    \033[31m    (context bar 90%+, PR changes_requested)
Reset:  \033[0m
```

---

## §5 Subagent Statusline: `subagent_statusline.py`

Receives all visible subagent rows as a JSON object with a `tasks` array.
Outputs one JSON line per task.

### Row format

```
agent-name [O4.6] ██░░░ 23% | high | running
```

| Segment | Source field | Notes |
|---|---|---|
| Agent name | `task.label` or `task.name` | Label preferred (user-set), falls back to name |
| Model tier | `task.model` | Shortened: "O4.6", "S5", "H4.5", etc. |
| Context bar | `task.tokenCount / task.contextWindowSize` | 5-char mini bar. Color-coded same thresholds as main. |
| Effort level | `task.effort` | Badge: "low", "med", "high", "xhigh", "max". Omitted if absent. |
| Status | `task.status` | Color: green=completed, yellow=running, dim=queued |

### Output format

Per CC docs, one JSON line per row to stdout:

```json
{"id": "task-abc", "content": "agent-name [O4.6] ██░░░ 23% | high | running"}
```

Omitting a task ID preserves default rendering for that row.

---

## §6 Settings Configuration

Added to `.claude/settings.json` (project settings, so all repo contributors get it):

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 \"$CLAUDE_PROJECT_DIR/scripts/tui/statusline.py\"",
    "refreshInterval": 10
  },
  "subagentStatusLine": {
    "type": "command",
    "command": "python3 \"$CLAUDE_PROJECT_DIR/scripts/tui/subagent_statusline.py\""
  }
}
```

- `refreshInterval: 10` keeps elapsed time, rate limits, and git state fresh during
  idle periods (e.g., coordinator waiting on background subagents).
- `$CLAUDE_PROJECT_DIR` resolves to the repo root, making paths portable across
  clones and worktrees.

---

## §7 The JSON Schema: What CC Sends

The full schema is committed to `scripts/tui/statusline-schema.json`. Summary of
all top-level fields:

| Field | Type | Always present | Bridge relevance |
|---|---|---|---|
| `cwd` | string | Yes | Workspace identity |
| `session_id` | string | Yes | Session routing (cache keys, bridge session IDs) |
| `session_name` | string | No | Display only |
| `prompt_id` | string | No (after first input) | Correlation with OpenTelemetry |
| `transcript_path` | string | Yes | Debug/replay |
| `model.id`, `.display_name` | string | Yes | Model tier for bridge routing |
| `workspace.*` | object | Yes (sub-fields vary) | Project/repo identity |
| `version` | string | Yes | Compatibility checks |
| `cost.*` | object | Yes (values default 0) | Token/cost tracking in game HUD |
| `context_window.*` | object | Yes (values nullable) | Context gauge in game HUD |
| `exceeds_200k_tokens` | boolean | Yes | Threshold alert |
| `fast_mode` | boolean | Yes | Mode indicator |
| `effort.level` | string | No (model-dependent) | Effort display |
| `thinking.enabled` | boolean | Yes | Mode indicator |
| `rate_limits.*` | object | No (Pro/Max only) | Subscription-aware HUD |
| `vim.mode` | string | No (vim mode only) | N/A for game |
| `agent.name` | string | No (--agent only) | Agent identity in game |
| `pr.*` | object | No (when PR exists) | Dev workflow awareness |
| `worktree.*` | object | No (--worktree only) | Multi-session awareness |

Fields marked "Bridge relevance" will appear in the game's HUD via the Layer 3
bridge. The statusline scripts prove the parsing works before the bridge is built.

---

## §8 Bridge Connection

This work is explicitly a **tuning pass, not engine modding** — CC's stdio protocol
is a documented, shipped feature. What transfers to the bridge:

1. **JSON-via-stdio pattern.** CC sends structured session data as JSON on stdin.
   The bridge will send structured session data as JSON over WebSocket. Same shape,
   different transport.

2. **Null/absent field handling.** CC's schema has three categories: always-present,
   absent-when-not-applicable, and null-before-first-response. The bridge inherits
   all three patterns. `cc_session.py` documents the right fallback for each.

3. **Session identity.** `session_id` scopes caches and state. The bridge's
   domain-scoped sessions use the same pattern.

4. **Model/context/cost shape.** The game's HUD will render exactly these fields:
   which model is active, how much context is consumed, what it's costing. The
   statusline proves the rendering logic before it touches Godot.

---

## §9 Testing

Each script can be tested standalone by piping mock JSON:

```bash
cat scripts/tui/statusline-schema.json | python3 scripts/tui/statusline.py
```

The committed `statusline-schema.json` serves as the canonical test fixture.

No automated test is added to CI — the statusline is a devex tool, not a gate.
If the script errors, it produces blank output in the TUI; CC handles this gracefully
(logs the error in `--debug` mode, continues running).

---

## §10 Future: B → C Migration Path

When scope demands it (more than 2 scripts, or the bridge needs a typed contract),
the migration from B to C is:

1. Accessor functions → dataclass fields (~30 lines)
2. Inline formatting → segment functions with a registry (~20 lines)
3. Hardcoded ANSI → renderer abstraction (terminal ANSI vs Godot BBCode) (~20 lines)

Total delta: ~70 lines of structure. One session.

---

## §11 Acceptance Criteria

- [ ] `scripts/tui/cc_session.py` exists, imports cleanly, handles all documented null/absent fields
- [ ] `scripts/tui/statusline.py` produces two-line ANSI output when fed the schema JSON
- [ ] `scripts/tui/subagent_statusline.py` produces JSON lines when fed subagent task JSON
- [ ] `scripts/tui/statusline-schema.json` matches the schema documented by Anthropic
- [ ] `docs/cc-statusline-protocol.md` exists with proper frontmatter, registered in doc-registry.json
- [ ] `.claude/settings.json` has `statusLine` and `subagentStatusLine` pointing to the scripts
- [ ] Scripts pass `black --check` and `flake8 --select=E9,F63,F7,F82`
- [ ] Statusline renders correctly in a live Claude Code session (manual verification)
