#!/usr/bin/env sh
#
# check_sync.sh — is this checkout in sync with the branch it integrates into?
#
# Why this exists: on 2026-07-30 a planning session ran from a checkout 31
# commits behind origin/dev and produced three findings that were already fixed
# upstream. CLAUDE.md § "Sync the environment before anything else" states the
# rule; documentation alone does not enforce it. This script does, and the
# SessionStart hook in .claude/settings.json runs it (PLZG-114).
#
# Failure mode is deliberate. Default is WARN AND CONTINUE — always exit 0.
# A detached worktree, an offline laptop, or a sandbox without a remote must not
# hard-fail a session; a hook that blocks work gets removed, and then nothing is
# enforced at all. Use --strict where a non-zero exit is wanted (CI).
#
# Usage:
#   scripts/check_sync.sh              # warn, always exit 0
#   scripts/check_sync.sh --strict     # exit 1 if behind, or if state is unknowable
#   scripts/check_sync.sh --no-fetch   # skip the network call
#
# Environment:
#   PLZG_SKIP_FETCH=1                  # same as --no-fetch
#   PLZG_BASE_REF=origin/main          # override the branch compared against
#
# POSIX sh only — no bashisms, no dependencies beyond git. Consistent with the
# repo's stdlib-only tooling rule.

set -u

STRICT=0
FETCH=1

for arg in "$@"; do
    case "$arg" in
        --strict)   STRICT=1 ;;
        --no-fetch) FETCH=0 ;;
        -h|--help)
            # Print the header block, stopping at the first non-comment line.
            # A hardcoded line range was used here and leaked `set -u` into the
            # output when the header grew; deriving the end is drift-proof.
            awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
            exit 0
            ;;
        *)
            echo "check_sync: unknown argument: $arg" >&2
            echo "check_sync: try --help" >&2
            exit 2
            ;;
    esac
done

[ "${PLZG_SKIP_FETCH:-0}" = "1" ] && FETCH=0

# Exit according to mode. Warn mode always succeeds; strict propagates.
finish() {
    if [ "$STRICT" = "1" ]; then
        exit "$1"
    fi
    exit 0
}

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "check_sync: not a git repository — skipping sync check." >&2
    finish 1
fi

# Run from the top of *this* worktree. git rev-parse --show-toplevel resolves
# per-worktree, so a linked worktree checks itself rather than the main
# checkout. That matters: worktrees drift exactly the same way.
TOPLEVEL=$(git rev-parse --show-toplevel 2>/dev/null) || finish 1
cd "$TOPLEVEL" || finish 1

if ! git remote get-url origin >/dev/null 2>&1; then
    echo "check_sync: no 'origin' remote — cannot determine upstream state." >&2
    finish 1
fi

# Fetch BEFORE deciding what to compare against. Resolving the base ref first
# asks "does origin/dev exist locally?" of a checkout that has not talked to the
# remote yet, so on a fresh clone the answer is no and the script concludes there
# is nothing to compare against — silently, in warn mode. That shipped and was
# caught in review of PR #70 (PLZG-124).
if [ "$FETCH" = "1" ]; then
    if ! git fetch origin --quiet 2>/dev/null; then
        echo "check_sync: git fetch failed (offline?) — counts below may be stale." >&2
        # Strict callers must know they are reasoning from unrefreshed data.
        [ "$STRICT" = "1" ] && exit 1
    fi
fi

# Make a remote-tracking ref available even when the clone's refspec excludes it.
# `git clone --single-branch` (and actions/checkout@v4 by default) writes a
# refspec covering exactly one branch, so no amount of bare `git fetch origin`
# will ever produce origin/dev. Fetching the branch by name works regardless,
# leaving it in FETCH_HEAD.
resolve_ref() {
    candidate="$1"
    if git rev-parse --verify --quiet "$candidate" >/dev/null 2>&1; then
        printf '%s' "$candidate"
        return 0
    fi
    [ "$FETCH" = "1" ] || return 1
    if git fetch origin --quiet "${candidate#origin/}" 2>/dev/null &&
        git rev-parse --verify --quiet FETCH_HEAD >/dev/null 2>&1; then
        printf 'FETCH_HEAD'
        return 0
    fi
    return 1
}

