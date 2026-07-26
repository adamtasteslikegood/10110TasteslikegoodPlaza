#!/usr/bin/env python3
"""Generate data/agents.json from the claude-code-tresor submodule.

`D-016`: the submodule is the canonical agent layer and `data/agents.json` is
generated from it, never hand-edited. This script is the generator, and the
`--check` mode is what makes that rule enforceable rather than aspirational --
CI regenerates and fails if the committed file has drifted.

**Reads `subagents/` only.** Upstream v2.7.0 consolidated agents there and made
`agents/` a backward-compatible shim:

    subagents/<dept>/<subcat>/<name>/agent.md   133 real files, PRIMARY
    agents/<name>/agent.md                        8 symlinks into subagents/core
    agents/<name>.md                              8 pre-v2.7.0 leftovers, diverged

The symlinks would duplicate the core eight; the flat files carry 2025-era
classifications (`category: engineering`, `color: blue`) that the catalog has
since superseded (`category: core`, `color: "#FFD700"`). Neither is catalog data.

Unlike `validate_specs.py`, this uses PyYAML rather than a hand-rolled parser.
That validator reads *our* frontmatter, which we control and keep to a flat
subset. This reads *upstream* frontmatter: block sequences, nested `examples`,
and three different `tools` syntaxes. Hand-parsing that invites silent
misreads, which is a worse failure than a dependency.

Usage::

    python3 scripts/generate_agents_json.py            # write data/agents.json
    python3 scripts/generate_agents_json.py --check    # verify, write nothing

Exits 0 on success; 1 on drift (in --check) or any data problem.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment problem, not logic
    sys.exit("fatal: PyYAML is required. pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBAGENTS = REPO_ROOT / "claude-code-tresor" / "subagents"
OUTPUT = REPO_ROOT / "data" / "agents.json"

# Canonical department -> tint, per D-017 (docs/agent-directory.md is the
# taxonomy authority). Frontmatter is cross-checked against this so a drifting
# upstream colour fails the build instead of silently retinting a department.
DEPARTMENT_COLOURS = {
    "account-customer-success": "#06B6D4",
    "ai-automation": "#6366F1",
    "core": "#FFD700",
    "design": "#EC4899",
    "engineering": "#3B82F6",
    "leadership": "#F59E0B",
    "marketing": "#10B981",
    "operations": "#14B8A6",
    "product": "#8B5CF6",
    "research": "#F97316",
}

# --------------------------------------------------------------------------
# Local curation of upstream id collisions
# --------------------------------------------------------------------------
# Upstream ships 133 files carrying only 130 distinct `name` slugs. Three roles
# exist in two departments each -- an artefact of the v2.7.0 consolidation that
# their own DUPLICATE-ANALYSIS.md (v2.5.0) predates and does not cover.
#
# Keyed by source path rather than by slug, so if upstream moves or renames a
# file the entry stops matching and the build fails, instead of the override
# silently landing on the wrong agent.
#
# This is still generation, not hand-editing: the curation is code, reviewed in
# the diff, and `data/agents.json` remains a pure function of the submodule
# plus these tables. `D-016` holds.

EXCLUDED = {
    # Near-identical to engineering/devops/infrastructure-maintainer: same
    # scope (health, performance, scaling, reliability), adding only capacity
    # planning and disaster recovery. The clearest case of the three that this
    # is one role filed twice rather than two roles sharing a name. Dropped so
    # the office has one infrastructure NPC, not two doing the same job.
    "operations/infrastructure/infrastructure-maintainer": (
        "duplicate of engineering/devops/infrastructure-maintainer"
    ),
}

RENAMES = {
    # Handles tickets, FAQs and canned responses. The account-customer-success
    # agent that keeps the bare `customer-support` slug does something
    # different -- it analyses resolution patterns and escalation risk.
    "operations/support/customer-support": "support-ticket-handler",
    # Self-described "Educational content specialist"; every capability is
    # pedagogy. Sits in marketing/content/ beside content-creator,
    # content-marketer and content-writer, so the name matches its siblings.
    # The engineering agent keeping `tutorial-engineer` builds tutorials from
    # code, which is a different job.
    "marketing/content/tutorial-engineer": "educational-content-writer",
}

# 133 upstream files, minus the one excluded above.
EXPECTED_TOTAL = 133 - len(EXCLUDED)


def parse_frontmatter(path: Path) -> dict:
    """Return the YAML frontmatter of an agent.md as a dict."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path}: no frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path}: unterminated frontmatter")
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict):
        raise ValueError(f"{path}: frontmatter is not a mapping")
    return data


