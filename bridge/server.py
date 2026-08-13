"""WebSocket bridge server — protocol routing for two engines.

Routes incoming messages to the conversation engine or domain session
manager based on the protocol's type field. Handles push delivery of
domain session output and domain state notifications.

D-005: zero UI awareness.
D-015: ws://localhost:8765.
"""

import asyncio
import json
import sys

import websockets

from bridge.conversation import ConversationEngine
from bridge.domain_manager import DomainManager
from bridge.protocol import (
    RequestType,
    parse_request,
    validate_request,
    make_error,
    make_success,
)

LISTEN_HOST = "localhost"
LISTEN_PORT = 8765

_LIFECYCLE_TYPES = {
    "activate_domain",
    "background_domain",
    "refocus_domain",
    "deactivate_domain",
}


class BridgeServer:
    def __init__(self, base_path=None):
        self.conversation = ConversationEngine()
        self.domains = DomainManager(base_path=base_path)
        self._websocket = None

    async def dispatch_raw(self, raw_message: str) -> list[dict]:
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError) as exc:
            return [make_error("", "", "invalid_request", f"Bad JSON: {exc}")]
        return await self.dispatch(data)

    async def dispatch(self, data: dict) -> list[dict]:
        msg_type = data.get("type", "")

        if msg_type in _LIFECYCLE_TYPES:
            return await self._handle_lifecycle(msg_type, data)

        request = parse_request(data)
        error = validate_request(request)
        if error:
            return [
                make_error(request.agent_id, request.task, "invalid_request", error)
            ]

        if request.type == RequestType.CONVERSATION:
            resp = await asyncio.to_thread(self.conversation.handle_request, data)
            return [resp]

        if request.type == RequestType.DOMAIN_QUERY:
            result = await self.domains.handle_domain_query(
                request, on_output=self._push_output
            )
            return [result] if result else []

        if request.type == RequestType.RESUME:
            entries = self.domains.handle_resume(request.domain_id, request.cursor)
            state = self.domains.get_domain_state(request.domain_id)
            if state:
                self.domains.refocus_domain(request.domain_id)
            return entries

        return [make_error("", "", "invalid_request", f"Unknown type: {msg_type}")]

    async def _handle_lifecycle(self, msg_type, data):
        domain_id = data.get("domain_id", "")
        if not domain_id:
            return [make_error("", "", "invalid_request", "domain_id is required")]

        if msg_type == "activate_domain":
            result = await self.domains.activate_domain(domain_id)
            return [result]
        elif msg_type == "background_domain":
            return [self.domains.background_domain(domain_id)]
        elif msg_type == "refocus_domain":
            return [self.domains.refocus_domain(domain_id)]
        elif msg_type == "deactivate_domain":
            result = await self.domains.deactivate_domain(domain_id)
            return [result]
        return []

    async def _push_output(self, domain_id, entry):
        if self._websocket:
            resp = make_success(
                entry.agent_id,
                entry.task,
                entry.output,
                domain_id=domain_id,
                request_id=entry.request_id,
                output_id=str(entry.output_id),
            )
            await self._websocket.send(json.dumps(resp))

    async def _handle_connection(self, websocket):
        self._websocket = websocket
        try:
            async for raw in websocket:
                responses = await self.dispatch_raw(raw)
                for resp in responses:
                    await websocket.send(json.dumps(resp))
        finally:
            self._websocket = None

    async def serve(self):
        async with websockets.serve(
            self._handle_connection,
            LISTEN_HOST,
            LISTEN_PORT,
        ):
            print(
                f"Bridge running on ws://{LISTEN_HOST}:{LISTEN_PORT}",
                file=sys.stderr,
            )
            await asyncio.Future()


async def serve():
    server = BridgeServer()
    await server.serve()
