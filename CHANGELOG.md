# Changelog

All notable changes to **10110 TastesLikegood Plaza** are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries land under `[Unreleased]` as work is merged and graduate to a numbered
section at release time. PR references in parentheses.

## [Unreleased]

### Added
- **A meta-spec layer at `specs/meta/`** — one authoritative answer to "which
  document wins", replacing three documents that each described themselves as the
  thing to align to.
  - `META-SPEC.md` — the constitution. A five-tier ladder (0 meta · 1 concept ·
    2 implementation and reference · 3 derived plans · 4 summaries and inputs), an
    `authority` vocabulary, the conflict protocol ("never silently reconcile"), and
    the binding rules for agents.
  - `concept-driver.md` — names `docs/storyboard-week1.md` the sole origin of
    concept decisions, defines the dual-layer scene contract, and indexes all 18
    beats as `SB-01`–`SB-18`.
  - `decision-register.md` — every locked decision as a citable `D-nnn` with a
    named origin document, deduplicated from the three places they previously lived
    in parallel.
  - `spec-drivers-v0.2.5.md` — v0.2.5 deliverables, the
    `D-nnn → SB-nn → M1–M8 → TO-nnn` traceability chain, the round plan, and the
    open-conflict register.
  - `spec-frontmatter.schema.json` and `doc-registry.json` — the machine-readable
    contract and index. Authority is now a lookup, not an argument.
- **`scripts/validate_specs.py` and a `Validate Specs` CI job.** Standard library
  only — no new CI dependencies. Reads its rules from the published schema and
  registry so the gate cannot drift from the contract. Fails the build on missing
  or malformed frontmatter, unregistered documents, authority that disagrees with
  the registry, downward `derives_from`, more or fewer than one concept origin,
  `doc_set_version` skew, broken relative links, unknown `D-nnn` claims, and scene
  ids with no matching scene.
- YAML frontmatter (`doc_id`, `tier`, `authority`, `status`, `doc_set_version`,
  `last_updated`, `derives_from`, `decides`) on all 17 governed documents.
- Stable `SB-nn` ids on every storyboard scene heading, so milestones, tasks, and
  Jira issues can cite a beat instead of paraphrasing it.

### Fixed
- **`specs/aligned-spec-v0.2.5.md` §01.3 contradicted the storyboard.** It invented
  a 14-scene spine — openly labelled a "proposed reconstruction" written when the
  real file could not be retrieved — that omits Day 0 entirely, relocates the
  assistant's introduction, drops the player-configuration and coding-lesson beats,
  and invents an RA/QM department scene out of explicitly deferred scope. Until now
  that document was named the source of truth by `CLAUDE.md`, `specs/README.md`, and
  `Docs/files/README.md`. Reconciled in favour of the storyboard; the side-by-side
  is in `specs/meta/concept-driver.md` §4.
- Removed 64 lines of pasted chat-sidebar text — a project file list, recent
  conversation titles, and a verbatim memory dump — from the top of
  `specs/aligned-spec-v0.2.5.md`, above the document's real H1.
- Eleven broken relative links, caught by the new gate on its first run: nine in
  `docs/agent-directory.md` pointing at upstream-fork paths that live in the
  `claude-code-tresor` submodule or nowhere, and two in
  `specs/branching-strategy.md` (`./CONTRIBUTING.md` is at the repo root;
  `GITHUB_WORKFLOWS.md` does not exist). Cleaned the `{{rolels}}` / `{{charators}}`
  template placeholders in the sections touched.

### Changed
- `LICENSE` replaced with MIT (© 2026 Adam Schoen), resolving the long-standing
  conflict with the Apache-2.0 boilerplate the file previously carried. `README.md`
  and `CLAUDE.md` already said MIT, as does the upstream attribution. Registered as
  `D-018`.
- `specs/aligned-spec-v0.2.5.md` demoted from "current source-of-truth for spec
  details" to a tier-4 research input (`authority: research`,
  `status: SUPERSEDED`), with a banner pointing at the meta layer. Retained for its
  findings, the Document A bridge architecture, and the Document B taxonomy.
- `CLAUDE.md`, `specs/README.md`, `docs/README.md`, and `Docs/files/README.md`
  repointed at `specs/meta/META-SPEC.md` as the entry point. In `CLAUDE.md` the
  stale source-of-truth prose was replaced rather than added to, per the file's own
  instruction-budget rule.
- `specs/branching-strategy.md` marked `status: DRAFT` in the registry — it
  describes workflows this repo does not have. Tracked as an open conflict.

