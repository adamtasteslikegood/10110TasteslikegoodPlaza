# Current session handoff

## Read/update contract

- This is short-term **development-session memory**, requested by the owner on
  2026-10-21. It does not implement application persistence or SDK recovery.
- At startup, follow `CLAUDE.md`'s Git fetch/status requirement, then read this
  file, `TODO.md`, and `PROGRESS.md` in the current worktree. Verify remembered
  branch/HEAD, files, Jira and test claims before acting; context may be stale.
- After each substantive user/assistant turn, and before yielding, handoff or
  compaction: refresh this snapshot and TODO, then append a short progress entry.
  Record intent, decisions, completed work, evidence, blockers and next action.
  Do not log each tool call. If interrupted, checkpoint before switching tasks.
- Keep exactly these three memory files: this snapshot <=120 lines, TODO <=80,
  PROGRESS <=120 with at most 12 recent entries (<=6 bullets each). Condense older
  entries into a short recap; use Git history for detail instead of new archives.
- Use repo-relative paths, dates/timezone, branch and verified commit references.
  Label user reports, observations, proposals and pending approvals separately.
  Never store secrets, credentials, raw transcripts or speculative success.
- The lead agent writes these files; subagents report back. Independent worktrees
  keep independent copies. Do not resolve them through the shared Git directory
  or copy a different branch's handoff wholesale. Reconcile context when merging.
- Include meaningful memory updates in task checkpoints and push according to
  `.claude/pr-workflow.md`; never stage unrelated changes. Files are available to
  later machines only after the branch is pushed and fetched there.
- These are derived notes, subordinate to current user instructions, live state
  and governed documents. Existing PM/Confluence hooks are unchanged.

## Snapshot — 2026-10-21 11:04 UTC

- Work: PLZG M10/M11 reconciliation and M12 domain execution design; owner also
  requested this compact session memory. Agent: Codex, M12 design session.
- Branch: `docs/PLZG-289-m12-domain-design`, based on `origin/dev` at `142b17a`.
  Design checkpoint: `9bd33a95d754bd26389f8833414d40a77822899c` (pushed).
  Use `git log -3 --oneline` and `git status` for the newer memory checkpoint;
  this file cannot record its own eventual commit hash.
- Authoring worktree on this cloud machine:
  `/workspace/10110TasteslikegoodPlaza/.claude/worktrees/m12-domain-design`.
  The owner's accepted runtime changes are on laptop-local `dev`; do not assume
  this cloud checkout proves the laptop state.
- Design: `docs/superpowers/specs/2026-10-21-m12-domain-execution-design.md`.
  Written spec is **DRAFT awaiting owner review**. No implementation plan or
  M12 product implementation exists in this branch. No PR opened yet.
- Jira: M9–M11 Done; M12 PLZG-289 In Progress; M13–M15 PLZG-290/291/292 To Do.
  PLZG-284 closed on owner acceptance; PLZG-285 retains shutdown/rate-limit
  observations follow-up. Recheck live Jira before reporting status again.

## User direction and proposed details

- Owner confirmed M10/M11 work locally using Claude subscription and API token;
  the output cap was a setting. No itemized desktop log was provided.
- Owner chose explicit Start/Run; walking away backgrounds already-started work.
- Owner requires at least one dedicated execution Git worktree now, separate
  from source/runtime checkout, with room for independent parallel environments
  later. M13/M14 persistence and isolation can reorder/combine; M15 provider is
  unselected. Do not add a container/VM provider in M12.
- Draft proposes one operator-created linked worktree, validated CWD, one SDK
  domain session reserving it from Start through Stop, correlated replay and
  explicit Godot controls. Session-length reservation is still a proposal.
- SDK owner task, cross-process lock/unclean marker, generation checks, Stop
  during activation, read-only discovery and bounded buffers are specified.
- Live acceptance must show an actual SDK file write after backgrounding and
  unrelated NPC chat, plus Godot/plain-client replay. Prior NPC recall is not it.

## Evidence and open work

- Design/roadmap reviewed by bridge and Godot audit agents; findings addressed.
  No remaining blocking contradiction reported in their final reviews.
- Latest doc validation: 22 governed documents at v0.2.16 pass; 18 existing
  submodule links were skipped because that submodule is uninitialized here.
  Delivery-coordinates validation, `git diff --check`, Black (59 files), and
  fatal flake8 checks pass. Memory size limits and instruction links verified.
- The 112 bridge checks cited in the design were baseline exploration, not M12
  implementation evidence. No live SDK acceptance run performed for this work.
- Three memory files and Claude/Codex startup instructions are prepared and
  validated. Jira PLZG-289/290/291 now reflects minimum worktree scope in M12,
  flexible M13/M14 sequencing, and a link to the pushed written design.
- Next product step: owner reviews the committed written spec. Requested
  Superpowers brainstorming requires written-spec approval before `writing-plans`;
  then written-plan review/execution choice before implementation. Current owner
  approval covers the direction and minimum worktree requirement only.
