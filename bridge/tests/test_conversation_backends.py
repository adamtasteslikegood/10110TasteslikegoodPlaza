"""Offline execution contracts for default Claude Code and explicit API mode."""

import asyncio
from dataclasses import replace
import inspect
import json
from unittest.mock import AsyncMock, MagicMock

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)
import httpx
import pytest

from bridge.config import ConfigError, default_config, load_config
from bridge.conversation import ConversationEngine


def terminal(**changes):
    return ResultMessage(
        **{
            "subtype": "success",
            "duration_ms": 1,
            "duration_api_ms": 1,
            "is_error": False,
            "num_turns": 1,
            "session_id": "observed-session",
            "result": "answer",
            **changes,
        }
    )


def assistant(text="answer", **changes):
    return AssistantMessage(content=[TextBlock(text=text)], model="test", **changes)


def install_sdk(monkeypatch, stream=None, *, connect=None, disconnect=None):
    from bridge import conversation_sdk

    clients = []

    def factory(*, options):
        client = AsyncMock()
        client.options = options
        client.connect.side_effect = connect
        client.disconnect.side_effect = disconnect

        async def receive():
            for message in stream if stream is not None else [assistant(), terminal()]:
                yield message

        client.receive_response = receive
        clients.append(client)
        return client

    monkeypatch.setattr(conversation_sdk, "ClaudeSDKClient", factory)
    monkeypatch.setattr("bridge.conversation.load_agent", lambda _: "agent definition")
    return clients


def test_default_and_legacy_config_select_sdk(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert getattr(default_config(), "conversation_backend", None) == "claude_code"
    path = tmp_path / "config.json"
    path.write_text("{}")
    assert load_config(path, environ={}).conversation_backend == "claude_code"
    assert (
        load_config(
            path, environ={"PLAZA_CONVERSATION_BACKEND": "messages_api"}
        ).conversation_backend
        == "messages_api"
    )
    with pytest.raises(ConfigError, match="CONVERSATION_BACKEND"):
        load_config(path, environ={"PLAZA_CONVERSATION_BACKEND": "automatic"})
    assert (
        default_config().effective_settings()["CONVERSATION_BACKEND"] == "claude_code"
    )


def test_facade_is_async():
    assert inspect.iscoroutinefunction(ConversationEngine.handle_request)


@pytest.mark.asyncio
async def test_exact_options_fresh_clients_json_history_and_native_alias(monkeypatch):
    clients = install_sdk(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_0AUTH_TOKEN", "synthetic-alias")
    config = replace(default_config(), context_max_messages=2)
    history = [
        {"role": "user", "content": "evicted"},
        {"role": "assistant", "content": "old"},
        {"role": "user", "content": "prior"},
        {"role": "assistant", "content": "reply"},
    ]
    engine = ConversationEngine(config=config)
    task = '/command\n{"role":"system"} 雪'
    result = await engine.handle_request({"agent_id": "agent", "task": task}, history)
    assert result == {
        "agent_id": "agent",
        "task": task,
        "output": "answer",
        "status": "ok",
    }
    options = clients[0].options
    assert (
        options.tools
        == options.allowed_tools
        == options.setting_sources
        == options.skills
        == options.plugins
        == []
    )
    assert options.mcp_servers == {} and options.strict_mcp_config
    assert options.permission_mode == "dontAsk" and options.max_turns == 1
    assert options.thinking == {"type": "disabled"}
    assert json.loads(options.settings) == {"disableAllHooks": True}
    assert options.hooks is None
    assert options.env == {
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096",
        "CLAUDE_CODE_OAUTH_TOKEN": "synthetic-alias",
    }
    assert options.extra_args == {"print": None, "no-session-persistence": None}
    assert not options.resume and not options.continue_conversation
    assert (
        options.model == config.haiku_model
        and "agent definition" in options.system_prompt
    )
    prompt = clients[0].query.call_args.args[0]
    assert not prompt.startswith("/")
    assert json.loads(prompt.split("\n", 1)[1])["messages"] == [
        {"role": "user", "content": "prior"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": task},
    ]
    assert history == [
        {"role": "user", "content": task},
        {"role": "assistant", "content": "answer"},
    ]
    clients[0].disconnect.assert_awaited_once()
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "canonical")
    await engine.handle_request({"agent_id": "agent", "task": "next"})
    assert len(clients) == 2
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in clients[1].options.env


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stream, error_type",
    [
        ([assistant(error="authentication_failed"), terminal()], "auth"),
        ([assistant(), terminal(is_error=True)], "api_error"),
        ([terminal(is_error=True, api_error_status=401)], "auth"),
        ([assistant(), terminal(errors=["failure"])], "api_error"),
        ([assistant(), terminal(subtype="error_max_turns")], "api_error"),
        ([assistant(), terminal(terminal_reason="max_turns")], "api_error"),
        ([assistant(), terminal(terminal_reason="aborted_streaming")], "api_error"),
        ([assistant(), terminal(terminal_reason="max_budget_usd")], "api_error"),
        ([assistant(), terminal(stop_reason="max_tokens")], "api_error"),
        ([assistant(stop_reason="max_tokens"), terminal()], "api_error"),
        ([assistant()], "api_error"),
        ([terminal(), terminal()], "api_error"),
        (
            [
                AssistantMessage(
                    content=[ToolUseBlock(id="x", name="Bash", input={})], model="test"
                ),
                terminal(),
            ],
            "api_error",
        ),
        ([terminal(deferred_tool_use={"name": "Bash"})], "api_error"),
    ],
)
async def test_typed_errors_do_not_commit_partial_reply_or_fallback(
    monkeypatch, stream, error_type
):
    clients = install_sdk(monkeypatch, stream)
    from bridge import conversation_api

    api = MagicMock(side_effect=AssertionError("no fallback"))
    monkeypatch.setattr(conversation_api, "AsyncAnthropic", api)
    history = []
    result = await ConversationEngine().handle_request(
        {"agent_id": "agent", "task": "hello"}, history
    )
    assert result["error_type"] == error_type and result["output"] == ""
    assert history == []
    clients[0].disconnect.assert_awaited_once()
    api.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stream, output",
    [
        ([assistant("雪🚀"), terminal(result="雪🚀")], "雪🚀"),
        ([terminal(result="fallback")], "fallback"),
        ([terminal(result="")], ""),
    ],
)
async def test_success_text_is_not_duplicated_and_empty_is_not_stored(
    monkeypatch, stream, output
):
    install_sdk(monkeypatch, stream)
    history = []
    result = await ConversationEngine().handle_request(
        {"agent_id": "agent", "task": "hello"}, history
    )
    assert result["status"] == "ok" and result["output"] == output
    assert len(history) == (2 if output else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["connect", "receive", "cleanup"])