# Pick what to compare against: the branch this checkout INTEGRATES INTO, which
# is not the same as the branch's own upstream.
#
# Do not reach for @{upstream} first. On any pushed feature branch it resolves to
# that branch's own remote copy, so the script would compare the branch with
# itself and report "in sync" while origin/dev raced ahead — a no-op in exactly
# the case this tool exists to catch. That shipped in the first revision of this
# script and was caught in review of PR #70; the local tests missed it because
# they only ran on dev and on a detached worktree, the two states where
# @{upstream} is absent or happens to equal origin/dev.
#
# Only when HEAD *is* an integration branch does its own upstream become the
# right answer — otherwise sitting on main would be measured against dev.
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

# BASE is what git compares against; BASE_LABEL is what the human is told. They
# differ when a ref had to be fetched by name into FETCH_HEAD, and reporting
# "FETCH_HEAD" would be useless.
if [ -n "${PLZG_BASE_REF:-}" ]; then
    BASE_LABEL="$PLZG_BASE_REF"
elif [ "$CURRENT_BRANCH" = "dev" ] || [ "$CURRENT_BRANCH" = "main" ]; then
    BASE_LABEL=$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null) \
        || BASE_LABEL="origin/$CURRENT_BRANCH"
else
    BASE_LABEL="origin/dev"
fi

BASE=$(resolve_ref "$BASE_LABEL") || BASE=""

# Last resort: whatever the remote calls its default branch — but ONLY when we
# were able to reach the remote and it genuinely has no such branch.
#
# Offline, an unresolvable base means "we could not look", not "it is not
# there", and substituting a different branch turns that into a confident
# "in sync" against something the caller never asked about. A restricted-refspec
# clone run with --no-fetch reported "in sync with origin/main" while sitting
# five commits behind dev. Reporting the wrong branch cheerfully is the failure
# this script exists to prevent, so offline now yields UNKNOWN instead.
if [ -z "$BASE" ] && [ "$FETCH" = "1" ] && [ "$BASE_LABEL" != "origin/HEAD" ]; then
    FALLBACK=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null) || FALLBACK=""
    if [ -n "$FALLBACK" ] && [ "$FALLBACK" != "$BASE_LABEL" ]; then
        BASE=$(resolve_ref "$FALLBACK") || BASE=""
        if [ -n "$BASE" ]; then
            echo "check_sync: '$BASE_LABEL' is not on origin; falling back to $FALLBACK." >&2
            BASE_LABEL="$FALLBACK"
        fi
    fi
fi

if [ -z "$BASE" ]; then
    echo "check_sync: cannot resolve '$BASE_LABEL' — not present locally and not" >&2
    echo "check_sync: fetchable from origin. This checkout's sync state is UNKNOWN," >&2
    echo "check_sync: which is not the same as being in sync." >&2
    finish 1
fi

COUNTS=$(git rev-list --left-right --count "HEAD...$BASE" 2>/dev/null) || {
    echo "check_sync: could not compare HEAD with $BASE_LABEL (unrelated histories?)." >&2
    finish 1
}

AHEAD=$(printf '%s\n' "$COUNTS" | cut -f1)
BEHIND=$(printf '%s\n' "$COUNTS" | cut -f2)

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
[ "$BRANCH" = "HEAD" ] && BRANCH="(detached at $(git rev-parse --short HEAD))"

DIRTY=""
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    DIRTY=" · uncommitted changes present"
fi

if [ "$BEHIND" -gt 0 ]; then
    echo "check_sync: $BRANCH is $BEHIND commit(s) BEHIND $BASE_LABEL (ahead $AHEAD)$DIRTY"
    echo "check_sync: this checkout does not reflect upstream. Anything you assert"
    echo "check_sync: about repository state may already be wrong. Reconcile first:"
    echo "check_sync:     git pull --ff-only origin ${BASE_LABEL#origin/}"
    finish 1
fi

echo "check_sync: $BRANCH is in sync with $BASE_LABEL (ahead $AHEAD, behind 0)$DIRTY"
exit 0
