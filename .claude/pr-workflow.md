# Working a PR — instructions for the agent, not for contributors

> Split out of `CLAUDE.md` under `PLZG-107`. `CONTRIBUTING.md` has the human-facing mechanics.


`CONTRIBUTING.md` has the human-facing mechanics. This section is what *you* do.

**Commit and push after every significant work-run** so nothing is lost if the session or VM dies. Stage only intentional files; keep commits scoped.

**Opening a PR is not the end of the task.** Every PR you author, or are actively working on, is yours until it merges — by default, without being asked.

- **A `PLZG-###` key in the title is required.** Jira's GitHub integration links PRs, branches and commits by scanning the title, so a PR without one is invisible to the board. Put it in the branch name and commit messages too. Forgot it? Edit the title; the rescan picks it up. **If no issue exists for the work, file one first — never invent a key.**
- **Monitor it.** `gh pr view <n> --comments`, `gh api repos/{owner}/{repo}/pulls/<n>/comments`, `gh pr checks <n>`. Re-check whenever you return, and before declaring related work done. `claude-review.yml` is advisory and `continue-on-error`, so read its job log rather than its check mark — and it cannot review changes to itself.
- **Answer every comment**, with either a fix commit plus a reply saying what changed, or a concrete technical rebuttal. Never leave feedback silently unaddressed. **Verify each claim against the file before replying** — reply from what the code says, not what the comment asserts.
- **Sign replies posted on Adam's behalf.** They go out under his account, so end each with an attribution line naming *which* Claude wrote it — model and session:

  > `_Replied by Claude on Adam's behalf — <model> · session <id>_`

  `<id>` is **`${CLAUDE_CODE_SESSION_ID:0:7}`** — seven characters, the `git --short` convention. That is the only value distinguishing parallel sessions in the same terminal tab list; two sessions opened a minute apart on the same branch are otherwise indistinguishable in a thread. Seven is comfortable: across every transcript in this project, four characters already collide zero times.

  It also names that session's own transcript, so a reply leads back to the conversation that wrote it — but **the directory is derived from `cwd`**, so a session running in a worktree lands under the worktree's slug, not the repo's:

  ```
  ~/.claude/projects/<cwd-slug>/$CLAUDE_CODE_SESSION_ID.jsonl
  ```

  Do not substitute `$CLAUDE_JOB_DIR` (background jobs only), `$CLAUDE_CODE_BRIDGE_SESSION_ID` (the claude.ai session — absent in a plain terminal), the branch, or the worktree name. None are unique per session. (`Co-authored-by:` trailers belong in commits, not comments.)
- **Review round bounds (`D-030`).** Minimum 2 rounds of reading and replying to review comments before merge. Maximum 3 rounds before deciding: merge (if clean), close PR, or revert to draft and elevate to Adam. Security, branch-protection and ticket-linked blockers are exempt from the max. A "round" is one full pass reading all comments and either fixing or rebutting each. **Default to fixing** over rebutting — a rebuttal the bot re-raises on the next push costs more than the fix.
- **Loop until merged.** Monitor → fix or rebut → reply, until it merges, closes, or Adam says stop. Judgment calls only he can make — scope, product — go to him rather than a guess, but still reply on the thread noting it awaits his call.

**Keep a PR to one concern.** A branch carrying a skill, a task-runner, a policy change and a bug fix gets reviewed as four arguments at once, and the mergeable part drowns in the arguable ones. Split before pushing.

