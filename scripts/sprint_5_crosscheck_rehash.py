#!/usr/bin/env python3
"""List, and on request re-stamp, stale rows in the Sprint 5 T4 cross-check evidence.

`sprint_5_gate.py t4` fails a row whose document changed after it was reviewed.
Run with no arguments to see which documents those are; it writes nothing and
exits 1 if any row is stale. Re-read them, then run with --write to re-stamp.
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
    write = sys.argv[1:] == ["--write"]
    if sys.argv[1:] and not write:
        print("usage: sprint_5_crosscheck_rehash.py [--write]", file=sys.stderr)
        return 2
    stale = 0
    for row in evidence["reviewed_docs"]:
        blob = subprocess.run(
            ["git", "hash-object", paths[row["doc_id"]]],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=True,
        ).stdout.strip()
        if row.get("reviewed_blob") != blob:
            stale += 1
            verb = "re-stamped" if write else "changed since review"
            print(f"{verb}: {row['doc_id']} ({paths[row['doc_id']]})")
            row["reviewed_blob"] = blob
    if write:
        EVIDENCE.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
        return 0
    if stale:
        print(
            f"{stale} row(s) stale; re-read those documents, then re-run with --write"
        )
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
