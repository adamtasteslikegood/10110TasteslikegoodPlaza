---
cron: "0 9 * * 1-5"
description: "Triage and deduplicate open GitHub issues"
---

Review all open issues on this repository. For each issue:
1. Check if it duplicates another open issue (same PR reference, same underlying problem)
2. If duplicate, comment linking to the original and close as duplicate
3. Check if the issue has been fixed by a subsequent merge (check git log for the PR/file referenced)
4. If fixed, comment with the fixing commit and close as completed
5. Ensure every open issue has at least one label
