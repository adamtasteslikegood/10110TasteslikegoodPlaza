# Working a PR — instructions for the agent, not for contributors

> Split out of `CLAUDE.md` under `PLZG-107`. `CONTRIBUTING.md` has the human-facing mechanics.


`CONTRIBUTING.md` has the human-facing mechanics. This section is what *you* do.

**Commit and push after every significant work-run** so nothing is lost if the session or VM dies. Stage only intentional files; keep commits scoped.

**Opening a PR is not the end of the task.** Every PR you author, or are actively working on, is yours until it merges — by default, without being asked — and merging it is part of that (`D-031`).

- **A `PLZG-###` key in the title is required.** Jira's GitHub integration links PRs, branches and commits by scanning the title, so a PR without one is invisible to the board. Put it in the branch name and commit messages too. Forgot it? Edit the title; the rescan picks it up. **If no issue exists for the work, file one first — never invent a key.**
- **Monitor it.** Check all three review surfaces (add `--paginate` to each so nothing past page 1 is missed) — `gh api --paginate repos/{owner}/{repo}/pulls/<n>/comments` (inline diff comments), `gh api --paginate repos/{owner}/{repo}/issues/<n>/comments` (top-level conversation comments), and `gh api --paginate repos/{owner}/{repo}/pulls/<n>/reviews` (submitted review summaries, whose prose lives in `.body` with no inline comment) — plus `gh pr checks <n>`. Do **not** rely on `gh pr view --comments`: it misses review-body comments and suppressed co-pilot reviews, and the review hook denies it. Re-check whenever you return, and before declaring related work done. `claude-review.yml` is advisory and `continue-on-error`, so read its job log rather than its check mark — and it cannot review changes to itself.
- **Answer every comment**, with either a fix commit plus a reply saying what changed, or a concrete technical rebuttal. Never leave feedback silently unaddressed. **Verify each claim against the file before replying** — reply from what the code says, not what the comment asserts.
- **Sign replies posted on Adam's behalf.** They go out under his account, so end each with an attribution line naming *which* Claude wrote it — model and session:

  > `_Replied by Claude on Adam's behalf — <model> · session <id>_`

  `<id>` is **`${CLAUDE_CODE_SESSION_ID:0:7}`** — seven characters, the `git --short` convention. That is the only value distinguishing parallel sessions in the same terminal tab list; two sessions opened a minute apart on the same branch are otherwise indistinguishable in a thread. Seven is comfortable: across every transcript in this project, four characters already collide zero times.

  It also names that session's own transcript, so a reply leads back to the conversation that wrote it — but **the directory is derived from `cwd`**, so a session running in a worktree lands under the worktree's slug, not the repo's:

  ```
  ~/.claude/projects/<cwd-slug>/$CLAUDE_CODE_SESSION_ID.jsonl
  ```

  Do not substitute `$CLAUDE_JOB_DIR` (background jobs only), `$CLAUDE_CODE_BRIDGE_SESSION_ID` (the claude.ai session — absent in a plain terminal), the branch, or the worktree name. None are unique per session. (`Co-authored-by:` trailers belong in commits, not comments.)
- **Merge it yourself when every thread is resolved (`D-031`).** Rounds are not counted — `D-030`'s minimum 2 / maximum 3 is superseded. You merge a PR into `dev` when all of these hold: required checks green on the head commit; the head commit's review runs have finished and you have re-read all three surfaces since your last push; every inline thread has a reply and is marked resolved (`gh api graphql` on the PR's `reviewThreads` returns no `isResolved: false`), and every conversation comment and review body that raises a point has a reply. Each resolution is a **fix** (name the commit), a **rebuttal** verified against the file, or **deliberately not fixed now** — say why it does not affect the work this PR exists to do, and file a `PLZG` ticket for anything owed. Resolve the thread after you reply; do not resolve one you have not answered.
- **"Not fixed now" is not an exit from review.** It is for a finding beside the PR's purpose, so a small change does not grow or drag. It does not cover a finding about whether the change is correct, and "out of scope" with no reason resolves nothing. Security findings, a failing required check, and the ticket's own acceptance are never deferred. **Default to fixing** when the fix is small — a rebuttal the bot re-raises on the next push costs more than the fix.
- **Loop until merged.** Monitor → fix, rebut or defer → reply → resolve, until you merge it, it closes, or Adam says stop. Judgment calls only he can make — scope, product, a disagreement you cannot settle on the merits — go to him rather than a guess: reply on the thread that it awaits his call, leave that thread open, and do not merge. `D-031` covers PRs into `dev` only — it says nothing about `dev` → `main`, so do not merge a release on its authority. The merge-guard hook still asks for confirmation on `gh pr merge`; that prompt is the hook's, not a rule that Adam merges.
- **Move the board when the work moves (`D-032`).** Start the Jira sprint when its first task starts. A ticket goes to `In Progress` when its branch is created — the automation does it; do it by hand if it did not fire. After the merge, run the ticket's acceptance command and move the ticket to `Done` with the evidence in a comment. Close the sprint when every ticket in it is `Done` and its close gate exits 0. Sprint start and close are pre-authorised; they are not the "destructive action" a loop plan escalates.
- **A closed sprint's gate is frozen (`PLZG-268`, owner ruling 2026-10-07).** Today that means `scripts/sprint_5_gate.py`: its checks compare live state (open board items, governed-document blob hashes) with evidence captured at the close, so they go red as work continues. That is not a finding: do not re-stamp the evidence, and rebut a review comment that asks for it by citing this line. The freeze covers close-time evidence only. A check that runs the product — the smoke test, the bridge tests, anything `sprint_6_gate.py` runs against the scene or the bridge — failing is a regression whichever sprint wrote it.

**Keep a PR to one concern.** A branch carrying a skill, a task-runner, a policy change and a bug fix gets reviewed as four arguments at once, and the mergeable part drowns in the arguable ones. Split before pushing.

