# Quick start

A fast path from `git clone` to "running what's runnable today". This repo is **between planning and prototype** — there's no Godot project yet, but the Atlassian integration scripts and the agent submodule both work right now.

## 1. Clone with submodules

```bash
git clone --recurse-submodules https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza.git
cd 10110TasteslikegoodPlaza
```

If you cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

The `claude-code-tresor/` submodule holds the 137+ agent definitions under `subagents/` (by department) and `agents/` (the eight production-ready cores). These will become `data/agents.json` once M3 ships.

## 2. Set up the `.env` (only if you want to run the Atlassian scripts)

The two Python scripts at the repo root post status reports from Jira to Confluence. They both read `./.env` directly — no `python-dotenv` involved. Create it with:

```bash
cat > .env <<'EOF'
ATLASSIAN_API_TOKEN_BASE64_USEREMAIL=<base64-encoded "email:api_token">
ATLASSIAN_URL=<your-site>.atlassian.net
EOF
```

`.env` is gitignored. Don't commit it.

## 3. Install Python deps

The CI workflow uses just `flake8 black websockets`. You can match it:

```bash
python -m venv .venv
source .venv/bin/activate
pip install flake8 black websockets requests
```

(`requests` is what the Atlassian scripts use.)

## 4. Generate and post a status report

```bash
# Pulls Jira project TO updates from the last 7 days into report.md
python generate_report.py

# Renders report.md to HTML and posts it as a child of Confluence page 15925249
python post_to_confluence.py
```

Both will crash with a `KeyError` if either `.env` var is missing — that's intentional.

## 5. Lint before pushing

Same checks CI runs:

```bash
black --check .                                       # advisory
flake8 . --select=E9,F63,F7,F82                       # must pass
flake8 . --exit-zero --max-complexity=10 --max-line-length=127   # advisory
```

## 6. Where to go next

| If you want to… | Start here |
|---|---|
| Understand the project end-to-end | [`README.md`](README.md) |
| Orient as a developer or agent | [`CLAUDE.md`](CLAUDE.md) |
| See the active design | [`docs/designs/2.5D-RPG-Prototype.md`](docs/designs/2.5D-RPG-Prototype.md) |
| Pick up a milestone | [`specs/roadmap.md`](specs/roadmap.md) |
| Track current work | [`specs/task-tracker.md`](specs/task-tracker.md) |
| Follow the contribution flow | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

The first real prototype task is **M1** — install Godot 4 and drop in the First-Person Shooter demo (which under the 2.5D pivot becomes a top-down `CharacterBody2D` setup instead). See [`specs/roadmap.md`](specs/roadmap.md) and [`docs/designs/2.5D-RPG-Prototype.md`](docs/designs/2.5D-RPG-Prototype.md).

*Last updated: May 2026*
