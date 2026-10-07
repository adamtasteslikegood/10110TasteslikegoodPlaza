"""Regression fixtures for scripts/sprint_6_live.py (PLZG-261).

The runner is what Gate B believes, and a real run cannot be made to produce a
fragmented frame, a ping during a slow reply, a crashed Godot or a hung client
on demand. These cases produce them.

The WebSocket client talks to the other end of a socket pair, Godot is faked at
``subprocess.run`` and the bridge at ``subprocess.Popen``. No network beyond
loopback, no credential, no engine, no model call.

Stdlib only. Run: python3 -m unittest tests/test_sprint_6_live.py
"""

import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sprint_6_gate as gate  # noqa: E402
import sprint_6_live as live  # noqa: E402

NONCE = "kestrel-4417"
PROMPTS = live.prompts_for(NONCE)


def server_frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    """A frame as a server sends it: unmasked."""
    first = (0x80 if fin else 0) | opcode
    size = len(payload)
    if size < 126:
        return bytes([first, size]) + payload
    if size < 65536:
        return bytes([first, 126]) + struct.pack(">H", size) + payload
    return bytes([first, 127]) + struct.pack(">Q", size) + payload


def read_client_frame(sock: socket.socket) -> "tuple[int, bytes]":
    """Decode one frame as a client sends it. A client frame must be masked."""

    def read(count: int) -> bytes:
        data = b""
        while len(data) < count:
            data += sock.recv(count - len(data))
        return data

    first, second = read(2)
    assert second & 0x80, "client frame is not masked"
    size = second & 0x7F
    if size == 126:
        size = struct.unpack(">H", read(2))[0]
    elif size == 127:
        size = struct.unpack(">Q", read(8))[0]
    mask = read(4)
    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(read(size)))
    return first & 0x0F, payload


