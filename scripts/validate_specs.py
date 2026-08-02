#!/usr/bin/env python3
"""Validate the 10110 TastesLike Plaza governed document set.

The meta layer in ``specs/meta/`` declares which document wins when two
disagree. This script is what makes that declaration real: it reads the
published contract (``spec-frontmatter.schema.json``) and the published index
(``doc-registry.json``) and checks the repository against them.

Rules are read from those two files rather than restated here, so the gate
cannot drift away from the contract it enforces.

Standard library only, on purpose. CI installs no extra packages for this job,
and a validator that needs a dependency is a validator that eventually gets
skipped.

Usage::

    python3 scripts/validate_specs.py

Exits 0 when the set is consistent, 1 otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
META_DIR = REPO_ROOT / "specs" / "meta"
SCHEMA_PATH = META_DIR / "spec-frontmatter.schema.json"
REGISTRY_PATH = META_DIR / "doc-registry.json"

# Trees whose markdown must be registered. Everything else is out of scope.
GOVERNED_TREES = ("docs", "specs", "Docs")
GOVERNED_ROOT_FILES = ("README.md",)

SCENE_ID_RE = re.compile(r"\bSB-\d{2}\b")
DECISION_ID_RE = re.compile(r"\bD-\d{3}\b")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
EXTERNAL_LINK_RE = re.compile(r"^(https?:|mailto:|#)")


class Problem:
    """A single validation failure, tied to the file that caused it."""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        self.message = message

    def __str__(self) -> str:
        try:
            where = self.path.relative_to(REPO_ROOT)
        except ValueError:
            where = self.path
        return f"{where}: {self.message}"


# --------------------------------------------------------------------------
# Frontmatter
# --------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[dict, str | None]:
    """Parse a deliberately narrow YAML subset from a document's frontmatter.

    Supported: ``key: scalar`` and ``key: [a, b]``. Anything richer is an
    error rather than a silent misparse -- governed frontmatter is a contract,
    not a config file, and it stays readable without a YAML library.

    Returns ``(fields, error)``. ``error`` is ``None`` on success.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "missing YAML frontmatter (file must open with '---')"

    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, "frontmatter block is never closed with '---'"

    fields: dict = {}
    for offset, raw in enumerate(lines[1:end], start=2):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line != line.lstrip():
            return {}, f"line {offset}: nested frontmatter is not supported"
        if ":" not in line:
            return {}, f"line {offset}: expected 'key: value', got {line!r}"
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items = [item.strip().strip("\"'") for item in inner.split(",")]
            fields[key] = [item for item in items if item]
        elif re.fullmatch(r"-?\d+", value):
            fields[key] = int(value)
        else:
            fields[key] = value.strip("\"'")
    return fields, None


# --------------------------------------------------------------------------
# Minimal JSON Schema subset
# --------------------------------------------------------------------------


