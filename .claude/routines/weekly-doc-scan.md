---
cron: "0 10 * * 1"
description: "Scan governed docs for stale claims"
---

Run `python3 scripts/validate_specs.py` and check for stale claims in CLAUDE.md:
1. Verify "M1, M3 and M4 are done" matches specs/task-tracker.md
2. Check bridge TODO claims against bridge/ directory state
3. Verify submodule agent counts match docs/agent-directory.md
4. If any claim is stale, open an issue with the specific stale line and current state
