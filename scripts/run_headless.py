"""Run existing Godot acceptance scenes with bounded time and positive markers."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MARKERS = {
    "smoke": "smoke_test: OK — 132 agents, all checks passed.",
    "conversation_store": "conversation_store_test: OK — 578 checks passed.",
    "transport_client": "transport_client_test: OK — 154 checks passed.",
    "dialogue_panel": "dialogue_panel_test: OK — 220 checks passed.",
}


def main():
    for name in sys.argv[1:]:
        if name not in MARKERS:
            raise SystemExit(f"Unknown headless gate: {name}")
        result = subprocess.run(
            [
                os.environ.get("GODOT_BIN", "godot"),
                "--headless",
                "--path",
                str(ROOT),
                f"tests/{name}_test.tscn",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
        print(result.stdout, end="", flush=True)
        if (
            result.returncode
            or MARKERS[name] not in result.stdout
            or "SCRIPT ERROR" in result.stdout
            or "ERROR:" in result.stdout
        ):
            raise SystemExit(result.returncode or 1)
    if len(sys.argv) == 1:
        raise SystemExit("Select at least one headless gate")


if __name__ == "__main__":
    main()
