# Quick start

This repo is **a running Godot prototype with a live agent bridge**. `godot .`
opens a walkable 2.5D office. Working characters expose explicit project
preparation, Start and Send controls through a Python WebSocket bridge to
Claude Code via the Claude Agent SDK (`D-037`).

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
pip install -r requirements.txt   # pinned runtime, tests, lint and catalog tools
```

**Claude Code authentication** — normal model execution, including every NPC
conversation, defaults to Claude Code through the Claude Agent SDK (`D-037`). The
pinned Python SDK supplies the CLI runtime. Keep existing supported native CLI
credentials/bindings; an API-key environment variable is **not required** for the
default backend when native Claude Code authentication works. The bridge does not
read credential files or choose the CLI's authentication source. The historical
`CLAUDE_CODE_0AUTH_TOKEN` spelling contains a digit zero; it maps to canonical
`CLAUDE_CODE_OAUTH_TOKEN` only when canonical is absent or empty.

Execution path and authentication/billing are separate: a cloud API key inherited
by Claude Code still executes through Agent SDK/CLI. Native subscription or
setup-token use depends on the account's supported Claude Code entitlement; this
guide makes no subscription, quota or billing guarantee. Consult the current
[Agent SDK authentication documentation](https://code.claude.com/docs/en/agent-sdk/quickstart)
for applicable account/product terms. Do not replace working native bindings just
because one environment variable is absent. To diagnose environment bindings,
report only variable names and set/unset status, never values or credential files.

**Explicit Messages API compatibility mode** — select this only when you intend
direct API execution. Set `ANTHROPIC_API_KEY` securely in your environment, then:

```bash
PLAZA_CONVERSATION_BACKEND=messages_api python3 bridge/bridge.py
```

This mode requires a nonempty API key and rejects known OAuth/setup-token forms
before HTTP; it never uses OAuth/auth-token fallbacks. Credentials do not select
the backend. Missing/failing CLI authentication, timeout or any other default-path
failure is returned visibly; the bridge never switches to Messages API automatically.
The default is `CONVERSATION_BACKEND=claude_code`, including in the shipped config.

## 3. Run the demo

Open **two terminals** (both from the repo root, both with the venv activated):

```bash
# Terminal 1 — start the bridge
python3 bridge/bridge.py
# → "Bridge running on ws://localhost:8765"

