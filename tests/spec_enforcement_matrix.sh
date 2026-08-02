#!/usr/bin/env sh
#
# spec_enforcement_matrix.sh — the non-vacuity matrix for the D-027 enforcement
# axis in scripts/validate_specs.py.
#
# WHY THIS FILE EXISTS
#
# The five enforcement checks can all pass while checking nothing, and during
# PLZG-134 three of them did. `python3 scripts/validate_specs.py` exited 0 the
# whole time:
#
#   * check 5 matched `weakest_claim` against the raw file text -- which contains
#     the frontmatter the claim was read from -- so the line matched itself and a
#     fabricated quote passed;
#   * `if jobs and job not in jobs` skipped the job-existence rule entirely
#     whenever ci.yml was missing or merely reindented past the parser;
#   * the enum vocabulary was not bound to the implemented semantics, so a fifth
#     value would have validated green with nothing checking documents using it.
#
# Fourteen review findings were raised across that task and all fourteen upheld.
# A green validator was the evidence for none of them. That is the same failure
# tests/smoke_test.tscn sat in until v0.2.8, and this file is the answer to it:
# every case below asserts the validator FAILS, so a check that stops checking
# turns this matrix red instead of staying quietly green.
#
# HOW IT BUILDS FIXTURES
#
# It writes a minimal but genuinely valid three-document doc set into a temp
# directory, confirms that baseline exits 0, then re-copies it per case and
# breaks exactly one thing. Nothing here touches the working repository, and
# there is no network.
#
# scripts/validate_specs.py and specs/meta/spec-frontmatter.schema.json are
# COPIED IN rather than reinvented: they are the system under test and its
# published contract, and a matrix asserting against a hand-written imitation of
# either would prove nothing about the real ones. The script must be copied
# rather than invoked in place because it derives REPO_ROOT from its own
# location.
#
# THE STALE-SNAPSHOT FIXTURES ARE NOW HERE, added by T5/PLZG-130. They were
# deliberately EXCLUDED when T4 shipped this file: T4 and T5 share this
# acceptance command, so shipping them early would have satisfied T5 the moment
# T4 passed, having changed nothing. That split did its job -- reverting only
# T5's script change, keeping its fixtures, leaves seven cases red.
#
# Usage: tests/spec_enforcement_matrix.sh    (exit 0 all pass, 1 any failure)

set -u

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(dirname "$SCRIPT_DIR")
SUT="$REPO_ROOT/scripts/validate_specs.py"
SCHEMA="$REPO_ROOT/specs/meta/spec-frontmatter.schema.json"
COORD="$REPO_ROOT/scripts/validate_delivery_coordinates.py"

for required in "$SUT" "$SCHEMA" "$COORD"; do
    if [ ! -f "$required" ]; then
        echo "FATAL: $required is missing" >&2
        exit 1
    fi
done

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM

PASS=0
FAIL=0

# --------------------------------------------------------------------------
# Fixture construction
# --------------------------------------------------------------------------

