---
doc_id: BRANCHING-STRATEGY
title: 10110 TastesLike Plaza — Branching Strategy
tier: 3
authority: derived
status: ACTIVE
doc_set_version: 0.2.11
last_updated: 2026-08
owner: adamtasteslikegood
derives_from: [META-SPEC]
enforcement: asserted
gates: [Validate Specs:live, Check Sync Matrix:live]
weakest_claim: Convention, followed in practice
---

# Branching Strategy

> **One line:** `feature/*` `fix/*` `hotfix/*` → `dev` → `main`, Conventional
> Commits, merge commits.
>
> This is the **policy** doc — what the rules are and what enforces them.
> [`../CONTRIBUTING.md`](../CONTRIBUTING.md) is the **everyday** guide (how to
> branch, commit, and open a PR). If you only read one, read that one.

## 1. What is actually enforced

Most branching docs describe an aspiration. This section is the honest split.

| | Status |
|---|---|
| `feature/*` `fix/*` `hotfix/*` → `dev` → `main` | Convention, followed in practice |
| Conventional Commits | Convention |
| Merge commits, not squash (`D-023`) | **Enforced by repository settings** — squash and rebase merging are disabled. Verified 2026-07-26; §4 has the re-check command |
| `ci.yml` — `Validate Specs`, `Lint Python Bridge`, `Export Godot 4 Prototype` | **Runs on every push and PR to `main` and `dev`** |
| CodeQL (`Analyze (python)`, `Analyze (actions)`), GitGuardian | **Runs on PRs** |
| `claude-review.yml` — independent review | **Runs on PRs to `main` and `dev`**; see its `on:` block for the exact trigger set. Advisory, never a required check |
| Branch protection on `dev` | **Active** — ruleset `18798438`: PR required, deletion and force-push blocked, code scanning gates merge, and **`Spec Enforcement Matrix` is a required status check**. See §5 |
| Branch protection on `main` | **Not configured.** §5 "Still to apply" |
| Required status checks by name | **One:** `Spec Enforcement Matrix`, required since 2026-08-02. Every other CI job — `Validate Specs`, `Lint Python Bridge`, `Validate Agent Data`, `Validate Delivery Coordinates`, `Check Sync Matrix`, `Export Godot 4 Prototype` — still reports without gating the merge |
| CODEOWNERS gating | **No `CODEOWNERS` file exists** |
| Required linked issue | Convention at best |

`Validate Specs` is the one gate with real teeth today: it fails any PR that lets
the governed document set drift out of the hierarchy in
[`meta/META-SPEC.md`](meta/META-SPEC.md).

## 2. The branch model

```
feature/* | fix/* | hotfix/*  →  dev  →  main
        (your work)          (integration)  (release)
```

- **`main`** — release line. Updated only when cutting a release. No releases have
  been cut yet; the first tag lands when M8 is demonstrable in-engine.
- **`dev`** — integration branch, and the repository's **default branch**. All new
  work targets `dev`.
- **Short-lived branches** — `feature/<name>`, `fix/<name>`, `hotfix/<name>`,
  `docs/<name>`, `refactor/<name>`, `test/<name>`. Branch off `dev`, PR back into
  `dev`, delete after merge.
- **`claude/<task-slug>`** — task-assigned working branches for Claude Code
  sessions. Same flow; the session is told its branch name up front.

**Never commit directly to `main` or `dev`.** Go through a PR. This is convention
until §5 is applied — nothing currently blocks a direct push.

### Long-lived branches that exist right now

Worth knowing about, because they are not short-lived and will not simply merge:

| Branch | What it is |
|---|---|
| `feature/TO-1-prototype-initialization` | Carries a substantial `scripts/` tree (Jira PM daemon, ahead-behind tooling, shell/Python helpers) that does not exist on `dev`. **Check here before adding anything to `scripts/`** — an equivalent may already be written. |
| `sync-main-to-dev`, `adamtasteslikegood-patch-1`, `copilot/set-up-dependabot-yaml` | In-flight or stale. Prune when their PRs land or close. |

