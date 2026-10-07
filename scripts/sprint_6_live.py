#!/usr/bin/env python3
"""Gate B's runner: two real turns through the bridge, from two clients.

Run by ``scripts/sprint_6_gate.py`` (``t5``, ``live``), or directly:

    python3 scripts/sprint_6_live.py

It starts ``bridge/bridge.py``, then asks one agent two questions from each of
two clients:

* **godot** -- ``tests/live_conversation.tscn``, headless, through the dialogue
  panel and ``scenes/bridge/ws_client.gd``. The reply is read off ``BodyLabel``.
* **python** -- the WebSocket client in this file, which is forty lines of
  stdlib and has never heard of Godot. That is the ``D-005`` swap test: a
  bridge that only works for one of these has learned who is calling.

Turn 1 hands over a random nonce. Turn 2 asks for it back without repeating it.
A bridge that answers requests passes turn 1; only one that holds a
conversation passes turn 2. Nothing about the model's wording is asserted.

Each run makes up to ``MAX_TRIES`` tries per client and records every one, so a
flaky pass is visible as a pass on try 3 rather than as a clean pass.

It writes ``specs/evidence/sprint-6-live-transcript.json`` every time it gets
as far as a model reply, pass or fail, stamped with the time of this run -- the
gate refuses a transcript older than the run it just made.

Exit codes: 0 both clients recalled the nonce; 1 they did not, or the path
broke; 2 it could not be run -- no credential, no bridge dependencies, no
Godot, port in use. A 2 is never evidence either way.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = REPO_ROOT / "specs" / "sprint-6-loop-plan.json"
BRIDGE_ENTRY = REPO_ROOT / "bridge" / "bridge.py"
GODOT_SCENE = "tests/live_conversation.tscn"
HOST, PORT = "localhost", 8765
AGENT_ID = "systems-architect"
MAX_TRIES = 3
BRIDGE_START_SECONDS = 20
READY_LINE = f"Bridge running on ws://{HOST}:{PORT}"
REPLY_SECONDS = 120
GODOT_SECONDS = 300
# What bridge/conversation.py's build_client reads. The digit-zero spelling is
# a typo the bridge accepts on purpose (issue #258); it is listed because a
# working .env on this project carries it.
CREDENTIAL_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_0AUTH_TOKEN",
)


class CouldNotRun(Exception):
    """Exit 2: the run says nothing about the bridge."""


class AuthRefused(CouldNotRun):
    """The model refused the credential."""


def dotenv() -> dict:
    env = {}
    path = REPO_ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip("'\"")
    return env


def bridge_environment() -> dict:
    env = dict(os.environ)
    for key, value in dotenv().items():
        if key in CREDENTIAL_VARS and value:
            env.setdefault(key, value)
    if not any(env.get(name) for name in CREDENTIAL_VARS):
        raise CouldNotRun(
            "no Claude credential: set one of "
            + ", ".join(CREDENTIAL_VARS)
            + " in ./.env or the environment"
        )
    return env


def bridge_python() -> str:
    """An interpreter that can import what the bridge imports."""
    candidates = [REPO_ROOT / ".venv" / "bin" / "python", Path(sys.executable)]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        probe = subprocess.run(
            [str(candidate), "-c", "import websockets, anthropic"],
            capture_output=True,
        )
        if probe.returncode == 0:
            return str(candidate)
    raise CouldNotRun(
        "no interpreter with the bridge's dependencies (websockets, anthropic); "
        "tried .venv/bin/python and " + sys.executable
    )


class BridgeLog:
    """The child bridge's stderr, read on a thread so the pipe never fills."""

    def __init__(self, stream):
        self.lines = []
        self.ready = threading.Event()
        threading.Thread(target=self._drain, args=(stream,), daemon=True).start()

    def _drain(self, stream) -> None:
        for line in stream:
            self.lines.append(line)
            if READY_LINE in line:
                self.ready.set()

    def tail(self) -> str:
        return "".join(self.lines)[-600:]


def port_open() -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((HOST, PORT)) == 0


class PlainClient:
    """A WebSocket text client from the standard library. No Godot, no SDK."""

    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=REPLY_SECONDS)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET / HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        head = b""
        while b"\r\n\r\n" not in head:
            head += self._read(1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"bridge refused the upgrade: {head[:80]!r}")

    def _read(self, count: int) -> bytes:
        data = b""
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise RuntimeError("bridge closed the connection")
            data += chunk
        return data

    def _frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        size = len(payload)
        first = 0x80 | opcode
        if size < 126:
            header = bytes([first, 0x80 | size])
        elif size < 65536:
            header = bytes([first, 0x80 | 126]) + struct.pack(">H", size)
        else:
            header = bytes([first, 0x80 | 127]) + struct.pack(">Q", size)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send(self, text: str) -> None:
        self._frame(0x1, text.encode())

    def receive(self) -> str:
        message = b""
        while True:
            first, second = self._read(2)
            opcode, size = first & 0x0F, second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(size)
            if opcode == 0x8:
                raise RuntimeError("bridge closed the connection")
            if opcode == 0x9:
                # The server pings every 20s and drops a client that stays
                # silent, which a slow model reply would otherwise trip.
                self._frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            message += payload
            if first & 0x80:
                return message.decode("utf-8")

    def close(self) -> None:
        self.sock.close()


