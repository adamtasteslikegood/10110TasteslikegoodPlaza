"""CloudOwner against FakeRunner, with a bare repository in tmp_path as origin."""

import asyncio
import errno
import json
import os
import threading
import time
from types import SimpleNamespace

import pytest

from bridge import cloud_owner
from bridge.cloud_git import CloudSyncError, mark_cloud
from bridge.cloud_owner import PREAMBLE, CloudOwner, CloudStartRefused
from bridge.cloud_runner import RunnerDown, RunnerRefused
from bridge.domain_sdk import CleanupOutcome
from bridge.tests.cloud_fakes import FakeRunner
from bridge.tests.test_cloud_git import (  # noqa: F401 (fixtures)
    commit,
    file_protocol,
    head,
    isolated_home,
    other_clone,
    path_origin,
    remote_tip,
    setup as make_project,
)
from bridge.tests.test_workspace import git

KEY = "key-1"
DELTA_REPLY = json.dumps({"answer": "Partly.", "memory_delta": {"summary": "Half"}})


class LogRunner(FakeRunner):
    """FakeRunner whose events come from one log, served by ``after`` two at a time."""

    PAGE = 2

    def __init__(self, log=()):
        super().__init__()
        self.log = list(log)
        self.event_faults = []
        self.served = []

    def events(self, name, after):
        self.calls.append(("events", name, after))
        if self.event_faults:
            fault = self.event_faults.pop(0)
            if fault is not None:
                raise fault
        rows = [row for row in self.log if row["seq"] > after][: self.PAGE]
        self.served += [row["seq"] for row in rows]
        return rows, (rows[-1]["seq"] if rows else after)


def event(seq, run, kind, payload):
    return dict(seq=seq, run=run, generation=1, at="", type=kind, payload=payload)


def ended(run=1, state="succeeded", **extra):
    return dict(state=state, run=run, generation=1, **extra)


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(CloudOwner, "POLL_SECONDS", 0)


@pytest.fixture
def cloud(tmp_path, file_protocol):  # noqa: F811
    origin, workspace = make_project(tmp_path)
    runner = LogRunner()
    owner = CloudOwner(
        SimpleNamespace(domain_max_turns=40),
        workspace,
        None,
        None,
        runner=runner,
        conversation=KEY,
    )
    name = f"{workspace.project_id}-{workspace.domain_id}"
    clone = {}

    def push_from_cloud(file_name):
        """Commit and push on origin's branch, as the runner does after a run."""
        if "root" not in clone:
            clone["root"] = other_clone(tmp_path, origin, workspace.branch)
        sha = commit(clone["root"], file_name)
        git(clone["root"], "push", "-q", "origin", workspace.branch)
        return sha

    def note():
        path = workspace.common_git_dir / "plaza/cloud" / f"{workspace.domain_id}.json"
        return json.loads(path.read_text())["unsynced"]

    return SimpleNamespace(
        origin=origin,
        workspace=workspace,
        runner=runner,
        owner=owner,
        name=name,
        push_from_cloud=push_from_cloud,
        note=note,
    )


def run(cloud, **changes):
    arguments = dict(
        agent_id="engineering-agent",
        definition="definition",
        task="task",
        prior_project_notes="notes",
    )
    return cloud.owner.execute(**dict(arguments, **changes))


def methods(runner):
    return [call[0] for call in runner.calls]


@pytest.fixture
def fast_forwards(monkeypatch):
    seen = []
    real = cloud_owner.fast_forward_to

    def counting(workspace, sha):
        seen.append(sha)
        return real(workspace, sha)

    monkeypatch.setattr(cloud_owner, "fast_forward_to", counting)
    return seen


# start()


@pytest.mark.asyncio
async def test_start_asks_the_status_then_syncs_then_creates_the_workspace_named_for_the_project_and_department(
    cloud,
):
    assert remote_tip(cloud.origin, cloud.workspace.branch) is None
    await cloud.owner.start()
    branch = cloud.workspace.branch
    assert cloud.runner.calls == [
        ("status", cloud.name),
        ("create", cloud.name, str(cloud.origin), branch),
    ]
    assert cloud.name == f"{cloud.workspace.project_id}-engineering"
    assert remote_tip(cloud.origin, branch) == head(cloud.workspace)
    assert cloud.note() is False


@pytest.mark.asyncio
async def test_a_second_start_asks_nothing_and_a_start_after_stop_is_refused(cloud):
    await cloud.owner.start()
    calls = len(cloud.runner.calls)
    await cloud.owner.start()  # the session calls start() before every Run
    assert len(cloud.runner.calls) == calls
    await cloud.owner.stop()
    calls = len(cloud.runner.calls)
    with pytest.raises(RuntimeError, match="stopped"):
        await cloud.owner.start()
    assert len(cloud.runner.calls) == calls


@pytest.mark.asyncio
async def test_start_pushes_nothing_while_an_earlier_run_is_active(cloud):
    await cloud.owner.start()
    before = remote_tip(cloud.origin, cloud.workspace.branch)
    commit(cloud.workspace.worktree_path, "ahead.txt")
    owner = CloudOwner(
        SimpleNamespace(domain_max_turns=40),
        cloud.workspace,
        None,
        None,
        runner=cloud.runner,
        conversation=KEY,
    )
    cloud.runner.script("status", ended(state="running"))
    with pytest.raises(CloudStartRefused):
        await owner.start()
    assert remote_tip(cloud.origin, cloud.workspace.branch) == before


@pytest.mark.parametrize("which", ["status", "create"])
@pytest.mark.asyncio
async def test_start_is_refused_while_an_earlier_run_is_active(
    cloud, fast_forwards, which
):
    cloud.runner.script(which, ended(state="running"))
    with pytest.raises(CloudStartRefused) as refused:
        await cloud.owner.start()
    assert refused.value.code == "cloud_run_active"
    assert "stop" not in methods(cloud.runner)
    assert not cloud.owner.healthy
    if which == "status":
        assert methods(cloud.runner) == ["status"]
        assert remote_tip(cloud.origin, cloud.workspace.branch) is None
    note = (
        cloud.workspace.common_git_dir
        / "plaza/cloud"
        / (f"{cloud.workspace.domain_id}.json")
    )
    assert not note.exists()
    assert fast_forwards == []


@pytest.mark.parametrize(
    "fault, code",
    [
        ("down", "cloud_unavailable"),
        ("refused", "cloud_refused"),
        ("dirty", "cloud_sync_failed"),
    ],
)
@pytest.mark.asyncio
async def test_start_maps_down_refused_and_sync_errors(cloud, capsys, fault, code):
    if fault == "down":
        cloud.runner.script("status", RunnerDown("no answer"))
    elif fault == "refused":
        cloud.runner.script("create", RunnerRefused(422, "No GitHub token"))
    else:
        (cloud.workspace.worktree_path / "loose.txt").write_text("local\n")
    with pytest.raises(CloudStartRefused) as refused:
        await cloud.owner.start()
    assert refused.value.code == code
    assert not cloud.owner.healthy
    if fault == "dirty":
        assert "create" not in methods(cloud.runner)
        one_line(capsys, cloud, "dirty")


@pytest.mark.asyncio
async def test_a_404_from_the_first_status_is_no_workspace_yet(cloud):
    cloud.runner.script("status", RunnerRefused(404, "No such workspace"))
    await cloud.owner.start()
    assert methods(cloud.runner) == ["status", "create"]
    assert cloud.owner.healthy


