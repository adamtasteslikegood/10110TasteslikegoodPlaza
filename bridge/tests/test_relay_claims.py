"""Opt-in relay work claims: settings, and a domain generation's claim lifecycle."""

import asyncio
import subprocess
import threading

import pytest
import pytest_asyncio

from bridge.config import default_config
from bridge.domain_protocol import DomainCommandError
from bridge.domain_session import DomainSession
from bridge.relay_claims import RelayClaims, REF_PREFIX
from bridge.relay_work import RelayDown, RelayRefused
from bridge.tests.domain_fakes import (
    FakeOwner,
    FakeProjectService,
    collect_until,
    context,
    query,
)

CREDENTIAL = dict(PR_GATE_RELAY_URL="https://relay.test", PR_GATE_RELAY_TOKEN="t")


class FakeWork:
    """RelayWork's surface, recording calls; ``refuse`` and ``down`` script failures."""

    def __init__(self):
        self.holder = "bridge@test"
        self.calls = []
        self.tokens = {}
        self.refuse = {}
        self.down = set()
        self.hold_first_checkpoint = None
        self.holders = []

    def _call(self, op, ref, **fields):
        self.calls.append((op, ref, fields))
        if op in self.down:
            raise RelayDown("no answer")
        if op in self.refuse:
            raise RelayRefused(self.refuse[op], {"error": "refused"})

    def claim(self, ref, title=None, branch=None, reopen=False):
        self._call("claim", ref, branch=branch, reopen=reopen)
        self.holders.append(self.holder)
        self.tokens[ref] = 1
        return dict(token=1, tookOver=False, resume=dict(branch=None, steps=[]))

    def beat(self, ref):
        self._call("beat", ref)
        return dict(ok=True)

    def checkpoint(self, ref, text, commit=None, branch=None, notes=None):
        self._call("checkpoint", ref, text=text, commit=commit, branch=branch)
        first = self.ops().count("checkpoint") == 1
        if first and self.hold_first_checkpoint is not None:
            assert self.hold_first_checkpoint.wait(5)
        return dict(ok=True)

    def release(self, ref, outcome, text=None):
        self._call("release", ref, outcome=outcome)
        self.tokens.pop(ref, None)
        return dict(ok=True)

    def ops(self):
        return [op for op, _, _ in self.calls]


def test_from_env_is_off_unless_repo_is_set():
    assert RelayClaims.from_env({}) is None
    assert RelayClaims.from_env(dict(CREDENTIAL)) is None