build_base() {
    base=$1
    mkdir -p "$base/scripts" "$base/specs/meta" "$base/docs" "$base/.github/workflows"
    cp "$SUT" "$base/scripts/validate_specs.py"
    cp "$SCHEMA" "$base/specs/meta/spec-frontmatter.schema.json"

    # Two job names, one of each gate type, so `live` and `snapshot` are both
    # exercised against a real lookup.
    cat > "$base/.github/workflows/ci.yml" <<'CI'
name: CI
on: [push]
jobs:
  validate-specs:
    name: Validate Specs
    runs-on: ubuntu-latest
    steps:
      - name: Check out
        run: echo fixture
  check-sync-matrix:
    name: Check Sync Matrix
    runs-on: ubuntu-latest
    steps:
      - name: Run
        run: echo fixture
CI

    cat > "$base/specs/meta/META-SPEC.md" <<'DOC'
---
doc_id: META-SPEC
title: Fixture constitution
tier: 0
authority: constitution
status: ACTIVE
doc_set_version: 9.9.9
last_updated: 2026-08
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: this fixture constitution asserts one checkable thing
---

# Fixture constitution

this fixture constitution asserts one checkable thing
DOC

    # The `n/a` document. Also the vehicle for the widened job-existence case:
    # PLZG-134 extended that rule from enforced/asserted to EVERY enforcement
    # value, and an `asserted` fixture cannot prove it, having failed before the
    # widening too.
    cat > "$base/docs/storyboard.md" <<'DOC'
---
doc_id: STORYBOARD-W1
title: Fixture concept source
tier: 1
authority: concept
status: ACTIVE
doc_set_version: 9.9.9
last_updated: 2026-08
enforcement: n/a
---

# Fixture concept source

Narrative only. Asserts nothing about the repository.
DOC

    cat > "$base/docs/subject.md" <<'DOC'
---
doc_id: SUBJECT
title: Fixture subject document
tier: 2
authority: implementation
status: ACTIVE
doc_set_version: 9.9.9
last_updated: 2026-08
enforcement: asserted
gates: [Validate Specs:live, Check Sync Matrix:snapshot]
weakest_claim: the subject document claims this sentence is true
---

# Fixture subject document

the subject document claims this sentence is true
DOC

    cat > "$base/specs/meta/doc-registry.json" <<'REG'
{
  "doc_set_version": "9.9.9",
  "documents": [
    { "doc_id": "META-SPEC", "path": "specs/meta/META-SPEC.md", "tier": 0,
      "authority": "constitution", "status": "ACTIVE" },
    { "doc_id": "STORYBOARD-W1", "path": "docs/storyboard.md", "tier": 1,
      "authority": "concept", "status": "ACTIVE",
      "enforcement_na_reason": "Narrative only; makes no claim about state." },
    { "doc_id": "SUBJECT", "path": "docs/subject.md", "tier": 2,
      "authority": "implementation", "status": "ACTIVE" }
  ],
  "exempt": []
}
REG
}

# --------------------------------------------------------------------------
# Case runner
# --------------------------------------------------------------------------

# A fresh copy per case, so one mutation can never leak into the next.
new_case() {
    rm -rf "$WORK/case"
    cp -R "$WORK/base" "$WORK/case"
    printf '%s' "$WORK/case"
}

# Every broken fixture must FAIL, and must fail as a reported problem rather
# than as a crash. A traceback is a defect even when the exit code is right:
# it aborts before queued problems print, so the reader sees a stack trace
# instead of the finding. Three TypeErrors were found this way in PLZG-134.
# THE MESSAGE IS ASSERTED, NOT JUST THE EXIT CODE, and the difference is the
# point. Several checks overlap: disabling check 4's missing-reason branch still
# fails the fixture, because the sibling branch catches _MISSING as "not a
# string" -- right outcome, wrong reason, and an exit-code-only matrix cannot
# tell them apart. A case that passes because SOME check fired proves nothing
# about the check it is named after.
expect_fail() { # name, needle, dir
    name=$1 needle=$2 dir=$3
    out=$( cd "$dir" && python3 scripts/validate_specs.py 2>&1 )
    rc=$?
    tb=$( printf '%s' "$out" | grep -c 'Traceback' )
    hit=$( printf '%s' "$out" | grep -cF "$needle" )
    # The banner is required as well as the needle. Exit 1 with no "Traceback"
    # is NOT enough to prove the validator ran: a SyntaxError in
    # validate_specs.py exits 1 and prints no traceback line at all -- just the
    # file, the offending source line and "SyntaxError". If that echoed source
    # line happened to contain the needle, the case would count as passed while
    # the validator never produced a report. Demanding the completed banner
    # means only a finished validation run can satisfy a failure case.
    banner=$( printf '%s' "$out" | grep -c 'Spec validation FAILED' )
    if [ "$rc" = 1 ] && [ "$tb" = 0 ] && [ "$hit" -ge 1 ] && [ "$banner" -ge 1 ]; then
        PASS=$((PASS + 1))
        printf '  ok   %-50s exit=1, reported\n' "$name"
    else
        FAIL=$((FAIL + 1))
        printf '  FAIL %-50s exit=%s tb=%s matched=%s banner=%s\n' \
            "$name" "$rc" "$tb" "$hit" "$banner"
        printf '         expected to contain: %s\n' "$needle"
        printf '%s\n' "$out" | sed 's/^/         | /' | head -6
    fi
}

