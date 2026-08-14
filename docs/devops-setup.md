---
doc_id: DEVOPS-SETUP
title: DevOps Setup Guide
tier: 3
authority: derived
status: ACTIVE
doc_set_version: 0.2.12
last_updated: 2026-08
owner: adamtasteslikegood
derives_from: []
enforcement: n/a
gates: []
---

> **Authority: none.** Tier 3 `derived`, documents setup procedures for
> the five devops capabilities added in the devops-foundation PR.
> Authoritative over nothing; the CI pipeline, release config, and
> workflow files are the source of truth.

# DevOps Setup Guide

Five capabilities that keep this repository organized: model routing,
CI pipeline, issue triage, scheduled routines, and release automation.

## 1. Model Routing (`claude-code-router`)

Routes Claude Code requests by type to different models. Background
requests (subagents, background jobs) use a cheaper model; foreground
stays on Opus.

**One-time setup:**

```bash
npm install -g @musistudio/claude-code-router
```

**Usage:** Start Claude Code through the router instead of directly:

```bash
ccr code
```

**Config:** `.claude-code-router.json` in the project root defines
routing rules. The default config routes background requests to
Sonnet 5 and keeps foreground on Opus 4.6.

**Coexistence:** The native `advisorModel` setting in
`~/.claude/settings.json` operates at a different layer and is
unaffected by the router.

## 2. CI Pipeline

`.github/workflows/ci.yml` runs on push/PR to `main` and `dev`.

**Jobs** (8 total):

| Job | What it checks |
|-----|----------------|
| `validate-specs` | Governed document frontmatter and registry |
| `validate-delivery-coordinates` | Delivery coordinate consistency |
| `check-sync-matrix` | check_sync.sh regression matrix |
| `spec-enforcement-matrix` | Enforcement-axis non-vacuity |
| `validate-agent-data` | agents.json matches submodule |
| `python-lint` | Black formatting + flake8 syntax errors |
| `bridge-tests` | pytest bridge/tests/ (76 tests) |
| `godot-build` | Import + headless smoke test (cached binary) |

**Godot caching:** The Godot binary is cached by version. On cache
hit the ~80MB download is skipped. To bust the cache (e.g. after a
Godot version bump), update `GODOT_VERSION` in ci.yml and the cache
key changes automatically.

## 3. Issue Triage

`.github/workflows/issue-triage.yml` runs on `issues: [opened]` and
auto-labels by title pattern:

| Label | Pattern |
|-------|---------|
| `ci-review-followup` | "no PLZG", "no CHANGELOG", "has no...entry" |
| `bridge` | "bridge", "domain session", "websocket" |
| `documentation` | "CLAUDE.md", "doc", "spec", "META-SPEC" |
| `pr-followup` | "PR #NNN" |

Labels are created automatically on first match via the GitHub API
(they must exist as repository labels first).

## 4. Claude Scheduled Routines

Three routines in `.claude/routines/`:

| Routine | Schedule | Purpose |
|---------|----------|---------|
| `daily-issue-triage.md` | Weekdays 9am | Dedup and close fixed issues |
| `weekly-doc-scan.md` | Mondays 10am | Catch stale doc claims |
| `weekly-submodule-check.md` | Wednesdays 10am | Detect drifted submodule pin |

**Prerequisite:** Claude Code subscription with routines enabled.
Routines run as Claude Code sessions on the configured schedule.

## 5. Release Automation (release-please)

Google's `release-please` reads conventional commits on `main` and:

1. Opens a Release PR with generated CHANGELOG entries
2. When merged, creates a GitHub Release with a semver tag

**Config files:**

- `release-please-config.json` — release type, changelog section mapping
- `.release-please-manifest.json` — current version (`0.1.22`)
- `.github/workflows/release-please.yml` — triggered on push to `main`

**Constraints:**

- Only triggers on `main` (not `dev`) — the dev-to-main merge flow
- Uses merge commits per D-023 (squash/rebase disabled)
- Manages the application version axis only (`0.1.y`), not the
  document set version (`0.2.x`)

**Workflow:** conventional commits land on `dev` via feature PRs.
When `dev` merges to `main`, release-please creates a Release PR.
Merging that PR publishes the GitHub Release.

*Last updated: August 2026*
