"""Project composition uses real repositories and never initializes on discovery."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from bridge.config import default_config
from bridge.tests.test_workspace import repository


async def settled(service):
    await service.start()
    await service._bootstrap_task


@pytest.mark.asyncio
async def test_other_npc_refers_without_reviewer_or_tools(tmp_path):
    from bridge.project_service import ProjectService

    root = tmp_path / "project"
    root.mkdir()
    reviewer = AsyncMock()
    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="run",
        reviewer=reviewer,
    )
    await settled(service)
    assert service.snapshot()["stage"] == "needs_architect"
    assert "Chief Architect" in await service.interact_setup("builder", "request")
    assert reviewer.await_count == 0
    assert not (root / ".git").exists()
    assert (await service.refresh_snapshot())["stage"] == "needs_architect"
    await service.close()


@pytest.mark.asyncio
async def test_chief_submission_confirms_once_without_human_prompt(tmp_path):
    from bridge.project_service import ProjectService

    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("seed")
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def review(proposal):
        calls.append(proposal)
        entered.set()
        await release.wait()
        return dict(
            proposal_id=proposal.proposal_id,
            digest=proposal.digest,
            approved=True,
            reason="Approved seed",
        )

    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="run",
        reviewer=review,
    )
    await settled(service)
    first = asyncio.create_task(service.interact_setup("systems-architect", "first"))
    await entered.wait()
    assert (
        "review"
        in (await service.interact_setup("systems-architect", "second")).lower()
    )
    assert not (root / ".git").exists()
    release.set()
    await first
    assert len(calls) == 1
    assert service.snapshot()["stage"] == "ready"
    notes = service.require_memory().load()
    assert "Approved seed" in notes.progress
    assert service.require_workspace().initial_commit in notes.progress
    await service.close()


@pytest.mark.asyncio
async def test_existing_project_bootstraps_and_memory_revision_survives_failed_save(
    tmp_path,
):
    from bridge.project_service import ProjectService
    from bridge.project_memory import MemorySaveResult

    service = ProjectService(
        replace(default_config(), workspace_root_dir=repository(tmp_path)),
        runtime_root=tmp_path / "runtime",
        owner_run_id="run",
        reviewer=AsyncMock(),
    )
    await settled(service)
    assert service.snapshot()["stage"] == "ready"
    revision = service.snapshot()["memory"]["revision"]
    service.publish_memory(MemorySaveResult(False, None, "memory_unavailable"))
    assert service.snapshot()["memory"]["status"] == "unsaved"
    assert service.snapshot()["memory"]["revision"] == revision
    await service.close()


@pytest.mark.asyncio
async def test_setup_save_failure_preserves_repository_and_never_reinitializes(
    tmp_path, monkeypatch
):
    from bridge.project_service import ProjectService
    from bridge.project_memory import MemorySaveResult
    from bridge.tests.test_workspace import git

    root = tmp_path / "project"
    root.mkdir()
    calls = []

    async def review(proposal):
        calls.append(proposal)
        return dict(
            proposal_id=proposal.proposal_id,
            digest=proposal.digest,
            approved=True,
            reason="Approved",
        )

    monkeypatch.setattr(
        "bridge.project_memory.ProjectMemoryStore.checkpoint_setup",
        lambda *args: MemorySaveResult(False, None, "memory_unavailable"),
    )
    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="run",
        reviewer=review,
    )
    await settled(service)
    await service.interact_setup("systems-architect", "first")
    commit = git(root, "rev-parse", "HEAD")
    assert service.snapshot()["stage"] == "failed"
    assert service.snapshot()["memory"]["status"] == "unsaved"
    await service.interact_setup("systems-architect", "second")
    assert git(root, "rev-parse", "HEAD") == commit and len(calls) == 1
    await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["denied", "wrong_id", "extra_key", "not_boolean"])
async def test_invalid_chief_decisions_never_mutate_git(tmp_path, decision):
    from bridge.project_service import ProjectService

    root = tmp_path / "project"
    root.mkdir()

    async def review(proposal):
        payload = dict(
            proposal_id=proposal.proposal_id,
            digest=proposal.digest,
            approved=True,
            reason="decision",
        )
        if decision == "denied":
            payload["approved"] = False
        if decision == "wrong_id":
            payload["proposal_id"] = "other"
        if decision == "extra_key":
            payload["extra"] = 1
        if decision == "not_boolean":
            payload["approved"] = 1
        return payload

    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="run",
        reviewer=review,
    )
    await settled(service)
    await service.interact_setup("systems-architect", "first")
    assert service.snapshot()["stage"] == "failed"
    assert not (root / ".git").exists()
    await service.close()


@pytest.mark.asyncio
async def test_foreign_live_reservation_allows_bootstrap_memory_but_start_is_busy(
    tmp_path,
):
    from bridge.project_service import ProjectService
    from bridge.workspace import prepare_worktree, inspect_project
    from bridge.workspace_lease import WorkspaceLease
    from bridge.server import BridgeServer

    root = repository(tmp_path)
    workspace = prepare_worktree(
        inspect_project(root), runtime_root=tmp_path / "runtime"
    )
    lease = WorkspaceLease.acquire(
        workspace, domain_id="foreign", domain_session_id="foreign-generation"
    )
    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="run",
        reviewer=AsyncMock(),
    )
    try:
        await settled(service)
        assert service.snapshot()["stage"] == "ready"
        assert service.snapshot()["reservation"]["domain_id"] == "foreign"
        assert service.require_memory().load().revision >= 1
        server = BridgeServer(config=service._config, project_service=service)
        result = await server.dispatch(
            dict(type="activate_domain", domain_id="local", request_id="start")
        )
        assert result[-1]["error_type"] == "workspace_busy"
        await server._shutdown_domains()
    finally:
        lease.release(cleanup_confirmed=True)
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_late_preflight_never_calls_provider_and_settles_owned_intent(
    tmp_path, monkeypatch, cancel
):
    import threading
    from bridge.project_service import ProjectService
    from bridge.server import BridgeServer

    root = repository(tmp_path)
    config = replace(
        default_config(),
        workspace_root_dir=root,
        conversation_timeout_seconds=5 if cancel else 0.5,
    )
    service = ProjectService(
        config,
        runtime_root=tmp_path / "runtime",
        owner_run_id="run",
        reviewer=AsyncMock(),
    )
    await settled(service)
    server = BridgeServer(config=config, project_service=service)
    monkeypatch.setattr("bridge.server.load_agent", lambda _: "definition")
    server.conversation.handle_request = AsyncMock()
    memory = service.require_memory()
    begin = memory.begin_turn
    entered, release = threading.Event(), threading.Event()

    def delayed(turn):
        value = begin(turn)
        entered.set()
        release.wait(5)
        return value

    monkeypatch.setattr(memory, "begin_turn", delayed)
    operation = asyncio.create_task(
        server.dispatch(dict(agent_id="builder", task="work", request_id="request"))
    )
    while not entered.is_set():
        await asyncio.sleep(0.001)
    if cancel:
        operation.cancel()
        await asyncio.sleep(0)
        operation.cancel()
    else:
        await asyncio.sleep(0.6)
    assert not operation.done()
    assert server.conversation.handle_request.await_count == 0
    release.set()
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await operation
    else:
        assert (await operation)[0]["error_type"] == "timeout"
    notes = memory.load()
    assert "pending" not in notes.todo
    assert ("cancelled" if cancel else "error") in notes.todo
    assert server.conversation.handle_request.await_count == 0
    await service.close()
    assert not list((root / ".git/plaza/runs").glob("*.json"))


@pytest.mark.asyncio
async def test_preflight_memory_failure_prevents_provider_call(tmp_path, monkeypatch):
    from bridge.project_service import ProjectService
    from bridge.server import BridgeServer
    from bridge.project_memory import MemoryError

    config = replace(default_config(), workspace_root_dir=repository(tmp_path))
    service = ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="run"
    )
    await settled(service)
    server = BridgeServer(config=config, project_service=service)
    monkeypatch.setattr("bridge.server.load_agent", lambda _: "definition")
    server.conversation.handle_request = AsyncMock()
    service.require_readiness().prepare_turn = AsyncMock(
        side_effect=MemoryError("memory_unavailable", "unavailable")
    )
    result = await server.dispatch(
        dict(agent_id="builder", task="work", request_id="request")
    )
    assert result[0]["error_type"] == "memory_unavailable"
    server.conversation.handle_request.assert_not_awaited()
    await service.close()


@pytest.mark.asyncio
async def test_memory_save_failure_keeps_successful_history_and_unclean_run_evidence(
    tmp_path, monkeypatch
):
    from bridge.project_service import ProjectService
    from bridge.server import BridgeServer
    from bridge.project_memory import MemorySaveResult, MemoryError
    from bridge.conversation import ConversationEngine

    config = replace(default_config(), workspace_root_dir=repository(tmp_path))
    service = ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="run"
    )
    await settled(service)
    server = BridgeServer(config=config, project_service=service)
    monkeypatch.setattr("bridge.server.load_agent", lambda _: "definition")
    monkeypatch.setattr("bridge.conversation.load_agent", lambda _: "definition")
    backend = AsyncMock()
    backend.complete.return_value = "completed task"
    server.conversation = ConversationEngine(config=config, backend=backend)
    memory = service.require_memory()
    monkeypatch.setattr(
        memory,
        "finish_turn",
        lambda *args, **kwargs: MemorySaveResult(False, None, "memory_unavailable"),
    )
    histories = {}
    result = await server.dispatch(
        dict(agent_id="builder", task="work", request_id="request"), histories
    )
    assert result[0]["status"] == "ok" and result[0]["output"] == "completed task"
    assert histories["builder"][-1]["content"] == "completed task"
    assert backend.complete.await_count == 1
    assert (
        backend.complete.call_args.kwargs["timeout"]
        < config.conversation_timeout_seconds
    )
    assert service.snapshot()["memory"]["status"] == "unsaved"
    with pytest.raises(MemoryError):
        await service.close()
    assert list((config.workspace_root_dir / ".git/plaza/runs").glob("*.json"))
    # Dispose only this intentionally unclean test fixture's OS handles.
    for lock in memory._runs.values():
        lock.close()


def test_memory_publications_never_regress_last_confirmed_revision(tmp_path):
    from bridge.project_service import ProjectService
    from bridge.project_memory import MemorySaveResult

    service = ProjectService(
        default_config(), runtime_root=tmp_path, owner_run_id="run"
    )
    service.publish_memory(MemorySaveResult(True, 9, None))
    service.publish_memory(MemorySaveResult(True, 2, None))
    assert service.snapshot()["memory"]["revision"] == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["claude_code", "messages_api"])
async def test_actual_chief_reviewer_is_fresh_tools_disabled_exact_json(
    tmp_path, monkeypatch, backend
):
    import json
    from types import SimpleNamespace
    from bridge.project_service import review_repository
    from bridge.repository_setup import build_init_proposal
    from bridge.tests.test_conversation_backends import install_sdk, assistant, terminal
    from bridge import conversation_api

    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("seed")
    proposal = build_init_proposal(root)
    decision = dict(
        proposal_id=proposal.proposal_id,
        digest=proposal.digest,
        approved=True,
        reason="exact decision",
    )
    raw = json.dumps(decision)
    clients = install_sdk(monkeypatch, [assistant(raw), terminal(result=raw)])
    monkeypatch.setattr(
        "bridge.project_service.load_agent", lambda _: "Chief definition"
    )
    api = AsyncMock()
    api.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text=raw)]
    )
    manager = AsyncMock()
    manager.__aenter__.return_value = api
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(conversation_api, "AsyncAnthropic", lambda **kwargs: manager)
    config = replace(default_config(), conversation_backend=backend)
    assert await review_repository(config, proposal) == decision
    assert not (root / ".git").exists()
    if backend == "claude_code":
        options = clients[0].options
        assert options.tools == [] and options.allowed_tools == []
        assert options.model == config.model_for(config.conversation_tier)
        assert options.setting_sources == [] and options.skills == []
        sent = json.loads(clients[0].query.call_args.args[0].split("\n", 1)[1])[
            "messages"
        ]
    else:
        request = api.messages.create.call_args.kwargs
        assert "tools" not in request
        assert request["model"] == config.model_for(config.conversation_tier)
        sent = request["messages"]
    assert len(sent) == 1 and sent[0]["role"] == "user"
    reviewed = json.loads(sent[0]["content"])
    assert reviewed["root"] == str(root)
    assert reviewed["root_identity"] == list(proposal.root_identity)
    assert reviewed["seed_files"][0]["sha256"] == proposal.seed_files[0].sha256
    assert reviewed["digest"] == proposal.digest


@pytest.mark.asyncio
async def test_lone_surrogate_envelope_fallback_finishes_real_memory_turn(
    tmp_path, monkeypatch, offline_clients
):
    from bridge.project_service import ProjectService
    from bridge.server import BridgeServer

    config = replace(default_config(), workspace_root_dir=repository(tmp_path))
    service = ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="run"
    )
    await settled(service)
    server = BridgeServer(config=config, project_service=service)
    monkeypatch.setattr("bridge.server.load_agent", lambda _: "definition")
    raw = '{"answer":"\\ud800"}'
    offline_clients[0].reply.return_value = raw
    history = {}
    response = await server.dispatch(
        dict(agent_id="builder", task="work", request_id="request"), history
    )
    assert response[0]["status"] == "ok" and response[0]["output"] == raw
    assert history["builder"][-1]["content"] == raw
    notes = service.require_memory().load()
    assert "pending" not in notes.todo and "success" in notes.todo
    assert service.snapshot()["memory"]["status"] == "saved"
    await service.close()


def test_cleanup_publication_clears_only_matching_released_lease(tmp_path):
    from types import SimpleNamespace
    from bridge.project_service import ProjectService

    service = ProjectService(
        default_config(), runtime_root=tmp_path, owner_run_id="run"
    )
    first = SimpleNamespace(domain_id="first", domain_session_id="old", held=False)
    second = SimpleNamespace(domain_id="second", domain_session_id="new", held=True)
    service.publish_reservation(second)
    service.publish_cleanup(first, clean=True)
    assert service.snapshot()["reservation"]["domain_id"] == "second"
    service.publish_cleanup(second, clean=True)
    assert service.snapshot()["reservation"]["domain_id"] == "second"
    service.publish_cleanup(second, clean=False)
    assert service.snapshot()["reservation"]["cleanup_failed"]
    second.held = False
    service.publish_cleanup(second, clean=True)
    assert service.snapshot()["reservation"] is None


@pytest.mark.asyncio
async def test_chief_deadline_returns_approval_while_owned_initialization_drains(
    tmp_path, monkeypatch
):
    import threading
    from bridge import project_service as module

    root = tmp_path / "project"
    root.mkdir()
    config = replace(
        default_config(), workspace_root_dir=root, conversation_timeout_seconds=0.8
    )
    calls = []
    entered, release = threading.Event(), threading.Event()
    original = module.initialize_repository

    def initialize(proposal, approval):
        assert approval.approved
        calls.append("initialize")
        entered.set()
        release.wait(5)
        return original(proposal, approval)

    monkeypatch.setattr(module, "initialize_repository", initialize)

    async def review(proposal):
        calls.append("review")
        return dict(
            proposal_id=proposal.proposal_id,
            digest=proposal.digest,
            approved=True,
            reason="exact approved reason",
        )

    service = module.ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="run", reviewer=review
    )
    await settled(service)
    try:
        reply = await asyncio.wait_for(
            service.interact_setup("systems-architect", "first"), 1.5
        )
        assert entered.is_set()
        assert "initialization in progress" in reply.lower()
        assert service.snapshot()["architect_decision"]["digest"] in reply
        assert "exact approved reason" in reply
        assert service.snapshot()["stage"] == "initializing"
        assert service.snapshot()["memory"]["status"] == "unavailable"
        assert (
            "progress"
            in (await service.interact_setup("systems-architect", "second")).lower()
        )
        assert calls == ["review", "initialize"]
        closing = asyncio.create_task(service.close())
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        await asyncio.wait_for(closing, 5)
        assert service.snapshot()["stage"] == "ready"
        assert service.snapshot()["memory"]["status"] == "saved"
        assert "exact approved reason" in service.require_memory().load().progress
        assert calls == ["review", "initialize"]
    finally:
        release.set()
        await service.close()


@pytest.mark.asyncio
async def test_review_timeout_cannot_initialize_repository(tmp_path):
    from bridge.project_service import ProjectService

    root = tmp_path / "project"
    root.mkdir()

    async def slow_review(proposal):
        await asyncio.Future()

    service = ProjectService(
        replace(
            default_config(), workspace_root_dir=root, conversation_timeout_seconds=0.1
        ),
        runtime_root=tmp_path / "runtime",
        owner_run_id="run",
        reviewer=slow_review,
    )
    await settled(service)
    await service.interact_setup("systems-architect", "request")
    await service._setup_task
    assert service.snapshot()["reason"] == "timeout"
    assert not (root / ".git").exists()
    await service.close()


@pytest.mark.asyncio
async def test_late_synchronous_review_decision_never_authorizes_git(
    tmp_path, monkeypatch
):
    import time
    from bridge import project_service as module

    root = tmp_path / "project"
    root.mkdir()
    proposal = module.build_init_proposal(root)
    monkeypatch.setattr(module, "build_init_proposal", lambda _: proposal)

    async def late(proposal):
        time.sleep(0.15)
        return dict(
            proposal_id=proposal.proposal_id,
            digest=proposal.digest,
            approved=True,
            reason="too late",
        )

    service = module.ProjectService(
        replace(
            default_config(), workspace_root_dir=root, conversation_timeout_seconds=0.1
        ),
        runtime_root=tmp_path / "runtime",
        owner_run_id="run",
        reviewer=late,
    )
    await settled(service)
    await service.interact_setup("systems-architect", "request")
    await service._setup_task
    assert service.snapshot()["reason"] == "timeout"
    assert service.snapshot()["architect_decision"] is None
    assert not (root / ".git").exists()
    await service.close()
