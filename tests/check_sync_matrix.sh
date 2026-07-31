#!/usr/bin/env sh
#
# check_sync_matrix.sh — the regression matrix for scripts/check_sync.sh.
#
# Three defects have been found in that script by review rather than by its own
# tests: fallback priority (PLZG-122), a stale CHANGELOG claim (PLZG-123), and
# base-ref resolution ordering (PLZG-124). All three sat within the same dozen
# lines, and each got through because the manual testing covered the states
# where the bug happened to be invisible.
#
# This file exists so "the matrix was run" is a fact about the repository rather
# than a sentence in a commit message. It builds its own fixtures -- a bare
# origin with main and dev, plus full and single-branch clones -- so it needs no
# network and does not touch the working repository.
#
# Usage: tests/check_sync_matrix.sh    (exit 0 all pass, 1 any failure)

set -u

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(dirname "$SCRIPT_DIR")
SUT="$REPO_ROOT/scripts/check_sync.sh"

if [ ! -x "$SUT" ]; then
    echo "FATAL: $SUT is missing or not executable" >&2
    exit 1
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM

PASS=0
FAIL=0

# Keep the fixtures' git identity local so the runner's config is irrelevant.
git_q() { git -c user.email=t@example.com -c user.name=t -c commit.gpgsign=false "$@"; }

report() { # name, expected, actual
    if [ "$2" = "$3" ]; then
        PASS=$((PASS + 1))
        printf '  ok   %-46s %s\n' "$1" "$3"
    else
        FAIL=$((FAIL + 1))
        printf '  FAIL %-46s expected %s, got %s\n' "$1" "$2" "$3"
    fi
}

expect_exit() { # name, expected_code, dir, args...
    name=$1 expected=$2 dir=$3
    shift 3
    ( cd "$dir" && "$SUT" "$@" >/dev/null 2>&1 )
    report "$name" "exit=$expected" "exit=$?"
}

expect_output() { # name, needle, dir, args...
    name=$1 needle=$2 dir=$3
    shift 3
    out=$( cd "$dir" && "$SUT" "$@" 2>&1 )
    case "$out" in
        *"$needle"*) PASS=$((PASS + 1)); printf '  ok   %-46s matched %s\n' "$name" "'$needle'" ;;
        *) FAIL=$((FAIL + 1)); printf '  FAIL %-46s no %s in: %s\n' "$name" "'$needle'" "$out" ;;
    esac
}

# ---------------------------------------------------------------- fixtures ---
ORIGIN="$WORK/origin.git"
git_q init -q --bare "$ORIGIN"

SEED="$WORK/seed"
git_q init -q -b main "$SEED"
mkdir -p "$SEED/scripts"
cp "$SUT" "$SEED/scripts/check_sync.sh"
( cd "$SEED" && echo seed > f.txt && git_q add -A && git_q commit -q -m "seed" )
( cd "$SEED" && git_q remote add origin "$ORIGIN" && git_q push -q -u origin main )
# dev advances beyond main by 5 commits.
( cd "$SEED" && git_q checkout -q -b dev )
i=1
while [ "$i" -le 5 ]; do
    ( cd "$SEED" && echo "d$i" >> f.txt && git_q add -A && git_q commit -q -m "dev $i" )
    i=$((i + 1))
done
( cd "$SEED" && git_q push -q -u origin dev )

FULL="$WORK/full"
git_q clone -q "$ORIGIN" "$FULL"

# The shape `git clone --single-branch` and actions/checkout@v4 produce: a
# refspec covering exactly one branch, so origin/dev can never arrive via a
# bare `git fetch origin`. This is the PLZG-124 fixture.
SINGLE="$WORK/single"
git_q clone -q --single-branch --branch main "$ORIGIN" "$SINGLE"

echo "check_sync regression matrix"
echo

# --------------------------------------------------------- PLZG-124 cases ---
echo "restricted-refspec clone (the PLZG-124 regression)"
( cd "$SINGLE" && git_q checkout -q -b feature/probe )
expect_output "feature branch sees it is behind dev" "BEHIND origin/dev" "$SINGLE"
expect_output "and names the real gap"               "5 commit(s)"       "$SINGLE"
expect_exit   "warn mode still exits 0"           0 "$SINGLE"
expect_exit   "strict mode exits 1"               1 "$SINGLE" --strict
# Offline it cannot know -- and must not claim to.
expect_output "offline reports UNKNOWN, not in sync" "UNKNOWN" "$SINGLE" --no-fetch
expect_exit   "offline warn exits 0"              0 "$SINGLE" --no-fetch
expect_exit   "offline strict exits 1"            1 "$SINGLE" --no-fetch --strict

# ------------------------------------------------------- PLZG-122 cases ---
echo
echo "base-ref priority (the PLZG-122 regression)"
( cd "$FULL" && git_q checkout -q -b feature/pushed dev~3 )
( cd "$FULL" && git_q push -q -u origin feature/pushed )
# Its own upstream is origin/feature/pushed; comparing against that would
# always report "in sync". It must compare against origin/dev instead.
expect_output "pushed feature branch compares vs dev" "origin/dev" "$FULL" --no-fetch
expect_output "and reports the real gap"             "BEHIND"     "$FULL" --no-fetch

echo
echo "integration branches and overrides"
( cd "$FULL" && git_q checkout -q dev )
expect_output "on dev, compares vs origin/dev"  "in sync with origin/dev" "$FULL" --no-fetch
( cd "$FULL" && git_q checkout -q main )
expect_output "on main, compares vs origin/main" "origin/main"            "$FULL" --no-fetch
( cd "$FULL" && git_q checkout -q -b release/9.9 dev~2 )
expect_output "release branch defaults to dev"   "origin/dev"             "$FULL" --no-fetch
PLZG_BASE_REF=origin/main
export PLZG_BASE_REF
expect_output "PLZG_BASE_REF overrides the base"  "origin/main"            "$FULL" --no-fetch
unset PLZG_BASE_REF

echo
echo "degraded environments must warn, never hard-fail a session"
NOREPO="$WORK/norepo"
mkdir -p "$NOREPO"
expect_exit "outside a git repo, warn"   0 "$NOREPO"
expect_exit "outside a git repo, strict" 1 "$NOREPO" --strict
NOORIGIN="$WORK/noorigin"
git_q init -q "$NOORIGIN"
expect_exit "no origin remote, warn"     0 "$NOORIGIN"
expect_exit "no origin remote, strict"   1 "$NOORIGIN" --strict

echo
echo "argument handling"
expect_exit   "unknown argument exits 2" 2 "$FULL" --bogus
expect_output "--help does not leak code" "POSIX sh only" "$FULL" --help
help_tail=$( cd "$FULL" && "$SUT" --help 2>&1 | tail -1 )
case "$help_tail" in
    *"set -u"*) FAIL=$((FAIL + 1)); printf '  FAIL %-46s help leaked "set -u"\n' "--help stops at the header" ;;
    *) PASS=$((PASS + 1)); printf '  ok   %-46s no code leaked\n' "--help stops at the header" ;;
esac

echo
echo "----------------------------------------------------------"
printf 'passed %d, failed %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
