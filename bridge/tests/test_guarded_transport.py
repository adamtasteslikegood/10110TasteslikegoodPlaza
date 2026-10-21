"""Error protocol frames must never turn a required hook into success."""

import importlib
import json

import pytest


class Inner:
    def __init__(self):
        self.frames = []
        self.writes = []
        self.closed = False

    async def connect(self):
        pass

    async def write(self, data):
        self.writes.extend(json.loads(line) for line in data.splitlines())

    async def read_messages(self):
        for frame in self.frames:
            yield frame

    async def close(self):
        self.closed = True

    async def end_input(self):
        pass

    def is_ready(self):
        return not self.closed


def request(identifier="request", **changes):
    payload = dict(
        subtype="hook_callback",
        callback_id="hook_0",
        input={"hook_event_name": "PreToolUse"},
    )
    payload.update(changes)
    return dict(type="control_request", request_id=identifier, request=payload)


def reply(value, subtype="success", identifier="request"):
    return (
        json.dumps(
            dict(
                type="control_response",
                response=dict(subtype=subtype, request_id=identifier, response=value),
            )
        )
        + "\n"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value, subtype",
    [
        (None, "error"),
        (None, "success"),
        ({"async": True}, "success"),
        ({"hookSpecificOutput": {"permissionDecision": "allow"}}, "success"),
        ({"anything": "bad"}, "success"),
    ],
)
async def test_normalize_error_and_malformed_reply_to_denial(value, subtype):
    module = importlib.import_module("bridge.guarded_transport")
    inner = Inner()
    transport = module.GuardedTransport(inner)
    inner.frames = [request()]
    stream = transport.read_messages()
    await anext(stream)
    await transport.write(reply(value, subtype))
    assert (
        inner.writes[-1]["response"]["response"]["hookSpecificOutput"][
            "permissionDecision"
        ]
        == "deny"
    )
    assert not transport.pending
    await transport.close()
    await stream.aclose()


@pytest.mark.asyncio
async def test_success_unchanged_and_cancel_suppresses_late_response():
    module = importlib.import_module("bridge.guarded_transport")
    inner = Inner()
    transport = module.GuardedTransport(inner)
    inner.frames = [
        request(),
        dict(type="control_cancel_request", request_id="request"),
    ]
    stream = transport.read_messages()
    await anext(stream)
    await transport.write(reply({}))
    assert inner.writes[-1]["response"]["response"] == {}
    await anext(stream)
    await transport.write(reply({}))
    assert len(inner.writes) == 1
    await transport.close()
    await stream.aclose()


@pytest.mark.asyncio
async def test_duplicate_control_id_breaks_channel():
    module = importlib.import_module("bridge.guarded_transport")
    inner = Inner()
    transport = module.GuardedTransport(inner)
    inner.frames = [request(), request()]
    stream = transport.read_messages()
    await anext(stream)
    with pytest.raises(module.GuardTransportError):
        await anext(stream)
    assert transport.broken
    await transport.close()


@pytest.mark.asyncio
async def test_hung_callback_watchdog_denies_and_suppresses_late_allow(monkeypatch):
    import asyncio

    module = importlib.import_module("bridge.guarded_transport")
    inner = Inner()
    transport = module.GuardedTransport(inner)
    monkeypatch.setattr(transport, "RESPONSE_TIMEOUT", 0.01)
    inner.frames = [request()]
    stream = transport.read_messages()
    await anext(stream)
    await asyncio.sleep(0.03)
    assert (
        inner.writes[-1]["response"]["response"]["hookSpecificOutput"][
            "permissionDecision"
        ]
        == "deny"
    )
    await transport.write(reply({}))
    assert len(inner.writes) == 1 and not transport.pending
    await transport.close()
    await stream.aclose()


@pytest.mark.asyncio
async def test_pending_cancel_and_eof_fail_closed():
    module = importlib.import_module("bridge.guarded_transport")
    for frames in (
        [request()],
        [request(), dict(type="control_cancel_request", request_id="request")],
    ):
        inner = Inner()
        called = []
        transport = module.GuardedTransport(
            inner, on_failure=lambda: called.append(True)
        )
        inner.frames = frames
        stream = transport.read_messages()
        await anext(stream)
        with pytest.raises(module.GuardTransportError):
            await anext(stream)
        assert called and transport.broken
        await transport.close()