### Changed (previously)
- 2.5D-alignment sweep across the reader-facing docs so the promoted 2.5D
  pivot (`docs/designs/2.5D-RPG-Prototype.md`) and the aligned spec
  (`specs/aligned-spec-v0.2.5.md`) show up where they matter:
  - `README.md` pitch, Concept intro, Layer 2 description, and the
    engine-choice reason now lead with 2.5D top-down. `first-person`
    references dropped from the top-level overview.
  - `docs/quick-reference.md` pitch line rewritten to 2.5D-first with a
    pointer to the promoted design and the aligned spec.
  - `specs/roadmap.md` and `specs/task-tracker.md` gained a top-of-file
    ⚠️ banner marking their 3D-specific node names as deprecated while
    keeping the milestone structure / checklist authoritative.
  - `Docs/files/README.md` (the migration-signpost stub added on `dev`
    after PR #5) gained a "where the files actually live now" table so
    the note's referent ("these files") points at real paths.
  - `CLAUDE.md` "critical architectural reframe" and doc-layout sections
    now name `specs/aligned-spec-v0.2.5.md` as the current source-of-
    truth for spec details and enumerate the specific 3D-legacy caveats
    per file.
  - `specs/README.md` — reordered the table to lead with the aligned spec,
    reworded roadmap/task-tracker entries with the 3D-deprecation caveat.
- Renamed
  `specs/TastesLike Plaza v0_2_5_ Aligned Specification Set for a 2_5D AI Agent Office World.md`
  → `specs/aligned-spec-v0.2.5.md`. Spaces, underscores, and mixed casing
  in the original filename made it hostile to CLI tooling, URLs, and
  cross-references. Content is unchanged.

### Added
- `CONTRIBUTING.md` — day-to-day contributor guide: branching flow,
  Conventional Commits, PR workflow, CI expectations, doc/spec split rules.
  Points at `specs/branching-strategy.md` for the formal policy.
- `QUICKSTART.md` — fast path from `git clone` to running the Atlassian
  scripts and submodule init; pointers to the next-step docs.
- `docs/README.md` — folder index for `docs/`. Defines the *what / why*
  scope and rules of thumb for what belongs under design vs. process.
- `specs/README.md` — folder index for `specs/`. Defines the *how / when*
  scope, highlights the M1 → M4 → M8 critical path, and explains the
  status-checkbox convention.
- `CLAUDE.md` — onboarding guide for future Claude Code sessions. Covers the
  4-layer architecture, the three Godot autoloads (`AgentRegistry`,
  `GameEvents`, `GameState`), the M1 → M4 → M8 critical path, the
  `claude-code-tresor` submodule workflow, CI lint rules, the consolidated
  `docs/` + `specs/` layout, and the prescribed Godot project layout.
  (PR #4)
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
- **Docs layout consolidated.** The legacy `Docs/` tree was split into a
  design/reference folder (`docs/`) and a development-process folder
  (`specs/`). Numeric prefixes dropped; folder structure conveys order:
  - `Docs/files/01_WEEK1_STORYBOARD.md` → `docs/storyboard-week1.md`
  - `Docs/files/04_QUICK_REFERENCE.md` → `docs/quick-reference.md`
  - `Docs/10110_TastesLikePlaza_DIRECTORY.md` → `docs/agent-directory.md`
  - `Docs/plaza_build_steps.html` → `docs/assets/plaza_build_steps.html`
  - `Docs/plaza_godot_architecture.svg` → `docs/assets/plaza_godot_architecture.svg`
  - `Docs/files/02_PROTOTYPE_ROADMAP.md` → `specs/roadmap.md`
  - `Docs/files/03_PM_TASK_TRACKER.md` → `specs/task-tracker.md`
  - `Docs/BRANCHING_STRATEGY.md` → `specs/branching-strategy.md`
- `CLAUDE.md` — replaced the "Two doc trees" section with a doc layout
  reflecting the consolidated `docs/` + `specs/` split. Updated all
  internal references to the legacy `Docs/` paths.
- `.gitmodules` — fix `claude-code-tresor` URL from the relative
  `../claude-code-tresor.git` to the canonical
  `https://github.com/adamtasteslikegood/claude-code-tresor.git` so fresh
  clones can initialize the submodule with
  `git submodule update --init --recursive`. (PR #4)
- `CLAUDE.md` — refreshed the **Branching** section: `dev` is now the
  integration branch (caught up to `main` via PR #3) and the merged
  `sync-main-to-dev` line was dropped. (PR #4)

### Removed
- `Docs/files/00_PROJECT_OVERVIEW.md` — byte-identical to the top-level
  `README.md`. `README.md` is now the single source for the project
  overview; the department/color table is mirrored in
  `docs/agent-directory.md` only.
- Legacy `Docs/` tree (capital `D`) — all files relocated under `docs/` or
  `specs/` per the consolidation above. Empty directory removed.
- Stray `@googleworkspace/cli` `CHANGELOG.md` (accidental import) — removed
  during PR #3 review feedback. This file replaces it.
- `.omg/state/learn-watch.json` — removed during PR #3 review.
- `sync-main-to-dev` branch — deleted from the remote after PR #3 merged
  it into `dev`. (PR #4 cleanup)

### Notes
- `dev` was fast-forwarded to match `main` via PR #3 (`sync-main-to-dev` →
  `dev`). `dev` is once again the integration branch per
  `specs/branching-strategy.md`.
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
