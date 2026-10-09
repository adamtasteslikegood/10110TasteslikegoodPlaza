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
#    checks the PR's review threads itself (`D-031`, `PLZG-278`).
#    - DENY: any unresolved thread, on any merge in the command.
#    - PASS (no decision): every merge targets `dev` and has no
#      unresolved thread. Comes with a reminder about the two review
#      surfaces thread state cannot see.
#    - ASK: anything it cannot be sure of — a PR it cannot resolve, a
#      failed query, quoting or expansion it does not parse, or a base
#      branch other than `dev`, which `D-031` does not cover.
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
# `gh`, optional -R/--repo before the subcommand, then `pr merge`.
MG_RE='gh([[:space:]]+(-R|--repo)([[:space:]]+|=)[^[:space:]&|;]+)*[[:space:]]+pr[[:space:]]+merge'
MG_BASE='dev'

merge_guard_ask() {
  jq -n --arg why "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:("Merge guard is not deciding this merge: " + $why),additionalContext:("The merge guard is asking instead of deciding (" + $why + "). Before merging, check yourself: `gh api graphql` on the `reviewThreads` of the PR must return no `isResolved: false`, and all three review surfaces must have been re-read since the last push (`gh api --paginate repos/{owner}/{repo}/pulls/{number}/comments`, `.../issues/{number}/comments`, `.../pulls/{number}/reviews`). D-031 covers PRs into `dev` only.")}}'
  exit 0
}

# Sets mg_pr / mg_open / mg_err for ONE `gh ... pr merge ...` segment.
merge_guard_inspect() {
  local seg="$1" target="" repo="" skip=0 want_repo=0 seen_pr=0 seen_merge=0 tok view pr_url pr_base pr_rest pr_name pr_owner
  local -a view_args=()
  mg_pr=""
  mg_open=""
  mg_err=""
  # The segment is re-split on whitespace, which is only sound when it has
  # no quoting or expansion. With either, a word from inside a quoted
  # value can pose as the PR target and the guard would clear a different
  # PR from the one being merged — so it does not decide those.
  case "$seg" in
    *[\"\'\\\$\`\(\)\{\}\<\>]*)
      mg_err="the merge command uses quoting or expansion the guard does not parse"
      return 0
      ;;
  esac
  set -f
  # shellcheck disable=SC2086
  set -- ${seg#*gh}
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
      pr) if [ "$seen_pr" -eq 0 ]; then seen_pr=1; elif [ -z "$target" ]; then target="$tok"; fi ;;
      merge) if [ "$seen_merge" -eq 0 ]; then seen_merge=1; elif [ -z "$target" ]; then target="$tok"; fi ;;
      *) [ -n "$target" ] || target="$tok" ;;
    esac
  done

  [ -z "$target" ] || view_args+=("$target")
  [ -z "$repo" ] || view_args+=(-R "$repo")
  if ! view="$(gh pr view "${view_args[@]}" --json url,baseRefName --jq '.url + " " + .baseRefName' 2>/dev/null)" || [ -z "$view" ]; then
    mg_err="gh pr view did not resolve the PR for: $seg"
    return 0
  fi
  pr_url="${view%% *}"
  pr_base="${view#* }"
  # https://<host>/<owner>/<name>/pull/<number>
  mg_pr="${pr_url##*/}"
  pr_rest="${pr_url%/pull/*}"
  pr_name="${pr_rest##*/}"
  pr_rest="${pr_rest%/*}"
  pr_owner="${pr_rest##*/}"
  case "$mg_pr" in
    '' | *[!0-9]*)
      mg_err="unexpected PR url $pr_url"
      return 0
      ;;
  esac

  # shellcheck disable=SC2016
  if ! mg_open="$(gh api graphql --paginate \
    -F owner="$pr_owner" -F name="$pr_name" -F number="$mg_pr" \
    -f query='query($owner:String!,$name:String!,$number:Int!,$endCursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100,after:$endCursor){pageInfo{hasNextPage endCursor} nodes{isResolved path line comments(first:1){nodes{author{login}}}}}}}}' \
    --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | "\(.path):\(.line // "outdated") (\(.comments.nodes[0].author.login // "unknown"))"' 2>/dev/null)"; then
    mg_open=""
    mg_err="the GraphQL reviewThreads query failed for PR #$mg_pr"
    return 0
  fi
  # Unresolved threads deny whatever the base; only a clean PR needs the
  # base checked, because passing it is what D-031 has to authorise.
  if [ -z "$mg_open" ] && [ "$pr_base" != "$MG_BASE" ]; then
    mg_err="PR #$mg_pr targets \`$pr_base\`, and D-031 covers merges into \`$MG_BASE\` only"
  fi
  return 0
}

