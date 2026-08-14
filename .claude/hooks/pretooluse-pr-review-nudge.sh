#!/usr/bin/env bash
# PreToolUse nudge — PR review feedback and merge guard.
#
# Two triggers, one script:
#
# 1. REPLY NUDGE: fires before `gh pr comment`, `gh pr review`, or
#    `gh api ...pulls/*/comments -X POST`. Reminds the agent to invoke
#    superpowers:receiving-code-review, verify claims against the code,
#    and sign the reply on Adam's behalf.
#
# 2. MERGE GUARD: fires before `gh pr merge`. Reminds the agent to
#    check for unanswered review comments before merging.
#
# Registered on PreToolUse > Bash with `if: "Bash(gh *)"` so it only
# fires for gh commands. Non-blocking: injects additionalContext only.
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

# --- Merge guard ---
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+pr[[:space:]]+merge([[:space:]]|$)'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"STOP -- you are about to merge a PR. Before merging, you MUST check for unanswered review comments. Run `gh api repos/{owner}/{repo}/pulls/{number}/comments` and `gh api repos/{owner}/{repo}/issues/{number}/comments` to verify all review feedback has been addressed with either a fix commit or a concrete technical rebuttal. If any comment is unanswered, address it first. Do not merge with unresolved feedback."}}
JSON
  exit 0
fi

# --- Reading PR comments (load receiving-code-review skill) ---
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+api[[:space:]]' \
  && printf '%s' "$cmd" | grep -Eq 'pulls/[0-9]+/comments' \
  && ! printf '%s' "$cmd" | grep -Eq '(-X[[:space:]]*POST|--method[[:space:]]*POST|-f[[:space:]]|-F[[:space:]]|--field[[:space:]]|--input[[:space:]])'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"You are reading PR review comments. If you have not already this turn, invoke the superpowers:receiving-code-review skill before responding to any feedback."}}
JSON
  exit 0
fi

exit 0
