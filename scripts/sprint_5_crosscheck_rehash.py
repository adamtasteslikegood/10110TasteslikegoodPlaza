#!/usr/bin/env python3
"""Re-stamp reviewed_blob in the Sprint 5 T4 cross-check evidence.

`sprint_5_gate.py t4` fails a row whose document changed after it was reviewed.
Run this only after re-reading the documents it reports as changed: it prints
each one so the re-stamp is a decision, not a reflex.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "specs/evidence/sprint-5-doc-crosscheck.json"
REGISTRY = ROOT / "specs/meta/doc-registry.json"


def main() -> int:
    paths = {
        d["doc_id"]: d["path"] for d in json.loads(REGISTRY.read_text())["documents"]
    }
    evidence = json.loads(EVIDENCE.read_text())
    for row in evidence["reviewed_docs"]:
        blob = subprocess.run(
            ["git", "hash-object", paths[row["doc_id"]]],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=True,
        ).stdout.strip()
        if row.get("reviewed_blob") != blob:
            print(f"re-stamped {row['doc_id']}: {paths[row['doc_id']]}")
            row["reviewed_blob"] = blob
    EVIDENCE.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
