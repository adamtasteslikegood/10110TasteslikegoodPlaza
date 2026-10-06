"""Regression fixtures for scripts/sprint_5_gate.py (PLZG-245).

The gate decides whether each Sprint 5 task counts as done, so a check that
stops checking has to turn something red. Every case here runs the real check
against a fake Jira and a temp directory -- no network, no credential, nothing
in the working tree touched -- and most assert that the gate FAILS.

Jira is faked at ``jira_get``, one layer below the checks, so pagination and
the chunked key lookup run for real. The two subprocess gates the script
delegates to (validate_specs.py, validate_delivery_coordinates.py) are stubbed:
they have their own matrix in tests/spec_enforcement_matrix.sh.

Stdlib only. Run: python3 -m unittest tests/test_sprint_5_gate.py
"""

import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sprint_5_gate as gate  # noqa: E402

TASK_KEYS = [f"PLZG-{n}" for n in range(230, 236)]
PAGE_SIZE = 2  # small, so every multi-issue search spans several pages


def issue(status="To Do", category="new", labels=(), sprint=None):
    return {
        "status": status,
        "category": category,
        "labels": list(labels),
        "sprint": sprint,
    }


def done(*labels):
    return issue("Done", "done", labels)


class FakeJira:
    """Answers the three JQL shapes the gate sends, a page at a time."""

    def __init__(self, issues, sprint_board=169):
        self.issues = issues
        self.sprint_board = sprint_board
        self.calls = []

    def match(self, jql):
        keyed = re.fullmatch(r"key in \((.*)\)", jql)
        if keyed:
            wanted = keyed.group(1).split(",")
            return [k for k in wanted if k in self.issues]
        in_sprint = re.fullmatch(r"sprint = (\d+)", jql)
        if in_sprint:
            sprint = int(in_sprint.group(1))
            return [k for k, v in self.issues.items() if v["sprint"] == sprint]
        if re.fullmatch(r"project = \w+ AND statusCategory != Done", jql):
            return [k for k, v in self.issues.items() if v["category"] != "done"]
        raise AssertionError(f"unexpected JQL: {jql}")

    def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        if endpoint.startswith("/rest/agile/1.0/sprint/"):
            return {
                "originBoardId": self.sprint_board,
                "name": "Sprint 5",
                "state": "future",
            }
        assert endpoint == "/rest/api/3/search/jql", endpoint
        keys = self.match(params["jql"])
        start = int(params.get("nextPageToken", 0))
        page = {
            "issues": [
                {
                    "key": k,
                    "fields": {
                        "status": {
                            "name": self.issues[k]["status"],
                            "statusCategory": {"key": self.issues[k]["category"]},
                        },
                        "labels": self.issues[k]["labels"],
                    },
                }
                for k in keys[start : start + PAGE_SIZE]
            ]
        }
        if start + PAGE_SIZE < len(keys):
            page["nextPageToken"] = str(start + PAGE_SIZE)
        return page