def _type_matches(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return True


def validate_against_schema(instance: object, schema: dict, where: str = "") -> list:
    """Check ``instance`` against the subset of JSON Schema the contract uses.

    Handles ``type``, ``required``, ``properties``, ``additionalProperties``,
    ``enum``, ``pattern``, ``minimum``, ``maximum``, ``minLength`` and
    ``items`` -- everything ``spec-frontmatter.schema.json`` actually relies
    on. Anything the schema adds later that is not handled here is ignored
    rather than silently passed as valid, so extend this when you extend the
    schema.
    """
    errors = []
    label = where or "frontmatter"

    expected_type = schema.get("type")
    if expected_type and not _type_matches(instance, expected_type):
        got = type(instance).__name__
        errors.append(f"{label}: expected {expected_type}, got {got}")
        return errors

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{label}: missing required field '{key}'")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    errors.append(f"{label}: unknown field '{key}'")
        for key, value in instance.items():
            if key in properties:
                child = where + "." + key if where else key
                errors.extend(validate_against_schema(value, properties[key], child))
        return errors

    if isinstance(instance, list):
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(instance):
                errors.extend(
                    validate_against_schema(item, item_schema, f"{label}[{index}]")
                )
        return errors

    if "enum" in schema and instance not in schema["enum"]:
        allowed = ", ".join(str(option) for option in schema["enum"])
        errors.append(f"{label}: {instance!r} is not one of [{allowed}]")
    if "pattern" in schema and isinstance(instance, str):
        if not re.fullmatch(schema["pattern"], instance):
            errors.append(f"{label}: {instance!r} does not match {schema['pattern']}")
    if "minLength" in schema and isinstance(instance, str):
        if len(instance) < schema["minLength"]:
            errors.append(f"{label}: shorter than {schema['minLength']} characters")
    if "minimum" in schema and isinstance(instance, int):
        if instance < schema["minimum"]:
            errors.append(f"{label}: {instance} is below minimum {schema['minimum']}")
    if "maximum" in schema and isinstance(instance, int):
        if instance > schema["maximum"]:
            errors.append(f"{label}: {instance} is above maximum {schema['maximum']}")
    return errors


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def load_documents(registry: dict, schema: dict, problems: list) -> dict:
    """Read and schema-check every registered document. Returns doc_id -> info."""
    loaded = {}
    for entry in registry.get("documents", []):
        path = REPO_ROOT / entry["path"]
        if not path.is_file():
            problems.append(
                Problem(path, "registered in doc-registry.json but missing")
            )
            continue
        text = path.read_text(encoding="utf-8")
        fields, error = parse_frontmatter(text)
        if error:
            problems.append(Problem(path, error))
            continue
        for message in validate_against_schema(fields, schema):
            problems.append(Problem(path, message))
        for field in ("doc_id", "tier", "authority", "status"):
            declared = fields.get(field)
            registered = entry.get(field)
            if declared != registered:
                problems.append(
                    Problem(
                        path,
                        f"{field} is {declared!r} but doc-registry.json says "
                        f"{registered!r} -- the two must agree",
                    )
                )
        doc_id = fields.get("doc_id")
        if doc_id:
            if doc_id in loaded:
                problems.append(Problem(path, f"duplicate doc_id {doc_id!r}"))
            loaded[doc_id] = {"path": path, "fields": fields, "text": text}
    return loaded


def check_no_orphans(registry: dict, problems: list) -> None:
    """Every markdown file in a governed tree must be registered or exempt."""
    known = {entry["path"] for entry in registry.get("documents", [])}
    known |= {entry["path"] for entry in registry.get("exempt", [])}

    candidates = []
    for tree in GOVERNED_TREES:
        candidates.extend(sorted((REPO_ROOT / tree).rglob("*.md")))
    for name in GOVERNED_ROOT_FILES:
        candidate = REPO_ROOT / name
        if candidate.is_file():
            candidates.append(candidate)

    for path in candidates:
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative not in known:
            problems.append(
                Problem(
                    path,
                    "not listed in doc-registry.json -- add it to 'documents' if it "
                    "carries authority, or to 'exempt' with a reason if it does not",
                )
            )


def check_references(documents: dict, problems: list) -> None:
    """derives_from / supersedes must resolve, and must not point downward."""
    for doc_id, info in sorted(documents.items()):
        fields = info["fields"]
        tier = fields.get("tier")
        for field in ("derives_from", "supersedes"):
            for target in fields.get(field, []):
                if target == doc_id:
                    problems.append(Problem(info["path"], f"{field} references itself"))
                    continue
                if target not in documents:
                    problems.append(
                        Problem(
                            info["path"], f"{field} references unknown id {target!r}"
                        )
                    )
                    continue
                if field == "derives_from":
                    target_tier = documents[target]["fields"].get("tier")
                    if (
                        isinstance(tier, int)
                        and isinstance(target_tier, int)
                        and target_tier > tier
                    ):
                        problems.append(
                            Problem(
                                info["path"],
                                f"derives_from {target!r} (tier {target_tier}) but is "
                                f"itself tier {tier} -- authority flows downward only",
                            )
                        )


def check_single_concept_origin(documents: dict, problems: list) -> None:
    """Exactly one document may originate concept decisions."""
    holders = [
        doc_id
        for doc_id, info in documents.items()
        if info["fields"].get("authority") == "concept"
    ]
    if len(holders) == 1:
        return
    target = documents.get("META-SPEC", {}).get("path", META_DIR / "META-SPEC.md")
    if not holders:
        problems.append(
            Problem(target, "no document holds authority 'concept' -- exactly one must")
        )
    else:
        joined = ", ".join(sorted(holders))
        problems.append(
            Problem(
                target,
                f"{len(holders)} documents hold authority 'concept' ({joined}) -- "
                "exactly one must",
            )
        )


def check_version_agreement(documents: dict, registry: dict, problems: list) -> None:
    """The set carries one version; files do not version independently."""
    expected = registry.get("doc_set_version")
    for doc_id, info in sorted(documents.items()):
        declared = info["fields"].get("doc_set_version")
        if declared != expected:
            problems.append(
                Problem(
                    info["path"],
                    f"doc_set_version is {declared!r} but the set is {expected!r} -- "
                    "bump every governed document together",
                )
            )


def uninitialised_submodules() -> list:
    """Submodule paths registered in .gitmodules that have no content checked out.

    CI checks out without submodules, so a link into one is unverifiable there.
    Rather than banning such links or silently ignoring them, they are checked
    whenever the submodule *is* initialised (locally, or in any job that opts
    in) and skipped when it is not.
    """
    gitmodules = REPO_ROOT / ".gitmodules"
    if not gitmodules.is_file():
        return []
    paths = re.findall(
        r"^\s*path\s*=\s*(.+)$", gitmodules.read_text(encoding="utf-8"), re.MULTILINE
    )
    empty = []
    for raw in paths:
        candidate = REPO_ROOT / raw.strip()
        if not candidate.is_dir() or not any(candidate.iterdir()):
            empty.append(candidate.resolve())
    return empty


def check_links(documents: dict, problems: list) -> int:
    """Relative markdown links in governed documents must resolve.

    Returns the number of links skipped because they point into a submodule
    that is not checked out, so the caller can say so rather than implying
    full coverage.
    """
    skipped = 0
    unavailable = uninitialised_submodules()
    for doc_id, info in sorted(documents.items()):
        path = info["path"]
        if path.suffix != ".md":
            continue
        for target in MD_LINK_RE.findall(info["text"]):
            if EXTERNAL_LINK_RE.match(target):
                continue
            cleaned = target.split("#", 1)[0]
            if not cleaned:
                continue
            resolved = (path.parent / cleaned).resolve()
            if any(
                resolved == root or root in resolved.parents for root in unavailable
            ):
                skipped += 1
                continue
            if not resolved.exists():
                problems.append(Problem(path, f"broken link to {target!r}"))
    return skipped


def check_scene_ids(documents: dict, problems: list) -> None:
    """Every SB-nn in the concept driver must exist in the storyboard."""
    driver = documents.get("CONCEPT-DRIVER")
    storyboard = documents.get("STORYBOARD-W1")
    if not driver or not storyboard:
        return
    indexed = sorted(set(SCENE_ID_RE.findall(driver["text"])))
    present = set(SCENE_ID_RE.findall(storyboard["text"]))
    for scene_id in indexed:
        if scene_id not in present:
            problems.append(
                Problem(
                    storyboard["path"],
                    f"{scene_id} is indexed in concept-driver.md but no scene here "
                    "carries that id",
                )
            )
    for scene_id in sorted(present - set(indexed)):
        problems.append(
            Problem(
                driver["path"],
                f"{scene_id} appears in the storyboard but is missing from the "
                "scene index",
            )
        )


def check_decision_authority(documents: dict, schema: dict, problems: list) -> None:
    """A document may only originate decisions if its authority licenses it to.

    The gap this closes: ``check_decisions`` confirmed every claimed ``D-nnn``
    existed in the register, but never asked whether the *claiming* document was
    entitled to decide anything at all. ``PROJECT-OVERVIEW`` originated eight
    decisions while declaring ``authority: derived`` -- licensed by META-SPEC
    section 2 to decide "nothing new" -- and the set validated green for two
    releases. See issue #11.

    Deliberately a coarse gate. It enforces "may this authority originate
    *something*", read from the schema so the rule cannot drift from the
    published contract. It cannot enforce "is this particular decision within
    that authority's subject matter" -- that a tier-0 constitution document is
    deciding about documents rather than about the product stays a human
    judgement, and one worth making at review time.
    """
    authority_schema = schema.get("properties", {}).get("authority", {})
    permitted = authority_schema.get("x-may-originate", {}).get("values")
    if not permitted:
        # No published rule means nothing to enforce. Say so rather than
        # passing silently -- a check that quietly does nothing is worse than
        # no check, because the green tick still reads as coverage.
        target = documents.get("META-SPEC", {}).get("path", SCHEMA_PATH)
        problems.append(
            Problem(
                target,
                "spec-frontmatter.schema.json declares no authority.x-may-originate "
                "values, so 'may this document decide anything' cannot be checked",
            )
        )
        return

    for doc_id, info in sorted(documents.items()):
        claimed = info["fields"].get("decides", [])
        if not claimed:
            continue
        authority = info["fields"].get("authority")
        if authority not in permitted:
            allowed = ", ".join(permitted)
            problems.append(
                Problem(
                    info["path"],
                    f"declares authority {authority!r} but claims to originate "
                    f"{', '.join(claimed)} -- only [{allowed}] may originate "
                    "decisions. Move them to an entitled document, or change this "
                    "one's authority deliberately (META-SPEC section 2)",
                )
            )


def check_decisions(documents: dict, problems: list) -> None:
    """Every D-nnn claimed in frontmatter must be in the decision register."""
    register = documents.get("DECISION-REGISTER")
    if not register:
        return
    registered = set(DECISION_ID_RE.findall(register["text"]))
    for doc_id, info in sorted(documents.items()):
        for decision in info["fields"].get("decides", []):
            if decision not in registered:
                problems.append(
                    Problem(
                        info["path"],
                        f"claims to decide {decision} but it is not in "
                        "specs/meta/decision-register.md",
                    )
                )


# --------------------------------------------------------------------------
# The enforcement axis (D-027)
# --------------------------------------------------------------------------

# The one gate type that counts as re-derivation. D-027 rule 4: `enforced`
# requires a gate that re-derives the fact from the system that owns it, and a
# `snapshot` gate re-reads committed data without re-checking anything, so it
# caps at `asserted`. The VOCABULARY is read from the schema below rather than
# restated here; only which member means "re-derives" is named, because that is
# a decision D-027 makes and no schema can express.
_MISSING = object()

LIVE_GATE_TYPE = "live"

# The enforcement values this implementation knows the SEMANTICS of. The schema
# publishes the vocabulary; per-value meaning -- which values need gates, which
# need a weakest_claim, which needs a registry reason -- is D-027's, and cannot
# be expressed in JSON Schema, so it is branched on below.
#
# Checked against the schema rather than assumed to match. Without that check,
# adding a fifth value to the enum would validate green while every rule below
# silently skipped documents carrying it -- the vocabulary and the semantics
# would drift apart with no signal. This is not hypothetical: PLZG-147 proposes
# exactly such a fifth value for "was true, now stale", and this is what will
# make that change fail loudly here until the semantics land with it.
HANDLED_ENFORCEMENT = {"enforced", "asserted", "intended", "n/a"}

CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CI_JOB_NAME_RE = re.compile(r"^    name:\s*(.+?)\s*$", re.M)
GATE_TYPES_RE = re.compile(r"\(([a-z|]+)\)")


def schema_enforcement_values(schema: dict) -> list:
    """The permitted `enforcement` values, read from the published contract."""
    return schema.get("properties", {}).get("enforcement", {}).get("enum", [])


def schema_gate_types(schema: dict) -> list:
    """The permitted gate types, extracted from the schema's own `gates` pattern.

    Read rather than restated, for the same reason ``check_decision_authority``
    reads ``x-may-originate``: a validator holding its own copy of a published
    vocabulary is a second source of truth, and section 4.8 is the record of what
    happens when the two drift. The pattern is ``^[^:]+:(live|snapshot)$``; the
    alternation group is the vocabulary.
    """
    pattern = (
        schema.get("properties", {})
        .get("gates", {})
        .get("items", {})
        .get("pattern", "")
    )
    found = GATE_TYPES_RE.search(pattern)
    return found.group(1).split("|") if found else []


def document_body(text: str) -> str:
    """Everything after the frontmatter block.

    Check 5 matches ``weakest_claim`` against THIS, not against the raw file, and
    the difference is the whole check. The frontmatter is part of the file, so
    ``claim in text`` matches the ``weakest_claim:`` line against itself and is
    true for every possible value -- including a sentence appearing nowhere in
    the document. The first draft of this check did exactly that and passed a
    fabricated quote, which is precisely the vacuous-gate failure
    ``tests/smoke_test.tscn`` sat in until v0.2.8.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "".join(lines[index + 1 :])
    return text


def ci_job_names() -> set:
    """Display names of every job in ci.yml.

    Deliberately a narrow regex rather than a YAML parse: this validator is
    stdlib-only by design so it runs on a bare checkout with no install step,
    and `Validate Specs` must never be the job that needs a dependency.
    """
    if not CI_WORKFLOW.is_file():
        return set()
    return {
        m.strip("\"'")
        for m in CI_JOB_NAME_RE.findall(CI_WORKFLOW.read_text(encoding="utf-8"))
    }


def check_enforcement(
    documents: dict, registry: dict, schema: dict, problems: list
) -> None:
    """The five enforcement-axis checks (D-027).

    Each closes a gap the schema cannot: the schema validates one field of one
    document at a time, and every rule here is either cross-field (gates depend
    on the enforcement value), cross-file (a job name lives in ci.yml, a reason
    lives in the registry), or cross-layer (a quote must appear in the body).

    Check 1 is why this task had to run AFTER the migration. `enforcement` is
    optional in the schema so T6 could populate all 24 documents first; absence
    becomes fatal here. You do not switch on a required field before populating
    it.

    WHAT THESE CANNOT SEE, stated so it is not rediscovered as a defect: check 5
    proves a `weakest_claim` quote is real, never that it is the WEAKEST. During
    the T6 migration eight of the 24 claims were genuine verbatim quotes and not
    the weakest, and every one was caught by human review rather than by any
    gate. A green run here is not evidence the values are honest.
    """
    permitted = schema_enforcement_values(schema)
    gate_types = schema_gate_types(schema)
    if not permitted or not gate_types:
        problems.append(
            Problem(
                SCHEMA_PATH,
                "publishes no enforcement enum or no gates type vocabulary, so the "
                "D-027 axis cannot be checked -- a check that quietly does nothing "
                "is worse than no check, because the green tick still reads as coverage",
            )
        )
        return
    if set(permitted) != HANDLED_ENFORCEMENT:
        unknown = sorted(set(permitted) - HANDLED_ENFORCEMENT)
        dropped = sorted(HANDLED_ENFORCEMENT - set(permitted))
        problems.append(
            Problem(
                SCHEMA_PATH,
                f"publishes enforcement values {sorted(permitted)}, which this "
                f"validator does not match (unhandled: {unknown}, missing: {dropped}). "
                "Every value needs its rules written here -- gates, weakest_claim, "
                "registry reason -- or documents carrying it validate green while "
                "nothing checks them",
            )
        )
        return
    if LIVE_GATE_TYPE not in gate_types:
        problems.append(
            Problem(
                SCHEMA_PATH,
                f"gates vocabulary {gate_types} does not contain {LIVE_GATE_TYPE!r}, so "
                "D-027 rule 4 (enforced requires a re-deriving gate) cannot be enforced",
            )
        )
        return

    reasons = {
        entry["doc_id"]: entry["enforcement_na_reason"]
        for entry in registry.get("documents", [])
        if "enforcement_na_reason" in entry
    }
    jobs = ci_job_names()
    if not jobs:
        # ONE precise diagnostic instead of N misleading ones. With the earlier
        # `if jobs and ...` guard an empty set skipped the job-existence check
        # entirely and the run still exited 0; that guard is gone, so an empty
        # set would now report every gate on every document as naming a missing
        # job -- true, but it buries the actual fault. The real fault is here:
        # ci.yml is absent, or it has been reindented past CI_JOB_NAME_RE. A
        # narrow regex is the price of staying stdlib-only, and this says so
        # once, pointing at the file that broke.
        problems.append(
            Problem(
                CI_WORKFLOW,
                "no job names could be read, so 'every gate names a real CI job' "
                "cannot be checked. Either the file is missing or its formatting "
                "no longer matches the parser -- fix one of those rather than "
                "letting the check pass on nothing",
            )
        )
        return

    for doc_id, info in sorted(documents.items()):
        path, fields = info["path"], info["fields"]
        body = document_body(info["text"])
        value = fields.get("enforcement")

        # 1. Declared, from the enum. Absence fails -- no default.
        if value is None:
            problems.append(
                Problem(
                    path,
                    "declares no enforcement value. Every governed document states how "
                    f"far its claims about state are proven -- one of {permitted} "
                    "(META-SPEC section 2.1, D-027)",
                )
            )
            continue

        gates = fields.get("gates", [])
        if not isinstance(gates, list) or not all(isinstance(g, str) for g in gates):
            # Same guard, same reason, as weakest_claim below -- a schema failure
            # does not remove a document from `documents`, so a malformed value
            # arrives here anyway. Two distinct ways this bit: `gates: 42` parses
            # as an int and made `for gate in gates` raise TypeError, killing the
            # run before any queued Problem printed; `gates: some-string` parses
            # as a str, which IS iterable, so it walked the value character by
            # character and reported the missing job 'g'. A crash and a nonsense
            # message are both worse than one accurate sentence.
            problems.append(
                Problem(
                    path,
                    f"declares a malformed gates value ({gates!r}). It must be a list "
                    "of 'job:type' strings, as in [Validate Specs:live]",
                )
            )
            continue

        # 2. enforced/asserted need a NON-EMPTY gates list; ANY declared gate,
        #    whatever the enforcement value, must name a job that exists.
        #
        # The two halves are scoped differently on purpose. Requiring gates is
        # about the value's meaning, so it applies only where the value claims
        # CI backing. Requiring a named job to be real is about the claim being
        # checkable at all, and an `intended` or `n/a` document naming a
        # nonexistent job is just as false -- scoping that half to
        # enforced/asserted left a hole nothing would ever have reported.
        if value in ("enforced", "asserted") and not gates:
            problems.append(
                Problem(
                    path,
                    f"is {value!r} but declares no gates. A value claiming CI backing "
                    "must name the job that provides it",
                )
            )
        for gate in gates:
            job = gate.rsplit(":", 1)[0]
            if job not in jobs:
                problems.append(
                    Problem(
                        path,
                        f"names gate job {job!r}, which is not a job in "
                        ".github/workflows/ci.yml -- a gate that does not exist "
                        "cannot be enforcing anything",
                    )
                )

        # 3. enforced needs at least one live gate (D-027 rule 4).
        if value == "enforced":
            if not any(g.rsplit(":", 1)[-1] == LIVE_GATE_TYPE for g in gates):
                problems.append(
                    Problem(
                        path,
                        f"is 'enforced' but declares no {LIVE_GATE_TYPE!r} gate. A "
                        "snapshot gate re-reads committed data without re-deriving it, "
                        "so it caps at 'asserted' (D-027 rule 4)",
                    )
                )

        # 4. n/a must say why, in the registry, where claiming it is visible.
        #
        # PRESENCE and CONTENT are asked separately, and the difference matters
        # in both directions. `"enforcement_na_reason": ""` on a non-n/a
        # document is a leftover the earlier truthiness test let through, since
        # an empty reason and an absent key looked identical to it -- yet the
        # rule is that a non-n/a document must not carry the key at all. And a
        # non-string reason used to reach .strip() and raise AttributeError,
        # the same crash class as gates and weakest_claim: the registry is JSON
        # and nothing constrains this key's type, so it arrives however it was
        # written.
        reason = reasons.get(doc_id, _MISSING)
        if value == "n/a":
            if reason is _MISSING:
                problems.append(
                    Problem(
                        path,
                        "is 'n/a' but carries no enforcement_na_reason in "
                        "specs/meta/doc-registry.json. Taking a document off the scale "
                        "is a claim, and an unexplained claim is the thing this axis exists "
                        "to stop",
                    )
                )
            elif not isinstance(reason, str) or not reason.strip():
                problems.append(
                    Problem(
                        REGISTRY_PATH,
                        f"{doc_id} declares enforcement_na_reason {reason!r} -- it must "
                        "be a non-empty string saying why the document is off the scale",
                    )
                )
        elif reason is not _MISSING:
            problems.append(
                Problem(
                    path,
                    f"is {value!r} but still carries an enforcement_na_reason in "
                    "doc-registry.json -- a leftover from a rescoring. Remove the key",
                )
            )

        # 5. asserted/intended must quote a weakest claim that really appears.
        if value in ("asserted", "intended"):
            claim = fields.get("weakest_claim")
            if not isinstance(claim, str):
                # A schema failure does not remove a document from `documents`,
                # so a non-string value -- `weakest_claim: 42`, or anything in
                # [brackets], which parse_frontmatter reads as a list -- reaches
                # this check. Without the type guard `claim not in body` raises
                # TypeError and aborts the whole run, so a reader sees a
                # traceback instead of the schema error that was already queued.
                if claim is not None:
                    problems.append(
                        Problem(
                            path,
                            f"declares a non-string weakest_claim ({claim!r}). It must "
                            "be one quoted sentence appearing in the document body",
                        )
                    )
                    continue
                claim = ""
            if not claim.strip():
                problems.append(
                    Problem(
                        path,
                        f"is {value!r} but declares no weakest_claim. The quote is what "
                        "makes the value falsifiable in ten seconds",
                    )
                )
            elif claim not in body:
                problems.append(
                    Problem(
                        path,
                        f"declares weakest_claim {claim!r}, which does not appear "
                        "verbatim in the document. Substring match -- either the quote "
                        "is wrong or the sentence it cited has been edited, and either "
                        "way the value needs re-examining",
                    )
                )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> int:
    problems: list = []

    for required in (SCHEMA_PATH, REGISTRY_PATH):
        if not required.is_file():
            print(f"fatal: {required.relative_to(REPO_ROOT)} is missing")
            return 1

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    documents = load_documents(registry, schema, problems)
    check_no_orphans(registry, problems)
    check_references(documents, problems)
    check_single_concept_origin(documents, problems)
    check_version_agreement(documents, registry, problems)
    skipped_links = check_links(documents, problems)
    check_scene_ids(documents, problems)
    check_decisions(documents, problems)
    check_decision_authority(documents, schema, problems)
    check_enforcement(documents, registry, schema, problems)

    if problems:
        print(f"Spec validation FAILED -- {len(problems)} problem(s):\n")
        for problem in problems:
            print(f"  - {problem}")
        print(
            "\nSee specs/meta/META-SPEC.md for the rules, and section 8 for how to "
            "add or change a governed document."
        )
        return 1

    summary = (
        f"Spec validation passed: {len(documents)} governed document(s), "
        f"doc set v{registry.get('doc_set_version')}."
    )
    if skipped_links:
        summary += (
            f"\n{skipped_links} link(s) into an uninitialised submodule were not "
            "checked -- run `git submodule update --init --recursive` to verify them."
        )
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