@pytest.mark.parametrize("timeout", [False, True])
async def test_cancellation_and_deadline_drain_cleanup_before_return(
    monkeypatch, phase, timeout
):
    from bridge.conversation import ExecutionMetadata

    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def connect():
        if phase == "connect":
            entered.set()
            await asyncio.Future()

    async def disconnect():
        with anyio.CancelScope(shield=True):
            cleaning.set()
            await release.wait()

    clients = install_sdk(monkeypatch, connect=connect, disconnect=disconnect)
    # Factory wraps receive so cancellation can occur after an observed init ID.
    from bridge import conversation_sdk

    original = conversation_sdk.ClaudeSDKClient

    def factory(**kwargs):
        client = original(**kwargs)

        async def receive():
            yield SystemMessage(
                subtype="init", data={"session_id": "observed-before-cancel"}
            )
            if phase == "receive":
                entered.set()
                await asyncio.Future()
            yield assistant()
            yield terminal()

        client.receive_response = receive
        return client

    monkeypatch.setattr(conversation_sdk, "ClaudeSDKClient", factory)
    history, metadata = [], ExecutionMetadata()
    engine = ConversationEngine(timeout=0.02 if timeout else 60)
    task = asyncio.create_task(
        engine.handle_request(
            {"agent_id": "agent", "task": "hi"}, history, metadata=metadata
        )
    )
    if phase == "cleanup":
        await asyncio.wait_for(cleaning.wait(), 1)
    else:
        await asyncio.wait_for(entered.wait(), 1)
    if not timeout or phase == "cleanup":
        task.cancel("original")
    await asyncio.wait_for(cleaning.wait(), 1)
    assert history == [] and not task.done()
    if not timeout or phase == "cleanup":
        task.cancel("repeated")
        await asyncio.sleep(0)
        assert not task.done()
    release.set()
    if not timeout or phase == "cleanup":
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert (await task)["error_type"] == "timeout"
    assert history == []
    clients[0].disconnect.assert_awaited_once()
    if phase == "receive":
        assert metadata.provider_session_id == "observed-before-cancel"
    # A new call uses a fresh lifetime after cancellation.
    install_sdk(monkeypatch)
    assert (await engine.handle_request({"agent_id": "agent", "task": "next"}))[
        "status"
    ] == "ok"
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "npc-sdk-request"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key", [None, "", "sk-ant-oat01-setup", "sk-ant-ort01-refresh", "Bearer token"]
)
async def test_explicit_api_rejects_missing_or_oauth_keys_before_http(monkeypatch, key):
    from bridge import conversation_api

    if key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "must-not-use")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "must-not-use")
    monkeypatch.setattr("bridge.conversation.load_agent", lambda _: "definition")
    factory = MagicMock(
        side_effect=AssertionError("HTTP client must not be constructed")
    )
    monkeypatch.setattr(conversation_api, "AsyncAnthropic", factory)
    config = replace(default_config(), conversation_backend="messages_api")
    result = await ConversationEngine(config=config).handle_request(
        {"agent_id": "agent", "task": "hi"}
    )
    assert result["error_type"] == "auth"
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_api_real_http_headers_ignore_inherited_bearer(monkeypatch):
    from anthropic import AsyncAnthropic
    from bridge import conversation_api

    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "API reply"}],
                "model": "test",
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-synthetic")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "inherited-bearer")
    monkeypatch.setattr("bridge.conversation.load_agent", lambda _: "definition")
    monkeypatch.setattr(
        conversation_api,
        "AsyncAnthropic",
        lambda **kwargs: AsyncAnthropic(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ),
    )
    config = replace(default_config(), conversation_backend="messages_api")
    from bridge.conversation import ExecutionMetadata

    metadata = ExecutionMetadata()
    result = await ConversationEngine(config=config).handle_request(
        {"agent_id": "agent", "task": "hi"}, metadata=metadata
    )
    assert result["output"] == "API reply"
    assert len(seen) == 1
    assert seen[0].headers["x-api-key"] == "sk-ant-api03-synthetic"
    assert "authorization" not in seen[0].headers
    assert metadata.provider_session_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown", [False, True])