class GateCase(unittest.TestCase):
    """A passing world: plan, registry, evidence and board all agree."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "specs" / "meta").mkdir(parents=True)
        (self.root / "specs" / "evidence").mkdir()
        (self.root / "docs").mkdir()

        self.docs = {
            "ROADMAP": ("docs/roadmap.md", "ACTIVE"),
            "SPRINT-2-CHARTER": ("docs/s2.md", "HISTORICAL"),
            "SPRINT-3-CHARTER": ("docs/s3.md", "HISTORICAL"),
        }
        for path, _ in self.docs.values():
            (self.root / path).write_text(f"# {path}\n", encoding="utf-8")

        self.plan = {
            "jira": {"project": "PLZG", "board_id": 169, "sprint_id": 51},
            "governed_doc_limit": 3,
            "tasks": [
                {
                    "id": "T1",
                    "jira": "PLZG-230",
                    "acceptance_inputs": {"done": ["PLZG-1"], "wont_do": ["PLZG-2"]},
                },
                {"id": "T2", "jira": "PLZG-231"},
                {
                    "id": "T3",
                    "jira": "PLZG-232",
                    "acceptance_inputs": {
                        "must_stay_governed": list(self.docs),
                        "must_be_historical": [
                            "SPRINT-2-CHARTER",
                            "SPRINT-3-CHARTER",
                        ],
                    },
                },
                {"id": "T4", "jira": "PLZG-233"},
                {"id": "T5", "jira": "PLZG-234"},
                {"id": "T6", "jira": "PLZG-235"},
            ],
        }
        self.registry = {
            "documents": [
                {"doc_id": doc_id, "path": path, "status": status}
                for doc_id, (path, status) in self.docs.items()
            ]
        }
        self.triage = {
            "baseline_keys": ["PLZG-1", "PLZG-2", "PLZG-3", "PLZG-4", "PLZG-5"],
            "baseline_captured_at": "2026-10-06T00:00:00Z",
            "review_complete": True,
            "items": [
                self.row("PLZG-1", "done"),
                self.row("PLZG-2", "wont_do"),
                self.row("PLZG-3", "keep"),
                self.row("PLZG-4", "keep"),
                self.row("PLZG-5", "keep"),
            ],
        }
        self.crosscheck = {
            "reviewed_docs": [
                {
                    "doc_id": doc_id,
                    "contradiction": False,
                    "verified_against": ["git"],
                    "reviewed_blob": self.blob(path),
                }
                for doc_id, (path, _) in self.docs.items()
            ]
        }
        self.jira = FakeJira(
            {
                "PLZG-1": done(),
                "PLZG-2": done(gate.WONT_DO_LABEL),
                "PLZG-3": issue(),
                "PLZG-4": issue("In Progress", "indeterminate"),
                "PLZG-5": issue(),
                **{key: issue(sprint=51) for key in TASK_KEYS},
            }
        )
        self.governed = 3

        for name, value in {
            "REPO_ROOT": self.root,
            "PLAN_PATH": self.root / "specs" / "sprint-5-loop-plan.json",
            "REGISTRY_PATH": self.root / "specs" / "meta" / "doc-registry.json",
            "TRIAGE_PATH": self.root / "specs" / "evidence" / "sprint-5-triage.json",
            "CROSSCHECK_PATH": self.root
            / "specs"
            / "evidence"
            / "sprint-5-doc-crosscheck.json",
            "jira_get": lambda endpoint, params=None: self.jira.get(endpoint, params),
            "governed_count": lambda: self.governed,
            "check_snapshot": lambda: "flow snapshot fresh",
        }.items():
            patcher = mock.patch.object(gate, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def row(self, key, bucket):
        return {
            "key": key,
            "bucket": bucket,
            "reviewed_at": "2026-10-06",
            "reason": "reviewed",
        }

    def blob(self, path):
        result = subprocess.run(
            ["git", "hash-object", path],
            capture_output=True,
            text=True,
            cwd=self.root,
            check=True,
        )
        return result.stdout.strip()

    def write(self):
        charter = self.root / "specs" / "sprint-5-charter.md"
        charter.write_text("# Sprint 5\n", encoding="utf-8")
        files = {
            gate.PLAN_PATH: self.plan,
            gate.REGISTRY_PATH: self.registry,
            gate.TRIAGE_PATH: self.triage,
            gate.CROSSCHECK_PATH: self.crosscheck,
        }
        for path, data in files.items():
            path.write_text(json.dumps(data), encoding="utf-8")

    def passes(self, check, **kwargs):
        self.write()
        return check(self.plan, **kwargs)

    def fails(self, check, expected, **kwargs):
        self.write()
        with self.assertRaises(gate.GateFailure) as caught:
            check(self.plan, **kwargs)
        self.assertIn(expected, str(caught.exception))


class Baseline(GateCase):
    """If the passing world does not pass, every failing case below is vacuous."""

    def test_every_check_passes(self):
        for check in (gate.check_t1, gate.check_t2, gate.check_t3, gate.check_t4):
            with self.subTest(check=check.__name__):
                self.passes(check)
        self.passes(gate.check_t5)
        self.passes(gate.check_t6)


class Pagination(GateCase):
    def test_search_follows_every_page(self):
        found = gate.jira_search("project = PLZG AND statusCategory != Done")
        self.assertEqual(
            sorted(found), sorted(["PLZG-3", "PLZG-4", "PLZG-5"] + TASK_KEYS)
        )
        searches = [c for c in self.jira.calls if c[0] == "/rest/api/3/search/jql"]
        self.assertGreater(len(searches), 1)

    def test_an_untriaged_issue_on_the_last_page_is_still_found(self):
        self.jira.issues["PLZG-999"] = issue()
        self.fails(gate.check_t2, "open keys with no triage row: ['PLZG-999']")

    def test_a_response_without_an_issues_list_is_an_error_not_a_pass(self):
        with mock.patch.object(gate, "jira_get", lambda *a, **k: {}):
            with self.assertRaises(gate.GateError):
                gate.jira_search("sprint = 51")


class T1(GateCase):
    def test_key_not_done(self):
        self.jira.issues["PLZG-1"] = issue()
        self.fails(gate.check_t1, "not Done in Jira: ['PLZG-1']")

    def test_key_missing_from_jira(self):
        del self.jira.issues["PLZG-2"]
        self.fails(gate.check_t1, "not Done in Jira: ['PLZG-2']")

    def test_wont_do_without_the_label(self):
        self.jira.issues["PLZG-2"] = done()
        self.fails(gate.check_t1, "closed as Won't Do without")

    def test_done_carrying_the_wont_do_label(self):
        self.jira.issues["PLZG-1"] = done(gate.WONT_DO_LABEL)
        self.fails(gate.check_t1, "listed as done but labelled")


class T2(GateCase):
    def test_evidence_file_missing(self):
        self.write()
        gate.TRIAGE_PATH.unlink()
        with self.assertRaises(gate.GateFailure):
            gate.check_t2(self.plan)

    def test_baseline_key_with_no_row(self):
        self.triage["items"] = self.triage["items"][:-1]
        self.fails(gate.check_t2, "baseline keys with no triage row: ['PLZG-5']")

    def test_open_issue_filed_after_the_baseline(self):
        self.jira.issues["PLZG-900"] = issue("In Progress", "indeterminate")
        self.fails(gate.check_t2, "open keys with no triage row: ['PLZG-900']")

    def test_unrelated_issue_cannot_skip_triage_by_joining_the_sprint(self):
        self.jira.issues["PLZG-900"] = issue(sprint=51)
        self.fails(gate.check_t2, "open keys with no triage row: ['PLZG-900']")

    def test_task_ticket_outside_the_sprint_is_not_exempt(self):
        self.jira.issues["PLZG-231"] = issue(sprint=None)
        self.fails(gate.check_t2, "open keys with no triage row: ['PLZG-231']")

    def test_key_bucketed_twice(self):
        self.triage["items"].append(self.row("PLZG-3", "done"))
        self.fails(gate.check_t2, "keys bucketed more than once: ['PLZG-3']")

    def test_unknown_bucket(self):
        self.triage["items"][2]["bucket"] = "later"
        self.fails(gate.check_t2, "bucket must be one of")

    def test_row_without_a_reason(self):
        self.triage["items"][2]["reason"] = ""
        self.fails(gate.check_t2, "PLZG-3: reason missing")

    def test_keep_that_was_closed(self):
        self.jira.issues["PLZG-3"] = done()
        self.fails(gate.check_t2, "PLZG-3: bucketed keep but is Done")

    def test_done_that_is_still_open(self):
        self.jira.issues["PLZG-1"] = issue()
        self.fails(gate.check_t2, "PLZG-1: bucketed done but is To Do")

    def test_wont_do_without_the_label(self):
        self.jira.issues["PLZG-2"] = done()
        self.fails(gate.check_t2, "PLZG-2: bucketed wont_do without")

    def test_done_carrying_the_wont_do_label(self):
        self.jira.issues["PLZG-1"] = done(gate.WONT_DO_LABEL)
        self.fails(gate.check_t2, "PLZG-1: bucketed done but carries")

    def test_review_complete_is_only_demanded_at_close(self):
        self.triage["review_complete"] = False
        self.passes(gate.check_t2)
        self.fails(gate.check_t2, "review_complete must be true", require_complete=True)


class T3(GateCase):
    def test_over_the_limit(self):
        self.governed = 4
        self.fails(gate.check_t3, "4 governed documents, limit is 3")

    def test_protected_document_removed(self):
        self.registry["documents"] = self.registry["documents"][1:]
        self.fails(gate.check_t3, "must stay governed were removed: ['ROADMAP']")

    def test_charter_not_retired(self):
        self.registry["documents"][1]["status"] = "ACTIVE"
        self.fails(gate.check_t3, "not yet marked HISTORICAL: ['SPRINT-2-CHARTER']")

    def test_plan_without_a_protected_list(self):
        del self.plan["tasks"][2]["acceptance_inputs"]["must_stay_governed"]
        self.fails(gate.check_t3, "declares no must_stay_governed list")


class T4(GateCase):
    def test_document_with_no_row(self):
        self.crosscheck["reviewed_docs"] = self.crosscheck["reviewed_docs"][1:]
        self.fails(gate.check_t4, "no cross-check row: ['ROADMAP']")

    def test_duplicate_row_cannot_hide_a_contradiction(self):
        rows = self.crosscheck["reviewed_docs"]
        clean = copy.deepcopy(rows[0])
        rows[0]["contradiction"] = True
        rows.append(clean)
        self.fails(gate.check_t4, "cross-checked more than once: ['ROADMAP']")

    def test_contradiction_recorded(self):
        self.crosscheck["reviewed_docs"][0]["contradiction"] = True
        self.fails(gate.check_t4, "ROADMAP: contradiction must be recorded as false")

    def test_contradiction_omitted(self):
        del self.crosscheck["reviewed_docs"][0]["contradiction"]
        self.fails(gate.check_t4, "ROADMAP: contradiction must be recorded as false")

    def test_unknown_owning_system(self):
        self.crosscheck["reviewed_docs"][0]["verified_against"] = ["memory"]
        self.fails(gate.check_t4, "ROADMAP: verified_against must name")

    def test_document_changed_since_review(self):
        self.write()
        (self.root / "docs" / "roadmap.md").write_text("# edited\n", encoding="utf-8")
        with self.assertRaises(gate.GateFailure) as caught:
            gate.check_t4(self.plan)
        self.assertIn("changed since it was reviewed", str(caught.exception))


class T5(GateCase):
    def test_sprint_on_another_board(self):
        self.jira.sprint_board = 7
        self.fails(gate.check_t5, "belongs to board 7, not 169")

    def test_task_ticket_not_in_the_sprint(self):
        self.jira.issues["PLZG-233"] = issue(sprint=None)
        self.fails(gate.check_t5, "task tickets not in sprint 51: ['PLZG-233']")


class T6(GateCase):
    """Sprint close is only as strong as the weakest check it forwards."""

    def test_t1_failure_propagates(self):
        self.jira.issues["PLZG-1"] = issue()
        self.fails(gate.check_t6, "not Done in Jira")

    def test_t2_failure_propagates(self):
        self.jira.issues["PLZG-900"] = issue(sprint=51)
        self.fails(gate.check_t6, "open keys with no triage row")

    def test_t2_runs_in_close_mode(self):
        self.triage["review_complete"] = False
        self.fails(gate.check_t6, "review_complete must be true")

    def test_t3_failure_propagates(self):
        self.governed = 4
        self.fails(gate.check_t6, "limit is 3")

    def test_t4_failure_propagates(self):
        self.crosscheck["reviewed_docs"][0]["contradiction"] = True
        self.fails(gate.check_t6, "contradiction must be recorded as false")

    def test_snapshot_failure_propagates(self):
        def stale():
            raise gate.GateFailure("snapshot stale")

        with mock.patch.object(gate, "check_snapshot", stale):
            self.fails(gate.check_t6, "snapshot stale")


class Credential(unittest.TestCase):
    """./.env wins whole; a stale shell value never fills a gap in it."""

    def resolve(self, file_env, shell):
        with mock.patch.object(gate, "read_dotenv", lambda: file_env):
            with mock.patch.dict(gate.os.environ, shell, clear=True):
                return gate.resolve_credential()

    def test_file_base64_beats_a_shell_email_and_token(self):
        shell = {"ATLASSIAN_EMAIL": "old@example.com", "ATLASSIAN_API_TOKEN": "old"}
        file_env = {"ATLASSIAN_URL": "site", "ATLASSIAN_API_TOKEN_BASE64": "FILE"}
        self.assertEqual(self.resolve(file_env, shell), ("site", "FILE"))

    def test_file_pair_beats_a_shell_base64(self):
        file_env = {"ATLASSIAN_EMAIL": "a@example.com", "ATLASSIAN_API_TOKEN": "t"}
        shell = {"ATLASSIAN_URL": "site", "ATLASSIAN_API_TOKEN_BASE64": "SHELL"}
        expected = gate.base64.b64encode(b"a@example.com:t").decode()
        self.assertEqual(self.resolve(file_env, shell), ("site", expected))

    def test_half_a_file_pair_is_not_completed_from_the_shell(self):
        file_env = {"ATLASSIAN_EMAIL": "a@example.com"}
        shell = {"ATLASSIAN_API_TOKEN": "stale", "ATLASSIAN_API_TOKEN_BASE64": "SHELL"}
        self.assertEqual(self.resolve(file_env, shell)[1], "SHELL")

    def test_shell_is_the_fallback_without_a_file(self):
        shell = {"ATLASSIAN_URL": "site", "ATLASSIAN_API_TOKEN_BASE64": "SHELL"}
        self.assertEqual(self.resolve({}, shell), ("site", "SHELL"))

    def test_no_credential_anywhere_is_could_not_run(self):
        with mock.patch.object(gate, "resolve_credential", lambda: (None, None)):
            with mock.patch.object(gate, "_authenticated", False):
                with self.assertRaises(gate.GateError):
                    gate.jira_get("/rest/api/3/search/jql", {"jql": "sprint = 51"})


class ExitCodes(GateCase):
    """0 passed, 1 the answer is no, 2 the question could not be asked."""

    def run_main(self, name):
        self.write()
        with mock.patch.object(gate.sys, "stderr"), mock.patch.object(
            gate.sys, "stdout"
        ):
            return gate.main(["sprint_5_gate.py", name])

    def test_pass_is_zero(self):
        self.assertEqual(self.run_main("t1"), 0)

    def test_failure_is_one(self):
        self.jira.issues["PLZG-1"] = issue()
        self.assertEqual(self.run_main("t1"), 1)

    def test_could_not_run_is_two(self):
        def unreachable(endpoint, params=None):
            raise gate.GateError("Jira answered 401")

        with mock.patch.object(gate, "jira_get", unreachable):
            self.assertEqual(self.run_main("t1"), 2)

    def test_unknown_subcommand_is_two(self):
        self.assertEqual(self.run_main("t9"), 2)


if __name__ == "__main__":
    unittest.main()
