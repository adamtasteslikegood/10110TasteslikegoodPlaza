# CC TUI Statusline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a custom Claude Code statusline and subagent statusline for this project, built on a shared Python parser module that prototypes the bridge's session data contract.

**Architecture:** A shared parser module (`cc_session.py`) reads CC's stdin JSON and exposes null-safe accessor functions. Two thin scripts import it: `statusline.py` (two-line main dashboard) and `subagent_statusline.py` (per-row agent renderer). All committed to `scripts/tui/`. A governed reference doc in `docs/` documents the protocol. Settings.json wiring makes it active for all contributors.

**Tech Stack:** Python 3 (stdlib only — `json`, `sys`, `os`, `subprocess`, `time`). ANSI escape codes for terminal color. `jq` not required.

**Design spec:** `docs/superpowers/specs/2026-08-13-cc-tui-statusline-design.md`

## Global Constraints

- Python stdlib only — no third-party dependencies (this repo's CI has no `pip install` step)
- All scripts must pass `black --check .` and `flake8 . --select=E9,F63,F7,F82`
- Scripts are executable (`chmod +x`) and use `#!/usr/bin/env python3` shebang
- ANSI codes only — no unicode box-drawing beyond `█` and `░` (safe in all modern terminals)
- `$CLAUDE_PROJECT_DIR` for paths in settings.json — portable across clones and worktrees
- The governed reference doc needs YAML frontmatter matching the pattern in `docs/quick-reference.md` and a registry entry in `specs/meta/doc-registry.json`
- Run `python3 scripts/validate_specs.py` after adding the reference doc to confirm the registry is valid

---

### Task 1: Shared parser module and JSON schema

**Files:**
- Create: `scripts/tui/__init__.py` (empty, makes directory importable)
- Create: `scripts/tui/cc_session.py`
- Create: `scripts/tui/statusline-schema.json`

**Interfaces:**
- Consumes: CC's stdin JSON (documented in the schema file created here)
- Produces: All accessor functions that Tasks 2 and 3 import:
  - `parse_session() -> dict`
  - `get_model(data: dict) -> tuple[str, str]`
  - `get_context(data: dict) -> dict` with keys `used_pct`, `remaining_pct`, `total_input`, `total_output`, `window_size`
  - `get_cost(data: dict) -> dict` with keys `cost_usd`, `duration_ms`, `api_duration_ms`, `lines_added`, `lines_removed`
  - `get_rate_limits(data: dict) -> dict | None` with keys `five_hour_pct`, `seven_day_pct`
  - `get_workspace(data: dict) -> dict` with keys `current_dir`, `project_dir`, `repo_owner`, `repo_name`, `git_worktree`
  - `get_git_status(data: dict) -> dict` with keys `branch`, `staged_count`, `modified_count`
  - `get_pr(data: dict) -> dict | None` with keys `number`, `url`, `review_state`
  - `get_worktree(data: dict) -> dict | None` with keys `name`, `path`, `branch`, `original_cwd`, `original_branch`
  - `format_duration(ms: int) -> str`
  - ANSI color constants: `CYAN`, `GREEN`, `YELLOW`, `RED`, `DIM`, `RESET`

- [ ] **Step 1: Create the JSON schema file**

Create `scripts/tui/statusline-schema.json` with CC's full schema from the design spec §7. This file serves as both documentation and test fixture.

```json
{
  "cwd": "/home/user/Projects/10110TasteslikegoodPlaza",
  "session_id": "abc123-test-session",
  "session_name": "my-session",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
  "transcript_path": "/path/to/transcript.jsonl",
  "model": {
    "id": "claude-opus-4-6",
    "display_name": "Opus 4.6"
  },
  "workspace": {
    "current_dir": "/home/user/Projects/10110TasteslikegoodPlaza",
    "project_dir": "/home/user/Projects/10110TasteslikegoodPlaza",
    "added_dirs": [],
    "git_worktree": "feature-xyz",
    "repo": {
      "host": "github.com",
      "owner": "adamtasteslikegood",
      "name": "10110TasteslikegoodPlaza"
    }
  },
  "version": "2.1.200",
  "output_style": {
    "name": "default"
  },
  "cost": {
    "total_cost_usd": 1.23,
    "total_duration_ms": 754000,
    "total_api_duration_ms": 23000,
    "total_lines_added": 156,
    "total_lines_removed": 23
  },
  "context_window": {
    "total_input_tokens": 84000,
    "total_output_tokens": 1200,
    "context_window_size": 200000,
    "used_percentage": 42,
    "remaining_percentage": 58,
    "current_usage": {
      "input_tokens": 8500,
      "output_tokens": 1200,
      "cache_creation_input_tokens": 5000,
      "cache_read_input_tokens": 2000
    }
  },
  "exceeds_200k_tokens": false,
  "fast_mode": false,
  "effort": {
    "level": "high"
  },
  "thinking": {
    "enabled": true
  },
  "rate_limits": {
    "five_hour": {
      "used_percentage": 23.5,
      "resets_at": 1738425600
    },
    "seven_day": {
      "used_percentage": 41.2,
      "resets_at": 1738857600
    }
  },
  "vim": {
    "mode": "NORMAL"
  },
  "agent": {
    "name": "security-reviewer"
  },
  "pr": {
    "number": 198,
    "url": "https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/pull/198",
    "review_state": "pending"
  },
  "worktree": {
    "name": "my-feature",
    "path": "/home/user/.claude/worktrees/my-feature",
    "branch": "worktree-my-feature",
    "original_cwd": "/home/user/Projects/10110TasteslikegoodPlaza",
    "original_branch": "dev"
  }
}
```

- [ ] **Step 2: Create the empty `__init__.py`**

Create `scripts/tui/__init__.py` as an empty file. This makes `scripts/tui` a Python package so the statusline scripts can import `cc_session` as a sibling module.

```python
```

(Empty file — just needs to exist.)

- [ ] **Step 3: Write `cc_session.py`**

Create `scripts/tui/cc_session.py` with all accessor functions. Every function handles absent keys and null values with documented fallbacks.

```python
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
    session_id = data.get("session_id", "unknown")
    cache_file = f"/tmp/statusline-git-cache-{session_id}"

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
```

- [ ] **Step 4: Test the parser against the schema fixture**

Run from the repo root:

```bash
python3 -c "
import sys, os
sys.path.insert(0, 'scripts/tui')
import cc_session, json

with open('scripts/tui/statusline-schema.json') as f:
    data = json.load(f)

model_id, model_name = cc_session.get_model(data)
assert model_name == 'Opus 4.6', f'got {model_name}'

ctx = cc_session.get_context(data)
assert ctx['used_pct'] == 42, f'got {ctx[\"used_pct\"]}'

cost = cc_session.get_cost(data)
assert cost['cost_usd'] == 1.23, f'got {cost[\"cost_usd\"]}'

rl = cc_session.get_rate_limits(data)
assert rl is not None
assert rl['five_hour_pct'] == 23.5

ws = cc_session.get_workspace(data)
assert '10110' in ws['current_dir']

pr = cc_session.get_pr(data)
assert pr['number'] == 198
assert pr['review_state'] == 'pending'

wt = cc_session.get_worktree(data)
assert wt['name'] == 'my-feature'

dur = cc_session.format_duration(754000)
assert dur == '12m 34s', f'got {dur}'

print('All assertions passed')
"
```

Expected: `All assertions passed`

- [ ] **Step 5: Test null/absent field handling**

Run from the repo root — this verifies the parser handles a minimal JSON payload (pre-first-API-response, no PR, no worktree, no rate limits):

```bash
python3 -c "
import sys
sys.path.insert(0, 'scripts/tui')
import cc_session

data = {
    'model': {'id': 'claude-sonnet-5', 'display_name': 'Sonnet'},
    'workspace': {'current_dir': '/tmp/test'},
    'session_id': 'test',
    'context_window': {'used_percentage': None, 'context_window_size': 200000},
    'cost': {}
}

ctx = cc_session.get_context(data)
assert ctx['used_pct'] == 0, 'null percentage should fallback to 0'

cost = cc_session.get_cost(data)
assert cost['cost_usd'] == 0, 'absent cost should fallback to 0'

rl = cc_session.get_rate_limits(data)
assert rl is None, 'absent rate_limits should return None'

pr = cc_session.get_pr(data)
assert pr is None, 'absent pr should return None'

wt = cc_session.get_worktree(data)
assert wt is None, 'absent worktree should return None'

ws = cc_session.get_workspace(data)
assert ws['repo_owner'] is None, 'absent repo should give None owner'

print('All null-handling assertions passed')
"
```

Expected: `All null-handling assertions passed`

- [ ] **Step 6: Run linters**

```bash
black --check scripts/tui/cc_session.py
flake8 scripts/tui/cc_session.py --select=E9,F63,F7,F82
```

Expected: both pass with no output.

- [ ] **Step 7: Commit**

```bash
git add scripts/tui/__init__.py scripts/tui/cc_session.py scripts/tui/statusline-schema.json
git commit -m "feat(tui): add shared CC session parser and JSON schema

Shared parser module (cc_session.py) reads Claude Code's statusline
stdin JSON and exposes null-safe accessor functions for model, context
window, cost, rate limits, workspace, git status, PR, and worktree
data. Committed schema serves as documentation and test fixture."
```

---

### Task 2: Main statusline script

**Files:**
- Create: `scripts/tui/statusline.py`

**Interfaces:**
- Consumes: All functions from `cc_session.py` (Task 1)
- Produces: Two lines of ANSI-colored text to stdout when executed

- [ ] **Step 1: Write `statusline.py`**

Create `scripts/tui/statusline.py`. This script is invoked by Claude Code — it reads JSON from stdin, uses the shared parser, and prints two lines.

```python
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
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/tui/statusline.py
```

- [ ] **Step 3: Test with the schema fixture**

```bash
cat scripts/tui/statusline-schema.json | python3 scripts/tui/statusline.py
```

Expected output (with ANSI colors — raw text shown here):
```
[Opus 4.6] 10110TasteslikegoodPlaza | dev wt:my-feature  PR #198 pending
████░░░░░░ 42% | $1.23 | 5h: 24% 7d: 41% | 12m 34s
```

Verify: two lines, model name in cyan, cost in yellow, context bar in green (42% < 70%).

- [ ] **Step 4: Test with minimal input (no PR, no worktree, no rate limits)**

```bash
echo '{"model":{"id":"claude-sonnet-5","display_name":"Sonnet"},"workspace":{"current_dir":"/tmp/test-project"},"session_id":"test","context_window":{"used_percentage":null},"cost":{}}' | python3 scripts/tui/statusline.py
```

Expected output:
```
[Sonnet] test-project
░░░░░░░░░░ -- | $0.00 | 0m 0s
```

Verify: no branch, no worktree, no PR, no rate limits. Context shows `--`. Cost shows `$0.00`.

- [ ] **Step 5: Run linters**

```bash
black --check scripts/tui/statusline.py
flake8 scripts/tui/statusline.py --select=E9,F63,F7,F82
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/tui/statusline.py
git commit -m "feat(tui): add two-line main statusline script

Two-line dashboard: Line 1 shows model, project, branch, worktree
name, PR status. Line 2 shows color-coded context bar, cost, rate
limits, and duration. All segments degrade gracefully when fields
are absent or null."
```

---

### Task 3: Subagent statusline script

**Files:**
- Create: `scripts/tui/subagent_statusline.py`

**Interfaces:**
- Consumes: ANSI color constants and `format_duration` from `cc_session.py` (Task 1)
- Consumes: CC's subagent JSON input (different shape from main statusline — has `tasks` array)
- Produces: One JSON line per task to stdout: `{"id": "...", "content": "..."}`

- [ ] **Step 1: Write `subagent_statusline.py`**

Create `scripts/tui/subagent_statusline.py`. This script receives a different JSON shape than the main statusline — an object with a `tasks` array. Each task has `id`, `name`, `label`, `status`, `model`, `effort`, `tokenCount`, `contextWindowSize`.

```python
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
    color_map = {
        "completed": cc_session.GREEN,
        "running": cc_session.YELLOW,
    }
    color = color_map.get(status, cc_session.DIM)
    return f"{color}{status or 'queued'}{cc_session.RESET}"


def render_task(task):
    name = task.get("label") or task.get("name") or "agent"
    model_id = task.get("model", "")
    model_short = shorten_model(model_id)
    token_count = task.get("tokenCount")
    context_size = task.get("contextWindowSize")
    effort = task.get("effort")
    status = task.get("status")

    bar, pct_label = build_mini_bar(token_count, context_size)

    parts = [f"{name} [{model_short}] {bar} {pct_label}"]

    if effort:
        effort_labels = {"xhigh": "xhigh", "medium": "med"}
        parts.append(effort_labels.get(effort, effort))

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
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/tui/subagent_statusline.py
```

- [ ] **Step 3: Test with mock subagent input**

```bash
echo '{
  "tasks": [
    {
      "id": "task-1",
      "name": "code-reviewer",
      "label": "review:bugs",
      "status": "running",
      "model": "claude-opus-4-6",
      "effort": "high",
      "tokenCount": 46000,
      "contextWindowSize": 200000
    },
    {
      "id": "task-2",
      "name": "Explore",
      "status": "completed",
      "model": "claude-sonnet-5",
      "tokenCount": 150000,
      "contextWindowSize": 200000
    },
    {
      "id": "task-3",
      "name": "general-purpose",
      "status": "queued",
      "model": null,
      "tokenCount": null,
      "contextWindowSize": null
    }
  ]
}' | python3 scripts/tui/subagent_statusline.py
```

Expected: three JSON lines to stdout, one per task. Verify:
- task-1 shows `review:bugs [O4.6]` with a mini bar at 23%, effort `high`, status `running` in yellow
- task-2 shows `Explore [S5]` with a mini bar at 75%, no effort, status `completed` in green
- task-3 shows `general-purpose [?]` with dim empty bar and `--`, no effort, status `queued` in dim

- [ ] **Step 4: Run linters**

```bash
black --check scripts/tui/subagent_statusline.py
flake8 scripts/tui/subagent_statusline.py --select=E9,F63,F7,F82
```

Expected: both pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/tui/subagent_statusline.py
git commit -m "feat(tui): add subagent statusline renderer

Per-row subagent renderer showing agent name, shortened model tier,
mini context bar, effort level, and color-coded status. Outputs one
JSON line per task as required by CC's subagentStatusLine protocol."
```

---

### Task 4: Reference doc, doc registry, and settings.json wiring

**Files:**
- Create: `docs/cc-statusline-protocol.md`
- Modify: `specs/meta/doc-registry.json` (add entry to `documents` array and add the design spec to `exempt` array)
- Modify: `.claude/settings.json` (add `statusLine` and `subagentStatusLine`)

**Interfaces:**
- Consumes: the committed schema from Task 1 (`scripts/tui/statusline-schema.json`)
- Consumes: the statusline/subagent scripts from Tasks 2 and 3
- Produces: a governed reference doc discoverable via the doc registry; live statusline in all CC sessions in this repo

- [ ] **Step 1: Create the governed reference doc**

Create `docs/cc-statusline-protocol.md` with proper YAML frontmatter. The `authority: reference` and `tier: 4` match the doc classification from the design spec. Follow the frontmatter pattern from `docs/quick-reference.md`.

```markdown
---
doc_id: CC-STATUSLINE-PROTOCOL
title: Claude Code Statusline Protocol Reference
tier: 4
authority: reference
status: ACTIVE
doc_set_version: 0.2.12
last_updated: 2026-08
owner: adamtasteslikegood
derives_from: []
enforcement: na
enforcement_na_reason: "External protocol documentation. Describes Anthropic's shipped CC statusline feature; asserts nothing about this repository's code or state."
gates: []
---

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
```

- [ ] **Step 2: Add registry entries**

Add the new reference doc to the `documents` array in `specs/meta/doc-registry.json`, and add the design spec and implementation plan to the `exempt` array.

Add to `documents` array (after `AGILE-LIKE-IM-5` entry):

```json
    {
      "doc_id": "CC-STATUSLINE-PROTOCOL",
      "path": "docs/cc-statusline-protocol.md",
      "tier": 4,
      "authority": "reference",
      "status": "ACTIVE",
      "note": "Claude Code statusline protocol reference. Documents Anthropic's shipped JSON schema for statusline scripts and annotates bridge relevance per field. External protocol, asserts nothing about this repository.",
      "enforcement_na_reason": "External protocol documentation. Describes Anthropic's shipped CC statusline feature; asserts nothing about this repository's code or state."
    }
```

Add to `exempt` array (after the existing superpowers entries):

```json
    {
      "path": "docs/superpowers/specs/2026-08-13-cc-tui-statusline-design.md",
      "reason": "Superpowers-generated design spec. Brainstorming output driving the plan, not a governed doc."
    },
    {
      "path": "docs/superpowers/plans/2026-08-13-cc-tui-statusline.md",
      "reason": "Superpowers-generated implementation plan. Execution artifact, not a governed spec."
    }
```

- [ ] **Step 3: Validate the registry**

```bash
python3 scripts/validate_specs.py
```

Expected: pass with no errors. If it fails, read the error — likely a path typo or missing frontmatter field.

- [ ] **Step 4: Wire settings.json**

Add `statusLine` and `subagentStatusLine` to `.claude/settings.json`. The existing keys (`extraKnownMarketplaces`, `enabledPlugins`, `hooks`) stay untouched. Add the new keys at the top level.

The final `.claude/settings.json` should look like:

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
  },
  "extraKnownMarketplaces": {
    ...existing...
  },
  "enabledPlugins": {
    ...existing...
  },
  "hooks": {
    ...existing...
  }
}
```

- [ ] **Step 5: Run linters on all scripts**

```bash
black --check scripts/tui/
flake8 scripts/tui/ --select=E9,F63,F7,F82
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add docs/cc-statusline-protocol.md specs/meta/doc-registry.json .claude/settings.json
git commit -m "feat(tui): wire statusline into settings, add protocol reference doc

- Add governed reference doc (docs/cc-statusline-protocol.md) with
  field inventory and bridge relevance annotations
- Register in doc-registry.json; exempt design spec and plan
- Wire statusLine and subagentStatusLine in project settings.json
  with refreshInterval: 10 for timer-based updates"
```

- [ ] **Step 7: Manual verification**

Start a new Claude Code session in this repo (or restart the current one) and verify:
1. The statusline appears at the bottom of the TUI
2. Line 1 shows model name, project folder, and git branch
3. Line 2 shows a context bar, cost, and duration
4. If running subagents, the subagent panel shows custom rows

If the statusline is blank, run `claude --debug` and check for script errors in the log output.
