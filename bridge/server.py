"""WebSocket bridge server — protocol routing for two engines.

Routes incoming messages to the conversation engine or domain session
manager based on the protocol's type field. Handles push delivery of
domain session output and domain state notifications.

D-005: zero UI awareness.
D-015: ws://localhost:8765.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time
import uuid

import websockets

from bridge.agent_bindings import BindingRegistry, InvalidBinding
from bridge.interaction_protocol import (
    COMMANDS as INTERACTIONS,
    validate_interaction,
    interaction_error,
)
from bridge.config import BridgeConfig, ConfigError, default_config, load_config
from bridge.observability import BridgeRecorder, RequestContext
from bridge.context import compose_context, ContextError
from bridge.conversation import ConversationEngine, ExecutionMetadata
from bridge.domain_session import _SDK_ENV_PASSTHROUGH
from bridge.domain_manager import DomainManager
from bridge.domain_protocol import COMMANDS
from bridge.domain_session import deliver
from bridge.connection import ConnectionState
from bridge.project_service import ProjectService, REFERRAL
from bridge.project_memory import TurnIntent
from bridge.readiness import owned_io
from bridge.application_state import StateError
from bridge.state_coordinator import (
    StateCoordinator,
    LazySQLiteStateRepository,
    VolatileStateRepository,
)
from bridge.agents import load_agent
from bridge.protocol import (
    validate_agent_id,
    parse_request,
    validate_request,
    make_error,
    make_success,
)

LISTEN_HOST = "localhost"
LISTEN_PORT = 8765


def _is_domain_request(data):
    kind = data.get("type")
    return isinstance(kind, str) and kind in COMMANDS


async def _drain(task):
    """Join an owned task despite repeated cancellation of its owner."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if not task.cancelled():
        task.exception()


@asynccontextmanager
async def _drained_listener(listener):
    """Close sockets and join their handlers before recorder shutdown.

    Repeated raw cancellation of serve() must not abandon WebSocket __aexit__
    while those handlers are draining their SDK workers.
    """
    await listener.__aenter__()
    try:
        yield
    finally:
        cleanup = asyncio.create_task(listener.__aexit__(*sys.exc_info()))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await _drain(cleanup)
            raise


