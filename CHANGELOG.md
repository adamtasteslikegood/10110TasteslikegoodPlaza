# Changelog

All notable changes to **10110 TastesLikegood Plaza** are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries land under `[Unreleased]` as work is merged and graduate to a numbered
section at release time. PR references in parentheses.

## [Unreleased]

### Added
- `CLAUDE.md` — onboarding guide for future Claude Code sessions. Covers the
  4-layer architecture, the three Godot autoloads (`AgentRegistry`,
  `GameEvents`, `GameState`), the M1 → M4 → M8 critical path, the
  `claude-code-tresor` submodule workflow, CI lint rules, the two-doc-tree
  convention (`Docs/` legacy 3D vs. `docs/designs/` active 2.5D), and the
  prescribed Godot project layout. (PR #4)
- This `CHANGELOG.md`. (PR #4)
- `docs/designs/2.5D-RPG-Prototype.md` — promoted CEO plan (status:
  `PROMOTED`, dated 2026-04-27) pivoting the prototype from full 3D
  first-person to a 2.5D top-down RPG (Pokémon / Stardew Valley style).
  Accepted scope: one generic cardboard sprite tinted by department color,
  one generic silhouette portrait, "Wait or Delegate" UX for long-running
  tasks, and typewriter-effect pseudo-streaming over full JSON responses.
  True streaming, unique per-agent sprites, and 3D first-person navigation
  deferred. (PR #3)
- CI workflow (`.github/workflows/ci.yml`) on push/PR to `main` and `dev` —
  Python lint job (`black --check`, strict `flake8` subset for E9/F63/F7/F82,
  advisory full lint) and a Godot 4 export stub. (PR #3)
- Gemini CLI automation suite — `gemini-dispatch`, `gemini-invoke`,
  `gemini-review`, `gemini-plan-execute`, `gemini-triage`, and
  `gemini-scheduled-triage` workflows with matching `.toml` command prompts
  under `.github/commands/` and `.gemini/commands/`. Triggered by
  `@gemini-cli` mentions and a schedule. (PR #3)
- Atlassian glue scripts — `generate_report.py` queries Jira project `TO`
  for issues updated in the last 7 days, buckets by status, and writes
  `report.md`; `post_to_confluence.py` converts that to HTML and posts it
  as a child of Confluence page `15925249` (fallback `15695959`). Both read
  `./.env` directly. (PR #3)
- `claude-code-tresor` git submodule — canonical agent layer with 137+
  agent `.md` files across nine departments plus 8 production-ready core
  agents. (PR #3)
- `LICENSE` — MIT. (PR #3)
- `.gitignore`. (PR #3)
- Initial planning docs under `Docs/` — `00_PROJECT_OVERVIEW.md`,
  `01_WEEK1_STORYBOARD.md`, `02_PROTOTYPE_ROADMAP.md`,
  `03_PM_TASK_TRACKER.md`, `04_QUICK_REFERENCE.md`,
  `BRANCHING_STRATEGY.md`, `10110_TastesLikePlaza_DIRECTORY.md`, plus
  `plaza_build_steps.html` and `plaza_godot_architecture.svg`. (PR #1)
- `README.md` with attribution to upstream
  [alirezarezvani/claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor)
  via the [adamtasteslikegood/claude-code-tresor](https://github.com/adamtasteslikegood/claude-code-tresor)
  fork. (PR #1)

### Changed
- `.gitmodules` — fix `claude-code-tresor` URL from the relative
  `../claude-code-tresor.git` to the canonical
  `https://github.com/adamtasteslikegood/claude-code-tresor.git` so fresh
  clones can initialize the submodule with
  `git submodule update --init --recursive`. (PR #4)
- `CLAUDE.md` — updated the `CHANGELOG.md` note in "Two doc trees" now that
  this file exists as a real project changelog. (PR #4)
- `CLAUDE.md` — refreshed the **Branching** section: `dev` is now the
  integration branch (caught up to `main` via PR #3) and the merged
  `sync-main-to-dev` line was dropped. (PR #4)

### Removed
- Stray `@googleworkspace/cli` `CHANGELOG.md` (accidental import) — removed
  during PR #3 review feedback. This file replaces it.
- `.omg/state/learn-watch.json` — removed during PR #3 review.
- `sync-main-to-dev` branch — deleted from the remote after PR #3 merged
  it into `dev`. (PR #4 cleanup)

### Notes
- `dev` was fast-forwarded to match `main` via PR #3 (`sync-main-to-dev` →
  `dev`). `dev` is once again the integration branch per
  `Docs/BRANCHING_STRATEGY.md`.
- No tagged releases yet. First tag will follow once the M1 → M4 → M8
  critical-path prototype is demonstrable in-engine.

## Pull request history

- **PR #4** — *docs: add CLAUDE.md guide for future Claude Code sessions* —
  open against `dev`. Adds `CLAUDE.md`, this `CHANGELOG.md`, fixes
  `.gitmodules` submodule URL, refreshes branching notes, and removes the
  merged `sync-main-to-dev` branch.
- **PR #3** — *chore: Sync latest progress (Docs & CI) from main to dev* —
  merged 2026-05-14. Brought `dev` up to `main` (2.5D plan, gemini
  workflows, CI, Atlassian scripts, submodule, LICENSE). 22 files,
  +2246 lines.
- **PR #2** — *Added README.md and other changes* — closed without merge
  (superseded by PR #3 sync flow).
- **PR #1** — *Added README.md* — merged 2026-04-24. Initial planning docs
  and README on `dev`.
