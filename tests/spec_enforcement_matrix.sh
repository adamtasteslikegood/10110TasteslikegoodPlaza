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
# DELIBERATELY EXCLUDED: the stale-snapshot fixture. That is T5/PLZG-130's
# deliverable. T4 and T5 share this acceptance command, so shipping it here
# would satisfy T5 the moment T4 passed, having changed nothing.
#
# Usage: tests/spec_enforcement_matrix.sh    (exit 0 all pass, 1 any failure)

set -u

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(dirname "$SCRIPT_DIR")
SUT="$REPO_ROOT/scripts/validate_specs.py"
SCHEMA="$REPO_ROOT/specs/meta/spec-frontmatter.schema.json"

for required in "$SUT" "$SCHEMA"; do
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
    if [ "$rc" = 1 ] && [ "$tb" = 0 ] && [ "$hit" -ge 1 ]; then
        PASS=$((PASS + 1))
        printf '  ok   %-50s exit=1, reported\n' "$name"
    else
        FAIL=$((FAIL + 1))
        printf '  FAIL %-50s exit=%s tracebacks=%s matched=%s (want 1, 0, >=1)\n' \
            "$name" "$rc" "$tb" "$hit"
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
# The matrix
# --------------------------------------------------------------------------

echo "Building fixtures..."
build_base "$WORK/base"

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
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