class PlainClientFrames(unittest.TestCase):
    def setUp(self):
        ours, self.server = socket.socketpair()
        self.server.settimeout(5)
        # Past the handshake, which needs a listener and has its own case.
        self.client = live.PlainClient.__new__(live.PlainClient)
        self.client.sock = ours
        self.client.deadline = time.monotonic() + 5
        self.addCleanup(ours.close)
        self.addCleanup(self.server.close)

    def test_text_round_trip(self):
        self.client.send("hello")
        self.assertEqual(read_client_frame(self.server), (0x1, b"hello"))
        self.server.sendall(server_frame(0x1, b"world"))
        self.assertEqual(self.client.receive(5), "world")

    def test_long_payloads_use_the_extended_lengths(self):
        for size in (126, 70000):
            text = "x" * size
            self.client.send(text)
            self.assertEqual(read_client_frame(self.server), (0x1, text.encode()))
            self.server.sendall(server_frame(0x1, text.encode()))
            self.assertEqual(self.client.receive(5), text)

    def test_fragmented_reply_is_joined(self):
        self.server.sendall(
            server_frame(0x1, b"one ", fin=False)
            + server_frame(0x0, b"two ", fin=False)
            + server_frame(0x0, b"three")
        )
        self.assertEqual(self.client.receive(5), "one two three")

    def test_ping_is_answered_with_a_masked_pong(self):
        self.server.sendall(server_frame(0x9, b"abcd") + server_frame(0x1, b"late"))
        self.assertEqual(self.client.receive(5), "late")
        self.assertEqual(read_client_frame(self.server), (0xA, b"abcd"))

    def test_ping_between_fragments_does_not_break_the_message(self):
        self.server.sendall(
            server_frame(0x1, b"one ", fin=False)
            + server_frame(0x9, b"")
            + server_frame(0x0, b"two")
        )
        self.assertEqual(self.client.receive(5), "one two")

    def test_unsolicited_pong_is_ignored(self):
        self.server.sendall(server_frame(0xA, b"") + server_frame(0x1, b"ok"))
        self.assertEqual(self.client.receive(5), "ok")

    def test_close_frame_raises(self):
        self.server.sendall(server_frame(0x8, b""))
        with self.assertRaises(RuntimeError):
            self.client.receive(5)

    def test_dropped_connection_raises(self):
        self.server.close()
        with self.assertRaises(RuntimeError):
            self.client.receive(5)

    def test_pings_do_not_keep_a_reply_that_never_comes_alive(self):
        stop = threading.Event()

        def ping_for_ever():
            while not stop.is_set():
                try:
                    self.server.sendall(server_frame(0x9, b""))
                except OSError:
                    return
                time.sleep(0.02)

        thread = threading.Thread(target=ping_for_ever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(stop.set)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.client.receive(0.3)
        self.assertLess(time.monotonic() - started, 3)


class Handshake(unittest.TestCase):
    def serve_once(self, response: bytes) -> int:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)

        def answer():
            conn, _ = listener.accept()
            with conn:
                conn.recv(4096)
                conn.sendall(response)
                time.sleep(0.2)

        threading.Thread(target=answer, daemon=True).start()
        return listener.getsockname()[1]

    def test_upgrade_accepted(self):
        port = self.serve_once(b"HTTP/1.1 101 Switching Protocols\r\n\r\n")
        with mock.patch.multiple(live, HOST="127.0.0.1", PORT=port):
            live.PlainClient().close()

    def test_upgrade_refused_raises(self):
        port = self.serve_once(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        with mock.patch.multiple(live, HOST="127.0.0.1", PORT=port):
            with self.assertRaises(RuntimeError):
                live.PlainClient()


def live_line(turn: int, **over) -> str:
    record = {
        "turn": turn,
        "sent": PROMPTS[turn - 1],
        "received": "OK" if turn == 1 else NONCE,
        "label_holds_reply": True,
        "typewriter_started_at": 0,
        "typewriter_after_frames": 3,
    }
    record.update(over)
    return "LIVE " + json.dumps(record)


def godot_result(stdout: str, code: int = 0):
    return subprocess.CompletedProcess(["godot"], code, stdout=stdout, stderr="")


class AskGodot(unittest.TestCase):
    def ask(self, result=None, seconds=500.0, side_effect=None):
        with mock.patch.object(live.shutil, "which", return_value="/usr/bin/godot"):
            with mock.patch.object(
                live.subprocess, "run", return_value=result, side_effect=side_effect
            ) as run:
                self.run = run
                return live.ask_godot(PROMPTS, seconds)

    def test_two_turns_are_returned(self):
        turns = self.ask(godot_result(live_line(1) + "\n" + live_line(2) + "\n"))
        self.assertEqual([t["received"] for t in turns], ["OK", NONCE])

    def test_non_zero_exit_fails_even_with_both_turns_printed(self):
        with self.assertRaisesRegex(RuntimeError, "exited 1"):
            self.ask(godot_result(live_line(1) + "\n" + live_line(2) + "\n", code=1))

    def test_auth_error_is_a_could_not_run(self):
        error = 'LIVE_ERROR {"error_type": "auth", "message": "bad token"}\n'
        with self.assertRaises(live.AuthRefused):
            self.ask(godot_result(error, code=1))

    def test_other_bridge_error_is_a_failure_not_a_could_not_run(self):
        error = 'LIVE_ERROR {"error_type": "timeout", "message": "slow"}\n'
        with self.assertRaises(RuntimeError) as caught:
            self.ask(godot_result(error, code=1))
        self.assertNotIsInstance(caught.exception, live.CouldNotRun)

    def test_missing_turn_fails(self):
        with self.assertRaisesRegex(RuntimeError, "1 of 2 turns"):
            self.ask(godot_result(live_line(1) + "\n"))

    def test_reply_that_never_reached_the_label_fails(self):
        out = live_line(1, label_holds_reply=False) + "\n" + live_line(2) + "\n"
        with self.assertRaisesRegex(RuntimeError, "BodyLabel"):
            self.ask(godot_result(out))

    def test_typewriter_that_did_not_advance_fails(self):
        out = live_line(1, typewriter_after_frames=0) + "\n" + live_line(2) + "\n"
        with self.assertRaisesRegex(RuntimeError, "typewriter"):
            self.ask(godot_result(out))

    def test_timeout_is_a_failure_and_is_clipped_to_what_is_left(self):
        hang = subprocess.TimeoutExpired(["godot"], 45)
        with self.assertRaisesRegex(RuntimeError, "did not exit"):
            self.ask(seconds=45.0, side_effect=hang)
        self.assertEqual(self.run.call_args.kwargs["timeout"], 45.0)

    def test_no_godot_is_a_could_not_run(self):
        with mock.patch.object(live.shutil, "which", return_value=None):
            with self.assertRaises(live.CouldNotRun):
                live.ask_godot(PROMPTS, 500.0)


def turns(recalled: bool) -> list:
    return [
        {"sent": PROMPTS[0], "received": "OK"},
        {"sent": PROMPTS[1], "received": NONCE if recalled else "no record"},
    ]


class RunClient(unittest.TestCase):
    def run_client(self, ask, budget=1000.0):
        with mock.patch("builtins.print"):
            return live.run_client("fake", ask, NONCE, time.monotonic() + budget)

    def test_stops_at_the_first_recall_and_logs_the_tries_before_it(self):
        answers = iter([turns(False), turns(True), turns(True)])
        result = self.run_client(lambda prompts, seconds: next(answers))
        self.assertTrue(result["recalled"])
        self.assertEqual([t["recalled"] for t in result["tries"]], [False, True])

    def test_never_recalled_uses_every_try(self):
        result = self.run_client(lambda prompts, seconds: turns(False))
        self.assertFalse(result["recalled"])
        self.assertEqual(len(result["tries"]), live.MAX_TRIES)
        self.assertEqual(result["turns"], turns(False))

    def test_a_broken_try_is_logged_and_the_next_one_runs(self):
        outcomes = iter([OSError("connection reset"), turns(True)])

        def ask(prompts, seconds):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        result = self.run_client(ask)
        self.assertTrue(result["recalled"])
        self.assertEqual(result["tries"][0]["error"], "connection reset")

    def test_every_try_broken_leaves_no_turns_and_no_recall(self):
        def ask(prompts, seconds):
            raise RuntimeError("bridge answered timeout: slow")

        result = self.run_client(ask)
        self.assertEqual((result["turns"], result["recalled"]), ([], False))

    def test_a_late_failure_does_not_inherit_an_earlier_recall(self):
        # Not reachable today -- a recall ends the loop -- but `recalled` must
        # be the last try's, so a change to the loop cannot report a stale one.
        outcomes = iter([turns(False), RuntimeError("x"), RuntimeError("y")])

        def ask(prompts, seconds):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        result = self.run_client(ask)
        self.assertFalse(result["recalled"])
        self.assertEqual(result["turns"], turns(False))

    def test_could_not_run_is_not_swallowed_as_a_failed_try(self):
        def ask(prompts, seconds):
            raise live.AuthRefused("the model refused the credential")

        with self.assertRaises(live.CouldNotRun):
            self.run_client(ask)

    def test_no_try_starts_without_budget_for_it(self):
        calls = []
        result = self.run_client(
            lambda prompts, seconds: calls.append(seconds) or turns(False),
            budget=live.MIN_TRY_SECONDS - 1,
        )
        self.assertEqual(calls, [])
        self.assertEqual(result["tries"][0]["error"], "run budget exhausted")
        self.assertFalse(result["recalled"])

    def test_a_try_is_given_only_what_is_left(self):
        seen = []
        self.run_client(
            lambda prompts, seconds: seen.append(seconds) or turns(True), budget=100.0
        )
        self.assertLessEqual(seen[0], 100.0)


class Budget(unittest.TestCase):
    def test_the_whole_run_fits_inside_the_gates_timeout(self):
        worst = live.BRIDGE_START_SECONDS + live.RUN_SECONDS + live.BRIDGE_STOP_SECONDS
        # A try may overrun the deadline by one socket connect at most.
        self.assertLess(worst + live.CONNECT_SECONDS, gate.LIVE_TIMEOUT_SECONDS)


class Credential(unittest.TestCase):
    def environment(self, dotenv: str, shell: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            if dotenv is not None:
                (Path(tmp) / ".env").write_text(dotenv, encoding="utf-8")
            with mock.patch.object(live, "REPO_ROOT", Path(tmp)):
                with mock.patch.dict(os.environ, shell, clear=True):
                    return live.bridge_environment()

    def test_dotenv_wins_and_the_shells_credential_is_dropped(self):
        env = self.environment(
            "CLAUDE_CODE_OAUTH_TOKEN='fresh'\nATLASSIAN_URL=x\n",
            {"ANTHROPIC_API_KEY": "stale", "PATH": "/bin"},
        )
        self.assertEqual(env.get("CLAUDE_CODE_OAUTH_TOKEN"), "fresh")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env.get("PATH"), "/bin")
        # Only credentials are lifted from the file.
        self.assertNotIn("ATLASSIAN_URL", env)

    def test_shell_is_the_fallback_when_the_file_names_no_credential(self):
        for dotenv in (None, "ATLASSIAN_URL=x\nANTHROPIC_API_KEY=\n"):
            env = self.environment(dotenv, {"ANTHROPIC_API_KEY": "shell"})
            self.assertEqual(env.get("ANTHROPIC_API_KEY"), "shell")

    def test_no_credential_anywhere_is_a_could_not_run(self):
        with self.assertRaises(live.CouldNotRun):
            self.environment("ATLASSIAN_URL=x\n", {"PATH": "/bin"})


class FakeBridge:
    """A child that died at startup without ever printing the ready line."""

    def __init__(self, stderr_lines):
        self.stderr = iter(stderr_lines)
        self.killed = self.terminated = False

    def poll(self):
        return 1

    def kill(self):
        self.killed = True

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 1


class Startup(unittest.TestCase):
    def main(self, port_open: bool, bridge=None):
        patches = [
            mock.patch.object(live, "bridge_environment", return_value={}),
            mock.patch.object(live, "bridge_python", return_value="python3"),
            mock.patch.object(live, "port_open", return_value=port_open),
            mock.patch.object(live.subprocess, "Popen", return_value=bridge),
            mock.patch.object(live, "run_client"),
            mock.patch("builtins.print"),
        ]
        started = []
        for patch in patches:
            started.append(patch.start())
            self.addCleanup(patch.stop)
        self.popen, self.run_client = started[3], started[4]
        return live.main()

    def test_port_already_in_use_is_exit_2_and_starts_nothing(self):
        self.assertEqual(self.main(port_open=True), 2)
        self.popen.assert_not_called()

    def test_a_bridge_that_never_says_ready_is_exit_2_and_asks_nothing(self):
        # The port may well be answering -- someone else's listener -- and that
        # must not count: only the child's own startup line does.
        bridge = FakeBridge(["OSError: [Errno 98] address already in use\n"])
        self.assertEqual(self.main(port_open=False, bridge=bridge), 2)
        self.assertTrue(bridge.terminated or bridge.killed)
        self.run_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