def normalise_tools(raw: object, path: Path) -> list:
    """Coerce the three upstream `tools` syntaxes into one list of strings.

    Upstream writes tools three ways, and 83 of 133 agents use the bare form
    that YAML reads as a single string:

        tools: Read, Write, Edit          -> str   (83 agents)
        tools: [Read, Write, Edit]        -> list
        tools:\\n  - Read\\n  - Write       -> list

    Passing the str form straight through would give GDScript a string where
    it expects an array, for most of the directory.
    """
    if isinstance(raw, str):
        items = [t.strip() for t in raw.split(",")]
    elif isinstance(raw, list):
        items = [str(t).strip() for t in raw]
    elif raw is None:
        items = []
    else:
        raise ValueError(f"{path}: unexpected tools type {type(raw).__name__}")
    return [t for t in items if t]


def display_name(slug: str) -> str:
    """`legacy-modernizer` -> `Legacy Modernizer`, for the dialogue panel."""
    return titleise(slug)


# Words that must not be sentence-cased when a slug becomes a label.
ACRONYMS = {
    "ai": "AI",
    "api": "API",
    "aso": "ASO",
    "css": "CSS",
    "devops": "DevOps",
    "ml": "ML",
    "mlops": "MLOps",
    "qa": "QA",
    "rag": "RAG",
    "seo": "SEO",
    "ui": "UI",
    "ux": "UX",
}


def titleise(slug: str) -> str:
    """`code-quality` -> `Code Quality`, `ui` -> `UI`, `devops` -> `DevOps`."""
    words = slug.replace("_", "-").replace("/", "-").split("-")
    return " ".join(ACRONYMS.get(w.lower(), w.capitalize()) for w in words if w)


def short_role(subcategory: str, dept: str) -> str:
    """The topical label under a name in the dialogue panel.

    Derived from the taxonomy (`subcategory`, falling back to `dept`) rather
    than from prose. An earlier version took the first sentence or clause of
    the description, which truncated on punctuation rather than on meaning and
    produced labels like "UI design specialist for creating beautiful" -- worse
    than no label. Topical relevance has to win over mechanical trimming, and
    the taxonomy is already topical, short, and never mangled.

    The full prose is preserved in `description`; nothing is lost.
    """
    return titleise(subcategory or dept)


def build_entry(path: Path) -> tuple:
    """Return (agent_id, entry-dict) for one agent.md."""
    fm = parse_frontmatter(path)

    for required in ("name", "description", "category", "color"):
        if not fm.get(required):
            raise ValueError(f"{path}: missing required field '{required}'")

    agent_id = str(fm["name"]).strip()
    dept = str(fm["category"]).strip()
    colour = str(fm["color"]).strip()

    expected = DEPARTMENT_COLOURS.get(dept)
    if expected is None:
        raise ValueError(f"{path}: unknown department '{dept}'")
    if colour.upper() != expected.upper():
        raise ValueError(
            f"{path}: colour {colour} disagrees with the D-017 taxonomy "
            f"({expected}) for department '{dept}'"
        )

    description = " ".join(str(fm["description"]).split())
    entry = {
        "name": display_name(agent_id),
        "role": short_role(
            str(fm["subcategory"]).strip() if fm.get("subcategory") else "", dept
        ),
        "dept": dept,
        "color": expected,
        "tools": normalise_tools(fm.get("tools"), path),
        "description": description,
        "subcategory": str(fm["subcategory"]).strip() if fm.get("subcategory") else "",
        "source": str(path.relative_to(REPO_ROOT).as_posix()),
    }
    return agent_id, entry