@pytest.mark.asyncio
async def test_start_takes_a_commit_pushed_while_the_bridge_was_away_and_clears_the_note(
    cloud,
):
    from bridge.cloud_git import sync_before_start

    sync_before_start(cloud.workspace)
    mark_cloud(cloud.workspace, unsynced=True)
    pushed = {}

    def create(name, repo, branch):
        # A run ends between the sync and the answer: its push lands on origin.
        cloud.runner.calls.append(("create", name, repo, branch))
        pushed["sha"] = cloud.push_from_cloud("cloud.txt")
        return ended(pushed={"commit": pushed["sha"]})

    cloud.runner.create = create
    await cloud.owner.start()
    assert head(cloud.workspace) == pushed["sha"]
    assert cloud.note() is False


# execute()


@pytest.mark.asyncio
async def test_a_run_returns_the_decoded_answer_and_memory_delta(cloud):
    await cloud.owner.start()
    cloud.runner.log = [
        event(1, 1, "system", {"subtype": "init", "session_id": "session-1"}),
        event(2, 1, "result", {"subtype": "success"}),
    ]
    reply = json.dumps({"answer": "Ready.", "memory_delta": {"summary": "Checked"}})
    cloud.runner.script("status", ended(state="running"), ended(result=reply))
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("success", "completed")
    assert outcome.output == "Ready."
    assert outcome.memory_delta == {"summary": "Checked"}
    assert outcome.provider_session_id == "session-1"


@pytest.mark.asyncio
async def test_the_worktree_is_at_the_pushed_commit_after_a_run(cloud, fast_forwards):
    await cloud.owner.start()
    sha = cloud.push_from_cloud("work.txt")
    cloud.runner.script("status", ended(result="done", pushed={"commit": sha}))
    outcome = await run(cloud)
    assert outcome.status == "success"
    assert head(cloud.workspace) == sha
    assert fast_forwards == [sha]


@pytest.mark.asyncio
async def test_an_outage_mid_run_reads_no_event_twice(cloud):
    await cloud.owner.start()
    cloud.runner.log = [
        event(1, 1, "system", {"session_id": "session-1"}),
        event(2, 1, "assistant", {}),
        event(3, 1, "assistant", {}),
        event(4, 1, "assistant", {}),
        event(5, 1, "result", {"subtype": "success"}),
    ]
    # Rows arrive, then the status call fails: the next events call must carry on.
    cloud.runner.event_faults = [None, RunnerDown("x"), None]
    cloud.runner.script(
        "status",
        RunnerDown("after rows"),
        ended(state="running"),
        RunnerDown("again"),
        ended(result="done"),
    )
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("success", "completed")
    afters = [call[2] for call in cloud.runner.calls if call[0] == "events"]
    assert afters == sorted(afters)
    assert cloud.runner.served == [1, 2, 3, 4, 5]
    assert outcome.provider_session_id == "session-1"


@pytest.mark.asyncio
async def test_an_outage_longer_than_the_limit_ends_as_transport_error(
    cloud, monkeypatch, fast_forwards
):
    monkeypatch.setattr(CloudOwner, "OUTAGE_SECONDS", 0.05)
    await cloud.owner.start()
    cloud.runner.event_faults = [RunnerDown("down")] * 10_000
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("error", "transport_error")
    assert cloud.note() is True
    assert fast_forwards == []


@pytest.mark.asyncio
async def test_an_earlier_runs_events_never_reach_the_outcome(cloud):
    await cloud.owner.start()
    cloud.runner.log = [
        event(1, 1, "system", {"session_id": "session-1"}),
        event(2, 1, "result", {"subtype": "error_max_turns", "truncated": True}),
        event(3, 1, "runner", {"notice": "result truncated", "run": 1}),
        event(4, 2, "system", {"session_id": "session-2"}),
        event(5, 2, "result", {"subtype": "success"}),
    ]
    cloud.runner.script("start_run", 2)
    cloud.runner.script("status", ended(run=1), ended(run=2, result="answer two"))
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("success", "completed")
    assert outcome.provider_session_id == "session-2"
    assert outcome.output == "answer two"


@pytest.mark.asyncio
async def test_the_cursor_carries_on_to_the_next_run(cloud):
    await cloud.owner.start()
    cloud.runner.log = [event(1, 1, "system", {"session_id": "session-1"})]
    cloud.runner.script(
        "status", ended(run=1, result="one"), ended(run=2, result="two")
    )
    await run(cloud)
    cloud.runner.log.append(event(2, 2, "system", {"session_id": "session-2"}))
    cloud.runner.calls.clear()
    cloud.runner.script("status", ended(run=2, result="two"))
    outcome = await run(cloud)
    assert [call[2] for call in cloud.runner.calls if call[0] == "events"][0] == 1
    assert outcome.provider_session_id == "session-2"


def bounded(cloud):
    """A Run that has not ended in 5 s fails the test instead of hanging it."""
    return asyncio.wait_for(run(cloud), 5)


@pytest.mark.asyncio
async def test_a_later_run_in_the_status_ends_ours_as_lost(cloud, fast_forwards):
    await cloud.owner.start()
    cloud.runner.log = [event(1, 1, "system", {"session_id": "session-1"})]
    cloud.runner.script("status", ended(run=2, state="running"))
    outcome = await bounded(cloud)
    assert (outcome.status, outcome.reason) == ("error", "cloud_run_lost")
    assert methods(cloud.runner).count("status") == 2  # start's, and one poll
    assert cloud.note() is True
    assert fast_forwards == []
    # The owner is usable for a later Run, and its cursor carries on.
    cloud.runner.calls.clear()
    cloud.runner.script("status", ended(run=2, result="two"))
    outcome = await bounded(cloud)
    assert (outcome.status, outcome.output) == ("success", "two")
    assert [call[2] for call in cloud.runner.calls if call[0] == "events"][0] == 1


@pytest.mark.parametrize(
    "answer",
    [ended(run=0, state="running"), {"state": "idle"}, ended(run="1"), ended(run=True)],
)
@pytest.mark.asyncio
async def test_a_status_that_never_names_this_run_ends_as_lost_after_the_limit(
    cloud, monkeypatch, fast_forwards, answer
):
    monkeypatch.setattr(CloudOwner, "OUTAGE_SECONDS", 0.05)
    await cloud.owner.start()
    cloud.runner.script("status", answer)
    outcome = await bounded(cloud)
    assert (outcome.status, outcome.reason) == ("error", "cloud_run_lost")
    assert cloud.note() is True
    assert fast_forwards == []
    cloud.runner.script("status", ended(run=2, result="two"))
    outcome = await bounded(cloud)
    assert (outcome.status, outcome.output) == ("success", "two")


@pytest.mark.asyncio
async def test_outages_and_wrong_run_answers_share_one_limit(
    cloud, monkeypatch, fast_forwards
):
    monkeypatch.setattr(CloudOwner, "OUTAGE_SECONDS", 0.05)
    await cloud.owner.start()
    seen = []

    def status(name):
        # Down, then an answer that does not name this run, in turn.
        seen.append("down" if len(seen) % 2 == 0 else "wrong")
        if seen[-1] == "down":
            raise RunnerDown("down")
        return ended(run=0, state="running")

    cloud.runner.status = status
    outcome = await bounded(cloud)
    assert outcome.status == "error"
    last = "transport_error" if seen[-1] == "down" else "cloud_run_lost"
    assert outcome.reason == last
    assert cloud.note() is True
    assert fast_forwards == []


