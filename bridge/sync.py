"""Synchronize committed bindings and curated definitions from the canonical generator.

Development only: runtime consumes the committed bridge store (D-029).
Run python -m bridge.sync [--check], or the presentation generator.
"""

import argparse
from pathlib import Path

from scripts import generate_agents_json as generator
from bridge.agent_bindings import BindingRegistry

STORE_DIR = Path(__file__).resolve().parent / "agents"
BINDINGS = Path(__file__).resolve().parent / "agent_bindings.json"


def synchronize(registry, *, check=False, dest=None, metadata=None):
    dest = Path(dest) if dest is not None else STORE_DIR
    metadata = Path(metadata) if metadata is not None else BINDINGS
    bindings = {
        agent: {"execution_kind": "working", "domain_id": entry["dept"]}
        for agent, entry in registry.items()
    }
    BindingRegistry(metadata=bindings, catalog=registry)
    expected = {
        dest
        / f"{agent}.md": (generator.REPO_ROOT / entry["source"]).read_text(
            encoding="utf-8"
        )
        for agent, entry in registry.items()
    }
    expected[metadata] = generator.render(bindings)
    stale = set(dest.glob("*.md")) - {dest / f"{agent}.md" for agent in registry}
    drift = bool(stale)
    for path, text in expected.items():
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            drift = True
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    if not check:
        for path in stale:
            path.unlink()
    return not drift if check else True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return 0 if synchronize(generator.build_registry(), check=args.check) else 1


if __name__ == "__main__":
    raise SystemExit(main())