def build_registry() -> dict:
    """Walk the catalog and return the full id -> entry mapping."""
    if not SUBAGENTS.is_dir():
        sys.exit(
            "fatal: claude-code-tresor/subagents not found. Run "
            "`git submodule update --init --recursive` first."
        )

    agents: dict = {}
    problems: list = []
    seen_keys: set = set()

    for path in sorted(SUBAGENTS.rglob("agent.md")):
        key = path.parent.relative_to(SUBAGENTS).as_posix()

        if key in EXCLUDED:
            seen_keys.add(key)
            continue

        try:
            agent_id, entry = build_entry(path)
        except ValueError as exc:
            problems.append(str(exc))
            continue

        if key in RENAMES:
            seen_keys.add(key)
            entry["upstream_name"] = agent_id
            entry["id_note"] = (
                f"Renamed locally from '{agent_id}', which collides with another "
                "department's agent upstream. See scripts/generate_agents_json.py."
            )
            agent_id = RENAMES[key]

        if agent_id in agents:
            # Every known collision is handled by EXCLUDED or RENAMES above, so
            # reaching here means upstream introduced a new one. Fail loudly
            # rather than auto-suffixing: a new duplicate is a judgement call
            # about what the two agents actually do, and that belongs to a
            # human reading both descriptions, not to a naming rule.
            problems.append(
                f"{path}: id '{agent_id}' collides with "
                f"{agents[agent_id]['source']}. Upstream added a new duplicate "
                "-- read both and add an EXCLUDED or RENAMES entry."
            )
            continue
        agents[agent_id] = entry

    stale = sorted((set(EXCLUDED) | set(RENAMES)) - seen_keys)
    for key in stale:
        problems.append(
            f"curation entry '{key}' matched no file -- upstream moved or "
            "removed it. Re-check the collision and update the table."
        )

    if problems:
        print(f"Agent data FAILED -- {len(problems)} problem(s):\n")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)

    if len(agents) != EXPECTED_TOTAL:
        sys.exit(
            f"fatal: found {len(agents)} agents, expected {EXPECTED_TOTAL}. "
            "If the submodule pin moved deliberately, update EXPECTED_TOTAL here "
            "and the counts in docs/agent-directory.md (the D-017 authority) "
            "together."
        )
    return dict(sorted(agents.items()))


def render(agents: dict) -> str:
    """Deterministic JSON, so --check diffs mean drift and not formatting."""
    return json.dumps(agents, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify data/agents.json matches a fresh generation; write nothing",
    )
    args = parser.parse_args()

    agents = build_registry()
    rendered = render(agents)

    by_dept: dict = {}
    for entry in agents.values():
        by_dept[entry["dept"]] = by_dept.get(entry["dept"], 0) + 1
    summary = ", ".join(f"{d} {n}" for d, n in sorted(by_dept.items()))

    if args.check:
        if not OUTPUT.is_file():
            print(f"Agent data FAILED -- {OUTPUT.name} does not exist.")
            print("Run: python3 scripts/generate_agents_json.py")
            return 1
        current = OUTPUT.read_text(encoding="utf-8")
        if current != rendered:
            print(
                "Agent data FAILED -- data/agents.json is out of sync with the "
                "submodule.\n\nIt is generated, never hand-edited (D-016). "
                "Regenerate and commit:\n\n"
                "    python3 scripts/generate_agents_json.py\n"
            )
            return 1
        print(f"Agent data OK: {len(agents)} agents ({summary}).")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}: {len(agents)} agents ({summary}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
