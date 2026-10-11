"""Exercise the real hook with a hermetic gh boundary (no merges or network)."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HOOK = (
    Path(__file__).resolve().parents[1] / ".claude/hooks/pretooluse-pr-review-nudge.sh"
)

# Both repositories have PR 334. The checkout's PR is clean; the requested
# repository's PR has an open thread. Dropping -R must therefore fail the test.
GH_STUB = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with Path(os.environ["GH_CALLS"]).open("a") as calls:
    calls.write(json.dumps(args) + "\n")
if args[:2] == ["pr", "view"]:
    if os.environ.get("FAIL_VIEW"):
        sys.exit(1)
    repo = args[args.index("-R") + 1] if "-R" in args else "checkout/clean"
    base = os.environ.get("PR_BASE", "dev")
    print(f"https://github.com/{repo}/pull/334 {base}")
elif args[:2] == ["api", "graphql"]:
    if os.environ.get("FAIL_QUERY"):
        sys.exit(1)
    if "owner=target" in args and "name=blocked" in args:
        print("src/target.gd:17 (reviewer)")
else:
    sys.exit(2)
"""


class MergeGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        stub = self.work / "gh"
        stub.write_text(GH_STUB)
        stub.chmod(0o755)
        self.calls_path = self.work / "calls.jsonl"

    def run_hook(self, command, **extra_env):
        self.calls_path.write_text("")
        env = dict(os.environ, **extra_env)
        env.update(
            PATH=f"{self.work}{os.pathsep}{os.environ['PATH']}",
            GH_CALLS=str(self.calls_path),
        )
        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
            text=True,
            capture_output=True,
            cwd=self.work,
            env=env,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout) if result.stdout.strip() else {}
        calls = [json.loads(line) for line in self.calls_path.read_text().splitlines()]
        return output.get("hookSpecificOutput", {}), calls

    def test_repo_forms_check_requested_repository_not_clean_checkout(self):
        for flag in (
            "-R target/blocked",
            "-R=target/blocked",
            "-Rtarget/blocked",
            "--repo target/blocked",
            "--repo=target/blocked",
        ):
            for command in (
                f"gh {flag} pr merge 334 --merge",
                f"gh pr merge {flag} 334 --merge",
                f"gh pr merge 334 --merge {flag}",
            ):
                with self.subTest(command=command):
                    output, calls = self.run_hook(command)
                    self.assertEqual(output.get("permissionDecision"), "deny", output)
                    self.assertIn(
                        "src/target.gd:17", output["permissionDecisionReason"]
                    )
                    self.assertEqual(
                        calls[0][:5], ["pr", "view", "334", "-R", "target/blocked"]
                    )
                    self.assertIn("owner=target", calls[1])
                    self.assertIn("name=blocked", calls[1])
                    self.assertIn("--paginate", calls[1])

    def test_clean_checkout_control_passes(self):
        output, calls = self.run_hook("gh pr merge 334 --merge")
        self.assertNotIn("permissionDecision", output)
        self.assertIn("0 unresolved review threads", output["additionalContext"])
        self.assertIn("owner=checkout", calls[1])
        self.assertIn("name=clean", calls[1])

    def test_attached_repo_without_target_still_checks_requested_repository(self):
        output, calls = self.run_hook("gh pr merge -Rtarget/blocked --merge")
        self.assertEqual(output.get("permissionDecision"), "deny")
        self.assertEqual(calls[0][:4], ["pr", "view", "-R", "target/blocked"])

    def test_chains_deny_in_both_orders_without_separator_spaces(self):
        clean = "gh pr merge 334 --merge"
        blocked = "gh pr merge 334 -Rtarget/blocked --merge"
        for command in (f"{clean}&&{blocked}", f"{blocked};{clean}"):
            with self.subTest(command=command):
                output, calls = self.run_hook(command)
                self.assertEqual(output.get("permissionDecision"), "deny")
                self.assertEqual(len(calls), 4)

    def test_ambiguous_commands_ask_without_lookup(self):
        for command in (
            'gh pr merge --body "see 334" --merge',
            "gh pr merge $PR --merge",
            "gh --hostname other.example pr merge 334",
        ):
            with self.subTest(command=command):
                output, calls = self.run_hook(command)
                self.assertEqual(output.get("permissionDecision"), "ask")
                self.assertEqual(calls, [])

    def test_lookup_failures_and_non_dev_base_ask(self):
        for env in ({"FAIL_VIEW": "1"}, {"FAIL_QUERY": "1"}, {"PR_BASE": "main"}):
            with self.subTest(env=env):
                output, _ = self.run_hook("gh pr merge 334 --merge", **env)
                self.assertEqual(output.get("permissionDecision"), "ask")

    def test_view_comments_deny_takes_priority(self):
        output, calls = self.run_hook("gh pr merge 334 && gh pr view 334 --comments")
        self.assertEqual(output.get("permissionDecision"), "deny")
        self.assertIn("Use gh api instead", output["permissionDecisionReason"])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