@pytest.mark.parametrize(
    "status, reason", [(404, "cloud_run_lost"), (401, "transport_error")]
)
@pytest.mark.asyncio
async def test_a_refusal_while_polling_ends_the_run_without_raising(
    cloud, fast_forwards, status, reason
):
    await cloud.owner.start()
    cloud.runner.script("status", RunnerRefused(status, "refused"))
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("error", reason)
    assert cloud.note() is True
    assert fast_forwards == []
    assert methods(cloud.runner).count("status") == 2  # start's, and one poll


@pytest.mark.parametrize("fault", [RunnerDown("down"), RunnerRefused(404, "gone")])
@pytest.mark.asyncio
async def test_a_failed_last_events_call_keeps_the_known_end_state(cloud, fault):
    await cloud.owner.start()
    cloud.runner.log = [event(1, 1, "system", {"session_id": "session-1"})]
    # The poll's events call answers; the last one, after the end state, fails.
    cloud.runner.event_faults = [None, fault]
    cloud.runner.script("status", ended(result="done"))
    outcome = await bounded(cloud)
    assert (outcome.status, outcome.reason, outcome.output) == (
        "success",
        "completed",
        "done",
    )
    assert outcome.provider_session_id == "session-1"
    assert methods(cloud.runner).count("events") == 2  # one attempt at the last


@pytest.mark.asyncio
async def test_a_push_error_is_an_error_with_the_answer_kept(cloud):
    await cloud.owner.start()
    cloud.runner.script("status", ended(result="done", pushError="fatal: denied"))
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("error", "cloud_push_failed")
    assert outcome.output == "done"


@pytest.mark.parametrize(
    "status, expected",
    [
        (ended(state="failed", error="max turns"), ("error", "max_turns")),
        (ended(state="lost", error="gone"), ("error", "cloud_run_lost")),
        (ended(state="stopped", result=DELTA_REPLY), ("cancelled", "stopped")),
    ],
)
@pytest.mark.asyncio
async def test_max_turns_lost_and_stopped_map_as_the_table_says(
    cloud, status, expected
):
    await cloud.owner.start()
    cloud.runner.log = [event(1, 1, "result", {"subtype": "error_max_turns"})]
    cloud.runner.script("status", status)
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == expected
    if status["state"] == "stopped":
        # As the local owner reports a stop: no delta, the raw text kept.
        assert outcome.memory_delta is None
        assert outcome.output == DELTA_REPLY


@pytest.mark.parametrize(
    "mark",
    [
        event(2, 1, "runner", {"notice": "result truncated", "run": 1}),
        event(2, 1, "result", {"truncated": True, "bytes": 999_999}),
    ],
)
@pytest.mark.asyncio
async def test_a_truncated_result_is_output_limit(cloud, mark):
    await cloud.owner.start()
    cloud.runner.log = [event(1, 1, "system", {"session_id": "s"}), mark]
    cloud.runner.script("status", ended(result="partial"))
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("error", "output_limit")
    assert outcome.output == ""
    assert outcome.memory_delta is None


@pytest.mark.asyncio
async def test_an_oversized_result_is_cut_as_the_local_owner_cuts(cloud):
    await cloud.owner.start()
    cloud.runner.script("status", ended(result="x" * (300 * 1024)))
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("error", "output_limit")
    assert outcome.output.endswith("\n[Output truncated]")
    assert len(outcome.output.encode()) <= cloud_owner.MAX_OUTPUT_BYTES


@pytest.mark.asyncio
async def test_a_plain_text_result_is_the_answer_with_no_delta(cloud):
    await cloud.owner.start()
    cloud.runner.script("status", ended(result="Just prose."))
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("success", "completed")
    assert outcome.output == "Just prose."
    assert outcome.memory_delta is None


@pytest.mark.asyncio
async def test_the_prompt_starts_with_the_preamble_and_carries_the_local_command_json(
    cloud,
):
    cloud.owner = CloudOwner(
        SimpleNamespace(domain_max_turns=400),
        cloud.workspace,
        None,
        None,
        runner=cloud.runner,
        conversation=KEY,
    )
    await cloud.owner.start()
    cloud.runner.script("status", ended(result="done"))
    await run(cloud, context_packet=SimpleNamespace(render=lambda: "context 雪"))
    (call,) = [call for call in cloud.runner.calls if call[0] == "start_run"]
    _, name, prompt, conversation, max_turns = call
    assert (name, conversation, max_turns) == (cloud.name, KEY, 100)
    assert PREAMBLE.startswith("Follow the selected agent definition")
    assert PREAMBLE.endswith(cloud_owner.PROJECT_REPLY_INSTRUCTIONS)
    assert prompt.startswith(PREAMBLE + "\n\n")
    assert json.loads(prompt[len(PREAMBLE) + 2 :]) == dict(
        agent_id="engineering-agent",
        definition="definition",
        task="task",
        prior_project_notes="notes",
        current_context="context 雪",
    )
    assert "雪" in prompt


@pytest.mark.asyncio
async def test_conversation_is_new_until_the_runner_holds_this_key(cloud):
    assert await cloud.owner.conversation_is_new()
    cloud.runner.script("status", ended(conversation="another"))
    assert await cloud.owner.conversation_is_new()
    cloud.runner.script("status", ended(conversation=KEY))
    assert not await cloud.owner.conversation_is_new()
    cloud.runner.script("status", RunnerDown("no answer"))
    assert await cloud.owner.conversation_is_new()
    cloud.runner.script("status", RunnerRefused(404, "gone"))
    assert await cloud.owner.conversation_is_new()


# stop() and healthy


@pytest.mark.asyncio
async def test_stop_with_no_run_sends_nothing(cloud):
    await cloud.owner.start()
    cloud.runner.calls.clear()
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert cloud.runner.calls == []


async def until(predicate):
    for _ in range(2000):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


@pytest.mark.asyncio
async def test_stop_mid_run_ends_the_run_as_stopped_and_syncs_once(
    cloud, fast_forwards
):
    await cloud.owner.start()
    cloud.runner.script("status", ended(state="running"))
    sha = cloud.push_from_cloud("stopped.txt")
    real_stop = cloud.runner.stop

    def stop(name):
        cloud.runner.script("status", ended(state="stopped", pushed={"commit": sha}))
        return real_stop(name)

    cloud.runner.stop = stop
    execution = asyncio.create_task(run(cloud))
    await until(lambda: "start_run" in methods(cloud.runner))
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert execution.done()
    outcome = execution.result()
    assert (outcome.status, outcome.reason) == ("cancelled", "stopped")
    assert methods(cloud.runner).count("stop") == 1
    assert fast_forwards == [sha]
    assert head(cloud.workspace) == sha
    assert cloud.note() is False


@pytest.mark.asyncio
async def test_stop_retries_a_409_then_reports_unclean(cloud):
    await cloud.owner.start()
    cloud.runner.script("status", ended(state="running"))
    cloud.runner.script("stop", RunnerRefused(409, "busy"))
    execution = asyncio.create_task(run(cloud))
    await until(lambda: "start_run" in methods(cloud.runner))
    assert await cloud.owner.stop() == CleanupOutcome(False, "cloud_unavailable")
    assert methods(cloud.runner).count("stop") == 4
    outcome = await asyncio.wait_for(execution, 5)
    assert (outcome.status, outcome.reason) == ("cancelled", "stopped")


