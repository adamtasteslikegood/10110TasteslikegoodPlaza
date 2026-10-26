"""Generation-owned domain work, admission, bounded terminals and cleanup.

Socket tasks only await shielded work. A generation holds its reservation until
SDK, checkpoint and terminal-memory workers have all settled successfully enough
to confirm cleanup. Delivery is an independent best-effort observation.
"""

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from enum import Enum
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from bridge.context import compose_context
from bridge.agents import load_agent
from bridge.agent_bindings import require_working_binding, InvalidBinding
from bridge.config import BridgeConfig
from bridge.application_state import StateCommand, StateError, StateView
from datetime import datetime, timezone
from bridge.domain_protocol import DomainCommandError, error_packet
from bridge.domain_sdk import DomainSDKOwner, SDKOutcome
from bridge.domain_store import DomainSessionStore, MemoryStore
from bridge.domain_run_state import DurableRunState, settle_owned
from bridge.session_recovery import reconcile_memory
from bridge.session_recap import build_recap
from bridge.failure_diagnostics import (
    diagnostic_fields,
    exception_diagnostics,
    failure_reason,
)
from bridge.observability import BridgeRecorder, RequestContext
from bridge.project_memory import MemorySaveResult, TurnIntent
from bridge.readiness import owned_io, denial
from bridge.workspace_lease import WorkspaceLease

if TYPE_CHECKING:
    from bridge.project_service import ProjectService

DomainSink = Callable[[dict], Awaitable[None]]
# Existing server diagnostics import the credential-name inventory. This is not
# an execution path; Task 6 moves composition to the service-based manager.
_SDK_ENV_PASSTHROUGH = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_0AUTH_TOKEN",
]
MAX_OUTPUT_BYTES = 256 * 1024


class SessionState(Enum):
    INACTIVE = "inactive"
    ACTIVATING = "activating"
    ACTIVE = "active"
    BACKGROUND = "background"
    STOPPING = "stopping"
    CLEANUP_FAILED = "cleanup_failed"


async def deliver(emit, packet, recorder=None, context=None):
    try:
        async with asyncio.timeout(2):
            await emit(deepcopy(packet))
    except (Exception, asyncio.CancelledError) as error:
        if recorder is not None:
            recorder.event(
                (
                    "delivery_cancelled"
                    if isinstance(error, asyncio.CancelledError)
                    else "delivery_failed"
                ),
                context,
                outcome=(
                    "cancelled"
                    if isinstance(error, asyncio.CancelledError)
                    else "failure"
                ),
            )
        if (
            isinstance(error, asyncio.CancelledError)
            and asyncio.current_task().cancelling()
        ):
            # Detach a cancelled socket/control caller. Session-owned startup and
            # Run jobs are shielded separately and keep their immutable sink.
            raise


@dataclass
class _Run:
    command: dict
    context: RequestContext
    emit: DomainSink
    intent: TurnIntent
    admitted: asyncio.Future
    job: asyncio.Task | None = None
    accepted: bool = False
    preparing: bool = False
    execution_id: str | None = None
    memory_revision: int | None = None
    disposition: str | None = None


class _ExecutionReadiness:
    """Gate actual startup/turn/tool readiness against committed-state health."""

    def __init__(self, readiness, check):
        self._readiness, self._check = readiness, check

    def __getattr__(self, name):
        return getattr(self._readiness, name)

    async def check_tool(self, *args, **kwargs):
        self._check()
        result = await self._readiness.check_tool(*args, **kwargs)
        self._check()
        return result

    async def prepare_turn(self, *args, **kwargs):
        self._check()
        result = await self._readiness.prepare_turn(*args, **kwargs)
        self._check()
        return result

    def pre_tool_hook(self, *args, **kwargs):
        hook = self._readiness.pre_tool_hook(*args, **kwargs)

        async def guarded(*arguments):
            try:
                self._check()
                result = await hook(*arguments)
                self._check()
                return result
            except (StateError, DomainCommandError):
                on_denied = kwargs.get("on_denied")
                if on_denied is not None:
                    try:
                        on_denied(dict(readiness_category="readiness_error"))
                    except Exception:
                        pass
                return denial(
                    "Application state is unavailable; refresh domain status before restarting."
                )

        return guarded


