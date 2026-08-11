"""Seed or upgrade the bridge agent store from the submodule.

D-029: the bridge maintains its own committed copy of agent definitions,
decoupled from the submodule at runtime. bridge/agents/ is checked into
git — the bridge works without the submodule and without running this
script. This script is for:

  1. Seeding v0.0.1: one-time copy from the submodule to create the
     initial bridge/agents/ contents.
  2. Upgrading: refreshing bridge/agents/ when the submodule gets new
     or updated agents.

After running, review the diff and commit. The committed files are the
bridge's own copy and may be adjusted to fit the bridge context.
"""

import os
import shutil
import sys

SUBMODULE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "claude-code-tresor", "subagents"
)
STORE_DIR = os.path.join(os.path.dirname(__file__), "agents")


def seed(source=None, dest=None):
    """Copy agent.md files from the submodule into the bridge store.

    Each agent directory (e.g. core/systems-architect/) contains an
    agent.md. The parent directory name becomes the slug filename in
    the store (e.g. bridge/agents/systems-architect.md).

    Returns the count of files copied.
    """
    source = source or SUBMODULE_DIR
    dest = dest or STORE_DIR

    if not os.path.isdir(source):
        print(
            f"seed: source directory not found: {source}\n"
            "  Hint: run 'git submodule update --init --recursive'",
            file=sys.stderr,
        )
        return 0

    agent_files = []
    for root, _dirs, files in os.walk(source):
        if "agent.md" in files:
            agent_files.append(os.path.join(root, "agent.md"))

    if not agent_files:
        print(f"seed: no agent.md files found in {source}", file=sys.stderr)
        return 0

    os.makedirs(dest, exist_ok=True)

    copied = 0
    seen_slugs = {}
    for src_path in sorted(agent_files):
        slug = os.path.basename(os.path.dirname(src_path))
        if slug in seen_slugs:
            print(
                f"seed: collision on '{slug}' — "
                f"{seen_slugs[slug]} vs {src_path}, skipping duplicate",
                file=sys.stderr,
            )
            continue
        seen_slugs[slug] = src_path
        dest_path = os.path.join(dest, f"{slug}.md")
        shutil.copy2(src_path, dest_path)
        copied += 1

    print(f"seed: copied {copied} agent definitions to {dest}", file=sys.stderr)
    return copied


if __name__ == "__main__":
    count = seed()
    sys.exit(0 if count > 0 else 1)