class BridgeServer:
    def __init__(
        self,
        *,
        config: BridgeConfig | None = None,
        recorder: BridgeRecorder | None = None,
        project_service: ProjectService | None = None,
        bindings=None,
        state_coordinator: StateCoordinator | None = None,
    ):
        self._config = config if config is not None else default_config()
        self._recorder = recorder
        self._closed = False
        self.application_state = state_coordinator
        self._state_open_task = None
        self._state_error = None
        self.bindings = bindings if bindings is not None else BindingRegistry()
        self.conversation = ConversationEngine(
            config=self._config, registry=self.bindings
        )
        self.project = project_service or ProjectService(
            self._config,
            runtime_root=Path(__file__).resolve().parent.parent,
            owner_run_id=str(uuid.uuid4()),
            on_ready=self._ensure_application_state,
        )
        self.domains = DomainManager(
            config=self._config,
            project_service=self.project,
            recorder=recorder,
            state_provider=lambda: self.application_state,
            state_status=self.application_state_status,
        )
        self._connection_tasks = set()
        self._connections = set()
        self._npc_tasks = set()
        self._stopping = False

    def application_state_status(self):
        """Storage facts for lifecycle/protocol consumers; independent of workspace."""
        durable = self._config.domain_state_backend == "sqlite"
        return dict(
            backend=self._config.domain_state_backend,
            durable=durable,
            continuity="project" if durable else "process",
            error_type=(
                self.application_state.health
                if self.application_state is not None
                else self._state_error
            ),
        )

    async def _open_application_state(self):
        try:
            binding = await self.project.application_state_binding()
            if binding is None:
                return
            common_git_dir, project_id = binding
            factory = (
                (lambda: LazySQLiteStateRepository(common_git_dir, project_id))
                if self._config.domain_state_backend == "sqlite"
                else (lambda: VolatileStateRepository(project_id))
            )
            self.application_state = StateCoordinator(
                factory, boot_id=self.domains.boot_id
            )
            await self.application_state.open()
            observer = getattr(self.project, "observe_application_state", None)
            if observer is not None:
                await observer(self.application_state.snapshot())
        except StateError as error:
            self._state_error = error.code
        except Exception:
            # Invalidated project facts cannot become guessed storage paths.
            self._state_error = "state_store_invalid"

    async def _ensure_application_state(self):
        """Ready callback, also the explicit seam for injected ProjectServices."""
        if self._stopping:
            return
        if self._state_open_task is not None:
            opening = self._state_open_task
            await asyncio.shield(opening)
            if (
                self._state_open_task is opening
                and self.application_state is None
                and self._state_error is None
            ):
                self._state_open_task = None
            return
        if self.application_state is not None:
            return
        if self._state_open_task is None:
            self._state_open_task = asyncio.create_task(
                self._open_application_state(), name="application-state-open"
            )
        await asyncio.shield(self._state_open_task)
        if self.application_state is None and self._state_error is None:
            # A genuinely unprepared project had no binding. Later bootstrap
            # may provide one; this is not a retry of a failed storage open.
            self._state_open_task = None

    def _event(self, name, context=None, **metadata):
        if self._recorder is not None:
            self._recorder.event(name, context, **metadata)

    def _context(self, data, connection_id):
        domain = _is_domain_request(data)
        kind = data.get("type")
        interaction = isinstance(kind, str) and kind in INTERACTIONS
        request_id = data.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            request_id = str(uuid.uuid4())
        agent_id = data.get("agent_id")
        domain_id = data.get("domain_id")
        return RequestContext(
            connection_id,
            request_id,
            agent_id if validate_agent_id(agent_id) else None,
            kind if interaction else "domain" if domain else "conversation",
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
        emit=None,
    ) -> list[dict]:
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError) as exc:
            self._reject_raw(connection_id)
            return await self._emit_responses(
                [make_error("", "", "invalid_request", f"Bad JSON: {exc}")], emit
            )
        if not isinstance(data, dict):
            self._reject_raw(connection_id)
            return await self._emit_responses(
                [
                    make_error(
                        "", "", "invalid_request", "Request must be a JSON object"
                    )
                ],
                emit,
            )
        return await self.dispatch(
            data, histories, connection_id=connection_id, emit=emit
        )

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
        emit=None,
    ) -> list[dict]:
        """Route one request, keeping histories and correlation caller-owned."""
        context = self._context(data, connection_id)
        started = time.monotonic()
        self._event("request_received", context)
        try:
            await self._ensure_application_state()
            responses = await self._route(data, histories, context, emit)
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
        if emit is not None and _is_domain_request(data):
            return []
        return await self._emit_responses(responses, emit)

    async def _emit_responses(self, responses, emit):
        if emit is None:
            return responses
        for packet in responses:
            await deliver(emit, packet, self._recorder, None)
        return []

    def _record_dispatch_outcome(self, data, responses, context, started):
        # DomainManager/DomainSession own rejected domain commands and actual
        # execution terminals, including their validated diagnostics. Dispatch
        # owns admission and successful commands; replayed execution packets do
        # not change the outcome of the replay command or create new failures.
        error = next(
            (
                r
                for r in responses
                if r.get("status") == "error" and r.get("type") != "domain_result"
            ),
            None,
        )
        if (
            _is_domain_request(data)
            and error is not None
            and error.get("type") == "domain_error"
        ):
            return
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

    async def _interaction(self, data):
        try:
            validate_interaction(data)
            binding = self.bindings.resolve_binding(data["agent_id"])
        except (ValueError, InvalidBinding) as error:
            return interaction_error(
                data, getattr(error, "code", "invalid_request"), self.project.snapshot()
            )
        if data["type"] == "project_setup":
            output = (
                (
                    await self.project.interact_setup(
                        data["agent_id"], data["request_id"], intent=data["intent"]
                    )
                )
                if binding.agent_id == "systems-architect"
                else REFERRAL
            )
            project = self.project.snapshot()
            status = (
                "error"
                if binding.agent_id == "systems-architect"
                and project["stage"] in ("failed", "unconfigured")
                else "ok"
            )
            packet = dict(
                type="project_setup",
                agent_id=binding.agent_id,
                request_id=data["request_id"],
                status=status,
                output=output
                or (
                    "Project is ready."
                    if project["stage"] == "ready"
                    else "Configure a project root before preparation."
                ),
                project=project,
                architect_decision=project.get("architect_decision"),
            )
            if status == "error":
                packet["error_type"] = project.get("reason") or (
                    "workspace_unconfigured"
                    if project["stage"] == "unconfigured"
                    else "workspace_not_ready"
                )
            return packet
        project = self.project.snapshot()
        workspace = (
            await self.project.refresh_snapshot(binding.domain_id)
            if binding.domain_id
            else None
        )
        state = self.domains.snapshot(binding.domain_id) if binding.domain_id else None
        capacity = self.project.capacity_snapshot(binding.domain_id)
        ready = project["stage"] == "ready"
        active = state is not None and state["state"] in ("active", "background")
        can_run = bool(
            ready
            and active
            and state["execution_state"] == "idle"
            and workspace["stage"] == "ready"
            and self.domains.can_run(binding.domain_id)
        )
        can_start = bool(
            ready
            and self.application_state is not None
            and self.application_state.admission_open
            and binding.domain_id
            and capacity["available"]
            and not active
            and workspace["stage"] != "failed"
            and state["state"] == "inactive"
            and not workspace.get("reservation")
        )
        reason = (
            (
                project.get("reason")
                or (
                    "workspace_unconfigured"
                    if project["stage"] == "unconfigured"
                    else "workspace_not_ready"
                )
            )
            if not ready
            else (
                workspace.get("reason")
                if workspace and workspace.get("reason")
                else (
                    "capacity_limit"
                    if binding.domain_id and not capacity["available"] and not active
                    else (
                        "workspace_busy"
                        if workspace and workspace.get("reservation") and not active
                        else (
                            "sdk_error"
                            if active
                            and not self.domains.owner_healthy(binding.domain_id)
                            else "domain_busy" if active and not can_run else None
                        )
                    )
                )
            )
        )
        return dict(
            type="agent_status",
            agent_id=binding.agent_id,
            request_id=data["request_id"],
            execution_kind=binding.execution_kind,
            domain_id=binding.domain_id,
            project=project,
            workspace=workspace,
            domain_state=state,
            capabilities=dict(
                protocol_version=2,
                state_store=self.application_state_status(),
                can_start=can_start,
                can_run=can_run,
                can_prepare_project=binding.agent_id == "systems-architect"
                and project["stage"] in ("needs_architect", "failed")
                and not self.project.initialized,
                tools=["Read", "Edit", "Bash"] if can_run else [],
                execution_capacity=capacity,
                reason=reason,
            ),
        )

    async def _route(self, data, histories, context, emit):
        kind = data.get("type", "conversation")
        if isinstance(kind, str) and kind in INTERACTIONS:
            return [await self._interaction(data)]
        if _is_domain_request(data):
            immediate = []
            collecting = True

            async def sink(packet):
                if collecting:
                    immediate.append(packet)
                if emit is not None:
                    await emit(packet)

            try:
                await self.domains.handle(data, context=context, emit=sink)
            finally:
                collecting = False
            return immediate
        if kind != "conversation":
            return [
                make_error(
                    data.get("agent_id", ""),
                    data.get("task", ""),
                    "invalid_request",
                    "Unknown typed operation",
                )
            ]
        request = parse_request({**data, "request_id": context.request_id})
        error = validate_request(request)
        if error:
            return [
                make_error(request.agent_id, request.task, "invalid_request", error)
            ]
        if not isinstance(request.agent_id, str) or not isinstance(request.task, str):
            return [
                make_error(
                    "", "", "invalid_request", "agent_id and task must be strings"
                )
            ]
        if not validate_agent_id(request.agent_id):
            return [
                make_error(
                    request.agent_id,
                    request.task,
                    "invalid_request",
                    "agent_id contains invalid characters",
                )
            ]
        try:
            binding = self.bindings.resolve_binding(request.agent_id)
        except InvalidBinding:
            return [
                make_error(
                    request.agent_id,
                    request.task,
                    "invalid_binding",
                    "Agent binding is unavailable",
                )
            ]
        if binding.execution_kind == "working":
            return [
                make_error(
                    request.agent_id,
                    request.task,
                    "domain_required",
                    "Use the character's domain controls for work.",
                    binding=asdict(binding),
                    execution_kind=binding.execution_kind,
                    domain_id=binding.domain_id,
                    required_action=(
                        "activate_domain"
                        if self.project.snapshot()["stage"] == "ready"
                        else "project_setup"
                    ),
                )
            ]
        self._event("engine_routing", context)
        return [await self._conversation(data, histories, context)]

    def _message(self, context, role, content, outcome, metadata=None):
        if self._recorder is not None and context.agent_id is not None:
            self._recorder.message(
                context,
                role,
                content,
                outcome,
                provider_session_id=metadata.provider_session_id if metadata else None,
            )

    async def _conversation(self, data, histories, context):
        metadata = ExecutionMetadata()
        task = data.get("task")
        record = context.agent_id is not None and isinstance(task, str) and bool(task)
        if record:
            self._message(context, "user", task, "input")
        try:
            operation = asyncio.current_task()
            self._npc_tasks.add(operation)
            try:
                resp = await self._call_conversation(data, histories, metadata)
            finally:
                if metadata.cleanup_failed:
                    self.project.note_cleanup_failure()
                self._npc_tasks.discard(operation)
        except asyncio.CancelledError:
            if record:
                self._message(context, "error", "cancelled", "cancelled", metadata)
            raise
        except Exception:
            if record:
                self._message(context, "error", "engine_error", "failure", metadata)
            raise
        if record:
            success = resp.get("status") == "ok"
            self._message(
                context,
                "assistant" if success else "error",
                resp.get("output", "") if success else "conversation_error",
                "success" if success else "failure",
                metadata,
            )
        if metadata.context_sources is not None:
            self._event(
                "context_composed", context, context_sources=metadata.context_sources
            )
        return resp

    async def _call_conversation(self, data, histories, metadata):
        agent_id = data.get("agent_id")
        history = (
            histories.get(agent_id, [])
            if histories is not None and isinstance(agent_id, str)
            else None
        )
        if self._config.workspace_root_dir is None:
            try:
                context_packet = await owned_io(
                    compose_context,
                    self._config,
                    agent_id=agent_id,
                    execution_kind="extra",
                    domain_id=None,
                    project=self.project.snapshot(),
                    workspace=None,
                    tools=[],
                    permission_mode="dontAsk",
                    interaction="conversation",
                )
            except ContextError:
                return make_error(
                    agent_id or "",
                    data.get("task", ""),
                    "context_unavailable",
                    "Context is unavailable",
                )
            options = dict(metadata=metadata, context_packet=context_packet)
            response = (
                await self.conversation.handle_request(data, history, **options)
                if history is not None
                else await self.conversation.handle_request(data, **options)
            )
        else:
            response = await self._project_conversation(data, history, metadata)
        if histories is not None and history:
            histories[agent_id] = history
        return response

    async def _project_conversation(self, data, history, metadata):
        agent, task = data.get("agent_id"), data.get("task")
        if not validate_agent_id(agent) or not isinstance(task, str) or not task:
            return make_error(
                "", "", "invalid_request", "agent_id and task are required"
            )
        if load_agent(agent, registry=self.bindings) is None:
            return make_error(agent, task, "not_found", "Agent is unavailable")
        deadline = (
            asyncio.get_running_loop().time()
            + self._config.conversation_timeout_seconds
        )
        guidance = await self.project.interact_setup(
            agent, data.get("request_id", ""), deadline=deadline
        )
        if guidance is not None:
            return make_success(agent, task, guidance)
        turn = TurnIntent(
            str(uuid.uuid4()),
            data.get("request_id") or str(uuid.uuid4()),
            self.project.owner_run_id,
            agent,
            None,
            None,
            task,
        )
        prepared = None
        attempted = False
        outcome, output = "error", "Not executed: project preflight failed"
        response = None
        try:
            async with asyncio.timeout_at(deadline):
                memory = self.project.require_memory()
                attempted = True
                prepared = asyncio.create_task(self.project.prepare_memory_turn(turn))
                snapshot = await asyncio.shield(prepared)
                self.project.publish_memory(snapshot)
                context_packet = await owned_io(
                    compose_context,
                    self._config,
                    agent_id=agent,
                    execution_kind="extra",
                    domain_id=None,
                    project=self.project.snapshot(),
                    workspace=None,
                    tools=[],
                    permission_mode="dontAsk",
                    interaction="conversation",
                )
                response = await self.conversation.handle_request(
                    data,
                    history,
                    metadata=metadata,
                    prior_project_notes=snapshot.as_context(),
                    deadline=deadline,
                    context_packet=context_packet,
                )
                outcome = "success" if response.get("status") == "ok" else "error"
                output = (
                    response.get("output", "")
                    if outcome == "success"
                    else "Conversation failed"
                )
        except asyncio.CancelledError:
            outcome, output = "cancelled", "Cancelled before conversation completed"
            raise
        except TimeoutError:
            response = make_error(
                agent, task, "timeout", "Conversation deadline expired"
            )
        except Exception as error:
            response = make_error(
                agent,
                task,
                getattr(error, "code", "memory_unavailable"),
                "Project memory or workspace is unavailable",
            )
        finally:
            if attempted:

                async def settle():
                    if prepared is not None:
                        await _drain(prepared)
                        if not prepared.cancelled() and prepared.exception() is None:
                            self.project.publish_memory(prepared.result())
                    result = await owned_io(
                        memory.finish_turn,
                        turn.turn_id,
                        outcome=outcome,
                        output=output,
                        delta=metadata.memory_delta if outcome == "success" else None,
                    )
                    self.project.publish_memory(result)

                worker = asyncio.create_task(settle(), name="npc-memory-settlement")
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    await _drain(worker)
                    # An already completed response/history remains successful.
                    if outcome != "success":
                        raise
        return response

    async def _handle_connection(self, websocket):
        connection = ConnectionState(
            websocket,
            self.dispatch_raw,
            project_snapshot=self.project.snapshot,
            workspace_snapshot=self.project.workspace_snapshot,
        )
        self._connections.add(connection)
        context = RequestContext(
            connection.connection_id, str(uuid.uuid4()), None, "transport", None
        )
        self._event("connection_opened", context)

        async def watch_closed():
            await websocket.wait_closed()
            await connection.close()

        watcher = asyncio.create_task(watch_closed(), name="npc-peer-disconnect")
        try:
            async for raw in websocket:
                if self._stopping:
                    break
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    data = None
                operation = connection.submit(raw, data)
                if operation is not None:
                    self._connection_tasks.add(operation)
                    operation.add_done_callback(self._connection_tasks.discard)
        finally:
            await connection.close()
            watcher.cancel()
            await _drain(watcher)
            self._connections.discard(connection)
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
        await self.domains.shutdown()

    async def _shutdown(self):
        self._stopping = True
        failure = None
        try:
            await self._shutdown_domains()
        except BaseException as error:
            failure = error
        for connection in tuple(self._connections):
            await connection.close()
        for task in tuple(self._npc_tasks):
            task.cancel()
            await _drain(task)
        for task in tuple(self._connection_tasks):
            await _drain(task)
        if self._state_open_task is not None:
            await _drain(self._state_open_task)
        if self.application_state is not None:
            try:
                await self.application_state.close()
            except BaseException as error:
                failure = failure or error
        try:
            await self.project.close()
        except BaseException as error:
            failure = failure or error
        if failure is not None:
            raise failure

    async def serve(self, *, stop_event: asyncio.Event | None = None):
        """Close admission; drain domains, NPC/setup IO and run ownership, then logs."""
        clean = False
        primary = None
        cleanup = None

        async def shutdown():
            nonlocal cleanup
            if cleanup is None:
                cleanup = asyncio.create_task(self._shutdown())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await _drain(cleanup)
                raise

        try:
            await self.project.start()
            async with _drained_listener(
                websockets.serve(
                    self._handle_connection, LISTEN_HOST, LISTEN_PORT, origins=[None]
                )
            ):
                print(
                    f"Bridge running on ws://{LISTEN_HOST}:{LISTEN_PORT}",
                    file=sys.stderr,
                )
                self._event("bridge_started")
                try:
                    if stop_event is None:
                        await asyncio.Future()
                    else:
                        await stop_event.wait()
                except BaseException as error:
                    primary = error
                    raise
                finally:
                    try:
                        await shutdown()
                    except BaseException as error:
                        if primary is None or isinstance(error, asyncio.CancelledError):
                            raise
            clean = True
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                if cleanup is None:
                    await shutdown()
            except BaseException as error:
                clean = False
                if primary is None or isinstance(error, asyncio.CancelledError):
                    raise
            finally:
                self.close(clean=clean)


async def serve(*, stop_event: asyncio.Event | None = None):
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
        await server.serve(stop_event=stop_event)
        clean = True
    finally:
        if server is None:
            recorder.close(clean=False)
        else:
            server.close(clean=clean)
