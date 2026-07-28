---
name: review-specs
description: Review a PR or branch in this repo the way its defects actually appear — stale repository-state claims, decision-register authority violations, broken section cites, and governed-document validation. Use when asked to review a PR, review a diff, or check changes before merging here. Not a general code review; this repo is a governed document set.
---

# Reviewing this repo

The interactive counterpart to `.github/workflows/claude-review.yml`. Same discipline, run by a session with network and `gh` rather than by CI.

**Why this exists separately from a generic review skill.** The Godot project is small and there is no Node here — no web surface, no request handling, no ORM. SQL injection, race conditions and N+1 queries have nothing to bite on. What breaks in this repo is *claims* — assertions about how the repository is configured, and bookkeeping about who was entitled to decide what. GDScript under `autoload/`, `scenes/` and `tests/` still deserves an ordinary read for correctness; it is just not where the defects have been.

**Not a governed document.** It lives in `.claude/` deliberately. Anything under `specs/` must be registered in `specs/meta/doc-registry.json` and declare an `authority`, and *which document may hold authority* is the open question in issue #11. A review checklist should not need that settled first.

---

## 0. Orient

Read `CLAUDE.md` and `specs/meta/META-SPEC.md`. Establish base branch and diff:

```bash
gh pr view <N> --json baseRefName,headRefOid,state,headRefName
git fetch origin <base> --quiet
DIFF_BASE=$(git merge-base origin/<base> HEAD)
git diff "$DIFF_BASE" --stat
```

Check PR state first. A branch here can be reused across PRs, so confirm which PR you are actually reviewing.

## 1. Validator — non-negotiable

```bash
python3 scripts/validate_specs.py
```

Stdlib only, no `pip install`. Report the exact output. Any new `.md` under a governed tree must appear in `doc-registry.json` as `documents` or `exempt`, or this hard-fails.

## 2. Repository-state claims — the highest-yield check

This document set asserts things about repository configuration. Those assertions rot. Three failure modes, all of which have happened here (`specs/branching-strategy.md` §9):

1. **Inherited and never checked** — carried from `alirezarezvani/claude-code-tresor`, plausible-sounding, false.
2. **Checked once, then stale** — real cited evidence; the state moved underneath it afterwards.
3. **Checked against an endpoint that cannot see the answer** — the worst, because the response looks like evidence.

When the diff asserts anything about branch protection, merge strategy, required checks or labels, verify it live:

```bash
gh api repos/adamtasteslikegood/10110TasteslikegoodPlaza \
  --jq '{merge:.allow_merge_commit, squash:.allow_squash_merge, rebase:.allow_rebase_merge, delete_branch:.delete_branch_on_merge}'
gh api repos/adamtasteslikegood/10110TasteslikegoodPlaza/rulesets
gh api repos/adamtasteslikegood/10110TasteslikegoodPlaza/rules/branches/dev
gh api repos/adamtasteslikegood/10110TasteslikegoodPlaza/rules/branches/main
```

> **The trap.** `GET /branches/{branch}/protection` returns `404 Branch not protected` for a branch protected by a **ruleset**. That 404 means "no *classic* protection", not "no protection". Never conclude a branch is unprotected from it. `dev` is protected by ruleset `18798438`; `main` currently has nothing.

Required status checks match **by name**. If the diff names them, confirm against `.github/workflows/ci.yml`: `Validate Specs`, `Lint Python Bridge`, `Export Godot 4 Prototype`.

## 3. Governance and authority

- **A new or changed `D-nnn`:** check the Origin document's `authority` permits deciding, per the META-SPEC §2 table. `derived`, `summary`, `research` and `historical` originate **nothing**. A decision from an unentitled origin must be `PROPOSED`, not `LOCKED`. This has already happened seven times — issue #11. Check every time.
- **Tier ladder:** tier 0 `specs/meta/` governs · tier 1 `docs/storyboard-week1.md` owns concept · tier 2 `docs/designs/*` owns implementation · tier 3 `specs/roadmap.md` sequences · tier 4 decides nothing. **Lower tier wins.**
- **Never reconcile two disagreeing documents.** Say so and say it belongs in the open-conflict register (`specs/meta/spec-drivers-v0.2.5.md` §4). META-SPEC §4 forbids drive-by reconciliation.
- **Agent counts** derive from `docs/agent-directory.md` (D-017). 133 distinct roles; 141 files = 8 + 133. Both right — flag text using one while meaning the other.