@pytest.mark.parametrize(
    "environ",
    [
        dict(RELAY_WORK_REPO="owner/name", PR_GATE_RELAY_TOKEN="t"),
        dict(RELAY_WORK_REPO="owner/name", PR_GATE_RELAY_URL="https://relay.test"),
        dict(RELAY_WORK_REPO="no-slash", **CREDENTIAL),
        dict(
            RELAY_WORK_REPO="owner/name", RELAY_WORK_HOLDER="bridge@hôte", **CREDENTIAL
        ),
        dict(RELAY_WORK_REPO="owner/name", RELAY_WORK_HOLDER="bridge\nx", **CREDENTIAL),
        dict(RELAY_WORK_REPO="owner/name", RELAY_WORK_HOLDER="h" * 188, **CREDENTIAL),
        dict(RELAY_WORK_REPO="owner/..", **CREDENTIAL),
        dict(RELAY_WORK_REPO="owner/.", **CREDENTIAL),
        dict(RELAY_WORK_REPO="own er/name", **CREDENTIAL),
        dict(RELAY_WORK_REPO="owner/na?me", **CREDENTIAL),
        dict(RELAY_WORK_REPO="owner/name#x", **CREDENTIAL),
        dict(RELAY_WORK_REPO="-owner/name", **CREDENTIAL),
        dict(RELAY_WORK_REPO="owner/name/work", **CREDENTIAL),
        dict(
            RELAY_WORK_REPO="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/name",
            **CREDENTIAL,
        ),
        dict(RELAY_WORK_REPO="owner/name", RELAY_WORK_BEAT_SECONDS="1", **CREDENTIAL),
        dict(RELAY_WORK_REPO="owner/name", RELAY_WORK_BEAT_SECONDS="inf", **CREDENTIAL),
        dict(RELAY_WORK_REPO="owner/name", RELAY_WORK_BEAT_SECONDS="nan", **CREDENTIAL),
        dict(RELAY_WORK_REPO="owner/name", RELAY_WORK_BEAT_SECONDS="61", **CREDENTIAL),
        dict(
            RELAY_WORK_REPO="owner/name",
            PR_GATE_RELAY_URL="http://relay.test",
            PR_GATE_RELAY_TOKEN="t",
        ),
        dict(
            RELAY_WORK_REPO="owner/name",
            PR_GATE_RELAY_URL="https://",
            PR_GATE_RELAY_TOKEN="t",
        ),
        dict(
            RELAY_WORK_REPO="owner/name",
            PR_GATE_RELAY_URL="https:///v1",
            PR_GATE_RELAY_TOKEN="t",
        ),
        dict(
            RELAY_WORK_REPO="owner/name",
            PR_GATE_RELAY_URL="https://user:pw@relay.test",
            PR_GATE_RELAY_TOKEN="t",
        ),
        dict(
            RELAY_WORK_REPO="owner/name",
            PR_GATE_RELAY_URL="https://relay.test?x=1",
            PR_GATE_RELAY_TOKEN="t",
        ),
        dict(
            RELAY_WORK_REPO="owner/name",
            PR_GATE_RELAY_URL="https://relay.test/v1",
            PR_GATE_RELAY_TOKEN="t",
        ),
        dict(
            RELAY_WORK_REPO="owner/name",
            PR_GATE_RELAY_URL="https://relay.test:99999",
            PR_GATE_RELAY_TOKEN="t",
        ),
        dict(
            RELAY_WORK_REPO="owner/name",
            PR_GATE_RELAY_URL="relay.test",
            PR_GATE_RELAY_TOKEN="t",
        ),
    ],
)
def test_from_env_refuses_a_half_made_setting(tmp_path, environ):
    environ["RELAY_WORK_SECRET_FILE"] = str(tmp_path / "secret")
    with pytest.raises(ValueError):
        RelayClaims.from_env(environ)


