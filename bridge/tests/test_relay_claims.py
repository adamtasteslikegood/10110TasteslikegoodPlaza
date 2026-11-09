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


def test_from_env_is_off_unless_repo_is_set(tmp_path):
    assert RelayClaims.from_env({}) is None
    assert RelayClaims.from_env(dict(CREDENTIAL)) is None


@pytest.mark.parametrize(
    "environ",
    [
        dict(RELAY_WORK_REPO="owner/name", PR_GATE_RELAY_TOKEN="t"),
        dict(RELAY_WORK_REPO="owner/name", PR_GATE_RELAY_URL="https://relay.test"),
        dict(RELAY_WORK_REPO="no-slash", **CREDENTIAL),
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


def test_from_env_accepts_an_https_origin_with_a_port(tmp_path):
    environ = dict(
        RELAY_WORK_REPO="owner/name",
        RELAY_WORK_SECRET_FILE=str(tmp_path / "secret"),
        PR_GATE_RELAY_URL="https://127.0.0.1:8443/",
        PR_GATE_RELAY_TOKEN="t",
    )
    work = RelayClaims.from_env(environ).work
    assert work.endpoint == "https://127.0.0.1:8443/v1/owner/name/work"


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
    work.hold_first_checkpoint = threading.Event()
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
    work.hold_first_checkpoint.set()
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
async def test_a_relay_that_does_not_answer_never_stops_local_work(claimed):
    session, _, owners, work = claimed
    work.down.add("claim")
    await session.start()
    assert (await run_once(session))["status"] == "success"
    await session.stop()
    assert work.ops() == ["claim"]


@pytest.mark.asyncio
async def test_a_lost_claim_stops_beating_and_records_nothing_more(claimed):
    session, _, _, work = claimed
    work.refuse["beat"] = 409
    await session.start()
    await asyncio.sleep(0.05)
    assert work.ops().count("beat") == 1
    assert (await run_once(session))["status"] == "success"
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
