"""Correlated, best-effort bridge archives and structured standard diagnostics.

Only this facade's metadata reaches its private logger. Message bodies go directly
into transcripts, independently of diagnostic filtering. The storage writer owns
run identity, UTC timestamps, sequence numbers, bounds, and retries.
"""

from dataclasses import dataclass, fields
import json
import logging
import math
import re
import threading
from typing import Literal

from bridge.config import BridgeConfig
from bridge.log_storage import RunLogWriter


@dataclass(frozen=True)
class RequestContext:
    """Originating request identity; never contains a task or provider options."""

    connection_id: str | None
    request_id: str
    agent_id: str | None
    engine: str
    model: str | None
    domain_id: str | None = None


class _MetadataOnly(logging.Filter):
    def __init__(self, token: object):
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "_bridge_token", None) is self._token


class _EventArchive(logging.Handler):
    """Adapt trusted standard log records to the bounded event stream."""

    def __init__(self, recorder: "BridgeRecorder"):
        super().__init__()
        self._recorder = recorder

    def emit(self, record: logging.LogRecord) -> None:
        record._bridge_captured = self._recorder._append(
            "event", record._bridge_metadata
        )


class BridgeRecorder:
    """Public calls return true only for disk captures; storage errors are isolated.

    Ordinary lifecycle events are INFO. Routing details are DEBUG; names ending
    in ``_warning``, ``_cancelled`` or ``_rejected`` are WARNING; ``_failed`` and
    ``_error`` are ERROR. Failure/error and cancelled outcomes also select those
    severities. Event names are machine tokens, never exception descriptions.
    """

    def __init__(
        self,
        config: BridgeConfig,
        project_label: str,
        *,
        writer: RunLogWriter | None = None,
        redactions: tuple[str, ...] = (),
    ):
        self.config = config
        self._redactions = tuple(
            sorted({s for s in redactions if s}, key=len, reverse=True)
        )
        self._project_label = self._redact(project_label)
        self._writer = writer
        self._closed = False
        self._suspended = False
        self._mutex = threading.RLock()
        self._local = threading.local()
        self._token = object()
        # A standalone logger avoids global registration/level changes and the
        # registry retaining one logger per run. No provider or root propagation.
        self._logger = logging.Logger(
            "bridge.observability", getattr(logging, config.log_level)
        )
        self._logger.propagate = False
        self._stderr = logging.StreamHandler()
        self._stderr.setFormatter(logging.Formatter("%(levelname)s bridge %(message)s"))
        self._stderr.addFilter(_MetadataOnly(self._token))
        self._archive = _EventArchive(self)
        self._archive.addFilter(_MetadataOnly(self._token))
        self._logger.addHandler(self._stderr)
        self._logger.addHandler(self._archive)
        with self._mutex:
            self._local.active = True
            try:
                self._ensure_writer()
            except Exception:
                self._failed()
            finally:
                self._local.active = False

    def _redact(self, value: str) -> str:
        for secret in self._redactions:
            value = value.replace(secret, "[REDACTED]")
        return value

    def _record(
        self, context: RequestContext | None, **values: object
    ) -> dict[str, object]:
        if context is not None:
            values.update(
                {
                    field.name: getattr(context, field.name)
                    for field in fields(RequestContext)
                }
            )
        return {
            key: self._redact(value) if isinstance(value, str) else value
            for key, value in values.items()
            if value is not None
        }

    def _log_record(self, level: int, metadata: dict[str, object]) -> logging.LogRecord:
        record = self._logger.makeRecord(
            self._logger.name,
            level,
            __file__,
            0,
            json.dumps(metadata, ensure_ascii=True, allow_nan=False),
            (),
            None,
        )
        record._bridge_token = self._token
        record._bridge_metadata = metadata
        record._bridge_captured = False
        return record

    def _diagnostic(self, message: str) -> None:
        # Bypass the disk handler, so failures cannot trigger recursive writes.
        try:
            self._stderr.handle(self._log_record(logging.WARNING, {"event": message}))
        except Exception:
            pass  # an unavailable stderr must not break conversation execution

    def _failed(self) -> None:
        if not self._suspended:
            self._suspended = True
            self._diagnostic("recording suspended")

    def _ensure_writer(self) -> RunLogWriter:
        if self._writer is None:
            self._writer = RunLogWriter(self.config, self._project_label)
        return self._writer

    def _append(
        self,
        kind: Literal["event", "transcript"],
        record: dict[str, object],
        *,
        agent_id: str | None = None,
    ) -> bool:
        try:
            captured = self._ensure_writer().append(kind, record, agent_id=agent_id)
        except Exception:
            self._failed()
            return False
        if not captured:
            self._failed()
            return False
        if self._suspended:
            self._suspended = False
            self._diagnostic("recording recovered")
        return True

    @staticmethod
    def _event_level(name: str, outcome: str | None) -> int:
        if name.endswith(("_failed", "_error")) or outcome in ("failure", "error"):
            return logging.ERROR
        if (
            name.endswith(("_warning", "_cancelled", "_rejected"))
            or outcome == "cancelled"
        ):
            return logging.WARNING
        if name in ("engine_routing", "engine_routed", "request_routed"):
            return logging.DEBUG
        return logging.INFO

    def event(
        self,
        name: str,
        context: RequestContext | None = None,
        *,
        outcome: str | None = None,
        duration_ms: float | None = None,
        domain_state: str | None = None,
    ) -> bool:
        if getattr(self._local, "active", False):
            return False
        with self._mutex:
            if self._closed:
                return False
            self._local.active = True
            try:
                if (
                    not isinstance(name, str)
                    or re.fullmatch(r"[a-z][a-z0-9_.-]*", name) is None
                ):
                    raise ValueError("event name must be a machine token")
                level = self._event_level(name, outcome)
                if not self._logger.isEnabledFor(level):
                    return False
                if duration_ms is not None and (
                    type(duration_ms) not in (int, float)
                    or not math.isfinite(duration_ms)
                    or duration_ms < 0
                ):
                    raise ValueError("duration must be finite and nonnegative")
                metadata = self._record(
                    context,
                    event=name,
                    outcome=outcome,
                    duration_ms=duration_ms,
                    domain_state=domain_state,
                )
                record = self._log_record(level, metadata)
                self._logger.handle(record)
                return record._bridge_captured
            except Exception:
                self._failed()
                return False
            finally:
                self._local.active = False

    def message(
        self,
        context: RequestContext,
        role: Literal["user", "assistant", "error"],
        content: str,
        outcome: str,
        *,
        output_id: str | None = None,
        provider_session_id: str | None = None,
    ) -> bool:
        if getattr(self._local, "active", False):
            return False
        with self._mutex:
            if self._closed or not self.config.transcripts_enabled:
                return False
            self._local.active = True
            try:
                if role not in ("user", "assistant", "error") or not isinstance(
                    content, str
                ):
                    raise ValueError("invalid transcript message")
                record = self._record(
                    context,
                    role=role,
                    content=content,
                    outcome=outcome,
                    output_id=output_id,
                    provider_session_id=provider_session_id,
                )
                return self._append("transcript", record, agent_id=context.agent_id)
            except Exception:
                self._failed()
                return False
            finally:
                self._local.active = False

    def close(self, *, clean: bool = True) -> None:
        if getattr(self._local, "active", False):
            return
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            self._local.active = True
            try:
                if self._writer is not None:
                    self._writer.close(clean=clean)
            except Exception:
                self._failed()
            finally:
                self._local.active = False
                for handler in (self._archive, self._stderr):
                    self._logger.removeHandler(handler)
                    handler.close()