expect_pass() { # name, dir
    name=$1 dir=$2
    out=$( cd "$dir" && python3 scripts/validate_specs.py 2>&1 )
    rc=$?
    if [ "$rc" = 0 ]; then
        PASS=$((PASS + 1))
        printf '  ok   %-50s exit=0\n' "$name"
    else
        FAIL=$((FAIL + 1))
        printf '  FAIL %-50s expected exit=0, got %s\n' "$name" "$rc"
        printf '%s\n' "$out" | sed 's/^/         | /' | head -8
    fi
}

# Rewrite one frontmatter key in a fixture document.
set_key() { # file, key, value
    sed -i.bak "s|^$2: .*|$2: $3|" "$1" && rm -f "$1.bak"
}

drop_key() { # file, key
    sed -i.bak "/^$2: /d" "$1" && rm -f "$1.bak"
}

# doc-registry.json is edited as JSON, never with sed: deleting a line leaves a
# trailing comma, the run dies on invalid JSON, and the case then proves the
# editor broke rather than that the check works.
registry_py() { # dir, python-body
    python3 -c "
import json, pathlib, sys
p = pathlib.Path('$1/specs/meta/doc-registry.json')
r = json.loads(p.read_text())
docs = {d['doc_id']: d for d in r['documents']}
$2
p.write_text(json.dumps(r, indent=2) + '\n')
"
}


# --------------------------------------------------------------------------
# Clause (b): snapshot freshness (T5 / PLZG-130)
# --------------------------------------------------------------------------
#
# A SECOND system under test, deliberately in this file rather than its own.
# T4 and T5 share `tests/spec_enforcement_matrix.sh` as their acceptance
# command, so T5's fixture has to live where T5's acceptance runs. T4 shipped
# WITHOUT these cases on purpose: had it included them, T5 would have been
# satisfied the moment T4 passed, having changed nothing.
#
# The fixture is a bare snapshot plus the script -- clause (a) scans governed
# trees for `TO` references and finds none here, so it passes trivially and
# leaves clause (b) as the only thing under test.

build_coord_base() {
    base=$1
    mkdir -p "$base/scripts" "$base/data" "$base/.git"
    # The script refuses to run outside a checkout, so the fixture needs a .git
    # marker. A directory is enough -- nothing here runs git, and creating a real
    # repository would be slower and no more honest.
    cp "$COORD" "$base/scripts/validate_delivery_coordinates.py"
    cat > "$base/data/plzg-flow-snapshot.json" <<'SNAP'
{
  "mode": "flow",
  "project": "PLZG",
  "as_of": "SNAP_AS_OF",
  "counts": { "total": 10, "done": 4, "wip": 1 },
  "work_item_age": [ { "key": "PLZG-1", "created": "SNAP_START", "age_days": 1 } ],
  "aging_wip_alerts": [],
  "wip_limit": 3,
  "sprint": { "name": "Fixture Sprint", "board": 169, "id": 99,
              "start": "SNAP_START", "end": "SNAP_END" }
}
SNAP
    # Dates are stamped at run time, never hardcoded: a fixture with fixed dates
    # is a time bomb -- it passes until the day its window closes, then fails
    # for a reason that has nothing to do with the code.
    today=$(date -u +%Y-%m-%d)
    start=$(date -u -d '2 days ago' +%Y-%m-%d 2>/dev/null || date -u -v-2d +%Y-%m-%d)
    end=$(date -u -d '10 days' +%Y-%m-%d 2>/dev/null || date -u -v+10d +%Y-%m-%d)
    sed -i.bak "s|SNAP_AS_OF|${today}T00:00:00+00:00|; s|SNAP_START|$start|g; s|SNAP_END|$end|" \
        "$base/data/plzg-flow-snapshot.json"
    rm -f "$base/data/plzg-flow-snapshot.json.bak"
}

