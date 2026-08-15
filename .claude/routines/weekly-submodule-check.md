---
cron: "0 10 * * 3"
description: "Check if claude-code-tresor submodule pin is current"
---

Check if the claude-code-tresor submodule is behind its upstream:
1. Run: git submodule update --init --recursive
2. cd claude-code-tresor && git fetch origin
3. Compare HEAD with origin/10110TLGP/dev
4. If behind, open an issue titled "chore: bump claude-code-tresor submodule pin"
   with the commit range and summary of what changed