@pytest.mark.asyncio
async def test_stop_is_unclean_when_the_run_does_not_return(cloud, monkeypatch):
    monkeypatch.setattr(CloudOwner, "STOP_WAIT_SECONDS", 0.05)
    await cloud.owner.start()
    cloud.runner.script("status", ended(state="running"))
    execution = asyncio.create_task(run(cloud))
    await until(lambda: "start_run" in methods(cloud.runner))
    assert await cloud.owner.stop() == CleanupOutcome(False, "cloud_unavailable")
    outcome = await asyncio.wait_for(execution, 5)
    assert (outcome.status, outcome.reason) == ("cancelled", "stopped")


@pytest.mark.parametrize("fault", [RunnerRefused(409, "busy"), RunnerDown("down")])
@pytest.mark.asyncio
async def test_an_unclean_stop_ends_the_execute_in_flight_as_stopped(
    cloud, monkeypatch, fast_forwards, fault
):
    await cloud.owner.start()
    cloud.runner.log = [event(1, 1, "system", {"session_id": "session-1"})]
    cloud.runner.script("status", ended(state="running"))
    cloud.runner.script("stop", fault)
    execution = asyncio.create_task(run(cloud))
    await until(lambda: 1 in cloud.runner.served)
    # A long poll interval from here: the end must not wait it out.
    monkeypatch.setattr(CloudOwner, "POLL_SECONDS", 1.0)
    assert await cloud.owner.stop() == CleanupOutcome(False, "cloud_unavailable")
    loop = asyncio.get_running_loop()
    began = loop.time()
    outcome = await asyncio.wait_for(execution, 5)
    assert loop.time() - began < 0.5
    assert (outcome.status, outcome.reason) == ("cancelled", "stopped")
    assert outcome.memory_delta is None
    assert outcome.provider_session_id == "session-1"
    assert cloud.note() is True
    assert fast_forwards == []


@pytest.mark.asyncio
async def test_stop_waits_one_budget_in_all(cloud, monkeypatch):
    monkeypatch.setattr(CloudOwner, "STOP_WAIT_SECONDS", 0.6)
    await cloud.owner.start()
    cloud.runner.script("status", ended(state="running"))
    real_start_run = cloud.runner.start_run

    def slow_start_run(*args, **kwargs):
        time.sleep(0.4)
        return real_start_run(*args, **kwargs)

    cloud.runner.start_run = slow_start_run
    execution = asyncio.create_task(run(cloud))
    await asyncio.sleep(0.01)
    loop = asyncio.get_running_loop()
    began = loop.time()
    assert await cloud.owner.stop() == CleanupOutcome(False, "cloud_unavailable")
    # Two separate waits would take about 0.4 + 0.6 s.
    assert loop.time() - began < 0.85
    outcome = await asyncio.wait_for(execution, 5)
    assert (outcome.status, outcome.reason) == ("cancelled", "stopped")


def stops(runner):
    return methods(runner).count("stop")


UNKNOWN_STARTS = [RunnerDown("no answer"), RunnerRefused(200, "malformed")]


@pytest.mark.parametrize("fault", UNKNOWN_STARTS)
@pytest.mark.asyncio
async def test_a_stop_after_a_run_start_with_no_known_outcome_asks_the_runner(
    cloud, fault
):
    await cloud.owner.start()
    cloud.runner.script("start_run", fault)
    outcome = await run(cloud)
    assert outcome.status == "error"
    assert stops(cloud.runner) == 0
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert [call for call in cloud.runner.calls if call[0] == "stop"] == [
        ("stop", cloud.name)
    ]


@pytest.mark.asyncio
async def test_an_unanswered_stop_after_an_unknown_start_asks_again_on_the_next_stop(
    cloud, capsys
):
    await cloud.owner.start()
    cloud.runner.script("start_run", RunnerDown("no answer"))
    outcome = await run(cloud)
    assert outcome.reason == "transport_error"
    cloud.runner.script("stop", RunnerDown("still down"))
    capsys.readouterr()
    assert await cloud.owner.stop() == CleanupOutcome(False, "cloud_unavailable")
    one_line(capsys, cloud, "stop: unclean: the runner did not answer")
    assert stops(cloud.runner) == 1
    cloud.runner.script("stop", {"state": "stopped"})  # the runner is back
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert stops(cloud.runner) == 2
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert stops(cloud.runner) == 2  # settled: nothing more is asked


def hang_stops(runner):
    """The runner's stop never answers until the returned event is set."""
    release = threading.Event()

    def stop(name):
        runner.calls.append(("stop", name))
        release.wait(5)
        return {"state": "stopped"}

    runner.stop = stop
    return release


@pytest.mark.parametrize("in_flight", [False, True])
@pytest.mark.asyncio
async def test_a_stop_the_runner_never_answers_is_unclean_within_the_budget(
    cloud, monkeypatch, capsys, in_flight
):
    monkeypatch.setattr(CloudOwner, "STOP_WAIT_SECONDS", 0.2)
    await cloud.owner.start()
    if in_flight:
        cloud.runner.script("status", ended(state="running"))
        execution = asyncio.create_task(run(cloud))
        await until(lambda: cloud.owner._run is not None)
    else:
        cloud.runner.script("start_run", RunnerDown("no answer"))
        await run(cloud)
    release = hang_stops(cloud.runner)
    capsys.readouterr()
    loop = asyncio.get_running_loop()
    began = loop.time()
    try:
        assert await cloud.owner.stop() == CleanupOutcome(False, "cloud_unavailable")
        assert loop.time() - began < 0.4
        one_line(capsys, cloud, "stop: unclean: the runner did not answer in time")
        assert stops(cloud.runner) == 1
    finally:
        release.set()
    if in_flight:
        outcome = await asyncio.wait_for(execution, 5)
        assert (outcome.status, outcome.reason) == ("cancelled", "stopped")
    # The flag stays set: the next stop asks again.
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert stops(cloud.runner) == 2


@pytest.mark.parametrize("in_flight", [False, True])
@pytest.mark.asyncio
async def test_409_pauses_end_within_the_stop_budget(
    cloud, monkeypatch, capsys, in_flight
):
    monkeypatch.setattr(CloudOwner, "STOP_WAIT_SECONDS", 0.2)
    await cloud.owner.start()
    if in_flight:
        cloud.runner.script("status", ended(state="running"))
        execution = asyncio.create_task(run(cloud))
        await until(lambda: cloud.owner._run is not None)
    else:
        cloud.runner.script("start_run", RunnerDown("no answer"))
        await run(cloud)
    monkeypatch.setattr(CloudOwner, "POLL_SECONDS", 1.0)
    cloud.runner.script("stop", RunnerRefused(409, "busy"))
    capsys.readouterr()
    loop = asyncio.get_running_loop()
    began = loop.time()
    assert await cloud.owner.stop() == CleanupOutcome(False, "cloud_unavailable")
    assert loop.time() - began < 0.4
    # The budget ran out in a pause after a 409: the runner did answer.
    one_line(capsys, cloud, "stop: unclean: the runner kept answering 409")
    assert stops(cloud.runner) == 1
    if in_flight:
        outcome = await asyncio.wait_for(execution, 5)
        assert (outcome.status, outcome.reason) == ("cancelled", "stopped")


