#!/usr/bin/env bash
# PreToolUse nudge — PR review feedback and merge guard.
#
# Four triggers, one script. A hook invocation can return only ONE
# decision, and `grep -Eq` matches its pattern ANYWHERE in the command
# string, so a compound command (`gh pr comment ... && gh pr merge ...`)
# can match several triggers at once. They are therefore evaluated
# STRONGEST-FIRST — blocking branches before informational ones — so a
# blocking decision always wins regardless of where its subcommand sits
# in the chain. File order == priority order:
#
# 1. GH PR VIEW REDIRECT (deny): fires before `gh pr view --comments`.
#    DENIES the call — it misses review-body comments and suppressed
#    co-pilot reviews. Redirects to the `gh api` method.
#
# 2. MERGE GUARD (deny / pass / ask): fires before `gh pr merge` and
#    checks the PR's review threads itself (`D-031`, `PLZG-278`). Any
#    unresolved thread DENIES the merge and names it. None unresolved
#    lets the merge through with a reminder about the two surfaces thread
#    state cannot see. If the PR or its threads cannot be read, it falls
#    back to ASK rather than guessing either way.
#
# 3. REPLY NUDGE (informational): fires before `gh pr comment`,
#    `gh pr review`, or `gh api ...pulls/*/comments -X POST`. Reminds the
#    agent to invoke superpowers:receiving-code-review, verify claims
#    against the code, and sign the reply on Adam's behalf.
#
# 4. READ COMMENTS NUDGE (informational): fires before
#    `gh api ...pulls/*/comments` (GET). Reminds the agent to invoke
#    receiving-code-review and check for suppressed co-pilot reviews.
#
# Registered on PreToolUse > Bash with `if: "Bash(gh *)"` so it only
# fires for gh commands.
#
# Adapted from tasteslikegoodtheangularsvegancookbook/.claude/hooks/
# pretooluse-pr-review-nudge.sh, extended with merge guard.
#
# Fail-open: any error exits 0 so a transient failure never blocks. The
# merge guard is the exception — a failed lookup there asks, see above.
set -uo pipefail
trap 'exit 0' ERR

payload="$(cat)"
tool_name="$(printf '%s' "$payload" | jq -r '.tool_name // empty' 2>/dev/null || true)"

[ "$tool_name" = "Bash" ] || exit 0

cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"

# ===================================================================
# BLOCKING branches first — a match here must win over the informational
# nudges below even when the triggering subcommand is chained after one.
# ===================================================================

# --- gh pr view --comments redirect (wrong tool) — DENY ---
# Single regex so the --comments/-c flag is scoped to THIS `gh pr view`
# invocation: `[^&|;]*` cannot cross a command separator, so a later
# `bash -c` / `grep -c` in a compound command no longer false-positives.
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+pr[[:space:]]+view[[:space:]]([^&|;]*[[:space:]])?(--comments|-c)([[:space:]]|$)'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Use gh api instead -- gh pr view --comments misses review-body comments and suppressed co-pilot reviews","additionalContext":"WRONG TOOL: `gh pr view --comments` only shows issue-style comments, NOT inline review comments or suppressed co-pilot reviews. Use ALL THREE gh api endpoints (add `--paginate` to each so nothing past page 1 is missed): `gh api --paginate repos/{owner}/{repo}/pulls/{number}/comments` (inline diff comments), `gh api --paginate repos/{owner}/{repo}/issues/{number}/comments` (top-level conversation comments), and `gh api --paginate repos/{owner}/{repo}/pulls/{number}/reviews` (submitted review summaries -- prose feedback in a review `.body` with no inline comments appears in NONE of the others; check both `.body` and `.state`)."}}
JSON
  exit 0
fi

# --- Merge guard — checks review threads itself (D-031) ---
merge_guard_ask() {
  jq -n --arg why "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:("Merge guard could not check review threads: " + $why),additionalContext:("The merge guard could not read the review threads of this PR (" + $why + "), so it is asking instead. Before merging, check them yourself: `gh api graphql` on the `reviewThreads` of the PR must return no `isResolved: false`, and all three review surfaces must have been re-read since the last push (`gh api --paginate repos/{owner}/{repo}/pulls/{number}/comments`, `.../issues/{number}/comments`, `.../pulls/{number}/reviews`).")}}'
  exit 0
}

