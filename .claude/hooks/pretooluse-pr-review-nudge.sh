#!/usr/bin/env bash
# PreToolUse nudge — PR review feedback and merge guard.
#
# Four triggers, one script:
#
# 1. REPLY NUDGE: fires before `gh pr comment`, `gh pr review`, or
#    `gh api ...pulls/*/comments -X POST`. Reminds the agent to invoke
#    superpowers:receiving-code-review, verify claims against the code,
#    and sign the reply on Adam's behalf.
#
# 2. MERGE GUARD: fires before `gh pr merge`. BLOCKS (permissionDecision:
#    ask) until user confirms all review comments are addressed. Tells
#    agent to use `gh api` (not `gh pr view --comments`) to check.
#
# 3. GH PR VIEW REDIRECT: fires before `gh pr view --comments`. DENIES
#    the call — `gh pr view --comments` misses review-body comments and
#    suppressed co-pilot reviews. Redirects to `gh api` method.
#
# 4. READ COMMENTS NUDGE: fires before `gh api ...pulls/*/comments` (GET).
#    Reminds agent to invoke receiving-code-review and check for
#    suppressed co-pilot reviews.
#
# Registered on PreToolUse > Bash with `if: "Bash(gh *)"` so it only
# fires for gh commands.
#
# Adapted from tasteslikegoodtheangularsvegancookbook/.claude/hooks/
# pretooluse-pr-review-nudge.sh, extended with merge guard.
#
# Fail-open: any error exits 0 so a transient failure never blocks.
set -uo pipefail
trap 'exit 0' ERR

payload="$(cat)"
tool_name="$(printf '%s' "$payload" | jq -r '.tool_name // empty' 2>/dev/null || true)"

[ "$tool_name" = "Bash" ] || exit 0

cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"

# --- Reply nudge ---
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+pr[[:space:]]+(comment|review)([[:space:]]|$)'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"You are about to post a reply to PR review feedback. Per the PR workflow rules: if you have not already this turn, invoke the superpowers:receiving-code-review skill and evaluate this feedback with technical rigor -- verify each claim against the code, then either push a fix commit or give a concrete technical rebuttal (never performative agreement, never silently ignore). End the reply with the attribution line: _Replied by Claude on Adam's behalf_"}}
JSON
  exit 0
fi

if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+api[[:space:]]' \
  && printf '%s' "$cmd" | grep -Eq 'pulls/[0-9]+/comments' \
  && printf '%s' "$cmd" | grep -Eq '(-X[[:space:]]*POST|--method[[:space:]]*POST|-f[[:space:]]|-F[[:space:]]|--field[[:space:]]|--input[[:space:]])'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"You are about to post a reply to PR review feedback via gh api. Per the PR workflow rules: if you have not already this turn, invoke the superpowers:receiving-code-review skill and evaluate this feedback with technical rigor -- verify each claim against the code, then either push a fix commit or give a concrete technical rebuttal (never performative agreement, never silently ignore). End the reply with the attribution line: _Replied by Claude on Adam's behalf_"}}
JSON
  exit 0
fi

# --- Merge guard (blocks until user confirms) ---
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+pr[[:space:]]+merge([[:space:]]|$)'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"Merge guard: have all review comments been addressed?","additionalContext":"STOP -- you are about to merge a PR. Before merging, you MUST check for unanswered review comments. Use `gh api repos/{owner}/{repo}/pulls/{number}/comments` (NOT `gh pr view --comments` which misses review-body comments) and `gh api repos/{owner}/{repo}/issues/{number}/comments` to retrieve ALL review feedback including suppressed co-pilot reviews. Every comment must be addressed with either a fix commit or a concrete technical rebuttal. If any comment is unanswered, deny this merge and address it first."}}
JSON
  exit 0
fi

# --- gh pr view --comments redirect (wrong tool) ---
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+pr[[:space:]]+view[[:space:]]' \
  && printf '%s' "$cmd" | grep -Eq '(--comments|-c)([[:space:]]|$)'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Use gh api instead -- gh pr view --comments misses review-body comments and suppressed co-pilot reviews","additionalContext":"WRONG TOOL: `gh pr view --comments` only shows issue-style comments, NOT inline review comments or suppressed co-pilot reviews. Use `gh api repos/{owner}/{repo}/pulls/{number}/comments` to get ALL review comments. Also check `gh api repos/{owner}/{repo}/issues/{number}/comments` for top-level PR comments."}}
JSON
  exit 0
fi

# --- Reading PR comments (load receiving-code-review skill) ---
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+api[[:space:]]' \
  && printf '%s' "$cmd" | grep -Eq 'pulls/[0-9]+/comments' \
  && ! printf '%s' "$cmd" | grep -Eq '(-X[[:space:]]*POST|--method[[:space:]]*POST|-f[[:space:]]|-F[[:space:]]|--field[[:space:]]|--input[[:space:]])'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"You are reading PR review comments via the correct API method (gh api). If you have not already this turn, invoke the superpowers:receiving-code-review skill before responding to any feedback. Also check `gh api repos/{owner}/{repo}/issues/{number}/comments` for top-level PR comments, and watch for suppressed co-pilot reviews in the response body -- these are real reviews that should be evaluated with the same rigor."}}
JSON
  exit 0
fi

exit 0
