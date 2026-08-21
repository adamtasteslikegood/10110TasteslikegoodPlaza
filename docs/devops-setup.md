---
doc_id: DEVOPS-SETUP
title: DevOps Setup Guide
tier: 3
authority: derived
status: ACTIVE
doc_set_version: 0.2.13
last_updated: 2026-08
owner: adamtasteslikegood
derives_from: []
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: "Three routines in `.claude/routines/`:"
---

> **Authority: none.** Tier 3 `derived`, documents setup procedures for
> the five devops capabilities added in the devops-foundation PR.
> Authoritative over nothing; the CI pipeline, release config, and
> workflow files are the source of truth. State claims asserted as of
> `last_updated`; nothing re-checks them automatically.

# DevOps Setup Guide

Five capabilities that keep this repository organized: model routing,
CI pipeline, issue triage, scheduled routines, and release automation.

## 1. Model Routing (`claude-code-router`)

Routes Claude Code requests through a local gateway that can direct
traffic to different upstream providers and models. Configured via a
browser-based management UI, not a project-level config file.

**One-time setup:**

```bash
npm install -g @musistudio/claude-code-router
ccr ui
```

This starts the background service and opens the management UI at
`http://127.0.0.1:3458`. From there:

1. Add an upstream provider and at least one model.
2. Create a CCR client key under **API Keys**.
3. Configure routing rules (e.g. route background requests to Sonnet).
4. Confirm the gateway is running under **Server** (default:
   `http://127.0.0.1:3456`).

**Launching Claude Code through a profile:**

```bash
ccr "Claude - Work" cli
```

Profiles are created in the **Agent Profiles** section of the UI.
Each profile can specify a model, surface (CLI/App), and routing
overrides.

**Service commands:**

| Command | What it does |
|---------|-------------|
| `ccr start` | Start background service + gateway |
| `ccr ui` | Start service and open management UI |
| `ccr stop` | Stop background service |
| `ccr serve` | Run in foreground (for process supervisors) |

**Config location:** `~/.claude-code-router/config.sqlite` (managed
via the UI, not hand-edited).

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

Labels must exist as repository labels before the workflow can apply
them. The four labels were created as part of the devops-foundation
setup; new patterns require a matching `gh label create` first.

## 4. Claude Scheduled Routines

Three routines in `.claude/routines/`:

| Routine | Schedule | Purpose |
|---------|----------|---------|
| `daily-issue-triage.md` | Weekdays 9am | Dedup and close fixed issues |
| `weekly-doc-scan.md` | Mondays 10am | Catch stale doc claims |
| `weekly-submodule-check.md` | Wednesdays 10am | Detect drifted submodule pin |

**Setup required:** These files are prompt templates, not
self-registering. To activate each routine, use `/schedule` in
Claude Code or create it through the routines UI, pasting the
prompt from the corresponding `.md` file. The `cron` frontmatter
documents the intended schedule.

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
- Manages the application version axis only (currently `0.1.x`),
  not the document set version (currently `0.2.x`). A `feat` commit
  bumps the minor, so the next feature release becomes `0.2.0`.

**Workflow:** conventional commits land on `dev` via feature PRs.
When `dev` merges to `main`, release-please creates a Release PR.
Merging that PR publishes the GitHub Release.

*Last updated: August 2026*
