"""WebSocket bridge server — protocol routing for two engines.

Routes incoming messages to the conversation engine or domain session
manager based on the protocol's type field. Handles push delivery of
domain session output and domain state notifications.

D-005: zero UI awareness.
D-015: ws://localhost:8765.
"""

import asyncio
import json
import os
from pathlib import Path
import sys
import time
import uuid

import websockets

from bridge.config import BridgeConfig, ConfigError, default_config, load_config
from bridge.observability import BridgeRecorder, RequestContext
from bridge.conversation import ConversationEngine
from bridge.domain_session import _SDK_ENV_PASSTHROUGH
from bridge.domain_manager import DomainManager
from bridge.protocol import (
    RequestType,
    validate_agent_id,
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
    def __init__(
        self,
        base_path=None,
        *,
        config: BridgeConfig | None = None,
        recorder: BridgeRecorder | None = None,
    ):
        self._config = config if config is not None else default_config()
        self._recorder = recorder
        self._closed = False
        self.conversation = ConversationEngine(config=self._config)
        self.domains = DomainManager(
            base_path=base_path,
            config=self._config,
            recorder=recorder,
        )
        self._websocket = None

    def _event(self, name, context=None, **metadata):
        if self._recorder is not None:
            self._recorder.event(name, context, **metadata)

    def _context(self, data, connection_id):
        domain = data.get("type") in (
            "domain_query",
            "resume",
            "activate_domain",
            "background_domain",
            "refocus_domain",
            "deactivate_domain",
        )
        request_id = data.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            request_id = str(uuid.uuid4())
        agent_id = data.get("agent_id")
        domain_id = data.get("domain_id")
        return RequestContext(
            connection_id,
            request_id,
            agent_id if validate_agent_id(agent_id) else None,
            "domain" if domain else "conversation",
            (
                self._config.model_for(self._config.domain_tier)
                if domain
                else self.conversation.model
            ),
            domain_id if isinstance(domain_id, str) and domain_id else None,
        )

    async def dispatch_raw(
        self,
        raw_message: str,
        histories=None,
        *,
        connection_id: str | None = None,
    ) -> list[dict]:
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError) as exc:
            self._reject_raw(connection_id)
            return [make_error("", "", "invalid_request", f"Bad JSON: {exc}")]
        if not isinstance(data, dict):
            self._reject_raw(connection_id)
            return [
                make_error("", "", "invalid_request", "Request must be a JSON object")
            ]
        return await self.dispatch(data, histories, connection_id=connection_id)

    def _reject_raw(self, connection_id):
        context = self._context({}, connection_id)
        self._event("request_received", context)
        self._event("request_rejected", context, outcome="rejected")

    async def dispatch(
        self,
        data: dict,
        histories=None,
        *,
        connection_id: str | None = None,
    ) -> list[dict]:
        """Route one request, keeping histories and correlation caller-owned."""
        context = self._context(data, connection_id)
        started = time.monotonic()
        self._event("request_received", context)
        try:
            responses = await self._route(data, histories, context)
        except asyncio.CancelledError:
            self._event(
                "request_cancelled",
                context,
                outcome="cancelled",
                duration_ms=(time.monotonic() - started) * 1000,
            )
            raise
        except Exception:
            self._event(
                "request_failed",
                context,
                outcome="failure",
                duration_ms=(time.monotonic() - started) * 1000,
            )
            raise
        request_id = data.get("request_id")
        if (
            context.engine == "conversation"
            and isinstance(request_id, str)
            and request_id.strip()
        ):
            responses = [
                {**response, "request_id": request_id} for response in responses
            ]
        self._record_dispatch_outcome(data, responses, context, started)
        return responses

    def _record_dispatch_outcome(self, data, responses, context, started):
        error = next((r for r in responses if r.get("status") == "error"), None)
        if error is not None:
            name = (
                "request_rejected"
                if error.get("error_type") == "invalid_request"
                else "request_failed"
            )
            outcome = "rejected" if name == "request_rejected" else "failure"
        elif data.get("type") == "domain_query":
            name, outcome = "request_accepted", "accepted"
        else:
            name, outcome = "request_completed", "success"
        self._event(
            name,
            context,
            outcome=outcome,
            duration_ms=(time.monotonic() - started) * 1000,
        )

    async def _route(self, data, histories, context):
        msg_type = data.get("type", "")
        if isinstance(msg_type, str) and msg_type in _LIFECYCLE_TYPES:
            return await self._handle_lifecycle(msg_type, data)
        request = parse_request({**data, "request_id": context.request_id})
        error = validate_request(request)
        if error:
            return [
                make_error(request.agent_id, request.task, "invalid_request", error)
            ]
        self._event("engine_routing", context)
        if request.type == RequestType.CONVERSATION:
            return [await self._conversation(data, histories, context)]
        if request.type == RequestType.DOMAIN_QUERY:
            if not validate_agent_id(request.agent_id) or not isinstance(
                request.task, str
            ):
                return [
                    make_error(
                        request.agent_id,
                        request.task,
                        "invalid_request",
                        "agent_id and task must be valid strings",
                    )
                ]
            result = await self.domains.handle_domain_query(
                request,
                on_output=self._push_output,
                context=context,
            )
            return [result] if result else []
        if request.type == RequestType.RESUME:
            entries = self.domains.handle_resume(request.domain_id, request.cursor)
            state = self.domains.get_domain_state(request.domain_id)
            if state and state.get("state") == "backgrounded":
                self.domains.refocus_domain(request.domain_id)
            return entries
        return [make_error("", "", "invalid_request", f"Unknown type: {msg_type}")]

    def _message(self, context, role, content, outcome):
        if self._recorder is not None and context.agent_id is not None:
            self._recorder.message(context, role, content, outcome)

    async def _conversation(self, data, histories, context):
        task = data.get("task")
        record = context.agent_id is not None and isinstance(task, str) and bool(task)
        if record:
            self._message(context, "user", task, "input")
        try:
            resp = await self._call_conversation(data, histories)
        except asyncio.CancelledError:
            if record:
                self._message(context, "error", "cancelled", "cancelled")
            raise
        except Exception:
            if record:
                self._message(context, "error", "engine_error", "failure")
            raise
        if record:
            success = resp.get("status") == "ok"
            self._message(
                context,
                "assistant" if success else "error",
                resp.get("output", "") if success else "conversation_error",
                "success" if success else "failure",
            )
        return resp

    async def _call_conversation(self, data, histories):
        agent_id = data.get("agent_id")
        if histories is None or not isinstance(agent_id, str):
            return await asyncio.to_thread(self.conversation.handle_request, data)
        # Store only exchanges the engine successfully extended. Context stays
        # per connection and agent, and failed calls leave no history key.
        history = histories.get(agent_id, [])
        resp = await asyncio.to_thread(self.conversation.handle_request, data, history)
        if history:
            histories[agent_id] = history
        return resp

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
        connection_id = str(uuid.uuid4())
        context = RequestContext(
            connection_id, str(uuid.uuid4()), None, "transport", None
        )
        self._event("connection_opened", context)
        # Conversation history lives exactly as long as the connection, one
        # list per agent. The loop below answers one message before reading
        # the next, so the worker thread that extends a list never races
        # another request on the same connection.
        histories: dict[str, list] = {}
        try:
            async for raw in websocket:
                responses = await self.dispatch_raw(
                    raw, histories, connection_id=connection_id
                )
                for resp in responses:
                    await websocket.send(json.dumps(resp))
        finally:
            self._websocket = None
            self._event("connection_closed", context)

    def close(self, *, clean: bool = True) -> None:
        """Release only the recorder this server owns, once."""
        if self._closed:
            return
        self._closed = True
        self._event("bridge_stopped", outcome="success" if clean else "failure")
        if self._recorder is not None:
            self._recorder.close(clean=clean)

    async def _shutdown_domains(self):
        failure = None
        for domain_id in self.domains.list_active_domains():
            try:
                await self.domains.deactivate_domain(domain_id)
            except asyncio.CancelledError as exc:
                failure = exc
            except Exception as exc:
                if failure is None:
                    failure = exc
        if failure is not None:
            raise failure

    async def serve(self, *, stop_event: asyncio.Event | None = None):
        """Serve until cancelled or an explicit normal stop is requested."""
        clean = False
        serve_failure = None
        try:
            async with websockets.serve(
                self._handle_connection,
                LISTEN_HOST,
                LISTEN_PORT,
            ):
                print(
                    f"Bridge running on ws://{LISTEN_HOST}:{LISTEN_PORT}",
                    file=sys.stderr,
                )
                self._event("bridge_started")
                if stop_event is None:
                    await asyncio.Future()
                else:
                    await stop_event.wait()
            clean = True
        except BaseException as exc:
            serve_failure = exc
            raise
        finally:
            try:
                await self._shutdown_domains()
            except BaseException as exc:
                clean = False
                # Preserve the listener's original failure/cancellation while
                # allowing a new caller cancellation during shutdown to escape.
                if serve_failure is None or isinstance(exc, asyncio.CancelledError):
                    raise
            finally:
                self.close(clean=clean)


async def serve():
    """Process composition root: load once, then construct network clients."""
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Bridge configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    recorder = BridgeRecorder(
        config,
        Path.cwd().name,
        redactions=tuple(os.environ.get(name, "") for name in _SDK_ENV_PASSTHROUGH),
    )
    server = None
    clean = False
    try:
        server = BridgeServer(config=config, recorder=recorder)
        await server.serve()
        clean = True
    finally:
        if server is None:
            recorder.close(clean=False)
        else:
            server.close(clean=clean)
