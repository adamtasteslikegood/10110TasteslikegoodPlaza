"""Execute workflow scripts against Git graphs and safe reporting fixtures."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/claude-review.yml"


def workflow_script(step_id):
    lines = WORKFLOW.read_text().splitlines()
    for start, line in enumerate(lines):
        if line.strip() != f"id: {step_id}":
            continue
        for index in range(start + 1, len(lines)):
            if lines[index].strip() == "run: |":
                body = []
                for item in lines[index + 1 :]:
                    if item and not item.startswith("          "):
                        break
                    body.append(item[10:] if item else "")
                return "\n".join(body)
    return ""


class ReviewScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Scope Test")
        self.git("config", "user.email", "scope@example.invalid")
        self.base = self.commit("base")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text("#!/bin/sh\necho unexpected-history-lookup >&2\nexit 99\n")
        gh.chmod(0o755)

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.repo, text=True, stderr=subprocess.PIPE
        ).strip()

    def commit(self, name):
        (self.repo / name).write_text(name)
        self.git("add", name)
        self.git("commit", "-qm", name)
        return self.git("rev-parse", "HEAD")

    def run_scope(self, action="synchronize", before=None):
        script = workflow_script("scope")
        self.assertTrue(script, "workflow has no scope-selection step")
        output = self.root / "outputs"
        env = dict(os.environ)
        env.update(
            PATH=str(self.bin) + os.pathsep + env["PATH"],
            ACTION=action,
            HEAD_SHA=self.git("rev-parse", "HEAD"),
            BEFORE=self.base if before is None else before,
            GITHUB_OUTPUT=str(output),
        )
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=self.repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("unexpected-history-lookup", result.stderr)
        return dict(line.split("=", 1) for line in output.read_text().splitlines())

    def test_multi_commit_push_includes_all_new_commits(self):
        self.commit("first-in-push")
        head = self.commit("second-in-push")
        result = self.run_scope()
        self.assertEqual(result["mode"], "delta")
        self.assertEqual(result["range"], f"{self.base}..{head}")

    def test_failed_prior_review_does_not_replay_earlier_push(self):
        previous = self.commit("earlier-failed-review")
        head = self.commit("new-push")
        self.assertEqual(
            self.run_scope(before=previous)["range"], f"{previous}..{head}"
        )

    def test_rewritten_history_uses_net_diff_when_both_objects_exist(self):
        self.git("checkout", "--orphan", "replacement")
        self.git("rm", "-rf", ".")
        head = self.commit("replacement")
        self.assertEqual(self.run_scope()["range"], f"{self.base}..{head}")

    def test_merge_push_uses_delta(self):
        self.git("checkout", "-qb", "side", self.base)
        self.commit("side")
        self.git("checkout", "main")
        self.commit("main-change")
        self.git("merge", "--no-ff", "side", "-m", "merge side")
        self.assertEqual(self.run_scope()["mode"], "delta")

    def test_invalid_missing_zero_and_unavailable_before_fall_back_with_reason(self):
        self.commit("new-push")
        for before in ("", "0" * 40, "f" * 40, "bad; touch injected"):
            with self.subTest(before=before):
                result = self.run_scope(before=before)
                self.assertEqual(result["mode"], "full")
                self.assertEqual(result["range"], "")
                self.assertTrue(result["reason"])
        self.assertFalse((self.repo / "injected").exists())

    def test_non_push_events_review_whole_pr(self):
        self.commit("new-push")
        for action in ("opened", "ready_for_review", "labeled", ""):
            with self.subTest(action=action):
                result = self.run_scope(action=action)
                self.assertEqual(result["mode"], "full")

    def test_identical_before_and_head_skips_model_call(self):
        self.assertEqual(self.run_scope()["mode"], "skip")


class ReviewModelTests(unittest.TestCase):
    def test_only_owner_approved_reviewer_models_are_selected(self):
        script = workflow_script("pick")
        with tempfile.TemporaryDirectory() as root:
            for configured, expected in (
                ("", "claude-sonnet-5-5"),
                ("claude-sonnet-5-5", "claude-sonnet-5-5"),
                ("claude-opus-4-6", "claude-opus-4-6"),
                ("claude-opus-4-7", "claude-sonnet-5-5"),
                ("bad\nmodel", "claude-sonnet-5-5"),
            ):
                with self.subTest(configured=configured):
                    output = Path(root) / "output"
                    output.write_text("")
                    result = subprocess.run(
                        ["bash", "-e", "-o", "pipefail", "-c", script],
                        env=dict(
                            os.environ,
                            CLAUDE_REVIEW_MODEL=configured,
                            GITHUB_OUTPUT=str(output),
                        ),
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(output.read_text(), f"model={expected}\n")


class ReviewPolicyTests(unittest.TestCase):
    def test_policy_uses_separate_limits_and_fresh_private_config(self):
        script = workflow_script("policy")
        self.assertTrue(script)
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "outputs"
            stale = Path(root) / "claude-execution-output.json"
            directories = []
            for mode, expected in (
                ("full", ("high", "20", "8", "3")),
                ("delta", ("low", "8", "4", "1")),
            ):
                output.write_text("")
                stale.write_text("old SDK execution must not certify this run")
                result = subprocess.run(
                    ["bash", "-e", "-o", "pipefail", "-c", script],
                    env=dict(
                        os.environ,
                        RUNNER_TEMP=root,
                        GITHUB_OUTPUT=str(output),
                        MODE=mode,
                        FULL_EFFORT="high",
                        FULL_TURNS="20",
                        FULL_MINUTES="8",
                        FULL_BUDGET_USD="3",
                        DELTA_EFFORT="low",
                        DELTA_TURNS="8",
                        DELTA_MINUTES="4",
                        DELTA_BUDGET_USD="1",
                    ),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                values = dict(
                    line.split("=", 1) for line in output.read_text().splitlines()
                )
                self.assertEqual(
                    tuple(
                        values[key] for key in ("effort", "turns", "minutes", "budget")
                    ),
                    expected,
                )
                config = Path(values["config_dir"])
                self.assertEqual(config.stat().st_mode & 0o777, 0o700)
                self.assertEqual(list(config.iterdir()), [])
                self.assertFalse(stale.exists())
                directories.append(config)
            self.assertNotEqual(*directories)


class ReviewReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(
            "#!/usr/bin/env python3\n"
            "import json,os,pathlib,sys\n"
            "with open(os.environ['REPORT_CALLS'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
            "if os.environ.get('REPORT_GH_FAIL'): sys.exit(1)\n"
            "if '--input' in sys.argv:\n"
            " p=pathlib.Path(sys.argv[sys.argv.index('--input')+1])\n"
            " pathlib.Path(os.environ['REPORT_PAYLOAD']).write_text(p.read_text())\n"
            " print('{}')\n"
            "elif any('/pulls/' in arg for arg in sys.argv):\n"
            " print(json.dumps({'state':'open','head':{'sha':os.environ.get('REPORT_CURRENT_HEAD',os.environ['HEAD_SHA']),'repo':{'full_name':os.environ['GITHUB_REPOSITORY']}}}))\n"
            "else: print(os.environ.get('REPORT_COMMENTS','[]'))\n"
        )
        gh.chmod(0o755)

    def run_report(self, messages=None, malformed=False, **overrides):
        script = workflow_script("report")
        self.assertTrue(script, "workflow lacks deterministic report step")
        (self.root / "step-summary").write_text("")
        (self.root / "outputs").write_text("")
        (self.root / "payload").unlink(missing_ok=True)
        execution = self.root / "claude-execution-output.json"
        execution.unlink(missing_ok=True)
        if messages is not None:
            execution.write_text(json.dumps(messages))
        if malformed:
            execution.write_text("malformed SECRET_RAW_TASK")
        env = dict(os.environ)
        env.update(
            PATH=str(self.bin) + os.pathsep + env["PATH"],
            RUNNER_TEMP=str(self.root),
            GITHUB_OUTPUT=str(self.root / "outputs"),
            GITHUB_STEP_SUMMARY=str(self.root / "step-summary"),
            GITHUB_REPOSITORY="owner/project",
            GITHUB_RUN_ID="123",
            GITHUB_RUN_ATTEMPT="1",
            GITHUB_SERVER_URL="https://github.com",
            PR_NUMBER="42",
            HEAD_SHA="1" * 40,
            BASE_SHA="2" * 40,
            MODE="delta",
            RANGE="3" * 40 + ".." + "1" * 40,
            SCOPE_REASON="push delta",
            MODEL="claude-sonnet-5-5",
            AUTH_PRESENT="true",
            REVIEW_OUTCOME="failure",
            REVIEW_CONCLUSION="failure",
            EXECUTION_FILE="",
            REPORT_CALLS=str(self.root / "calls"),
            REPORT_PAYLOAD=str(self.root / "payload"),
        )
        env.update(overrides)
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = dict(
            line.split("=", 1)
            for line in (self.root / "outputs").read_text().splitlines()
        )
        artifact = Path(output["artifact_dir"])
        summary = (artifact / "summary.md").read_text()
        diagnostics = json.loads((artifact / "diagnostics.json").read_text())
        all_output = summary + json.dumps(diagnostics) + result.stdout + result.stderr
        self.assertNotIn("SECRET_RAW_TASK", all_output)
        self.assertNotIn("secret-tool-input", all_output)
        self.assertTrue((self.root / "step-summary").read_text().startswith(summary))
        if (self.root / "payload").exists():
            payload = json.loads((self.root / "payload").read_text())
            self.assertEqual(payload["body"], summary)
        return diagnostics, summary, result

    def terminal(self, subtype="success", **extra):
        return dict(
            type="result",
            subtype=subtype,
            is_error=subtype != "success",
            num_turns=9,
            duration_ms=1200,
            total_cost_usd=1.2,
            result="SECRET_RAW_TASK",
            errors=["SECRET_RAW_TASK"],
            **extra,
        )

    def test_turn_and_budget_exhaustion_preserve_safe_stats_and_tool_names(self):
        for subtype in ("error_max_turns", "error_max_budget_usd"):
            with self.subTest(subtype=subtype):
                messages = [
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-sonnet-5-5",
                            "content": [
                                {"type": "text", "text": "SECRET_RAW_TASK"},
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {"command": "secret-tool-input"},
                                },
                            ],
                        },
                    },
                    self.terminal(subtype),
                ]
                data, summary, _ = self.run_report(messages)
                self.assertEqual(data["status"], "incomplete")
                self.assertEqual(data["terminal"]["subtype"], subtype)
                self.assertEqual(data["terminal"]["num_turns"], 9)
                self.assertEqual(data["trace"][0]["tools"], ["Bash"])
                self.assertIn("only this range", summary)

    def test_success_requires_action_and_terminal_success(self):
        data, summary, _ = self.run_report(
            [self.terminal()], REVIEW_OUTCOME="success", REVIEW_CONCLUSION="success"
        )
        self.assertEqual(data["status"], "completed")
        self.assertIn("does not certify earlier PR changes", summary)

    def test_green_validation_skip_is_not_a_completed_review(self):
        data, _, _ = self.run_report(REVIEW_OUTCOME="success", REVIEW_CONCLUSION="")
        self.assertEqual(data["status"], "incomplete")
        self.assertEqual(data["execution"], "missing")

    def test_timeout_missing_file_reports_unknown_measurements(self):
        data, summary, _ = self.run_report()
        self.assertEqual(data["status"], "incomplete")
        self.assertEqual(data["execution"], "missing")
        self.assertIn("unknown", summary)

    def test_malformed_execution_does_not_leak_parse_exception(self):
        data, _, _ = self.run_report(malformed=True)
        self.assertEqual(data["execution"], "malformed")
        self.assertEqual(data["status"], "incomplete")

    def test_missing_credentials_and_identical_head_are_explicit_skips(self):
        data, _, _ = self.run_report(AUTH_PRESENT="false", REVIEW_OUTCOME="skipped")
        self.assertEqual(data["status"], "skipped_missing_credentials")
        data, _, _ = self.run_report(MODE="skip", REVIEW_OUTCOME="skipped")
        self.assertEqual(data["status"], "skipped_identical_head")

    def test_invalid_context_never_posts_comment_but_still_writes_artifacts(self):
        data, _, _ = self.run_report(PR_NUMBER="", HEAD_SHA="")
        self.assertEqual(data["status"], "skipped_invalid_context")
        self.assertFalse((self.root / "calls").exists())

    def test_existing_workflow_comment_is_updated(self):
        comments = [
            [
                {
                    "id": 77,
                    "body": "<!-- claude-review-workflow-status -->\nold",
                    "user": {"login": "github-actions[bot]"},
                }
            ]
        ]
        self.run_report(REPORT_COMMENTS=json.dumps(comments))
        calls = (self.root / "calls").read_text()
        self.assertIn("PATCH", calls)
        self.assertIn("issues/comments/77", calls)

    def test_comment_failure_is_visible_and_does_not_change_review_status(self):
        data, _, result = self.run_report(REPORT_GH_FAIL="1")
        self.assertEqual(data["status"], "incomplete")
        self.assertIn("::warning::", result.stdout)

    def test_non_array_execution_is_malformed(self):
        data, _, _ = self.run_report({"result": "SECRET_RAW_TASK"})
        self.assertEqual(data["execution"], "malformed")

    def test_explicit_execution_output_path_is_used(self):
        execution = self.root / "custom-execution.json"
        execution.write_text(json.dumps([self.terminal()]))
        data, _, _ = self.run_report(
            EXECUTION_FILE=str(execution),
            REVIEW_OUTCOME="success",
            REVIEW_CONCLUSION="success",
        )
        self.assertEqual(data["status"], "completed")

    def test_extremely_large_usage_value_is_omitted_without_losing_report(self):
        terminal = self.terminal()
        terminal["num_turns"] = 10**400
        data, _, _ = self.run_report([terminal])
        self.assertNotIn("num_turns", data["terminal"])

    def test_newer_pr_head_prevents_stale_status_overwrite(self):
        _, _, result = self.run_report(REPORT_CURRENT_HEAD="9" * 40)
        self.assertFalse((self.root / "payload").exists())
        self.assertIn("head moved", (self.root / "step-summary").read_text())

    def test_bad_field_types_and_terminal_error_cannot_claim_success(self):
        terminal = self.terminal()
        terminal.update(
            is_error=True, num_turns="SECRET_RAW_TASK", total_cost_usd=float("nan")
        )
        data, _, _ = self.run_report(
            [terminal], REVIEW_OUTCOME="success", REVIEW_CONCLUSION="success"
        )
        self.assertEqual(data["status"], "incomplete")
        self.assertNotIn("num_turns", data["terminal"])
        self.assertNotIn("total_cost_usd", data["terminal"])


class ReviewConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Config Test")
        self.git("config", "user.email", "config@example.invalid")
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude/settings.json").write_text('{"trusted":true}')
        (self.repo / "CLAUDE.md").write_text("trusted instructions")
        (self.repo / "source.txt").write_text("base source")
        self.git("add", ".")
        self.git("commit", "-qm", "trusted base")
        self.base = self.git("rev-parse", "HEAD")
        (self.repo / ".claude/settings.json").write_text('{"trusted":false}')
        (self.repo / ".mcp.json").write_text('{"untrusted":true}')
        (self.repo / "CLAUDE.md").unlink()
        (self.repo / "source.txt").write_text("PR source")
        self.outside = self.root / "outside"
        self.outside.write_text("leave this file alone")
        (self.repo / ".claude.json").symlink_to(self.outside)
        self.git("add", ".")
        self.git("commit", "-qm", "PR config changes")
        self.head = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.repo, text=True, stderr=subprocess.PIPE
        ).strip()

    def restore(self):
        script = workflow_script("trusted")
        self.assertTrue(
            script, "dispatch lacks trusted startup configuration restoration"
        )
        env = dict(os.environ, BASE_SHA=self.base)
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=self.repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_restores_base_settings_and_deleted_instructions(self):
        self.restore()
        self.assertEqual(
            (self.repo / ".claude/settings.json").read_text(), '{"trusted":true}'
        )
        self.assertEqual((self.repo / "CLAUDE.md").read_text(), "trusted instructions")

    def test_removes_pr_only_startup_config(self):
        self.restore()
        self.assertFalse((self.repo / ".mcp.json").exists())

    def test_does_not_follow_pr_controlled_symlinks(self):
        self.restore()
        self.assertFalse((self.repo / ".claude.json").is_symlink())
        self.assertEqual(self.outside.read_text(), "leave this file alone")

    def test_keeps_pr_commit_index_and_source_available_for_review(self):
        self.restore()
        self.assertEqual(self.git("rev-parse", "HEAD"), self.head)
        self.assertEqual(self.git("diff", "--cached"), "")
        self.assertEqual((self.repo / "source.txt").read_text(), "PR source")
        self.assertEqual(
            self.git("show", "HEAD:.claude/settings.json"), '{"trusted":false}'
        )


class ReviewContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "print(os.environ['PR_GUARD_METADATA'])\n"
        )
        gh.chmod(0o755)
        self.metadata = {
            "state": "open",
            "draft": False,
            "user": {"login": "author"},
            "head": {
                "repo": {"full_name": "owner/project"},
                "ref": "feature/review",
                "sha": "1" * 40,
            },
            "base": {"ref": "dev", "sha": "2" * 40},
        }

    def run_context(self, number="42", event_head=""):
        script = workflow_script("pr")
        self.assertTrue(script, "workflow has no PR context validation")
        output = self.root / "outputs"
        env = dict(os.environ)
        env.update(
            PATH=str(self.bin) + os.pathsep + env["PATH"],
            PR_NUMBER=number,
            EVENT_HEAD=event_head,
            GITHUB_REPOSITORY="owner/project",
            GITHUB_OUTPUT=str(output),
            PR_GUARD_METADATA=json.dumps(self.metadata),
        )
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        values = (
            dict(line.split("=", 1) for line in output.read_text().splitlines())
            if output.exists()
            else {}
        )
        return result, values

    def assert_rejected(self, **kwargs):
        result, values = self.run_context(**kwargs)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(values, {})

    def test_manual_dispatch_resolves_actual_pr_head_and_base(self):
        result, values = self.run_context()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(values["number"], "42")
        self.assertEqual(values["head_sha"], "1" * 40)
        self.assertEqual(values["base_sha"], "2" * 40)
        self.assertEqual(values["head_ref"], "feature/review")

    def test_fork_dispatch_is_rejected_before_checkout(self):
        self.metadata["head"]["repo"]["full_name"] = "fork/project"
        self.assert_rejected()

    def test_closed_pr_is_rejected_before_checkout(self):
        self.metadata["state"] = "closed"
        self.assert_rejected()

    def test_draft_pr_is_rejected_before_checkout(self):
        self.metadata["draft"] = True
        self.assert_rejected()

    def test_dependabot_dispatch_is_rejected_before_checkout(self):
        self.metadata["user"]["login"] = "dependabot[bot]"
        self.assert_rejected()

    def test_unexpected_base_is_rejected_before_checkout(self):
        self.metadata["base"]["ref"] = "release"
        self.assert_rejected()

    def test_stale_pull_request_event_is_rejected(self):
        self.assert_rejected(event_head="3" * 40)

    def test_invalid_dispatch_number_is_not_interpreted_as_shell_source(self):
        self.assert_rejected(number="42; touch injected")
        self.assertFalse((self.root / "injected").exists())


if __name__ == "__main__":
    unittest.main()