if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+pr[[:space:]]+merge([[:space:]]|$)'; then
  # Arguments of THIS `gh pr merge` only: `[^&|;]*` stops at a command
  # separator. Word-splitting is naive — a quoted `--body "two words"`
  # yields a stray token — so a target that does not resolve asks rather
  # than passes, and GitHub's own thread-resolution rule on `dev` is the
  # backstop either way.
  seg="$(printf '%s' "$cmd" | grep -Eo 'gh[[:space:]]+pr[[:space:]]+merge([[:space:]][^&|;]*)?' | head -n 1 || true)"
  target=""
  repo=""
  skip=0
  want_repo=0
  set -f
  # shellcheck disable=SC2086
  set -- ${seg#*merge}
  set +f
  for tok in "$@"; do
    if [ "$want_repo" -eq 1 ]; then
      repo="$tok"
      want_repo=0
      continue
    fi
    if [ "$skip" -eq 1 ]; then
      skip=0
      continue
    fi
    case "$tok" in
      -R | --repo) want_repo=1 ;;
      --repo=*) repo="${tok#--repo=}" ;;
      -b | --body | -F | --body-file | -t | --subject | -A | --author-email | --match-head-commit) skip=1 ;;
      -*) ;;
      *) [ -n "$target" ] || target="$tok" ;;
    esac
  done
  target="${target%\"}"
  target="${target#\"}"
  target="${target%\'}"
  target="${target#\'}"

  view_args=()
  [ -z "$target" ] || view_args+=("$target")
  [ -z "$repo" ] || view_args+=(-R "$repo")
  if ! pr_url="$(gh pr view "${view_args[@]}" --json url --jq .url 2>/dev/null)" || [ -z "$pr_url" ]; then
    merge_guard_ask "gh pr view did not resolve the PR"
  fi
  # https://<host>/<owner>/<name>/pull/<number>
  pr_number="${pr_url##*/}"
  pr_rest="${pr_url%/pull/*}"
  pr_name="${pr_rest##*/}"
  pr_rest="${pr_rest%/*}"
  pr_owner="${pr_rest##*/}"
  case "$pr_number" in
    '' | *[!0-9]*) merge_guard_ask "unexpected PR url $pr_url" ;;
  esac

  # shellcheck disable=SC2016
  if ! open_threads="$(gh api graphql --paginate \
    -F owner="$pr_owner" -F name="$pr_name" -F number="$pr_number" \
    -f query='query($owner:String!,$name:String!,$number:Int!,$endCursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100,after:$endCursor){pageInfo{hasNextPage endCursor} nodes{isResolved path line comments(first:1){nodes{author{login}}}}}}}}' \
    --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | "\(.path):\(.line // "outdated") (\(.comments.nodes[0].author.login // "unknown"))"' 2>/dev/null)"; then
    merge_guard_ask "the GraphQL reviewThreads query failed for PR #$pr_number"
  fi

  if [ -n "$open_threads" ]; then
    open_count="$(printf '%s\n' "$open_threads" | grep -c . || true)"
    open_list="$(printf '%s\n' "$open_threads" | head -n 20 | paste -sd ';' - | sed 's/;/; /g')"
    jq -n --arg n "$open_count" --arg pr "$pr_number" --arg list "$open_list" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:("Merge guard: PR #" + $pr + " has " + $n + " unresolved review thread(s): " + $list),additionalContext:("MERGE DENIED (D-031): PR #" + $pr + " has " + $n + " unresolved review thread(s): " + $list + ". Answer each one — a fix commit, a rebuttal verified against the file, or a deliberate not-now with the reason and a PLZG ticket for anything owed — then resolve it. Do not resolve a thread you have not answered. A thread that needs the call of the owner stays open and the PR stays unmerged.")}}'
    exit 0
  fi

  jq -n --arg pr "$pr_number" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:("Merge guard: PR #" + $pr + " has 0 unresolved review threads, so the merge is not blocked. Thread state does not cover conversation comments or review bodies: if you have not re-read `gh api --paginate repos/{owner}/{repo}/issues/{number}/comments` and `.../pulls/{number}/reviews` since your last push, and confirmed required checks are green on the head commit, do that before relying on this merge (D-031).")}}'
  exit 0
fi

# ===================================================================
# INFORMATIONAL nudges — only reached when no blocking branch matched.
# ===================================================================

# --- Reply nudge (gh pr comment/review) ---
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+pr[[:space:]]+(comment|review)([[:space:]]|$)'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"You are about to post a reply to PR review feedback. Per the PR workflow rules: if you have not already this turn, invoke the superpowers:receiving-code-review skill and evaluate this feedback with technical rigor -- verify each claim against the code, then either push a fix commit or give a concrete technical rebuttal (never performative agreement, never silently ignore). End the reply with the attribution line: _Replied by Claude on Adam's behalf_"}}
JSON
  exit 0
fi

# --- Reply nudge (gh api ...pulls/*/comments POST) ---
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+api[[:space:]]' \
  && printf '%s' "$cmd" | grep -Eq 'pulls/[0-9]+/comments' \
  && printf '%s' "$cmd" | grep -Eq '(-X[[:space:]]*POST|--method[[:space:]]*POST|-f[[:space:]]|-F[[:space:]]|--field[[:space:]]|--input[[:space:]])'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"You are about to post a reply to PR review feedback via gh api. Per the PR workflow rules: if you have not already this turn, invoke the superpowers:receiving-code-review skill and evaluate this feedback with technical rigor -- verify each claim against the code, then either push a fix commit or give a concrete technical rebuttal (never performative agreement, never silently ignore). End the reply with the attribution line: _Replied by Claude on Adam's behalf_"}}
JSON
  exit 0
fi

# --- Reading PR comments (load receiving-code-review skill) ---
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+api[[:space:]]' \
  && printf '%s' "$cmd" | grep -Eq 'pulls/[0-9]+/comments' \
  && ! printf '%s' "$cmd" | grep -Eq '(-X[[:space:]]*POST|--method[[:space:]]*POST|-f[[:space:]]|-F[[:space:]]|--field[[:space:]]|--input[[:space:]])'; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"You are reading PR review comments via the correct API method (gh api). If you have not already this turn, invoke the superpowers:receiving-code-review skill before responding to any feedback. This endpoint only returns inline diff comments -- also check `gh api --paginate repos/{owner}/{repo}/issues/{number}/comments` for top-level PR comments AND `gh api --paginate repos/{owner}/{repo}/pulls/{number}/reviews` for submitted review summaries (a COMMENTED/CHANGES_REQUESTED review can carry prose feedback in its `.body` with no inline comments; check both `.body` and `.state`). Add `--paginate` so feedback past page 1 is not missed. This is where suppressed co-pilot reviews hide -- they are real reviews that should be evaluated with the same rigor."}}
JSON
  exit 0
fi

exit 0