@pytest.mark.parametrize(
    "answer, clean, why",
    [
        (RunnerRefused(404, "No such workspace"), True, None),
        (RunnerRefused(409, "busy"), False, "the runner kept answering 409"),
        (RunnerRefused(401, "who"), False, "the runner refused the stop: 401"),
    ],
)
@pytest.mark.asyncio
async def test_a_stop_with_no_run_in_flight_settles_on_200_or_404_only(
    cloud, capsys, answer, clean, why
):
    await cloud.owner.start()
    cloud.runner.script("start_run", RunnerDown("no answer"))
    await run(cloud)
    cloud.runner.script("stop", answer)
    capsys.readouterr()
    outcome = await cloud.owner.stop()
    assert outcome.clean is clean
    expected = 4 if answer.status == 409 else 1  # 409 has the same retries
    assert stops(cloud.runner) == expected
    if clean:
        assert cloud_lines(capsys) == []
    else:
        line = one_line(capsys, cloud, f"stop: unclean: {why}")
        assert "who" not in line and "busy" not in line
    await cloud.owner.stop()
    assert stops(cloud.runner) == expected + (0 if clean else expected)


@pytest.mark.parametrize("status", [302, 400, 409])
@pytest.mark.asyncio
async def test_a_refused_run_start_of_a_fresh_owner_sends_no_stop(cloud, status):
    # 3xx: the request never reached the runner. 409: the active run is not
    # this owner's, and the runner's stop takes no run number.
    await cloud.owner.start()
    assert cloud.note() is False
    cloud.runner.script("start_run", RunnerRefused(status, "refused"))
    outcome = await run(cloud)
    assert outcome.status == "error"
    assert cloud.note() is False  # nothing ran: the earlier value is back
    calls = len(cloud.runner.calls)
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert stops(cloud.runner) == 0
    assert len(cloud.runner.calls) == calls


@pytest.mark.parametrize("status", [302, 400, 409])
@pytest.mark.asyncio
async def test_a_refused_run_start_after_one_in_doubt_still_asks_for_a_stop(
    cloud, status
):
    await cloud.owner.start()
    cloud.runner.script("start_run", RunnerDown("no answer"))
    assert (await run(cloud)).reason == "transport_error"
    cloud.runner.script("start_run", RunnerRefused(status, "refused"))
    assert (await run(cloud)).status == "error"
    assert cloud.note() is True  # the first run may still be going
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert stops(cloud.runner) == 1


@pytest.mark.asyncio
async def test_a_run_that_settles_after_one_in_doubt_ends_the_doubt(cloud):
    await cloud.owner.start()
    cloud.runner.script("start_run", RunnerDown("no answer"))
    assert (await run(cloud)).reason == "transport_error"
    cloud.runner.script("start_run", 2)
    cloud.runner.script("status", ended(run=2, result="done"))
    assert (await run(cloud)).status == "success"
    calls = len(cloud.runner.calls)
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert len(cloud.runner.calls) == calls


@pytest.mark.asyncio
async def test_a_stop_after_a_later_run_ended_ours_sends_nothing(cloud):
    await cloud.owner.start()
    cloud.runner.script("status", ended(run=2, state="running"))
    outcome = await bounded(cloud)
    assert outcome.reason == "cloud_run_lost"
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert stops(cloud.runner) == 0  # the later run is not this owner's


@pytest.mark.asyncio
async def test_a_stop_after_the_workspace_went_away_sends_nothing(cloud):
    await cloud.owner.start()
    cloud.runner.script("status", RunnerRefused(404, "gone"))
    outcome = await bounded(cloud)
    assert outcome.reason == "cloud_run_lost"
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert stops(cloud.runner) == 0


@pytest.mark.asyncio
async def test_a_stop_after_polling_gave_up_on_an_outage_asks_the_runner(
    cloud, monkeypatch
):
    monkeypatch.setattr(CloudOwner, "OUTAGE_SECONDS", 0.05)
    await cloud.owner.start()
    cloud.runner.event_faults = [RunnerDown("down")] * 10_000
    outcome = await bounded(cloud)
    assert outcome.reason == "transport_error"
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert stops(cloud.runner) == 1


@pytest.mark.parametrize("answer", [ended(run=0, state="running"), {"state": "idle"}])
@pytest.mark.asyncio
async def test_a_stop_after_no_status_named_the_run_asks_the_runner(
    cloud, monkeypatch, answer
):
    # The runner answers, but never about this run: it may still be going.
    monkeypatch.setattr(CloudOwner, "OUTAGE_SECONDS", 0.05)
    await cloud.owner.start()
    cloud.runner.script("status", answer)
    outcome = await bounded(cloud)
    assert outcome.reason == "cloud_run_lost"
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert stops(cloud.runner) == 1


@pytest.mark.asyncio
async def test_a_stop_after_a_run_that_settled_sends_nothing(cloud):
    await cloud.owner.start()
    cloud.runner.script("status", ended(result="done"))
    outcome = await run(cloud)
    assert outcome.status == "success"
    calls = len(cloud.runner.calls)
    assert await cloud.owner.stop() == CleanupOutcome(True, None)
    assert len(cloud.runner.calls) == calls


@pytest.mark.asyncio
async def test_a_stop_during_a_run_start_that_then_fails_asks_the_runner(cloud):
    await cloud.owner.start()
    entered, release = threading.Event(), threading.Event()

    def start_run(name, prompt, **kwargs):
        cloud.runner.calls.append(("start_run", name))
        entered.set()
        release.wait(5)
        raise RunnerDown("timed out")

    cloud.runner.start_run = start_run
    execution = asyncio.create_task(run(cloud))
    try:
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        stopping = asyncio.create_task(cloud.owner.stop())
        await asyncio.sleep(0.05)
        assert not stopping.done()  # it waits for start_run's answer
    finally:
        release.set()
    assert await asyncio.wait_for(stopping, 3) == CleanupOutcome(True, None)
    assert (await execution).reason == "transport_error"
    assert stops(cloud.runner) == 1


@pytest.mark.asyncio
async def test_a_refused_stop_mid_run_asks_again_when_the_run_ends_unsettled(
    cloud, capsys
):
    await cloud.owner.start()
    cloud.runner.script("status", ended(state="running"))
    real_stop = cloud.runner.stop

    def stop(name):
        # The runner refuses the stop, and then its status too.
        cloud.runner.script("status", RunnerRefused(401, "who"))
        cloud.runner.script("stop", RunnerRefused(401, "who"))
        return real_stop(name)

    cloud.runner.stop = stop
    execution = asyncio.create_task(run(cloud))
    await until(lambda: "start_run" in methods(cloud.runner))
    capsys.readouterr()
    assert await cloud.owner.stop() == CleanupOutcome(False, "cloud_unavailable")
    assert (await asyncio.wait_for(execution, 5)).reason == "transport_error"
    assert stops(cloud.runner) == 2  # the one mid-run, then one after it ended
    lines = [line for line in cloud_lines(capsys) if "stop: unclean" in line]
    assert len(lines) == 1 and "the runner refused the stop: 401" in lines[0]


@pytest.mark.asyncio
async def test_healthy_only_between_start_and_stop(cloud):
    assert not cloud.owner.healthy
    await cloud.owner.start()
    assert cloud.owner.healthy
    await cloud.owner.stop()
    assert not cloud.owner.healthy


def hold(runner, method):
    """Make ``method`` block in its thread until released; returns (entered, release)."""
    entered, release = threading.Event(), threading.Event()
    real = getattr(runner, method)

    def held(*args, **kwargs):
        entered.set()
        release.wait(5)
        return real(*args, **kwargs)

    setattr(runner, method, held)
    return entered, release


