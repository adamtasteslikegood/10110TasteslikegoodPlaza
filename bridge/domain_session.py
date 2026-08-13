"""Domain session — Agent SDK runtime with output buffer and lifecycle.

Each active domain gets one DomainSession. The session manages a
ClaudeSDKClient, buffers output for resume, and enforces the 5-state
lifecycle.

D-005: this module knows domain_id strings and agent definitions, not
       sprites, floors, or proximity triggers.
"""

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

from bridge.agents import load_agent


class SessionState(Enum):
    INACTIVE = "inactive"
    ACTIVATING = "activating"
    ACTIVE = "active"
    BACKGROUNDED = "backgrounded"
    DEACTIVATED = "deactivated"


_VALID_TRANSITIONS = {
    SessionState.INACTIVE: {SessionState.ACTIVATING},
    SessionState.ACTIVATING: {SessionState.ACTIVE},
    SessionState.ACTIVE: {SessionState.BACKGROUNDED, SessionState.DEACTIVATED},
    SessionState.BACKGROUNDED: {SessionState.ACTIVE, SessionState.DEACTIVATED},
    SessionState.DEACTIVATED: set(),
}


class InvalidTransitionError(Exception):
    pass


@dataclass
class OutputEntry:
    output_id: int
    agent_id: str
    task: str
    output: str
    request_id: str
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class OutputBuffer:
    """Append-only buffer of agent output with monotonic ids for resume."""

    def __init__(self):
        self._entries: list[OutputEntry] = []
        self._next_id: int = 0

    def append(self, agent_id, task, output, request_id) -> OutputEntry:
        entry = OutputEntry(
            output_id=self._next_id,
            agent_id=agent_id,
            task=task,
            output=output,
            request_id=request_id,
        )
        self._next_id += 1
        self._entries.append(entry)
        return entry

    def since(self, cursor: int) -> list[OutputEntry]:
        return [e for e in self._entries if e.output_id > cursor]

    def count_since(self, cursor: int) -> int:
        return sum(1 for e in self._entries if e.output_id > cursor)

    @property
    def latest_id(self) -> int:
        return self._entries[-1].output_id if self._entries else -1


DEFAULT_DOMAIN_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TURNS = 20
DEFAULT_MAX_BUDGET_USD = 1.0

_SDK_ENV_PASSTHROUGH = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_0AUTH_TOKEN",
]


def _resolve_sdk_env() -> dict:
    """Pass bridge auth env vars through to the Agent SDK subprocess.

    ClaudeAgentOptions.env replaces the child process environment rather
    than merging with it, so this must be assembled explicitly per D-005's
    neighbor concern here: the bridge stays auth-agnostic about *which*
    credential is present, it just forwards whatever is set.
    """
    env = {}
    for key in _SDK_ENV_PASSTHROUGH:
        val = os.environ.get(key)
        if val:
            env[key] = val
    return env


class DomainSession:
    """One Agent SDK client scoped to a single domain, with output buffering
    and a 5-state lifecycle (INACTIVE -> ACTIVATING -> ACTIVE <-> BACKGROUNDED
    -> DEACTIVATED).

    Phase 1 accommodation hooks (no claim logic yet, just the data model):
    `claims` and `worktree_path` exist so a later phase can add
    worktree-per-domain isolation without changing this class's shape.
    """

    def __init__(self, domain_id: str, base_path: Optional[str] = None):
        self.domain_id = domain_id
        self.base_path: str = base_path or os.getcwd()
        self.buffer = OutputBuffer()
        self.claims: list = []
        self.worktree_path: Optional[str] = None
        self._session_id = str(
            uuid.uuid5(uuid.NAMESPACE_DNS, f"bridge.domain.{domain_id}")
        )
        self._state = SessionState.INACTIVE
        self._client: Optional[ClaudeSDKClient] = None
        self._active_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> SessionState:
        return self._state

    def _transition(self, target: SessionState):
        if target not in _VALID_TRANSITIONS.get(self._state, set()):
            raise InvalidTransitionError(
                f"Cannot transition from {self._state.value} to {target.value}"
            )
        self._state = target

    async def activate(self, sdk_env: Optional[dict] = None):
        """Stand up the Agent SDK client for this domain and connect it."""
        self._transition(SessionState.ACTIVATING)
        options = ClaudeAgentOptions(
            model=DEFAULT_DOMAIN_MODEL,
            permission_mode="acceptEdits",
            cwd=self.worktree_path or self.base_path,
            max_turns=DEFAULT_MAX_TURNS,
            max_budget_usd=DEFAULT_MAX_BUDGET_USD,
            env=sdk_env if sdk_env is not None else _resolve_sdk_env(),
            session_id=self._session_id,
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        self._transition(SessionState.ACTIVE)

    async def submit_query(self, agent_id, task, request_id, on_output=None):
        """Fire off a query against this domain's client without blocking
        the caller. The result lands in `self.buffer` and, if provided,
        `on_output(domain_id, entry)` is awaited when it completes.
        """
        self._active_task = asyncio.create_task(
            self._execute_query(agent_id, task, request_id, on_output)
        )

    async def _execute_query(self, agent_id, task, request_id, on_output=None):
        definition = load_agent(agent_id)
        prompt = f"{definition}\n\n{task}" if definition else task
        await self._client.query(prompt)
        text_parts = []
        async for msg in self._client.receive_response():
            if hasattr(msg, "content"):
                for block in msg.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
            if type(msg).__name__ == "ResultMessage":
                break
        output = "\n\n".join(text_parts) if text_parts else ""
        entry = self.buffer.append(agent_id, task, output, request_id)
        if on_output:
            await on_output(self.domain_id, entry)

    def background(self):
        self._transition(SessionState.BACKGROUNDED)

    def refocus(self):
        self._transition(SessionState.ACTIVE)

    async def deactivate(self):
        """Tear down the client. Cancels any in-flight query first."""
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
        if self._client:
            await self._client.disconnect()
            self._client = None
        self._transition(SessionState.DEACTIVATED)