# Terminal 2 — launch the game
godot .
```

Walk around with **arrow keys or WASD**. Approach a character to open its name,
role and department view. Approach only obtains status. Prepare the configured
project with the Chief, then select **Let's work** at a Core representative.
Type into the dialogue composer and select **Send** or press **Enter** to Run.
Escape backgrounds the interaction. The full response renders progressively.
See [project work and domain controls](#project-work-and-domain-controls-m12)
for readiness and current acceptance requirements. Explicit extras use contextual
conversation; `messages_api` is an opt-in adapter for those conversations.

Without the bridge running, the game still opens and you can walk and see agent
info — questions will show a "Bridge not connected" error until you start
`bridge/bridge.py`.

## Project work and domain controls (M12)

The runtime correction merged in PR #365 and has recorded Linux API-key cloud
acceptance: both twelve-source guard modes passed 29/29 at `ec5d236`, and the Godot/plain-client
flow passed in selected `dontAsk` mode at clean `eaba12a`, bound to 48 relevant
source files. Chief setup, background work, independent extra conversation,
replay, restart/readback, project isolation and all three clean bridge closures
passed. The owner has confirmed laptop tools, worktree/memory behavior and the
latest OAuth run. This correction's laptop and remaining desktop checks are
separate; see [M12 evidence and desktop checks](#m12-live-evidence-and-desktop-checks).
Catalog characters require a prepared project for work. Explicit extras retain
tools-disabled conversation when `WORKSPACE_ROOT_DIR` is JSON `null` (the default).
Select one existing project directory before starting the bridge:

```bash
PLAZA_WORKSPACE_ROOT_DIR=/absolute/path/to/disposable-project python3 bridge/bridge.py
```

Alternatively select non-secret JSON with `BRIDGE_CONFIG_PATH`; a minimal file is
`{"CONFIG_VERSION":1,"WORKSPACE_ROOT_DIR":"/absolute/path/to/disposable-project"}`.
Precedence is built-ins → selected JSON → `PLAZA_` overrides. Workspace and log
paths resolve against the selected JSON's directory, including relative env
values. The workspace env override is a raw nonempty path: `null` means a literal
path, not JSON null. Restart the bridge and reconnect the game to change projects;
clients do not supply filesystem paths or switch projects within a session.

M12 requires Git with linked worktrees, `--no-lazy-fetch`,
`--no-optional-locks`, `rev-parse --path-format=absolute` and `show-ref --exists`.
Unsupported Git fails closed; do not remove those flags. Safe project files and
stable locks require POSIX `O_NOFOLLOW`, `O_DIRECTORY`, directory fsync and
`fcntl.flock`. Native Windows support is not established by the venv example.
A worktree and readiness hook provide cooperative isolation, not a host/network
sandbox. The execution checkout, configured project and bridge runtime checkout
must be canonically disjoint.

For an empty, non-Git or unborn project, other working characters offer a Chief
Architect referral. At the Chief (`systems-architect`), select **Prepare this
project**. Approach/status alone invokes no model. The typed `project_setup`
request reviews the exact inspected `main`/seed proposal; the bridge initializes
only its approved allowlist with no second human prompt. Project readiness
establishes shared memory; it does not provision department worktrees.

At a Core character, **Let's work** explicitly prepares/reuses Core's worktree
and reserves its session. Start may connect the SDK owner but queries zero models.
**Send** or Enter submits the draft as one Run; Enter never starts an inactive
domain. Systems Architect and Security Auditor share Core work, retaining the
originating representative on each result. The secondary domain pane uses the
same draft, generation, pending request, history and reading position.

Walking away or pressing Escape backgrounds work. An explicit extra can converse
while Core runs; another Core agent shows the shared work. Return/refocus replays
each result once. Completion, backgrounding and disconnect retain ownership.
**Stop work** remains available while idle or backgrounded; wait for confirmed
release. Default caps are 20 turns/USD 1.00 per task; acceptance uses smaller caps.

`DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS` is a strict JSON boolean, default `false`:
`false` selects `dontAsk`, `true` selects `bypassPermissions`. The environment
`PLAZA_DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS=true|false` overrides it. Both modes
retain Read/Edit/Bash and mandatory readiness guards; neither enables tools before
readiness or substitutes for matching real guard evidence.

Game/work briefs refresh on each admitted Run. `INSTALL_CONTEXT_DIR` defaults to
`../.local/plaza-context`, with optional `GAME_CONTEXT.md`/`WORK_CONTEXT.md` (8 KiB
each, also the bound on each shipped brief). Runtime facts are bounded to 4 KiB.
`PROJECT_GUIDANCE_FILE` defaults to optional `PLAZA_AGENTS.md` in the main
project (32 KiB). Both support `PLAZA_` overrides. Unsafe/symlink/oversized guidance
fails visibly as `context_unavailable`; diagnostics record source identities and
revisions without instruction bodies. Config path settings remain startup snapshots.

| Retained object | Location |
|---|---|
| Execution files | `<project-parent>/.plaza-worktrees/<sanitized-project-name>-<project-key>/<domain-id>/execution` |
| Execution branch | `plaza/workspace-<project-key>-<domain-id>` |
| Identity descriptor | `<git-common-dir>/plaza/workspaces/<domain-id>.json` |
| Canonical project notes | `<git-common-dir>/plaza/session-memory/{TODO,HANDOFF,PROGRESS}.md` |
| Execution reservation | Actual execution Git directory's `plaza-execution.lock` and `plaza-unclean.json` |
| Memory ownership | `<git-common-dir>/plaza/memory.lock` and `plaza/runs/<sha256(owner_run_id)>.lock/.json` |
| Recording | Configured `LOG_DIR/runs/<archival-run-id>/manifest.json` |

Valid idle legacy Core ownership is adopted in place, preserving its old path,
branch, commits and dirty files. Uncertain ownership blocks reuse; directory names
alone never prove ownership. All departments share one project note set.

TODO/HANDOFF are at most 16 KiB each; TODO has at most 64 items. PROGRESS is at
most 32 KiB with 12 recent entries and a bounded recap. Limits count complete
UTF-8 files. Notes are repository data/prior context, not instruction authority,
a complete transcript, a queue or SDK recovery. A fresh invocation loads valid
notes; completed work is not automatically rerun. Old process-local result replay
is not promised after bridge restart.

Inspect recovery state with read-only `describe_workspace` and `domain_status`:
record identity, worktree/branch, edits, generation, reservation and memory
saved/unsaved status/revision. If the owner is reachable, request normal Stop and
wait for confirmed inactive cleanup. Preserve tracked and untracked execution
edits on success, cancellation and failure; reuse does not reset or merge them.
On `cleanup_failed`, unavailable/unsaved memory or uncertain shutdown, retain
files, logs, descriptor and markers. Inspect actual SDK/bridge activity, OS lock
ownership, Git registration, canonical notes/revisions and the exact archive
manifest. PID absence, elapsed time or a free lock with an unclean marker does
not establish safe reuse. Stable lock inodes normally remain after clean Stop.
Never apply blanket lock/marker deletion, `git reset --hard`, `git clean`, automatic
worktree removal or a claimed daemon-killed shortcut. There is no generic recovery
CLI; establish actual cleanup and diagnose damaged state before manual repair.
For example, an interrupted `git worktree add` may leave a `creating` ownership
descriptor at `<git-common-dir>/plaza/workspaces/<domain-id>.json`, with incomplete Git
registration or an execution directory. Preserve the descriptor, registration,
files and logs; compare their recorded identities and actual Git/lock/process
state before deciding on a specific repair. A `creating` record is not permission
to delete an ownership record or discard the execution tree.


## Copying NPC dialogue and domain results

Use **Copy** or **Select All** in the NPC header or the domain pane's actions.
Right-click transcript text for the same menu. Drag across text to select it,
then use Copy to transfer it. Copy uses your selection when
present; otherwise it copies the displayed transcript. Only currently revealed
plain text is copied, including Unicode, line breaks and displayed context,
speaker and status labels. Hidden typewriter text is excluded. Empty text
disables the controls, and disconnected retained history remains copyable.

Select All focuses the transcript so standard platform Select All/Copy shortcuts
continue to work (Ctrl+A/Ctrl+C or Ctrl+Insert on Linux; platform mappings apply).
Tab reaches both buttons. The input composer keeps its native editing and menu.
Copying does not submit, start, stop or replay work. Closing or changing the
character, domain or project dismisses the transcript menu and clears selection.

The earlier runtime live report remains bound to its original 48 sources at
`eaba12a`; it does not establish this newer clipboard helper or prefix renderer's
behavior. The focused panel scenes cover its UI behavior without a provider. For optional real
Linux clipboard verification, set DISPLAY to an owned X11 display with Godot
and `xclip` available:

```bash
python3 scripts/check_chat_clipboard.py --godot /path/to/godot \
  --xclip /path/to/xclip --output /tmp/plaza-clipboard.json \
  --screenshots /tmp/plaza-clipboard-layout
