---
doc_id: BRIDGE-PLATFORM-DESIGN
title: Bridge-first platform — local observability and conversation UI
tier: 2
authority: implementation
status: ACTIVE
doc_set_version: 0.2.16
last_updated: 2026-10
owner: adamtasteslikegood
derives_from: [PLATFORM-DECISIONS, DESIGN-25D]
supersedes: []
enforcement: intended
gates: [Validate Specs:live]
weakest_claim: Hosted user-scoped durability is a later milestone.
---

# Bridge-first platform — local observability and conversation UI

**Approval state, 2026-10-18:** the owner approved this written specification and
the separate M10 implementation plan, including mouse resizing and expanded
keyboard controls for M11. M9 documentation alignment and written approval are
complete; M10 settings and bounded recording are implemented with deterministic
acceptance coverage. M11 history, correlation and controls are implemented under
the [M11 plan](../plans/2026-10-18-m11-npc-conversations.md), with deterministic
coverage and desktop acceptance outstanding. This ACTIVE design also specifies
future durable-state functionality, so `enforcement: intended` remains.
M12–M15 require their own detailed designs before execution.

The owner explicitly confirmed synchronous NPC calls with timeout (`D-033`,
superseding `D-006`) and asynchronous domains with buffered results and existing turn/budget caps
(`D-034`). `PLATFORM-DECISIONS` ratifies centralized non-secret settings (`D-035`)
and bounded local archives/diagnostics (`D-036`), with the exact contracts below.
The subsequent runtime correction `D-037` is implemented: normal model execution,
including NPCs, defaults to Claude Code through Agent SDK; direct Messages API
conversation is an explicit API-key-only opt-in with no automatic fallback.
The CLI retains its native authentication handling. See [Quick start](../../../QUICKSTART.md)
for the fresh cloud SDK recall evidence, authentication and remaining limits.

**Owner scope update, 2026-10-21:** M10/M11 operation is accepted on the owner's
laptop using local `dev`, with Claude subscription and API-token authentication;
the output cap was a setting. This supersedes the outstanding laptop acceptance
statements dated 2026-10-18 below, without adding cloud or shutdown evidence.
The owner now requires a minimum dedicated execution Git worktree in M12, ahead
of the broader worktree/runtime isolation previously grouped under M14. The
bridge selects one project through `WORKSPACE_ROOT_DIR` with an environment
override, creates/reuses its worktree, and creates/reads three native project
memory files (TODO, handoff, turn summaries), isolated by repository. Empty or
non-Git projects require Chief Architect confirmation before initialization on
`main`. Other NPCs refer the player to that agent; interacting with the Chief
Architect triggers review and its confirmation authorizes setup without another
human prompt. All agent tools pass a shared Git/worktree/memory readiness check. The
[detailed M12 specification](2026-10-21-m12-domain-execution-design.md) is DRAFT
for written review. Richer persistence and stronger execution isolation can be
resequenced or combined through an integrated provider; none is selected here.

## 1. Purpose and scope

Plaza is an agentic workspace built around a UI-independent bridge and execution
layer. The current Godot prototype proves spatial interaction with real agents.
The platform goal is durable history and execution state scoped to authenticated
users, their projects, and domains within those projects, with worktrees providing
execution isolation. Godot is one client of that platform (`D-005`, `D-020`).

The existing 2.5D design describes an early prototype, not the full platform goal.
Its scene and narrative constraints remain applicable to that prototype. This
specification changes platform priorities without rewriting storyboard beats.
M5's scripted assistant (`D-010`) and M6's unlock/map work are separate, deferred
frontend milestones; neither is renamed to cover NPC conversation history.

The immediate design covers documentation alignment (M9), local configuration and
observability (M10), and usable NPC conversation controls/history (M11).
Hosted user-scoped durability is a later milestone. Authentication, databases, domain
coordination, new worktrees, streaming, model-provider abstraction, and a custom
logging framework are outside M10/M11.

## 2. Historical pre-M10 prototype baseline

