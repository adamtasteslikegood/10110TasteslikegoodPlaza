"""Unit tests for bridge.agents — the agent store loader."""

import os
import shutil
import tempfile
import unittest

from bridge import agents


class TestLoadAgent(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_store = agents.STORE_DIR
        agents.STORE_DIR = self.tmpdir

        with open(os.path.join(self.tmpdir, "systems-architect.md"), "w") as f:
            f.write("You are the Systems Architect.")

    def tearDown(self):
        agents.STORE_DIR = self._orig_store
        shutil.rmtree(self.tmpdir)

    def test_load_existing(self):
        result = agents.load_agent("systems-architect")
        self.assertEqual(result, "You are the Systems Architect.")

    def test_load_missing(self):
        result = agents.load_agent("nonexistent-agent")
        self.assertIsNone(result)

    def test_load_empty_id(self):
        self.assertIsNone(agents.load_agent(""))

    def test_load_non_string(self):
        self.assertIsNone(agents.load_agent(42))
        self.assertIsNone(agents.load_agent(None))

    def test_path_traversal_rejected(self):
        self.assertIsNone(agents.load_agent("../../etc/passwd"))
        self.assertIsNone(agents.load_agent("../secrets"))

    def test_invalid_characters_rejected(self):
        self.assertIsNone(agents.load_agent("agent/sub"))
        self.assertIsNone(agents.load_agent(".hidden"))


class TestListAgents(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_store = agents.STORE_DIR
        agents.STORE_DIR = self.tmpdir

        for name in ["beta-agent", "alpha-agent", "gamma-agent"]:
            with open(os.path.join(self.tmpdir, f"{name}.md"), "w") as f:
                f.write(f"You are {name}.")

    def tearDown(self):
        agents.STORE_DIR = self._orig_store
        shutil.rmtree(self.tmpdir)

    def test_lists_sorted(self):
        result = agents.list_agents()
        self.assertEqual(result, ["alpha-agent", "beta-agent", "gamma-agent"])

    def test_empty_store(self):
        agents.STORE_DIR = tempfile.mkdtemp()
        self.assertEqual(agents.list_agents(), [])
        shutil.rmtree(agents.STORE_DIR)

    def test_missing_store(self):
        agents.STORE_DIR = "/nonexistent/path"
        self.assertEqual(agents.list_agents(), [])


if __name__ == "__main__":
    unittest.main()