async def stop_during(cloud, method):
    """Stop while start() is inside ``method``; returns (stop task, start task, release)."""
    entered, release = hold(cloud.runner, method)
    starting = asyncio.create_task(cloud.owner.start())
    try:
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        stopping = asyncio.create_task(cloud.owner.stop())
        await asyncio.sleep(0.05)
    except BaseException:
        release.set()
        raise
    return stopping, starting, release


@pytest.mark.asyncio
async def test_a_stop_during_the_first_status_waits_and_nothing_is_pushed_or_created(
    cloud, fast_forwards
):
    commit(cloud.workspace.worktree_path, "ahead.txt")  # a push would carry it
    stopping, starting, release = await stop_during(cloud, "status")
    try:
        assert not stopping.done()  # stop() waits for the start in flight
    finally:
        release.set()
    assert await asyncio.wait_for(stopping, 3) == CleanupOutcome(True, None)
    assert starting.done()
    with pytest.raises(RuntimeError, match="stopped before readiness"):
        starting.result()
    assert methods(cloud.runner) == ["status"]
    assert remote_tip(cloud.origin, cloud.workspace.branch) is None
    assert not cloud.owner.healthy
    note = cloud.workspace.common_git_dir / "plaza/cloud"
    assert not (note / f"{cloud.workspace.domain_id}.json").exists()
    assert fast_forwards == []


@pytest.mark.parametrize(
    "answer, unsynced",
    [
        (dict(state="idle"), False),
        (ended(result="done", pushError="fatal: denied"), True),
        (ended(state="lost"), True),
    ],
)
@pytest.mark.asyncio
async def test_a_stop_during_create_takes_nothing_and_leaves_a_true_note(
    cloud, fast_forwards, answer, unsynced
):
    from bridge.cloud_git import sync_before_start

    sync_before_start(cloud.workspace)  # the branch is on origin
    sha = cloud.push_from_cloud("cloud.txt")
    cloud.runner.script("create", dict(answer, pushed={"commit": sha}))
    stopping, starting, release = await stop_during(cloud, "create")
    try:
        assert not stopping.done()
    finally:
        release.set()
    assert await asyncio.wait_for(stopping, 3) == CleanupOutcome(True, None)
    with pytest.raises(RuntimeError, match="stopped before readiness"):
        starting.result()
    assert fast_forwards == []  # nothing further starts once the stop is seen
    assert cloud.note() is unsynced
    assert not cloud.owner.healthy


@pytest.mark.asyncio
async def test_a_stop_during_the_sync_creates_nothing(cloud, monkeypatch):
    from bridge.cloud_git import sync_before_start as real_sync

    entered, release = threading.Event(), threading.Event()

    def sync(workspace, **kwargs):
        entered.set()
        release.wait(5)
        return real_sync(workspace, **kwargs)

    monkeypatch.setattr(cloud_owner, "sync_before_start", sync)
    starting = asyncio.create_task(cloud.owner.start())
    try:
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        stopping = asyncio.create_task(cloud.owner.stop())
        await asyncio.sleep(0.05)
        assert not stopping.done()
    finally:
        release.set()
    assert await asyncio.wait_for(stopping, 3) == CleanupOutcome(True, None)
    with pytest.raises(RuntimeError, match="stopped before readiness"):
        starting.result()
    # The push already running may finish; the workspace is not created after it.
    assert methods(cloud.runner) == ["status"]
    assert cloud.note() is False  # the first status said nothing is unsynced
    assert not cloud.owner.healthy


@pytest.mark.asyncio
async def test_a_start_that_outlives_the_stop_budget_is_an_unclean_stop(
    cloud, monkeypatch
):
    monkeypatch.setattr(CloudOwner, "STOP_WAIT_SECONDS", 0.05)
    entered, release = hold(cloud.runner, "status")
    starting = asyncio.create_task(cloud.owner.start())
    try:
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        outcome = await cloud.owner.stop()
    finally:
        release.set()
    assert outcome == CleanupOutcome(False, "cloud_unavailable")
    with pytest.raises(RuntimeError, match="stopped before readiness"):
        await asyncio.wait_for(starting, 3)
    assert methods(cloud.runner) == ["status"]
    assert not cloud.owner.healthy


# The cloud note


@pytest.mark.asyncio
async def test_the_note_says_unsynced_during_a_run_and_synced_after_it(cloud):
    await cloud.owner.start()
    assert cloud.note() is False
    seen = []
    real_start_run = cloud.runner.start_run

    def start_run(*args, **kwargs):
        seen.append(cloud.note())
        return real_start_run(*args, **kwargs)

    cloud.runner.start_run = start_run
    sha = cloud.push_from_cloud("work.txt")
    cloud.runner.script("status", ended(result="done", pushed={"commit": sha}))
    outcome = await run(cloud)
    assert outcome.status == "success"
    assert seen == [True]
    assert cloud.note() is False


@pytest.mark.parametrize(
    "status",
    [
        ended(result="done", pushError="fatal: denied"),
        ended(state="lost", error="gone"),
        ended(state="failed", pushError="fatal: denied"),
    ],
)
@pytest.mark.asyncio
async def test_a_push_error_or_a_lost_run_leaves_the_note_unsynced(cloud, status):
    await cloud.owner.start()
    cloud.runner.script("status", status)
    await run(cloud)
    assert cloud.note() is True


@pytest.mark.asyncio
async def test_a_failed_fast_forward_after_a_run_is_cloud_sync_failed_with_the_answer_kept(
    cloud,
):
    await cloud.owner.start()
    commit(cloud.workspace.worktree_path, "local.txt")  # diverges from the cloud
    sha = cloud.push_from_cloud("cloud.txt")
    cloud.runner.script("status", ended(result="done", pushed={"commit": sha}))
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("error", "cloud_sync_failed")
    assert outcome.output == "done"
    assert cloud.note() is True


@pytest.mark.parametrize(
    "answer, reason",
    [
        (RunnerRefused(409, "busy"), "cloud_run_active"),
        (RunnerRefused(412, "diverged"), "cloud_sync_failed"),
        (RunnerRefused(413, "too large"), "sdk_error"),
    ],
)
@pytest.mark.parametrize("before", [False, True])
@pytest.mark.asyncio
async def test_a_refused_start_run_puts_the_note_back(cloud, answer, reason, before):
    if before:
        # The note was unsynced already (a lost run before); start keeps it so.
        cloud.runner.script("create", ended(state="lost"))
    await cloud.owner.start()
    assert cloud.note() is before
    cloud.runner.script("start_run", answer)
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("error", reason)
    assert cloud.note() is before
    assert "events" not in methods(cloud.runner)


@pytest.mark.asyncio
async def test_a_start_run_with_no_answer_is_transport_error_and_stays_unsynced(cloud):
    await cloud.owner.start()
    cloud.runner.script("start_run", RunnerDown("no answer"))
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("error", "transport_error")
    assert cloud.note() is True


# The bridge.cloud log: one stderr line per event, naming the department.


def cloud_lines(capsys):
    return [
        line for line in capsys.readouterr().err.splitlines() if "bridge.cloud " in line
    ]


def one_line(capsys, cloud, *parts):
    lines = cloud_lines(capsys)
    assert len(lines) == 1, lines
    assert f"bridge.cloud {cloud.workspace.domain_id}: " in lines[0]
    for part in parts:
        assert part in lines[0], (part, lines[0])
    return lines[0]


