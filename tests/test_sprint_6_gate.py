"""Regression fixtures for scripts/sprint_6_gate.py (PLZG-257).

The gate decides whether each Sprint 6 task counts as done, so a check that
stops checking has to turn something red. Most cases here assert that the gate
FAILS: on a room nobody built, a smoke test that skipped a room, a transcript
that is two requests rather than a conversation, and a ticket opened and closed
in the same breath.

Godot is faked at ``run_godot`` and Jira at ``jira_get``; the live runner is a
real subprocess writing into a temp directory. No network, no credential, no
engine, nothing in the working tree touched.

Stdlib only. Run: python3 -m unittest tests/test_sprint_6_gate.py
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sprint_5_gate as base  # noqa: E402
import sprint_6_gate as gate  # noqa: E402

ROOMS = ["lobby", "server-room", "war-room"]
NONCE = "kestrel-4417"
TRANSCRIPT = "specs/evidence/transcript.json"
PROBE_OK = (
    "PROBE rooms: lobby,server-room,war-room\n"
    "PROBE doorways: server-room,war-room\n"
    "PROBE locked_corridors: east,north\n"
)


SMOKE_OK = (
    "SMOKE rooms_reachable: " + ",".join(ROOMS) + "\n"
    "SMOKE corridors_blocked: east,north\n"
)


def turns(recalled=NONCE, second_sent="What word did I give you?"):
    return {
        "turns": [
            {"sent": f"Remember this word: {NONCE}", "received": "Noted."},
            {"sent": second_sent, "received": f"You gave me {recalled}."},
        ]
    }


def history(to_status, when):
    return {"created": when, "items": [{"field": "status", "toString": to_status}]}


class GateCase(unittest.TestCase):
    """A passing world: plan, scene output, transcript and board all agree."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "specs" / "evidence").mkdir(parents=True)
        (self.root / "scripts").mkdir()
        for module in (gate, base):
            patcher = mock.patch.object(module, "REPO_ROOT", self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.plan = {
            "jira": {"project": "PLZG", "board_id": 169, "sprint_id": 120},
            "tasks": [
                {
                    "id": "T2",
                    "jira": "PLZG-2",
                    "acceptance_inputs": {"probe_scene": "probe.tscn", "rooms": ROOMS},
                },
                {
                    "id": "T3",
                    "jira": "PLZG-3",
                    "acceptance_inputs": {
                        "start_room": "lobby",
                        "min_locked_corridors": 2,
                    },
                },
                {
                    "id": "T4",
                    "jira": "PLZG-4",
                    "acceptance_inputs": {"smoke_scene": "smoke.tscn"},
                },
                {
                    "id": "T5",
                    "jira": "PLZG-5",
                    "acceptance_inputs": {
                        "live_runner": "scripts/live.py",
                        "transcript": TRANSCRIPT,
                        "clients": ["godot", "python"],
                        "simulated_reply": "Hello from the bridge.",
                    },
                },
                {
                    "id": "T6",
                    "jira": "PLZG-6",
                    "acceptance_inputs": {"max_defects": 3, "defects": []},
                },
                {"id": "T7", "jira": "PLZG-7"},
            ],
        }
        self.transcript = {
            "captured_at": "2026-10-08T12:00:00+00:00",
            "nonce": NONCE,
            "owner_read": False,
            "clients": {"godot": turns(), "python": turns()},
        }
        self.godot = {"probe.tscn": (0, PROBE_OK), "smoke.tscn": (0, "")}
        patcher = mock.patch.object(
            gate, "run_godot", side_effect=lambda scene: self.godot[scene]
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_transcript(self):
        (self.root / TRANSCRIPT).write_text(
            json.dumps(self.transcript), encoding="utf-8"
        )

    def write_runner(self, exit_code, writes_transcript=True):
        """A stand-in runner. A real one stamps the transcript it writes."""
        stamp = (
            "import datetime, json, pathlib\n"
            f"p = pathlib.Path({TRANSCRIPT!r})\n"
            "if p.is_file():\n"
            "    d = json.loads(p.read_text())\n"
            "    now = datetime.datetime.now(datetime.timezone.utc)\n"
            "    d['captured_at'] = now.isoformat()\n"
            "    p.write_text(json.dumps(d))\n"
        )
        (self.root / "scripts" / "live.py").write_text(
            (stamp if writes_transcript else "")
            + f"import sys\nsys.exit({exit_code})\n",
            encoding="utf-8",
        )

    def assertFails(self, check, fragment):
        with self.assertRaises(base.GateFailure) as caught:
            check(copy.deepcopy(self.plan))
        self.assertIn(fragment, str(caught.exception))


class RoomChecks(GateCase):
    def test_all_rooms_present_passes(self):
        self.assertIn("3 room(s)", gate.check_t2(self.plan))

    def test_unbuilt_room_fails(self):
        self.godot["probe.tscn"] = (0, PROBE_OK.replace(",war-room\n", "\n", 1))
        self.assertFails(gate.check_t2, "war-room")

    def test_probe_that_printed_nothing_fails(self):
        self.godot["probe.tscn"] = (0, "Godot Engine v4\n")
        self.assertFails(gate.check_t2, "PROBE rooms")

    def test_probe_crash_fails(self):
        self.godot["probe.tscn"] = (1, "SCRIPT ERROR\n")
        self.assertFails(gate.check_t2, "exited 1")

    def test_room_without_doorway_fails(self):
        self.godot["probe.tscn"] = (
            0,
            PROBE_OK.replace("doorways: server-room,war-room", "doorways: war-room"),
        )
        self.assertFails(gate.check_t3, "server-room")

    def test_start_room_needs_no_doorway(self):
        self.assertIn("2 doorway(s)", gate.check_t3(self.plan))

    def test_too_few_locked_corridors_fails(self):
        self.godot["probe.tscn"] = (0, PROBE_OK.replace("east,north", "east"))
        self.assertFails(gate.check_t3, "need 2")


class SmokeCheck(GateCase):
    def test_green_and_every_room_walked_passes(self):
        self.godot["smoke.tscn"] = (0, SMOKE_OK)
        self.assertIn("2 locked corridor(s) held", gate.check_t4(self.plan))

    def test_corridor_locked_in_name_only_fails(self):
        # Declared locked, and the body walked straight through one of them.
        self.godot["smoke.tscn"] = (0, SMOKE_OK.replace("east,north", "east"))
        self.assertFails(gate.check_t4, "need 2")

    def test_blocked_corridors_the_scene_never_declared_fail(self):
        self.godot["smoke.tscn"] = (0, SMOKE_OK.replace("east,north", "x,y"))
        self.assertFails(gate.check_t4, "does not declare locked")

    def test_smoke_that_never_tried_a_locked_corridor_fails(self):
        self.godot["smoke.tscn"] = (0, SMOKE_OK.split("\n")[0])
        self.assertFails(gate.check_t4, "corridors_blocked")

    def test_green_smoke_that_names_no_rooms_fails(self):
        # Sprint 5's smoke test: exit 0, and it never walked anywhere.
        self.assertFails(gate.check_t4, "rooms_reachable")

    def test_green_smoke_that_skipped_a_room_fails(self):
        self.godot["smoke.tscn"] = (0, "SMOKE rooms_reachable: lobby,server-room")
        self.assertFails(gate.check_t4, "war-room")

    def test_red_smoke_fails_even_if_it_names_every_room(self):
        self.godot["smoke.tscn"] = (1, "SMOKE rooms_reachable: " + ",".join(ROOMS))
        self.assertFails(gate.check_t4, "exited 1")


class TranscriptCheck(GateCase):
    def test_conversation_passes(self):
        self.write_transcript()
        self.assertIn("nonce recalled", gate.check_transcript(self.plan))

    def test_nonce_not_recalled_fails(self):
        self.transcript["clients"]["godot"] = turns(recalled="something else")
        self.write_transcript()
        self.assertFails(gate.check_transcript, "did not recall")

    def test_nonce_handed_over_in_turn_two_fails(self):
        self.transcript["clients"]["python"] = turns(second_sent=f"Say {NONCE}")
        self.write_transcript()
        self.assertFails(gate.check_transcript, "proves nothing")

    def test_missing_client_fails(self):
        # Godot alone would pass a bridge that had learned about Godot (D-005).
        del self.transcript["clients"]["python"]
        self.write_transcript()
        self.assertFails(gate.check_transcript, "'python'")

    def test_plan_naming_no_clients_fails(self):
        # An empty list checks nothing, and nothing must not read as a pass.
        self.plan["tasks"][3]["acceptance_inputs"]["clients"] = []
        self.write_transcript()
        self.assertFails(gate.check_transcript, "two distinct clients")

    def test_plan_naming_one_client_fails(self):
        self.plan["tasks"][3]["acceptance_inputs"]["clients"] = ["godot", "godot"]
        self.write_transcript()
        self.assertFails(gate.check_transcript, "two distinct clients")

    def test_simulated_reply_fails(self):
        self.transcript["clients"]["godot"]["turns"][0][
            "received"
        ] = "Hello from the bridge."
        self.write_transcript()
        self.assertFails(gate.check_transcript, "simulated")

    def test_empty_reply_fails(self):
        self.transcript["clients"]["godot"]["turns"][0]["received"] = "  "
        self.write_transcript()
        self.assertFails(gate.check_transcript, "no reply")


class LiveCheck(GateCase):
    def test_runner_not_built_yet_fails(self):
        self.assertFails(gate.check_live, "does not exist yet")

    def test_runner_exit_2_is_could_not_run_not_failed(self):
        # No credential is not evidence the bridge is broken -- and must never
        # be mistaken for evidence that it works.
        self.write_runner(2)
        with self.assertRaises(base.GateError):
            gate.check_live(self.plan)

    def test_runner_failure_fails(self):
        self.write_runner(1)
        self.write_transcript()
        self.assertFails(gate.check_live, "failed")

    def test_runner_success_still_needs_a_real_transcript(self):
        self.write_runner(0)
        self.transcript["clients"]["godot"] = turns(recalled="nope")
        self.write_transcript()
        self.assertFails(gate.check_live, "did not recall")

    def test_runner_that_wrote_nothing_is_not_judged_on_an_old_transcript(self):
        # Exit 0, a perfect transcript on disk -- left there by an earlier run.
        self.write_runner(0, writes_transcript=False)
        self.transcript["captured_at"] = "2026-08-20T12:00:00+00:00"
        self.write_transcript()
        self.assertFails(gate.check_live, "before this run started")

    def test_t5_is_not_judged_on_an_old_transcript_either(self):
        self.write_runner(1, writes_transcript=False)
        self.transcript["captured_at"] = "2026-08-20T12:00:00+00:00"
        self.write_transcript()
        self.assertFails(gate.check_t5, "before this run started")

    def test_runner_that_hangs_fails(self):
        (self.root / "scripts" / "live.py").write_text(
            "import time\ntime.sleep(30)\n", encoding="utf-8"
        )
        with mock.patch.object(gate, "LIVE_TIMEOUT_SECONDS", 0.2):
            self.assertFails(gate.check_live, "did not exit")

    def test_t5_passes_on_real_replies_before_the_bridge_has_history(self):
        # The stateless bridge: the runner exits 1 because turn 2 forgot.
        self.write_runner(1)
        self.transcript["clients"]["godot"] = turns(recalled="nothing")
        self.transcript["clients"]["python"] = turns(recalled="nothing")
        self.write_transcript()
        self.assertIn("recall not asked", gate.check_t5(self.plan))

    def test_t5_still_refuses_the_simulated_reply(self):
        self.write_runner(1)
        self.transcript["clients"]["godot"]["turns"][1][
            "received"
        ] = "Hello from the bridge."
        self.write_transcript()
        self.assertFails(gate.check_t5, "simulated")

    def test_t5_without_a_credential_could_not_run(self):
        self.write_runner(2)
        with self.assertRaises(base.GateError):
            gate.check_t5(self.plan)

    def test_fourth_defect_fails_t6(self):
        self.plan["tasks"][4]["acceptance_inputs"]["defects"] = [{}] * 4
        self.assertFails(gate.check_t6, "file and escalate")

    def test_unrecorded_defects_list_fails_t6(self):
        del self.plan["tasks"][4]["acceptance_inputs"]["defects"]
        self.assertFails(gate.check_t6, "even if []")


class T1Check(GateCase):
    """The sprint Jira holds is the sprint the plan describes."""

    KEYS = ["PLZG-2", "PLZG-3", "PLZG-4", "PLZG-5", "PLZG-6", "PLZG-7"]

    def setUp(self):
        super().setUp()
        (self.root / "specs" / "meta").mkdir()
        registry = self.root / "specs" / "meta" / "doc-registry.json"
        registry.write_text(
            json.dumps({"documents": [{"doc_id": "CHARTER"}]}), encoding="utf-8"
        )
        (self.root / "specs" / "charter.md").write_text("#\n", encoding="utf-8")
        self.plan["jira"]["epic"] = "PLZG-1"
        self.plan["tasks"].insert(
            0,
            {
                "id": "T1",
                "acceptance_inputs": {
                    "files": ["specs/charter.md"],
                    "charter_doc_id": "CHARTER",
                },
            },
        )
        self.board = 169
        self.in_sprint = set(self.KEYS)
        self.under_epic = set(self.KEYS)
        fakes = {
            "REGISTRY_PATH": registry,
        }
        for name, value in fakes.items():
            patcher = mock.patch.object(gate, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, fake in (
            ("governed_count", lambda: 20),
            ("jira_get", lambda endpoint, params=None: self.sprint()),
            ("jira_search", self.search),
        ):
            patcher = mock.patch.object(base, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sprint(self):
        return {"originBoardId": self.board, "name": "Sprint 6", "state": "future"}

    def search(self, jql):
        return self.in_sprint if jql.startswith("sprint = ") else self.under_epic

    def test_plan_and_board_agree_passes(self):
        self.assertIn("all 6 task ticket(s)", gate.check_t1(self.plan))

    def test_sprint_on_another_board_fails(self):
        self.board = 12
        self.assertFails(gate.check_t1, "belongs to board 12")

    def test_ticket_missing_from_the_sprint_fails(self):
        self.in_sprint.discard("PLZG-4")
        self.assertFails(gate.check_t1, "not in sprint 120: ['PLZG-4']")

    def test_ticket_outside_the_epic_fails(self):
        self.under_epic.discard("PLZG-6")
        self.assertFails(gate.check_t1, "not under epic PLZG-1: ['PLZG-6']")

    def test_unregistered_charter_fails(self):
        self.plan["tasks"][0]["acceptance_inputs"]["charter_doc_id"] = "OTHER"
        self.assertFails(gate.check_t1, "not in the doc registry")

    def test_missing_file_fails(self):
        (self.root / "specs" / "charter.md").unlink()
        self.assertFails(gate.check_t1, "is missing")


class AcceptanceCheck(GateCase):
    """T7's reading of the transcript: committed, current, and owner-accepted."""

    def setUp(self):
        super().setUp()
        self.plan["jira"]["window"] = {"start": "2026-10-07T16:00:00+00:00"}
        self.transcript["owner_read"] = True
        self.tracked = 0
        patcher = mock.patch.object(
            gate.subprocess,
            "run",
            side_effect=lambda *a, **k: mock.Mock(returncode=self.tracked),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_committed_current_and_accepted_passes(self):
        self.write_transcript()
        self.assertIn("accepted by the owner", gate.check_acceptance(self.plan))

    def test_uncommitted_transcript_fails(self):
        self.tracked = 1
        self.write_transcript()
        self.assertFails(gate.check_acceptance, "not committed")

    def test_transcript_from_before_the_sprint_fails(self):
        self.transcript["captured_at"] = "2026-08-20T12:00:00+00:00"
        self.write_transcript()
        self.assertFails(gate.check_acceptance, "before this sprint")

    def test_transcript_after_the_jira_end_date_still_passes(self):
        # The end date is Jira's required field, not a promise (charter 1.3).
        self.plan["jira"]["window"]["end"] = "2026-10-21T16:00:00+00:00"
        self.transcript["captured_at"] = "2026-11-02T12:00:00+00:00"
        self.write_transcript()
        self.assertIn("accepted by the owner", gate.check_acceptance(self.plan))

    def test_transcript_the_owner_has_not_read_fails(self):
        self.transcript["owner_read"] = False
        self.write_transcript()
        self.assertFails(gate.check_acceptance, "owner_read")


class FlowCheck(GateCase):
    KEYS = ["PLZG-2", "PLZG-3", "PLZG-4", "PLZG-5", "PLZG-6"]

    def setUp(self):
        super().setUp()
        self.status = {k: "done" for k in self.KEYS}
        self.logs = {
            k: [
                history("In Progress", "2026-10-08T09:00:00.000-0700"),
                history("Done", "2026-10-08T11:30:00.000-0700"),
            ]
            for k in self.KEYS
        }
        for name, fake in (("jira_get", self.jira_get),):
            patcher = mock.patch.object(base, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def jira_get(self, endpoint, params=None):
        if endpoint.endswith("/changelog"):
            key = endpoint.split("/")[-2]
            return {"values": self.logs[key], "isLast": True}
        assert endpoint == "/rest/api/3/search/jql", endpoint
        wanted = params["jql"][len("key in (") : -1].split(",")
        return {
            "issues": [
                {
                    "key": k,
                    "fields": {
                        "status": {
                            "name": self.status[k],
                            "statusCategory": {"key": self.status[k]},
                        },
                        "labels": [],
                    },
                }
                for k in wanted
            ]
        }

    def test_real_cycle_times_pass(self):
        # T7's own ticket is open while T7 runs, so it is not among the five.
        self.assertIn("5 task ticket(s)", gate.check_flow(self.plan))

    def test_open_ticket_fails(self):
        self.status["PLZG-4"] = "new"
        self.assertFails(gate.check_flow, "PLZG-4")

    def test_bookkeeping_transition_fails(self):
        self.logs["PLZG-3"] = [
            history("In Progress", "2026-10-08T09:00:00.000-0700"),
            history("Done", "2026-10-08T09:04:00.000-0700"),
        ]
        self.assertFails(gate.check_flow, "bookkeeping")

    def test_never_started_fails(self):
        self.logs["PLZG-5"] = [history("Done", "2026-10-08T11:30:00.000-0700")]
        self.assertFails(gate.check_flow, "never entered In Progress")

    def test_reopened_ticket_is_measured_to_its_last_close(self):
        self.logs["PLZG-6"] = [
            history("In Progress", "2026-10-08T09:00:00.000-0700"),
            history("Done", "2026-10-08T09:10:00.000-0700"),
            history("In Progress", "2026-10-08T09:20:00.000-0700"),
            history("Done", "2026-10-08T12:00:00.000-0700"),
        ]
        self.assertIn("5 task ticket(s)", gate.check_flow(self.plan))


if __name__ == "__main__":
    unittest.main()
