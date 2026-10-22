"""Conversation correlation stays opaque, optional, and connection-local."""

import asyncio
import json

import pytest
import websockets

from bridge.server import BridgeServer


@pytest.mark.asyncio
@pytest.mark.parametrize("request_type", [{}, {"type": "conversation"}])
async def test_conversation_echoes_exact_opaque_id(
    request_type, runtime_config, offline_clients
):
    server = BridgeServer(config=runtime_config)
    request_id = "  opaque/雪:42\n"
    response = await server.dispatch_raw(
        json.dumps(
            {
                **request_type,
                "agent_id": "agent",
                "task": "hi",
                "request_id": request_id,
            }
        )
    )
    assert response == [
        {
            "agent_id": "agent",
            "task": "hi",
            "output": "conversation reply",
            "status": "ok",
            "request_id": request_id,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [{}, *({"request_id": value} for value in (None, "", " \t\n", 7, True, [], {}))],
)
@pytest.mark.parametrize("provider_fails", [False, True])
async def test_no_usable_id_preserves_exact_legacy_shape(
    metadata, provider_fails, runtime_config, offline_clients
):
    client, _, _ = offline_clients
    if provider_fails:
        client.reply.side_effect = RuntimeError("provider unavailable")
    server = BridgeServer(config=runtime_config)
    expected = {
        "agent_id": "agent",
        "task": "hi",
        "output": "conversation reply",
        "status": "ok",
    }
    if provider_fails:
        expected.update(
            output="",
            status="error",
            error_type="api_error",
            message="provider unavailable",
        )
    assert await server.dispatch({"agent_id": "agent", "task": "hi", **metadata}) == [
        expected
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload, message, agent_id, task",
    [
        ({"task": "hi"}, "agent_id is required", "", "hi"),
        ({"agent_id": "agent"}, "task is required", "agent", ""),
        (
            {"agent_id": "../agent", "task": "hi"},
            "agent_id contains invalid characters",
            "../agent",
            "hi",
        ),
        (
            {"agent_id": ["agent"], "task": "hi"},
            "agent_id and task must be strings",
            "",
            "",
        ),
        (
            {"agent_id": "agent", "task": 42},
            "agent_id and task must be strings",
            "",
            "",
        ),
    ],
)
async def test_validation_errors_keep_fields_and_echo_id(
    payload, message, agent_id, task, runtime_config, offline_clients
):
    server = BridgeServer(config=runtime_config)
    response = await server.dispatch({**payload, "request_id": "invalid-input"})
    assert response == [
        {
            "agent_id": agent_id,
            "task": task,
            "output": "",
            "status": "error",
            "error_type": "invalid_request",
            "message": message,
            "request_id": "invalid-input",
        }
    ]
    offline_clients[0].reply.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure, error_type, message",
    [
        (RuntimeError("provider unavailable"), "api_error", "provider unavailable"),
        (RuntimeError("authentication failed"), "auth", "authentication failed"),
        (TimeoutError("timed out"), "timeout", "Timed out after 60s"),
    ],
)
async def test_provider_errors_echo_id_without_changing_error_fields(
    failure, error_type, message, runtime_config, offline_clients
):
    client, _, _ = offline_clients
    client.reply.side_effect = failure
    server = BridgeServer(config=runtime_config)
    histories = {}
    assert await server.dispatch(
        {"agent_id": "agent", "task": "hi", "request_id": "provider-error"}, histories
    ) == [
        {
            "agent_id": "agent",
            "task": "hi",
            "output": "",
            "status": "error",
            "error_type": error_type,
            "message": message,
            "request_id": "provider-error",
        }
    ]
    assert histories == {}


@pytest.mark.asyncio
async def test_missing_agent_error_echoes_id(
    runtime_config, offline_clients, monkeypatch
):
    monkeypatch.setattr("bridge.conversation.load_agent", lambda _, **kw: None)
    server = BridgeServer(config=runtime_config)
    response = await server.dispatch(
        {"agent_id": "absent", "task": "hi", "request_id": "missing-agent"}
    )
    assert response == [
        {
            "agent_id": "absent",
            "task": "hi",
            "output": "",
            "status": "error",
            "error_type": "invalid_binding",
            "message": "Agent binding is unavailable",
            "request_id": "missing-agent",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_type",
    [
        "domain_query",
        "resume",
        "activate_domain",
        "background_domain",
        "refocus_domain",
        "deactivate_domain",
    ],
)
async def test_domain_validation_uses_explicit_correlation_without_fabricating_ids(
    request_type, runtime_config, offline_clients
):
    server = BridgeServer(config=runtime_config)
    response = await server.dispatch({"type": request_type, "request_id": "metadata"})
    assert response[0]["error_type"] == "invalid_request"
    assert response[0]["type"] == "domain_error"
    assert response[0]["request_id"] == "metadata"
    missing = await server.dispatch({"type": request_type})
    assert missing[0]["error_type"] == "invalid_request"
    assert "request_id" not in missing[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw", ['{"request_id":"untrusted",', '[{"request_id":"untrusted"}]']
)
async def test_invalid_json_or_nonobject_has_no_trusted_id(
    raw, runtime_config, offline_clients
):
    server = BridgeServer(config=runtime_config)
    response = await server.dispatch_raw(raw)
    assert response[0]["error_type"] == "invalid_request"
    assert "request_id" not in response[0]


@pytest.mark.asyncio
async def test_simultaneous_clients_receive_only_their_own_id(
    runtime_config, offline_clients
):
    server = BridgeServer(config=runtime_config)
    try:
        async with websockets.serve(
            server._handle_connection, "127.0.0.1", 0
        ) as listener:
            uri = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
            async with websockets.connect(uri) as first, websockets.connect(
                uri
            ) as second:

                async def ask(socket, request_id):
                    await socket.send(
                        json.dumps(
                            {
                                "agent_id": "agent",
                                "task": "hi",
                                "request_id": request_id,
                            }
                        )
                    )
                    return json.loads(await asyncio.wait_for(socket.recv(), timeout=5))

                responses = await asyncio.gather(
                    ask(first, "first"), ask(second, "second")
                )
                assert [response["request_id"] for response in responses] == [
                    "first",
                    "second",
                ]
                # A later legacy request must not inherit a previous ID.
                await first.send(json.dumps({"agent_id": "agent", "task": "legacy"}))
                legacy = json.loads(await asyncio.wait_for(first.recv(), timeout=5))
                assert "request_id" not in legacy
    finally:
        server.close()
