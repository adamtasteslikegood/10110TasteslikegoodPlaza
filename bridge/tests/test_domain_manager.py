"""Public command boundary: startup visibility, generation fencing and caps."""

import asyncio
import pytest

from bridge.agent_bindings import DOMAIN_IDS
import pytest_asyncio
from bridge.config import default_config
from bridge.domain_manager import DomainManager
from bridge.tests.domain_fakes import FakeProjectService, FakeOwner, context


@pytest_asyncio.fixture
async def setup(tmp_path, monkeypatch):
    service = FakeProjectService(tmp_path)
    owners = []

    def factory(*args):
        owner = FakeOwner(*args)
        owners.append(owner)
        return owner

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", factory, raising=False)
    manager = DomainManager(default_config(), service)
    yield manager, service, owners
    await manager.shutdown()
    service.close()


async def command(manager, type, **kwargs):
    packets = []

    async def emit(packet):
        packets.append(packet)

    await manager.handle(
        dict(type=type, request_id="request", domain_id="engineering", **kwargs),
        context=context(),
        emit=emit,
    )
    return packets


@pytest.mark.asyncio
async def test_activation_exposes_generation_before_connect(setup, monkeypatch):
    manager, service, owners = setup
    original = FakeOwner.start

    async def blocked(owner):
        owner.connect_gate = asyncio.Event()
        await original(owner)

    monkeypatch.setattr(FakeOwner, "start", blocked)
    packets, observed = [], asyncio.Event()

    async def emit(packet):
        packets.append(packet)
        observed.set()

    start = asyncio.create_task(
        manager.handle(
            dict(type="activate_domain", domain_id="engineering", request_id="start"),
            context=context("start"),
            emit=emit,
        )
    )
    await observed.wait()
    await owners[0].started.wait()
    assert packets[0]["state"] == "activating" and service.reservation.held
    generation = packets[0]["domain_session_id"]
    repeated = await command(manager, "activate_domain")
    assert repeated[0]["domain_session_id"] == generation and len(owners) == 1
    stopped = await command(manager, "deactivate_domain", domain_session_id=generation)
    await start
    assert stopped[-1]["state"] == "inactive"
    assert not any(p.get("state") == "active" for p in packets)


@pytest.mark.asyncio
async def test_stale_generation_cannot_mutate(setup):
    manager, _, _ = setup
    first = (await command(manager, "activate_domain"))[-1]["domain_session_id"]
    await command(manager, "deactivate_domain", domain_session_id=first)
    second = (await command(manager, "activate_domain"))[-1]["domain_session_id"]
    assert first != second
    for action in (
        "background_domain",
        "refocus_domain",
        "deactivate_domain",
        "domain_query",
    ):
        extra = (
            dict(agent_id="backend-architect", task="task")
            if action == "domain_query"
            else {}
        )
        reply = await command(manager, action, domain_session_id=first, **extra)
        assert reply[-1]["error_type"] == "session_unavailable"
    assert (await command(manager, "domain_status"))[-1]["state"] == "active"
    assert (await command(manager, "resume", domain_session_id=first, cursor="0"))[-1][
        "type"
    ] == "resume_complete"


@pytest.mark.asyncio
async def test_three_generations_evict_only_clean_oldest(setup):
    manager, _, _ = setup
    generations = []
    for _ in range(3):
        generation = (await command(manager, "activate_domain"))[-1][
            "domain_session_id"
        ]
        generations.append(generation)
        await command(manager, "deactivate_domain", domain_session_id=generation)
    status = (await command(manager, "domain_status"))[-1]
    assert status["available_generations"] == generations[1:]
    assert (
        await command(manager, "resume", domain_session_id=generations[0], cursor="0")
    )[-1]["error_type"] == "session_unavailable"


@pytest.mark.asyncio
async def test_discovery_and_invalid_correlation_are_safe(setup):
    manager, service, owners = setup
    packets = []

    async def emit(packet):
        packets.append(packet)

    await manager.handle(
        dict(type="describe_workspace", request_id="inspect"),
        context=context(),
        emit=emit,
    )
    assert packets[-1]["request_id"] == "inspect" and not owners
    await manager.handle(
        dict(type="activate_domain", domain_id=[]), context=context(), emit=emit
    )
    assert packets[-1]["error_type"] == "invalid_request"
    assert "request_id" not in packets[-1] and "domain_id" not in packets[-1]
    assert "request_id" not in service.snapshot()


@pytest.mark.asyncio
async def test_ten_domain_ids_and_idle_reservation(setup):
    manager, service, _ = setup
    for i in range(11):
        packets = []

        async def emit(packet):
            packets.append(packet)

        await manager.handle(
            dict(
                type="activate_domain",
                request_id=str(i),
                domain_id=(sorted(DOMAIN_IDS) + ["engineering"])[i],
            ),
            context=context(),
            emit=emit,
        )
        if i == 0:
            assert packets[-1]["state"] == "active"
        else:
            assert packets[-1]["error_type"] == "capacity_limit"
    assert service.reservation.held
    # Failed clean generations can be evicted; a held generation never is.
    assert len(manager._sessions) <= 10