def test_an_existing_secret_file_is_made_private_and_checked(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("s" * 40)
    secret.chmod(0o644)
    environ = dict(
        RELAY_WORK_REPO="owner/name", RELAY_WORK_SECRET_FILE=str(secret), **CREDENTIAL
    )
    assert RelayClaims.from_env(environ).work.secret == "s" * 40
    assert secret.stat().st_mode & 0o777 == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["secret"]
    secret.write_text("short")
    with pytest.raises(ValueError):
        RelayClaims.from_env(environ)
    secret.unlink()
    secret.symlink_to(tmp_path / "elsewhere")
    (tmp_path / "elsewhere").write_text("s" * 40)
    with pytest.raises(ValueError):
        RelayClaims.from_env(environ)


def test_relay_redactions_cover_secrets_and_only_a_real_client_id():
    from bridge.server import _relay_redactions

    short = dict(PR_GATE_RELAY_CLIENT_ID="bridge", PR_GATE_RELAY_CLIENT_SECRET="s" * 40)
    assert _relay_redactions(short) == ("s" * 40, "")
    real = dict(short, PR_GATE_RELAY_CLIENT_ID="0123456789abcdef.access")
    assert "0123456789abcdef.access" in _relay_redactions(real)


def test_from_env_accepts_an_https_origin_with_a_port(tmp_path):
    environ = dict(
        RELAY_WORK_REPO="owner/name",
        RELAY_WORK_SECRET_FILE=str(tmp_path / "secret"),
        PR_GATE_RELAY_URL="https://127.0.0.1:8443/",
        PR_GATE_RELAY_TOKEN="t",
    )
    work = RelayClaims.from_env(environ).work
    assert work.endpoint == "https://127.0.0.1:8443/v1/owner/name/work"


@pytest.mark.asyncio
async def test_a_slow_relay_never_queues_checkpoints_without_bound(claimed):
    session, _, _, work = claimed
    await session.start()
    # Start swapped in the claim's own copy of the client (holder digest).
    live = session._claim.work
    live.hold_first_checkpoint = threading.Event()
    for n in range(25):
        session._claim.queue_checkpoint(f"step {n}")
    live.hold_first_checkpoint.set()
    await session._claim.flush()
    sent = [f["text"] for op, _, f in work.calls if op == "checkpoint"]
    assert sent == [f"step {n}" for n in range(20)]


@pytest.mark.asyncio
async def test_a_relay_outage_cannot_hold_stop_past_its_limit(claimed, monkeypatch):
    session, _, _, work = claimed
    monkeypatch.setattr("bridge.relay_claims.FLUSH_SECONDS", 0.2)
    await session.start()
    # Start swapped in the claim's own copy of the client (holder digest).
    live = session._claim.work
    live.hold_first_checkpoint = threading.Event()
    session._claim.queue_checkpoint("stuck")
    session._claim.queue_checkpoint("behind it")
    started = asyncio.get_running_loop().time()
    await session.stop()
    assert asyncio.get_running_loop().time() - started < 3
    assert session.clean_inactive
    live.hold_first_checkpoint.set()
    await asyncio.sleep(0.05)
    assert "behind it" not in [f.get("text") for _, _, f in work.calls]
    # A checkpoint may still have been in flight, so Stop let the claim lapse.
    assert "release" not in work.ops()


@pytest.mark.asyncio
async def test_a_checkpoint_sends_no_more_text_than_the_relay_keeps(claimed):
    session, _, _, work = claimed
    await session.start()
    session._claim.queue_checkpoint("x" * 400)
    await session._claim.flush()
    sent = [f["text"] for op, _, f in work.calls if op == "checkpoint"]
    assert sent == ["x" * 300]


def test_from_env_keeps_one_secret_per_machine(tmp_path):
    environ = dict(
        RELAY_WORK_REPO="Owner/Name",
        RELAY_WORK_SECRET_FILE=str(tmp_path / "plaza" / "secret"),
        RELAY_WORK_HOLDER="bridge@laptop",
        **CREDENTIAL,
    )
    first = RelayClaims.from_env(environ)
    second = RelayClaims.from_env(environ)
    assert first.work.secret == second.work.secret and len(first.work.secret) >= 32
    assert (tmp_path / "plaza" / "secret").stat().st_mode & 0o077 == 0
    assert first.work.endpoint == "https://relay.test/v1/owner/name/work"
    assert first.work.holder == "bridge@laptop" and first.work.runtime == "bridge"
    assert first.work.headers["cf-access-token"] == "t"


@pytest_asyncio.fixture
async def claimed(tmp_path, monkeypatch):
    service = FakeProjectService(tmp_path)
    owners = []

    def factory(*args):
        owner = FakeOwner(*args)
        owners.append(owner)
        return owner

    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", factory, raising=False)
    monkeypatch.setattr(
        "bridge.domain_session.load_agent",
        lambda agent: "definition" if agent == "backend-architect" else None,
    )
    work = FakeWork()
    session = DomainSession(
        "engineering",
        "generation",
        execution_id="execution",
        config=default_config(),
        project_service=service,
        claims=RelayClaims(work, every=0.01),
    )
    yield session, service, owners, work
    await session.stop()
    service.close()


async def run_once(session, request="run", flush=True):
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(
        query(request, task=f"Build {request}"), context=context(request), emit=emit
    )
    await collect_until(session, packets)
    async with asyncio.timeout(3):
        while session._inflight is not None or any(
            not job.done() for job in session._jobs
        ):
            await asyncio.sleep(0.001)
        if flush and session._claim is not None:
            await session._claim.flush()
    return packets[-1]


def head(path):
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.mark.asyncio
async def test_a_recorder_failure_never_stalls_later_checkpoints(claimed):
    session, _, _, work = claimed
    await session.start()

    class Recorder:
        def event(self, *args, **kwargs):
            return True

        def message(self, context, role, *args, **kwargs):
            if role != "user":
                raise RuntimeError("recording failed after the terminal")

    session._recorder = Recorder()
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(query("run-1"), context=context("run-1"), emit=emit)
    async with asyncio.timeout(3):
        while any(not job.done() for job in session._jobs):
            await asyncio.sleep(0.001)
    session._recorder = None
    assert (await run_once(session, "run-2"))["status"] == "success"
    async with asyncio.timeout(3):
        await session._claim.flush()
    texts = [f["text"] for op, _, f in work.calls if op == "checkpoint"]
    assert texts[-1] == "success (completed): Build run-2"


@pytest.mark.asyncio
async def test_the_checkpoint_follows_the_terminals_delivery(claimed):
    session, _, _, work = claimed
    await session.start()
    delivering, release = asyncio.Event(), asyncio.Event()
    packets = []

    async def emit(packet):
        if packet["type"] == "domain_result":
            delivering.set()
            await release.wait()
        packets.append(packet)

    await session.admit_query(query(), context=context(), emit=emit)
    async with asyncio.timeout(3):
        await delivering.wait()
    await asyncio.sleep(0.05)
    assert "checkpoint" not in work.ops()  # nothing reaches the relay yet
    release.set()
    await collect_until(session, packets)
    async with asyncio.timeout(3):
        while any(not job.done() for job in session._jobs):
            await asyncio.sleep(0.001)
    await session._claim.flush()
    assert work.ops().count("checkpoint") == 1


@pytest.mark.asyncio
async def test_checkpoints_keep_each_runs_head_and_arrive_in_order(claimed):
    session, service, _, work = claimed
    await session.start()
    # Start swapped in the claim's own copy of the client (holder digest).
    live = session._claim.work
    live.hold_first_checkpoint = threading.Event()
    path = service.workspace.worktree_path
    first_head = head(path)
    assert (await run_once(session, "run-1", flush=False))["status"] == "success"
    # The next Run moves the worktree while the first checkpoint is in flight.
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t"]
        + ["-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-qm", "b"],
        check=True,
    )
    second_head = head(path)
    assert (await run_once(session, "run-2", flush=False))["status"] == "success"
    live.hold_first_checkpoint.set()
    await session._claim.flush()
    sent = [f for op, _, f in work.calls if op == "checkpoint"]
    assert [f["commit"] for f in sent] == [first_head, second_head]
    assert [f["text"] for f in sent] == [
        "success (completed): Build run-1",
        "success (completed): Build run-2",
    ]
    await session.stop()
    assert work.ops()[-1] == "release"


