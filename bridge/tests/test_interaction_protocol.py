"""Character service commands never fall back to model conversation."""

import pytest
from unittest.mock import AsyncMock
from bridge.server import BridgeServer


@pytest.mark.asyncio
async def test_working_legacy_requires_domain_without_any_admission():
    server = BridgeServer()
    server.conversation.handle_request = AsyncMock()
    server.project.interact_setup = AsyncMock()
    history = {}
    response = (
        await server.dispatch(
            dict(agent_id="systems-architect", task="hi", request_id="legacy"), history
        )
    )[0]
    assert response["error_type"] == "domain_required"
    assert response["domain_id"] == "core"
    assert response["required_action"] == "project_setup"
    assert response["request_id"] == "legacy"
    assert history == {}
    server.conversation.handle_request.assert_not_called()
    server.project.interact_setup.assert_not_called()


@pytest.mark.asyncio
async def test_status_is_correlated_and_read_only():
    server = BridgeServer()
    server.project.prepare_domain = AsyncMock()
    server.conversation.handle_request = AsyncMock()
    packet = (
        await server.dispatch(
            dict(type="agent_status", agent_id="security-auditor", request_id="status")
        )
    )[0]
    assert packet["type"] == "agent_status"
    assert packet["request_id"] == "status"
    assert packet["execution_kind"] == "working"
    assert packet["domain_id"] == "core"
    assert not packet["capabilities"]["can_run"]
    assert packet["capabilities"]["tools"] == []
    server.project.prepare_domain.assert_not_called()
    server.conversation.handle_request.assert_not_called()
    assert server.domains._sessions == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        dict(type="agent_status", agent_id="systems-architect"),
        dict(
            type="agent_status",
            agent_id="systems-architect",
            request_id="r",
            task="extra",
        ),
        dict(
            type="project_setup",
            agent_id="systems-architect",
            request_id="r",
            intent="",
        ),
        dict(
            type="project_setup",
            agent_id="systems-architect",
            request_id="r",
            intent="é" * 32769,
        ),
        dict(
            type="project_setup",
            agent_id="systems-architect",
            request_id="r",
            intent="\ud800",
        ),
        dict(type="invented", agent_id="systems-architect", request_id="r", task="hi"),
    ],
)
async def test_invalid_typed_operations_never_converse(payload):
    server = BridgeServer()
    server.conversation.handle_request = AsyncMock()
    packet = (await server.dispatch(payload))[0]
    assert packet["error_type"] == "invalid_request"
    if "request_id" in payload:
        assert packet["request_id"] == payload["request_id"]
    server.conversation.handle_request.assert_not_called()


