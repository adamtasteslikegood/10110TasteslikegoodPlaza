"""Per-connection admission and bounded serialized delivery; no domain ownership."""

import asyncio
import json
from uuid import uuid4

from bridge.domain_protocol import COMMANDS, error_packet
from bridge.protocol import make_error
from bridge.interaction_protocol import COMMANDS as INTERACTIONS, interaction_error
from bridge.workspace import WorkspaceError


class ConnectionState:
    def __init__(
        self, websocket, dispatch, *, project_snapshot=None, workspace_snapshot=None
    ):
        self.connection_id = str(uuid4())
        self.histories = {}
        self._websocket, self._dispatch = websocket, dispatch
        self._project_snapshot = project_snapshot or (lambda: {})
        self._workspace_snapshot = workspace_snapshot or (lambda domain_id: {})
        self._queue = asyncio.Queue(maxsize=32)
        self._sender = None
        self._slots = {}
        self._delivery_tasks = set()
        self.closed = False

    async def send(self, packet):
        if self.closed:
            raise ConnectionError("Connection delivery detached")
        future = asyncio.get_running_loop().create_future()
        try:
            self._queue.put_nowait((packet, future))
        except asyncio.QueueFull:
            self._detach()
            raise ConnectionError("Connection delivery queue full") from None
        if self._sender is None:
            self._sender = asyncio.create_task(
                self._send_loop(), name="connection-sender"
            )
        await future

    def _detach(self):
        self.closed = True
        while not self._queue.empty():
            _, future = self._queue.get_nowait()
            if not future.done():
                future.set_exception(ConnectionError("Connection delivery detached"))

    async def _send_loop(self):
        try:
            while True:
                packet, future = await self._queue.get()
                try:
                    async with asyncio.timeout(2):
                        await self._websocket.send(json.dumps(packet))
                except BaseException:
                    if not future.done():
                        future.set_exception(
                            ConnectionError("Connection delivery failed")
                        )
                    raise
                else:
                    if not future.done():
                        future.set_result(None)
        except (Exception, asyncio.CancelledError):
            self._detach()

    def submit(self, raw, data):
        data = data if isinstance(data, dict) else {}
        kind = data.get("type")
        domain = isinstance(kind, str) and kind in COMMANDS
        interaction = isinstance(kind, str) and kind in INTERACTIONS
        slot = (
            "stop"
            if kind == "deactivate_domain"
            else (
                "discovery"
                if kind in ("describe_workspace", "domain_status", "agent_status")
                else (
                    "setup"
                    if kind == "project_setup"
                    else "control" if domain else "npc"
                )
            )
        )
        if self.closed and slot == "npc":
            return None
        active = self._slots.get(slot)
        if active is not None and not active.done():
            snapshot = dict(self._project_snapshot()) if domain else {}
            # Project identity is shared; execution identity belongs only to the
            # requested department, including commands refused before dispatch.
            snapshot.pop("workspace_id", None)
            if domain and isinstance(data.get("domain_id"), str):
                try:
                    workspace = self._workspace_snapshot(data["domain_id"])
                    snapshot["workspace_id"] = workspace.get("workspace_id")
                except WorkspaceError:
                    pass
            packet = (
                error_packet(
                    data,
                    "domain_busy",
                    project_id=snapshot.get("project_id"),
                    workspace_id=snapshot.get("workspace_id"),
                )
                if domain
                else make_error(
                    data.get("agent_id", ""),
                    data.get("task", ""),
                    "conversation_busy",
                    "An NPC conversation is already in progress",
                )
            )
            if interaction:
                packet = interaction_error(
                    data, "service_busy", dict(self._project_snapshot())
                )
            if (
                not domain
                and isinstance(data.get("request_id"), str)
                and data["request_id"].strip()
            ):
                packet["request_id"] = data["request_id"]
            if len(self._delivery_tasks) >= 32:
                self._detach()
                return None
            task = asyncio.create_task(self.send(packet))
            self._delivery_tasks.add(task)
            task.add_done_callback(self._delivery_done)
            return None
        task = asyncio.create_task(
            self._dispatch(
                raw, self.histories, connection_id=self.connection_id, emit=self.send
            ),
            name="connection-" + slot,
        )
        self._slots[slot] = task
        task.add_done_callback(self._retrieve)
        return task

    @staticmethod
    def _retrieve(task):
        if not task.cancelled():
            task.exception()

    def _delivery_done(self, task):
        self._delivery_tasks.discard(task)
        self._retrieve(task)

    async def close(self):
        self._detach()
        npc = self._slots.get("npc")
        if npc is not None and not npc.done():
            npc.cancel()
            await _drain(npc)
        self.histories.clear()
        if self._sender is not None:
            self._sender.cancel()
            await _drain(self._sender)
        for task in tuple(self._delivery_tasks):
            await _drain(task)


async def _drain(task):
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if not task.cancelled():
        task.exception()
