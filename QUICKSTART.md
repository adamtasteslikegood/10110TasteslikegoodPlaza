# Quick start

This repo is **a running Godot prototype**. `project.godot` exists, `godot .` opens a walkable office, and `tests/smoke_test.tscn` gates it in CI. The agent bridge is the part that is not built yet.

For what has actually shipped, read [`specs/task-tracker.md`](specs/task-tracker.md) — it is the status of record. This page deliberately does not restate milestone state, because restating it is how this line drifted into claiming the prototype might not exist.

## 1. Clone with submodules

```bash
git clone --recurse-submodules https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza.git
cd 10110TasteslikegoodPlaza
```

If you cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

The `claude-code-tresor/` submodule holds the agent definitions under `subagents/` (nested by department) and `agents/` (the same core roles in Claude Code's runtime format — a backward-compat shim, not extra roles). For the counts and what each one means, see [`docs/agent-directory.md`](docs/agent-directory.md) — `D-017` makes it the authority, and every other count in the repo derives from it rather than restating one here.

This repo tracks [adamtasteslikegood/claude-code-tresor](https://github.com/adamtasteslikegood/claude-code-tresor) — a fork of the original repo of the same name by Alireza Rezvani, the author of the agents, skills, commands, sub-agents and agent-skills for Claude Code and other AI/coding agents. ***See links below***

   - [alirezarezvani/claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor)  <—- submodule _is_ fork of
### **Be sure to check out:**
   - [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) 23.4k GitHub Stars
   - ***Other open source projects:***
   - [Claude Forge - CLAUDE.md](https://github.com/alirezarezvani/ClaudeForge) generator + 'best practices'
   - [Alireza Rezvani - GitHub](https://github.com/alirezarezvani)
   - Articles about [AI engineering and agentic development](https://alirezarezvani.medium.com/) on [Medium](https://alirezarezvani.medium.com/)
   - [https://alirezarezvani.com/](https://alirezarezvani.com/)

These definitions are what [`data/agents.json`](data/agents.json) is built from — `scripts/generate_agents_json.py` generates it from the submodule (`D-024`). It already exists; never hand-edit it, regenerate. `python3 scripts/generate_agents_json.py --check` fails if the two have drifted apart, and CI runs that check.


## 2. What the two root Python scripts are — and why they are not a step here

`generate_report.py` and `post_to_confluence.py` are **maintainer tooling**, not part of getting started. They build a status report from this project's Jira board and publish it into this project's own Confluence space.

**They are not runnable against a space of your own.** `post_to_confluence.py` targets a fixed parent page in code, deliberately and with no fallback — an earlier fallback silently published into a sibling product's space, which is how reports ended up there. So there is nothing to configure that would point them at your own Confluence.

You do not need them to run the prototype, read the specs, or contribute.

If you are working *on* those scripts: `cp .env.example .env` and fill it in. [`.env.example`](.env.example) is the source of truth for what they read — every required variable, how to build the base64 credential, and which variables that appear in real `.env` files here are read by nothing. Both scripts name what is missing and exit 1 rather than raising.

`.env` is gitignored; `.env.example` is committed and must never carry a real value. If a token is ever exposed, rotate it — deleting the commit does not revoke it.

## 3. Install Python deps

The CI workflow uses just `flake8 black websockets`. You can match it:

```bash
python -m venv .venv
source .venv/bin/activate
pip install flake8 black websockets requests
```

(`requests` is only used by the two Atlassian scripts in §2; the rest is what CI runs.)

## 4. Lint before pushing

Same checks CI runs:

```bash
black --check .                                       # must pass
flake8 . --select=E9,F63,F7,F82                       # must pass
flake8 . --exit-zero --max-complexity=10 --max-line-length=127   # advisory
```

## 5. Where to go next

| If you want to… | Start here |
|---|---|
| Understand the project end-to-end | [`README.md`](README.md) |
| Orient as a developer or agent | [`CLAUDE.md`](CLAUDE.md) |
| See the active design | [`docs/designs/2.5D-RPG-Prototype.md`](docs/designs/2.5D-RPG-Prototype.md) |
| Pick up a milestone | [`specs/roadmap.md`](specs/roadmap.md) |
| Track current work | [`specs/task-tracker.md`](specs/task-tracker.md) |
| Follow the contribution flow | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

To run what is already here: `godot --headless --import` once on a fresh clone, then `godot .` to walk the office, or `godot --headless tests/smoke_test.tscn` for the build gate. Which milestone is next is tracked in [`specs/task-tracker.md`](specs/task-tracker.md), sequenced by [`specs/roadmap.md`](specs/roadmap.md), and designed in [`docs/designs/2.5D-RPG-Prototype.md`](docs/designs/2.5D-RPG-Prototype.md) — read those rather than a milestone name pinned here.

*Last updated: July 2026*
