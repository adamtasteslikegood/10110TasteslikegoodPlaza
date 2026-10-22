"""Generation-owned domain work, admission, bounded terminals and cleanup.

Socket tasks only await shielded work. A generation holds its reservation until
SDK, checkpoint and terminal-memory workers have all settled successfully enough
to confirm cleanup. Delivery is an independent best-effort observation.
"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import Enum
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from bridge.agents import load_agent
from bridge.config import BridgeConfig
from bridge.domain_protocol import DomainCommandError, error_packet
from bridge.domain_sdk import DomainSDKOwner, SDKOutcome
from bridge.observability import BridgeRecorder, RequestContext
from bridge.project_memory import MemorySaveResult, TurnIntent
from bridge.readiness import owned_io
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
MAX_ENTRIES = 256
MAX_OUTPUT_BYTES = 256 * 1024
MAX_TOTAL_OUTPUT_BYTES = 4 * 1024 * 1024


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


class DomainSession:
    def __init__(
        self,
        domain_id: str,
        domain_session_id: str,
        *,
        config: BridgeConfig,
        project_service: "ProjectService",
        recorder: BridgeRecorder | None = None
    ):
        self.domain_id, self.domain_session_id = domain_id, domain_session_id
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
        self._entries = deque()
        self._output_bytes = 0
        self._highwater = 0
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
        )

    def snapshot(self):
        execution = "idle"
        if self._state in (SessionState.STOPPING, SessionState.CLEANUP_FAILED):
            execution = self._state.value
        elif self._inflight is not None:
            execution = "running"
        return dict(
            type="domain_state",
            **self._identity(),
            state=self._state.value,
            execution_state=execution
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

        def acquire():
            self._lease = WorkspaceLease.acquire(
                self._workspace,
                domain_id=self.domain_id,
                domain_session_id=self.domain_session_id,
            )

        await owned_io(acquire)
        self._service.publish_reservation(self._lease)
        self._owner = DomainSDKOwner(
            self._config, self._workspace, self._lease, self._readiness
        )
        if not self._stopping:
            self._transition(SessionState.ACTIVATING)

    async def _reserve_start(self):
        """Reserve and register an owned continuation before activation delivery."""
        if self._reserve_task is None:
            self._reserve_task = asyncio.create_task(self._reserve())
            self._startup = asyncio.create_task(self._start_owned())
            self._startup.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
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

    async def _error(self, command, code, emit, context):
        await deliver(
            emit,
            error_packet(
                command,
                code,
                project_id=self._identity()["project_id"],
                workspace_id=self._identity()["workspace_id"],
            ),
            self._recorder,
            context,
        )

    async def admit_query(
        self, command: dict, *, context: RequestContext, emit: DomainSink
    ) -> None:
        # No await before installing the single in-flight record.
        command = dict(command)
        if command.get("domain_session_id") != self.domain_session_id:
            return await self._error(command, "session_unavailable", emit, context)
        for packet in self._entries:
            if packet["request_id"] == command["request_id"]:
                if (packet["agent_id"], packet["task"]) != (
                    command["agent_id"],
                    command["task"],
                ):
                    return await self._error(command, "invalid_request", emit, context)
                return await deliver(emit, packet, self._recorder, context)
        if self._inflight is not None:
            run = self._inflight
            if run.command["request_id"] == command["request_id"]:
                if run.command != command:
                    return await self._error(command, "invalid_request", emit, context)
                packet = await asyncio.shield(run.admitted)
                return await deliver(emit, packet, self._recorder, context)
            return await self._error(command, "domain_busy", emit, context)
        if (
            self._state not in (SessionState.ACTIVE, SessionState.BACKGROUND)
            or self._stopping
        ):
            return await self._error(command, "session_unavailable", emit, context)
        if self._broken:
            return await self._error(command, "sdk_error", emit, context)
        definition = load_agent(command["agent_id"])
        if not definition:
            return await self._error(command, "invalid_request", emit, context)
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

    async def _require_owner_ready(self):
        if self._stopping:
            raise DomainCommandError("session_unavailable")
        try:
            # The generation already started this owner. Its public start is an
            # idempotent readiness observation, never a reconnect/new worker.
            await self._owner.start()
        except Exception:
            if self._stopping:
                raise DomainCommandError("session_unavailable") from None
            self._broken = True
            raise DomainCommandError("sdk_error") from None
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
                self._memory_revision = snapshot.revision
                self._service.publish_memory(snapshot)
            run.preparing = False
            # The owner may have failed while checkpoint IO was awaiting.
            await self._require_owner_ready()
        except (Exception, asyncio.CancelledError) as error:
            run.preparing = False
            # prepare_turn can fail/cancel after its durable begin. Its owned IO
            # has drained; finish safely settles that intent if it exists. An
            # already-dead owner never began intent and must not touch memory.
            if prepare_attempted:
                await self._save(
                    run,
                    SDKOutcome(
                        "Not executed: admission did not complete.",
                        "error",
                        "not_executed",
                        None,
                        None,
                    ),
                )
            packet = error_packet(
                run.command,
                getattr(error, "code", "memory_unavailable"),
                project_id=self._identity()["project_id"],
                workspace_id=self._identity()["workspace_id"],
            )
            self._inflight = None
            await deliver(run.emit, packet, self._recorder, run.context)
            run.admitted.set_result(packet)
            return
        run.accepted = True
        packet = dict(
            type="domain_accepted",
            **self._identity(),
            request_id=run.command["request_id"],
            agent_id=run.command["agent_id"],
            task=run.command["task"],
            execution_state="running"
        )
        # Sink failure cannot roll admission back; release execution after the
        # acceptance attempt even when the originating socket disappeared.
        await deliver(run.emit, packet, self._recorder, run.context)
        run.admitted.set_result(packet)
        if self._recorder:
            self._recorder.message(run.context, "user", run.command["task"], "input")
            self._recorder.event("execution_started", run.context)
        try:
            if self._stopping:
                outcome = SDKOutcome("", "cancelled", "stopped", None, None)
            else:
                outcome = await self._owner.execute(
                    agent_id=run.command["agent_id"],
                    definition=definition,
                    task=run.command["task"],
                    prior_project_notes=snapshot.as_context(),
                )
        except Exception:
            self._broken = True
            outcome = SDKOutcome("", "error", "transport_error", None, None)
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
            outcome.reason,
            outcome.provider_session_id,
            outcome.memory_delta,
        )
        saved = await self._save(run, outcome)
        self._highwater += 1
        terminal = dict(
            type="domain_result",
            **self._identity(),
            request_id=run.command["request_id"],
            agent_id=run.command["agent_id"],
            task=run.command["task"],
            output=output,
            output_id=str(self._highwater),
            status=outcome.status,
            reason=outcome.reason,
            truncated=truncated,
            memory=asdict(saved)
        )
        self._entries.append(terminal)
        self._output_bytes += len(output.encode("utf-8"))
        while (
            len(self._entries) > MAX_ENTRIES
            or self._output_bytes > MAX_TOTAL_OUTPUT_BYTES
        ):
            self._output_bytes -= len(self._entries.popleft()["output"].encode("utf-8"))
        self._inflight = None
        if self._recorder:
            record_outcome = "failure" if outcome.status == "error" else outcome.status
            self._recorder.message(
                run.context,
                "assistant" if outcome.status == "success" else "error",
                (
                    output
                    if outcome.status == "success"
                    else "cancelled" if outcome.status == "cancelled" else "sdk_error"
                ),
                record_outcome,
                output_id=terminal["output_id"],
                provider_session_id=outcome.provider_session_id,
            )
            self._recorder.event(
                {
                    "success": "request_completed",
                    "error": "request_failed",
                    "cancelled": "request_cancelled",
                }[outcome.status],
                run.context,
                outcome=record_outcome,
                duration_ms=(time.monotonic() - started) * 1000,
            )
        await deliver(run.emit, terminal, self._recorder, run.context)

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
        if type(cursor) is not int or cursor < 0:
            raise DomainCommandError()
        highwater = self._highwater
        earliest = (
            int(self._entries[0]["output_id"]) if self._entries else highwater + 1
        )
        packets = [
            deepcopy(entry)
            for entry in self._entries
            if cursor < int(entry["output_id"]) <= highwater
        ]
        packets.append(
            dict(
                self.snapshot(),
                type="resume_complete",
                high_water_mark=str(highwater),
                earliest_output_id=str(earliest) if self._entries else None,
                history_gap=cursor < earliest - 1,
            )
        )
        return packets
