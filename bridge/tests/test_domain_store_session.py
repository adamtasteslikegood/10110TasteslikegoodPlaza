"""Execution/replay behavior across the extracted real store boundary."""

import json

import pytest

from bridge.config import default_config
from bridge.domain_session import DomainSession
from bridge.domain_store import MemoryStore
from bridge.tests.domain_fakes import collect_until, context, query
from bridge.tests.test_domain_session import setup  # noqa: F401


@pytest.mark.asyncio
async def test_injected_store_retains_delivered_terminal_and_duplicate_identity(setup):
    _, service, owners = setup
    store = MemoryStore()
    session = DomainSession(
        "engineering",
        "generation",
        config=default_config(),
        project_service=service,
        store=store,
    )
    packets = []

    async def emit(packet):
        packets.append(packet)

    try:
        await session.start()
        await session.admit_query(query(), context=context(), emit=emit)
        await collect_until(session, packets)
        terminal = packets[-1]
        assert terminal["type"] == "domain_result"
        assert terminal["output"] == "done" and terminal["output_id"] == "1"
        assert terminal["memory"]["saved"] is True
        # Match the pre-extraction wire field order as well as packet values.
        expected = dict(
            type="domain_result",
            project_id=service.workspace.project_id,
            workspace_id=service.workspace.workspace_id,
            domain_id="engineering",
            domain_session_id="generation",
            request_id="run",
            agent_id="backend-architect",
            task="Build something",
            output="done",
            output_id="1",
            status="success",
            reason="completed",
            truncated=False,
            memory=terminal["memory"],
        )
        assert json.dumps(terminal) == json.dumps(expected)
        assert store.find_request(terminal["request_id"]) == terminal
        assert store.replay(0).entries == [terminal]
        replayed = session.replay(0)
        assert replayed[0] == terminal
        assert replayed[-1] == dict(
            session.snapshot(),
            type="resume_complete",
            high_water_mark="1",
            earliest_output_id="1",
            history_gap=False,
        )
        await session.admit_query(query(), context=context(), emit=emit)
        assert packets[-1] == terminal and len(owners[0].calls) == 1
        await session.admit_query(query(task="conflict"), context=context(), emit=emit)
        assert packets[-1]["error_type"] == "invalid_request"
        assert len(owners[0].calls) == 1
    finally:
        await session.stop()


@pytest.mark.asyncio
async def test_default_session_stores_do_not_share_history_or_sequence(setup):
    first, service, owners = setup
    second = DomainSession(
        "engineering",
        "next-generation",
        config=default_config(),
        project_service=service,
    )
    packets = []

    async def emit(packet):
        packets.append(packet)

    await first.start()
    await first.admit_query(query(), context=context(), emit=emit)
    await collect_until(first, packets)
    assert second.replay(0)[-1]["high_water_mark"] == "0"
    assert len(second.replay(0)) == 1
    await first.stop()
    try:
        await second.start()
        command = dict(query(), domain_session_id="next-generation")
        await second.admit_query(command, context=context(), emit=emit)
        await collect_until(second, packets, 2)
        assert len(owners) == 2 and len(owners[1].calls) == 1
        assert packets[-1]["output_id"] == "1"
        assert packets[-1]["domain_session_id"] == "next-generation"
        assert len(first.replay(0)) == 2
        assert first.replay(0)[0]["domain_session_id"] == "generation"
    finally:
        await second.stop()