new_coord_case() {
    rm -rf "$WORK/coord"
    cp -R "$WORK/coordbase" "$WORK/coord"
    printf '%s' "$WORK/coord"
}

snapshot_py() { # dir, python-body operating on `s`
    python3 -c "
import json, pathlib
p = pathlib.Path('$1/data/plzg-flow-snapshot.json')
s = json.loads(p.read_text())
$2
p.write_text(json.dumps(s, indent=2) + '\n')
"
}

coord_expect() { # name, expected_exit, needle, dir
    name=$1 want=$2 needle=$3 dir=$4
    out=$( cd "$dir" && python3 scripts/validate_delivery_coordinates.py 2>&1 )
    rc=$?
    tb=$( printf '%s' "$out" | grep -c 'Traceback' )
    if [ -n "$needle" ]; then
        hit=$( printf '%s' "$out" | grep -cF "$needle" )
    else
        hit=1
    fi
    if [ "$rc" = "$want" ] && [ "$tb" = 0 ] && [ "$hit" -ge 1 ]; then
        PASS=$((PASS + 1))
        printf '  ok   %-50s exit=%s\n' "$name" "$rc"
    else
        FAIL=$((FAIL + 1))
        printf '  FAIL %-50s exit=%s tb=%s matched=%s (want %s)\n' "$name" "$rc" "$tb" "$hit" "$want"
        printf '%s\n' "$out" | sed 's/^/         | /' | head -5
    fi
}

# --------------------------------------------------------------------------
# The matrix
# --------------------------------------------------------------------------

echo "Building fixtures..."
build_base "$WORK/base"
build_coord_base "$WORK/coordbase"

echo
echo "baseline — a valid set must pass, or every case below is meaningless"
d=$(new_case); expect_pass "unmodified three-document set" "$d"

echo
echo "check 1 — enforcement declared, absence fatal"
d=$(new_case); drop_key "$d/docs/subject.md" enforcement
expect_fail "enforcement absent" "declares no enforcement value" "$d"
d=$(new_case); set_key "$d/docs/subject.md" enforcement proven
expect_fail "enforcement outside the published enum" "is not one of" "$d"
# Absence is caught TWICE -- by the schema's `required` and by check 1 in
# validate_specs.py -- so the case above passes even with check 1 disabled and
# proves only the schema. This case drops `enforcement` from `required` in the
# fixture's schema, leaving check 1 as the only thing that can catch it. Without
# this, "the doubling is real" would be an assertion rather than a test.
d=$(new_case)
python3 -c "
import json, pathlib
p = pathlib.Path('$d/specs/meta/spec-frontmatter.schema.json')
s = json.loads(p.read_text())
s['required'] = [k for k in s['required'] if k != 'enforcement']
p.write_text(json.dumps(s, indent=2) + '\n')
"
drop_key "$d/docs/subject.md" enforcement
expect_fail "enforcement absent, schema not requiring it" "declares no enforcement value" "$d"

