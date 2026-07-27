# Changelog

All notable changes to **10110 TastesLikegood Plaza** are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries land under `[Unreleased]` as work is merged and graduate to a numbered
section at release time. PR references in parentheses.

## [Unreleased]

### Changed — doc set v0.2.7: the eight decisions get an entitled home (#11)

- **`docs/designs/platform-decisions.md` created** (`PLATFORM-DECISIONS`, tier 2,
  `authority: implementation`) and now originates `D-003`, `D-015`, `D-016`,
  `D-018`, `D-021`, `D-022`, `D-023`, `D-024`. Its scope test: *would this decision
  survive replacing the entire frontend?* If it dies with the 2.5D prototype it
  belongs in the promoted design instead.
- **`README.md` loses its `decides:` list.** It declared `authority: derived` —
  licensed by `META-SPEC` §2 to decide "nothing new" — while being named as the
  origin of all eight. The layer contradicted itself, and the set validated green
  for two releases. Option (b) of issue #11, chosen by the owner: existing authority
  vocabulary, no schema enum change, no new tier.
- **`D-023` and `D-024` flip `PROPOSED` → `LOCKED`.** Their substance was never in
  question; only the bookkeeping about who was entitled to make them. "Not yet
  authorised" in the decision register is now empty.
- **The validator gained the check whose absence caused this.**
  `check_decision_authority()` fails the build when a document declares `decides:`
  without an authority listed in `authority.x-may-originate` — published in
  `spec-frontmatter.schema.json`, not restated in the script, so the gate cannot
  drift from the contract. Verified by running it against the unfixed tree first:
  it named `README.md` and all eight ids before anything was moved.
- **A coarse gate, deliberately.** It asks whether an authority may originate
  *something*, not whether a given decision falls inside that authority's subject
  matter. Writing it surfaced one instance of the second kind — `D-005` is an
  architecture decision originated by tier-0 `META-SPEC`, which §2 says may never
  originate product decisions. Recorded as open conflict **§4.9** rather than fixed,
  per the conflict protocol; nothing is blocked either way.

### Added — M3: the agent data layer (`D-024`)

