"""Validated, committed character bindings; no runtime submodule dependency."""

from dataclasses import dataclass
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
METADATA = ROOT / "agent_bindings.json"
EXTRAS = ROOT / "extras.json"
DOMAIN_IDS = frozenset(
    {
        "account-customer-success",
        "ai-automation",
        "core",
        "design",
        "engineering",
        "leadership",
        "marketing",
        "operations",
        "product",
        "research",
    }
)
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]*\Z")


@dataclass(frozen=True)
class AgentBinding:
    agent_id: str
    execution_kind: str
    domain_id: str | None


class InvalidBinding(ValueError):
    code = "invalid_binding"

    def __init__(self):
        super().__init__(self.code)


class BindingRegistry:
    """An explicit extra mapping may be injected by callers, including fixtures."""

    def __init__(self, *, metadata=None, extras=None, catalog=None):
        try:
            if catalog is None:
                catalog = json.loads((ROOT.parent / "data/agents.json").read_text())
            metadata = (
                json.loads(METADATA.read_text()) if metadata is None else metadata
            )
            extras = json.loads(EXTRAS.read_text()) if extras is None else extras
            if not isinstance(metadata, dict) or set(metadata) != set(catalog):
                raise InvalidBinding()
            if not isinstance(extras, dict) or set(extras) & set(catalog):
                raise InvalidBinding()
            self.bindings = {}
            self.extras = {}
            for agent, entry in metadata.items():
                if (
                    not _ID.fullmatch(agent)
                    or not isinstance(entry, dict)
                    or entry.get("domain_id") not in DOMAIN_IDS
                    or entry
                    != {
                        "execution_kind": "working",
                        "domain_id": catalog[agent]["dept"],
                    }
                ):
                    raise InvalidBinding()
                self.bindings[agent] = AgentBinding(
                    agent, "working", entry["domain_id"]
                )
            for agent, entry in extras.items():
                if (
                    not isinstance(agent, str)
                    or not _ID.fullmatch(agent)
                    or not isinstance(entry, dict)
                    or set(entry) != {"execution_kind", "domain_id", "definition"}
                    or entry["execution_kind"] != "extra"
                    or entry["domain_id"] is not None
                    or not isinstance(entry["definition"], str)
                    or not entry["definition"].strip()
                ):
                    raise InvalidBinding()
                self.bindings[agent] = AgentBinding(agent, "extra", None)
                self.extras[agent] = entry["definition"]
        except (OSError, TypeError, KeyError, json.JSONDecodeError):
            raise InvalidBinding() from None

    def resolve_binding(self, agent_id):
        if not isinstance(agent_id, str) or agent_id not in self.bindings:
            raise InvalidBinding()
        return self.bindings[agent_id]

    def require_working_binding(self, agent_id, domain_id):
        binding = self.resolve_binding(agent_id)
        if binding.execution_kind != "working" or binding.domain_id != domain_id:
            raise InvalidBinding()
        return binding

    def load_extra(self, agent_id):
        return self.extras.get(agent_id)


def resolve_binding(agent_id: str) -> AgentBinding:
    return BindingRegistry().resolve_binding(agent_id)


def require_working_binding(agent_id: str, domain_id: str) -> AgentBinding:
    return BindingRegistry().require_working_binding(agent_id, domain_id)