if printf '%s' "$cmd" | grep -Eq "${MG_RE}([[:space:]]|\$)"; then
  # From here an unexpected failure must not fall through to the
  # fail-open trap: that would let a merge past with no decision at all.
  trap 'merge_guard_ask "the guard hit an internal error"' ERR
  # One hook call covers the whole command string, so EVERY merge in it is
  # checked: `[^&|;]*` ends a segment at a command separator, and a chain
  # of two merges yields two segments. One blocked merge blocks the call;
  # one merge the guard cannot vouch for makes the call ask.
  mg_denied=""
  mg_asked=""
  mg_clean=""
  mg_segments="$(printf '%s' "$cmd" | grep -Eo "${MG_RE}([[:space:]][^&|;]*)?" || true)"
  while IFS= read -r mg_seg; do
    [ -n "$mg_seg" ] || continue
    merge_guard_inspect "$mg_seg"
    if [ -n "$mg_open" ]; then
      # awk reads its whole input, so no SIGPIPE under `pipefail`.
      mg_total="$(printf '%s\n' "$mg_open" | awk 'NF{n++} END{print n+0}')"
      mg_list="$(printf '%s\n' "$mg_open" | awk 'NF && ++n<=20{printf "%s%s", (n>1?"; ":""), $0}')"
      if [ "$mg_total" -gt 20 ]; then
        mg_list="$mg_list; ... first 20 of $mg_total shown, query reviewThreads for the rest"
      fi
      mg_denied="${mg_denied:+$mg_denied | }PR #$mg_pr has $mg_total unresolved review thread(s): $mg_list"
    elif [ -n "$mg_err" ]; then
      mg_asked="${mg_asked:+$mg_asked; }$mg_err"
    else
      mg_clean="${mg_clean:+$mg_clean, }#$mg_pr"
    fi
  done <<<"$mg_segments"

  if [ -n "$mg_denied" ]; then
    jq -n --arg d "$mg_denied" --arg a "$mg_asked" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:("Merge guard: " + $d),additionalContext:("MERGE DENIED (D-031): " + $d + (if $a == "" then "" else " | Also not vouched for: " + $a end) + ". Answer each thread — a fix commit, a rebuttal verified against the file, or a deliberate not-now with the reason and a PLZG ticket for anything owed — then resolve it. Do not resolve a thread you have not answered. A thread that needs the call of the owner stays open and the PR stays unmerged.")}}'
    exit 0
  fi
  if [ -n "$mg_asked" ] || [ -z "$mg_clean" ]; then
    merge_guard_ask "${mg_asked:-no merge target could be parsed}"
  fi
  jq -n --arg pr "$mg_clean" --arg base "$MG_BASE" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:("Merge guard: PR " + $pr + " into `" + $base + "`: 0 unresolved review threads, so the merge is not blocked. Thread state does not cover conversation comments or review bodies: if you have not re-read `gh api --paginate repos/{owner}/{repo}/issues/{number}/comments` and `.../pulls/{number}/reviews` since your last push, and confirmed required checks are green on the head commit, do that before relying on this merge (D-031).")}}'
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
