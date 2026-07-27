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