def ask_plain(prompts: list) -> list:
    client = PlainClient()
    try:
        turns = []
        for prompt in prompts:
            client.send(json.dumps({"agent_id": AGENT_ID, "task": prompt}))
            reply = json.loads(client.receive())
            if reply.get("status") != "ok":
                refuse(reply.get("error_type"), reply.get("message"))
            turns.append({"sent": prompt, "received": reply.get("output", "")})
        return turns
    finally:
        client.close()


def ask_godot(prompts: list) -> list:
    godot = shutil.which("godot")
    if godot is None:
        raise CouldNotRun("godot is not on PATH")
    env = dict(os.environ, LIVE_AGENT=AGENT_ID, LIVE_TURNS=json.dumps(prompts))
    try:
        result = subprocess.run(
            [godot, "--headless", GODOT_SCENE],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
            timeout=GODOT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{GODOT_SCENE} did not exit in {GODOT_SECONDS}s") from exc
    turns = []
    for line in result.stdout.splitlines():
        if line.startswith("LIVE_ERROR "):
            error = json.loads(line[len("LIVE_ERROR ") :])
            refuse(error.get("error_type"), error.get("message"))
    if result.returncode != 0:
        raise RuntimeError(
            f"{GODOT_SCENE} exited {result.returncode}:\n"
            + f"{result.stdout}{result.stderr}".strip()[-600:]
        )
    for line in result.stdout.splitlines():
        if line.startswith("LIVE "):
            turn = json.loads(line[len("LIVE ") :])
            if not turn.get("label_holds_reply"):
                raise RuntimeError(
                    f"turn {turn.get('turn')}: BodyLabel does not hold the reply"
                )
            if not turn["typewriter_after_frames"] > turn["typewriter_started_at"]:
                raise RuntimeError(
                    f"turn {turn.get('turn')}: the typewriter did not advance (D-007)"
                )
            turns.append({"sent": turn["sent"], "received": turn["received"]})
    if len(turns) != len(prompts):
        raise RuntimeError(
            f"{GODOT_SCENE} reported {len(turns)} of {len(prompts)} turns:\n"
            + f"{result.stdout}{result.stderr}".strip()[-600:]
        )
    return turns


def refuse(error_type, message) -> None:
    if error_type == "auth":
        raise AuthRefused(f"the model refused the credential: {message}")
    raise RuntimeError(f"bridge answered {error_type}: {message}")


def prompts_for(nonce: str) -> list:
    return [
        f"Please remember this code word for my next message: {nonce}. "
        "Reply with just the word OK.",
        "What was the code word I gave you in my previous message? "
        "Reply with the code word only.",
    ]


def run_client(name: str, ask, nonce: str) -> dict:
    """Up to MAX_TRIES tries; the last one is the client's recorded result."""
    prompts = prompts_for(nonce)
    tries = []
    for number in range(1, MAX_TRIES + 1):
        try:
            turns = ask(prompts)
            recalled = nonce in turns[1]["received"]
            tries.append({"try": number, "turns": turns, "recalled": recalled})
        except CouldNotRun:
            raise
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            tries.append({"try": number, "error": str(exc), "recalled": False})
            recalled = False
        print(f"{name} try {number}: {'recalled' if recalled else 'not recalled'}")
        if recalled:
            break
    last = next((t for t in reversed(tries) if "turns" in t), None)
    return {
        "turns": last["turns"] if last else [],
        "recalled": tries[-1]["recalled"],
        "tries": tries,
    }


def main() -> int:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    spec = next(t for t in plan["tasks"] if t["id"] == "T5")["acceptance_inputs"]
    transcript_path = REPO_ROOT / spec["transcript"]
    askers = {"godot": ask_godot, "python": ask_plain}

    try:
        env = bridge_environment()
        python = bridge_python()
        if port_open():
            raise CouldNotRun(
                f"port {PORT} is already in use; stop the running bridge so this "
                "run can be sure which bridge it tested"
            )
        bridge = subprocess.Popen(
            [python, str(BRIDGE_ENTRY)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except CouldNotRun as exc:
        print(f"could not run: {exc}", file=sys.stderr)
        return 2

    log = BridgeLog(bridge.stderr)
    try:
        # The port answering is not enough: another process could have taken
        # it after the check above. The bridge prints READY_LINE only once its
        # own bind succeeded, and it exits if the bind failed.
        deadline = time.monotonic() + BRIDGE_START_SECONDS
        while not log.ready.wait(0.25):
            if bridge.poll() is not None or time.monotonic() > deadline:
                bridge.kill()
                print(
                    f"could not run: the bridge did not start:\n{log.tail()}",
                    file=sys.stderr,
                )
                return 2
        if bridge.poll() is not None:
            print(
                f"could not run: the bridge exited at startup:\n{log.tail()}",
                file=sys.stderr,
            )
            return 2

        nonce = "kestrel-" + secrets.token_hex(4)
        clients = {
            name: run_client(name, askers[name], nonce) for name in spec["clients"]
        }
    except CouldNotRun as exc:
        print(f"could not run: {exc}", file=sys.stderr)
        return 2
    finally:
        bridge.terminate()
        try:
            bridge.wait(timeout=10)
        except subprocess.TimeoutExpired:
            bridge.kill()

    transcript = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "nonce": nonce,
        "agent_id": AGENT_ID,
        "owner_read": False,
        "clients": clients,
    }
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        json.dumps(transcript, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    recalled = all(client["recalled"] for client in clients.values())
    print(
        f"wrote {spec['transcript']}: "
        + ("both clients recalled the nonce" if recalled else "nonce NOT recalled")
    )
    return 0 if recalled else 1


if __name__ == "__main__":
    sys.exit(main())
