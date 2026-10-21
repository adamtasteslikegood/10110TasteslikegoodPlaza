"""Run existing Godot acceptance scenes with bounded time and positive markers."""

import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MARKERS = {
    "domain_store": r"domain_store_test: OK — [1-9][0-9]* checks passed\.",
    "domain_transport": r"domain_transport_test: OK — [1-9][0-9]* checks passed\.",
    "smoke": r"smoke_test: OK — [1-9][0-9]* agents, all checks passed\.",
    "conversation_store": r"conversation_store_test: OK — [1-9][0-9]* checks passed\.",
    "transport_client": r"transport_client_test: OK — [1-9][0-9]* checks passed\.",
    "dialogue_panel": r"dialogue_panel_test: OK — [1-9][0-9]* checks passed\.",
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
            or not any(
                re.fullmatch(MARKERS[name], line) for line in result.stdout.splitlines()
            )
            or "SCRIPT ERROR" in result.stdout
            or "ERROR:" in result.stdout
        ):
            raise SystemExit(result.returncode or 1)
    if len(sys.argv) == 1:
        raise SystemExit("Select at least one headless gate")


if __name__ == "__main__":
    main()
