"""Strict runner-only scene receipts, shared by deterministic and future live gates.

This module performs no provider work and implements no live runner. A stage is
an observation, never authority to run a product command. The supervisor must
also corroborate its IDs/content with bridge and filesystem observations.
"""

from datetime import datetime, timezone
import math
import re
import time

STAGES = (
    "referral_rendered",
    "chief_ready",
    "domain_running",
    "background_ack",
    "npc_rendered",
    "domain_rendered",
    "stop_ack",
)
IDENTITY = {"project_id", "workspace_id"}
DOMAIN = IDENTITY | {"domain_id", "domain_session_id"}
FIELDS = {
    "referral_rendered": {"request_id", "agent_id", "assistant"},
    "chief_ready": {"project_id", "request_id", "assistant"},
    "domain_running": DOMAIN | {"request_id", "agent_id"},
    "background_ack": DOMAIN
    | {"request_id", "state", "execution_state", "radius", "distance", "panel_hidden"},
    "npc_rendered": DOMAIN | {"request_id", "agent_id", "assistant", "execution_state"},
    "domain_rendered": DOMAIN
    | {
        "request_id",
        "refocus_request_id",
        "output_id",
        "output",
        "status",
        "rendered_text",
        "rendered_unique_results",
    },
    "stop_ack": DOMAIN | {"request_id", "state"},
}


def _text(value):
    return (
        isinstance(value, str) and bool(value.strip()) and len(value.encode()) <= 65536
    )


class StageError(ValueError):
    pass


class StageValidator:
    def __init__(self, run_id, producer, scenario="a_initial"):
        if not all(_text(v) for v in (run_id, producer)) or scenario not in (
            "a_initial",
            "a_restart",
            "b_isolation",
        ):
            raise StageError("invalid stage binding")
        self.run_id, self.producer, self.scenario = run_id, producer, scenario
        self.receipts = []
        self.binding = {}
        self.request_ids = set()

    def accept(self, record):
        expected = {
            "schema_version",
            "run_id",
            "scenario",
            "producer",
            "seq",
            "stage",
            "payload",
        }
        index = len(self.receipts)
        if not isinstance(record, dict) or set(record) != expected:
            raise StageError("invalid envelope")
        if (
            type(record["schema_version"]) is not int
            or record["schema_version"] != 1
            or type(record["seq"]) is not int
            or record["seq"] != index + 1
            or record["run_id"] != self.run_id
            or record["producer"] != self.producer
            or record["scenario"] != self.scenario
            or index >= len(STAGES)
            or record["stage"] != STAGES[index]
        ):
            raise StageError("stale, foreign or out-of-order stage")
        stage, payload = record["stage"], record["payload"]
        if not isinstance(payload, dict) or set(payload) != FIELDS[stage]:
            raise StageError("invalid payload fields")
        for key, value in payload.items():
            if key in ("radius", "distance"):
                if (
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    raise StageError("invalid physical observation")
            elif key == "panel_hidden":
                if value is not True:
                    raise StageError("panel must be hidden")
            elif key == "rendered_unique_results":
                if type(value) is not int or value != 1:
                    raise StageError("duplicate rendered result")
            elif not _text(value):
                raise StageError("invalid text")
            if key.endswith("_id") and len(value.encode()) > 128:
                raise StageError("invalid identifier")
        if (
            "domain_id" in payload
            and re.fullmatch(r"[A-Za-z0-9_-]+", payload["domain_id"]) is None
        ):
            raise StageError("invalid domain")
        for key in DOMAIN & payload.keys():
            if key in self.binding and self.binding[key] != payload[key]:
                raise StageError("identity/generation mismatch")
        if payload["request_id"] in self.request_ids:
            raise StageError("duplicate command identity")
        if stage == "background_ack" and (
            payload["state"] != "background"
            or payload["execution_state"] != "running"
            or payload["distance"] <= payload["radius"]
        ):
            raise StageError("background not observed outside anchor")
        if stage == "npc_rendered" and payload["execution_state"] != "running":
            raise StageError("domain must remain pending during NPC chat")
        if stage == "domain_rendered" and (
            payload["status"] != "success"
            or re.fullmatch(r"[0-9]+", payload["output_id"]) is None
            or int(payload["output_id"]) < 1
            or payload["output"] not in payload["rendered_text"]
            or payload["domain_session_id"] not in payload["rendered_text"]
            or payload["output_id"] not in payload["rendered_text"]
        ):
            raise StageError("terminal not rendered")
        if stage == "stop_ack" and payload["state"] != "inactive":
            raise StageError("Stop not confirmed")
        self.binding.update({k: payload[k] for k in DOMAIN & payload.keys()})
        self.request_ids.add(payload["request_id"])
        receipt = {
            **record,
            "payload": dict(payload),
            "receipt_seq": index + 1,
            "received_monotonic": time.monotonic(),
            "received_utc": datetime.now(timezone.utc).isoformat(),
        }
        self.receipts.append(receipt)
        return receipt

    @property
    def may_release(self):
        return len(self.receipts) == 5

    def finish(self):
        if len(self.receipts) != len(STAGES):
            raise StageError("missing required stage")
        return self.receipts
