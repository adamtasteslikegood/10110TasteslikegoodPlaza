# Bridge Domain Architecture — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the bridge from a single-request pipe into a two-engine architecture — a stateless conversation engine (Haiku, NPC chat) and a persistent domain session engine (Agent SDK, tool use, background execution with resume) — behind a shared protocol layer that routes messages and maintains backward compatibility with the existing Godot client.

**Architecture:** The WebSocket server (`ws://localhost:8765`, D-015) gains a protocol layer that classifies incoming messages by `type` field and routes them to one of two engines. Requests without `type` route to the conversation engine (backward compat). Domain queries route to the domain session manager, which maintains one Agent SDK runtime per active domain with an output buffer and resume cursor. Domain sessions run queries as asyncio tasks so output accumulates even when the player walks away (backgrounded). The conversation engine is the current `bridge.py` logic extracted into its own module, model changed to Haiku.

**Tech Stack:**
- `claude-agent-sdk==0.2.136` — `ClaudeSDKClient` for domain sessions (stateful, bidirectional, built-in tools)
- `anthropic==0.121.0` — `Anthropic` client for conversation engine (stateless, single-request)
- `websockets==17.0.1` — WebSocket server (same library as current bridge)
- `pytest==9.1.1` — test framework (matches existing `bridge/tests/` patterns)
- Python 3.13, asyncio event loop

## Global Constraints