class DomainSession:
    def __init__(
        self,
        domain_id: str,
        domain_session_id: str,
        *,
        config: BridgeConfig,
        project_service: "ProjectService",
        recorder: BridgeRecorder | None = None,
        store: DomainSessionStore | None = None,
        execution_id: str | None = None,
        coordinator=None,
        authority_check=None,
    ):
        self.domain_id, self.domain_session_id = domain_id, domain_session_id
        self.execution_id = execution_id or str(uuid4())
        self._coordinator = coordinator
        self._authority_check = authority_check
        self._lifecycle_stopped = False
        self._failure_outcome = None
        self.memory_reconciliation = []
        self._config, self._service, self._recorder = config, project_service, recorder
        self._state = SessionState.INACTIVE
        self._workspace = None
        self._memory = None
        self._readiness = None
        self._lease = None
        self._owner = None
        self._reserve_task = None
        self._startup = None
        self._start_gate = asyncio.Event()
        self._stop_task = None
        self._stopping = False
        self._broken = False
        self._inflight = None
        self._jobs = set()
        # The synchronous terminal-only store remains a direct-session test seam.
        # A coordinator-backed owner never creates or falls back to that store.
        self._store = (
            (store if store is not None else MemoryStore())
            if coordinator is None
            else None
        )
        self._run_state = (
            DurableRunState(coordinator, domain_session_id, self.execution_id)
            if coordinator is not None
            else None
        )
        self._recap_supplied = False
        self._memory_revision = None
        # The store intentionally rejects concurrent file-lock acquisition.
        # Serialize this generation's own checkpoints while retaining explicit
        # failures from unrelated NPC/process actors and storage faults.
        self._memory_lock = asyncio.Lock()
        self._background_checkpoint = None

    @property
    def model(self):
        return self._config.model_for(self._config.domain_tier)

    @property
    def state(self):
        return self._state

    @property
    def owner_healthy(self):
        return bool(
            self._owner is not None and self._owner.healthy and not self._broken
        )

    @property
    def can_run(self):
        return (
            self._state in (SessionState.ACTIVE, SessionState.BACKGROUND)
            and self.owner_healthy
            and not (self._stopping or self._inflight is not None)
            and (self._coordinator is None or self._coordinator.admission_open)
        )

    @property
    def clean_inactive(self):
        return (
            self._state is SessionState.INACTIVE
            and not (self._lease and self._lease.held)
            and all(task.done() for task in self._jobs)
            and (self._startup is None or self._startup.done())
        )

    def _identity(self):
        return dict(
            project_id=(
                self._workspace.project_id
                if self._workspace
                else self._service.snapshot().get("project_id")
            ),
            workspace_id=self._workspace.workspace_id if self._workspace else None,
            domain_id=self.domain_id,
            domain_session_id=self.domain_session_id,
            execution_id=self.execution_id,
        )

    def snapshot(self):
        execution = "idle"
        if self._state in (SessionState.STOPPING, SessionState.CLEANUP_FAILED):
            execution = self._state.value
        elif self._inflight is not None:
            execution = "running"
        return dict(
            type="domain_state",
            protocol_version=2,
            **self._identity(),
            state=self._state.value,
            execution_state=execution,
        )

    def _transition(self, state):
        if self._state is state:
            return
        self._state = state
        if self._recorder:
            context = RequestContext(
                None, str(uuid4()), None, "domain", self.model, self.domain_id
            )
            self._recorder.event("domain_transition", context, domain_state=state.value)

    def _track(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._jobs.add(task)

        def done(job):
            self._jobs.discard(job)
            if not job.cancelled():
                job.exception()

        task.add_done_callback(done)
        return task

    async def _reserve(self):
        self._service.reserve_capacity(self)
        self._workspace = await self._service.prepare_domain(self.domain_id)
        self._memory = self._service.require_memory()
        self._readiness = self._service.require_readiness(self.domain_id)
        if self._coordinator is not None:
            self._readiness = _ExecutionReadiness(
                self._readiness, self._require_state_ready
            )

        def acquire():
            self._lease = WorkspaceLease.acquire(
                self._workspace,
                domain_id=self.domain_id,
                domain_session_id=self.domain_session_id,
            )

        await owned_io(acquire)
        self._service.publish_reservation(self._lease)
        if self._coordinator is not None:
            view = self._coordinator.snapshot()
            terminals = {(t.session_id, t.request_id): t for t in view.terminals}
            for request in view.requests:
                key = request.session_id, request.request_id
                if (
                    request.session_id == self.domain_session_id
                    and request.disposition == "recovered"
                    and key in terminals
                ):
                    result = await reconcile_memory(
                        self._service, request, terminals[key], lease=self._lease
                    )
                    self.memory_reconciliation.append(
                        dict(
                            request_id=request.request_id,
                            turn_id=request.turn_id,
                            **result,
                        )
                    )
        self._owner = DomainSDKOwner(
            self._config, self._workspace, self._lease, self._readiness
        )
        if not self._stopping:
            self._transition(SessionState.ACTIVATING)

    def _register_start(self):
        if self._reserve_task is None:
            self._reserve_task = asyncio.create_task(self._reserve())
            self._startup = asyncio.create_task(self._start_owned())
            self._startup.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )

    async def _reserve_start(self):
        """Reserve and register an owned continuation before activation delivery."""
        self._register_start()
        await asyncio.shield(self._reserve_task)
        return self.snapshot()

    async def _start_owned(self):
        try:
            await self._reserve_task
            await self._start_gate.wait()
            if not self._stopping:
                await self._owner.start()
            if not self._stopping:
                self._transition(SessionState.ACTIVE)
        except Exception:
            self._failure_outcome = "startup_failed"
            if not self._stopping:
                await self._cleanup()
            raise
        return self.snapshot()

    async def start(self) -> dict:
        try:
            await self._reserve_start()
        finally:
            self._start_gate.set()
        await asyncio.shield(self._startup)
        return self.snapshot()

    async def _error(self, command, code, emit, context, started):
        diagnostics = exception_diagnostics(DomainCommandError(code))
        if self._recorder:
            self._recorder.event(
                "request_rejected" if code == "invalid_request" else "request_failed",
                context,
                outcome="rejected" if code == "invalid_request" else "failure",
                duration_ms=(time.monotonic() - started) * 1000,
                **diagnostics,
            )
        await deliver(
            emit,
            dict(
                error_packet(
                    command,
                    code,
                    project_id=self._identity()["project_id"],
                    workspace_id=self._identity()["workspace_id"],
                ),
                **diagnostics,
            ),
            self._recorder,
            context,
        )

    async def admit_query(
        self, command: dict, *, context: RequestContext, emit: DomainSink
    ) -> None:
        # No await before installing the single in-flight record.
        started = time.monotonic()
        command = dict(command)
        try:
            self._require_state_ready()
        except (StateError, DomainCommandError) as error:
            return await self._error(command, error.code, emit, context, started)
        if (
            self._authority_check is not None
            and command.get("execution_id") != self.execution_id
        ):
            return await self._error(command, "stale_execution", emit, context, started)
        try:
            require_working_binding(command.get("agent_id"), self.domain_id)
        except InvalidBinding:
            return await self._error(command, "invalid_binding", emit, context, started)
        if command.get("domain_id") != self.domain_id:
            return await self._error(command, "invalid_binding", emit, context, started)
        if command.get("domain_session_id") != self.domain_session_id:
            return await self._error(
                command, "session_unavailable", emit, context, started
            )
        if self._inflight is not None:
            run = self._inflight
            if run.command["request_id"] == command["request_id"]:
                if (run.command["agent_id"], run.command["task"]) != (
                    command["agent_id"],
                    command["task"],
                ):
                    return await self._error(
                        command, "invalid_request", emit, context, started
                    )
                packet = await asyncio.shield(run.admitted)
                return await deliver(emit, packet, self._recorder, context)
        if self._run_state is not None:
            request = self._run_state.find_request(command["request_id"])
            if request is not None:
                if (request.agent_id, request.task) != (
                    command["agent_id"],
                    command["task"],
                ):
                    return await self._error(
                        command, "invalid_request", emit, context, started
                    )
                packet = self._run_state.find_terminal(command["request_id"])
                if packet is None:
                    packet = dict(
                        type="domain_accepted",
                        **self._identity(),
                        request_id=request.request_id,
                        agent_id=request.agent_id,
                        task=request.task,
                        execution_state="running",
                    )
                    packet["execution_id"] = request.execution_id
                return await deliver(emit, packet, self._recorder, context)
        else:
            packet = self._store.find_request(command["request_id"])
            if packet is not None:
                if (packet["agent_id"], packet["task"]) != (
                    command["agent_id"],
                    command["task"],
                ):
                    return await self._error(
                        command, "invalid_request", emit, context, started
                    )
                return await deliver(emit, packet, self._recorder, context)
        if self._inflight is not None:
            return await self._error(command, "domain_busy", emit, context, started)
        if (
            self._state not in (SessionState.ACTIVE, SessionState.BACKGROUND)
            or self._stopping
        ):
            return await self._error(
                command, "session_unavailable", emit, context, started
            )
        if self._broken:
            return await self._error(command, "sdk_error", emit, context, started)
        definition = load_agent(command["agent_id"])
        if not definition:
            return await self._error(command, "invalid_request", emit, context, started)
        origin = RequestContext(
            context.connection_id,
            command["request_id"],
            command["agent_id"],
            "domain",
            self.model,
            self.domain_id,
        )
        run = _Run(
            command,
            origin,
            emit,
            TurnIntent(
                str(uuid4()),
                command["request_id"],
                self._service.owner_run_id,
                command["agent_id"],
                self.domain_id,
                self.domain_session_id,
                command["task"],
                workspace_id=self._workspace.workspace_id,
            ),
            asyncio.get_running_loop().create_future(),
        )
        run.execution_id = self.execution_id
        self._inflight = run
        run.job = self._track(self._run(run, definition))
        await asyncio.shield(run.admitted)

    async def _save(self, run, outcome):
        async with self._memory_lock:
            try:
                result = await owned_io(
                    self._memory.finish_turn,
                    run.intent.turn_id,
                    outcome=outcome.status,
                    output=outcome.output,
                    delta=outcome.memory_delta,
                )
            except Exception:
                result = MemorySaveResult(
                    False, self._memory_revision, "memory_unavailable"
                )
            if result.saved:
                self._memory_revision = result.revision
            elif result.revision is None:
                result = MemorySaveResult(
                    False, self._memory_revision, result.error_type
                )
            self._service.publish_memory(result)
            return result

    def _require_state_ready(self):
        if self._coordinator is not None and not self._coordinator.admission_open:
            raise StateError(self._coordinator.health or "state_store_busy")
        if self._authority_check is not None:
            self._authority_check(self)

    async def _require_owner_ready(self):
        self._require_state_ready()
        if self._stopping:
            raise DomainCommandError("session_unavailable")
        try:
            # The generation already started this owner. Its public start is an
            # idempotent readiness observation, never a reconnect/new worker.
            await self._owner.start()
        except Exception as error:
            if self._stopping:
                raise DomainCommandError("session_unavailable") from None
            self._broken = True
            safe = DomainCommandError(getattr(error, "code", "sdk_error"))
            for key, value in exception_diagnostics(error, "transport_error").items():
                setattr(safe, key, value)
            raise safe from None
        if self._stopping:
            raise DomainCommandError("session_unavailable")

    async def _run(self, run, definition):
        started = time.monotonic()
        prepare_attempted = False
        try:
            if self._stopping:
                raise DomainCommandError("session_unavailable")
            run.preparing = True
            async with self._memory_lock:
                await self._require_owner_ready()
                prepare_attempted = True
                snapshot = await self._readiness.prepare_turn(run.intent)
                self._memory_revision = run.memory_revision = snapshot.revision
                self._service.publish_memory(snapshot)
            context_packet = await owned_io(
                compose_context,
                self._config,
                agent_id=run.command["agent_id"],
                execution_kind="domain",
                domain_id=self.domain_id,
                project=self._service.snapshot(),
                workspace=self._service.workspace_snapshot(self.domain_id),
                tools=["Read", "Edit", "Bash"],
                permission_mode=self._config.domain_permission_mode,
                interaction="explicit_run",
            )
            if self._coordinator is not None and not self._recap_supplied:
                view = self._coordinator.snapshot()
                if (
                    not isinstance(view, StateView)
                    or view.project_id != self._workspace.project_id
                ):
                    raise StateError("state_store_invalid")
                context_packet = replace(
                    context_packet,
                    continuity=build_recap(
                        view,
                        self.domain_session_id,
                        exclude_request_id=run.command["request_id"],
                    ),
                )
            # The owner may have failed while checkpoint IO was awaiting.
            await self._require_owner_ready()
            cancelled = False
            if self._run_state is not None:
                _, cancelled = await self._run_state.accept(
                    run.intent, run.memory_revision
                )
                run.disposition = "accepted"
            run.accepted = True
            # Acceptance may commit after Stop cancelled its await. Archive the
            # originating input before either accepted path can finish the Run.
            if self._recorder:
                self._recorder.message(
                    run.context, "user", run.command["task"], "input"
                )
            if cancelled or self._stopping:
                raise asyncio.CancelledError()
            run.preparing = False
        except (Exception, asyncio.CancelledError) as error:
            run.preparing = False
            # prepare_turn can fail/cancel after its durable begin. Its owned IO
            # has drained; finish safely settles that intent if it exists. An
            # already-dead owner never began intent and must not touch memory.
            if run.accepted:
                outcome = SDKOutcome("", "cancelled", "stopped", None, None)
                terminal = await self._finish_run(run, outcome, started)
                if not run.admitted.done():
                    run.admitted.set_result(terminal)
                return
            if prepare_attempted:
                await settle_owned(
                    self._save(
                        run,
                        SDKOutcome(
                            "Not executed: admission did not complete.",
                            "error",
                            "not_executed",
                            None,
                            None,
                        ),
                    )
                )
            packet = error_packet(
                run.command,
                getattr(error, "code", "memory_unavailable"),
                project_id=self._identity()["project_id"],
                workspace_id=self._identity()["workspace_id"],
            )
            cancelled = isinstance(error, asyncio.CancelledError)
            diagnostics = (
                {"terminal_reason": "stopped"}
                if cancelled
                else exception_diagnostics(error)
            )
            packet.update(diagnostics)
            if self._recorder:
                self._recorder.event(
                    "request_cancelled" if cancelled else "request_failed",
                    run.context,
                    outcome="cancelled" if cancelled else "failure",
                    duration_ms=(time.monotonic() - started) * 1000,
                    **diagnostics,
                )
            self._inflight = None
            await settle_owned(deliver(run.emit, packet, self._recorder, run.context))
            run.admitted.set_result(packet)
            return
        packet = dict(
            type="domain_accepted",
            **self._identity(),
            request_id=run.command["request_id"],
            agent_id=run.command["agent_id"],
            task=run.command["task"],
            execution_state="running",
        )
        # Sink failure cannot roll admission back; release execution after the
        # acceptance attempt even when the originating socket disappeared.
        run.preparing = True
        _, cancelled = await settle_owned(
            deliver(run.emit, packet, self._recorder, run.context)
        )
        run.admitted.set_result(packet)
        run.preparing = False
        if cancelled:
            await self._finish_run(
                run, SDKOutcome("", "cancelled", "stopped", None, None), started
            )
            return
        try:
            run.preparing = True
            if self._run_state is not None:
                _, cancelled = await self._run_state.dispatch(run.command["request_id"])
                run.disposition = "dispatched"
                if cancelled:
                    raise asyncio.CancelledError()
            run.preparing = False
            if self._stopping:
                outcome = SDKOutcome("", "cancelled", "stopped", None, None)
            else:
                self._require_state_ready()
                # Only this actual invocation consumes first-entry continuity.
                # Acceptance, dispatch failure and retained duplicate replay do not.
                recap = context_packet.continuity
                if self._recorder:
                    supplied = (
                        dict(
                            domain_session_id=self.domain_session_id,
                            execution_id=self.execution_id,
                            recap_source_high_water=recap.source_high_water,
                            recap_source_output_ids=recap.source_output_ids,
                            recap_notice_output_id=recap.notice_output_id,
                        )
                        if recap is not None
                        else {}
                    )
                    self._recorder.event(
                        "execution_started",
                        run.context,
                        context_sources=context_packet.diagnostics(),
                        **supplied,
                    )
                self._recap_supplied = True
                outcome = await self._owner.execute(
                    agent_id=run.command["agent_id"],
                    definition=definition,
                    task=run.command["task"],
                    prior_project_notes=snapshot.as_context(),
                    context_packet=context_packet,
                )
        except asyncio.CancelledError:
            run.preparing = False
            outcome = SDKOutcome("", "cancelled", "stopped", None, None)
        except StateError:
            run.preparing = False
            outcome = SDKOutcome("", "error", "not_executed", None, None)
        except Exception:
            run.preparing = False
            self._broken = True
            outcome = SDKOutcome("", "error", "transport_error", None, None)
        await self._finish_run(run, outcome, started)

    def _uncommitted(self, run, code, output, saved):
        return dict(
            type="domain_result",
            **self._identity(),
            request_id=run.command["request_id"],
            agent_id=run.command["agent_id"],
            task=run.command["task"],
            output=output,
            status="error",
            reason=code,
            error_type=code,
            committed=False,
            memory=asdict(saved) if saved is not None else None,
        )

    async def _finish_run(self, run, outcome, started):
        if outcome.reason in (
            "transport_error",
            "missing_terminal",
            "output_limit",
        ) or (outcome.status == "cancelled" and not self._stopping):
            self._broken = True
        data = outcome.output.encode("utf-8", errors="replace")
        truncated = len(data) > MAX_OUTPUT_BYTES or outcome.reason == "output_limit"
        output = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore")
        outcome = SDKOutcome(
            output,
            outcome.status,
            (
                failure_reason(outcome.reason)
                if outcome.status == "error"
                else outcome.reason
            ),
            outcome.provider_session_id,
            outcome.memory_delta,
            **diagnostic_fields(
                readiness_category=outcome.readiness_category,
                tool_name=outcome.tool_name,
                tool_use_id=outcome.tool_use_id,
            ),
        )
        saved, _ = await settle_owned(self._save(run, outcome))
        terminal = dict(
            type="domain_result",
            **self._identity(),
            request_id=run.command["request_id"],
            agent_id=run.command["agent_id"],
            task=run.command["task"],
            output=output,
            output_id=None,  # Store assigns the ID, preserving wire field order.
            status=outcome.status,
            reason=outcome.reason,
            truncated=truncated,
            memory=asdict(saved),
        )
        if outcome.readiness_category is not None:
            terminal["readiness_category"] = outcome.readiness_category
        if self._run_state is None:
            terminal = self._store.append(terminal)
        else:
            try:
                commit, _ = await self._run_state.terminal(
                    run.command["request_id"], terminal
                )
                terminal = commit.result["terminal"]
                run.disposition = "terminal"
            except StateError as error:
                terminal = self._uncommitted(run, error.code, output, saved)
        self._inflight = None
        if self._recorder:
            record_outcome = (
                "failure" if terminal["status"] == "error" else terminal["status"]
            )
            self._recorder.message(
                run.context,
                "assistant" if terminal["status"] == "success" else "error",
                (
                    output
                    if outcome.status in ("success", "error")
                    else "cancelled" if outcome.status == "cancelled" else "sdk_error"
                ),
                record_outcome,
                output_id=terminal.get("output_id"),
                provider_session_id=outcome.provider_session_id,
            )
            self._recorder.event(
                {
                    "success": "request_completed",
                    "error": "request_failed",
                    "cancelled": "request_cancelled",
                }[terminal["status"]],
                run.context,
                outcome=record_outcome,
                duration_ms=(time.monotonic() - started) * 1000,
                terminal_reason=terminal["reason"],
                readiness_category=outcome.readiness_category,
                tool_name=outcome.tool_name,
                tool_use_id=outcome.tool_use_id,
            )
        await settle_owned(deliver(run.emit, terminal, self._recorder, run.context))
        return terminal

    async def _checkpoint(self, event):
        async with self._memory_lock:
            try:
                result = await owned_io(
                    self._memory.checkpoint_lifecycle,
                    domain_id=self.domain_id,
                    domain_session_id=self.domain_session_id,
                    event=event,
                )
            except Exception:
                result = MemorySaveResult(
                    False, self._memory_revision, "memory_unavailable"
                )
            if result.saved:
                self._memory_revision = max(self._memory_revision or 0, result.revision)
            elif result.revision is None:
                result = MemorySaveResult(
                    False, self._memory_revision, result.error_type
                )
            self._service.publish_memory(result)

    def background(self) -> dict:
        if self._state not in (SessionState.ACTIVE, SessionState.BACKGROUND):
            raise DomainCommandError("session_unavailable")
        if self._state is not SessionState.BACKGROUND:
            self._transition(SessionState.BACKGROUND)
            # One bounded background-checkpoint worker. Repeated visibility
            # toggles while this fact is being saved share that checkpoint.
            if (
                self._background_checkpoint is None
                or self._background_checkpoint.done()
            ):
                self._background_checkpoint = self._track(
                    self._checkpoint("background")
                )
        return self.snapshot()

    def refocus(self) -> dict:
        if self._state not in (SessionState.ACTIVE, SessionState.BACKGROUND):
            raise DomainCommandError("session_unavailable")
        self._transition(SessionState.ACTIVE)
        return self.snapshot()

    async def _cleanup(self):
        clean = True
        try:
            if self._owner:
                clean = (await self._owner.stop()).clean
            if self._inflight and self._inflight.preparing:
                self._inflight.job.cancel()
            for task in tuple(self._jobs):
                await asyncio.shield(task)
            if self._memory and self._lease:
                await self._checkpoint("stop" if clean else "cleanup_failed")
            if self._coordinator is not None:
                await self._coordinator.drain()
            if clean and self._coordinator is not None and not self._lifecycle_stopped:
                try:
                    await self._coordinator.commit(
                        StateCommand(
                            "stop",
                            dict(
                                execution_id=self.execution_id,
                                outcome=self._failure_outcome or "stopped",
                                timestamp=datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                    )
                    self._lifecycle_stopped = True
                except StateError:
                    # A completed disk failure is not a running SDK or writer.
                    # Storage remains closed/visible; actual ownership may now
                    # release. End must still commit its own durable marker.
                    await self._coordinator.drain()
            if clean and self._lease:
                await owned_io(self._lease.release, cleanup_confirmed=True)
        except Exception:
            clean = False
        if self._lease:
            self._service.publish_cleanup(self._lease, clean=clean)
        if clean:
            self._service.release_capacity(self)
        self._transition(
            SessionState.INACTIVE if clean else SessionState.CLEANUP_FAILED
        )
        return self.snapshot()

    async def _stop_owned(self):
        if self._reserve_task:
            try:
                await self._reserve_task
            except Exception:
                pass
        result = await self._cleanup()
        if self._startup:
            try:
                await self._startup
            except Exception:
                pass
        return result

    async def stop(self) -> dict:
        if self.clean_inactive and self._reserve_task is None:
            return self.snapshot()
        if self._stop_task is None or (
            self._stop_task.done() and self._state is SessionState.CLEANUP_FAILED
        ):
            self._stopping = True
            self._transition(SessionState.STOPPING)
            self._start_gate.set()
            self._stop_task = asyncio.create_task(self._stop_owned())
        # Stop's caller may disconnect, but ownership must still drain before it
        # can report cancellation to a shutdown caller.
        cancelled = None
        while not self._stop_task.done():
            try:
                await asyncio.shield(self._stop_task)
            except asyncio.CancelledError as error:
                cancelled = error
        result = self._stop_task.result()
        if cancelled:
            raise cancelled
        return result

    def replay(self, cursor: int) -> list[dict]:
        window = (
            self._coordinator.replay(self.domain_session_id, cursor)
            if self._coordinator is not None
            else self._store.replay(cursor)
        )
        packets = window.entries
        packets.append(
            dict(
                self.snapshot(),
                type="resume_complete",
                high_water_mark=str(window.high_water_mark),
                earliest_output_id=(
                    str(window.earliest_output_id)
                    if window.earliest_output_id is not None
                    else None
                ),
                history_gap=window.history_gap,
            )
        )
        return packets
