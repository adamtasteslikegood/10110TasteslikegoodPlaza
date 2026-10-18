"""Exercise the workflow's real Bash scope selector against temporary Git graphs."""

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
        gh.write_text(
            "#!/usr/bin/env python3\n"
            "import json,os,sys\n"
            "runs=json.loads(os.environ['SCOPE_TEST_RUNS'])\n"
            "if os.environ.get('SCOPE_TEST_API_FAILURE'):\n"
            " sys.exit(1)\n"
            "if sys.argv[1:3]==['run','list']:\n"
            " print('\\n'.join(str(r['id']) for r in runs))\n"
            "elif sys.argv[1:3]==['run','view']:\n"
            " r=next(r for r in runs if str(r['id'])==sys.argv[3])\n"
            " print('\\n'.join(s['name'] for s in r['steps'] "
            "if s['conclusion']=='success'))\n"
            "else:\n"
            " sys.exit('unexpected gh operation')\n"
        )
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

    def reviewed(self, sha, number=42, run_id=1):
        return {
            "id": run_id,
            "steps": [
                {
                    "name": f"Reviewed PR {number} at {sha}",
                    "conclusion": "success",
                }
            ],
        }

    def run_scope(self, runs=(), action="synchronize", api_failure=False):
        script = workflow_script("scope")
        self.assertTrue(script, "workflow has no scope-selection step")
        output = self.root / "outputs"
        env = dict(os.environ)
        env.update(
            PATH=str(self.bin) + os.pathsep + env["PATH"],
            ACTION=action,
            PR_NUMBER="42",
            HEAD_SHA=self.git("rev-parse", "HEAD"),
            HEAD_REF="main",
            BEFORE=self.base,
            GITHUB_OUTPUT=str(output),
            SCOPE_TEST_RUNS=json.dumps(list(runs)),
            SCOPE_TEST_API_FAILURE="1" if api_failure else "",
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
        return dict(line.split("=", 1) for line in output.read_text().splitlines())

    def test_includes_every_commit_since_last_genuine_review(self):
        self.commit("first-unreviewed")
        head = self.commit("second-unreviewed")
        result = self.run_scope([self.reviewed(self.base)])
        self.assertEqual(result["mode"], "delta")
        self.assertEqual(result["range"], f"{self.base}..{head}")

    def test_cancelled_failed_and_skipped_reviews_do_not_advance_baseline(self):
        first = self.commit("first-unreviewed")
        head = self.commit("second-unreviewed")
        recent = [
            {"id": 3, "steps": []},
            {
                "id": 2,
                "steps": [
                    {
                        "name": f"Reviewed PR 42 at {first}",
                        "conclusion": "failure",
                    }
                ],
            },
        ]
        result = self.run_scope(recent + [self.reviewed(self.base)])
        self.assertEqual(result["range"], f"{self.base}..{head}")

    def test_green_action_without_completion_marker_requires_full_review(self):
        self.commit("unreviewed")
        result = self.run_scope(
            [
                {
                    "id": 1,
                    "steps": [
                        {"name": "Review + fix + comment", "conclusion": "success"}
                    ],
                }
            ]
        )
        self.assertEqual(result["mode"], "full")
        self.assertEqual(result["range"], "")

    def test_no_review_requires_full_review_instead_of_event_before(self):
        self.commit("unreviewed")
        self.assertEqual(self.run_scope()["mode"], "full")

    def test_other_pr_marker_is_not_a_baseline(self):
        self.commit("unreviewed")
        self.assertEqual(
            self.run_scope([self.reviewed(self.base, number=7)])["mode"], "full"
        )

    def test_dispatch_marker_uses_reviewed_sha_instead_of_workflow_run_head(self):
        head = self.commit("unreviewed")
        run = self.reviewed(self.base)
        run["headSha"] = "f" * 40
        self.assertEqual(self.run_scope([run])["range"], f"{self.base}..{head}")

    def test_older_review_after_many_skipped_runs_is_used(self):
        head = self.commit("unreviewed")
        skipped = [{"id": n, "steps": []} for n in range(16, 1, -1)]
        result = self.run_scope(skipped + [self.reviewed(self.base)])
        self.assertEqual(result["range"], f"{self.base}..{head}")

    def test_missing_or_nonancestor_review_requires_full_review(self):
        self.git("checkout", "--orphan", "replacement")
        self.git("rm", "-rf", ".")
        self.commit("replacement")
        self.assertEqual(self.run_scope([self.reviewed(self.base)])["mode"], "full")
        self.assertEqual(self.run_scope([self.reviewed("f" * 40)])["mode"], "full")

    def test_merge_since_review_requires_full_review(self):
        self.git("checkout", "-qb", "side", self.base)
        self.commit("side")
        self.git("checkout", "main")
        self.commit("main-change")
        self.git("merge", "--no-ff", "side", "-m", "merge side")
        self.assertEqual(self.run_scope([self.reviewed(self.base)])["mode"], "full")

    def test_non_push_events_review_the_whole_pr(self):
        self.commit("unreviewed")
        for action in ("opened", "ready_for_review", "labeled", ""):
            with self.subTest(action=action):
                result = self.run_scope([self.reviewed(self.base)], action=action)
                self.assertEqual(result["mode"], "full")

    def test_already_reviewed_head_skips_a_duplicate_model_call(self):
        self.assertEqual(self.run_scope([self.reviewed(self.base)])["mode"], "skip")

    def test_lookup_failure_falls_back_to_full_review(self):
        self.commit("unreviewed")
        self.assertEqual(self.run_scope(api_failure=True)["mode"], "full")


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
