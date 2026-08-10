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
import sys

import websockets
from anthropic import Anthropic

LISTEN_HOST = "localhost"
LISTEN_PORT = 8765
DEFAULT_MODEL = "claude-opus-4-6"
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_TOKENS = 4096


def _build_client():
    return Anthropic()


def _load_agent_definition(agent_id):
    """Load agent definition from the bridge agent store (D-029).

    T3b (bridge/agents.py) will provide the real loader. Until then, fall
    back to a generic persona so the bridge is testable standalone.
    """
    try:
        from bridge.agents import load_agent

        return load_agent(agent_id)
    except (ImportError, ModuleNotFoundError):
        pass

    agents_dir = os.path.join(os.path.dirname(__file__), "agents")
    agent_path = os.path.join(agents_dir, f"{agent_id}.md")
    if os.path.isfile(agent_path):
        with open(agent_path, encoding="utf-8") as f:
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
    agent_id = request.get("agent_id", "")
    task = request.get("task", "")

    if not agent_id or not task:
        return _make_error(
            agent_id, task, "invalid_request", "agent_id and task are required"
        )

    definition = _load_agent_definition(agent_id)
    if definition is None:
        return _make_error(agent_id, task, "not_found", f"No agent '{agent_id}'")

    model = request.get("model", DEFAULT_MODEL)
    timeout = request.get("timeout", DEFAULT_TIMEOUT)
    max_tokens = request.get("max_tokens", DEFAULT_MAX_TOKENS)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=definition,
            messages=[{"role": "user", "content": task}],
            timeout=timeout,
        )
        output = response.content[0].text if response.content else ""
        return _make_success(agent_id, task, output)
    except Exception as exc:
        exc_name = type(exc).__name__
        if "auth" in exc_name.lower() or "authentication" in str(exc).lower():
            return _make_error(agent_id, task, "auth", str(exc))
        if "timeout" in exc_name.lower() or "timed out" in str(exc).lower():
            return _make_error(agent_id, task, "timeout", f"Timed out after {timeout}s")
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
