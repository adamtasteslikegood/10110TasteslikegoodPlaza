# Quick start

This repo is **a running Godot prototype with a live agent bridge**. `godot .`
opens a walkable 2.5D office; pressing Enter near an NPC lets you ask a question
that routes through a Python WebSocket bridge to the Claude SDK and back.

For what has shipped and what's next, see the § Repository state and § Critical path
sections in [`CLAUDE.md`](CLAUDE.md).

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

**Python 3.11+** with a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt   # pinned bridge runtime, tests and lint tools
pip install pyyaml                 # only for regenerating agents.json
```

**Anthropic API key** — the bridge calls the Claude API (Messages API for NPC
chat, Agent SDK for domain sessions). Create a key at
[console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

> "Unless previously approved, Anthropic does not allow third party developers
> to offer claude.ai login or rate limits for their products, including agents
> built on the Claude Agent SDK. Please use the API key authentication methods
> described in this document instead."
>
> — [Anthropic Agent SDK QuickStart](https://code.claude.com/docs/en/agent-sdk/quickstart)

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

## Bridge settings and archives (M10)

The bridge loads one validated, immutable settings snapshot before constructing
provider clients or opening the listener. Restart the bridge to reload changes.
Precedence is **built-ins → JSON file → environment overrides**. The default file
is [`bridge/config.json`](bridge/config.json); set `BRIDGE_CONFIG_PATH` to select
another file. An absent default file uses built-ins. An explicitly selected
missing file, unreadable/malformed JSON, duplicate/unknown keys, unsupported
version or invalid effective values fails startup with exit code 2.

Every key supports `PLAZA_<KEY>`. Text overrides are raw strings; numbers and
booleans use JSON scalar syntax (`false`, not `False` or `0`). Unknown `PLAZA_`
names fail startup. For example, from the repository root:

```bash
PLAZA_LOG_LEVEL=DEBUG PLAZA_TRANSCRIPTS_ENABLED=false python3 bridge/bridge.py
# A custom config can contain only the settings you override:
BRIDGE_CONFIG_PATH=/path/to/config.json python3 bridge/bridge.py
```

Relative `LOG_DIR` values resolve against the **selected config's directory**, even
when overridden in the environment; with built-ins they resolve against `bridge/`.
The shipped `../.local/bridge-logs` therefore selects `.local/bridge-logs/` in this
checkout. That directory is Git-ignored; choosing/ignoring a custom external root
is the operator's responsibility. The committed config remains tracked.

These are all 20 keys and their built-in/shipped defaults:

| Key | Default | Constraint / meaning |
|---|---|---|
| `CONFIG_VERSION` | `1` | Supported integer version |
| `HAIKU_MODEL` | `claude-haiku-5-5` | Nonempty provider ID |
| `SONNET_MODEL` | `claude-sonnet-5-5` | Nonempty provider ID |
| `OPUS_MODEL` | `claude-opus-5-5` | Nonempty provider ID |
| `FABLE_MODEL` | `claude-fable-5-1` | Nonempty provider ID |
| `ADVISOR_MODEL` | `FABLE_MODEL` | Symbolic reference to one of the four model keys |
| `CONVERSATION_TIER` | `haiku` | `haiku`, `sonnet`, `opus`, `fable` |
| `DOMAIN_TIER` | `sonnet` | Same four tiers |
| `CONVERSATION_TIMEOUT_SECONDS` | `60` | Positive finite number |
| `CONVERSATION_MAX_OUTPUT_TOKENS` | `4096` | Positive integer |
| `CONTEXT_MAX_MESSAGES` | `40` | Even integer, at least 2; connection/agent model context |
| `DOMAIN_MAX_TURNS` | `20` | Positive integer; existing domain execution cap |
| `DOMAIN_MAX_BUDGET_USD` | `1.0` | Positive finite number; existing domain budget cap |
| `TRANSCRIPTS_ENABLED` | `true` | Boolean; `false` disables message-body archives, keeps events |
| `LOG_DIR` | `../.local/bridge-logs` | Nonempty path, resolved as above |
| `LOG_LEVEL` | `INFO` | `INFO`, `DEBUG`, `WARNING`, `ERROR` |
| `TRANSCRIPT_MAX_RECORD_BYTES` | `262144` | Integer ≥4096; encoded JSON plus LF, also applies to events |
| `TRANSCRIPT_MAX_FILE_BYTES` | `5242880` | Integer ≥record bound; rotate before exceeding |
| `LOG_MAX_TOTAL_BYTES` | `104857600` | Integer ≥file bound; managed archives including manifest temps |
| `LOG_MAX_AGE_DAYS` | `14` | Positive integer; prune eligible files by age first |

Numeric settings reject booleans, non-finite values and fractional integer limits.
Models have no fallback or automatic upgrade. `config.model_for("opus")` resolves
the explicit tier. The future-use helper `config.advisor_for("sonnet")` resolves
`ADVISOR_MODEL` only if its tier is strictly higher in
`haiku < sonnet < opus < fable` order and its provider ID differs from the caller's.
That relationship is checked when resolving; choosing Fable for ordinary chat
remains valid. There is **no advisor execution or default advisory routing**.
Keep credentials in the existing environment/SDK bindings, never in this config
or other non-secret settings; authentication precedence is unchanged.

### Inspect and manage recording

Linux recording is tested in the cloud and matches the owner's Linux laptop target.
Platforms without the required safe POSIX directory operations/OS lock suspend
recording while chat continues; native Windows archives are not supported.

```text
.local/bridge-logs/
  .writer.lock
  runs/<UTC timestamp>-<unique run ID>/
    manifest.json
    events-0001.jsonl
    agents/<agent_id>/transcript-0001.jsonl
