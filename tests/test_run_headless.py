"""Exercise the headless gate CLI with controlled engine output, offline."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import run_headless

ROOT = Path(__file__).resolve().parents[1]
SUCCESS_LINES = {
    "smoke": "smoke_test: OK — 133 agents, all checks passed.",
    "conversation_store": "conversation_store_test: OK — 579 checks passed.",
    "transport_client": "transport_client_test: OK — 155 checks passed.",
    "dialogue_panel": "dialogue_panel_test: OK — 221 checks passed.",
}


class HeadlessGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.engine = Path(temporary.name) / "fake-godot"
        self.engine.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "sys.stdout.write(os.environ['GATE_OUTPUT'])\n"
            "sys.exit(int(os.environ['GATE_STATUS']))\n"
        )
        self.engine.chmod(0o755)

    def run_gate(self, scene, output, status=0):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/run_headless.py"), scene],
            env={
                **os.environ,
                "GODOT_BIN": str(self.engine),
                "GATE_OUTPUT": output,
                "GATE_STATUS": str(status),
            },
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_changed_positive_scene_counts_are_accepted(self):
        for scene, line in SUCCESS_LINES.items():
            for output in (line, f"Godot Engine banner\n{line}\n", line + "\r\n"):
                with self.subTest(scene=scene, output=output):
                    result = self.run_gate(scene, output)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, output.replace("\r\n", "\n"))

    def test_single_positive_count_is_accepted(self):
        for scene, line in SUCCESS_LINES.items():
            count = line.split(" — ")[1].split()[0]
            with self.subTest(scene=scene):
                self.assertEqual(
                    self.run_gate(scene, line.replace(count, "1")).returncode, 0
                )

    def test_nonpositive_or_malformed_counts_are_rejected(self):
        for scene, line in SUCCESS_LINES.items():
            count = line.split(" — ")[1].split()[0]
            for invalid in ("0", "-1", "1.5", ""):
                with self.subTest(scene=scene, count=invalid):
                    result = self.run_gate(scene, line.replace(count, invalid))
                    self.assertEqual(result.returncode, 1, result.stdout)

    def test_missing_incomplete_or_embedded_success_is_rejected(self):
        for scene, line in SUCCESS_LINES.items():
            for output in (
                "Godot Engine banner\n",
                line.removesuffix("."),
                line.removesuffix(".") + "!",
                "quoted: " + line,
                line + " fake fragment",
                line.replace("passed.", "failed."),
            ):
                with self.subTest(scene=scene, output=output):
                    self.assertEqual(self.run_gate(scene, output).returncode, 1)

    def test_another_scenes_success_is_rejected(self):
        for scene, line in SUCCESS_LINES.items():
            other_scene = "smoke" if scene != "smoke" else "dialogue_panel"
            with self.subTest(scene=scene):
                self.assertEqual(self.run_gate(other_scene, line).returncode, 1)

    def test_engine_errors_override_success_even_with_zero_exit(self):
        for scene, line in SUCCESS_LINES.items():
            for error in ("SCRIPT ERROR (failed to load)", "ERROR: engine failure"):
                with self.subTest(scene=scene, error=error):
                    result = self.run_gate(scene, f"{error}\n{line}\n")
                    self.assertEqual(result.returncode, 1, result.stdout)

    def test_nonzero_engine_status_is_preserved_despite_success(self):
        for scene, line in SUCCESS_LINES.items():
            with self.subTest(scene=scene):
                self.assertEqual(self.run_gate(scene, line, status=7).returncode, 7)

    def test_timeout_propagates_with_the_existing_bound(self):
        def hung_engine(command, **kwargs):
            self.assertEqual(kwargs["timeout"], 30)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with mock.patch.object(sys, "argv", ["run_headless.py", "smoke"]):
            with mock.patch.object(run_headless.subprocess, "run", hung_engine):
                with self.assertRaises(subprocess.TimeoutExpired):
                    run_headless.main()


if __name__ == "__main__":
    unittest.main()