@pytest.mark.parametrize(
    "fault, parts",
    [
        ("down", ["start: runner did not answer: no answer"]),
        ("refused", ["start: runner refused: 422: No GitHub token"]),
        ("dirty", ["start: sync failed: dirty: "]),
    ],
)
@pytest.mark.asyncio
async def test_a_refused_start_is_one_line(cloud, capsys, fault, parts):
    if fault == "down":
        cloud.runner.script("status", RunnerDown("no answer"))
    elif fault == "refused":
        cloud.runner.script("create", RunnerRefused(422, "No GitHub token"))
    else:
        (cloud.workspace.worktree_path / "loose.txt").write_text("local\n")
    with pytest.raises(CloudStartRefused):
        await cloud.owner.start()
    one_line(capsys, cloud, *parts)


@pytest.mark.parametrize(
    "script, part",
    [
        (
            ("start_run", RunnerRefused(409, "busy")),
            "run start: runner refused: 409: busy",
        ),
        (("status", RunnerRefused(401, "who")), "run: runner refused: 401: who"),
        (
            ("status", ended(result="done", pushError="fatal: denied")),
            "run: push failed: fatal: denied",
        ),
        (
            ("status", ended(state="failed", error="max turns")),
            "run: run failed: max turns",
        ),
    ],
)
@pytest.mark.asyncio
async def test_a_refused_or_failed_run_is_one_line(cloud, capsys, script, part):
    await cloud.owner.start()
    capsys.readouterr()
    cloud.runner.script(*script)
    await run(cloud)
    one_line(capsys, cloud, part)


@pytest.mark.asyncio
async def test_a_failed_sync_after_a_run_is_one_line(cloud, capsys):
    await cloud.owner.start()
    commit(cloud.workspace.worktree_path, "local.txt")  # diverges from the cloud
    sha = cloud.push_from_cloud("cloud.txt")
    cloud.runner.script("status", ended(result="done", pushed={"commit": sha}))
    capsys.readouterr()
    await run(cloud)
    one_line(capsys, cloud, "run: sync failed: diverged: ")


@pytest.mark.asyncio
async def test_an_unclean_stop_is_one_line_with_why(cloud, capsys):
    await cloud.owner.start()
    cloud.runner.script("status", ended(state="running"))
    cloud.runner.script("stop", RunnerRefused(409, "busy"))
    execution = asyncio.create_task(run(cloud))
    await until(lambda: "start_run" in methods(cloud.runner))
    assert (await cloud.owner.stop()).clean is False
    await asyncio.wait_for(execution, 5)
    line = one_line(capsys, cloud, "stop: unclean: the runner kept answering 409")
    assert "busy" not in line


@pytest.mark.asyncio
async def test_a_start_that_does_not_settle_in_time_is_one_line(
    cloud, capsys, monkeypatch
):
    monkeypatch.setattr(CloudOwner, "STOP_WAIT_SECONDS", 0.05)
    entered, release = hold(cloud.runner, "status")
    starting = asyncio.create_task(cloud.owner.start())
    try:
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        assert (await cloud.owner.stop()).clean is False
    finally:
        release.set()
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(starting, 3)
    one_line(capsys, cloud, "stop: unclean: the start did not settle in time")


@pytest.mark.asyncio
async def test_a_run_that_does_not_end_in_time_is_one_line(cloud, capsys, monkeypatch):
    monkeypatch.setattr(CloudOwner, "STOP_WAIT_SECONDS", 0.05)
    await cloud.owner.start()
    cloud.runner.script("status", ended(state="running"))
    execution = asyncio.create_task(run(cloud))
    await until(lambda: "start_run" in methods(cloud.runner))
    assert (await cloud.owner.stop()).clean is False
    await asyncio.wait_for(execution, 5)
    one_line(capsys, cloud, "stop: unclean: the run did not end in time")


@pytest.mark.asyncio
async def test_a_clean_run_logs_nothing_and_never_the_result_or_the_prompt(
    cloud, capsys
):
    await cloud.owner.start()
    cloud.runner.script(
        "status", ended(state="failed", error="max turns", result="SECRET-RESULT")
    )
    await run(cloud, task="SECRET-PROMPT")
    err = capsys.readouterr().err
    assert "SECRET-RESULT" not in err and "SECRET-PROMPT" not in err
    cloud.runner.script("status", ended(result="done"))
    await run(cloud)
    assert cloud_lines(capsys) == []


@pytest.mark.asyncio
async def test_a_remote_text_is_one_line_cut_and_scrubbed(cloud, capsys):
    cloud.runner.secret = "s3cr3t-value"
    noisy = "first\nsecond https://user:pw@github.com/x s3cr3t-value " + "y" * 400
    cloud.runner.script("create", RunnerRefused(422, noisy))
    with pytest.raises(CloudStartRefused):
        await cloud.owner.start()
    line = one_line(capsys, cloud, "first second https://github.com/x *** y")
    assert "s3cr3t-value" not in line and "user:pw" not in line
    assert line.endswith("y" * 10) and "y" * 301 not in line


# A Start after the runner's last push failed or its run was lost


def fresh_owner(cloud):
    return CloudOwner(
        SimpleNamespace(domain_max_turns=40),
        cloud.workspace,
        None,
        None,
        runner=cloud.runner,
        conversation="key-2",
    )


HELD = [dict(pushError="fatal: unable to access"), dict(state="lost")]


@pytest.mark.parametrize("last", HELD)
@pytest.mark.asyncio
async def test_a_start_does_not_push_over_a_clone_whose_last_push_failed(
    cloud, capsys, last
):
    await cloud.owner.start()
    before = remote_tip(cloud.origin, cloud.workspace.branch)
    cloud.runner.script("status", ended(**dict(dict(result="done"), **last)))
    mark_cloud(cloud.workspace, unsynced=True)
    commit(cloud.workspace.worktree_path, "by-hand.txt")  # made on this machine
    capsys.readouterr()
    cloud.runner.calls.clear()
    owner = fresh_owner(cloud)
    with pytest.raises(CloudStartRefused) as refused:
        await owner.start()
    assert refused.value.code == "cloud_sync_failed"
    assert remote_tip(cloud.origin, cloud.workspace.branch) == before
    assert cloud.note() is True
    assert methods(cloud.runner) == ["status"]
    assert not owner.healthy
    one_line(capsys, cloud, "start: sync failed: unsynced: ", "did not arrive")


@pytest.mark.parametrize("last", HELD)
@pytest.mark.asyncio
async def test_a_branch_missing_on_origin_counts_as_ahead_after_a_failed_push(
    cloud, last
):
    assert remote_tip(cloud.origin, cloud.workspace.branch) is None
    cloud.runner.script("status", ended(**dict(dict(result="done"), **last)))
    with pytest.raises(CloudStartRefused) as refused:
        await cloud.owner.start()
    assert refused.value.code == "cloud_sync_failed"
    assert remote_tip(cloud.origin, cloud.workspace.branch) is None
    assert methods(cloud.runner) == ["status"]


@pytest.mark.parametrize("last", HELD)
@pytest.mark.parametrize("behind", [False, True])
@pytest.mark.asyncio
async def test_with_nothing_to_push_the_start_goes_on_after_a_failed_push(
    cloud, last, behind
):
    await cloud.owner.start()
    tip = remote_tip(cloud.origin, cloud.workspace.branch)
    if behind:
        tip = cloud.push_from_cloud("from-an-earlier-push.txt")
    cloud.runner.script("status", ended(**dict(dict(result="done"), **last)))
    cloud.runner.script("create", ended(**dict(dict(result="done"), **last)))
    owner = fresh_owner(cloud)
    await owner.start()
    assert owner.healthy
    assert head(cloud.workspace) == tip  # fast-forwarded when behind
    assert remote_tip(cloud.origin, cloud.workspace.branch) == tip
    assert cloud.note() is True  # a Start alone does not clear it


