"""Sync agent definitions from the submodule into the bridge agent store.

D-029: the bridge maintains its own copy of agent definitions, decoupled
from the submodule at runtime. This module is the only code that reads
the submodule; it runs explicitly (build step or manual), never at
request time.
"""

import os
import shutil
import sys

SUBMODULE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "claude-code-tresor", "subagents"
)
STORE_DIR = os.path.join(os.path.dirname(__file__), "agents")


def sync(source=None, dest=None):
    """Copy .md agent definitions from source into dest.

    Returns the count of files copied. Prints warnings to stderr for
    missing or empty source directories but never raises -- a missing
    submodule must not prevent the bridge from running with whatever
    was last synced.
    """
    source = source or SUBMODULE_DIR
    dest = dest or STORE_DIR

    if not os.path.isdir(source):
        print(
            f"sync: source directory not found: {source}\n"
            "  Hint: run 'git submodule update --init --recursive'",
            file=sys.stderr,
        )
        return 0

    md_files = []
    for root, _dirs, files in os.walk(source):
        for fname in files:
            if fname.endswith(".md"):
                md_files.append(os.path.join(root, fname))

    if not md_files:
        print(f"sync: no .md files found in {source}", file=sys.stderr)
        return 0

    os.makedirs(dest, exist_ok=True)

    copied = 0
    for src_path in md_files:
        rel = os.path.relpath(src_path, source)
        slug = os.path.splitext(rel.replace(os.sep, "--"))[0]
        dest_path = os.path.join(dest, f"{slug}.md")
        shutil.copy2(src_path, dest_path)
        copied += 1

    print(f"sync: copied {copied} agent definitions to {dest}", file=sys.stderr)
    return copied


if __name__ == "__main__":
    count = sync()
    sys.exit(0 if count > 0 else 1)
