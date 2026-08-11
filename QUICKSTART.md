# Quick start

This repo is **a running Godot prototype with a live agent bridge**. `godot .`
opens a walkable 2.5D office; pressing Enter near an NPC lets you ask a question
that routes through a Python WebSocket bridge to the Claude SDK and back.

For what has actually shipped, read [`specs/task-tracker.md`](specs/task-tracker.md)
— it is the status of record.

## 1. Clone with submodules

```bash
git clone --recurse-submodules https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza.git
cd 10110TasteslikegoodPlaza
```

If you cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

The `claude-code-tresor/` submodule holds the agent definitions under `subagents/`
(nested by department) and `agents/` (the same core roles in Claude Code's runtime
format — a backward-compat shim, not extra roles). For the counts and what each one
means, see [`docs/agent-directory.md`](docs/agent-directory.md) — `D-017` makes it
the authority, and every other count in the repo derives from it rather than
restating one here.

This repo tracks [adamtasteslikegood/claude-code-tresor](https://github.com/adamtasteslikegood/claude-code-tresor)
— a fork of the original repo of the same name by Alireza Rezvani, the author of
the agents, skills, commands, sub-agents and agent-skills for Claude Code and
other AI/coding agents.

   - [alirezarezvani/claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor)  <— submodule _is_ fork of
### **Be sure to check out:**
   - [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) 23.4k GitHub Stars
   - ***Other open source projects:***
   - [Claude Forge - CLAUDE.md](https://github.com/alirezarezvani/ClaudeForge) generator + 'best practices'
   - [Alireza Rezvani - GitHub](https://github.com/alirezarezvani)
   - Articles about [AI engineering and agentic development](https://alirezarezvani.medium.com/) on [Medium](https://alirezarezvani.medium.com/)
   - [https://alirezarezvani.com/](https://alirezarezvani.com/)

These definitions are what [`data/agents.json`](data/agents.json) is built from —
`scripts/generate_agents_json.py` generates it from the submodule (`D-024`). It
already exists; never hand-edit it, regenerate. `python3 scripts/generate_agents_json.py --check`
fails if the two have drifted apart, and CI runs that check.


## 2. Install prerequisites

**Godot 4.7+** — download from [godotengine.org](https://godotengine.org/download/)
and ensure `godot` is on your `PATH`.

**Python 3.10+** with a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install websockets anthropic   # bridge runtime
pip install flake8 black           # linting (CI gates)
pip install pyyaml                 # only for regenerating agents.json
```

**Anthropic API key** — the bridge calls the Claude SDK, so you need a key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

## 3. Run the demo

Open **two terminals** (both from the repo root, both with the venv activated):

```bash
# Terminal 1 — start the bridge
python3 bridge/bridge.py
# → "Bridge running on ws://localhost:8765"

# Terminal 2 — launch the game
godot .
```

Walk around with **arrow keys or WASD**. Approach an NPC — a dialogue panel opens
showing their name, role, and department. Click the text input at the bottom, type
a question, and press **Enter**. The bridge sends it to the Claude SDK with the
agent's `.md` definition as system prompt; the response renders with a typewriter
effect. Press **Escape** to release the input and walk to the next agent.

Without the bridge running, the game still opens and you can walk and see agent
info — questions will show a "Bridge not connected" error until you start
`bridge/bridge.py`.

## 4. Run tests

```bash
godot --headless --import                     # import assets (once per clone)
godot --headless tests/smoke_test.tscn        # the build gate
python3 scripts/validate_specs.py             # governed-document validator
```

Or use the npm facade (no install needed — no dependencies):

```bash
npm test                                      # validate → import → smoke
```

## 5. Lint before pushing

Same checks CI runs:

```bash
black --check .                                       # must pass
flake8 . --select=E9,F63,F7,F82                       # must pass
flake8 . --exit-zero --max-complexity=10 --max-line-length=127   # advisory
```

## 6. Optional: the Atlassian scripts

`generate_report.py` and `post_to_confluence.py` build a status report from a Jira
board and post it to a Confluence page. Both read `./.env` — `cp .env.example .env`
and fill in the four variables it documents, including your own board and page.
Nothing else in the repo needs them.

## 7. Where to go next

| If you want to… | Start here |
|---|---|
| Understand the project end-to-end | [`README.md`](README.md) |
| Orient as a developer or agent | [`CLAUDE.md`](CLAUDE.md) |
| See the active design | [`docs/designs/2.5D-RPG-Prototype.md`](docs/designs/2.5D-RPG-Prototype.md) |
| Pick up a milestone | [`specs/roadmap.md`](specs/roadmap.md) |
| Track current work | [`specs/task-tracker.md`](specs/task-tracker.md) |
| Follow the contribution flow | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

*Last updated: August 2026*