## 3. What runs on a pull request

From [`../.github/workflows/ci.yml`](../.github/workflows/ci.yml):

| Job | Hard fails on |
|---|---|
| `Validate Specs` | `python3 scripts/validate_specs.py` — missing or malformed frontmatter, unregistered documents, authority disagreeing with the registry, `doc_set_version` skew, broken relative links, unknown `D-nnn`, scene ids with no matching scene. Standard library only; no `pip install` step. |
| `Lint Python Bridge` | `black --check .` and `flake8 --select=E9,F63,F7,F82`. A third `flake8` pass runs `--exit-zero` and is advisory only. |
| `Export Godot 4 Prototype` | **Runs `godot --headless tests/smoke_test.tscn`** (`ci.yml:184`). Despite the name it does not export. It was a stub echo when this row was written; `project.godot` has existed since M1 and the job became a real gate in v0.2.8. Corrected 2026-08-02. |

Run all three locally before pushing. See
[`../CONTRIBUTING.md`](../CONTRIBUTING.md) § CI expectations for the commands.

## 4. Commits, PRs, and merges

Format and PR body structure live in [`../CONTRIBUTING.md`](../CONTRIBUTING.md) and
are not duplicated here. The policy points:

- **Conventional Commits**, lowercase, imperative, no trailing period —
  `type(scope): subject`. Types: `feat` `fix` `docs` `style` `refactor` `perf`
  `test` `build` `ci` `chore` `revert`.
- **PR titles follow the same format**, under 70 characters.
- **Merge commits — chosen, not defaulted into** (`D-023`). Squash **and rebase**
  merging are disabled in repository settings, so the merge button offers only the
  one that matches the policy. Every merge on `dev` is a merge commit
  (`Merge pull request #N from …`). The PR remains the unit of *review*; its commits
  land individually and the merge commit records the boundary.

  **This is live, mutable state — verify, don't inherit.** It was already wrong once:
  the setting changed between the `405` that proved it on 2026-07-26 and a review the
  same day that found all three merge buttons enabled. Last verified **2026-07-26**
  (`allow_merge_commit=true`, `allow_squash_merge=false`, `allow_rebase_merge=false`):

  ```bash
  gh api repos/adamtasteslikegood/10110TasteslikegoodPlaza \
    --jq '{merge: .allow_merge_commit, squash: .allow_squash_merge, rebase: .allow_rebase_merge}'
  ```

  If that output ever disagrees with this section, **fix the setting**, not the
  sentence — the policy is `D-023`, and the setting exists to enforce it.

  **Why, so nobody "fixes" this back.** The squash-only rule was inherited from
  `alirezarezvani/claude-code-tresor` along with the rest of this document — it was
  never a decision anyone made for this project. Squash merging has caused the owner
  real problems on other repositories, so merge commits are the deliberate choice
  here. Do not switch to squash because a linter, a bot, or a style guide suggests
  it; that reasoning is what put the wrong rule here in the first place.

  Practical consequences worth knowing rather than rediscovering:
  - Multi-commit PRs keep their history, so a well-structured commit series survives
    review and stays bisectable.
  - `dev` is **not** linear, and must not be required to be — see the note in §5.
  - Reverting a merged PR means `git revert -m 1 <merge-sha>`, not a plain revert.
- **Delete the branch after merge.**
- **A merged PR is finished.** Follow-up work starts a fresh branch off the latest
  `dev` — never stack new commits on already-merged history.

## 5. Branch protection

### What is active on `dev`

`dev` **is** protected — by a **repository ruleset**, not a classic branch-protection
rule. Ruleset `dev` (id `18798438`, `enforcement: active`) targets `~DEFAULT_BRANCH`,
which resolves to `dev`, re-verified against the API 2026-08-02. Rules as of 2026-08-02:

