"""Domain session manager — orchestrates domain lifecycle and routing.

Manages the registry of active domain sessions, routes queries, handles
resume requests, and produces domain state notifications.

D-005: knows domain_id strings and session states, not floors or sprites.
"""

from typing import Optional

from bridge.domain_session import DomainSession, SessionState
from bridge.protocol import (
    BridgeRequest,
    make_error,
    make_success,
    make_domain_state,
)


class DomainManager:
    def __init__(self, base_path=None):
        self._sessions: dict[str, DomainSession] = {}
        self._base_path = base_path

    async def activate_domain(self, domain_id) -> dict:
        if domain_id in self._sessions:
            session = self._sessions[domain_id]
            if session.state in (SessionState.ACTIVE, SessionState.BACKGROUNDED):
                return make_domain_state(
                    domain_id,
                    session.state.value,
                    session.buffer.count_since(-1),
                )
        session = DomainSession(domain_id, base_path=self._base_path)
        self._sessions[domain_id] = session
        await session.activate()
        return make_domain_state(domain_id, session.state.value, 0)

    async def handle_domain_query(self, request: BridgeRequest, on_output=None):
        session = self._sessions.get(request.domain_id)
        if not session or session.state not in (
            SessionState.ACTIVE,
            SessionState.BACKGROUNDED,
        ):
            return make_error(
                request.agent_id,
                request.task,
                "invalid_request",
                f"Domain '{request.domain_id}' is not active",
            )
        await session.submit_query(
            request.agent_id,
            request.task,
            request.request_id,
            on_output=on_output,
        )
        return None

    def handle_resume(self, domain_id, cursor=-1) -> list[dict]:
        session = self._sessions.get(domain_id)
        if not session:
            return []
        try:
            cursor_int = int(cursor)
        except (ValueError, TypeError):
            cursor_int = -1
        entries = session.buffer.since(cursor_int)
        return [
            make_success(
                e.agent_id,
                e.task,
                e.output,
                domain_id=domain_id,
                request_id=e.request_id,
                output_id=str(e.output_id),
            )
            for e in entries
        ]

    def background_domain(self, domain_id) -> dict:
        session = self._sessions.get(domain_id)
        if not session:
            return make_domain_state(domain_id, "inactive", 0)
        session.background()
        return make_domain_state(
            domain_id,
            session.state.value,
            session.buffer.count_since(-1),
        )

    def refocus_domain(self, domain_id) -> dict:
        session = self._sessions.get(domain_id)
        if not session:
            return make_domain_state(domain_id, "inactive", 0)
        session.refocus()
        return make_domain_state(
            domain_id,
            session.state.value,
            session.buffer.count_since(-1),
        )

    async def deactivate_domain(self, domain_id) -> dict:
        session = self._sessions.get(domain_id)
        if not session:
            return make_domain_state(domain_id, "deactivated", 0)
        await session.deactivate()
        return make_domain_state(domain_id, session.state.value, 0)

    def get_domain_state(self, domain_id) -> Optional[dict]:
        session = self._sessions.get(domain_id)
        if not session:
            return None
        return make_domain_state(
            domain_id,
            session.state.value,
            session.buffer.count_since(-1),
        )

    def list_active_domains(self) -> list[str]:
        return [
            did
            for did, s in self._sessions.items()
            if s.state in (SessionState.ACTIVE, SessionState.BACKGROUNDED)
        ]