async def test_peer_disconnect_and_service_shutdown_drain_sdk_once(
    monkeypatch, runtime_config, runtime_archive, shutdown
):
    import websockets
    from bridge.server import BridgeServer

    entered, cleaned = asyncio.Event(), asyncio.Event()
    clients = install_sdk(monkeypatch)
    from bridge import conversation_sdk

    original = conversation_sdk.ClaudeSDKClient

    def factory(**kwargs):
        client = original(**kwargs)

        async def receive():
            yield SystemMessage(
                subtype="init", data={"session_id": "disconnected-session"}
            )
            entered.set()
            await asyncio.Future()

        async def disconnect():
            await asyncio.sleep(0)
            cleaned.set()

        client.receive_response = receive
        client.disconnect.side_effect = disconnect
        return client

    monkeypatch.setattr(conversation_sdk, "ClaudeSDKClient", factory)
    recorder, writer = runtime_archive
    server = BridgeServer(config=runtime_config, recorder=recorder)
    listener = await websockets.serve(server._handle_connection, "127.0.0.1", 0)
    socket = await websockets.connect(
        f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
    )
    try:
        await socket.send(
            json.dumps({"agent_id": "agent", "task": "hi", "request_id": "r"})
        )
        await asyncio.wait_for(entered.wait(), 1)
        if shutdown:
            listener.close()
        else:
            await socket.close()
        await asyncio.wait_for(cleaned.wait(), 1)
        await asyncio.wait_for(
            listener.wait_closed() if shutdown else socket.wait_closed(), 1
        )
    finally:
        await socket.close()
        listener.close()
        await listener.wait_closed()
        server.close()
    records = [record for kind, record, _ in writer.records if kind == "transcript"]
    assert [(r["role"], r["outcome"]) for r in records] == [
        ("user", "input"),
        ("error", "cancelled"),
    ]
    assert records[-1]["provider_session_id"] == "disconnected-session"
    clients[0].disconnect.assert_awaited_once()
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "npc-sdk-request"]