@pytest.mark.asyncio
async def test_start_claims_runs_checkpoint_and_stop_releases_paused(claimed):
    session, service, owners, work = claimed
    await session.start()
    ref = REF_PREFIX + "engineering"
    op, claimed_ref, fields = work.calls[0]
    assert (op, claimed_ref) == ("claim", ref)
    assert fields == dict(branch=service.workspace.branch, reopen=True)
    await asyncio.sleep(0.05)
    assert "beat" in work.ops()
    result = await run_once(session)
    assert result["status"] == "success"
    checkpoint = next(f for op, _, f in work.calls if op == "checkpoint")
    assert checkpoint["text"] == "success (completed): Build run"
    assert checkpoint["branch"] == service.workspace.branch
    assert checkpoint["commit"] and len(checkpoint["commit"]) == 40
    await session.stop()
    assert work.calls[-1] == ("release", ref, dict(outcome="paused"))
    beats = work.ops().count("beat")
    await asyncio.sleep(0.05)
    assert work.ops().count("beat") == beats


@pytest.mark.asyncio
async def test_a_claim_held_elsewhere_refuses_start_and_frees_the_workspace(claimed):
    session, service, owners, work = claimed
    work.refuse["claim"] = 423
    with pytest.raises(DomainCommandError) as error:
        await session.start()
    assert error.value.code == "work_claimed"
    assert not owners or not owners[0].started.is_set()
    await session.stop()
    assert session.clean_inactive and service.capacity is None
    assert "release" not in work.ops()