```

The driver runs production panels with synthetic fixtures, reads the clipboard
and X11 PRIMARY from another process while Godot runs, and saves exact observed payloads and
optional layout images. With no DISPLAY it reports a skip; headless checks alone
do not establish desktop clipboard behavior. Native laptop acceptance remains
separate from these checks.

## NPC conversation history and controls (M11)

Conversation-backed extras retain the M11 history controls below. Working
catalog characters use the shared department history described above. Each extra
keeps an ordered display transcript, draft and reading position during this game session. A→B→A restores them immediately; a late A reply stays with A
while B remains visible. Each agent permits one pending question, with separate
agents allowed to queue on the bridge's serial connection. A failure remains in
that agent's transcript and releases its composer. Newly visible replies reveal
progressively; restored history appears immediately. Reading older text pauses
follow; scrolling to the newest visible text resumes it.

Drag any panel edge or corner to resize. The minimum is 480×260 logical pixels
when it fits, otherwise the viewport size. Controls reflow within the viewport;
the desired dimensions return after a temporary viewport clamp. Size preferences
last only for this session.

| Control | Behavior |
|---|---|
| Wheel / scrollbar | Read transcript history; manual upward scrolling pauses follow. |
| PgUp / PgDn | Page the transcript, including while composing. |
| Ctrl+Home / Ctrl+End | With transcript focus, jump to oldest/newest; End resumes follow. |
| Enter | Submit nonempty enabled composer input once. |
| Escape | Close/background the interaction while preserving draft and pending request. |
| Tab / Shift+Tab | Traverse enabled chat controls in either direction. |
| Composer Home/End, selection, edit and copy shortcuts | Retain native text editing. |

Handled chat navigation and typing do not move the player. Disconnect fails each
pending request visibly once and archives that display generation as read-only,
including unsent drafts. Actual reconnect marks a **fresh model context** and
starts a blank editable draft. Archived text is never resent or silently copied
into the fresh draft. Display history does not survive a game restart, and there
is no history-download endpoint.

The three retention limits are independent:

- **Model context:** bridge `CONTEXT_MAX_MESSAGES` defaults to 40 messages per
  agent/connection, retaining successful exchanges only. Reconnect resets it.
  Every SDK request creates a fresh client, submits one JSON transcript and
  disconnects before success is committed to history. No SDK client/session is
  retained or resumed; continuity comes from the bridge's bounded transcript.
  Only successful terminal assistant output enters history; errors, truncation
  and cancelled requests do not. NPC chat is text-only, with tools/MCP/skills and
  discretionary project/user hooks/plugins disabled; mandatory managed policy
  remains effective. Observed SDK session IDs are recorder metadata, not durable
  resume handles or extra response fields.
- **Frontend display:** Project Settings `plaza/chat/history_max_messages=200`
  and `plaza/chat/history_max_bytes=1048576` bound each known agent across all
  reconnect generations, drafts, pending/failed messages and archived drafts.
  Pending content is protected; oldest terminal exchanges can be evicted with an
  omission notice. Inadmissible input/draft changes fail visibly. Oversized
  display replies retain a Unicode-safe excerpt with `[truncated]` inside the
  byte bound; the submitted task, live response and model context stay intact.
- **Disk:** M10 archive quotas, file rotation, age and record limits below bound
  recording separately. Disk history never refills display or model context.

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

These are all 25 keys and their built-in/shipped defaults:

| Key | Default | Constraint / meaning |
|---|---|---|
| `CONFIG_VERSION` | `1` | Supported integer version |
| `HAIKU_MODEL` | `claude-haiku-5-5` | Nonempty provider ID |
| `SONNET_MODEL` | `claude-sonnet-5-5` | Nonempty provider ID |
| `OPUS_MODEL` | `claude-opus-5-5` | Nonempty provider ID |
| `FABLE_MODEL` | `claude-fable-5-1` | Nonempty provider ID |
| `ADVISOR_MODEL` | `FABLE_MODEL` | Symbolic reference to one of the four model keys |
| `CONVERSATION_BACKEND` | `claude_code` | Exactly `claude_code` or explicit `messages_api`; no automatic fallback |
| `CONVERSATION_TIER` | `haiku` | `haiku`, `sonnet`, `opus`, `fable` |
| `DOMAIN_TIER` | `sonnet` | Same four tiers |
| `CONVERSATION_TIMEOUT_SECONDS` | `60` | Positive finite operation deadline; SDK cleanup can extend elapsed time as below |
| `CONVERSATION_MAX_OUTPUT_TOKENS` | `4096` | Positive integer; SDK passes the cap through supported `CLAUDE_CODE_MAX_OUTPUT_TOKENS` |
| `CONTEXT_MAX_MESSAGES` | `40` | Even integer, at least 2; connection/agent model context |
| `DOMAIN_MAX_TURNS` | `20` | Positive integer; existing domain execution cap |
| `DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS` | `false` | Strict boolean: `dontAsk` or `bypassPermissions`; mandatory guards remain |
| `DOMAIN_MAX_BUDGET_USD` | `1.0` | Positive finite number; existing domain budget cap |
| `TRANSCRIPTS_ENABLED` | `true` | Boolean; `false` disables message-body archives, keeps events |
| `LOG_DIR` | `../.local/bridge-logs` | Nonempty path, resolved as above |
| `LOG_LEVEL` | `INFO` | `INFO`, `DEBUG`, `WARNING`, `ERROR` |
| `TRANSCRIPT_MAX_RECORD_BYTES` | `262144` | Integer ≥4096; encoded JSON plus LF, also applies to events |
| `TRANSCRIPT_MAX_FILE_BYTES` | `5242880` | Integer ≥record bound; rotate before exceeding |
| `LOG_MAX_TOTAL_BYTES` | `104857600` | Integer ≥file bound; managed archives including manifest temps |
| `LOG_MAX_AGE_DAYS` | `14` | Positive integer; prune eligible files by age first |
| `WORKSPACE_ROOT_DIR` | `null` | Existing project directory, or unconfigured domains; relative to selected config directory |
| `INSTALL_CONTEXT_DIR` | `../.local/plaza-context` | Optional bounded game/work guidance; relative to selected config directory |
| `PROJECT_GUIDANCE_FILE` | `PLAZA_AGENTS.md` | Main-project relative guidance file; default file may be absent |

Numeric settings reject booleans, non-finite values and fractional integer limits.
Models have no fallback or automatic upgrade. `config.model_for("opus")` resolves
the explicit tier. The future-use helper `config.advisor_for("sonnet")` resolves
`ADVISOR_MODEL` only if its tier is strictly higher in
`haiku < sonnet < opus < fable` order and its provider ID differs from the caller's.
That relationship is checked when resolving; choosing Fable for ordinary chat
remains valid. There is **no advisor execution or default advisory routing**.
Keep credentials in the existing environment/SDK bindings, never in this config
or other non-secret settings. Native CLI authentication owns the default mode;
explicit `messages_api` accepts only `ANTHROPIC_API_KEY`.

The default 60-second operation deadline covers SDK connect/query/receive.
Disconnect runs before a response/history commit; the installed SDK's bounded
subprocess cleanup escalation can add approximately 20 seconds, including after
cancellation. Do not treat the deadline as an instantaneous teardown guarantee.

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
session-only client scrollback. They are not replayed into models, durable
user/project state, or SDK restart recovery. Conversation responses echo optional
opaque request IDs; see [`bridge/PROTOCOL.md`](bridge/PROTOCOL.md).

Godot native output is configured separately, for example
`godot --log-file /tmp/plaza-godot.log --verbose .`. Its files are outside the
bridge quota and must be managed separately.

## 4. Run tests

```bash
godot --headless --import                     # import assets (once per clone)
godot --headless tests/smoke_test.tscn        # the build gate
python3 scripts/validate_specs.py             # governed-document validator
python3 -m pytest bridge/tests/ tests/ -q     # offline bridge/tooling tests
python3 scripts/run_headless.py conversation_store transport_client dialogue_panel
npm run test:bridge-integration               # real Godot + Python, fake provider
```

Or use the npm facade (activate the Python venv with `requirements.txt` installed;
Godot 4.7.1 must be available as `godot` on PATH for the import step; no npm
install needed):

```bash
npm test                       # validate → import → smoke → M11 scenes → integration
```

The Python scene runner and bridge integration honor `GODOT_BIN` when selecting
the executable; the direct `godot` commands and npm import step require PATH.
The scene runner requires a complete success line with a positive numeric count
and rejects engine/script load errors even if Godot exits zero, with a 30-second
timeout per scene. The Python integration starts its real bridge listener on an
ephemeral loopback port and
supplies the URL to `tests/godot_bridge_integration.tscn`; run it through pytest,
not by launching that scene alone. It controls delayed provider replies, verifies
hidden-agent success/B failure, a pending disconnect, archived drafts, fresh
server context without display replay, and tiny Unicode display limits. It uses
no credentials or network provider. Python-only environments may skip it when
Godot is absent; `npm run test:bridge-integration` and the Godot CI job require it.
Existing smoke and the separate real two-client conversation harness remain gates.

The earlier bounded API smoke on 2026-10-18 passed two turns each through Godot
and plain Python on the first attempt, checking Godot recall within the current
rendered assistant span. That historical run used the direct Messages API path,
bypassing the required default runtime. It proves direct-provider compatibility,
not Agent SDK execution; future API-mode runs must explicitly select and identify
`messages_api`.

A separate controller-observed run **passed at 2026-10-18 22:32:53 UTC** through
real Agent SDK **0.2.136** / Claude Code CLI **2.1.228**, backend `claude_code`,
model `claude-haiku-5-5`: Godot and plain Python each recalled the nonce in two
turns on their first attempt, with four distinct observed SDK session IDs.
[Fresh evidence and transcript](specs/evidence/npc-sdk-live-2026-10-18.json) preserve
this run separately from frozen Sprint 6 evidence. Authentication was the cloud
API key inherited by the CLI, not direct Messages API execution. Four live Haiku
requests ran; billed amount was not measured. `owner_read` remains false.
This proves neither laptop subscription authentication nor desktop acceptance,
M12 domain lifecycle/background execution or durable resume. The existing runner
stopped the bridge with SIGTERM and left its manifest open; the run does not prove
graceful shutdown. Deterministic fake-provider coverage above remains independent
of this live result.

<a id="desktop-acceptance-checklist--outstanding"></a>

### Desktop acceptance checklist

On 2026-10-21 the owner accepted M10/M11 operation on the laptop's local `dev`,
using both Claude subscription and API-token authentication; the output cap was
a setting ([PLZG-284](https://tasteslikegood.atlassian.net/browse/PLZG-284)).
This is owner-reported milestone acceptance, separate from the cloud run above.
No itemized desktop test log was supplied, so the reusable checklist below is
left unticked. For future verification, record date, platform, observed result
and any issue for each item; headless checks do not replace desktop observations.

- [ ] A→B→A restores ordered transcript, drafts and reading position. Let A succeed
  late while B is visible, then make B fail; each result stays with its agent.
- [ ] Drag all four edges and all four corners, then shrink/grow the desktop
  window; controls stay reachable and input/history/pending state remains intact.
- [ ] Use wheel and drag the scrollbar thumb. Read older messages while a new
  reply reveals; position stays stable. Reach newest text to resume follow.
- [ ] PgUp/PgDn work while composing. With transcript focus, Ctrl+Home/End reach
  oldest/newest and End resumes follow. Enter submits nonempty enabled input once.
- [ ] Escape releases focus without losing draft/pending. Tab/Shift+Tab traverse
  enabled controls predictably. Native composer Home/End, selection, edits and
  clipboard copy work. Typing and handled navigation do not move the player.
- [ ] Disconnect during a pending query; its failure and archived draft are
  visible and read-only. Reconnect shows a fresh-context notice and blank draft,
  preserving old display history within limits without replaying it to the model.

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

## M12 live evidence and desktop checks

**Runtime-correction Linux API-key cloud acceptance passed.** The new
[live ledger](specs/evidence/m12-runtime-live-attempts-2026-10-22.json) and
[unchanged report](specs/evidence/m12-runtime-live-dontAsk-2026-10-22.json)
record one selected `dontAsk` attempt at clean `eaba12a`. Chief setup on `main`,
explicit working-character controls, background work with an independent extra,
one rendered/replayed result, saved notes, restart/readback and separate-project
isolation passed. All three actual recording manifests have `status: closed` and
`ended_at`; owned SDK workers/transports finished, observed CLI children exited
0, run/lease markers detached and no forced teardown occurred. Before/after and
actual runtime baselines matched. The report binds **48 relevant source files**;
this is a conservative source inventory, not trace coverage of every file.
The runner composes `BridgeServer` directly; actual CLI SIGINT/SIGTERM and failed
SDK-cleanup behavior have separate provider-free Linux process tests.

The new [guard ledger](specs/evidence/m12-runtime-guard-attempts-2026-10-22.json)
records **29/29 cases in each permission mode** at `ec5d236`, with twelve source
fingerprints. The controller inspected each separately invoked matrix, verified
the actual installed SDK/AnyIO/CLI and bundled binary hash against both, then
atomically published the envelope and verified both runtime modes. Activation
and unchanged raw reports were committed at `eaba12a` before live. No paid retry
ran and no earlier evidence was overwritten. The
[offline record](specs/evidence/m12-runtime-offline-2026-10-22.json) records
**1,990 Python tests, 118 subtests and zero skips** plus all eight Godot gates,
formatting, fatal lint and spec/delivery validation at `ec5d236`.

The correction decodes supported final answer/memory envelopes while preserving
ordinary prose; memory proposals still pass the real store's strict grammar.
Both panes show fixed, readable failure causes alongside retained partial output.
Enabled transcript archives preserve that partial text; operational diagnostics
contain only bounded categories and hashed tool correlation. Work guidance
explains the managed branch and root working directory without relaxing checks.
Requested CLI shutdown drains owned work; uncertain SDK cleanup retains an open
manifest and ownership evidence instead of reporting a clean close.

Runtime remains SDK 0.2.136, AnyIO 4.14.2, bundled CLI 2.1.228 and Godot 4.7.1 on
Linux with API-key authentication. Guard terminal estimates are USD 0.7837115 and
0.734316 (24 observations per mode); the three live domain terminal estimates are
USD 0.276198, 0.104048 and 0.074404. Cancellation queries and separate Chief/NPC
calls are not fully represented; these are estimates, not billing totals. Two
guard modes do not establish live UI acceptance in both modes. The owner has
already confirmed laptop tools/worktree/memory behavior and latest OAuth;
new correction-specific laptop observations and remaining desktop checks are
still open. Git worktrees and permission controls are not host/network/process
containment; stronger isolation remains separate M13/M14 planning. Copy/Select
All and context menus are separate PLZG-293 work. No M12 completion is claimed.

**Historical character/domain amendment evidence follows unchanged.** Its
[live attempt ledger](specs/evidence/m12-character-live-attempts-2026-10-22.json)
and [unchanged accepted report](specs/evidence/m12-character-live-dontAsk-2026-10-22-final.json)
record the selected `dontAsk` Godot/plain-client flow at clean `a582f11`.
All three bridge lifetimes closed cleanly. Native NPC controls, typed Chief setup
on main, background work with independent extra conversation and replay, persisted
notes after restart/readback and separate-project isolation passed. The controller
verified the clean executed HEAD, equal before/after/actual runtime baselines and
all **44 recorded source hashes** before recording evidence. Runtime: SDK 0.2.136,
AnyIO 4.14.2, bundled CLI 2.1.228 and Godot 4.7.1 on Linux, API-key authentication.
This historical run proves live behavior in `dontAsk` only and did not establish
another laptop binary or native OAuth/desktop acceptance.

The [guard ledger](specs/evidence/m12-character-guard-attempts-2026-10-22.json)
records fresh **29/29 passing cases in each permission mode** at `ba5599b`, with
ten source fingerprints and actual runtime/binary validation before publication.
Those unchanged reports were committed with the then-current two-mode envelope at
`a582f11` before live. The earlier 58 passes at `e67c926`, pre-SDK setup failure,
and old six-source activation remain historical; no old hashes were refreshed.
The [first live report](specs/evidence/m12-character-live-dontAsk-2026-10-22-attempt1.json)
at `5f20d9c` remains failed with `wire domain_id`. Its typed extra-status validator
and subsequent short-lock contention corrections were reviewed before fresh proof.
Every attempt is retained; no automatic paid retries ran.

The recorded corrective offline checks at `6917d73` passed **1,849 Python tests
and 118 subtests in 161.85s with zero skips**, including both-mode offline
orchestration with required pinned Godot. All eight headless gates passed: smoke
132 agents; conversation store 578, transport client 154, dialogue panel 220,
domain store 136, domain transport 69, domain panel 111 and character domain 52
checks. The earlier [offline record](specs/evidence/m12-character-offline-2026-10-22.json)
retains its original 1,810-test baseline and source hashes.

Historical guard terminal estimates are USD 0.77665125 (`dontAsk`) and USD 0.71560025
(`bypassPermissions`), from 24 retained terminal observations per mode. Accepted
live domain terminal estimates are USD 0.2681655, 0.10136150000000001 and 0.07188675.
Guard nonterminal cancellation queries and separate live Chief/NPC calls are not
fully represented; these observations are not billing totals. Two guard modes do
not imply live UI acceptance in both modes. No merge or owner desktop completion
is claimed by these cloud results.

Historically, on 2026-10-21 the [29-case guard matrix](specs/evidence/m12-guard-2026-10-21.json)
and [real headless M12 flow](specs/evidence/m12-live-2026-10-21.json) passed on
Linux with SDK 0.2.136, AnyIO 4.14.2, bundled CLI 2.1.228 and Godot 4.7.1.
The live code is committed at `c128b543d73864099002247c7f32854e2b020c3f`;
the report also binds actual dirty documentation status and runtime/source hashes.
All three bridge lifetimes and five SDK CLI processes exited 0; actual manifests
are closed with `ended_at`, domain leases released and memory-run markers detached.
The single tool result survived clean restart; fresh readback used notes without
reexecution, and repository B received none of A's nonce/notes.

The [attempt ledger](specs/evidence/m12-live-attempts-2026-10-21.json) preserves
four failed reports and their concrete corrections, including the real Chief's
independent denial. The accepted five-invocation run reported USD 0.240059 in
terminal costs; the guard matrix reported USD 0.753546. These are SDK-reported
API-key costs, not evidence of native subscription billing. No automatic paid
retries ran. The successful result/notes and every failed artifact tree remain
preserved; the evidence includes their exact paths. Linux headless evidence does
not complete M12 or establish another laptop binary or desktop behavior.

After the final review corrections at `73fcfc5`, a [fresh final guard matrix](specs/evidence/m12-guard-final-2026-10-21.json)
passed all 29 cases against the changed probe source. The fixed activation manifest
was byte-identical to that inspected report and passed validation at that time.
Those sources and the single-record activation format are now superseded. Its reported cost was USD 0.72207375. The [final guard attempt ledger](specs/evidence/m12-guard-final-attempts-2026-10-21.json)
retains an earlier seven-case failure (USD 0.1846675): Edit was denied and cleanup
completed, but repeated Reads exhausted the four-turn case limit. One further full
attempt was deliberately authorized after inspection, with unchanged sources,
prompts, caps and validator. The failed report remains failed. This refresh does
not re-date the historical live flow or establish laptop/desktop acceptance.

The bounded runners are deliberate paid operations with **no automatic retries**:

```bash
python3 scripts/m12_tool_guard_probe.py --permission-mode dontAsk --output /tmp/m12-guard-dontAsk.json
# Inspect the outcome before deliberately running the other mode:
python3 scripts/m12_tool_guard_probe.py --permission-mode bypassPermissions --output /tmp/m12-guard-bypassPermissions.json
# Only after both records have passed review and runtime activation:
GODOT_BIN=/absolute/path/to/godot-4.7.1 python3 scripts/m12_live.py --output /tmp/m12-live.json
```

Choose fresh output paths with existing writable parents. Both runners reserve
the destination before runtime/child/case work and atomically publish a complete
report without replacing existing evidence. A sibling `.<report-name>.reserve`
coordinates runners; interruption may retain it or a staging file for inspection.
A publication collision preserves the other report and the attempted staging
report. The live runner retains a separate `/tmp/plaza-m12-live-*` artifact
tree on failure or success. Inspect raw bridge/Godot logs, stages, release/result,
notes, markers and actual manifests before publishing its allowlisted JSON.
Failed/partial runs, nonzero child exits, forced teardown and missing/open
manifests fail acceptance. Do not treat a previous output file as a new pass.
`--help` describes the new runner without starting providers. Legacy bridge and
Sprint 6 scripts do not implement help parsers; `--help` there may start work.

The probe pins SDK 0.2.136, AnyIO 4.14.2 and bundled CLI 2.1.228. It checks 29
Read/Edit/Bash, MCP, delegated and cancellation cases, at most 27 queries, model
`claude-haiku-5-5`, 45 seconds and USD 0.20 **per case**, stopping at the first
failure. MCP/delegation probe coverage does not enable them in product domains;
production tools remain Read/Edit/Bash. A callback alone never proves denial.
A complete exit-0 report must show real denied-tool non-execution, cleanup,
exact source hashes, versions and the actual local bundled binary hash.

Fresh probes are **not automatically activated**. Product activation reads fixed
`bridge/tool_guard_acceptance.json`, an envelope with `schema_version:1` and
`records` keyed by `dontAsk` and `bypassPermissions`. Both complete records must
match all twelve guarded source hashes. Each selected mode also verifies the pinned
SDK/AnyIO/CLI version and actual bundled binary SHA; there is no evidence override.

For publication, build `acceptance_envelope(records)` from the two unchanged
reports and call `check_acceptance(envelope, None, mode)` for both modes. **Before
replacing the fixed artifact**, verify installed SDK 0.2.136, AnyIO 4.14.2, actual
bundled `--version` exactly `2.1.228 (Claude Code)`, and that its SHA matches both
records. Stage exclusively, atomically replace, then call `_verify_runtime(mode)`
for each mode as a final local check. These validation calls do not contact providers.
Retain both raw reports and all failed attempts. Never refresh hashes alone or
change observations to pass. A failed/unavailable mode leaves tools blocked.
Another laptop OS/architecture needs its own exact-source/binary/auth evidence;
keep Linux evidence historical and disclose the local manifest change.

The live runner uses a disposable empty configured project, real tools-disabled
Chief typed setup, explicit Core character Start/Send, shared pane handoff,
actual physical background/return and independent explicit extra rendering, one SDK-created
nonce result, plain-client replay, clean restart/readback and independent repo B.
Its original SDK class/default factory and production runtime verification remain
active; transparent method/dispatch/listener and context-metadata observers are
disclosed. The runner declares `fixture-extra-a`/`fixture-extra-b` outside the
catalog, uses disposable installation/project guidance, records zero queries at
Start, and binds the actual selected permission mode in all three lifetimes.
It honors `GODOT_BIN` for both launch and version proof and rejects configuration
overrides that redirect the fixture or disagree with its selected mode.
The supervisor releases the nonce only after independently corroborated Godot
background acknowledgment and unrelated NPC completion. It never creates the
claimed result. Initial, restart and final result checks require a bounded regular
file at the canonical execution location, rejecting symlinks and special files
with no-follow open/descriptor checks. Configured Haiku tasks use 8 turns/USD 0.35 each, at most 3 domain
queries; Chief/NPC use one turn and a 65-second operation deadline. Per-stage
waits are 100 seconds, normal bridge drain 35 seconds; process escalation contains
hangs but fails clean acceptance. Private artifacts can contain disposable notes
and output; do not publish credentials, environment, full options or raw SDK dumps.

M12 acceptance status is recorded separately from historical NPC SDK evidence.
The owner has confirmed laptop tools/worktree/memory behavior and latest OAuth;
these are owner reports, not itemized results for the new correction below.
Cloud Linux API-key runs do not prove laptop subscription billing, a different
binary, or desktop behavior. M12 remains open for delivery and remaining
acceptance. Record date, OS/Godot/CLI binary, tested commit, auth category and
observed result; baseline connectivity does not need another confirmation.

Correction-specific laptop checklist, using disposable projects for deliberate
failure checks:

- [ ] Run and inspect both local guard modes against the intended new sources,
  laptop binary and auth; record the selected live mode.
- [ ] A supported final answer/memory envelope renders as readable prose; a valid
  proposal updates the project notes. Malformed or unsupported proposals preserve
  useful output and do not apply rejected proposal fields; the bridge still saves
  its labeled task/result excerpts and observed outcome.
- [ ] A managed-branch/root-cwd readiness failure shows a useful bounded cause in
  NPC dialogue and the domain pane. Restore the expected state and explicitly
  refresh/refocus; no automatic checkout/reset or weaker guard is expected.
- [ ] A failed query shows its readable cause with any partial answer, including
  an empty answer. With transcripts enabled, that partial text is retained;
  metadata-only logs do not acquire message bodies or arbitrary exception text.
- [ ] Ordinary requested bridge shutdown closes the manifest after drain and
  removes run/lease markers. If cleanup is uncertain, keep its open manifest and
  ownership evidence for inspection; do not force an acceptance pass.

Remaining desktop items, retaining earlier owner confirmations:

- [ ] Approach working characters without starting work; use typed referral/Prepare with the Chief and verify main/shared notes without an eager worktree.
- [ ] Use dialogue Let's work/Send with mouse and keyboard; Enter never starts implicitly, pending draft stays editable, shared pane switching submits once, and scroll/selection/focus preserve movement.
- [ ] Physically leave the anchor during real work; observe background state and hidden panel.
- [ ] Switch Core representatives and preserve originating attribution; reach an explicit extra, finish its reply, return/refocus and see one domain result.
- [ ] Stop idle and background sessions, confirm release, and start again; late status/reconnect packets never steal focus, switch the selected representative or submit work.
- [ ] Change guidance between Runs and verify refresh; unsafe/oversized guidance fails visibly without silently dropping instructions.
- [ ] Exercise a visible unsaved-memory state; confirm its revision/warning remains visible and recovery preserves edits.
- [ ] Restart cleanly, explicitly read prior notes, and verify separate-project isolation.