@pytest.mark.asyncio
async def test_simultaneous_observed_sessions_are_request_local(
    monkeypatch, runtime_config, runtime_archive
):
    from bridge import conversation_sdk
    from bridge.server import BridgeServer

    install_sdk(monkeypatch)
    both = asyncio.Event()
    arrived = 0

    def factory(**kwargs):
        client = AsyncMock()

        async def receive():
            nonlocal arrived
            text = json.loads(client.query.call_args.args[0].split("\n", 1)[1])[
                "messages"
            ][-1]["content"]
            arrived += 1
            if arrived == 2:
                both.set()
            await both.wait()
            yield assistant(text, session_id="early-" + text)
            yield terminal(session_id="final-" + text, result=text)

        client.receive_response = receive
        return client

    monkeypatch.setattr(conversation_sdk, "ClaudeSDKClient", factory)
    recorder, writer = runtime_archive
    server = BridgeServer(config=runtime_config, recorder=recorder)
    responses = await asyncio.gather(
        *(
            server.dispatch(
                {"agent_id": "agent", "task": text, "request_id": text},
                connection_id=text,
            )
            for text in ("one", "two")
        )
    )
    for text, responses_for_request in zip(("one", "two"), responses):
        assert responses_for_request == [
            {
                "agent_id": "agent",
                "task": text,
                "output": text,
                "status": "ok",
                "request_id": text,
            }
        ]
    records = [
        r
        for kind, r, _ in writer.records
        if kind == "transcript" and r["role"] == "assistant"
    ]
    assert {r["request_id"]: r["provider_session_id"] for r in records} == {
        "one": "final-one",
        "two": "final-two",
    }


@pytest.mark.asyncio
async def test_cancel_before_worker_scope_publication_never_starts_client(monkeypatch):
    clients = install_sdk(monkeypatch)
    history = []
    task = asyncio.create_task(
        ConversationEngine().handle_request(
            {"agent_id": "agent", "task": "hi"}, history
        )
    )
    await asyncio.sleep(0)  # facade has created its worker; worker has not run yet
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert clients == [] and history == []
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "npc-sdk-request"]


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_commit_success_and_keeps_observed_id(
    monkeypatch, runtime_config, runtime_archive
):
    async def disconnect():
        raise RuntimeError("cleanup failed")

    install_sdk(monkeypatch, disconnect=disconnect)
    from bridge.server import BridgeServer

    recorder, writer = runtime_archive
    server = BridgeServer(config=runtime_config, recorder=recorder)
    histories = {}
    response = await server.dispatch({"agent_id": "agent", "task": "hi"}, histories)
    assert response[0]["error_type"] == "api_error"
    assert response[0]["message"] == "cleanup failed"
    assert histories == {}
    records = [r for kind, r, _ in writer.records if kind == "transcript"]
    assert [(r["role"], r["outcome"]) for r in records] == [
        ("user", "input"),
        ("error", "failure"),
    ]
    assert records[-1]["provider_session_id"] == "observed-session"


@pytest.mark.asyncio
async def test_explicit_api_deadline_bounds_total_execution(monkeypatch):
    from anthropic import AsyncAnthropic
    from bridge import conversation_api

    async def stalled(request):
        await asyncio.Future()

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(stalled))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-synthetic")
    monkeypatch.setattr("bridge.conversation.load_agent", lambda _: "definition")
    monkeypatch.setattr(
        conversation_api,
        "AsyncAnthropic",
        lambda **kwargs: AsyncAnthropic(**kwargs, http_client=http_client),
    )
    config = replace(
        default_config(),
        conversation_backend="messages_api",
        conversation_timeout_seconds=0.02,
    )
    history = []
    response = await asyncio.wait_for(
        ConversationEngine(config=config).handle_request(
            {"agent_id": "agent", "task": "hi"}, history
        ),
        0.5,
    )
    assert response["error_type"] == "timeout"
    assert history == [] and http_client.is_closed