- **`data/agents.json` — 132 agents**, generated from the submodule by
  `scripts/generate_agents_json.py`, with a `Validate Agent Data` CI job that
  regenerates and fails on drift. That job is what makes `D-016` ("generated,
  never hand-edited") a gate rather than a rule.
- **Reads `subagents/` only.** The core-eight "collision" recorded earlier as an
  open M3 hazard was never one: upstream v2.7.0 made `subagents/` PRIMARY and left
  `agents/` as a backward-compat shim — 8 symlinks plus 8 pre-v2.7.0 flat files
  that were never deleted and still carry `category: engineering` / `color: blue`
  for the core eight. Those stale copies matter more than they look: the core eight
  are the most-referenced agents in the orchestration commands — of the 24 command
  files under `commands/` (39 `.md` in total, 15 of them READMEs), `security-auditor`
  is named in 10, `systems-architect` 9, `test-engineer` 8.
- **The real collision only the generator could find.** 133 files carry just **130
  distinct slugs**. `infrastructure-maintainer` is one role filed twice (operations
  copy removed); `customer-support` and `tutorial-engineer` are genuinely different
  jobs sharing a name (renamed `support-ticket-handler` and
  `educational-content-writer`). Upstream's own `DUPLICATE-ANALYSIS.md` is v2.5.0
  and predates the consolidation that caused them.
- **83 of 133 agents declare `tools` as a bare comma string**, which YAML reads as
  `str`, not `list`. Passed through unchanged that would have handed GDScript a
  string where it expects an array for most of the directory — an M4 bug caught at
  M3. All three upstream syntaxes are normalised to `list[str]`.
- Department colours are cross-checked against the `D-017` taxonomy, so a drifting
  upstream colour fails the build instead of silently retinting a department. All
  132 currently agree.
- `role` is derived from the taxonomy, not from prose. An earlier pass truncated the
  description on punctuation and produced labels like "UI design specialist for
  creating beautiful"; topical relevance has to win over mechanical trimming.

### Fixed

- Curation tables are keyed by **source path**, not slug, so an upstream move fails
  the build rather than silently applying an override to the wrong agent. A *new*
  collision is a hard error, never an auto-suffix — deciding "one role or two"
  means reading both descriptions.
- Renamed agents were keeping their upstream display names, so two NPCs would have
  shown the same label above different sprites. Display name is now recomputed from
  the final id; all 132 are unique.
- Corrected the stale "M3 hazard" framing in `docs/agent-directory.md`, `CLAUDE.md`
  and `spec-drivers` §4.2, and the README department table (Operations 6 → 5, total
  133 → 132).

### Changed — merge strategy is now a recorded decision (`D-023`)

- **Merge commits are the deliberate policy, not a settings accident.** The previous
  pass corrected the doc descriptively ("the setting disproves the claim"), which
  left squash reading as the aspiration and merge commits as a fallback. It is the
  other way round: the squash-only rule was inherited from
  `alirezarezvani/claude-code-tresor` and was never chosen for this project, and
  squash merging has caused the owner real problems on other repositories. `D-023`
  records the choice with its rationale so it is not "fixed" back by a linter, a
  bot, or the next person reading a style guide.
- Documented the consequences rather than leaving them to be rediscovered: `dev` is
  not linear and must not be required to be, multi-commit PRs keep their history so
  a structured series is worth writing, and reverting a merged PR needs
  `git revert -m 1 <merge-sha>`.
- Added an "inherited rules are the failure mode" table to
  `specs/branching-strategy.md` §9, recording both rules that survived the rewrite
  and how each was caught — the invented required-check names (read against
  `.github/workflows/`) and the squash claim (a `405` from the merge API).

### Open

- **New conflict (§4.8): `PROJECT-OVERVIEW` originates decisions its authority
  forbids.** `README.md` declares `authority: derived`, which `META-SPEC` §2 says may
  decide nothing — yet it is now the named origin of seven decisions (`D-003`,
  `D-015`, `D-016`, `D-018`, `D-021`, `D-022`, `D-023`). Surfaced while registering
  `D-023`. The validator misses it: it checks that every `D-nnn` in a `decides:` list
  exists in the register, never that the declaring document is entitled to decide.
  Recorded rather than fixed — the seven decisions are all substantively correct and
  evidenced; what is wrong is the bookkeeping about who was entitled to make them.
  Tracked as issue #11 with three options; `META-SPEC` §4 step 2 now says to open an issue
  for conflicts that need discussion, keeping the register as the index and the issue
  as where it gets settled.

### Corrected — `dev` was never unprotected

- **`branching-strategy.md` §5 said "not yet configured". `dev` is protected by an
  active ruleset** (`18798438`, targeting `~DEFAULT_BRANCH`) carrying `pull_request`,
  `deletion`, `non_fast_forward`, `code_scanning` and `copilot_code_review`. §5 now
  describes what is active and keeps only the genuine gaps as instructions —
  required status checks by name on `dev`, `main`'s ruleset, and CODEOWNERS.
- **Root cause worth more than the fix:** the claim *was* checked — against
  `GET /branches/{branch}/protection`, which returns `404 Branch not protected` for
  ruleset-based protection. Rulesets are a separate API surface (`/rulesets`,
  `/rules/branches/{branch}`). A confident negative from an endpoint that cannot see
  the thing being asked about is worse than no check, because it feels like evidence.
  Recorded as the third failure mode in §9, alongside inherited-and-false and
  true-then-stale.
- `non_fast_forward` (active) is **not** `required_linear_history` (must stay off).
  Different rules; only the latter conflicts with `D-023`. The §5 warning stands and
  is not currently violated.

### Corrected

- **`branching-strategy.md` claimed "squash and merge exclusively".** Squash merging
  is disabled in repository settings, and every merge on `dev` is a merge commit
  (`Merge pull request #N from …`) — the claim was inherited from the upstream
  original and survived the rewrite. Found by attempting the merge, which the API
  rejected with `405 Squash merges are not allowed on this repository`. §4 now says
  merge commits; the header, the enforcement table, the release flow, and
  `CONTRIBUTING.md` §Pull requests all corrected to match. §5 no longer tells you to
  enable "Require linear history", which is incompatible with merge commits and
  would have blocked every merge if applied as written.

### Security

- **`.github/workflows/ci.yml` now declares `permissions: contents: read`.** It was
  the only workflow with no permissions at any level, so `GITHUB_TOKEN` inherited
  the repository default — CodeQL's `actions/missing-workflow-permissions`, one
  alert per job. Every job in the file only reads the repo (checkout, set up
  Python, run a validator or linter), so `contents: read` is the correct least
  privilege. The `gemini-*.yml` workflows already declare permissions per job and
  were never affected.

### Doc set v0.2.6 — the four open conflicts closed

Six of seven conflicts in the open-conflict register now read RESOLVED. Two new
locked decisions (`D-014`, `D-020`) moved the doc set version per `META-SPEC` §8.4.

- **Agent counts settled (§4.2).** Submodule initialised and counted:
  **141 agent files = 8 core + 133 subagents, spanning 133 distinct roles.**
  Verified identical at `acfb923`, `bcfe30c` (`10110TLGP/main`), and `b7ec149`
  (the pin after the 2026-07-26 bump).
  Both figures are correct and measure different things — `agents/*.md` holds the
  same eight roles as `subagents/core/` in Claude Code's runtime format rather than
  the catalog format. The previous "137+" was wrong either way. Real per-department
  numbers (engineering 54, leadership 14, marketing 11, ai-automation 9, product 9,
  account-CS 8, core 8, design 7, research 7, operations 6) landed in
  `docs/agent-directory.md` as the taxonomy authority (`D-017`); `README.md`,
  `CLAUDE.md`, `docs/README.md`, and `specs/task-tracker.md` now derive from it.
  Recorded the `agents.json` id collision as an M3 hazard rather than deciding it
  early.
- **`D-020` ratified (§4.3).** Layer 2 is "the current frontend, which happens to be
  2.5D Godot", not "the Godot engine" — `D-005` and the swap test only mean
  something if the frontend is structurally a slot. Ratified into
  `docs/designs/2.5D-RPG-Prototype.md` under a `## Ratified in v0.2.6` heading that
  leaves the dated 2026-04-27 CEO-plan record intact, carrying the frontend-swap
  matrix. `README.md`, `CLAUDE.md`, and `docs/quick-reference.md` updated.
- **`D-014` ratified (§4.4).** Bridge boundary stays conceptual until after M8;
  flipped `PROPOSED` → `LOCKED` with its reversal threshold carried across verbatim.
  The "Not yet authorised" table is now empty.
- **`specs/branching-strategy.md` rewritten (§4.5), 806 lines → 181.** The document
  was inherited from the upstream fork and described a different project. Rather
  than correct it in place, it was rewritten against this repo: the real branch list
  (including the long-lived `feature/TO-1-prototype-initialization` and its
  `scripts/` tree), `dev` as the default branch, the CI jobs that actually run,
  the real submodule-bump procedure, and an honest "no tags cut yet" release
  section. Invented required checks (`quality-gates`, `validate-pr`,
  `production-build`, `validate-release-pr`) replaced with the correct job names —
  GitHub matches required checks by name, so the old list would have matched
  nothing. Branch-protection settings are labelled as a setup to apply, not as
  current state. `DRAFT` → `ACTIVE`.
- `CONTRIBUTING.md` updated to match: `Validate Specs` added to the CI expectations,
  stale counts corrected, and the branching-strategy pointer reworded now that the
  policy doc no longer claims CODEOWNERS gating exists.
- **New conflict, opened and closed (§4.7).** Nothing recorded whether the submodule
  pin tracks `10110TLGP/dev` or `10110TLGP/main`. Both halves are now settled and
  registered: the pin tracks `10110TLGP/dev`, the fork's default branch (`D-021`),
  and `10110TLGP/main` is **reserved as the fork's release branch** (`D-022`) —
  dormant until the fork has a `release.yml` and tagged releases, then cut
  `dev` → `main`, tag, back-sync. Not abandoned, not a pin target; recorded so
  nobody prunes it as stale or bumps to it by mistake. The fork's branch model is
  now documented in `specs/branching-strategy.md` §6 where a bump would surface it.
  **Correction:** an earlier draft called the two branches "diverged, needs
  reconciling." They diverge in *history* only — one commit each side of merge-base
  `4b68050`, each having merged the same upstream state by a different route. The
  trees are byte-identical (`b7aee19`), so the first `dev` → `main` merge won't
  fast-forward but cannot conflict.
- **Seven of eight conflicts resolved.** §4.8 is open, tracked as issue #11.
- **Validator:** links into an uninitialised submodule are now checked when the
  submodule is present and reported as skipped when it is not, instead of failing
  the build. CI checks out without submodules, so this is what makes the restored
  `claude-code-tresor` links safe. Verified in both states.
- Cleared the last `{{rolels}}` / `{{roles}}` / `{{charactor}}` upstream template
  placeholders from `docs/agent-directory.md`, and restored real links to the six
  reference docs (they live at `claude-code-tresor/docs/archive/`).

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
