"""Synchronous per-session terminal retention, independent of execution and UI.

MemoryStore owns only replayable terminal data. It provides no restart recovery
or durable I/O contract; adding either requires a separate ownership design.
"""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from bridge.domain_protocol import DomainCommandError

MAX_ENTRIES = 256
MAX_TOTAL_OUTPUT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ReplayWindow:
    entries: list[dict]
    high_water_mark: int
    earliest_output_id: int | None
    history_gap: bool


class DomainSessionStore(Protocol):
    """One session's bounded history; all operations run without suspension.

    Appends allocate a monotonic decimal-string output ID and return a terminal
    even if it is immediately trimmed. All returned packets are independent
    copies. Lookup scans only retained entries, oldest first. Replay validates
    cursors and reports retention metadata without constructing session packets.
    """

    def append(self, terminal: dict) -> dict: ...

    def find_request(self, request_id: str) -> dict | None: ...

    def replay(self, cursor: int) -> ReplayWindow: ...


class MemoryStore:
    def __init__(self):
        self._entries = deque()
        self._output_bytes = 0
        self._highwater = 0

    def append(self, terminal: dict) -> dict:
        entry = deepcopy(terminal)
        size = len(entry["output"].encode("utf-8"))
        self._highwater += 1
        entry["output_id"] = str(self._highwater)
        self._entries.append(entry)
        self._output_bytes += size
        while (
            len(self._entries) > MAX_ENTRIES
            or self._output_bytes > MAX_TOTAL_OUTPUT_BYTES
        ):
            self._output_bytes -= len(self._entries.popleft()["output"].encode("utf-8"))
        return deepcopy(entry)

    def find_request(self, request_id: str) -> dict | None:
        for entry in self._entries:
            if entry["request_id"] == request_id:
                return deepcopy(entry)
        return None

    def replay(self, cursor: int) -> ReplayWindow:
        if type(cursor) is not int or cursor < 0:
            raise DomainCommandError()
        highwater = self._highwater
        earliest = (
            int(self._entries[0]["output_id"]) if self._entries else highwater + 1
        )
        return ReplayWindow(
            entries=[
                deepcopy(entry)
                for entry in self._entries
                if cursor < int(entry["output_id"]) <= highwater
            ],
            high_water_mark=highwater,
            earliest_output_id=earliest if self._entries else None,
            history_gap=cursor < earliest - 1,
        )