| Rule | Effect |
|---|---|
| `pull_request` | PR required to merge. `required_approving_review_count: 0`, `dismiss_stale_reviews_on_push: false`, `required_review_thread_resolution: false` |
| `deletion` | `dev` cannot be deleted |
| `non_fast_forward` | Force pushes blocked |
| `code_scanning` | CodeQL results gate the merge |
| `copilot_code_review` | Automatic Copilot review on PRs |
| `required_status_checks` | **`Spec Enforcement Matrix` must pass to merge.** Added 2026-08-02 on the owner's instruction, alongside `PLZG-135`. `strict_required_status_checks_policy: false` — see below |

**On `strict_required_status_checks_policy: false`.** An earlier revision of this
section claimed strict was left off because it "forces rebasing, and `D-023`
disables rebase merging." **That reasoning was wrong and is corrected here.**
Strict requires the head branch to contain the latest base-branch commits, which
is satisfied by **merging `dev` into the topic branch** just as well as by
rebasing; and disabling *Rebase and merge* governs how a PR is **completed**, not
how its head branch is **updated**. The two never conflicted.

The real trade-off is ordinary: strict means every PR must absorb `dev` again
whenever `dev` moves, so a busy base branch turns into a queue of update-merge
commits. Left off for that reason alone. **Turning it on is an owner call and
would not violate `D-023`.**

**One live disagreement inside this ruleset, recorded rather than silently
tolerated.** Its `pull_request` rule lists `allowed_merge_methods: ["merge",
"rebase"]`, so the ruleset **permits rebase**, while repository settings deny it
(`allow_rebase_merge: false`, `allow_squash_merge: false`, `allow_merge_commit:
true` — read from the API 2026-08-02). Nothing is broken today because settings
win, and `D-023` is satisfied. But `D-023` locates the guarantee in *settings*,
so re-enabling rebase there would meet no resistance from the ruleset. Tightening
`allowed_merge_methods` to `["merge"]` would make the two agree; that is an owner
call, not a drive-by.

**Why that one job and not the others.** It is the only gate whose failure means
another gate has stopped working. `tests/spec_enforcement_matrix.sh` asserts that
`validate_specs.py` FAILS on 24 broken fixtures; if it goes green having checked
nothing, `Validate Specs` can be passing vacuously and nothing else would say so.
During `PLZG-134` three of those five checks were found checking nothing while
`Validate Specs` exited 0 throughout. The other jobs report on the tree; this one
reports on a gate.

**`non_fast_forward` is not `required_linear_history`.** They are different rules and
only the latter conflicts with `D-023`. The warning below still holds and is not
currently violated.

> ### The trap that hid this
>
> `GET /repos/{owner}/{repo}/branches/dev/protection` returns **`404 Branch not
> protected`** for a branch protected by a ruleset. The 404 means "no *classic*
> protection", not "no protection". Rulesets live on a separate API surface:
>
> ```bash
> gh api repos/adamtasteslikegood/10110TasteslikegoodPlaza/rulesets
> gh api repos/adamtasteslikegood/10110TasteslikegoodPlaza/rules/branches/dev
> ```
>
> This document asserted "not yet configured" on the strength of that 404. Check both
> surfaces before concluding a branch is unprotected.

### Still to apply

Genuinely not configured — these remain instructions, not description.

**More required status checks on `dev`.** Partially done: `Spec Enforcement
Matrix` was made required on 2026-08-02 (§5), because it is the one gate whose
failure means another gate has stopped working. The rest still only report.
Candidates to add to the ruleset's `required_status_checks`: `Validate Specs`,
`Lint Python Bridge`.

**CODEOWNERS gating.** No `CODEOWNERS` file exists; nothing enforces reviewer
assignment.

**`main` has no ruleset or protection at all.** Settings → Rules → New ruleset,
targeting `main`:

- Require a pull request before merging; require approvals: 1; dismiss stale reviews
- Require status checks to pass, branches up to date. Required checks:
  `Validate Specs`, `Lint Python Bridge`, `Export Godot 4 Prototype`,
  `Analyze (python)`, `Analyze (actions)`
- Require conversation resolution
- Restrict deletions; block force pushes; no bypass, including administrators

