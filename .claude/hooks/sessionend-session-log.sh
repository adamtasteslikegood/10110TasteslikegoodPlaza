#!/usr/bin/env bash
# SessionEnd hook — session-log safety net for paths PreCompact misses.
#
# Covers /clear and normal exit. Applies a substance gate: sessions whose
# condensed digest is under 800 chars are skipped.
#
# Design rules: never block teardown, detach slow work, recursion guard.

set -uo pipefail
trap 'exit 0' ERR

if [ -n "${CLAUDE_PM_SESSION_LOG_ACTIVE:-}" ]; then
  exit 0
fi

INPUT=$(cat 2>/dev/null || true)
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

COMMON_GIT=$(git -C "$PROJECT_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "")
if [ -n "$COMMON_GIT" ] && [ -d "$COMMON_GIT" ]; then
  MAIN_REPO=$(dirname "$COMMON_GIT")
else
  MAIN_REPO="$PROJECT_DIR"
fi

LOG="$MAIN_REPO/.claude/session-log-hook.log"
mkdir -p "$(dirname "$LOG")"

_field() {
  printf '%s' "$INPUT" | python3 -c "
import json,sys
try: print((json.load(sys.stdin) or {}).get('$1','') or '')
except Exception: print('')
" 2>/dev/null
}

TRANSCRIPT=$(_field transcript_path)
SESSION_ID=$(_field session_id)
REASON=$(_field reason)

{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) SessionEnd reason=${REASON:-?} session=${SESSION_ID:-?}"
} >>"$LOG" 2>&1

if [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ]; then
  echo "  skip: no transcript at '${TRANSCRIPT:-<empty>}'" >>"$LOG"
  exit 0
fi

_has_cred() {
  [ -n "$(printenv "$1" 2>/dev/null)" ] && return 0
  grep -qs "^[[:space:]]*$1=[^[:space:]]" "$MAIN_REPO/.env"
}

MISSING=""
for key in ATLASSIAN_URL ATLASSIAN_EMAIL ATLASSIAN_API_TOKEN; do
  _has_cred "$key" || MISSING="$MISSING $key"
done
if [ -n "$MISSING" ]; then
  echo "  skip: missing Atlassian credentials (env or $MAIN_REPO/.env):$MISSING" >>"$LOG"
  exit 0
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "  skip: claude CLI not on PATH" >>"$LOG"
  exit 0
fi