@pytest.mark.asyncio
async def test_registered_callback_malformed_input_is_still_guarded():
    module = importlib.import_module("bridge.guarded_transport")
    inner = Inner()
    transport = module.GuardedTransport(inner)
    await transport.write(
        json.dumps(
            {
                "type": "control_request",
                "request": {
                    "subtype": "initialize",
                    "hooks": {"PreToolUse": [{"hookCallbackIds": ["hook_0"]}]},
                },
            }
        )
    )
    inner.frames = [request(input=None)]
    stream = transport.read_messages()
    await anext(stream)
    await transport.write(reply(None, "error"))
    assert (
        inner.writes[-1]["response"]["response"]["hookSpecificOutput"][
            "permissionDecision"
        ]
        == "deny"
    )
    await transport.close()
    await stream.aclose()


@pytest.mark.asyncio
async def test_capacity_overflow_never_evicts_live_guard(monkeypatch):
    module = importlib.import_module("bridge.guarded_transport")
    inner = Inner()
    transport = module.GuardedTransport(inner)
    monkeypatch.setattr(transport, "MAX_PENDING", 1)
    inner.frames = [request(), request("second")]
    stream = transport.read_messages()
    await anext(stream)
    with pytest.raises(module.GuardTransportError):
        await anext(stream)
    assert "request" in transport.pending
    await transport.close()


@pytest.mark.asyncio
async def test_failed_denial_write_cancels_owner_and_retains_pending():
    module = importlib.import_module("bridge.guarded_transport")

    class Broken(Inner):
        async def write(self, data):
            raise OSError("broken pipe")

    inner = Broken()
    called = []
    transport = module.GuardedTransport(inner, on_failure=lambda: called.append(True))
    inner.frames = [request()]
    stream = transport.read_messages()
    await anext(stream)
    with pytest.raises(module.GuardTransportError):
        await transport.write(reply(None, "error"))
    assert transport.broken and called and "request" in transport.pending
    await transport.close()
    await stream.aclose()


@pytest.mark.asyncio
async def test_unclassifiable_hook_fails_closed():
    module = importlib.import_module("bridge.guarded_transport")
    inner = Inner()
    transport = module.GuardedTransport(inner)
    inner.frames = [
        request(callback_id="unknown", input={"hook_event_name": "UnknownEvent"})
    ]
    with pytest.raises(module.GuardTransportError):
        await anext(transport.read_messages())
    await transport.close()


@pytest.mark.asyncio
async def test_blocked_guard_write_is_bounded(monkeypatch):
    import asyncio

    module = importlib.import_module("bridge.guarded_transport")

    class Blocked(Inner):
        async def write(self, data):
            await asyncio.Event().wait()

    inner = Blocked()
    transport = module.GuardedTransport(inner)
    monkeypatch.setattr(transport, "WRITE_TIMEOUT", 0.01, raising=False)
    inner.frames = [request()]
    stream = transport.read_messages()
    await anext(stream)
    with pytest.raises(module.GuardTransportError):
        # The test watchdog is deliberately longer than the production deadline.
        await asyncio.wait_for(transport.write(reply(None, "error")), 0.1)
    assert transport.broken and "request" in transport.pending
    await transport.close()
    await stream.aclose()


@pytest.mark.asyncio
async def test_evicted_late_reply_cannot_become_permission(monkeypatch):
    module = importlib.import_module("bridge.guarded_transport")
    inner = Inner()
    transport = module.GuardedTransport(inner)
    monkeypatch.setattr(transport, "MAX_SETTLED", 1)
    inner.frames = [request("old"), request("new")]
    stream = transport.read_messages()
    await anext(stream)
    await transport.write(reply(None, "error", identifier="old"))
    await anext(stream)
    await transport.write(reply(None, "error", identifier="new"))
    with pytest.raises(module.GuardTransportError):
        await transport.write(reply({}, identifier="old"))
    assert len(inner.writes) == 2
    await transport.close()
    await stream.aclose()
