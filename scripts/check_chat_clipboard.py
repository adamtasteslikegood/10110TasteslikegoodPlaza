"""Optional real X11 panel checks with independent cross-process clipboard reads.

Run under an owned DISPLAY with Godot and xclip. No providers are called. Each
checkpoint follows an actual production-panel UI action and a fresh sentinel;
the scene's event loop stays running until xclip has read and compared the value.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def run_scene(scene, godot, xclip, screenshots=None):
    observations = []
    with tempfile.TemporaryDirectory(prefix="plaza-clipboard-") as directory:
        checkpoint = Path(directory) / "checkpoint.json"
        log = Path(directory) / "godot.log"
        environment = {**os.environ, "PLAZA_CLIPBOARD_PROBE_DIR": directory}
        if screenshots:
            environment["PLAZA_CLIPBOARD_SCREENSHOT_DIR"] = str(screenshots.resolve())
        with log.open("w+") as output:
            process = subprocess.Popen(
                [
                    godot,
                    "--path",
                    str(ROOT),
                    "--display-driver",
                    "x11",
                    "--rendering-method",
                    "gl_compatibility",
                    "--audio-driver",
                    "Dummy",
                    f"tests/{scene}_test.tscn",
                ],
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + 45
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"{scene}: desktop watchdog expired")
                    if checkpoint.exists():
                        record = json.loads(checkpoint.read_text())
                        read = subprocess.run(
                            [xclip, "-selection", record["selection"], "-out"],
                            check=True,
                            capture_output=True,
                            timeout=3,
                        )
                        actual = read.stdout.decode("utf-8")
                        observations.append({**record, "actual": actual})
                        if actual != record["expected"]:
                            raise AssertionError(
                                f"{scene}/{record['name']}: "
                                f"expected {record['expected']!r}, got {actual!r}"
                            )
                        checkpoint.unlink()
                    time.sleep(0.01)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                output.seek(0)
                transcript = output.read()
                print(transcript, end="")
        marker = rf"{scene}_test: OK — [1-9][0-9]* checks passed\."
        if (
            process.returncode
            or not re.search(marker, transcript)
            or "SCRIPT ERROR" in transcript
            or "ERROR:" in transcript
            or len(observations) < 12
        ):
            raise AssertionError(f"{scene}: desktop scene failed or missed checkpoints")
    return {
        "scene": scene,
        "observations": observations,
        "exit_code": process.returncode,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", default=os.environ.get("GODOT_BIN", "godot"))
    parser.add_argument("--xclip", default="xclip")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    if not os.environ.get("DISPLAY"):
        print("chat clipboard desktop: SKIP (no DISPLAY; headless is not OS proof)")
        return
    if not shutil.which(args.godot) or not shutil.which(args.xclip):
        parser.error("desktop checks require callable Godot and xclip binaries")
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    record = {
        "kind": "chat_clipboard_desktop",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "display": os.environ["DISPLAY"],
        "scenes": [
            run_scene(scene, args.godot, args.xclip, args.screenshots)
            for scene in ["dialogue_panel", "domain_panel"]
        ],
    }
    if args.output:
        args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    count = sum(len(scene["observations"]) for scene in record["scenes"])
    print(f"chat clipboard desktop: OK — {count} independent xclip reads")


if __name__ == "__main__":
    main()