@pytest.mark.asyncio
async def test_the_holder_names_the_checkout_so_two_checkouts_never_share(claimed):
    session, service, _, work = claimed
    await session.start()
    await session.stop()
    claims = RelayClaims(work, every=60)
    again = claims.for_domain("engineering")
    other = claims.for_domain("engineering")
    await again.claim(place=str(service.workspace.project_root))
    await other.claim(place="/elsewhere/another-checkout")
    await again.claim(place=str(service.workspace.project_root))
    first, renewed, elsewhere, repeated = work.holders
    assert repeated == renewed  # a repeated claim never stacks suffixes
    assert first == renewed and first.startswith("bridge@test:")
    assert elsewhere != first and elsewhere.startswith("bridge@test:")
    assert work.holder == "bridge@test"  # the shared settings are untouched
    for claim in (again, other):
        await claim.close(release=False)


@pytest.mark.asyncio
async def test_a_refused_credential_refuses_start(claimed):
    session, _, _, work = claimed
    work.refuse["claim"] = 403
    with pytest.raises(DomainCommandError) as error:
        await session.start()
    assert error.value.code == "relay_refused"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [dict(ok=True), dict(token="1"), dict(token=True), ValueError("unexpected shape")],
)
async def test_an_unreadable_claim_answer_refuses_start(claimed, monkeypatch, answer):
    session, service, _, work = claimed

    def claim(ref, title=None, branch=None, reopen=False):
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(work, "claim", claim)
    with pytest.raises(DomainCommandError) as error:
        await session.start()
    assert error.value.code == "relay_refused"
    await session.stop()
    assert session.clean_inactive and service.capacity is None


@pytest.mark.asyncio
async def test_a_relay_that_does_not_answer_never_stops_local_work(claimed):
    session, _, owners, work = claimed
    work.down.add("claim")
    await session.start()
    assert (await run_once(session))["status"] == "success"
    await session.stop()
    assert work.ops() == ["claim"]


@pytest.mark.asyncio
async def test_a_claim_lost_to_another_holder_records_nothing_more(claimed):
    session, _, _, work = claimed
    work.refuse["beat"] = 409
    await session.start()
    work.refuse["claim"] = 423  # another runtime holds it from here on
    await asyncio.sleep(0.05)
    assert work.ops().count("beat") == 1  # beating stopped with the loss
    packet = await refused_run(session, "run-1")
    assert packet["error_type"] == "work_claimed"
    await session.stop()
    assert "checkpoint" not in work.ops() and "release" not in work.ops()


@pytest.mark.asyncio
async def test_relay_trouble_after_start_never_fails_a_run(claimed):
    session, _, _, work = claimed
    await session.start()
    work.down.update({"beat", "checkpoint", "release"})
    assert (await run_once(session))["status"] == "success"
    await session.stop()
    assert session.clean_inactive


async def lose_claim(session, work):
    """The relay refuses the next beat, as after a lapse or a takeover."""
    work.refuse["beat"] = 409
    async with asyncio.timeout(3):
        while session._claim.held:
            await asyncio.sleep(0.005)
    del work.refuse["beat"]
    assert session.snapshot()["work_claim"] == "lost"


async def refused_run(session, request):
    packets = []

    async def emit(packet):
        packets.append(packet)

    await session.admit_query(
        query(request, task=f"Build {request}"), context=context(request), emit=emit
    )
    async with asyncio.timeout(3):
        while not packets or session._inflight is not None:
            await asyncio.sleep(0.001)
    return packets[-1]


@pytest.mark.asyncio
async def test_a_lost_claim_is_claimed_again_before_the_next_run(claimed):
    session, service, _, work = claimed
    await session.start()
    assert session.snapshot()["work_claim"] == "held"
    await lose_claim(session, work)
    before = len(work.calls)
    assert (await run_once(session, "run-1"))["status"] == "success"
    later = [(op, f) for op, _, f in work.calls[before:]]
    assert later[0] == ("claim", dict(branch=service.workspace.branch, reopen=True))
    assert "checkpoint" in [op for op, _ in later]
    assert work.holders[-1] == work.holders[0]  # the same holder, not a stacked one
    assert session.snapshot()["work_claim"] == "held"
    await asyncio.sleep(0.05)
    assert "beat" in [op for op, _, _ in work.calls[before:]]
    await session.stop()
    assert work.ops()[-1] == "release"


