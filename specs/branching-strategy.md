---
doc_id: BRANCHING-STRATEGY
title: 10110 TastesLike Plaza — Branching Strategy
tier: 3
authority: derived
status: ACTIVE
doc_set_version: 0.2.6
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [META-SPEC]
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
| Merge commits (squash merging is disabled in settings) | **Enforced by repository settings** |
| `ci.yml` — `Validate Specs`, `Lint Python Bridge`, `Export Godot 4 Prototype` | **Runs on every push and PR to `main` and `dev`** |
| CodeQL (`Analyze (python)`, `Analyze (actions)`), GitGuardian | **Runs on PRs** |
| `gemini-*.yml` triage / review / plan-execute | **Runs on PRs, issues, `@gemini-cli` mentions, and a schedule** |
| Branch protection rules | **Not configured.** §5 is the setup, not a description |
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
| `Export Godot 4 Prototype` | Nothing — a stub echo until `project.godot` exists. Don't wire it to a real export before M1. |

Run all three locally before pushing. See
[`../CONTRIBUTING.md`](../CONTRIBUTING.md) § CI expectations for the commands.

## 4. Commits, PRs, and merges

Format and PR body structure live in [`../CONTRIBUTING.md`](../CONTRIBUTING.md) and
are not duplicated here. The policy points:

- **Conventional Commits**, lowercase, imperative, no trailing period —
  `type(scope): subject`. Types: `feat` `fix` `docs` `style` `refactor` `perf`
  `test` `build` `ci` `chore` `revert`.
- **PR titles follow the same format**, under 70 characters.
- **Merge commits.** Squash merging is **disabled** in repository settings, and every
  merge on `dev` to date is a merge commit (`Merge pull request #N from …`). The PR
  is still the unit of review; its commits land individually and the merge commit
  records the boundary.
  *This corrected an inherited claim.* The upstream original said "squash and merge
  exclusively, no merge commits" — the repository setting disproves it. If you want
  squash instead, enable it in Settings → General → Pull Requests first, then change
  this line; don't change this line and hope the setting follows.
- **Delete the branch after merge.**
- **A merged PR is finished.** Follow-up work starts a fresh branch off the latest
  `dev` — never stack new commits on already-merged history.

## 5. Branch protection — the setup to apply

Not yet configured. These are instructions, not a description of current settings.

**`main`** — Settings → Branches → Add rule, pattern `main`:

- Require a pull request before merging; require approvals: 1; dismiss stale reviews
- Require status checks to pass, branches up to date. Required checks:
  `Validate Specs`, `Lint Python Bridge`, `Export Godot 4 Prototype`,
  `Analyze (python)`, `Analyze (actions)`
- Require conversation resolution
- Restrict deletions; block force pushes; no bypass, including administrators

> **Do not enable "Require linear history"** while squash merging is disabled — the
> two are incompatible, and turning it on would block every merge. It belongs with a
> squash-only workflow, not this one.

**`dev`** — same, pattern `dev`, with:

- Require approvals: 0 (raise to 1 if a second contributor joins)
- Required checks: `Validate Specs`, `Lint Python Bridge`
- Restrict deletions; block force pushes (again, **not** linear history)

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

---

**Issues:** [GitHub Issues](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues)
· **Related:** [`../CONTRIBUTING.md`](../CONTRIBUTING.md) ·
[`meta/META-SPEC.md`](meta/META-SPEC.md) · [`../CHANGELOG.md`](../CHANGELOG.md)

*Last updated: July 2026*