@pytest.mark.asyncio
async def test_installed_transport_reaps_local_child_on_cancel(monkeypatch):
    """Exercise SDK close on a harmless stdin reader; never launch Claude."""
    import os
    import sys
    from claude_agent_sdk._internal.transport.subprocess_cli import (
        SubprocessCLITransport,
    )
    from bridge import conversation_sdk

    entered, cleaned = asyncio.Event(), asyncio.Event()
    processes = []

    class LocalClient:
        def __init__(self, *, options):
            self.transport = SubprocessCLITransport(prompt="", options=options)

        async def connect(self):
            process = await anyio.open_process(
                [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"]
            )
            processes.append(process)
            self.transport._process = process
            self.transport._stdin_stream = process.stdin

        async def query(self, prompt):
            pass

        async def receive_response(self):
            yield SystemMessage(subtype="init", data={"session_id": "local-child"})
            entered.set()
            await asyncio.Future()

        async def disconnect(self):
            await self.transport.close()
            cleaned.set()

    monkeypatch.setattr(conversation_sdk, "ClaudeSDKClient", LocalClient)
    monkeypatch.setattr("bridge.conversation.load_agent", lambda _: "definition")
    history = []
    task = asyncio.create_task(
        ConversationEngine().handle_request(
            {"agent_id": "agent", "task": "hi"}, history
        )
    )
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert cleaned.is_set() and processes[0].returncode == 0 and history == []
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)


def test_installed_transport_builds_supported_isolation_arguments():
    from claude_agent_sdk._internal.transport.subprocess_cli import (
        SubprocessCLITransport,
    )
    from bridge.conversation_sdk import _options

    options = _options("definition", "test", 4096)
    transport = SubprocessCLITransport(prompt="data", options=options)
    transport._cli_path = "unused-offline-cli"
    command = transport._build_command()
    assert command[command.index("--tools") + 1] == ""
    assert "--setting-sources=" in command
    assert "--strict-mcp-config" in command
    assert "--print" in command and "--no-session-persistence" in command
    assert "--resume" not in command and "--continue" not in command
    assert json.loads(command[command.index("--settings") + 1])["disableAllHooks"]


@pytest.mark.asyncio
async def test_default_sdk_with_api_key_ignores_nontext_echoes(monkeypatch):
    from claude_agent_sdk import ThinkingBlock, UserMessage
    from bridge import conversation_api

    stream = [
        UserMessage(content="echo must not become output"),
        AssistantMessage(
            content=[
                ThinkingBlock(thinking="private thought", signature="synthetic"),
                TextBlock(text="first"),
                TextBlock(text="second"),
            ],
            model="test",
        ),
        terminal(result="first\n\nsecond"),
    ]
    install_sdk(monkeypatch, stream)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-synthetic")
    api = MagicMock(
        side_effect=AssertionError("default must not construct an API client")
    )
    monkeypatch.setattr(conversation_api, "AsyncAnthropic", api)
    response = await ConversationEngine().handle_request(
        {"agent_id": "agent", "task": "hi"}
    )
    assert response["output"] == "first\n\nsecond"
    api.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "credential", ["ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", None]
)
@pytest.mark.parametrize("sdk_fails", [False, True])
async def test_native_api_key_and_oauth_use_same_sdk_route_without_api_fallback(
    monkeypatch, credential, sdk_fails
):
    from bridge import conversation_api

    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_0AUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    if credential:
        monkeypatch.setenv(credential, "synthetic-credential")

    async def connect():
        if sdk_fails:
            raise RuntimeError("SDK connection failed")

    clients = install_sdk(monkeypatch, connect=connect)
    api = MagicMock(side_effect=AssertionError("no API client on default path"))
    monkeypatch.setattr(conversation_api, "AsyncAnthropic", api)
    monkeypatch.setattr("anthropic.Anthropic", api)
    response = await ConversationEngine().handle_request(
        {"agent_id": "agent", "task": "same default route"}
    )
    assert len(clients) == 1
    clients[0].connect.assert_awaited_once()
    clients[0].disconnect.assert_awaited_once()
    assert response["status"] == ("error" if sdk_fails else "ok")
    if sdk_fails:
        assert response["message"] == "SDK connection failed"
    else:
        assert response["output"] == "answer"
    api.assert_not_called()