(
  export CLAUDE_PM_SESSION_LOG_ACTIVE=1

  if [ -n "$SESSION_ID" ]; then
    SAFE_ID=$(printf '%s' "$SESSION_ID" | tr -c 'A-Za-z0-9._-' '_')
    CLAIM_ROOT="$MAIN_REPO/.claude/session-logs"
    CLAIM="$CLAIM_ROOT/$SAFE_ID"
    mkdir -p "$CLAIM_ROOT" 2>/dev/null || true
    if [ -d "$CLAIM" ] && [ -n "$(find "$CLAIM" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
      rm -rf "$CLAIM" 2>/dev/null || true
    fi
    if ! mkdir "$CLAIM" 2>/dev/null; then
      echo "  skip: session ${SESSION_ID} already logged within 10 min" >>"$LOG"
      exit 0
    fi
  fi

  WORK=$(mktemp -d -t session-log-end-XXXXXX)
  trap 'rm -rf "$WORK" "${CLAIM:-}"' EXIT

  DIGEST="$WORK/digest.txt"
  SUMMARY="$WORK/summary.md"

  DIGEST_PY="$PROJECT_DIR/scripts/pm/transcript_digest.py"
  [ -f "$DIGEST_PY" ] || DIGEST_PY="$MAIN_REPO/scripts/pm/transcript_digest.py"

  if ! python3 "$DIGEST_PY" \
      --transcript "$TRANSCRIPT" --max-chars 40000 >"$DIGEST" 2>>"$LOG"; then
    echo "  FAIL: transcript_digest.py ($DIGEST_PY)" >>"$LOG"
    exit 0
  fi

  DIGEST_CHARS=$(LC_ALL=C.UTF-8 wc -m <"$DIGEST" 2>/dev/null | tr -d ' ')
  DIGEST_CHARS=${DIGEST_CHARS:-0}
  if [ "$DIGEST_CHARS" -lt 800 ]; then
    echo "  skip: digest too small ($DIGEST_CHARS chars < 800) — trivial session" >>"$LOG"
    exit 0
  fi

  BRANCH=$(git -C "$PROJECT_DIR" branch --show-current 2>/dev/null || echo unknown)
  STAMP=$(date -u +%Y%m%d-%H%M%S)

  SNAP_SH="$PROJECT_DIR/.claude/hooks/lib/pm-snapshot.sh"
  [ -f "$SNAP_SH" ] || SNAP_SH="$MAIN_REPO/.claude/hooks/lib/pm-snapshot.sh"
  PM_SNAPSHOT=""
  if [ -f "$SNAP_SH" ]; then
    PM_SNAPSHOT=$(bash "$SNAP_SH" "$PROJECT_DIR" "$MAIN_REPO" "$BRANCH" 2>>"$LOG" || echo "")
  fi
  [ -n "$PM_SNAPSHOT" ] || PM_SNAPSHOT="(PM snapshot unavailable.)"

  PROMPT="You are writing a session log for an engineering team's Confluence.

Below is a condensed transcript of a Claude Code session on branch \`$BRANCH\`.
Write a session log in GitHub-flavored markdown with EXACTLY these sections:

## Summary
2-4 sentences. What was this session actually about, and what changed?

## Key decisions
Bullets. Each is a decision made and WHY. If none, write 'None.'

## Files changed
Bullets of file paths. If none, write 'None.'

## Follow-ups
Bullets of work left undone or flagged. If none, 'None.'

## Gotchas
Bullets of anything surprising or that cost time. If none, 'None.'

## Atlassian Alignment
Open with exactly one verdict in bold — **Aligned**, **Partially aligned**, or
**Drifting** — then 1-3 bullets of evidence naming specific PLZG keys and PR
numbers you saw. Judge with this rubric:
  * Git = code truth. PLZG = execution truth (who is on what, blockers).
    Confluence = durable narrative and session-history truth.
  * **Aligned** — active work is visible in PLZG, durable context is in
    Confluence, and both match the branch/PR state in the PM snapshot.
  * **Partially aligned** — one of PLZG/Confluence is stale or missing key
    updates. A fresh agent could not resume cleanly.
  * **Drifting** — branch/PR reality materially differs from what Jira or
    Confluence says.
If you have too little to judge, write '**Partially aligned** — insufficient
evidence in transcript' and say what is missing.

Rules: be concrete, name files and identifiers, no filler. Where the transcript
and PM snapshot disagree, TRUST THE SNAPSHOT. NEVER reproduce secrets.

Output ONLY the markdown.

--- PM SNAPSHOT ---
$PM_SNAPSHOT

--- TRANSCRIPT DIGEST ---
$(cat "$DIGEST")"

  if command -v timeout >/dev/null 2>&1; then
    RUNNER=(timeout 240)
  elif command -v gtimeout >/dev/null 2>&1; then
    RUNNER=(gtimeout 240)
  else
    RUNNER=()
  fi

  if ! "${RUNNER[@]}" claude -p "$PROMPT" \
        --model claude-haiku-4-5-20251001 \
        --allowedTools '' >"$SUMMARY" 2>>"$LOG"; then
    echo "  FAIL: claude -p summarizer" >>"$LOG"
    exit 0
  fi

  if [ ! -s "$SUMMARY" ]; then
    echo "  FAIL: summarizer produced empty output" >>"$LOG"
    exit 0
  fi

  TITLED="$WORK/titled.md"
  {
    echo "# Session Log — $BRANCH — $STAMP"
    echo
    echo "> Auto-captured by the SessionEnd hook (reason: ${REASON:-unknown}). Summarized by Haiku."
    echo "> Session ID: \`${SESSION_ID:-unknown}\`"
    echo
    cat "$SUMMARY"
  } >"$TITLED"

  if bash "$MAIN_REPO/scripts/pm/run_pm_script.sh" publish_session_log.py \
      --file "$TITLED" --root "$MAIN_REPO" \
      --title "Session Log: session-end (${REASON:-exit}) — $BRANCH — $STAMP" >>"$LOG" 2>&1; then
    echo "  OK: published session log for $BRANCH" >>"$LOG"
  else
    echo "  FAIL: publish_session_log.py (summary preserved below)" >>"$LOG"
    cat "$TITLED" >>"$LOG"
  fi
) >/dev/null 2>&1 &

disown 2>/dev/null || true
exit 0
