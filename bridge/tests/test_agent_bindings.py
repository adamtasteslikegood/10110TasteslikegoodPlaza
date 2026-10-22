"""Canonical bindings remain usable without the source submodule."""

import json
from pathlib import Path

import pytest

from bridge import agents

ROOT = Path(__file__).resolve().parents[2]


def bindings():
    from bridge import agent_bindings

    return agent_bindings


def test_core_representatives():
    module = bindings()
    for agent in ("systems-architect", "security-auditor"):
        binding = module.resolve_binding(agent)
        assert (binding.execution_kind, binding.domain_id) == ("working", "core")
        assert module.require_working_binding(agent, "core") == binding


def test_catalog_metadata_and_curated_definitions():
    module = bindings()
    catalog = json.loads((ROOT / "data/agents.json").read_text())
    metadata = json.loads((ROOT / "bridge/agent_bindings.json").read_text())
    assert set(catalog) == set(metadata)
    for agent, entry in catalog.items():
        assert module.resolve_binding(agent).domain_id == entry["dept"]
        assert agents.load_agent(agent)
        source = ROOT / entry["source"]
        if source.exists():
            assert agents.load_agent(agent) == source.read_text()


def test_invalid_membership_and_unknown_agent():
    module = bindings()
    for agent, domain in [
        ("systems-architect", "engineering"),
        ("missing", "core"),
        ("systems-architect", "unknown"),
    ]:
        with pytest.raises(ValueError, match="invalid_binding"):
            module.require_working_binding(agent, domain)


def test_explicit_extra_fixture_and_collision():
    module = bindings()
    registry = module.BindingRegistry(
        extras={
            "test-guide": {
                "execution_kind": "extra",
                "domain_id": None,
                "definition": "Fixture guide.",
            }
        }
    )
    assert registry.resolve_binding("test-guide").domain_id is None
    assert registry.load_extra("test-guide") == "Fixture guide."
    with pytest.raises(ValueError, match="invalid_binding"):
        registry.require_working_binding("test-guide", "core")
    for entry in (
        {"execution_kind": "extra", "domain_id": "core", "definition": "x"},
        {"execution_kind": "working", "domain_id": "unknown", "definition": "x"},
    ):
        with pytest.raises(ValueError, match="invalid_binding"):
            module.BindingRegistry(extras={"test-guide": entry})
    with pytest.raises(ValueError, match="invalid_binding"):
        module.BindingRegistry(
            extras={
                "systems-architect": {
                    "execution_kind": "extra",
                    "domain_id": None,
                    "definition": "x",
                }
            }
        )


def test_runtime_uses_only_committed_store(tmp_path, monkeypatch):
    module = bindings()
    monkeypatch.chdir(tmp_path)
    assert module.resolve_binding("systems-architect").domain_id == "core"


def test_malformed_metadata_never_defaults_to_working():
    module = bindings()
    metadata = json.loads(module.METADATA.read_text())
    for entry in (
        {},
        {"execution_kind": "extra", "domain_id": None},
        {"execution_kind": "working", "domain_id": "unknown"},
    ):
        broken = dict(metadata, **{"systems-architect": entry})
        with pytest.raises(ValueError, match="invalid_binding"):
            module.BindingRegistry(metadata=broken)


def test_sync_check_detects_definition_and_binding_drift(tmp_path, monkeypatch):
    from bridge.sync import synchronize
    from scripts import generate_agents_json as generator

    # The generator's canonical-submodule check covers catalog selection. Here
    # exercise synchronization against real files without requiring that checkout.
    source_root = tmp_path / "sources"
    source_root.mkdir()
    catalog = {
        "fixture-architect": {"dept": "core", "source": "architect.md"},
        "fixture-support": {"dept": "operations", "source": "selected.md"},
    }
    (source_root / "architect.md").write_text("Architect definition.")
    (source_root / "selected.md").write_text("Selected support definition.")
    (source_root / "unselected.md").write_text("Wrong collision winner.")
    monkeypatch.setattr(generator, "REPO_ROOT", source_root)
    store, metadata = tmp_path / "agents", tmp_path / "bindings.json"
    assert synchronize(catalog, dest=store, metadata=metadata)
    for agent, entry in catalog.items():
        assert (store / f"{agent}.md").read_text() == (
            source_root / entry["source"]
        ).read_text()
    assert json.loads(metadata.read_text()) == {
        agent: {"execution_kind": "working", "domain_id": entry["dept"]}
        for agent, entry in catalog.items()
    }
    assert synchronize(catalog, dest=store, metadata=metadata, check=True)
    definition = store / "fixture-support.md"
    definition.write_text("Wrong collision winner.")
    assert not synchronize(catalog, dest=store, metadata=metadata, check=True)
    assert definition.read_text() == "Wrong collision winner."
    assert synchronize(catalog, dest=store, metadata=metadata)
    assert definition.read_text() == "Selected support definition."
    metadata.write_text("{}")
    assert not synchronize(catalog, dest=store, metadata=metadata, check=True)
    assert metadata.read_text() == "{}"
    assert synchronize(catalog, dest=store, metadata=metadata)
    stale = store / "removed-agent.md"
    stale.write_text("Stale definition.")
    assert not synchronize(catalog, dest=store, metadata=metadata, check=True)
    assert stale.is_file()
    assert synchronize(catalog, dest=store, metadata=metadata)
    assert not stale.exists()
    assert synchronize(catalog, dest=store, metadata=metadata, check=True)


def test_runtime_with_submodule_absent(tmp_path):
    import shutil
    import subprocess
    import sys

    shutil.copytree(
        ROOT / "bridge",
        tmp_path / "bridge",
        ignore=shutil.ignore_patterns("__pycache__", "tests"),
    )
    shutil.copytree(ROOT / "data", tmp_path / "data")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from bridge.agent_bindings import resolve_binding; "
            "from bridge.agents import load_agent; "
            "assert resolve_binding('systems-architect').domain_id == 'core'; "
            "assert load_agent('support-ticket-handler')",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
