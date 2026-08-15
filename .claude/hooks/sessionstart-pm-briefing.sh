#!/usr/bin/env bash
# SessionStart hook — inject the PM briefing so every session opens briefed.
#
# Reads .agent-work/pm/PROJECT_PM_BRIEFING.md (first 12k chars) if present,
# else falls back to canonical specs/*.md planning files (first 1500 chars
# each). Injected as SessionStart additionalContext.
#
# Design rules: fail-open (always exit 0), bounded output, recursion-guarded.

set -uo pipefail
trap 'exit 0' ERR

if [ -n "${CLAUDE_PM_SESSION_LOG_ACTIVE:-}" ]; then
  exit 0
fi

INPUT=$(cat 2>/dev/null || true)

_field() {
  printf '%s' "$INPUT" | python3 -c "
import json,sys
try: print((json.load(sys.stdin) or {}).get('$1','') or '')
except Exception: print('')
" 2>/dev/null
}

SOURCE=$(_field source)
CWD=$(_field cwd)
[ -n "$CWD" ] || CWD="$(pwd)"

if [ "$SOURCE" = "compact" ]; then
  exit 0
fi

COMMON_GIT=$(git -C "$CWD" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "")
if [ -n "$COMMON_GIT" ] && [ -d "$COMMON_GIT" ]; then
  MAIN_REPO=$(dirname "$COMMON_GIT")
else
  MAIN_REPO="$CWD"
fi

BRIEFING=$(CWD="$CWD" MAIN_REPO="$MAIN_REPO" python3 <<'PY' 2>/dev/null || true
import os
import sys
from pathlib import Path

BRIEFING_FILE = Path(".agent-work/pm/PROJECT_PM_BRIEFING.md")

roots = []
for r in (os.environ.get("CWD"), os.environ.get("MAIN_REPO")):
    if r and r not in roots:
        roots.append(Path(r))

canonical_pm_files = None
for root in roots:
    candidate = root / "scripts" / "pm"
    if (candidate / "_canonical_pm_files.py").is_file():
        sys.path.insert(0, str(candidate))
        try:
            from _canonical_pm_files import canonical_pm_files
        except Exception:
            canonical_pm_files = None
        break

if canonical_pm_files is None:
    _FALLBACK = [
        "specs/roadmap.md",
        "specs/task-tracker.md",
    ]

    def _charter_key(rel):
        stem = Path(rel).name
        mid = stem.replace("sprint-", "").replace("-charter.md", "")
        return (0, int(mid), "") if mid.isdigit() else (1, 0, stem)

    def canonical_pm_files(root="."):
        base = Path(root)
        globbed = sorted(
            (m.relative_to(base).as_posix() for m in base.glob("specs/sprint-*-charter.md") if m.is_file()),
            key=_charter_key,
        )
        ordered, seen = [], set()
        for rel in _FALLBACK + globbed:
            if rel not in seen and (base / rel).is_file():
                seen.add(rel)
                ordered.append(rel)
        return [Path(p) for p in ordered]

for root in roots:
    bp = root / BRIEFING_FILE
    if bp.exists():
        try:
            c = bp.read_text(encoding="utf-8", errors="replace")
            print("CURRENT PM BRIEFING:\n" + c[:12000] + ("..." if len(c) > 12000 else ""))
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception:
            pass

status = []
seen = set()
for root in roots:
    for rel_path in canonical_pm_files(root):
        rel = rel_path.as_posix()
        fp = root / rel
        if rel in seen or not fp.exists():
            continue
        try:
            c = fp.read_text(encoding="utf-8", errors="replace")
            status.append(f"--- {rel} ---\n{c[:1500]}" + ("..." if len(c) > 1500 else ""))
            seen.add(rel)
        except Exception:
            pass

if status:
    print("CURRENT PM BRIEFING:\n" + "\n".join(status))
PY
)

[ -n "$BRIEFING" ] || exit 0

python3 -c "
import json,sys
ctx = sys.stdin.read()
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': ctx}}))
" <<<"$BRIEFING" 2>/dev/null || true

exit 0