echo
echo "check 2 — gates present, well formed, naming real CI jobs"
d=$(new_case); drop_key "$d/docs/subject.md" gates
expect_fail "asserted with no gates" "declares no gates" "$d"
d=$(new_case); set_key "$d/docs/subject.md" gates "[Nonexistent Job:live]"
expect_fail "gate names a job absent from ci.yml" "which is not a job in" "$d"
# The widened rule (PLZG-134). MUST be on a non-asserted document: an asserted
# fixture failed before the widening too, so it proves the old behaviour.
d=$(new_case)
printf 'gates: [Nonexistent Job:live]\n' >> /dev/null
sed -i.bak 's|^enforcement: n/a|enforcement: n/a\ngates: [Nonexistent Job:live]|' "$d/docs/storyboard.md"
rm -f "$d/docs/storyboard.md.bak"
expect_fail "fake job on an n/a doc (widened rule)" "which is not a job in" "$d"
d=$(new_case); set_key "$d/docs/subject.md" gates "[Validate Specs]"
expect_fail "gate carries no type" "does not match" "$d"
d=$(new_case); set_key "$d/docs/subject.md" gates "[Validate Specs:maybe]"
expect_fail "gate type outside the vocabulary" "does not match" "$d"
d=$(new_case); set_key "$d/docs/subject.md" gates "[{job: Validate Specs, type: live}]"
expect_fail "gates as a misparsing inline object" "does not match" "$d"
d=$(new_case); set_key "$d/docs/subject.md" gates "42"
expect_fail "gates as an int (must not TypeError)" "declares a malformed gates value" "$d"
d=$(new_case); set_key "$d/docs/subject.md" gates "some-string"
expect_fail "gates as a bare string (must not walk chars)" "declares a malformed gates value" "$d"

echo
echo "check 3 — enforced requires a live gate (D-027 rule 4)"
d=$(new_case)
set_key "$d/docs/subject.md" enforcement enforced
set_key "$d/docs/subject.md" gates "[Check Sync Matrix:snapshot]"
expect_fail "enforced backed only by a snapshot gate" "declares no 'live' gate" "$d"

echo
echo "check 4 — n/a carries a registry reason, and nothing else does"
d=$(new_case); registry_py "$d" "docs['STORYBOARD-W1'].pop('enforcement_na_reason', None)"
expect_fail "n/a document with no registry reason" "carries no enforcement_na_reason" "$d"
d=$(new_case); registry_py "$d" "docs['STORYBOARD-W1']['enforcement_na_reason'] = '   '"
expect_fail "n/a reason present but blank" "declares enforcement_na_reason" "$d"
d=$(new_case); registry_py "$d" "docs['STORYBOARD-W1']['enforcement_na_reason'] = 42"
expect_fail "n/a reason non-string (must not AttributeError)" "declares enforcement_na_reason" "$d"
d=$(new_case); registry_py "$d" "docs['SUBJECT']['enforcement_na_reason'] = 'leftover'"
expect_fail "stray reason on a non-n/a document" "still carries an enforcement_na_reason" "$d"
d=$(new_case); registry_py "$d" "docs['SUBJECT']['enforcement_na_reason'] = ''"
expect_fail "blank leftover reason on a non-n/a document" "still carries an enforcement_na_reason" "$d"

echo
echo "check 5 — weakest_claim appears verbatim in the BODY"
# The case the whole file exists for. Matching against the raw file passes
# always, because the frontmatter holding the claim is part of that text.
d=$(new_case); set_key "$d/docs/subject.md" weakest_claim "a sentence that appears nowhere in this document"
expect_fail "fabricated quote (the self-match vacuity)" "does not appear" "$d"
d=$(new_case); drop_key "$d/docs/subject.md" weakest_claim
expect_fail "asserted with no weakest_claim" "declares no weakest_claim" "$d"
d=$(new_case); set_key "$d/docs/subject.md" weakest_claim "42"
expect_fail "weakest_claim as an int (must not TypeError)" "declares a non-string weakest_claim" "$d"
d=$(new_case); set_key "$d/docs/subject.md" weakest_claim '"   "'
expect_fail "weakest_claim whitespace only" "declares no weakest_claim" "$d"

