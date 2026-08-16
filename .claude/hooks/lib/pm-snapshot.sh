#!/usr/bin/env bash
# PM snapshot builder — shared by precompact-session-log.sh and
# sessionend-session-log.sh.
#
# Gathers machine-observable facts (branch, git position, open PRs, dirty
# files) for the session-log summarizer which runs with --allowedTools ''
# and can read nothing but its prompt.
#
# Usage:  pm-snapshot.sh <project_dir> <main_repo> <branch>
# Output: markdown block on stdout. Always exits 0.

set -uo pipefail

PROJECT_DIR="${1:-$(pwd)}"
MAIN_REPO="${2:-$PROJECT_DIR}"
BRANCH="${3:-unknown}"

if command -v timeout >/dev/null 2>&1; then
  _t() { timeout "$@"; }
elif command -v gtimeout >/dev/null 2>&1; then
  _t() { gtimeout "$@"; }
else
  _t() { shift; "$@"; }
fi

echo "## PM snapshot (gathered from the machine, not the transcript)"
echo
echo "- Branch: \`$BRANCH\`"

AHEAD=$(_t 10 git -C "$PROJECT_DIR" rev-list --count origin/dev..HEAD 2>/dev/null || echo "")
[ -n "$AHEAD" ] && echo "- Commits ahead of \`origin/dev\`: $AHEAD"

DIRTY=$(_t 10 git -C "$PROJECT_DIR" status --porcelain 2>/dev/null \
  | grep -v '\.claude/session-log' \
  | grep -v '\.claude/pm-daemon-watcher\.lock' \
  | wc -l | tr -d ' ')
[ -n "$DIRTY" ] && echo "- Uncommitted files in working tree: $DIRTY"

CHANGED=$(_t 10 git -C "$PROJECT_DIR" diff --name-only origin/dev...HEAD 2>/dev/null | head -25)
if [ -n "$CHANGED" ]; then
  echo "- Files changed vs \`origin/dev\` (first 25):"
  printf '%s\n' "$CHANGED" | sed 's/^/  - /'
fi

if command -v gh >/dev/null 2>&1 && [ "$BRANCH" != "unknown" ]; then
  prs=$(_t 25 gh pr list --head "$BRANCH" --state open \
          --json number,title,url \
          --jq '.[] | "  - #\(.number) \(.title) — \(.url)"' 2>/dev/null || echo "")
  if [ -n "$prs" ]; then
    echo "- Open PRs for this branch:"
    printf '%s\n' "$prs"
  else
    echo "- Open PRs for this branch: none found"
  fi
else
  echo "- Open PRs: not checked (gh unavailable or branch unknown)"
fi

BRIEFING="$MAIN_REPO/.agent-work/pm/PROJECT_PM_BRIEFING.md"
if [ -f "$BRIEFING" ]; then
  MTIME=$(date -u -r "$BRIEFING" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
          || stat -c %y "$BRIEFING" 2>/dev/null || echo "unknown")
  echo "- PM briefing last refreshed: $MTIME"
else
  echo "- PM briefing: absent"
fi

exit 0
