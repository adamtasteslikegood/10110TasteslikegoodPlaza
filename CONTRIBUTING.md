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
5. **Merge commit** — squash merging is disabled on this repo. See [`specs/branching-strategy.md`](specs/branching-strategy.md) §4.

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
