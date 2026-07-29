# Quick start

   This repo is still in **early planning and prototype stages** — .godot prototype status, existence, instructions for testing and development are subject to change. Same goes for the agent bridge.  
   
## 1. Clone with submodules

```bash
git clone --recurse-submodules https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza.git
cd 10110TasteslikegoodPlaza
```

If you cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

The `claude-code-tresor/` submodule holds the 137+ agent definitions under `subagents/` (by department) and `agents/` (**the eight production-ready cores**). This repo tracks [adamtasteslikegood/claude-code-tressor](https://github.com/adamtasteslikegood/claude-code-tresor) - a fork of the original repo by the samne name by Alireza Rezvani, the author of the agents, skills, commands, sub-agents and agent-skills for Claude Code and other AI/coding agents. ***See links below*** 

   - [alirezarezavani/claude-code-tressor](https://github.com/alirezarezvani/claude-code-tresor)  <—- submodule _is_ fork of
### **Be sure to check out:**
   - [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) 23.4k GitHub Stars
   - ***Other open source projects:***
   - [Claude Forge - CLAUDE.md](https://github.com/alirezarezvani/ClaudeForge) generator + 'best practices'
   - [Alireza Rezvani - GitHub](https://github.com/alirezarezvani)
   - Articles about [AI engineering and agentic development](https://alirezarezvani.medium.com/) on [Medium](https://alirezarezvani.medium.com/)
   - [https://alirezarezvani.com/](https://alirezarezvani.com/)

**These will become** `data/agents.json` once M3 ships. 


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
# Pulls Jira project updates from the last 7 days into report.md
python generate_report.py

# Renders report.md to HTML and posts it as a child of Confluence page <confluence_page_id>,
# the home of space ____ ("Your Confluence Home Page goes Here")
python post_to_confluence.py
```

Both will crash with a `KeyError` if either `.env` var is missing — that's intentional.

## 5. Lint before pushing

Same checks CI runs:

```bash
black --check .                                       # must pass
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

The first real prototype task is **M1** — initialize a Godot 4 project for the 2.5D top-down prototype and implement basic `CharacterBody2D` player movement. See [`specs/roadmap.md`](specs/roadmap.md) and [`docs/designs/2.5D-RPG-Prototype.md`](docs/designs/2.5D-RPG-Prototype.md).

*Last updated: July 2026*