```

Each process has a unique run. The atomic manifest includes effective non-secret
settings, timestamps and `open`/`closed` status. A crash leaves the previous run
open; a later process creates a new run. Events contain correlated metadata and
outcomes, while message bodies occur only in transcripts. Known bound credential
values are redacted in recorded content and metadata; credential-bearing agent
path names use opaque aliases. Treat transcripts as potentially sensitive user
content. `PLAZA_TRANSCRIPTS_ENABLED=false` disables transcript creation without
changing responses, model history or operational events.

Inspect a transcript using the tolerant reader from the repository root (replace
the example path with an existing segment):

```python
from pathlib import Path
from bridge.log_storage import iter_jsonl

segment = Path(".local/bridge-logs/runs/<run>/agents/<agent>/transcript-0001.jsonl")
for record in iter_jsonl(segment, on_diagnostic=print):
    print(record)
```

The reader diagnoses malformed lines and ignores an incomplete final line after
a crash. Records have run-wide increasing sequence numbers, UTC timestamps and
request/connection/agent correlation; failed writes may leave sequence gaps.
Disk-only truncation marks oversized bodies and preserves their original UTF-8
byte count. Full replies and live model context remain intact. Retention prunes
age-expired files, then oldest eligible files as needed for each write; sealed
segments of the current run are eligible, open writable segments are protected.
Only recognized bridge-owned files count toward quota or are pruned. Symlinks,
unrelated files, SDK storage and worktrees are never retention targets.

A root has one OS-backed writer lock. A competing writer, full/read-only disk or
quota consumed by protected files suspends recording with a stderr diagnostic;
requests still run. Use separate log roots for independent bridge processes, or
release the other recorder. Restore space/permissions or increase limits and
restart as needed. Later writes retry automatically and report recovery; missed
records are not backfilled. A nonempty initial `manifest.<id>.tmp` without an
ownership manifest is ambiguous: inspect that orphan run, then restore a valid
matching `manifest.json` or move/clear only the ambiguous artifact out of
`LOG_DIR`. Do not recursively delete the log root. Admission conservatively
remains suspended until that ambiguity is resolved; a later append retries.

Archives are diagnostic history, separate from bounded live model context and
future client scrollback. They are not replayed into models, durable user/project
state, or SDK restart recovery. Conversation request-ID response echo remains
planned for M11; current wire fields are unchanged (see
[`bridge/PROTOCOL.md`](bridge/PROTOCOL.md)).

Godot native output is configured separately, for example
`godot --log-file /tmp/plaza-godot.log --verbose .`. Its files are outside the
bridge quota and must be managed separately.

## 4. Run tests

```bash
godot --headless --import                     # import assets (once per clone)
godot --headless tests/smoke_test.tscn        # the build gate
python3 scripts/validate_specs.py             # governed-document validator
python3 -m pytest bridge/tests/ -q            # offline bridge tests, no model calls
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
| Track current work | [`CLAUDE.md`](CLAUDE.md) § Repository state |
| Follow the contribution flow | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

*Last updated: October 2026*
