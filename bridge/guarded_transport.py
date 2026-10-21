"""Pinned SDK transport guard: required hook errors are explicit CLI denials.

This is a protocol adapter, not a permission bypass or host sandbox. Unknown
control traffic breaks the channel and cancels the SDK owner. A bounded watchdog
settles a hung guard before the CLI matcher timeout; late replies are suppressed.
"""

import asyncio
from collections import OrderedDict
import json

import anyio
from claude_agent_sdk import Transport

from bridge.readiness import denial


class GuardTransportError(RuntimeError):
    pass


class GuardedTransport(Transport):
    MAX_PENDING = 64
    MAX_SETTLED = 256
    RESPONSE_TIMEOUT = 7
    WRITE_TIMEOUT = 2

    def __init__(self, inner: Transport, *, on_failure=None):
        self.inner = inner
        self.on_failure = on_failure
        self.pending = {}
        self.settled = OrderedDict()
        self.callbacks = set()
        self.all_callbacks = {}
        self.other_pending = set()
        self.broken = False
        self.closed = False
        self._write_lock = asyncio.Lock()
        self._watchdogs = set()
        self.normalized_denials = 0
        self.timeout_denials = 0
        self.process = None

    def _fail(self):
        self.broken = True
        if self.on_failure:
            self.on_failure()
        return GuardTransportError("Required readiness control channel failed")

    def _settle(self, identifier):
        self.other_pending.discard(identifier)
        timer = self.pending.pop(identifier, None)
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
        self.settled[identifier] = None
        while len(self.settled) > self.MAX_SETTLED:
            self.settled.popitem(last=False)

    @staticmethod
    def _safe_response(value):
        if value == {}:
            return True
        if not isinstance(value, dict) or set(value) != {"hookSpecificOutput"}:
            return False
        detail = value["hookSpecificOutput"]
        return (
            isinstance(detail, dict)
            and set(detail)
            <= {"hookEventName", "permissionDecision", "permissionDecisionReason"}
            and detail.get("hookEventName") == "PreToolUse"
            and detail.get("permissionDecision") == "deny"
            and isinstance(detail.get("permissionDecisionReason", ""), str)
        )

    @staticmethod
    def _deny_frame(identifier):
        return {
            "type": "control_response",
            "response": {
                "subtype": "success",
                "request_id": identifier,
                "response": denial(
                    "Readiness guard control error; stop and review setup."
                ),
            },
        }

    async def _watch(self, identifier):
        try:
            await asyncio.sleep(self.RESPONSE_TIMEOUT)
            with anyio.fail_after(self.WRITE_TIMEOUT):
                await self._timeout_reply(identifier)
        except asyncio.CancelledError:
            pass
        except Exception:
            self._fail()

    async def _timeout_reply(self, identifier):
        async with self._write_lock:
            if identifier not in self.pending or self.closed:
                return
            await self.inner.write(json.dumps(self._deny_frame(identifier)) + "\n")
            self.timeout_denials += 1
            self._settle(identifier)

    async def connect(self):
        try:
            await self.inner.connect()
            self.process = getattr(self.inner, "_process", None)
        except BaseException:
            self.process = getattr(self.inner, "_process", None)
            raise

    async def write(self, data):
        try:
            with anyio.fail_after(self.WRITE_TIMEOUT):
                await self._write(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise self._fail() from None

    async def _write(self, data):
        if self.broken or self.closed:
            raise self._fail()
        try:
            frames = [json.loads(line) for line in data.splitlines() if line.strip()]
            async with self._write_lock:
                for frame in frames:
                    if not isinstance(frame, dict):
                        raise self._fail()
                    request = frame.get("request", {})
                    if (
                        frame.get("type") == "control_request"
                        and request.get("subtype") == "initialize"
                    ):
                        matchers = (request.get("hooks") or {}).get("PreToolUse", [])
                        self.callbacks = {
                            identifier
                            for matcher in matchers
                            for identifier in matcher.get("hookCallbackIds", [])
                        }
                        self.all_callbacks = {
                            identifier: event
                            for event, entries in (request.get("hooks") or {}).items()
                            for entry in entries
                            for identifier in entry.get("hookCallbackIds", [])
                        }
                        if len(self.all_callbacks) > self.MAX_PENDING:
                            raise self._fail()
                    if frame.get("type") == "control_response":
                        response = frame.get("response")
                        if not isinstance(response, dict) or not isinstance(
                            response.get("request_id"), str
                        ):
                            raise self._fail()
                        identifier = response["request_id"]
                        if identifier in self.settled:
                            continue
                        if identifier in self.pending:
                            if response.get(
                                "subtype"
                            ) != "success" or not self._safe_response(
                                response.get("response")
                            ):
                                frame = self._deny_frame(identifier)
                                self.normalized_denials += 1
                            await self.inner.write(json.dumps(frame) + "\n")
                            self._settle(identifier)
                            continue
                        if identifier not in self.other_pending:
                            # A very late response may outlive the bounded settled
                            # cache. Unknown response IDs fail closed, never pass.
                            raise self._fail()
                        await self.inner.write(json.dumps(frame) + "\n")
                        self._settle(identifier)
                        continue
                    await self.inner.write(json.dumps(frame) + "\n")
        except asyncio.CancelledError:
            raise
        except Exception:
            raise self._fail() from None

    async def read_messages(self):
        try:
            async for frame in self.inner.read_messages():
                if not isinstance(frame, dict):
                    raise self._fail()
                kind = frame.get("type")
                if kind == "control_request":
                    identifier, request = frame.get("request_id"), frame.get("request")
                    if (
                        not isinstance(identifier, str)
                        or not identifier
                        or len(identifier) > 256
                        or not isinstance(request, dict)
                    ):
                        raise self._fail()
                    if (
                        identifier in self.pending
                        or identifier in self.other_pending
                        or identifier in self.settled
                        or len(self.pending) + len(self.other_pending)
                        >= self.MAX_PENDING
                    ):
                        raise self._fail()
                    if request.get("subtype") == "hook_callback":
                        data = request.get("input")
                        required = request.get("callback_id") in self.callbacks or (
                            isinstance(data, dict)
                            and data.get("hook_event_name") == "PreToolUse"
                        )
                        if required:
                            timer = asyncio.create_task(self._watch(identifier))
                            self._watchdogs.add(timer)
                            timer.add_done_callback(self._watchdogs.discard)
                            self.pending[identifier] = timer
                        elif (
                            not isinstance(data, dict)
                            or request.get("callback_id") not in self.all_callbacks
                            or data.get("hook_event_name")
                            != self.all_callbacks[request["callback_id"]]
                        ):
                            raise self._fail()
                    elif request.get("subtype") not in {"can_use_tool", "mcp_message"}:
                        raise self._fail()
                    if identifier not in self.pending:
                        self.other_pending.add(identifier)
                elif kind == "control_cancel_request":
                    identifier = frame.get("request_id")
                    if not isinstance(identifier, str):
                        raise self._fail()
                    if identifier in self.pending:
                        # CLI cancellation cannot establish readiness. Abort the
                        # owned CLI rather than allowing its timeout fallback.
                        self._settle(identifier)
                        raise self._fail()
                    if identifier in self.other_pending:
                        self._settle(identifier)
                yield frame
            if not self.closed:
                raise self._fail()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise self._fail() from None

    async def close(self):
        self.closed = True
        timers = list(self._watchdogs)
        for timer in timers:
            timer.cancel()
        with anyio.CancelScope(shield=True):
            if timers:
                await asyncio.gather(*timers, return_exceptions=True)
            self.pending.clear()
            self.settled.clear()
            self.callbacks.clear()
            self.all_callbacks.clear()
            self.other_pending.clear()
            # Pinned subprocess close bounds graceful/terminate/kill escalation.
            with anyio.fail_after(25):
                await self.inner.close()
        if self.process is not None and self.process.returncode is None:
            raise self._fail()

    async def end_input(self):
        await self.inner.end_input()

    def is_ready(self):
        return not self.broken and not self.closed and self.inner.is_ready()
