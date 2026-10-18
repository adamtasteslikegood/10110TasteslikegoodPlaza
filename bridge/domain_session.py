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
from bridge.config import BridgeConfig, default_config
from bridge.observability import BridgeRecorder, RequestContext
from bridge.protocol import validate_agent_id


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
class _QueryExecution:
    context: RequestContext
    task: str
    submitted_at: float
    started: bool = False


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


_DEFAULT_CONFIG = default_config()
DEFAULT_DOMAIN_MODEL = _DEFAULT_CONFIG.model_for(_DEFAULT_CONFIG.domain_tier)
DEFAULT_MAX_TURNS = _DEFAULT_CONFIG.domain_max_turns
DEFAULT_MAX_BUDGET_USD = _DEFAULT_CONFIG.domain_max_budget_usd

_SDK_ENV_PASSTHROUGH = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_0AUTH_TOKEN",
]


def _resolve_sdk_env() -> dict:
    """Pass bridge auth env vars through to the Agent SDK subprocess.

    The SDK merges ClaudeAgentOptions.env over the inherited parent
    environment (claude-agent-sdk 0.2.136, subprocess_cli.py), so the child
    would see these variables anyway. Passing them explicitly is
    belt-and-suspenders, not the mechanism that delivers them. Per D-005's
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

    def __init__(
        self,
        domain_id: str,
        base_path: Optional[str] = None,
        *,
        config: BridgeConfig | None = None,
        recorder: BridgeRecorder | None = None,
    ):
        self._config = config if config is not None else default_config()
        self._recorder = recorder
        self._model = self._config.model_for(self._config.domain_tier)
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
    def model(self) -> str:
        return self._model

    def _event(self, name, context=None, **metadata):
        if self._recorder is not None:
            self._recorder.event(name, context, **metadata)

    @property
    def state(self) -> SessionState:
        return self._state

    def _transition(self, target: SessionState):
        if target not in _VALID_TRANSITIONS.get(self._state, set()):
            raise InvalidTransitionError(
                f"Cannot transition from {self._state.value} to {target.value}"
            )
        self._state = target
        context = RequestContext(
            None, str(uuid.uuid4()), None, "domain", self.model, self.domain_id
        )
        self._event("domain_transition", context, domain_state=target.value)

    async def activate(self, sdk_env: Optional[dict] = None):
        """Stand up the Agent SDK client for this domain and connect it."""
        self._transition(SessionState.ACTIVATING)
        options = ClaudeAgentOptions(
            model=self.model,
            permission_mode="acceptEdits",
            cwd=self.worktree_path or self.base_path,
            max_turns=self._config.domain_max_turns,
            max_budget_usd=self._config.domain_max_budget_usd,
            env=sdk_env if sdk_env is not None else _resolve_sdk_env(),
            session_id=self._session_id,
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        self._transition(SessionState.ACTIVE)

    async def submit_query(
        self,
        agent_id,
        task,
        request_id,
        on_output=None,
        *,
        context: RequestContext | None = None,
    ):
        """Schedule execution with its immutable origin; buffer before delivery."""
        if context is None:
            context = RequestContext(
                None,
                (
                    request_id
                    if isinstance(request_id, str) and request_id.strip()
                    else str(uuid.uuid4())
                ),
                agent_id if validate_agent_id(agent_id) else None,
                "domain",
                self.model,
                self.domain_id,
            )
        execution = _QueryExecution(context, task, time.monotonic())
        self._active_task = asyncio.create_task(
            self._execute_query(
                agent_id,
                task,
                request_id,
                on_output,
                context=context,
                execution=execution,
            )
        )
        self._active_task.add_done_callback(
            lambda task: self._consume_task_exception(task, execution)
        )

    def _consume_task_exception(self, task, execution):
        if task.cancelled():
            # Cancellation can prevent the coroutine from entering even its
            # first try block. Its source-owned callback still owns that outcome.
            if not execution.started:
                self._message(execution.context, "user", execution.task, "input")
                self._record_failure(
                    execution.context,
                    "cancelled",
                    execution.submitted_at,
                )
        else:
            # Consume detached exceptions without changing what awaiters receive.
            task.exception()

    def _message(self, context, role, content, outcome, **metadata):
        if self._recorder is not None and validate_agent_id(context.agent_id):
            self._recorder.message(context, role, content, outcome, **metadata)

    async def _receive_output(self, prompt):
        await self._client.query(prompt)
        text_parts = []
        provider_session_id = None
        failed = False
        async for msg in self._client.receive_response():
            if hasattr(msg, "content"):
                for block in msg.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
            if type(msg).__name__ == "ResultMessage":
                observed = getattr(msg, "session_id", None)
                if isinstance(observed, str) and observed:
                    provider_session_id = observed
                failed = getattr(msg, "is_error", False) is True
                break
        return "\n\n".join(text_parts), provider_session_id, failed

    async def _execute_query(
        self,
        agent_id,
        task,
        request_id,
        on_output=None,
        *,
        context: RequestContext,
        execution: _QueryExecution,
    ):
        execution.started = True
        started = time.monotonic()
        self._message(context, "user", task, "input")
        self._event("execution_started", context)
        try:
            definition = load_agent(agent_id)
            prompt = f"{definition}\n\n{task}" if definition else task
            output, provider_session_id, failed = await self._receive_output(prompt)
            entry = self.buffer.append(agent_id, task, output, request_id)
        except asyncio.CancelledError:
            self._record_failure(context, "cancelled", started)
            raise
        except Exception:
            self._record_failure(context, "failure", started)
            raise
        outcome = "failure" if failed else "success"
        self._message(
            context,
            "error" if failed else "assistant",
            "sdk_error" if failed else output,
            outcome,
            output_id=str(entry.output_id),
            provider_session_id=provider_session_id,
        )
        self._event(
            "request_failed" if failed else "request_completed",
            context,
            outcome=outcome,
            duration_ms=(time.monotonic() - started) * 1000,
        )
        if on_output:
            await self._deliver_output(on_output, entry, context)

    def _record_failure(self, context, outcome, started):
        self._message(
            context,
            "error",
            "cancelled" if outcome == "cancelled" else "sdk_error",
            outcome,
        )
        self._event(
            "request_cancelled" if outcome == "cancelled" else "request_failed",
            context,
            outcome=outcome,
            duration_ms=(time.monotonic() - started) * 1000,
        )

    async def _deliver_output(self, on_output, entry, context):
        try:
            await on_output(self.domain_id, entry)
        except asyncio.CancelledError:
            self._event("delivery_cancelled", context, outcome="cancelled")
            raise
        except Exception:
            self._event("delivery_failed", context, outcome="failure")
            raise

    def background(self):
        self._transition(SessionState.BACKGROUNDED)

    def refocus(self):
        self._transition(SessionState.ACTIVE)

    async def deactivate(self):
        """Finish query cancellation and disconnect, then propagate caller cancellation."""
        active_task = self._active_task
        if active_task is not None and not active_task.done():
            # Cancel before yielding so immediate submit/deactivate cannot start
            # provider work while the teardown task is waiting to run.
            active_task.cancel()
        else:
            active_task = None
        cleanup = asyncio.create_task(self._finish_deactivation(active_task))
        caller_cancelled = None
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError as exc:
                if not cleanup.cancelled():
                    caller_cancelled = exc
            except Exception:
                break  # retrieve and propagate the cleanup's actual exception below
        if caller_cancelled is not None:
            if not cleanup.cancelled():
                cleanup.exception()
            raise caller_cancelled
        cleanup.result()

    async def _finish_deactivation(self, active_task):
        # Only this shielded task awaits expected child cancellation; caller
        # cancellation cannot be mistaken for it or interrupt the SDK disconnect.
        if active_task is not None:
            try:
                await active_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.disconnect()
            self._client = None
        self._transition(SessionState.DEACTIVATED)