## 4. Cross-reference integrity

- Section cites must resolve to a real heading. `§4.2` is wrong when the target is `## 4.` plus a numbered list — write `§4, step 2`.
- `CHANGELOG.md`: read `[Unreleased]` against itself. An entry opening a conflict while an older bullet in the same section still says everything is resolved is a real defect, and it will sit outside the diff.
- The decision register table sorts by ascending `D-nnn`.
- Every relative link resolves.

## 5. Claims about the git graph

Verify the **inference**, not just the facts. `dev`'s head is a merge commit under `D-023`, so *every* branch cut from `dev` sits on top of already-merged history. That observation alone proves nothing. The discriminating check:

```bash
git log --format='%h parents=%p %s' -5 HEAD
```

Parent == base branch head ⇒ fresh branch. A finding built from individually-true facts can still be wrong.

## 6. Python

Anything under `scripts/` or `*.py` must pass `flake8 . --select=E9,F63,F7,F82`. `generate_report.py` and `post_to_confluence.py` read `./.env` directly and raise `KeyError` when a var is missing — known and intentional, do not flag.

## 7. Cross-model pass (optional)

```bash
codex exec "<review prompt>" -C "$(git rev-parse --show-toplevel)" -s read-only \
  -c 'model_reasoning_effort="high"' < /dev/null
```

Set the Bash `timeout` parameter to `300000`. **Codex's sandbox has no network** — it cannot reach `api.github.com`, so it can never check §2. Treat agreement as confirmation of *reasoning*, never of *live state*.

## 8. Posting findings

Format each as `**[CRITICAL|INFORMATIONAL] (confidence: N/10)** — problem`, then the evidence you ran, then the fix.

Quote the line or command output that motivates the finding. If you cannot quote it, you have not verified it: drop it, or mark it below 7/10 and say what you could not check.

`gh` specifics that will bite:

| | |
|---|---|
| Inline comments | Only on lines **inside a diff hunk**. Compute ranges from `gh pr diff <N>` hunk headers; anchor elsewhere and say where the real line is. |
| `commit_id` | Must be the **full 40-char** sha. A short sha returns `422 commit_id is not part of the pull request`. |
| Self-authored PRs | `REQUEST_CHANGES` is rejected. Use `event: COMMENT`. |
| `gh pr comment` | Takes no `-q` / `--jq`. It prints help and posts nothing. Use `gh api .../issues/<N>/comments` when you need a filter. |
| Many comments at once | `POST /pulls/<N>/reviews` with a `comments` array — one review, not N notifications. |

State plainly what you could not verify. Never imply coverage you do not have.

## 9. Follow-ups

Do not leave real work in a comment thread where it dies with the PR.

- **Issue** — work still to be done.
- **Discussion** — settled knowledge worth keeping that is not work.

Check open issues first; do not duplicate #11 (meta-layer authority), #12, #13, #14.

## Do not

- Edit `specs/meta/**` as a drive-by. Raise it instead.
- Re-status, reword or add a `D-nnn` row as a review fix.
- Change a storyboard beat — that is a concept change needing human sign-off.
- Bump `doc_set_version` or the submodule pointer.
- Recommend commands this repo does not have. `npm test` and the whole Node toolchain are still absent. `godot .`, `godot --headless --import` and `godot --headless tests/smoke_test.tscn` are real as of v0.2.8 — check `CLAUDE.md` § Repository state before asserting either way, and never carry this list forward as settled.
- Flag `{{rolels}}`-style template artifacts outside the section being edited; they are known upstream leftovers.