@pytest.mark.parametrize("canonical", [None, "", "canonical"])
def test_alias_applies_only_when_canonical_is_absent_or_empty(monkeypatch, canonical):
    from bridge.conversation_sdk import _options

    monkeypatch.setenv("CLAUDE_CODE_0AUTH_TOKEN", "alias")
    if canonical is None:
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", canonical)
    options = _options("definition", "model", 93)
    assert options.env.get("CLAUDE_CODE_OAUTH_TOKEN") == (
        None if canonical else "alias"
    )
    assert options.env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "93"


@pytest.mark.asyncio
async def test_api_provider_auth_failure_preserves_error_fields_without_sdk_fallback(
    monkeypatch,
):
    from anthropic import AsyncAnthropic
    from bridge import conversation_api, conversation_sdk

    def respond(request):
        return httpx.Response(
            401,
            json={
                "type": "error",
                "error": {"type": "authentication_error", "message": "invalid API key"},
            },
        )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-synthetic")
    monkeypatch.setattr("bridge.conversation.load_agent", lambda _: "definition")
    monkeypatch.setattr(
        conversation_api,
        "AsyncAnthropic",
        lambda **kwargs: AsyncAnthropic(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ),
    )
    sdk = MagicMock(side_effect=AssertionError("no fallback"))
    monkeypatch.setattr(conversation_sdk, "ClaudeSDKClient", sdk)
    config = replace(default_config(), conversation_backend="messages_api")
    history = []
    response = await ConversationEngine(config=config).handle_request(
        {"agent_id": "agent", "task": "hi"}, history
    )
    assert response["agent_id"] == "agent" and response["task"] == "hi"
    assert response["status"] == "error" and response["error_type"] == "auth"
    assert response["output"] == "" and "invalid API key" in response["message"]
    assert history == []
    sdk.assert_not_called()


@pytest.mark.asyncio
async def test_repeated_server_cancellation_waits_for_npc_cleanup(
    monkeypatch, runtime_config, runtime_archive
):
    import websockets
    from bridge import server as server_module

    ready, entered, cleaning, release = (asyncio.Event() for _ in range(4))
    listeners = []
    original_serve = websockets.serve

    def serve(handler, host, port):
        listener = original_serve(handler, host, 0)
        listeners.append(listener)
        return listener

    monkeypatch.setattr(server_module.websockets, "serve", serve)

    async def connect():
        entered.set()
        await asyncio.Future()

    async def disconnect():
        cleaning.set()
        await release.wait()

    install_sdk(monkeypatch, connect=connect, disconnect=disconnect)
    recorder, writer = runtime_archive
    server = server_module.BridgeServer(config=runtime_config, recorder=recorder)
    original_event = server._event

    def event(name, *args, **kwargs):
        original_event(name, *args, **kwargs)
        if name == "bridge_started":
            ready.set()

    monkeypatch.setattr(server, "_event", event)
    serving = asyncio.create_task(server.serve())
    await asyncio.wait_for(ready.wait(), 1)
    port = listeners[0].server.sockets[0].getsockname()[1]
    socket = await websockets.connect(f"ws://localhost:{port}")
    try:
        await socket.send(json.dumps({"agent_id": "agent", "task": "hi"}))
        await asyncio.wait_for(entered.wait(), 1)
        serving.cancel("first")
        await asyncio.wait_for(cleaning.wait(), 1)
        serving.cancel("second")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not serving.done()
        assert writer.closed == []
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await serving
        await socket.close()
        await listeners[0].server.wait_closed()
    records = [r for kind, r, _ in writer.records if kind == "transcript"]
    assert [(r["role"], r["outcome"]) for r in records] == [
        ("user", "input"),
        ("error", "cancelled"),
    ]
    assert writer.closed == [False]