echo
echo "cross-file — the checks must not disable themselves silently"
# Not merely a missing ci.yml: reindenting is the realistic case, and it left
# job-existence checking nothing while the run still exited 0.
d=$(new_case); sed -i.bak 's|^    name: |    nameX: |' "$d/.github/workflows/ci.yml"
rm -f "$d/.github/workflows/ci.yml.bak"
expect_fail "ci.yml reindented past the job-name parser" "no job names could be read" "$d"
d=$(new_case); rm -f "$d/.github/workflows/ci.yml"
expect_fail "ci.yml missing entirely" "no job names could be read" "$d"
d=$(new_case)
python3 -c "
import json, pathlib
p = pathlib.Path('$d/specs/meta/spec-frontmatter.schema.json')
s = json.loads(p.read_text())
s['properties']['enforcement']['enum'].append('stale')
p.write_text(json.dumps(s, indent=2) + '\n')
"
expect_fail "schema publishes a value with no semantics" "publishes enforcement values" "$d"

echo
echo "clause (b) — snapshot freshness and honesty (T5/PLZG-130)"
d=$(new_coord_case); coord_expect "fresh snapshot, wip=1" 0 "" "$d"
# The point of the owner ruling: an honest zero is not a failure. A gate that
# demands someone be mid-task is a gate that rewards a fake transition.
d=$(new_coord_case); snapshot_py "$d" "s['counts']['wip'] = 0; s['work_item_age'] = []"
coord_expect "HONEST ZERO wip must pass" 0 "" "$d"
d=$(new_coord_case); snapshot_py "$d" "s['sprint']['start'] = '2026-01-01'; s['sprint']['end'] = '2026-01-14'; s['as_of'] = '2026-01-05T00:00:00+00:00'"
coord_expect "snapshot describing a finished sprint" 1 "describes a finished sprint" "$d"
d=$(new_coord_case); snapshot_py "$d" "s['as_of'] = '2020-01-01T00:00:00+00:00'"
coord_expect "as_of outside its declared window" 1 "falls outside the sprint window" "$d"
d=$(new_coord_case); snapshot_py "$d" "s['counts']['wip'] = 3"
coord_expect "wip claims more items than it names" 1 "must name it" "$d"
d=$(new_coord_case); snapshot_py "$d" "s.pop('as_of')"
coord_expect "as_of missing" 1 "as_of is missing" "$d"
d=$(new_coord_case); snapshot_py "$d" "s.pop('sprint')"
coord_expect "sprint window missing" 1 "cannot be dated against a sprint window" "$d"
# A truthy non-dict sprint used to reach .get() and raise AttributeError.
d=$(new_coord_case); snapshot_py "$d" "s['sprint'] = 'unknown'"
coord_expect "sprint present but not an object" 1 "cannot be dated against a sprint window" "$d"
# A full-timestamp end must be the boundary AS GIVEN. Adding a day to it kept
# snapshots valid for 24 hours past expiry.
#
# The window has to straddle NOW for this to discriminate: `end` is three hours
# ago, so the correct boundary has passed and the buggy one (end + 1 day) has
# not. A fixture with `end` weeks in the past fails under BOTH versions and
# proves nothing -- the first draft of this case did exactly that, and was
# caught by reverting the fix and watching the matrix stay green.
d=$(new_coord_case)
tstart=$(date -u -d '5 days ago' +%Y-%m-%d 2>/dev/null || date -u -v-5d +%Y-%m-%d)
tend=$(date -u -d '3 hours ago' +%Y-%m-%dT%H:%M:%S+00:00 2>/dev/null || date -u -v-3H +%Y-%m-%dT%H:%M:%S+00:00)
tasof=$(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%S+00:00 2>/dev/null || date -u -v-1d +%Y-%m-%dT%H:%M:%S+00:00)
snapshot_py "$d" "s['sprint']['start'] = '$tstart'; s['sprint']['end'] = '$tend'; s['as_of'] = '$tasof'"
coord_expect "timestamp end is the boundary, not end+1d" 1 "describes a finished sprint" "$d"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
