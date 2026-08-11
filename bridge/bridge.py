"""WebSocket bridge server — Claude SDK call with agent personas.

D-005: zero UI awareness. This module knows nothing about Godot, scenes,
       sprites, or rendering. Swap test: replacing the frontend with a CLI
       harness or wscat must require no change here.
D-006: synchronous with timeout. Each request blocks until the SDK returns
       or the timeout fires. No streaming.
D-015: ws://localhost:8765.
"""

import asyncio
import json
import os
import re
import sys

import websockets
from anthropic import Anthropic

LISTEN_HOST = "localhost"
LISTEN_PORT = 8765
DEFAULT_MODEL = "claude-opus-4-6"
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_TOKENS = 4096

_VALID_AGENT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _build_client():
    return Anthropic()


def _load_agent_definition(agent_id):
    """Load agent definition from the bridge agent store (D-029).

    T3b (bridge/agents.py) will provide the real loader. Until then,
    reads .md files directly from bridge/agents/ if present.
    """
    try:
        from bridge.agents import load_agent

        return load_agent(agent_id)
    except (ImportError, ModuleNotFoundError):
        pass

    agents_dir = os.path.join(os.path.dirname(__file__), "agents")
    agent_path = os.path.join(agents_dir, f"{agent_id}.md")
    resolved = os.path.realpath(agent_path)
    if not resolved.startswith(os.path.realpath(agents_dir)):
        return None
    if os.path.isfile(resolved):
        with open(resolved, encoding="utf-8") as f:
            return f.read()

    return None


def _make_error(agent_id, task, error_type, message):
    return {
        "agent_id": agent_id,
        "task": task,
        "output": "",
        "status": "error",
        "error_type": error_type,
        "message": message,
    }


def _make_success(agent_id, task, output):
    return {
        "agent_id": agent_id,
        "task": task,
        "output": output,
        "status": "ok",
    }


def handle_request(client, request):
    """Process a single bridge request. Returns a response dict per PROTOCOL.md."""
    if not isinstance(request, dict):
        return _make_error("", "", "invalid_request", "Request must be a JSON object")

    agent_id = request.get("agent_id", "")
    task = request.get("task", "")

    if not isinstance(agent_id, str) or not isinstance(task, str):
        return _make_error(
            "", "", "invalid_request", "agent_id and task must be strings"
        )

    if not agent_id or not task:
        return _make_error(
            agent_id, task, "invalid_request", "agent_id and task are required"
        )

    if not _VALID_AGENT_ID.match(agent_id):
        return _make_error(
            agent_id, task, "invalid_request", "agent_id contains invalid characters"
        )

    definition = _load_agent_definition(agent_id)
    if definition is None:
        return _make_error(agent_id, task, "not_found", f"No agent '{agent_id}'")

    try:
        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=definition,
            messages=[{"role": "user", "content": task}],
            timeout=DEFAULT_TIMEOUT,
        )
        parts = [b.text for b in response.content if hasattr(b, "text")]
        output = "\n\n".join(parts) if parts else ""
        return _make_success(agent_id, task, output)
    except Exception as exc:
        exc_name = type(exc).__name__
        if "auth" in exc_name.lower() or "authentication" in str(exc).lower():
            return _make_error(agent_id, task, "auth", str(exc))
        if "timeout" in exc_name.lower() or "timed out" in str(exc).lower():
            return _make_error(
                agent_id, task, "timeout", f"Timed out after {DEFAULT_TIMEOUT}s"
            )
        return _make_error(agent_id, task, "api_error", str(exc))


async def _handle_connection(websocket, client):
    async for raw in websocket:
        try:
            request = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            resp = _make_error("", "", "invalid_request", f"Bad JSON: {exc}")
            await websocket.send(json.dumps(resp))
            continue

        # Single-client bridge: blocking the event loop is acceptable (D4).
        resp = handle_request(client, request)
        await websocket.send(json.dumps(resp))


async def serve():
    client = _build_client()
    async with websockets.serve(
        lambda ws: _handle_connection(ws, client),
        LISTEN_HOST,
        LISTEN_PORT,
    ):
        print(f"Bridge running on ws://{LISTEN_HOST}:{LISTEN_PORT}", file=sys.stderr)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(serve())