The following table preserves the source-inspected **pre-M10** design snapshot.
Its configuration/constants row is historical: current code uses centralized
validated settings and bounded archives. See §§5–6 and the
[operating guide](../../../QUICKSTART.md#bridge-settings-and-archives-m10).
This snapshot is not evidence of later UI features or durable recovery:

| Concern | Pre-M10 implementation | Boundary |
|---|---|---|
| Ordinary NPC conversation | Messages API with the agent definition as system prompt | All Godot NPC questions use this path; department membership does not select a domain session. |
| Model context | Server holds history per WebSocket connection and agent | Last 40 messages/20 successful exchanges; disconnect/restart loses it. No durable conversation ID. |
| Visible dialogue | One response replaces the previous body | Approaching an NPC resets the panel to its description. No scrollback transcript is restored. |
| Scrolling | RichTextLabel scrolling enabled | Typewriter code forces the scroll position; no dedicated paging/resize handling. |
| Pending requests | One client-side pending-agent slot | Offscreen responses are discarded by the panel; switching NPCs can overwrite pending tracking. |
| Domain execution | Backend lifecycle manager and retained Agent SDK client | Output buffer and manager are process-local; Godot does not send domain messages. |
| Domain identity | SDK session ID derived from domain ID | No user/project scope; assigning an ID does not establish SDK restart recovery. |
| Configuration | Python constants and constructor overrides | No centralized bridge config file or bounded run/agent transcript recorder. |

Sources: [conversation engine](../../../bridge/conversation.py),
[bridge server](../../../bridge/server.py), [domain runtime](../../../bridge/domain_session.py),
[Godot client](../../../scenes/bridge/ws_client.gd), and
[dialogue panel](../../../scenes/hud/dialogue_panel.gd).

The earlier API-key live test completed two-turn recall from Godot and Python
through the direct Messages API during onboarding. It bypassed the required
default runtime and is historical direct-provider compatibility evidence only.
The owner separately reported laptop Claude Code credential operation; that report
did not prove SDK execution in this environment. Neither observation proves
domain tool execution or restart recovery.

## 3. Milestone sequence and acceptance

These identifiers extend the existing M1–M8 sequence. Their order expresses
dependencies, not a date forecast. None of M10–M15 is completed by this document.

| Milestone | Deliverable | Acceptance |
|---|---|---|
| M9 | Align platform direction and prototype wording | This written spec, roadmap and protocol distinguish implemented, planned and deferred behavior; documentation validation passes and the owner reviews the written spec. |
| M10 | Central config and bounded local observability | Configuration precedence/validation, run manifests, per-agent transcripts, debug events, rotation, quota/age pruning and failure cases pass focused tests. |
| M11 | Usable NPC conversations | Mouse resizing, viewport reflow, wheel/scrollbar/paging keys, focus behavior, A→B→A scrollback and late-response correlation meet §7 tests. |
| M12 | Configured project, worktree bootstrap, three-file memory and domain execution | Create/reuse a dedicated worktree, initialize non-Git projects only after Chief Architect confirmation, and persist isolated project notes. Godot backgrounds/refocuses real SDK work and consumes results; a plain client exercises the same protocol. Details await written-spec review. |
| M13 | Local durable workspace state | User/project/domain-scoped conversations and execution metadata survive restart/reconnect; application-history restoration and SDK-task recovery are tested and reported separately. |
| M14 | Independent execution workspaces beyond M12's minimum | Domain work executes in assigned worktrees inside its project; concurrent changes stay isolated and can be reviewed for integration. |
| M15 | Authenticated durable service | Authenticated ownership, isolation and recovery work across processes/devices; select the managed durability provider in that milestone's design. |

## 4. State boundaries and storage choices

Keep model context, client display history, recorded transcripts, diagnostic events
and SDK execution sessions distinct. Changing transcript retention must not trim
live prompt context, reset a conversation, or delete authoritative workspace state.

For M10, use append-only JSONL for transcripts and Python standard logging for
diagnostics. This is small enough to inspect by hand and fits bridge-run/agent
folders. It provides an archive, not automatic conversation restoration.

The owner's 2026-10-21 scope update adds bounded persistent Markdown project notes
in M12. These support later-session context without restoring an SDK process,
durable output buffer or complete application history. They are bridge-owned
project data, not Plaza development-session instructions.

SQLite plus JSONL is the preferred richer local option at M13: SQLite owns durable
application state and relationships; JSONL remains diagnostic/export output. Avoid
maintaining two independent authoritative histories. Managed durable objects are
an option for M15, not a dependency of the local prototype.

The future ownership hierarchy is user → project → domain, with execution runs
associated with worktrees inside the project. Agent IDs describe participating
roles; they are not user identities. A bridge run, transport connection,
conversation, domain, worktree and provider session each need distinct identity.
M10 uses local project labels only; these labels provide no authentication or
multi-user isolation. Later work must scope domain identity to user and project,
rather than treating the current domain-only UUID as durable ownership.

## 5. M10: centralized configuration

Use a committed, non-secret `bridge/config.json` containing defaults. Built-in
defaults are the fallback; the default JSON file, or the file selected by
`BRIDGE_CONFIG_PATH`, overlays them; documented `PLAZA_<KEY>` environment overrides
win last. An explicitly selected missing/unreadable file, invalid JSON, unknown
key, unsupported version, wrong type or invalid bound fails startup with a useful
setting-specific error. Resolve relative LOG_DIR paths against the selected
configuration file's directory. Read settings once at startup; restart to reload.

The following approved complete settings set is implemented in
[`bridge/config.json`](../../../bridge/config.json) and built-in defaults:

```json
{
  "CONFIG_VERSION": 1,
  "HAIKU_MODEL": "claude-haiku-5-5",
  "SONNET_MODEL": "claude-sonnet-5-5",
  "OPUS_MODEL": "claude-opus-5-5",
  "FABLE_MODEL": "claude-fable-5-1",
  "ADVISOR_MODEL": "FABLE_MODEL",
  "CONVERSATION_BACKEND": "claude_code",
  "CONVERSATION_TIER": "haiku",
  "DOMAIN_TIER": "sonnet",
  "CONVERSATION_TIMEOUT_SECONDS": 60,
  "CONVERSATION_MAX_OUTPUT_TOKENS": 4096,
  "CONTEXT_MAX_MESSAGES": 40,
  "DOMAIN_MAX_TURNS": 20,
  "DOMAIN_MAX_BUDGET_USD": 1.0,
  "TRANSCRIPTS_ENABLED": true,
  "LOG_DIR": "../.local/bridge-logs",
  "LOG_LEVEL": "INFO",
  "TRANSCRIPT_MAX_RECORD_BYTES": 262144,
  "TRANSCRIPT_MAX_FILE_BYTES": 5242880,
  "LOG_MAX_TOTAL_BYTES": 104857600,
  "LOG_MAX_AGE_DAYS": 14
}
```

**Model default replacement, 2026-10-18:** the owner confirmed the official
provider IDs `claude-haiku-5-5` and `claude-sonnet-5-5` and requested both
committed JSON and built-in defaults use them. This replaces the earlier
`claude-haiku-4-5` / `claude-sonnet-4-6` assignments within the existing
configuration schema and policy.

**Additional model slots, 2026-10-18:** the owner requested `OPUS_MODEL`,
`FABLE_MODEL`, and the symbolic `ADVISOR_MODEL` reference shown above. The
four explicit provider IDs were confirmed available by read-only API model
catalog retrieval, alongside the owner's provider-document confirmation of
the Haiku/Sonnet replacements. Conversation and domain defaults remain
`haiku` and `sonnet`; all four tiers may be selected explicitly.

`ADVISOR_MODEL` accepts only `HAIKU_MODEL`, `SONNET_MODEL`, `OPUS_MODEL`, or
`FABLE_MODEL`, never a provider ID, self reference, or arbitrary key.
`BridgeConfig.advisor_for(caller_tier)` resolves this reference for future
callers only when its tier is strictly higher in the capability order
`haiku < sonnet < opus < fable` and its resolved provider ID differs from
the caller's. Numeric model versions do not determine this ordering. Fable
has no higher advisor here. These relationship checks occur on resolution;
a Fable engine configuration remains valid when no advisor is requested.
This amendment adds configuration/resolution only, with no advisory calls,
automatic promotion, fallback, provider framework, or routing-default change.

Model assignments use explicit provider IDs. These values are current defaults,
not a claim about the latest available release; confirm any replacement ID with
the provider before changing it. Both engines resolve their selected tier through
the same config. Agent Markdown `model:` frontmatter remains prompt data and does
not silently override execution settings. Per-agent model overrides can be added
in a later schema if a concrete workflow needs them.

Validate positive numeric limits, finite budgets/timeouts, boolean transcript
enablement, INFO/DEBUG/WARNING/ERROR log levels, and the supported haiku/sonnet/opus/fable
tiers. CONTEXT_MAX_MESSAGES is an even integer of at least 2 to preserve complete
exchanges; it is independent of transcript retention. Require
4096 ≤ record bytes ≤ file bytes ≤ total bytes. Age is a positive integer in days.
Do not accept credentials in this config or write them into the effective-settings
manifest; continue using existing environment credential bindings. No guessed
model IDs, automatic upgrades, or model fallback after an API error.

## 6. M10: recording, diagnostics and retention

Each bridge process start creates a unique UTC timestamp plus random run ID:

```text
LOG_DIR/
  runs/
    <timestamp>-<run_id>/
      manifest.json
      events-0001.jsonl
      agents/
        systems-architect/
          transcript-0001.jsonl
```

Acquire an exclusive OS-backed writer lock for LOG_DIR before creating a run,
and hold it for the recorder's lifetime. A second process using the same root
must suspend disk recording with a visible diagnostic; it may continue serving
conversations. Separate LOG_DIR values allow independent recorders. Release the
lock on process exit, including abnormal exit. Do not replace this with a stale
PID file that cannot establish whether a writer is alive. Keep generated logs
ignored by Git and leave pre-existing user files untouched.

The manifest contains schema version, run ID, start/end timestamps, local project
label, non-secret effective settings and lifecycle status. Write it atomically.
A crash may leave status open; do not misreport that as a clean shutdown. Recording
for a new process always gets a new run directory, even after a crash.

Transcript records contain schema version, sequence number, UTC timestamp,
run/connection/request/agent IDs, engine, model, message role and content, and
outcome. Add domain, output and provider-session IDs only when actually available.
Record user input, successful replies and failures as distinguishable records.
Record NPC provider-session IDs only when actually supplied by SDK/runtime;
fresh per-request IDs do not imply resume or durable recovery. Never invent one
for a Messages API conversation. Serialize
appends, flush each completed record and preserve per-conversation order. A reader
must tolerate an incomplete final line after a crash without treating it as a
complete message; malformed earlier lines produce a diagnostic rather than silent
rewriting. Validate agent IDs before using them as directory names.

Debug events record bridge start/stop, connect/disconnect, request received,
engine routing, completion/failure, duration and applicable domain transitions.
Use request IDs to correlate events with transcripts. Message bodies belong in
transcripts, not duplicated DEBUG entries; do not log auth headers or credentials.
Python standard logging supplies levels and stderr output. A small JSONL formatter
and bounded writer are enough; do not build a new logging framework.

Rotate transcript and event segments before their configured file bound is
exceeded. Count actual encoded bytes, including JSON framing and newlines. A
record larger than its bound is shortened at a valid text boundary with an
explicit truncation marker and original byte count; never truncate the live model
response merely to fit its disk copy. Event segments use the same record/file
bounds. The total quota covers bridge-owned manifests, events and transcripts.

Prune by age and then, if necessary, oldest-first until the total quota admits the
next write. Run pruning at startup and segment rotation. Under the exclusive
writer lock, quota admission, pruning and writing form one serialized operation
for every append and manifest creation/replacement, accounting for temporary
files used in atomic replacement. Delete only recognized, owned, closed files under LOG_DIR, never
follow symlinks, and never touch SDK storage, worktrees, user-selected files or
future authoritative state. Remove empty managed run folders afterward. Closed
segments from the current run may be pruned; open writable files are protected.
At rotation, seal the old segment before pruning so a long-lived run cannot grow
without bound. The exclusive writer lock prevents overlapping recorders from
admitting the same space or pruning each other's live files.

If protected files consume the quota or storage is unavailable, suspend disk
recording and emit a visible stderr diagnostic; conversation execution may
continue. Do not exceed the quota or silently claim a transcript was captured.
Resume recording after a later space check succeeds. Test disk-full, read-only
directory, malformed-record and competing-writer cases with local fixtures.

Godot native output already supports `--log-file <path>` and `--verbose`. A launcher
may configure those separately; this design adds no Godot-specific fields or
rendering awareness to the bridge. Native engine logs remain separately managed
by engine settings and are outside the bridge recorder's quota. The shared
GameEvents signal bus is a client event source, not an existing event archive.

## 7. M11: conversation history and controls

### History and request correlation

Maintain a client conversation store per agent within the current connection.
Store sent messages and pending/completed/failed status independently of whichever
NPC panel is visible. Cache a response before deciding whether to display it.
Returning to an NPC restores its transcript and scroll position; it does not
replace the transcript with the role description. Show the description separately
or as an initial introduction only when that conversation has no messages.

The client generates a unique request_id; the bridge echoes it on conversation
success and error responses. Replace the singleton pending-agent slot with a
request-ID map. Preserve legacy agent_id/task clients and existing response fields.
Unknown/duplicate response IDs must not append a second reply or clear another
request. Enforce one outstanding conversation query per agent initially; other
agents may queue requests even though the current server processes a connection
serially. A late A reply must be retained while B is visible; an ensuing B failure
must be attributed to B. Do not promise parallel model calls in this milestone.

Keep display history bounded independently of model context: initially 200 messages
or 1 MiB of UTF-8 message content per known agent, whichever is reached first.
These limits span all connection generations, including disconnected display
archives, failed messages and draft/pending message content. Remove oldest
completed exchanges or failed messages first; prevent a new input from exceeding
the remaining bound when only protected pending content remains. The pending map
is separate and bounded to one request per known agent. Store these client limits
in frontend project settings, not in bridge config. Mark omitted older display
history so trimming is visible. Shorten an individual oversized display message
at a valid text boundary with an explicit marker; this changes neither the live
model context nor the independently configured disk transcript.

On disconnect, fail pending requests visibly and retain the old displayed thread
as read-only history until the game exits. A new connection starts a new visible
conversation boundary with a clear notice that the model context restarted; old
display text is not silently resent as context. M11 adds neither cross-restart
display persistence nor a history-download endpoint.

### Mouse resizing and scrolling

The target is the in-game chat panel. Drag its edges/corners to resize it in both
dimensions. Keep its bounds inside the viewport with the input, header and resize
handles reachable. Use a 480×260 logical-pixel minimum when it fits; on smaller
viewports clamp to available space. Desktop-window resizing must reflow and clamp
the panel without losing transcript content, input text or pending state. Retain
the user's panel dimensions for this game session; saving preferences across game
restarts is deferred.

Mouse wheel and scrollbar drag scroll the transcript. Auto-follow new text only
while already at the bottom; manual scrolling upward disables follow. Returning
to the bottom re-enables it. Resizing preserves the reading position as closely
as possible. Restored messages appear immediately; only newly arriving replies
use the existing typewriter reveal (`D-007`). Old messages must not be reanimated.

### Keyboard bindings and focus

Declare named actions through Godot InputMap/project settings. A rebinding menu
and multiline composer are outside this milestone.

| Key | Behavior when the chat panel is active |
|---|---|
| PgUp / PgDn | Scroll approximately one visible transcript page, including while the composer is focused. |
| Ctrl+Home / Ctrl+End | Jump to oldest/newest visible transcript message when the transcript has focus; End re-enables follow. |
| Enter | Submit a nonempty composer when it has focus and no request for that agent is pending. |
| Escape | Release composer/transcript focus back to world interaction without submitting, deleting draft input or cancelling an in-flight request. |
| Tab / Shift+Tab | Move focus through enabled chat controls in a predictable order. |

Unmodified Home/End and standard selection/copy/edit shortcuts retain their normal
composer behavior. World movement must not react to typing or handled chat
navigation keys. These controls apply to NPC conversations; they do not introduce
M5's assistant overlay or assign new meanings to locked storyboard events.

### M11 acceptance

**Implementation status (2026-10-18):** store, transport and real-panel headless
acceptance cover the requirements below; the full Godot-client/Python-bridge
integration uses controlled fake provider replies, independent B failure and a
real disconnect/reconnect. It verifies assistant-only rendered output, fresh
server context without replay, and aggregate Unicode display bounds. Existing
smoke remains required. All six actual desktop outcomes below remain outstanding;
record results using the [operating checklist](../../../QUICKSTART.md#desktop-acceptance-checklist--outstanding).
The earlier direct Messages API smoke on 2026-10-18 passed two-client recall;
it is historical compatibility evidence, not SDK execution proof. A separate real
Agent SDK/Claude Code run passed at 22:32:53 UTC with cloud API-key authentication,
Haiku 5.5, two turns each from Godot and Python on the first attempt and four
distinct observed SDK session IDs. [Fresh evidence](../../../specs/evidence/npc-sdk-live-2026-10-18.json)
retains the transcript and limits; frozen Sprint 6 evidence is unchanged.
Owner readback remains outstanding. This does not establish laptop subscription
use, desktop acceptance, graceful runner shutdown or M12 domain execution.

Use deterministic headless checks for stored data, input dispatch, geometry and
request correlation, plus desktop mouse/keyboard verification for actual resizing
and scrolling. Preserve the existing smoke and real two-client conversation gates.
New checks must demonstrate:

1. A→B→A restores the correct ordered transcript without sharing agent context.
2. A reply arriving while B is visible is retained; B's later failure remains B's.
3. Resizing by mouse and shrinking/growing the desktop window keep controls usable
   and preserve input/history/pending state.
4. Wheel, scrollbar, PgUp/PgDn, transcript Ctrl+Home/End, Enter, Escape and Tab work
   with the stated focus rules, without moving the player while typing.
5. New text does not pull the reader downward while reading older messages;
   restored history is immediate and new replies still reveal progressively.
6. Reconnect clearly separates the archived display thread from fresh model
   context; repeated reconnects stay within the aggregate per-agent display bounds,
   and duplicate replies cannot corrupt another agent's thread.

## 8. Protocol and documentation handoff

[PROTOCOL.md](../../../bridge/PROTOCOL.md) remains the record of current wire
behavior. Optional opaque conversation request-ID echo is implemented and tested.
Keep lifecycle/resume semantics separate from UI controls; the bridge never needs
to know that an actor walked to a character or resized a panel.

[The roadmap](../../../specs/roadmap.md) sequences this design. Preserve completed
prototype history and original milestone IDs, but remove the claim that all
post-M8 work is polish. README and CLAUDE.md should point readers to the platform
goal and new track rather than identifying game expansion as the sole next step.
The August [domain brainstorm](2026-08-12-bridge-domain-architecture-design.md)
remains historical design input: its stateless-conversation description predates
connection-scoped history, and its persistent-domain wording does not prove
restart durability.

The owner resolved the `D-006` scope mismatch on 2026-10-18: synchronous calls
with timeout apply to NPC conversations in `DESIGN-25D` `D-033`, which
supersedes the preserved historical `D-006`; asynchronous buffered
domain execution and existing turn/budget caps are separately authorized by
`PLATFORM-DECISIONS` `D-034`. The former mismatch and ruling remain recorded in
[conflict register §4.13](../../../specs/meta/spec-drivers-v0.2.5.md), tracked by
[issue #341](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/341).
M10 settings and archive/diagnostic policies in §§4–6 are ratified as `D-035` and
`D-036` at that same entitled platform tier. This approval completes M9, not M10
or M11. The milestone scope preserves the scripted-guide distinction in `D-010`,
the frontend-independent bridge in `D-005`/`D-020`, and frontend-only typewriter
rendering in `D-007`. This documentation change does not advance a Jira board,
publish configuration, select a cloud provider, or implement any planned feature.

*Last updated: October 2026*