def note_file(cloud):
    workspace = cloud.workspace
    return workspace.common_git_dir / "plaza/cloud" / f"{workspace.domain_id}.json"


@pytest.fixture
def note_writes(monkeypatch, cloud):
    """Fail chosen writes of the cloud note (``fail``: 1 for the first after setup).

    The rename of the atomic replace fails, as a full or read-only disk would:
    the temporary is written and the old note, if any, stays in place.
    """
    state = SimpleNamespace(count=0, fail=set())
    real = os.replace
    target = note_file(cloud).name

    def replace(source, destination, *args, **kwargs):
        if destination == target and kwargs.get("dst_dir_fd") is not None:
            state.count += 1
            if state.count in state.fail:
                raise OSError(errno.ENOSPC, "No space left on device")
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    return state


@pytest.mark.asyncio
async def test_a_failed_last_note_write_of_a_run_leaves_the_note_unsynced(
    cloud, note_writes, capsys
):
    await cloud.owner.start()
    assert cloud.note() is False
    before = note_writes.count
    note_writes.fail = {before + 2}  # the Run's first write works, its last fails
    cloud.runner.log = [
        event(1, 1, "system", {"subtype": "init", "session_id": "session-1"}),
        event(2, 1, "result", {"subtype": "success"}),
    ]
    reply = json.dumps({"answer": "Ready.", "memory_delta": {"summary": "Checked"}})
    cloud.runner.script("status", ended(state="running"), ended(result=reply))
    capsys.readouterr()
    outcome = await run(cloud)
    # The outcome is what it would have been, project memory included.
    assert (outcome.status, outcome.reason) == ("success", "completed")
    assert outcome.memory_delta == {"summary": "Checked"}
    assert note_writes.count == before + 2
    assert cloud.note() is True  # the first write's value stayed in place
    one_line(capsys, cloud, "cloud note: sync failed: git_failed")


@pytest.fixture
def syncs(monkeypatch):
    seen = []
    real = cloud_owner.sync_before_start

    def counting(workspace, **kwargs):
        seen.append(kwargs)
        return real(workspace, **kwargs)

    monkeypatch.setattr(cloud_owner, "sync_before_start", counting)
    return seen


@pytest.mark.parametrize("last", HELD)
@pytest.mark.asyncio
async def test_a_held_start_whose_note_cannot_be_written_pushes_and_creates_nothing(
    cloud, capsys, note_writes, syncs, last
):
    from bridge.cloud_git import sync_before_start

    sync_before_start(cloud.workspace)  # the branch is on origin, nothing to push
    assert not note_file(cloud).exists()
    tip = remote_tip(cloud.origin, cloud.workspace.branch)
    cloud.runner.script("status", ended(**dict(dict(result="done"), **last)))
    note_writes.fail = {1}
    with pytest.raises(CloudStartRefused) as refused:
        await cloud.owner.start()
    assert refused.value.code == "cloud_sync_failed"
    assert methods(cloud.runner) == ["status"]
    assert syncs == []
    assert remote_tip(cloud.origin, cloud.workspace.branch) == tip
    assert not note_file(cloud).exists()
    assert not cloud.owner.healthy
    one_line(capsys, cloud, "start: sync failed: git_failed: cloud note not written")


@pytest.mark.parametrize("last", HELD)
@pytest.mark.asyncio
async def test_a_held_start_writes_the_note_before_the_create_that_fails(cloud, last):
    from bridge.cloud_git import sync_before_start

    sync_before_start(cloud.workspace)
    cloud.runner.script("status", ended(**dict(dict(result="done"), **last)))
    cloud.runner.script("create", RunnerDown("no answer"))
    with pytest.raises(CloudStartRefused) as refused:
        await cloud.owner.start()
    assert refused.value.code == "cloud_unavailable"
    assert cloud.note() is True


@pytest.mark.asyncio
async def test_a_first_cloud_start_that_fails_leaves_no_note(cloud):
    cloud.runner.script("status", RunnerRefused(404, "No such workspace"))
    cloud.runner.script("create", RunnerDown("no answer"))
    with pytest.raises(CloudStartRefused) as refused:
        await cloud.owner.start()
    assert refused.value.code == "cloud_unavailable"
    assert not note_file(cloud).exists()  # still free to start locally


@pytest.mark.parametrize("earlier", [True, False, None])
@pytest.mark.parametrize("write_fails", [False, True])
@pytest.mark.asyncio
async def test_a_failed_fast_forward_at_start_never_lowers_the_note(
    cloud, monkeypatch, capsys, note_writes, write_fails, earlier
):
    if earlier is not None:
        mark_cloud(cloud.workspace, unsynced=earlier)
    sha = "a" * 40

    def diverged(workspace, commit):
        raise CloudSyncError("diverged", "not a fast-forward")

    monkeypatch.setattr(cloud_owner, "fast_forward_to", diverged)
    cloud.runner.script("create", ended(state="idle", pushed={"commit": sha}))
    if write_fails:
        # The next note write is the one in the failed fast-forward branch.
        note_writes.fail = {note_writes.count + 1}
    capsys.readouterr()
    with pytest.raises(CloudStartRefused) as refused:
        await cloud.owner.start()
    assert refused.value.code == "cloud_sync_failed"
    lines = cloud_lines(capsys)
    noted = [line for line in lines if "cloud note: sync failed" in line]
    if write_fails:
        assert note_writes.fail <= set(range(1, note_writes.count + 1))
        assert len(noted) == 1
        # A failed write keeps what was on disk: never lowered, never raised.
        if earlier is None:
            assert not note_file(cloud).exists()
        else:
            assert cloud.note() is earlier
    else:
        assert noted == []
        assert cloud.note() is True


@pytest.mark.parametrize("last", HELD)
@pytest.mark.asyncio
async def test_a_create_answer_held_with_its_note_unwritten_is_refused(
    cloud, note_writes, last
):
    # The first status was clean; the create's answer is not (a run ended in
    # between). The last note write fails: the Start is refused, and the note
    # keeps what it said before, here nothing. Accepted: see the fix report.
    cloud.runner.script("create", ended(**dict(dict(result="done"), **last)))
    note_writes.fail = {1}
    with pytest.raises(CloudStartRefused) as refused:
        await cloud.owner.start()
    assert refused.value.code == "cloud_sync_failed"
    assert not note_file(cloud).exists()


@pytest.mark.parametrize(
    "answer",
    [
        RunnerRefused(202, "the runner did not name the run"),
        RunnerRefused(200, "malformed"),
    ],
)
@pytest.mark.parametrize("before", [False, True])
@pytest.mark.asyncio
async def test_a_2xx_refusal_from_start_run_leaves_the_note_unsynced(
    cloud, answer, before
):
    if before:
        cloud.runner.script("create", ended(state="lost"))
    await cloud.owner.start()
    cloud.runner.script("start_run", answer)
    outcome = await run(cloud)
    assert (outcome.status, outcome.reason) == ("error", "sdk_error")
    assert cloud.note() is True  # the run may have started
