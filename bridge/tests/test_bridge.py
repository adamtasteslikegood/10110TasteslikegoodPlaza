"""Unit tests for bridge.bridge — request handling and error classification."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from anthropic import RateLimitError

from bridge import bridge


class _FakeResponse:
    """Minimal stand-in for an httpx.Response attached to SDK exceptions."""

    def __init__(self, headers=None):
        self.headers = headers or {}


class _FakeMessage:
    """Minimal stand-in for an Anthropic Messages response."""

    def __init__(self, text="Hello"):
        block = MagicMock()
        block.text = text
        self.content = [block]


class TestHandleRequest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_store = bridge.STORE_DIR if hasattr(bridge, "STORE_DIR") else None

        from bridge import agents

        self._orig_agents_store = agents.STORE_DIR
        agents.STORE_DIR = self.tmpdir

        with open(os.path.join(self.tmpdir, "test-agent.md"), "w") as f:
            f.write("You are a test agent.")

        self.client = MagicMock()

    def tearDown(self):
        from bridge import agents

        agents.STORE_DIR = self._orig_agents_store
        shutil.rmtree(self.tmpdir)

    def test_success(self):
        self.client.messages.create.return_value = _FakeMessage("Hi there")
        resp = bridge.handle_request(
            self.client, {"agent_id": "test-agent", "task": "say hi"}
        )
        self.assertEqual(resp["status"], "ok")
        self.assertEqual(resp["output"], "Hi there")
        self.assertEqual(resp["agent_id"], "test-agent")

    def test_missing_agent_id(self):
        resp = bridge.handle_request(self.client, {"agent_id": "", "task": "hello"})
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error_type"], "invalid_request")

    def test_missing_task(self):
        resp = bridge.handle_request(
            self.client, {"agent_id": "test-agent", "task": ""}
        )
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error_type"], "invalid_request")

    def test_invalid_agent_id_chars(self):
        resp = bridge.handle_request(
            self.client, {"agent_id": "../evil", "task": "hello"}
        )
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error_type"], "invalid_request")

    def test_agent_not_found(self):
        resp = bridge.handle_request(
            self.client, {"agent_id": "nonexistent", "task": "hello"}
        )
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error_type"], "not_found")

    def test_non_dict_request(self):
        resp = bridge.handle_request(self.client, "not a dict")
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error_type"], "invalid_request")

    def test_rate_limit_error(self):
        fake_resp = _FakeResponse(headers={"retry-after": "30"})
        exc = RateLimitError(
            message="rate limited",
            response=MagicMock(
                status_code=429,
                headers=fake_resp.headers,
                json=MagicMock(return_value={}),
            ),
            body={"type": "error", "error": {"type": "rate_limit_error"}},
        )
        exc.response = MagicMock()
        exc.response.headers = fake_resp.headers
        self.client.messages.create.side_effect = exc

        resp = bridge.handle_request(
            self.client, {"agent_id": "test-agent", "task": "hello"}
        )
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error_type"], "rate_limit")
        self.assertIn("Rate limited on", resp["message"])
        self.assertIn("retry after 30s", resp["message"])

    def test_rate_limit_without_retry_header(self):
        exc = RateLimitError(
            message="rate limited",
            response=MagicMock(
                status_code=429,
                headers={},
                json=MagicMock(return_value={}),
            ),
            body={"type": "error", "error": {"type": "rate_limit_error"}},
        )
        exc.response = MagicMock()
        exc.response.headers = {}
        self.client.messages.create.side_effect = exc

        resp = bridge.handle_request(
            self.client, {"agent_id": "test-agent", "task": "hello"}
        )
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error_type"], "rate_limit")
        self.assertNotIn("retry after", resp["message"])

    def test_timeout_error(self):
        self.client.messages.create.side_effect = TimeoutError("timed out")
        resp = bridge.handle_request(
            self.client, {"agent_id": "test-agent", "task": "hello"}
        )
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error_type"], "timeout")

    def test_generic_api_error(self):
        self.client.messages.create.side_effect = RuntimeError("something broke")
        resp = bridge.handle_request(
            self.client, {"agent_id": "test-agent", "task": "hello"}
        )
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error_type"], "api_error")


class TestDefaultModel(unittest.TestCase):
    def test_default_is_haiku(self):
        self.assertEqual(bridge.DEFAULT_MODEL, "claude-haiku-4-5-20251001")

    @patch.dict(os.environ, {"BRIDGE_MODEL": "claude-opus-4-6"})
    def test_env_override(self):
        import importlib

        importlib.reload(bridge)
        self.assertEqual(bridge.DEFAULT_MODEL, "claude-opus-4-6")
        # Restore default
        os.environ.pop("BRIDGE_MODEL", None)
        importlib.reload(bridge)


if __name__ == "__main__":
    unittest.main()
