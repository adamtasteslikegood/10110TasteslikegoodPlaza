# Contributing

Thanks for working on **10110 TastesLikegood Plaza**. This file is the day-to-day reference for contributors (human or agent). For the formal policy — the branch model, what CI actually enforces, and the branch-protection setup still to be applied — see [`specs/branching-strategy.md`](specs/branching-strategy.md).

## Before you start

1. **Clone with submodules.** The agent definitions (141 files, 133 distinct roles) live in a submodule. Fresh checkouts won't have them.
   ```bash
   git clone --recurse-submodules https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza.git
   # or, if already cloned:
   git submodule update --init --recursive
   ```
2. **Read [`CLAUDE.md`](CLAUDE.md).** It's the orientation doc — what exists, what doesn't, the 4-layer architecture, the M1 → M4 → M8 critical path, the gotchas. Future-you and any agent picking up the work will start here.
3. **Skim [`QUICKSTART.md`](QUICKSTART.md)** if you need to run the existing Atlassian scripts or stand up a `.env`.
4. **Pick a milestone in [`specs/roadmap.md`](specs/roadmap.md).** Match it to a Jira ticket in project `TO` if one exists.

## Branching

```
feature/* | fix/* | hotfix/*  →  dev  →  main
       (your work)              (integration)   (release)
```

- `main` — production line; updated only when releasing.
- `dev` — **integration branch.** New work targets `dev`.
- `feature/<name>`, `fix/<name>`, `hotfix/<name>` — short-lived. Branch off `dev`, PR back into `dev`.
- `claude/<task-slug>` — task-assigned working branches used by Claude Code sessions. Same flow.

**Never commit directly to `main` or `dev`** — go through a PR.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/), lowercase, imperative mood, no trailing period.

```
feat(godot): add CharacterBody2D player controller
fix(bridge): handle subprocess timeout cleanly
docs(specs): bump roadmap last-updated date
chore: bump claude-code-tresor submodule
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.

## Pull requests

1. Push your branch and open a **draft PR** against `dev`.
2. Title follows Conventional Commits (under 70 chars).
3. Body covers:
   - **Summary** — 1–3 bullets, the *why*.
   - **Test plan** — checklist of what you verified.
   - Link to the Jira ticket if applicable.
4. Wait for CI (`Validate Specs`, `Lint Python Bridge`, and the Godot export stub) and any reviewer feedback.
5. **Merge commit** — squash and rebase merging are disabled on this repo, deliberately (`D-023`). Your commit series survives the merge, so structure it. See [`specs/branching-strategy.md`](specs/branching-strategy.md) §4.

### Commit and push cadence

On feature branches, commit and push after every significant work-run so work is recoverable from the remote if the VM or session dies. Stage only intentional files, keep commits scoped, and push immediately after each local commit unless the user explicitly says not to.

### A PR is yours until it merges

Opening a PR is not the end of the task. Every PR you author, or are actively working on or waiting on, is yours until it merges — this applies by default, without being asked.

- **Jira key in the title (REQUIRED).** Every PR title must contain a Jira issue key — for delivery work that is **`PLZG-###`**, e.g. `feat(bridge): synchronous agent invocation with timeout (PLZG-42)`. Jira's GitHub integration links PRs, branches and commits to an issue by scanning for the key in the PR title, so a PR without one is invisible to the board. Put the key in the branch name and commit messages too where practical — same scanner. Forgot it? Edit the PR title after the fact; Jira picks it up on its next rescan, typically within a couple of minutes. If no Jira issue exists for the work, that is the smell: file one first.
- **Monitor it.** While the PR is open, check for new review comments, inline comments and failing checks (`gh pr view <n> --comments`, `gh api repos/{owner}/{repo}/pulls/<n>/comments`, `gh pr checks <n>`). Re-check whenever you return to the PR and before declaring any related work done — a PR with unaddressed feedback is not finished. Note that `claude-review.yml` is advisory and `continue-on-error`, so **read its job log rather than trusting its check mark**, and remember it cannot review changes to itself.
- **Answer every comment.** For each piece of reviewer feedback, do one of two things: push a fix commit and reply confirming what changed, or reply with a concrete technical rebuttal explaining why no change is needed. Never leave feedback unanswered or silently ignored. **Verify each claim against the code before replying** — reply from what the file actually says, not from what the comment asserts. `.claude/skills/review-specs` is the checklist for what defects look like here, and the enabled `zero-hallucination-coder` skill exists precisely to keep a reply grounded in verified references rather than performative agreement.
- **Sign replies posted on Adam's behalf.** Replies go out under Adam's GitHub account, so make authorship explicit by ending each one with a plain attribution line (`Co-authored-by:` trailers belong in commit messages, not comments):

  > _Replied by Claude on Adam's behalf_

- **Loop until merged.** Repeat monitor → fix or rebut → reply until the PR is merged, closed, or Adam says stop. If feedback requires a judgment call only Adam can make — scope changes, product decisions — surface it to him instead of guessing, but still reply on the thread noting it is awaiting his call.

Reverting a merged PR here needs `git revert -m 1`, because `D-023` makes merge commits the merge strategy.

## CI expectations

Before you push, run locally what CI runs in [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

- `python3 scripts/validate_specs.py` — **must pass.** Fails if a governed document is missing frontmatter, unregistered, mis-declared, or links to a file that doesn't exist. Standard library only. See [`specs/meta/META-SPEC.md`](specs/meta/META-SPEC.md) §8 before adding or changing a doc.
- `black --check .` — **must pass.** Formatting failures fail CI.
- `flake8 . --select=E9,F63,F7,F82` — **must pass.** Syntax errors and undefined names are hard fails.
- `flake8 . --exit-zero --max-complexity=10 --max-line-length=127` — advisory; aim to keep new code clean.

The `Export Godot 4 Prototype` job is a stub until `project.godot` exists. Don't wire it up to a real export until M1 ships.

## Documentation

When you touch design, add it under [`docs/`](docs/README.md). When you touch process or in-flight work, add it under [`specs/`](specs/README.md). When in doubt, ask — or look at the rules of thumb in each folder's README.

After a notable change, add an entry to [`CHANGELOG.md`](CHANGELOG.md) under `## [Unreleased]`.

## Department / color mapping

The nine-department color scheme is canonical in two places:

- [`README.md`](README.md) — top-level overview table.
- [`docs/agent-directory.md`](docs/agent-directory.md) — taxonomy of the 133 roles, and the taxonomy authority (`D-017`) every other count derives from.

If you change a color or floor assignment, update both.

## Attribution

This project is an MIT-licensed adaptation of [alirezarezvani/claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor) via the [adamtasteslikegood/claude-code-tresor](https://github.com/adamtasteslikegood/claude-code-tresor) fork. Preserve the attribution block at the bottom of `README.md` and `docs/agent-directory.md` when editing those files.

*Last updated: July 2026*