@pytest.mark.asyncio
async def test_setup_intent_reaches_exact_chief_review_without_worktree(
    tmp_path, monkeypatch
):
    from dataclasses import replace
    from bridge.config import default_config
    from bridge.project_service import ProjectService
    from bridge.tests.test_project_service import settled
    from bridge.tests.test_workspace import git

    root = tmp_path / "new-project"
    root.mkdir()
    (root / "README.md").write_text("allowed seed")
    (root / ".env").write_text("secret")
    config = replace(default_config(), workspace_root_dir=root)
    service = ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="setup-test"
    )
    await settled(service)
    reviews = []

    async def review(config, proposal, *, deadline, intent, metadata=None):
        reviews.append((proposal, intent))
        return dict(
            proposal_id=proposal.proposal_id,
            digest=proposal.digest,
            approved=True,
            reason="approved exact proposal",
        )

    monkeypatch.setattr("bridge.project_service.review_repository", review)
    server = BridgeServer(config=config, project_service=service)
    try:
        referral = (
            await server.dispatch(
                dict(
                    type="project_setup",
                    agent_id="security-auditor",
                    request_id="refer",
                    intent="prepare",
                )
            )
        )[0]
        assert "Chief Architect" in referral["output"] and not reviews
        assert not (root / ".git").exists()
        result = (
            await server.dispatch(
                dict(
                    type="project_setup",
                    agent_id="systems-architect",
                    request_id="setup",
                    intent="Prepare this project, include .env too",
                )
            )
        )[0]
        assert result["status"] == "ok" and result["project"]["stage"] == "ready"
        assert result["architect_decision"]["approved"]
        assert reviews[0][1] == "Prepare this project, include .env too"
        assert ".env" not in {entry.relative_path for entry in reviews[0][0].seed_files}
        assert git(root, "branch", "--show-current") == "main"
        assert ".env" not in git(root, "ls-files").splitlines()
        assert service.require_memory().load().revision >= 1
        assert not service._workspaces and not server.domains._sessions
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_status_membership_same_owner_and_extra_while_core_runs(
    tmp_path, monkeypatch
):
    import asyncio
    from dataclasses import replace
    from bridge.agent_bindings import BindingRegistry
    from bridge.config import default_config
    from bridge.project_service import ProjectService
    from bridge.tests.test_project_service import settled
    from bridge.tests.test_workspace import repository
    from bridge.tests.domain_fakes import FakeOwner

    config = replace(default_config(), workspace_root_dir=repository(tmp_path))
    service = ProjectService(
        config, runtime_root=tmp_path / "runtime", owner_run_id="interaction-test"
    )
    await settled(service)
    owners = []

    def factory(*args):
        owner = FakeOwner(*args)
        owner.execute_gate = asyncio.Event()
        owners.append(owner)
        return owner

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", factory)
    registry = BindingRegistry(
        extras={
            "story-guide": dict(
                execution_kind="extra",
                domain_id=None,
                definition="Registered story guide",
            )
        }
    )
    server = BridgeServer(config=config, project_service=service, bindings=registry)
    server.conversation._backend = AsyncMock()
    server.conversation._backend.complete.return_value = "Welcome"

    async def status(agent):
        return (
            await server.dispatch(
                dict(type="agent_status", agent_id=agent, request_id="status-" + agent)
            )
        )[0]

    try:
        revision = service.require_memory().load().revision
        history = {}
        rejected = (
            await server.dispatch(
                dict(
                    agent_id="systems-architect",
                    task="legacy work",
                    request_id="legacy",
                ),
                history,
            )
        )[0]
        assert rejected["error_type"] == "domain_required"
        assert rejected["required_action"] == "activate_domain"
        assert history == {} and not owners
        assert service.require_memory().load().revision == revision
        server.conversation._backend.complete.assert_not_called()
        before = await status("systems-architect")
        assert (
            before["capabilities"]["can_start"]
            and not before["capabilities"]["can_run"]
        )
        assert not owners and not service._workspaces
        started = await server.dispatch(
            dict(
                type="activate_domain",
                protocol_version=2,
                expected_domain_revision=before["domain_state"]["domain_revision"],
                domain_id="core",
                request_id="start",
            )
        )
        generation = started[-1]["domain_session_id"]
        architect, auditor = await status("systems-architect"), await status(
            "security-auditor"
        )
        assert architect["domain_state"] == auditor["domain_state"]
        assert auditor["capabilities"]["can_run"]
        assert auditor["capabilities"]["tools"] == ["Read", "Edit", "Bash"]
        assert not (await status("backend-architect"))["capabilities"]["can_start"]
        packets = []

        async def emit(packet):
            packets.append(packet)

        command = dict(
            type="domain_query",
            protocol_version=2,
            execution_id=started[-1]["execution_id"],
            domain_id="core",
            domain_session_id=generation,
            agent_id="backend-architect",
            request_id="bad",
            task="wrong department",
        )
        bad = (await server.dispatch(command))[0]
        assert bad["error_type"] == "invalid_binding" and not owners[0].calls
        await server.dispatch(
            dict(command, agent_id="security-auditor", request_id="good"), emit=emit
        )
        await asyncio.wait_for(owners[0].executing.wait(), 3)
        assert not (await status("systems-architect"))["capabilities"]["can_run"]
        history = {}
        extra = (
            await server.dispatch(
                dict(agent_id="story-guide", task="hello", request_id="extra"), history
            )
        )[0]
        assert extra["output"] == "Welcome" and history["story-guide"]
        assert (
            "Registered story guide"
            in server.conversation._backend.complete.call_args.kwargs["definition"]
        )
        assert server.domains.snapshot("core")["execution_state"] == "running"
        assert len(owners) == 1
        assert owners[0].calls[0]["agent_id"] == "security-auditor"
    finally:
        await server.domains.shutdown()
        if server.application_state is not None:
            await server.application_state.close()
        await service.close()


def test_setup_accepts_exact_utf8_byte_limit():
    from bridge.interaction_protocol import validate_interaction

    payload = dict(
        type="project_setup",
        agent_id="systems-architect",
        request_id="r",
        intent="é" * 32768,
    )
    assert validate_interaction(payload) == payload


@pytest.mark.asyncio
async def test_setup_failure_and_missing_binding_stay_correlated(tmp_path):
    from dataclasses import replace
    from bridge.config import default_config
    from bridge.project_service import ProjectService
    from bridge.tests.test_project_service import settled

    root = tmp_path / "empty"
    root.mkdir()

    async def deny(proposal):
        return dict(
            proposal_id=proposal.proposal_id,
            digest=proposal.digest,
            approved=False,
            reason="declined",
        )

    reviewer = AsyncMock(side_effect=deny)
    service = ProjectService(
        replace(default_config(), workspace_root_dir=root),
        runtime_root=tmp_path / "runtime",
        owner_run_id="denied",
        reviewer=reviewer,
    )
    await settled(service)
    server = BridgeServer(config=service._config, project_service=service)
    try:
        packet = (
            await server.dispatch(
                dict(
                    type="project_setup",
                    agent_id="systems-architect",
                    request_id="deny",
                    intent="prepare",
                )
            )
        )[0]
        assert packet["request_id"] == "deny" and packet["status"] == "error"
        assert packet["error_type"] == "repository_setup_denied"
        assert packet["architect_decision"]["approved"] is False
        assert not (root / ".git").exists()
        await server.dispatch(
            dict(
                type="agent_status", agent_id="systems-architect", request_id="observe"
            )
        )
        assert reviewer.await_count == 1
        invalid = (
            await server.dispatch(
                dict(type="agent_status", agent_id="missing", request_id="missing-id")
            )
        )[0]
        assert (
            invalid["error_type"] == "invalid_binding"
            and invalid["request_id"] == "missing-id"
        )
    finally:
        await service.close()