> **Do not enable "Require linear history".** It is incompatible with merge commits
> (`D-023`) and would block every merge. It belongs to a squash-only workflow, which
> this project has deliberately not adopted. The upstream original told you to enable
> it — that instruction was never valid here.

`dev`'s ruleset already covers deletion, force pushes, PR-required, code
scanning, and one required status check by name — the remaining gap is the
*other* CI jobs, above. Keep
approvals at 0 until a second contributor joins.

Use the exact job names above — GitHub matches required checks by name, and the
invented names this document previously carried (`quality-gates`, `validate-pr`,
`production-build`, `validate-release-pr`) match nothing in this repository.

## 6. Bumping the `claude-code-tresor` submodule

The agent layer is a gitlink, so a submodule change is a two-step commit. Work in
the fork as its own repository, then record the new pin here:

```bash
cd claude-code-tresor
# branch, commit, push to the fork's origin
cd ..
git add claude-code-tresor
git commit -m "chore: bump claude-code-tresor submodule"
```

Never edit submodule contents from the parent repo and commit the dirty gitlink.

### The fork's own branch model

`adamtasteslikegood/claude-code-tresor` mirrors this repo: `dev` integrates, `main`
releases.

| Fork branch | Role |
|---|---|
| `10110TLGP/dev` | Default branch, and **what the pin tracks** (`D-021`). Bumps fast-forward to its head. |
| `10110TLGP/main` | **Reserved release branch** (`D-022`). Dormant until the fork has a `release.yml` and tagged releases. Not a pin target — don't bump to it, and don't prune it as stale. |
| `dev`, `main` | The pre-fork upstream branches. Not used by this project. |

The two `10110TLGP/*` branches currently diverge in **history only** — one commit
each side of merge-base `4b68050`, because each merged the same upstream state by a
different route. Their trees are byte-identical (`b7aee19`), so the first
`dev` → `main` release merge will not fast-forward but cannot conflict.

Closed in [`meta/spec-drivers-v0.2.5.md`](meta/spec-drivers-v0.2.5.md) §4.7.

## 7. Release flow

Not automated, and not yet exercised — there are no tags.

1. `dev` is ready: features merged, `CHANGELOG.md` `[Unreleased]` promoted to a
   version section, `doc_set_version` consistent across the governed set.
2. PR `dev` → `main`. Merge commit, per §4.
3. Tag `main` and write GitHub release notes from the CHANGELOG section.

First tag is cut when **M8 is demonstrable in-engine** — the exit criterion in
[`meta/spec-drivers-v0.2.5.md`](meta/spec-drivers-v0.2.5.md) §5.

## 8. Intended, not yet active

Nothing here is enforced. Do not cite it as a rule or block a PR on it.

| Workflow | Would do |
|---|---|
| `pr-into-dev.yml` | Branch-name validation, PR-title validation, linked-issue check on PRs into `dev` |
| `dev-to-main.yml` | Source-branch validation, CHANGELOG check, version consistency on `dev` → `main` |
| `release.yml` | Version-format validation, CHANGELOG extraction, GitHub release, tagging |

Also absent: branch protection (§5), a `CODEOWNERS` file, and any enforcement of
linked issues.

Building these is deliberately deferred — there is no application code to gate yet,
and the gate that matters now (`Validate Specs`) already exists.

## 9. Provenance

This document was adopted from `alirezarezvani/claude-code-tresor` and initially
kept its upstream text, which described a different project ("ClaudeForge"), linked
to the upstream issue tracker, and required four CI workflows that have never
existed here. Rewritten in doc set v0.2.6 to describe **this** repository. Where
this document and the upstream original differ, this one is simply correct — there
is nothing to reconcile.

**Inherited rules are the failure mode to watch for in this file.** Three survived the
first rewrite and had to be caught separately:

