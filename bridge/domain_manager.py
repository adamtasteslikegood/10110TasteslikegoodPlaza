"""Saved application catalog and fenced, separately owned SDK executions."""

import asyncio
import time
from typing import TYPE_CHECKING
from uuid import uuid4, uuid5, NAMESPACE_URL
from datetime import datetime, timezone

from bridge.application_state import StateCommand, StateError
from bridge.domain_store import MemoryStore

from bridge.config import BridgeConfig
from bridge.domain_protocol import (
    DomainCommandError,
    error_packet,
    validate_domain_command,
)
from bridge.domain_session import DomainSession, DomainSink, SessionState, deliver
from bridge.failure_diagnostics import exception_diagnostics
from bridge.observability import BridgeRecorder, RequestContext
from bridge.workspace import WorkspaceError

if TYPE_CHECKING:
    from bridge.project_service import ProjectService


class DomainManager:
    def __init__(
        self,
        config: BridgeConfig,
        project_service: "ProjectService",
        *,
        recorder: BridgeRecorder | None = None,
        state_coordinator=None,
        state_provider=None,
        state_status=None,
        boot_id=None,
    ):
        self._config, self._service, self._recorder = config, project_service, recorder
        self._sessions: dict[str, list[DomainSession]] = {}
        self._closing = False
        self._state_provider = state_provider or (lambda: state_coordinator)
        self._state_status = state_status
        self._boot_id = boot_id or str(
            uuid5(NAMESPACE_URL, project_service.owner_run_id)
        )
        self._controls = {}
        self._stores = {}
        self._operations = set()
        self._activation_lock = asyncio.Lock()
        self._shutdown_task = None

    @property
    def coordinator(self):
        return self._state_provider()

    def _require_state(self):
        coordinator = self.coordinator
        if coordinator is None or not coordinator.admission_open:
            health = self._storage_status().get("error_type")
            raise StateError(health or "state_store_busy")
        return coordinator

    def _storage_status(self):
        if self._state_status is not None:
            return self._state_status()
        durable = self._config.domain_state_backend == "sqlite"
        coordinator = self.coordinator
        return dict(
            backend=self._config.domain_state_backend,
            durable=durable,
            continuity="project" if durable else "process",
            error_type=coordinator.health if coordinator else "state_store_busy",
        )

    def _current(self, domain):
        sessions = self._sessions.get(domain, [])
        return sessions[-1] if sessions else None

    def _check_authority(self, session):
        self._require_state()
        if self._current(session.domain_id) is not session or session._stopping:
            raise DomainCommandError("stale_execution")

    def owner_healthy(self, domain):
        session = self._current(domain)
        return bool(session and session.owner_healthy)

    def can_run(self, domain):
        session = self._current(domain)
        return bool(
            self.coordinator
            and self.coordinator.admission_open
            and session
            and session.can_run
        )

    def _records(self, domain):
        view = self.coordinator.snapshot() if self.coordinator else None
        record = (
            next((d for d in view.domains if d.domain_id == domain), None)
            if view
            else None
        )
        saved = [s for s in view.sessions if s.domain_id == domain] if view else []
        saved.sort(key=lambda session: (session.created_at, session.session_id))
        return view, record, saved

    def snapshot(self, domain):
        _, record, saved = self._records(domain)
        session = self._current(domain)
        current_id = record.current_session_id if record else None
        live = (
            session is not None
            and not session.clean_inactive
            and session.domain_session_id == current_id
        )
        packet = (
            session.snapshot()
            if live
            else dict(
                type="domain_state",
                project_id=self._service.snapshot().get("project_id"),
                workspace_id=self._service.workspace_snapshot(domain).get(
                    "workspace_id"
                ),
                domain_id=domain,
                domain_session_id=current_id,
                execution_id=None,
                state="inactive",
                execution_state="idle",
            )
        )
        packet.update(
            protocol_version=2,
            domain_revision=str(record.domain_revision if record else 0),
            saved_sessions=[
                dict(
                    domain_session_id=s.session_id,
                    created_at=s.created_at,
                    ended_at=s.ended_at,
                    ended_by=s.ended_by,
                    high_water_mark=str(s.high_water_mark),
                )
                for s in saved
            ],
            state_store=self._storage_status(),
        )
        # Retained wire discovery alias; catalog is no longer two SDK generations.
        packet["available_generations"] = [s.session_id for s in saved]
        return packet

    def _validate_revision(self, domain, expected):
        if int(self.snapshot(domain)["domain_revision"]) != expected:
            raise DomainCommandError("stale_domain_revision")

    async def _activate(self, command):
        async with self._activation_lock:
            return await self._activate_domain(command)

    async def _activate_domain(self, command):
        domain = command["domain_id"]
        async with self._controls.setdefault(domain, asyncio.Lock()):
            stage = self._service.snapshot().get("stage")
            if stage != "ready":
                raise DomainCommandError(
                    "workspace_unconfigured"
                    if stage == "unconfigured"
                    else "workspace_not_ready"
                )
            coordinator = self._require_state()
            self._validate_revision(domain, command["expected_domain_revision"])
            session = self._current(domain)
            if session is not None and not session.clean_inactive:
                return session, False
            if self._closing:
                raise DomainCommandError("session_unavailable")
            capacity = self._service.capacity_snapshot(domain)
            if not capacity["available"]:
                raise DomainCommandError("capacity_limit")
            view, record, _ = self._records(domain)
            revision = command["expected_domain_revision"]
            if view and record and record.current_session_id:
                if any(
                    r.session_id == record.current_session_id
                    and r.disposition in {"accepted", "dispatched"}
                    for r in view.requests
                ):
                    raise StateError("state_store_busy")
                for execution in view.executions:
                    if (
                        execution.session_id == record.current_session_id
                        and execution.stopped_at is None
                    ):
                        if execution.boot_id == self._boot_id:
                            raise StateError("state_store_busy")
                        commit = await coordinator.commit(
                            StateCommand(
                                "stop",
                                dict(
                                    execution_id=execution.execution_id,
                                    outcome="interrupted",
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                ),
                            )
                        )
                        revision = commit.result["domain_revision"]
            commit = await coordinator.commit(
                StateCommand(
                    "start",
                    dict(
                        domain_id=domain,
                        expected_domain_revision=revision,
                        boot_id=self._boot_id,
                        execution_id=str(uuid4()),
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    ),
                )
            )
            identity = commit.result
            store = self._stores.setdefault(identity["session_id"], MemoryStore())
            session = DomainSession(
                domain,
                identity["session_id"],
                config=self._config,
                project_service=self._service,
                recorder=self._recorder,
                store=store,
                execution_id=identity["execution_id"],
                coordinator=coordinator,
                authority_check=self._check_authority,
            )
            self._sessions[domain] = [
                owner
                for owner in self._sessions.get(domain, [])
                if not owner.clean_inactive
            ] + [session]
            try:
                self._service.reserve_capacity(session)
            except Exception:
                session._failure_outcome = "startup_failed"
                await session._cleanup()
                raise
            session._register_start()
            return session, True

    def _owned(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._operations.add(task)
        task.add_done_callback(self._operations.discard)
        task.add_done_callback(
            lambda done: None if done.cancelled() else done.exception()
        )
        return task

    async def _end(self, command):
        domain = command["domain_id"]
        async with self._controls.setdefault(domain, asyncio.Lock()):
            coordinator = self._require_state()
            self._validate_revision(domain, command["expected_domain_revision"])
            _, record, _ = self._records(domain)
            session_id = command["domain_session_id"]
            if record is None or record.current_session_id != session_id:
                raise DomainCommandError("session_unavailable")
            session = self._current(domain)
            if session is not None and session.domain_session_id == session_id:
                packet = await session.stop()
                if packet["state"] == SessionState.CLEANUP_FAILED.value:
                    raise DomainCommandError("cleanup_failed")
            # The caller CAS was checked before cleanup while holding this same
            # control fence. Only our Stop may have advanced it in this scope.
            revision = int(self.snapshot(domain)["domain_revision"])
            await coordinator.commit(
                StateCommand(
                    "end",
                    dict(
                        session_id=session_id,
                        expected_domain_revision=revision,
                        actor="user",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    ),
                )
            )
            return self.snapshot(domain)

    async def _deactivate(self, command, session):
        domain = command["domain_id"]
        async with self._controls.setdefault(domain, asyncio.Lock()):
            self._execution(command)
            await session.stop()
            return self.snapshot(domain)

    def _execution(self, command):
        session = self._current(command["domain_id"])
        if (
            session is None
            or session.clean_inactive
            or session.domain_session_id != command["domain_session_id"]
            or session.execution_id != command["execution_id"]
        ):
            raise DomainCommandError("stale_execution")
        return session

    def _replay(self, command):
        domain, session_id = command["domain_id"], command["domain_session_id"]
        _, _, saved = self._records(domain)
        record = next((s for s in saved if s.session_id == session_id), None)
        if record is None:
            raise DomainCommandError("session_unavailable")
        # Task 5 moves runtime Run terminals to async commits. Until then the
        # terminal-only MemoryStore is an explicitly separate process view.
        store = self._stores.get(session_id)
        window = store.replay(command["cursor"]) if store else None
        if window is None or window.high_water_mark == 0:
            window = self.coordinator.replay(session_id, command["cursor"])
        packet = self.snapshot(domain)
        if packet["domain_session_id"] != session_id:
            packet.update(
                domain_session_id=session_id,
                execution_id=None,
                state="inactive",
                execution_state="idle",
            )
        packet.update(
            type="resume_complete",
            ended=record.ended_at is not None,
            high_water_mark=str(window.high_water_mark),
            earliest_output_id=(
                str(window.earliest_output_id)
                if window.earliest_output_id is not None
                else None
            ),
            history_gap=window.history_gap,
            request_id=command["request_id"],
        )
        return window.entries + [packet]

    async def handle(
        self, command: dict, *, context: RequestContext, emit: DomainSink
    ) -> None:
        session = None
        started = time.monotonic()
        try:
            command = validate_domain_command(command)
            kind = command["type"]
            if kind == "describe_workspace":
                packet = dict(
                    await self._service.refresh_snapshot(),
                    protocol_version=2,
                    state_store=self._storage_status(),
                )
            elif kind == "domain_status":
                packet = self.snapshot(command["domain_id"])
            elif kind == "activate_domain":
                # Retain ownership through cancelled callers, including the
                # commit-before-install boundary. The socket only detaches.
                operation = self._owned(self._activate(command))
                try:
                    session, created = await asyncio.shield(operation)
                except asyncio.CancelledError:

                    def release_start(done):
                        if not done.cancelled() and done.exception() is None:
                            done.result()[0]._start_gate.set()

                    operation.add_done_callback(release_start)
                    raise
                if created:
                    try:
                        packet = await session._reserve_start()
                        await deliver(
                            emit,
                            dict(
                                self.snapshot(command["domain_id"]),
                                request_id=command["request_id"],
                            ),
                            self._recorder,
                            context,
                        )
                    finally:
                        session._start_gate.set()
                    await session.start()
                packet = self.snapshot(command["domain_id"])
            elif kind == "end_domain_session":
                packet = await asyncio.shield(self._owned(self._end(command)))
            elif kind == "resume":
                for packet in self._replay(command):
                    await deliver(emit, packet, self._recorder, context)
                return
            else:
                session = self._execution(command)
                if kind == "deactivate_domain":
                    packet = await asyncio.shield(
                        self._owned(self._deactivate(command, session))
                    )
                else:
                    self._require_state()
                    if self._controls.get(
                        command["domain_id"], asyncio.Lock()
                    ).locked():
                        raise DomainCommandError("domain_busy")
                    if kind == "domain_query":
                        return await session.admit_query(
                            command, context=context, emit=emit
                        )
                    if kind == "background_domain":
                        session.background()
                    else:
                        session.refocus()
                    packet = self.snapshot(command["domain_id"])
            await deliver(
                emit,
                dict(packet, request_id=command["request_id"]),
                self._recorder,
                context,
            )
        except Exception as error:
            command = command if isinstance(command, dict) else {}
            snapshot = self._service.snapshot()
            if isinstance(command.get("domain_id"), str):
                try:
                    snapshot = self._service.workspace_snapshot(command["domain_id"])
                except WorkspaceError:
                    pass
            code = getattr(error, "code", "sdk_error")
            if session is not None:
                command = dict(command, domain_session_id=session.domain_session_id)
                if session.state is SessionState.CLEANUP_FAILED:
                    code = "cleanup_failed"
            packet = error_packet(
                command,
                code,
                project_id=snapshot.get("project_id"),
                workspace_id=snapshot.get("workspace_id"),
            )
            diagnostics = exception_diagnostics(error)
            packet.update(diagnostics)
            if self._recorder:
                self._recorder.event(
                    (
                        "request_rejected"
                        if code == "invalid_request"
                        else "request_failed"
                    ),
                    context,
                    outcome="rejected" if code == "invalid_request" else "failure",
                    duration_ms=(time.monotonic() - started) * 1000,
                    **diagnostics,
                )
            if code == "workspace_busy" and isinstance(error, WorkspaceError):
                # Lease errors expose only an already-validated domain slug,
                # never paths, provider details or arbitrary exception text.
                packet["message"] = str(error)
            await deliver(emit, packet, self._recorder, context)

    async def shutdown(self) -> None:
        self._closing = True
        if self._shutdown_task is None or (
            self._shutdown_task.done() and self._shutdown_task.exception() is not None
        ):
            # Cleanup failures retain ownership and permit an explicit later
            # cleanup attempt. Concurrent callers share this one retained drain.
            self._shutdown_task = asyncio.create_task(self._shutdown_owned())
            self._shutdown_task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        drain = self._shutdown_task
        cancelled = None
        while not drain.done():
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError as error:
                cancelled = error
            except Exception:
                # Observe the owned outcome below after preserving cancellation.
                break
        if cancelled is not None:
            try:
                drain.result()
            except Exception as error:
                raise cancelled from error
            raise cancelled
        drain.result()

    async def _shutdown_owned(self) -> None:
        if self._operations:
            await asyncio.gather(*tuple(self._operations), return_exceptions=True)
        sessions = [
            session
            for generations in self._sessions.values()
            for session in generations
        ]
        results = await asyncio.gather(
            *(session.stop() for session in sessions), return_exceptions=True
        )
        if any(
            isinstance(packet, BaseException)
            or packet["state"] == SessionState.CLEANUP_FAILED.value
            for packet in results
        ):
            raise DomainCommandError("cleanup_failed")