- **D-005:** Bridge has zero UI awareness. No Godot, sprites, scenes, or rendering concepts. Swap test: replacing the frontend with `wscat` must require no change.
- **D-006:** Conversation engine stays synchronous with timeout. Domain sessions are async but capped with `max_turns` and `max_budget_usd`.
- **D-015:** Server listens on `ws://localhost:8765`.
- **D-029:** Bridge reads agent definitions from its own store (`bridge/agents/`), never from the submodule directly.
- **Formatting:** All Python passes `black --check .` and `flake8 --select=E9,F63,F7,F82`.
- **Backward compatibility:** The existing Godot `BridgeClient` (sends `{"agent_id": "...", "task": "..."}` with no `type` field) must work without changes.
- **Phase 1 accommodation hooks:** Every domain session carries `claims: list = []`, `worktree_path: str | None = None`, and uses `self.base_path` (defaults to repo root) instead of hardcoded paths. No claim logic, no worktree management — just the data model hooks so Phase 3 isn't a rewrite.
- **Agent SDK auth:** Pass bridge env vars (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_0AUTH_TOKEN`) through to `ClaudeAgentOptions(env=...)`. Named as a known risk per design spec §9 — spike if the CLI needs a different auth path.

---

## File Structure

```
bridge/
├── protocol.py           # NEW — Message types, parsing, classification, validation, response builders
├── conversation.py       # NEW — Conversation engine (extracted from bridge.py, Haiku default)
├── domain_session.py     # NEW — Single domain session: lifecycle, Agent SDK client, output buffer
├── domain_manager.py     # NEW — Manages all domain sessions: activation, routing, resume
├── server.py             # NEW — WebSocket server with protocol routing, replaces bridge.py's serve()
├── bridge.py             # MODIFIED — Becomes thin entry point delegating to server.py
├── agents.py             # UNCHANGED
├── PROTOCOL.md           # MODIFIED — Extended protocol documentation
├── agents/               # UNCHANGED
└── tests/
    ├── test_agents.py          # UNCHANGED
    ├── test_protocol.py        # NEW — Protocol message types and validation
    ├── test_conversation.py    # NEW — Conversation engine unit tests
    ├── test_domain_session.py  # NEW — Domain session lifecycle and output buffer
    ├── test_domain_manager.py  # NEW — Domain manager orchestration
    └── test_server.py          # NEW — Server routing and backward compat integration
```

**Responsibility boundaries:**

| Module | Knows about | Does NOT know about |
|---|---|---|
| `protocol.py` | JSON message shapes, field validation | Anthropic SDK, Agent SDK, WebSocket |
| `conversation.py` | Anthropic Messages API, agent definitions | Domains, sessions, WebSocket |
| `domain_session.py` | Agent SDK, output buffering, lifecycle states | Other sessions, WebSocket, routing |
| `domain_manager.py` | Session registry, activation logic | WebSocket, message parsing |
| `server.py` | WebSocket, protocol routing, push delivery | Agent SDK internals, API calls |

---

### Task 1: Protocol Layer

**Files:**
- Create: `bridge/protocol.py`
- Create: `bridge/tests/test_protocol.py`

**Interfaces:**
- Consumes: nothing (pure data module)
- Produces: `RequestType` enum, `BridgeRequest` dataclass, `parse_request(raw: dict) -> BridgeRequest`, `classify_request(raw: dict) -> RequestType`, `validate_request(request: BridgeRequest) -> str | None`, `make_error(agent_id, task, error_type, message, **kwargs) -> dict`, `make_success(agent_id, task, output, **kwargs) -> dict`, `make_domain_state(domain_id, state, unread_count) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for bridge.protocol — message types, parsing, validation."""

import pytest

from bridge.protocol import (
    RequestType,
    BridgeRequest,
    classify_request,
    parse_request,
    validate_request,
    make_error,
    make_success,
    make_domain_state,
)


class TestClassifyRequest:
    def test_no_type_defaults_to_conversation(self):
        assert classify_request({"agent_id": "a", "task": "t"}) == RequestType.CONVERSATION

    def test_domain_query(self):
        assert classify_request({"type": "domain_query"}) == RequestType.DOMAIN_QUERY

    def test_conversation_explicit(self):
        assert classify_request({"type": "conversation"}) == RequestType.CONVERSATION

    def test_resume(self):
        assert classify_request({"type": "resume"}) == RequestType.RESUME

    def test_unknown_type_defaults_to_conversation(self):
        assert classify_request({"type": "bogus"}) == RequestType.CONVERSATION


class TestParseRequest:
    def test_parses_domain_query(self):
        raw = {
            "type": "domain_query",
            "domain_id": "engineering",
            "agent_id": "systems-architect",
            "task": "Review auth middleware",
            "request_id": "abc-123",
        }
        req = parse_request(raw)
        assert req.type == RequestType.DOMAIN_QUERY
        assert req.domain_id == "engineering"
        assert req.agent_id == "systems-architect"
        assert req.task == "Review auth middleware"
        assert req.request_id == "abc-123"

    def test_parses_legacy_request_no_type(self):
        raw = {"agent_id": "security-auditor", "task": "What do you think?"}
        req = parse_request(raw)
        assert req.type == RequestType.CONVERSATION
        assert req.agent_id == "security-auditor"

    def test_generates_request_id_when_missing(self):
        req = parse_request({"agent_id": "a", "task": "t"})
        assert req.request_id != ""

    def test_parses_resume(self):
        raw = {"type": "resume", "domain_id": "engineering", "cursor": "5"}
        req = parse_request(raw)
        assert req.type == RequestType.RESUME
        assert req.cursor == "5"

    def test_missing_fields_default_to_empty(self):
        req = parse_request({})
        assert req.agent_id == ""
        assert req.task == ""
        assert req.domain_id == ""


class TestValidateRequest:
    def test_valid_conversation(self):
        req = BridgeRequest(
            type=RequestType.CONVERSATION, agent_id="a", task="t"
        )
        assert validate_request(req) is None

    def test_conversation_missing_agent_id(self):
        req = BridgeRequest(type=RequestType.CONVERSATION, agent_id="", task="t")
        assert validate_request(req) is not None

    def test_conversation_missing_task(self):
        req = BridgeRequest(type=RequestType.CONVERSATION, agent_id="a", task="")
        assert validate_request(req) is not None

    def test_domain_query_missing_domain_id(self):
        req = BridgeRequest(
            type=RequestType.DOMAIN_QUERY, agent_id="a", task="t", domain_id=""
        )
        assert validate_request(req) is not None

    def test_domain_query_valid(self):
        req = BridgeRequest(
            type=RequestType.DOMAIN_QUERY,
            agent_id="a",
            task="t",
            domain_id="engineering",
        )
        assert validate_request(req) is None

    def test_resume_missing_domain_id(self):
        req = BridgeRequest(type=RequestType.RESUME, domain_id="")
        assert validate_request(req) is not None

    def test_resume_valid(self):
        req = BridgeRequest(type=RequestType.RESUME, domain_id="engineering")
        assert validate_request(req) is None


class TestResponseBuilders:
    def test_make_error(self):
        resp = make_error("agent-1", "do stuff", "not_found", "No agent")
        assert resp["status"] == "error"
        assert resp["error_type"] == "not_found"
        assert resp["agent_id"] == "agent-1"
        assert resp["output"] == ""

    def test_make_success(self):
        resp = make_success("agent-1", "do stuff", "result text")
        assert resp["status"] == "ok"
        assert resp["output"] == "result text"

    def test_make_success_with_domain_fields(self):
        resp = make_success(
            "agent-1", "do stuff", "result",
            domain_id="engineering", request_id="r1", output_id="3",
        )
        assert resp["domain_id"] == "engineering"
        assert resp["request_id"] == "r1"
        assert resp["output_id"] == "3"

    def test_make_domain_state(self):
        resp = make_domain_state("engineering", "backgrounded", 3)
        assert resp["type"] == "domain_state"
        assert resp["domain_id"] == "engineering"
        assert resp["state"] == "backgrounded"
        assert resp["unread_count"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest bridge/tests/test_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bridge.protocol'`

- [ ] **Step 3: Implement protocol.py**

```python
"""Protocol layer — message types, parsing, classification, response builders.

Shared vocabulary for the bridge's two engines (conversation and domain session).
This module has no I/O — it is pure data transformation.
"""

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RequestType(Enum):
    DOMAIN_QUERY = "domain_query"
    CONVERSATION = "conversation"
    RESUME = "resume"


@dataclass
class BridgeRequest:
    type: RequestType = RequestType.CONVERSATION
    agent_id: str = ""
    task: str = ""
    domain_id: str = ""
    request_id: str = ""
    cursor: str = ""


_VALID_AGENT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def classify_request(raw: dict) -> RequestType:
    type_str = raw.get("type", "conversation")
    try:
        return RequestType(type_str)
    except ValueError:
        return RequestType.CONVERSATION


def parse_request(raw: dict) -> BridgeRequest:
    return BridgeRequest(
        type=classify_request(raw),
        agent_id=raw.get("agent_id", ""),
        task=raw.get("task", ""),
        domain_id=raw.get("domain_id", ""),
        request_id=raw.get("request_id", "") or str(uuid.uuid4()),
        cursor=raw.get("cursor", ""),
    )


def validate_request(request: BridgeRequest) -> Optional[str]:
    if request.type == RequestType.DOMAIN_QUERY:
        if not request.domain_id:
            return "domain_id is required for domain_query"
        if not request.agent_id:
            return "agent_id is required for domain_query"
        if not request.task:
            return "task is required for domain_query"
    elif request.type == RequestType.CONVERSATION:
        if not request.agent_id:
            return "agent_id is required"
        if not request.task:
            return "task is required"
    elif request.type == RequestType.RESUME:
        if not request.domain_id:
            return "domain_id is required for resume"
    return None


def validate_agent_id(agent_id: str) -> bool:
    return bool(agent_id and isinstance(agent_id, str) and _VALID_AGENT_ID.match(agent_id))


def make_error(agent_id, task, error_type, message, **kwargs):
    resp = {
        "agent_id": agent_id,
        "task": task,
        "output": "",
        "status": "error",
        "error_type": error_type,
        "message": message,
    }
    resp.update(kwargs)
    return resp


def make_success(agent_id, task, output, **kwargs):
    resp = {
        "agent_id": agent_id,
        "task": task,
        "output": output,
        "status": "ok",
    }
    resp.update(kwargs)
    return resp


def make_domain_state(domain_id, state, unread_count):
    return {
        "type": "domain_state",
        "domain_id": domain_id,
        "state": state,
        "unread_count": unread_count,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest bridge/tests/test_protocol.py -v`
Expected: All 19 tests PASS

- [ ] **Step 5: Run linters**

Run: `black bridge/protocol.py bridge/tests/test_protocol.py && flake8 bridge/protocol.py bridge/tests/test_protocol.py --select=E9,F63,F7,F82`

- [ ] **Step 6: Commit**

```bash
git add bridge/protocol.py bridge/tests/test_protocol.py
git commit -m "feat(bridge): add protocol layer with message types and routing

Defines the shared vocabulary for domain_query, conversation, and
resume message types. Pure data module — no I/O, no SDK dependency."
```

---

### Task 2: Conversation Engine

**Files:**
- Create: `bridge/conversation.py`
- Create: `bridge/tests/test_conversation.py`

**Interfaces:**
- Consumes: `bridge.agents.load_agent(agent_id) -> str | None` from Task 0 (existing), `bridge.protocol.make_error`, `bridge.protocol.make_success`, `bridge.protocol.validate_agent_id` from Task 1
- Produces: `ConversationEngine` class with `__init__(client=None)`, `handle_request(request: dict) -> dict`. `build_client() -> Anthropic` free function (extracted from `bridge.py:_build_client`).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for bridge.conversation — the conversation engine (Haiku, stateless)."""

import os
import pytest
from unittest.mock import MagicMock, patch

from bridge.conversation import ConversationEngine, build_client


class TestConversationEngine:
    @pytest.fixture(autouse=True)
    def mock_agent_store(self, monkeypatch):
        monkeypatch.setattr(
            "bridge.conversation.load_agent",
            lambda aid: "You are a test agent." if aid == "systems-architect" else None,
        )

    @pytest.fixture
    def mock_anthropic(self):
        client = MagicMock()
        block = MagicMock()
        block.text = "Hello from Haiku"
        response = MagicMock()
        response.content = [block]
        client.messages.create.return_value = response
        return client

    @pytest.fixture
    def engine(self, mock_anthropic):
        return ConversationEngine(client=mock_anthropic)

    def test_success_response(self, engine, mock_anthropic):
        resp = engine.handle_request({"agent_id": "systems-architect", "task": "hi"})
        assert resp["status"] == "ok"
        assert resp["output"] == "Hello from Haiku"
        assert resp["agent_id"] == "systems-architect"

    def test_default_model_is_haiku(self, engine, mock_anthropic):
        engine.handle_request({"agent_id": "systems-architect", "task": "hi"})
        call_kwargs = mock_anthropic.messages.create.call_args
        assert "haiku" in call_kwargs.kwargs.get("model", call_kwargs[1].get("model", ""))

    def test_missing_agent_returns_not_found(self, engine):
        resp = engine.handle_request({"agent_id": "nonexistent-agent", "task": "hi"})
        assert resp["status"] == "error"
        assert resp["error_type"] == "not_found"

    def test_missing_agent_id_returns_invalid(self, engine):
        resp = engine.handle_request({"agent_id": "", "task": "hi"})
        assert resp["status"] == "error"
        assert resp["error_type"] == "invalid_request"

    def test_missing_task_returns_invalid(self, engine):
        resp = engine.handle_request({"agent_id": "systems-architect", "task": ""})
        assert resp["status"] == "error"
        assert resp["error_type"] == "invalid_request"

    def test_non_dict_returns_invalid(self, engine):
        resp = engine.handle_request("not a dict")
        assert resp["status"] == "error"

    def test_timeout_error(self, engine, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("timed out")
        resp = engine.handle_request({"agent_id": "systems-architect", "task": "hi"})
        assert resp["error_type"] == "timeout"

    def test_auth_error(self, engine, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception(
            "AuthenticationError: invalid key"
        )
        resp = engine.handle_request({"agent_id": "systems-architect", "task": "hi"})
        assert resp["error_type"] == "auth"


class TestBuildClient:
    def test_api_key_uses_api_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test123")
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        with patch("bridge.conversation.Anthropic") as mock_cls:
            build_client()
            mock_cls.assert_called_once_with(api_key="sk-ant-test123")

    def test_oauth_token_uses_auth_token(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-tok")
        with patch("bridge.conversation.Anthropic") as mock_cls:
            build_client()
            mock_cls.assert_called_once_with(auth_token="oauth-tok")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest bridge/tests/test_conversation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bridge.conversation'`

- [ ] **Step 3: Implement conversation.py**

```python
"""Conversation engine — stateless single-request handler for NPC chat.

Evolved from bridge.py's handle_request(). Uses the Anthropic Messages API
with Haiku for low-cost personality-driven NPC interactions.

D-005: zero UI awareness.
D-006: synchronous with timeout.
"""

import os
import re

from anthropic import Anthropic

from bridge.agents import load_agent
from bridge.protocol import make_error, make_success, validate_agent_id

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_TOKENS = 4096

_VALID_AGENT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def build_client():
    """Build an Anthropic client, resolving credentials in priority order.

    1. ANTHROPIC_API_KEY (sk-ant-..., x-api-key header)
    2. ANTHROPIC_AUTH_TOKEN (Authorization: Bearer)
    3. CLAUDE_CODE_OAUTH_TOKEN (bridge-local alias)
    4. CLAUDE_CODE_0AUTH_TOKEN (alternate spelling)
    5. SDK reads ~/.config/anthropic/ automatically
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key.startswith("sk-ant-"):
        return Anthropic(api_key=api_key)

    auth_token = (
        os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        or os.environ.get("CLAUDE_CODE_0AUTH_TOKEN")
    )
    if auth_token:
        return Anthropic(auth_token=auth_token)

    return Anthropic()


class ConversationEngine:
    """Stateless request/response engine for NPC chat and story content.

    Each call is an independent Haiku invocation — no session state,
    no tool use, no background execution.
    """

    def __init__(self, client=None, model=None, timeout=None):
        self._client = client or build_client()
        self._model = model or DEFAULT_MODEL
        self._timeout = timeout or DEFAULT_TIMEOUT

    def handle_request(self, request):
        if not isinstance(request, dict):
            return make_error("", "", "invalid_request", "Request must be a JSON object")

        agent_id = request.get("agent_id", "")
        task = request.get("task", "")

        if not isinstance(agent_id, str) or not isinstance(task, str):
            return make_error("", "", "invalid_request", "agent_id and task must be strings")

        if not agent_id or not task:
            return make_error(agent_id, task, "invalid_request", "agent_id and task are required")

        if not validate_agent_id(agent_id):
            return make_error(agent_id, task, "invalid_request", "agent_id contains invalid characters")

        definition = load_agent(agent_id)
        if definition is None:
            return make_error(agent_id, task, "not_found", f"No agent '{agent_id}'")

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=DEFAULT_MAX_TOKENS,
                system=definition,
                messages=[{"role": "user", "content": task}],
                timeout=self._timeout,
            )
            parts = [b.text for b in response.content if hasattr(b, "text")]
            output = "\n\n".join(parts) if parts else ""
            return make_success(agent_id, task, output)
        except Exception as exc:
            exc_name = type(exc).__name__
            if "auth" in exc_name.lower() or "authentication" in str(exc).lower():
                return make_error(agent_id, task, "auth", str(exc))
            if "timeout" in exc_name.lower() or "timed out" in str(exc).lower():
                return make_error(
                    agent_id, task, "timeout", f"Timed out after {self._timeout}s"
                )
            return make_error(agent_id, task, "api_error", str(exc))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest bridge/tests/test_conversation.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Run linters and commit**

```bash
black bridge/conversation.py bridge/tests/test_conversation.py
flake8 bridge/conversation.py bridge/tests/test_conversation.py --select=E9,F63,F7,F82
git add bridge/conversation.py bridge/tests/test_conversation.py
git commit -m "feat(bridge): extract conversation engine from bridge.py

Stateless Haiku-powered NPC chat handler. Same logic as bridge.py's
handle_request() with model changed to claude-haiku-4-5."
```

---

### Task 3: Domain Session with Output Buffer

**Files:**
- Create: `bridge/domain_session.py`
- Create: `bridge/tests/test_domain_session.py`

**Interfaces:**
- Consumes: `bridge.agents.load_agent(agent_id) -> str | None`, `bridge.protocol.make_success`
- Produces: `OutputEntry` dataclass (`output_id: int`, `agent_id: str`, `task: str`, `output: str`, `request_id: str`), `OutputBuffer` class (`append(agent_id, task, output, request_id) -> OutputEntry`, `since(cursor: int) -> list[OutputEntry]`, `count_since(cursor: int) -> int`, `latest_id -> int`), `SessionState` enum (5 states), `DomainSession` class (`__init__(domain_id, base_path=None)`, `async activate(sdk_env=None)`, `async submit_query(agent_id, task, request_id, on_output=None)`, `background()`, `refocus()`, `async deactivate()`, `state -> SessionState`, `buffer -> OutputBuffer`, `claims: list`, `worktree_path: str | None`, `domain_id: str`)

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for bridge.domain_session — output buffer and domain session lifecycle."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bridge.domain_session import (
    OutputBuffer,
    OutputEntry,
    SessionState,
    DomainSession,
    InvalidTransitionError,
)


class TestOutputBuffer:
    def test_append_returns_entry_with_monotonic_id(self):
        buf = OutputBuffer()
        e1 = buf.append("agent-a", "task 1", "output 1", "r1")
        e2 = buf.append("agent-b", "task 2", "output 2", "r2")
        assert e1.output_id == 0
        assert e2.output_id == 1

    def test_since_cursor_returns_newer_entries(self):
        buf = OutputBuffer()
        buf.append("a", "t", "first", "r1")
        buf.append("a", "t", "second", "r2")
        buf.append("a", "t", "third", "r3")
        entries = buf.since(0)
        assert len(entries) == 2
        assert entries[0].output == "second"
        assert entries[1].output == "third"

    def test_since_minus_one_returns_all(self):
        buf = OutputBuffer()
        buf.append("a", "t", "first", "r1")
        buf.append("a", "t", "second", "r2")
        entries = buf.since(-1)
        assert len(entries) == 2

    def test_since_latest_returns_empty(self):
        buf = OutputBuffer()
        buf.append("a", "t", "first", "r1")
        entries = buf.since(0)
        assert entries == []

    def test_count_since(self):
        buf = OutputBuffer()
        buf.append("a", "t", "first", "r1")
        buf.append("a", "t", "second", "r2")
        buf.append("a", "t", "third", "r3")
        assert buf.count_since(0) == 2
        assert buf.count_since(-1) == 3
        assert buf.count_since(2) == 0

    def test_latest_id_empty_buffer(self):
        buf = OutputBuffer()
        assert buf.latest_id == -1

    def test_latest_id_after_append(self):
        buf = OutputBuffer()
        buf.append("a", "t", "o", "r")
        assert buf.latest_id == 0
        buf.append("a", "t", "o", "r")
        assert buf.latest_id == 1


class TestSessionState:
    def test_initial_state_is_inactive(self):
        session = DomainSession("engineering")
        assert session.state == SessionState.INACTIVE

    def test_phase1_accommodation_defaults(self):
        session = DomainSession("engineering")
        assert session.claims == []
        assert session.worktree_path is None
        assert session.base_path is not None

    def test_custom_base_path(self):
        session = DomainSession("engineering", base_path="/custom/path")
        assert session.base_path == "/custom/path"

    def test_background_from_active(self):
        session = DomainSession("engineering")
        session._state = SessionState.ACTIVE
        session.background()
        assert session.state == SessionState.BACKGROUNDED

    def test_refocus_from_backgrounded(self):
        session = DomainSession("engineering")
        session._state = SessionState.BACKGROUNDED
        session.refocus()
        assert session.state == SessionState.ACTIVE

    def test_invalid_transition_raises(self):
        session = DomainSession("engineering")
        with pytest.raises(InvalidTransitionError):
            session.background()


@pytest.mark.asyncio
class TestDomainSessionSDK:
    @pytest.fixture
    def mock_sdk(self, monkeypatch):
        mock_client = AsyncMock()

        async def fake_receive():
            msg = MagicMock()
            msg.content = [MagicMock(text="SDK response text")]
            type(msg).__name__ = "AssistantMessage"
            yield msg
            result = MagicMock()
            type(result).__name__ = "ResultMessage"
            yield result

        mock_client.receive_response = fake_receive
        mock_cls = MagicMock(return_value=mock_client)
        monkeypatch.setattr("bridge.domain_session.ClaudeSDKClient", mock_cls)
        return mock_client, mock_cls

    async def test_activate_transitions_to_active(self, mock_sdk):
        session = DomainSession("engineering")
        await session.activate()
        assert session.state == SessionState.ACTIVE

    async def test_activate_connects_sdk_client(self, mock_sdk):
        mock_client, _ = mock_sdk
        session = DomainSession("engineering")
        await session.activate()
        mock_client.connect.assert_awaited_once()

    async def test_deactivate_disconnects(self, mock_sdk):
        mock_client, _ = mock_sdk
        session = DomainSession("engineering")
        await session.activate()
        await session.deactivate()
        assert session.state == SessionState.DEACTIVATED
        mock_client.disconnect.assert_awaited_once()

    async def test_submit_query_buffers_output(self, mock_sdk, monkeypatch):
        monkeypatch.setattr(
            "bridge.domain_session.load_agent",
            lambda aid: "You are an engineer.",
        )
        session = DomainSession("engineering")
        await session.activate()
        callback = AsyncMock()
        await session.submit_query("systems-architect", "review code", "r1", on_output=callback)
        await asyncio.sleep(0.1)
        assert session.buffer.latest_id == 0
        entry = session.buffer.since(-1)[0]
        assert entry.output == "SDK response text"
        assert entry.agent_id == "systems-architect"

    async def test_submit_query_calls_callback(self, mock_sdk, monkeypatch):
        monkeypatch.setattr(
            "bridge.domain_session.load_agent",
            lambda aid: "You are an engineer.",
        )
        session = DomainSession("engineering")
        await session.activate()
        callback = AsyncMock()
        await session.submit_query("systems-architect", "review code", "r1", on_output=callback)
        await asyncio.sleep(0.1)
        callback.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest bridge/tests/test_domain_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bridge.domain_session'`

- [ ] **Step 3: Implement domain_session.py**

```python
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
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

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
    def __init__(self):
        self._entries: list[OutputEntry] = []
        self._next_id: int = 0

    def append(self, agent_id, task, output, request_id):
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


def _resolve_sdk_env():
    env = {}
    for key in [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_0AUTH_TOKEN",
    ]:
        val = os.environ.get(key)
        if val:
            env[key] = val
    return env


class DomainSession:
    def __init__(self, domain_id, base_path=None):
        self.domain_id = domain_id
        self.base_path = base_path or os.getcwd()
        self.buffer = OutputBuffer()
        self.claims: list = []
        self.worktree_path: Optional[str] = None
        self._session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"bridge.domain.{domain_id}"))
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

    async def activate(self, sdk_env=None):
        self._transition(SessionState.ACTIVATING)
        options = ClaudeAgentOptions(
            model=DEFAULT_DOMAIN_MODEL,
            permission_mode="acceptEdits",
            cwd=self.worktree_path or self.base_path,
            max_turns=DEFAULT_MAX_TURNS,
            max_budget_usd=DEFAULT_MAX_BUDGET_USD,
            env=sdk_env or _resolve_sdk_env(),
            session_id=self._session_id,
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        self._transition(SessionState.ACTIVE)

    async def submit_query(self, agent_id, task, request_id, on_output=None):
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
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
        if self._client:
            await self._client.disconnect()
            self._client = None
        self._transition(SessionState.DEACTIVATED)
```

- [ ] **Step 4: Install pytest-asyncio for async tests**

Run: `pip install pytest-asyncio && pip freeze | grep pytest-asyncio`

Add `pytest-asyncio` to `requirements.txt` if not already present.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest bridge/tests/test_domain_session.py -v`
Expected: All 15 tests PASS

- [ ] **Step 6: Run linters and commit**

```bash
black bridge/domain_session.py bridge/tests/test_domain_session.py
flake8 bridge/domain_session.py bridge/tests/test_domain_session.py --select=E9,F63,F7,F82
git add bridge/domain_session.py bridge/tests/test_domain_session.py
git commit -m "feat(bridge): add domain session with Agent SDK runtime and output buffer

5-state lifecycle (INACTIVE → ACTIVE → BACKGROUNDED), Agent SDK client
per domain, output buffer with monotonic IDs and cursor-based resume.
Phase 1 accommodation hooks: claims=[], worktree_path=None, base_path."
```

---

### Task 4: Domain Session Manager

**Files:**
- Create: `bridge/domain_manager.py`
- Create: `bridge/tests/test_domain_manager.py`

**Interfaces:**
- Consumes: `bridge.domain_session.DomainSession`, `bridge.domain_session.SessionState`, `bridge.domain_session.OutputEntry`, `bridge.protocol.make_error`, `bridge.protocol.make_success`, `bridge.protocol.make_domain_state`
- Produces: `DomainManager` class with `__init__(base_path=None)`, `async activate_domain(domain_id) -> dict`, `async handle_domain_query(request: BridgeRequest, on_output) -> dict | None`, `handle_resume(domain_id, cursor) -> list[dict]`, `background_domain(domain_id) -> dict`, `refocus_domain(domain_id) -> dict`, `async deactivate_domain(domain_id) -> dict`, `get_domain_state(domain_id) -> dict | None`, `list_active_domains() -> list[str]`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for bridge.domain_manager — domain session orchestration."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bridge.domain_manager import DomainManager
from bridge.domain_session import SessionState, OutputEntry
from bridge.protocol import BridgeRequest, RequestType


@pytest.fixture
def mock_session_cls(monkeypatch):
    sessions = {}

    def make_session(domain_id, base_path=None):
        session = MagicMock()
        session.domain_id = domain_id
        session.state = SessionState.INACTIVE
        session._state = SessionState.INACTIVE
        session.buffer = MagicMock()
        session.buffer.latest_id = -1
        session.buffer.count_since.return_value = 0
        session.buffer.since.return_value = []
        session.activate = AsyncMock(
            side_effect=lambda **kw: setattr(session, "state", SessionState.ACTIVE)
            or setattr(session, "_state", SessionState.ACTIVE)
        )
        session.submit_query = AsyncMock()
        session.background = MagicMock(
            side_effect=lambda: setattr(session, "state", SessionState.BACKGROUNDED)
        )
        session.refocus = MagicMock(
            side_effect=lambda: setattr(session, "state", SessionState.ACTIVE)
        )
        session.deactivate = AsyncMock(
            side_effect=lambda: setattr(session, "state", SessionState.DEACTIVATED)
        )
        sessions[domain_id] = session
        return session

    monkeypatch.setattr("bridge.domain_manager.DomainSession", make_session)
    return sessions


@pytest.mark.asyncio
class TestDomainManager:
    async def test_activate_domain(self, mock_session_cls):
        mgr = DomainManager()
        result = await mgr.activate_domain("engineering")
        assert result["domain_id"] == "engineering"
        assert result["state"] == "active"
        assert "engineering" in mgr.list_active_domains()

    async def test_activate_already_active(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        result = await mgr.activate_domain("engineering")
        assert result["state"] == "active"

    async def test_submit_query_to_active_domain(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        req = BridgeRequest(
            type=RequestType.DOMAIN_QUERY,
            domain_id="engineering",
            agent_id="systems-architect",
            task="review code",
            request_id="r1",
        )
        callback = AsyncMock()
        result = await mgr.handle_domain_query(req, on_output=callback)
        assert result is None  # async — output comes via callback
        mock_session_cls["engineering"].submit_query.assert_awaited_once()

    async def test_submit_query_to_inactive_domain(self, mock_session_cls):
        mgr = DomainManager()
        req = BridgeRequest(
            type=RequestType.DOMAIN_QUERY,
            domain_id="engineering",
            agent_id="a",
            task="t",
            request_id="r1",
        )
        result = await mgr.handle_domain_query(req, on_output=AsyncMock())
        assert result["status"] == "error"
        assert "not active" in result["message"]

    async def test_background_domain(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        result = mgr.background_domain("engineering")
        assert result["state"] == "backgrounded"

    async def test_refocus_domain(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        mgr.background_domain("engineering")
        result = mgr.refocus_domain("engineering")
        assert result["state"] == "active"

    async def test_resume_returns_buffered_entries(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        entry = OutputEntry(
            output_id=0, agent_id="a", task="t", output="hello", request_id="r1"
        )
        mock_session_cls["engineering"].buffer.since.return_value = [entry]
        results = mgr.handle_resume("engineering", cursor=-1)
        assert len(results) == 1
        assert results[0]["output"] == "hello"
        assert results[0]["output_id"] == "0"

    async def test_deactivate_domain(self, mock_session_cls):
        mgr = DomainManager()
        await mgr.activate_domain("engineering")
        result = await mgr.deactivate_domain("engineering")
        assert result["state"] == "deactivated"

    async def test_get_domain_state(self, mock_session_cls):
        mgr = DomainManager()
        assert mgr.get_domain_state("engineering") is None
        await mgr.activate_domain("engineering")
        state = mgr.get_domain_state("engineering")
        assert state["domain_id"] == "engineering"
        assert state["state"] == "active"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest bridge/tests/test_domain_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bridge.domain_manager'`

- [ ] **Step 3: Implement domain_manager.py**

```python
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
                    domain_id, session.state.value,
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
                request.agent_id, request.task, "invalid_request",
                f"Domain '{request.domain_id}' is not active",
            )
        await session.submit_query(
            request.agent_id, request.task, request.request_id,
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
                e.agent_id, e.task, e.output,
                domain_id=domain_id, request_id=e.request_id,
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
            domain_id, session.state.value,
            session.buffer.count_since(-1),
        )

    def refocus_domain(self, domain_id) -> dict:
        session = self._sessions.get(domain_id)
        if not session:
            return make_domain_state(domain_id, "inactive", 0)
        session.refocus()
        return make_domain_state(
            domain_id, session.state.value,
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
            domain_id, session.state.value,
            session.buffer.count_since(-1),
        )

    def list_active_domains(self) -> list[str]:
        return [
            did for did, s in self._sessions.items()
            if s.state in (SessionState.ACTIVE, SessionState.BACKGROUNDED)
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest bridge/tests/test_domain_manager.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Run linters and commit**

```bash
black bridge/domain_manager.py bridge/tests/test_domain_manager.py
flake8 bridge/domain_manager.py bridge/tests/test_domain_manager.py --select=E9,F63,F7,F82
git add bridge/domain_manager.py bridge/tests/test_domain_manager.py
git commit -m "feat(bridge): add domain session manager for lifecycle orchestration

Routes domain queries to sessions, handles activate/background/refocus/
deactivate/resume. Produces domain_state notifications for the frontend."
```

---

### Task 5: Server Integration & Backward Compatibility

**Files:**
- Create: `bridge/server.py`
- Create: `bridge/tests/test_server.py`
- Modify: `bridge/bridge.py` — becomes thin entry point
- Modify: `bridge/PROTOCOL.md` — extended protocol docs

**Interfaces:**
- Consumes: `bridge.protocol.*` (Task 1), `bridge.conversation.ConversationEngine` (Task 2), `bridge.domain_manager.DomainManager` (Task 4)
- Produces: `BridgeServer` class with `async serve()`. `bridge.py` still works as `python bridge/bridge.py` entry point.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for bridge.server — WebSocket routing and backward compat."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bridge.server import BridgeServer


@pytest.fixture
def mock_engines(monkeypatch):
    conv_engine = MagicMock()
    conv_engine.handle_request.return_value = {
        "agent_id": "test", "task": "hi", "output": "hello",
        "status": "ok",
    }

    domain_mgr = AsyncMock()
    domain_mgr.handle_domain_query = AsyncMock(return_value=None)
    domain_mgr.activate_domain = AsyncMock(return_value={
        "type": "domain_state", "domain_id": "engineering",
        "state": "active", "unread_count": 0,
    })
    domain_mgr.handle_resume = MagicMock(return_value=[])
    domain_mgr.background_domain = MagicMock(return_value={
        "type": "domain_state", "domain_id": "engineering",
        "state": "backgrounded", "unread_count": 0,
    })
    domain_mgr.refocus_domain = MagicMock(return_value={
        "type": "domain_state", "domain_id": "engineering",
        "state": "active", "unread_count": 0,
    })

    monkeypatch.setattr("bridge.server.ConversationEngine", lambda **kw: conv_engine)
    monkeypatch.setattr("bridge.server.DomainManager", lambda **kw: domain_mgr)
    return conv_engine, domain_mgr


@pytest.mark.asyncio
class TestBridgeServerDispatch:
    async def test_legacy_request_routes_to_conversation(self, mock_engines):
        conv, _ = mock_engines
        server = BridgeServer()
        resp = await server.dispatch({"agent_id": "test", "task": "hi"})
        assert resp == [conv.handle_request.return_value]

    async def test_conversation_type_routes_to_conversation(self, mock_engines):
        conv, _ = mock_engines
        server = BridgeServer()
        resp = await server.dispatch(
            {"type": "conversation", "agent_id": "test", "task": "hi"}
        )
        assert resp == [conv.handle_request.return_value]

    async def test_domain_query_routes_to_domain_manager(self, mock_engines):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        resp = await server.dispatch({
            "type": "domain_query", "domain_id": "engineering",
            "agent_id": "systems-architect", "task": "review",
            "request_id": "r1",
        })
        domain_mgr.handle_domain_query.assert_awaited_once()

    async def test_resume_returns_buffered_entries(self, mock_engines):
        _, domain_mgr = mock_engines
        domain_mgr.handle_resume.return_value = [
            {"agent_id": "a", "output": "buffered", "status": "ok",
             "task": "t", "output_id": "0", "domain_id": "engineering",
             "request_id": "r1"},
        ]
        server = BridgeServer()
        resp = await server.dispatch({
            "type": "resume", "domain_id": "engineering", "cursor": "-1",
        })
        assert len(resp) == 1
        assert resp[0]["output"] == "buffered"

    async def test_activate_domain_dispatch(self, mock_engines):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        resp = await server.dispatch({
            "type": "activate_domain", "domain_id": "engineering",
        })
        domain_mgr.activate_domain.assert_awaited_once_with("engineering")

    async def test_background_domain_dispatch(self, mock_engines):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        resp = await server.dispatch({
            "type": "background_domain", "domain_id": "engineering",
        })
        domain_mgr.background_domain.assert_called_once_with("engineering")

    async def test_refocus_domain_dispatch(self, mock_engines):
        _, domain_mgr = mock_engines
        server = BridgeServer()
        resp = await server.dispatch({
            "type": "refocus_domain", "domain_id": "engineering",
        })
        domain_mgr.refocus_domain.assert_called_once_with("engineering")

    async def test_invalid_json_returns_error(self, mock_engines):
        server = BridgeServer()
        resp = await server.dispatch_raw("not json {{{")
        assert len(resp) == 1
        assert resp[0]["status"] == "error"

    async def test_validation_error_returns_error(self, mock_engines):
        server = BridgeServer()
        resp = await server.dispatch(
            {"type": "domain_query", "domain_id": "", "agent_id": "", "task": ""}
        )
        assert len(resp) == 1
        assert resp[0]["status"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest bridge/tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bridge.server'`

- [ ] **Step 3: Implement server.py**

```python
"""WebSocket bridge server — protocol routing for two engines.

Routes incoming messages to the conversation engine or domain session
manager based on the protocol's type field. Handles push delivery of
domain session output and domain state notifications.

D-005: zero UI awareness.
D-015: ws://localhost:8765.
"""

import asyncio
import json
import sys

import websockets

from bridge.conversation import ConversationEngine
from bridge.domain_manager import DomainManager
from bridge.protocol import (
    RequestType,
    classify_request,
    parse_request,
    validate_request,
    make_error,
    make_success,
    make_domain_state,
)

LISTEN_HOST = "localhost"
LISTEN_PORT = 8765

_LIFECYCLE_TYPES = {
    "activate_domain",
    "background_domain",
    "refocus_domain",
    "deactivate_domain",
}


class BridgeServer:
    def __init__(self, base_path=None):
        self.conversation = ConversationEngine()
        self.domains = DomainManager(base_path=base_path)
        self._websocket = None

    async def dispatch_raw(self, raw_message: str) -> list[dict]:
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError) as exc:
            return [make_error("", "", "invalid_request", f"Bad JSON: {exc}")]
        return await self.dispatch(data)

    async def dispatch(self, data: dict) -> list[dict]:
        msg_type = data.get("type", "")

        if msg_type in _LIFECYCLE_TYPES:
            return await self._handle_lifecycle(msg_type, data)

        request = parse_request(data)
        error = validate_request(request)
        if error:
            return [make_error(request.agent_id, request.task, "invalid_request", error)]

        if request.type == RequestType.CONVERSATION:
            resp = await asyncio.to_thread(
                self.conversation.handle_request, data
            )
            return [resp]

        if request.type == RequestType.DOMAIN_QUERY:
            result = await self.domains.handle_domain_query(
                request, on_output=self._push_output
            )
            return [result] if result else []

        if request.type == RequestType.RESUME:
            entries = self.domains.handle_resume(request.domain_id, request.cursor)
            state = self.domains.get_domain_state(request.domain_id)
            if state:
                self.domains.refocus_domain(request.domain_id)
            return entries

        return [make_error("", "", "invalid_request", f"Unknown type: {msg_type}")]

    async def _handle_lifecycle(self, msg_type, data):
        domain_id = data.get("domain_id", "")
        if not domain_id:
            return [make_error("", "", "invalid_request", "domain_id is required")]

        if msg_type == "activate_domain":
            result = await self.domains.activate_domain(domain_id)
            return [result]
        elif msg_type == "background_domain":
            return [self.domains.background_domain(domain_id)]
        elif msg_type == "refocus_domain":
            return [self.domains.refocus_domain(domain_id)]
        elif msg_type == "deactivate_domain":
            result = await self.domains.deactivate_domain(domain_id)
            return [result]
        return []

    async def _push_output(self, domain_id, entry):
        if self._websocket:
            resp = make_success(
                entry.agent_id, entry.task, entry.output,
                domain_id=domain_id,
                request_id=entry.request_id,
                output_id=str(entry.output_id),
            )
            await self._websocket.send(json.dumps(resp))

    async def _handle_connection(self, websocket):
        self._websocket = websocket
        try:
            async for raw in websocket:
                responses = await self.dispatch_raw(raw)
                for resp in responses:
                    await websocket.send(json.dumps(resp))
        finally:
            self._websocket = None

    async def serve(self):
        async with websockets.serve(
            self._handle_connection,
            LISTEN_HOST,
            LISTEN_PORT,
        ):
            print(
                f"Bridge running on ws://{LISTEN_HOST}:{LISTEN_PORT}",
                file=sys.stderr,
            )
            await asyncio.Future()


async def serve():
    server = BridgeServer()
    await server.serve()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest bridge/tests/test_server.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Update bridge.py to delegate to server.py**

Replace the body of `bridge/bridge.py` — keep it working as a standalone entry point but delegate to the new modules:

```python
"""WebSocket bridge server — entry point.

This is the backward-compatible entry point. The implementation has moved to:
- bridge/server.py       — WebSocket server with protocol routing
- bridge/conversation.py — conversation engine (Haiku, NPC chat)
- bridge/domain_manager.py — domain session orchestration
- bridge/domain_session.py — Agent SDK runtime per domain

D-005: zero UI awareness.
D-006: synchronous with timeout (conversation engine).
D-015: ws://localhost:8765.
"""

import asyncio

from bridge.server import serve


if __name__ == "__main__":
    asyncio.run(serve())
```

- [ ] **Step 6: Update PROTOCOL.md with extended protocol**

Replace `bridge/PROTOCOL.md` with the extended protocol covering all message types:

````markdown
# Bridge Protocol

WebSocket on `ws://localhost:8765` (D-015). JSON messages, one per WebSocket frame.

## Request Types

### Conversation (backward-compatible with M8)

```json
{
  "type": "conversation",
  "agent_id": "security-auditor",
  "task": "What's your take on the new hire?",
  "request_id": "optional-uuid"
}
```

A request **without** a `type` field is treated as `"conversation"` — existing
clients work without changes.

### Domain Query

```json
{
  "type": "domain_query",
  "domain_id": "engineering",
  "agent_id": "systems-architect",
  "task": "Review the auth middleware",
  "request_id": "uuid"
}
```

Domain queries run asynchronously. The response arrives as a push message
when the Agent SDK completes. If the domain is backgrounded, output
accumulates in the buffer for later resume.

### Resume

```json
{
  "type": "resume",
  "domain_id": "engineering",
  "cursor": "last-seen-output-id"
}
```

Returns all output entries since the cursor. Also refocuses the domain
(transitions from BACKGROUNDED to ACTIVE).

### Lifecycle Commands

```json
{"type": "activate_domain", "domain_id": "engineering"}
{"type": "background_domain", "domain_id": "engineering"}
{"type": "refocus_domain", "domain_id": "engineering"}
{"type": "deactivate_domain", "domain_id": "engineering"}
```

## Response Format

Both engines use the same response shape:

```json
{
  "agent_id": "systems-architect",
  "task": "Review the auth middleware",
  "output": "Looking at the middleware...",
  "status": "ok",
  "domain_id": "engineering",
  "request_id": "uuid",
  "output_id": "0"
}
```

Error responses add `error_type` and `message`:

```json
{
  "agent_id": "systems-architect",
  "task": "Review the auth middleware",
  "output": "",
  "status": "error",
  "error_type": "not_found",
  "message": "No agent 'systems-architect'"
}
```

## Domain State Notifications (push)

Sent by the bridge when domain state changes:

```json
{
  "type": "domain_state",
  "domain_id": "engineering",
  "state": "backgrounded",
  "unread_count": 3
}
```

## Domain Session States

```
INACTIVE → ACTIVATING → ACTIVE → BACKGROUNDED → ACTIVE (refocus)
                          ↓           ↓
                     DEACTIVATED  DEACTIVATED
```
````

- [ ] **Step 7: Run all tests**

Run: `python -m pytest bridge/tests/ -v`
Expected: All tests across all 6 test files PASS

- [ ] **Step 8: Run full linter suite**

```bash
black bridge/
flake8 bridge/ --select=E9,F63,F7,F82
```

- [ ] **Step 9: Verify backward compatibility**

Test that the old request format still works by running the existing `test_agents.py` and
confirming that `bridge/bridge.py` still launches:

```bash
python -m pytest bridge/tests/test_agents.py -v
python -c "from bridge.server import BridgeServer; print('Import OK')"
```

- [ ] **Step 10: Commit**

```bash
git add bridge/server.py bridge/tests/test_server.py bridge/bridge.py bridge/PROTOCOL.md
git commit -m "feat(bridge): add WebSocket server with protocol routing

Routes messages to conversation engine or domain manager by type field.
Legacy requests (no type) route to conversation for backward compat.
Updates bridge.py as thin entry point, PROTOCOL.md with extended protocol."
```

---

## Verification Checklist

After all tasks are complete, verify:

1. `python -m pytest bridge/tests/ -v` — all tests pass
2. `black --check bridge/` — formatting passes
3. `flake8 bridge/ --select=E9,F63,F7,F82` — no syntax errors
4. `python bridge/bridge.py` — server starts on ws://localhost:8765 (Ctrl+C to stop)
5. Send a legacy request via wscat: `echo '{"agent_id":"systems-architect","task":"hello"}' | wscat -c ws://localhost:8765` — gets a conversation response
6. Send a domain activation: `echo '{"type":"activate_domain","domain_id":"engineering"}' | wscat -c ws://localhost:8765` — gets a domain_state response
7. The Godot smoke test still passes: `godot --headless tests/smoke_test.tscn`