@pytest.mark.asyncio
async def test_a_claim_taken_elsewhere_refuses_the_next_run_not_the_session(claimed):
    session, service, owners, work = claimed
    await session.start()
    await lose_claim(session, work)
    work.refuse["claim"] = 423
    revision = service.memory.load().revision
    packet = await refused_run(session, "run-1")
    assert packet["type"] == "domain_error" and packet["error_type"] == "work_claimed"
    assert not owners[0].calls and service.memory.load().revision == revision
    assert session.can_run and session.snapshot()["work_claim"] == "lost"
    del work.refuse["claim"]
    assert (await run_once(session, "run-2"))["status"] == "success"
    assert session.snapshot()["work_claim"] == "held"


@pytest.mark.asyncio
async def test_a_relay_still_down_is_asked_again_only_after_a_wait(
    claimed, monkeypatch
):
    session, _, _, work = claimed
    work.down.add("claim")
    await session.start()
    assert session.snapshot()["work_claim"] == "unclaimed"
    assert (await run_once(session, "run-1"))["status"] == "success"
    assert work.ops().count("claim") == 1  # not asked again inside the wait
    monkeypatch.setattr("bridge.relay_claims.RETRY_SECONDS", 0)
    assert (await run_once(session, "run-2"))["status"] == "success"
    # With no wait, it is asked before preparing and again before acceptance.
    assert work.ops().count("claim") == 3 and "checkpoint" not in work.ops()
    work.down.discard("claim")
    assert (await run_once(session, "run-3"))["status"] == "success"
    assert session.snapshot()["work_claim"] == "held" and "checkpoint" in work.ops()


@pytest.mark.asyncio
async def test_work_claim_is_a_domain_state_fact_of_a_live_claimed_session(claimed):
    session, _, _, _ = claimed
    assert "work_claim" not in session.snapshot()
    await session.start()
    assert session.snapshot()["work_claim"] == "held"
    assert "work_claim" not in session.replay(0)[-1]
    await session.stop()
    assert "work_claim" not in session.snapshot()


@pytest.mark.asyncio
async def test_a_claim_lost_while_a_run_prepares_is_asked_again_before_acceptance(
    claimed,
):
    session, service, owners, work = claimed
    await session.start()
    prepare = session._readiness.prepare_turn

    async def losing(intent):
        snapshot = await prepare(intent)
        # Taken over elsewhere while this Run was still preparing.
        session._claim._lose()
        work.refuse["claim"] = 423
        return snapshot

    session._readiness.prepare_turn = losing
    packet = await refused_run(session, "run-1")
    assert packet["type"] == "domain_error" and packet["error_type"] == "work_claimed"
    assert not owners[0].calls and "pending" not in service.memory.load().todo
    session._readiness.prepare_turn = prepare
    del work.refuse["claim"]
    assert (await run_once(session, "run-2"))["status"] == "success"


@pytest.mark.asyncio
async def test_a_live_claimed_sessions_resume_complete_carries_no_work_claim(
    tmp_path, monkeypatch
):
    """The manager builds resume_complete from its own snapshot, not the session's."""
    from bridge.domain_manager import DomainManager
    from bridge.state_coordinator import LazySQLiteStateRepository, StateCoordinator
    from bridge.tests.test_domain_lifecycle_v2 import send

    service = FakeProjectService(tmp_path)
    monkeypatch.setattr("bridge.domain_session.DomainSDKOwner", FakeOwner)
    common, project = await service.application_state_binding()
    coordinator = StateCoordinator(lambda: LazySQLiteStateRepository(common, project))
    await coordinator.open()
    manager = DomainManager(
        default_config(),
        service,
        state_coordinator=coordinator,
        claims=RelayClaims(FakeWork(), every=60),
    )
    try:
        started = await send(manager, "activate_domain")
        assert started["type"] == "domain_state" and started["work_claim"] == "held"
        assert manager.snapshot("engineering")["work_claim"] == "held"
        resumed = await send(
            manager,
            "resume",
            domain_session_id=started["domain_session_id"],
            cursor="0",
        )
        assert resumed["type"] == "resume_complete" and resumed["state"] == "active"
        assert "work_claim" not in resumed
    finally:
        await manager.shutdown()
        await coordinator.close()
        service.close()
