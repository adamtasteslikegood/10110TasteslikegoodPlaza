"""UI-independent routing over bounded, generation-owned domain sessions."""

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

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
        recorder: BridgeRecorder | None = None
    ):
        self._config, self._service, self._recorder = config, project_service, recorder
        self._sessions: dict[str, list[DomainSession]] = {}
        self._closing = False

    def owner_healthy(self, domain):
        generations = self._sessions.get(domain, [])
        return bool(generations and generations[-1].owner_healthy)

    def can_run(self, domain):
        generations = self._sessions.get(domain, [])
        return bool(generations and generations[-1].can_run)

    def snapshot(self, domain):
        generations = self._sessions.get(domain, [])
        packet = (
            generations[-1].snapshot()
            if generations
            else dict(
                type="domain_state",
                project_id=self._service.snapshot().get("project_id"),
                workspace_id=self._service.workspace_snapshot(domain).get(
                    "workspace_id"
                ),
                domain_id=domain,
                domain_session_id=None,
                state="inactive",
                execution_state="idle",
            )
        )
        packet["available_generations"] = [s.domain_session_id for s in generations]
        return packet

    def _new_session(self, domain):
        generations = self._sessions.get(domain)
        if generations and not generations[-1].clean_inactive:
            return generations[-1], False
        if generations is None:
            if len(self._sessions) >= 10:
                old = next(
                    (
                        key
                        for key, values in self._sessions.items()
                        if all(s.clean_inactive for s in values)
                    ),
                    None,
                )
                if old is None:
                    raise DomainCommandError("domain_busy")
                del self._sessions[old]
            generations = self._sessions.setdefault(domain, [])
        if len(generations) >= 2:
            if not generations[0].clean_inactive:
                raise DomainCommandError("domain_busy")
            generations.pop(0)
        session = DomainSession(
            domain,
            str(uuid4()),
            config=self._config,
            project_service=self._service,
            recorder=self._recorder,
        )
        generations.append(session)
        return session, True

    async def handle(
        self, command: dict, *, context: RequestContext, emit: DomainSink
    ) -> None:
        session = None
        try:
            command = validate_domain_command(command)
            kind = command["type"]
            if kind == "describe_workspace":
                packet = dict(await self._service.refresh_snapshot())
            elif kind == "domain_status":
                generations = self._sessions.get(command["domain_id"], [])
                packet = (
                    generations[-1].snapshot()
                    if generations
                    else dict(
                        type="domain_state",
                        project_id=self._service.snapshot().get("project_id"),
                        workspace_id=self._service.workspace_snapshot(
                            command["domain_id"]
                        ).get("workspace_id"),
                        domain_id=command["domain_id"],
                        domain_session_id=None,
                        state="inactive",
                        execution_state="idle",
                    )
                )
                packet["available_generations"] = [
                    s.domain_session_id for s in generations
                ]
            elif kind == "activate_domain":
                if self._closing:
                    raise DomainCommandError("session_unavailable")
                session, created = self._new_session(command["domain_id"])
                if not created:
                    packet = session.snapshot()
                else:
                    try:
                        packet = await session._reserve_start()
                        await deliver(
                            emit,
                            dict(packet, request_id=command["request_id"]),
                            self._recorder,
                            context,
                        )
                    finally:
                        # Release the registered continuation even on socket loss.
                        session._start_gate.set()
                    packet = await session.start()
            else:
                generations = self._sessions.get(command["domain_id"], [])
                session = next(
                    (
                        s
                        for s in generations
                        if s.domain_session_id == command["domain_session_id"]
                    ),
                    None,
                )
                if session is None or (
                    kind != "resume" and session is not generations[-1]
                ):
                    raise DomainCommandError("session_unavailable")
                if kind == "domain_query":
                    return await session.admit_query(
                        command, context=context, emit=emit
                    )
                if kind == "resume":
                    for packet in session.replay(command["cursor"]):
                        if packet["type"] == "resume_complete":
                            packet["request_id"] = command["request_id"]
                        await deliver(emit, packet, self._recorder, context)
                    return
                if kind == "background_domain":
                    packet = session.background()
                elif kind == "refocus_domain":
                    packet = session.refocus()
                else:
                    packet = await session.stop()
            await deliver(
                emit,
                dict(packet, request_id=command["request_id"]),
                self._recorder,
                context,
            )
        except Exception as error:
            snapshot = self._service.snapshot()
            if command.get("domain_id"):
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
                    "request_failed", context, outcome="failure", **diagnostics
                )
            if code == "workspace_busy" and isinstance(error, WorkspaceError):
                # Lease errors expose only an already-validated domain slug,
                # never paths, provider details or arbitrary exception text.
                packet["message"] = str(error)
            await deliver(emit, packet, self._recorder, context)

    async def shutdown(self) -> None:
        self._closing = True
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
