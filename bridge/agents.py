"""Agent store loader — reads definitions from the bridge agent store.

D-029: at runtime the bridge reads only from its own store (bridge/agents/),
never from the submodule directly. bridge/sync.py populates the store;
this module consumes it.

D-016: NPC scenes store agent_id only. This loader resolves id to the
full definition text for use as a system prompt.
"""

import os
import re

STORE_DIR = os.path.join(os.path.dirname(__file__), "agents")

_VALID_AGENT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def load_agent(agent_id):
    """Return the .md definition for agent_id, or None if not found.

    The agent_id is validated against a slug pattern and the resolved
    path is checked for containment within the store directory.
    """
    if not isinstance(agent_id, str) or not _VALID_AGENT_ID.match(agent_id):
        return None

    agent_path = os.path.join(STORE_DIR, f"{agent_id}.md")
    resolved = os.path.realpath(agent_path)
    if not resolved.startswith(os.path.realpath(STORE_DIR)):
        return None

    if not os.path.isfile(resolved):
        return None

    with open(resolved, encoding="utf-8") as f:
        return f.read()


def list_agents():
    """Return a sorted list of available agent_ids in the store."""
    if not os.path.isdir(STORE_DIR):
        return []

    ids = []
    for fname in os.listdir(STORE_DIR):
        if fname.endswith(".md"):
            ids.append(os.path.splitext(fname)[0])
    return sorted(ids)
