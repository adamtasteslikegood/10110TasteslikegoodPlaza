"""Committed Run records and exact-command ownership across cancellation.

The caller owns this command until publication or a completed storage failure.
A cancelled await never classifies a still-running transaction as a failed write.
"""

import asyncio
import hashlib

from bridge.application_state import (
    COMPLETION_ALLOWANCE_BYTES,
    RequestRecord,
    StateCommand,
)


async def settle_owned(awaitable):
    """Return (result, was_cancelled) after draining this exact owned operation.

    Storage exceptions still propagate after the operation settles. Repeated
    cancellation cannot abandon it; callers classify cancellation using the
    successful result, including preserving an already committed terminal.
    """
    task = asyncio.create_task(awaitable)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    return task.result(), cancelled


class DurableRunState:
    def __init__(self, coordinator, session_id, execution_id):
        self.coordinator = coordinator
        self.session_id = session_id
        self.execution_id = execution_id

    def find_request(self, request_id):
        return self.coordinator.find_request(self.session_id, request_id)

    def find_terminal(self, request_id):
        view = self.coordinator.snapshot()
        return (
            next(
                (
                    t.packet
                    for t in view.terminals
                    if t.session_id == self.session_id and t.request_id == request_id
                ),
                None,
            )
            if view
            else None
        )

    async def accept(self, intent, memory_revision):
        request = RequestRecord(
            self.session_id,
            intent.request_id,
            self.execution_id,
            intent.agent_id,
            intent.task,
            hashlib.sha256(intent.task.encode("utf-8")).hexdigest(),
            intent.turn_id,
            memory_revision,
            "accepted",
            COMPLETION_ALLOWANCE_BYTES,
        )
        return await settle_owned(
            self.coordinator.commit(StateCommand("accept", {"request": request}))
        )

    async def dispatch(self, request_id):
        return await settle_owned(
            self.coordinator.commit(
                StateCommand(
                    "dispatch", dict(session_id=self.session_id, request_id=request_id)
                )
            )
        )

    async def terminal(self, request_id, packet):
        return await settle_owned(
            self.coordinator.commit(
                StateCommand(
                    "terminal",
                    dict(
                        session_id=self.session_id, request_id=request_id, packet=packet
                    ),
                )
            )
        )