@pytest.mark.asyncio
async def test_cancelled_start_caller_during_reservation_keeps_owned_startup(
    setup, monkeypatch
):
    manager, service, owners = setup
    entered, release = asyncio.Event(), asyncio.Event()
    from bridge.domain_session import DomainSession

    original = DomainSession._reserve

    async def reserve(session):
        entered.set()
        await release.wait()
        await original(session)

    monkeypatch.setattr(DomainSession, "_reserve", reserve)
    task = asyncio.create_task(command(manager, "activate_domain"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    try:
        session = manager._sessions["engineering"][-1]
        # Join the continuation registered before cancellation, including real
        # Git/lease IO. This is a finite hang guard, not a product timing cap.
        packet = await asyncio.wait_for(asyncio.shield(session._startup), 5)
        assert packet["state"] == "active"
        assert owners[0].started.is_set() and service.reservation.held
    finally:
        await manager.shutdown()
    assert owners[0].started.is_set()


@pytest.mark.asyncio
async def test_activation_failure_carries_new_generation_and_releases(
    setup, monkeypatch
):
    manager, service, _ = setup

    async def fail(owner):
        raise RuntimeError("private startup detail")

    monkeypatch.setattr(FakeOwner, "start", fail)
    replies = await command(manager, "activate_domain")
    assert replies[0]["state"] == "activating"
    assert replies[-1]["error_type"] == "sdk_error"
    assert replies[-1]["domain_session_id"] == replies[0]["domain_session_id"]
    assert service.reservation is None
    assert "private" not in str(replies)


@pytest.mark.asyncio
async def test_start_cleanup_failure_cannot_replace_generation(setup, monkeypatch):
    manager, service, _ = setup

    async def fail(owner):
        owner.clean = False
        raise RuntimeError("connect failed")

    monkeypatch.setattr(FakeOwner, "start", fail)
    replies = await command(manager, "activate_domain")
    assert replies[-1]["error_type"] == "cleanup_failed"
    generation = replies[0]["domain_session_id"]
    repeated = await command(manager, "activate_domain")
    assert repeated[-1]["domain_session_id"] == generation
    assert repeated[-1]["state"] == "cleanup_failed" and service.reservation.held
    manager._sessions["engineering"][-1]._owner.clean = True


@pytest.mark.asyncio
async def test_eleventh_live_identity_is_rejected_without_evicting_startup(
    setup, monkeypatch
):
    manager, _, _ = setup
    from bridge.domain_session import DomainSession

    release = asyncio.Event()
    original = DomainSession._reserve

    async def blocked(session):
        await release.wait()
        await original(session)

    monkeypatch.setattr(DomainSession, "_reserve", blocked)
    replies = [[] for _ in range(11)]

    async def start(index):
        async def emit(packet):
            replies[index].append(packet)

        await manager.handle(
            dict(
                type="activate_domain",
                request_id=str(index),
                domain_id=(sorted(DOMAIN_IDS) + ["extra-limit-test"])[index],
            ),
            context=context(str(index)),
            emit=emit,
        )

    tasks = [asyncio.create_task(start(index)) for index in range(10)]
    await asyncio.sleep(0)
    await start(10)
    assert replies[10][0]["error_type"] == "domain_busy"
    assert len(manager._sessions) == 10
    release.set()
    await asyncio.gather(*tasks)
    assert all(
        reply[-1].get("state") == "active"
        or reply[-1].get("error_type") == "capacity_limit"
        for reply in replies[:10]
    )


@pytest.mark.asyncio
async def test_capacity_refusal_does_not_claim_another_department_workspace(setup):
    manager, _, _ = setup
    await command(manager, "activate_domain")
    packets = []

    async def emit(packet):
        packets.append(packet)

    await manager.handle(
        dict(type="activate_domain", request_id="second", domain_id="core"),
        context=context("second"),
        emit=emit,
    )
    assert packets[-1]["error_type"] == "capacity_limit"
    assert "capacity" in packets[-1]["message"].lower()


@pytest.mark.asyncio
async def test_shutdown_drains_all_generations_before_reporting_cleanup_failure(
    setup, monkeypatch
):
    manager, _, owners = setup
    first = (await command(manager, "activate_domain"))[-1]["domain_session_id"]
    await command(manager, "deactivate_domain", domain_session_id=first)
    await command(manager, "activate_domain")
    old = manager._sessions["engineering"][0]

    async def fail():
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(old, "stop", fail)
    owners[-1].stop_gate = asyncio.Event()
    shutdown = asyncio.create_task(manager.shutdown())
    await owners[-1].stopped.wait()
    await asyncio.sleep(0.01)
    try:
        assert not shutdown.done()
    finally:
        owners[-1].stop_gate.set()
        try:
            await shutdown
        except Exception:
            pass
        monkeypatch.undo()
    assert not owners[-1].lease.held


@pytest.mark.asyncio
async def test_cancelled_activation_delivery_detaches_caller_but_keeps_startup(
    setup, monkeypatch
):
    manager, _, owners = setup
    original = FakeOwner.start

    async def blocked(owner):
        owner.connect_gate = asyncio.Event()
        await original(owner)

    monkeypatch.setattr(FakeOwner, "start", blocked)
    sending = asyncio.Event()

    async def emit(packet):
        sending.set()
        await asyncio.Future()

    task = asyncio.create_task(
        manager.handle(
            dict(type="activate_domain", request_id="start", domain_id="engineering"),
            context=context("start"),
            emit=emit,
        )
    )
    await sending.wait()
    task.cancel()
    await asyncio.sleep(0.01)
    try:
        assert task.done()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await manager.shutdown()
    assert owners[0].started.is_set()