| Inherited rule | How it was caught | Outcome |
|---|---|---|
| Required checks named `quality-gates`, `validate-pr`, `production-build`, `validate-release-pr` | Read against `.github/workflows/` — none exist | Replaced with the real job names. GitHub matches required checks by name, so the inherited list would have silently matched nothing |
| "Squash and merge exclusively… no merge commits" | The merge API returned `405 Squash merges are not allowed on this repository` | Reversed to merge commits and registered as `D-023`, with the rationale recorded so it is not re-inherited |
| "Branch protection: not yet configured" | `/branches/dev/protection` → `404 Branch not protected` was read as "unprotected". `dev` is protected by ruleset `18798438` | §5 rewritten to describe the active ruleset. **The 404 means no *classic* protection, not no protection** — rulesets are a separate API surface |

All three were plausible-sounding rules that were simply false here. When editing this
file, check a claim against the repository before keeping it — inheritance is not
evidence.

**Second failure mode: a claim that was true when checked, and then wasn't.** The
`405` above was real evidence on 2026-07-26 — and within hours a review found all
three merge buttons enabled again, because repository settings had changed underneath
the sentence. Verified-once is not verified.

**Third failure mode: the right question asked of the wrong endpoint.** The branch
protection claim was checked — against `/branches/dev/protection`, which returns a
404 for ruleset-based protection. A confident negative from an API that cannot see
the thing you are asking about is worse than no check at all, because it *feels* like
evidence. Both the original claim and the first review pass made this exact mistake.
When a check returns "nothing configured," confirm the endpoint can see the kind of
configuration you are looking for.

**Fourth failure mode: a flag that reads correctly and does not exist.**
`.github/workflows/claude-review.yml` passed `--comment` (and `--fix`) through
`claude_args`, which is forwarded verbatim to the Claude Code CLI. Those are
`claude-code-action` *inputs*, not CLI options, so every run of the independent
review died with `unknown option '--comment'` before reviewing anything. Because the
job is advisory and `continue-on-error`, the workflow stayed green and the red check
read as noise — the review had never run at all. Verified against `claude --help`:
`--allowed-tools` / `--disallowed-tools` exist; `--comment` and `--fix` match nothing.
Same shape as the rows above — a name that sounds right, never checked against the
tool that receives it. **When a workflow forwards arguments to a binary, check them
against that binary's `--help`, not against the action's documentation.**

**Fifth failure mode: a second copy of repository state, in the one file that is
expensive to correct.** The same `claude-review.yml` carried its own description of
the repo — *"a governed document set, not an application — there is no Godot project
and no Node"* — and handed it to every reviewer as fact. It was accurate when
written and false the moment M1 landed. Ordinary staleness, except for the trap
underneath it: `claude-code-action` refuses to run when the workflow differs from the
copy on the default branch, so **any PR that corrects this file cannot be reviewed by
the reviewer it configures**, and the check still reports a fast green (observed on
#17 run 3 and #19). The copy most likely to rot was also the copy most costly to fix,
and the failure was silent in both directions.

Fixed by deleting the copy rather than refreshing it: the prompt now states review
*method* and points at `CLAUDE.md` for repository *state*, with `CLAUDE.md` named as
the winner if they ever disagree. **Configuration should reference the source of
truth, not restate it** — a rule the doc set already applies to itself, which took
five rounds to notice applied to CI as well.

So any claim in this document about **live, mutable state** — merge settings, branch
protection, which checks are required — carries a verification date and the command
to re-run. Two things follow:

1. When the command disagrees with the doc, ask which one is *supposed* to be right.
   Here the answer was the doc: the setting was changed to match `D-023`, not the
   sentence weakened to match the setting.
2. Prefer claims that a script could check. `Validate Specs` catches doc-to-doc drift;
   nothing yet catches doc-to-GitHub-settings drift, which is why these carry dates.

---

**Issues:** [GitHub Issues](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues)
· **Related:** [`../CONTRIBUTING.md`](../CONTRIBUTING.md) ·
[`meta/META-SPEC.md`](meta/META-SPEC.md) · [`../CHANGELOG.md`](../CHANGELOG.md)

*Last updated: August 2026*
