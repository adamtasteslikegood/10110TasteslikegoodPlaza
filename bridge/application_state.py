"""Shared application-state records and worker-only repository contract; no I/O."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_SESSIONS = 128
MAX_DOMAINS = 10
MAX_TERMINALS_PER_SESSION = 256
MAX_REPLAY_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
MAX_TASK_BYTES = 64 * 1024
MAX_TERMINAL_PACKET_BYTES = 2 * 1024 * 1024
COMPLETION_ALLOWANCE_BYTES = 2 * 1024 * 1024
MAX_RECAP_PAIRS = 4
MAX_RECAP_TASK_BYTES = 1024
MAX_RECAP_ANSWER_BYTES = 2 * 1024
MAX_RECAP_BYTES = 16 * 1024

COMMAND_KINDS = frozenset(
    {
        "start",
        "accept",
        "dispatch",
        "terminal",
        "stop",
        "end",
        "recover",
        "delete_ended",
    }
)
REQUEST_DISPOSITIONS = frozenset({"accepted", "dispatched", "terminal", "recovered"})


class StateError(ValueError):
    """A public storage code without SQL, task text or filesystem internals."""

    def __init__(self, code: str, *, uncertain: bool = False):
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain


@dataclass(frozen=True)
class DomainRecord:
    domain_id: str
    current_session_id: str | None
    domain_revision: int


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    domain_id: str
    created_at: str
    ended_at: str | None
    ended_by: str | None
    high_water_mark: int


@dataclass(frozen=True)
class ExecutionRecord:
    execution_id: str
    session_id: str
    boot_id: str
    started_at: str
    stopped_at: str | None
    outcome: str | None


@dataclass(frozen=True)
class RequestRecord:
    session_id: str
    request_id: str
    execution_id: str
    agent_id: str
    task: str
    task_digest: str
    turn_id: str
    memory_revision: int
    disposition: str
    allowance_bytes: int


@dataclass(frozen=True)
class TerminalRecord:
    session_id: str
    request_id: str
    output_id: int
    packet: dict
    output_bytes: int

    def __post_init__(self):
        object.__setattr__(self, "packet", deepcopy(self.packet))


@dataclass(frozen=True)
class StateView:
    project_id: str
    instance_id: str
    revision: int
    domains: tuple[DomainRecord, ...]
    sessions: tuple[SessionRecord, ...]
    executions: tuple[ExecutionRecord, ...]
    requests: tuple[RequestRecord, ...]
    terminals: tuple[TerminalRecord, ...]


@dataclass(frozen=True)
class StateCommand:
    kind: str
    payload: dict

    def __post_init__(self):
        if self.kind not in COMMAND_KINDS:
            raise ValueError("invalid application state command")
        object.__setattr__(self, "payload", deepcopy(self.payload))


@dataclass(frozen=True)
class StateCommit:
    view: StateView
    result: dict

    def __post_init__(self):
        object.__setattr__(self, "result", deepcopy(self.result))


class StateRepository(Protocol):
    """Only the owning worker may call a repository's methods."""

    def load(self) -> StateView | None: ...

    def apply(self, command: StateCommand) -> StateCommit: ...

    def close(self) -> None: ...
