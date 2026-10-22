# Bridge Protocol

WebSocket on `ws://localhost:8765` (D-015). JSON messages, one per WebSocket frame.

## Current prototype scope

The current native listener accepts a missing `Origin` header (Godot and plain
Python clients) and rejects every supplied Origin during the handshake, including
localhost URLs and literal `Origin: null`, before protocol admission. This is an
Origin boundary, not local-client authentication or host isolation: another local
process can omit or forge headers. D-005/D-020 frontend independence remains;
a future browser frontend needs an explicit trusted-Origin and authentication
contract before connecting directly.

The request/response examples below describe the current implementation, not a
durable platform API. NPC conversation history is connection-local; domain SDK
clients, lifecycle state, and output buffers are bridge-process-local. Neither
engine currently provides bridge-managed recovery after a bridge restart.

Normal model execution, including NPC calls, defaults to Claude Code through the
Claude Agent SDK (`D-037`). `CONVERSATION_BACKEND=claude_code` preserves native CLI
authentication without requiring an API-key environment variable. Explicit
`messages_api` conversation mode requires `ANTHROPIC_API_KEY` and rejects known
OAuth/setup-token credentials. Backend selection never follows credential
presence or falls back automatically after failure. See the
[authentication guide](../QUICKSTART.md#2-install-prerequisites).

The Godot client implements NPC conversations plus configured-project discovery,
Chief referral/review, domain lifecycle controls and bounded output replay. The bridge remains unaware of rendering and controls
(D-005);
see the [platform design's client requirements](../docs/superpowers/specs/2026-10-18-bridge-first-platform-design.md).

Future work is separated under [Planned platform evolution](#planned-platform-evolution).
That section adds no implemented fields, commands, or persistence guarantees.

## Request Types

### Conversation (explicit extras only)

```json
{
  "type": "conversation",
  "agent_id": "registered-story-extra",
  "task": "What's your take on the new hire?",
  "request_id": "optional-uuid"
}
```

A request **without** a `type` field is treated as `"conversation"` — existing
extras clients retain the legacy wire shape. The example extra must be explicitly
registered in the bridge extras store; the shipped extras store is currently empty.
All catalog members are working agents. Their legacy requests return correlated
`domain_required`, `binding`, `execution_kind`, `domain_id`, and `required_action`
(`project_setup` before project readiness, `activate_domain` once ready), before
any provider, history or memory/checkpoint admission. Missing bindings return
`invalid_binding`. Unknown typed operations return `invalid_request`.

`request_id` is optional opaque correlation metadata. If supplied as a nonempty,
non-whitespace string, it is echoed exactly on every conversation success and
error response, including validation and provider errors. It need not be a UUID;
surrounding whitespace is preserved. Omitted, empty, whitespace-only and non-string
IDs leave the legacy response shape unchanged, without a generated wire ID.
Malformed JSON and non-object messages have no trusted ID to echo. This metadata
does not change conversation history or domain/lifecycle routing.

#### Conversation history

The bridge remembers a conversation for as long as the WebSocket connection it
arrived on stays open. Within a connection it keeps one history per `agent_id`:
each successful exchange is appended, and the next request for that agent is
sent to the model with those earlier turns in front of it. The default adapter
creates a fresh SDK client per request and submits one JSON-serialized transcript
with the agent definition as system prompt, then disconnects. There is no retained
NPC SDK client, resume/continue operation or provider-side history dependency.
Observed SDK session IDs are request-local recorder metadata only; the wire shape
is unchanged and an ID does not establish durable recovery.

- **The client sends no history/context payload.** Optional opaque `request_id`
  metadata correlates responses; it is not a durable conversation identity.
  A client holds model context by keeping its connection open and loses that
  context by reconnecting. Any client gets this the same way (`D-005`).
- **A new connection starts with nothing**, and two connections never see each
  other's turns, even for the same agent.
- **Only successful exchanges are kept.** A request that fails, is cancelled,
  truncates or returns no text leaves history unchanged. Success requires terminal
  completion and cleanup; only assistant text is returned. NPC tools/MCP/skills
  and discretionary project/user hooks/plugins are disabled, while mandatory
  managed policy remains effective.
- **It is bounded.** `CONTEXT_MAX_MESSAGES` defaults to the newest 40 messages
  (20 exchanges) per agent; older ones are dropped whole, oldest first.
- **Live context is not restored.** Optional M10 disk transcripts archive
  exchanges for inspection; they never repopulate this history. Disconnect or
  restart forgets live context. There is no stable conversation identity for
  reconnect/restart recovery. Durable session state is planned for M13.

### Character status and explicit setup

These commands require exactly the documented fields. IDs are nonempty UTF-8
strings of at most 128 bytes; agent IDs use the existing slug grammar. Extra
fields, missing fields and unknown operations fail explicitly. Errors retain
valid supplied correlation IDs.

```json
{"type":"agent_status","agent_id":"systems-architect","request_id":"status-1"}
{"type":"project_setup","agent_id":"systems-architect","request_id":"setup-1","intent":"Prepare this project"}
```

`agent_status` returns `type`, `agent_id`, `request_id`, `execution_kind`
(`working` or `extra`), nullable `domain_id`, `capabilities`, `project`, nullable
`workspace`, and nullable `domain_state`. Working characters receive their own
department's workspace and existing generation; extras have null workspace/state.
Status never creates a worktree, reserves capacity, invokes a provider, runs a
query, or changes foreground ownership. It refreshes bounded observations of
already-existing workspaces. Architect and Auditor report the same Core owner.

Capabilities contain `can_start`, `can_run`, `can_prepare_project`, `tools`,
`execution_capacity` and nullable `reason`. `can_start` means local project,
workspace and capacity state permits an explicit Start attempt; `can_run` means
an existing active/background owner is idle, healthy and locally ready. These
are observations, not guarantees: Start/Run revalidate readiness and the SDK's
source/runtime-bound live tool-guard acceptance. Status does not run acceptance
probes. `tools` is `["Read","Edit","Bash"]` only when Run is locally available,
otherwise `[]`. Locally failed/disconnected/stopped owners report `sdk_error`;
Stop and explicitly Start a fresh generation to recover. Observing failure leaves
the existing generation, lease and capacity intact until Stop. Capacity is `{limit:1, available, domain_id, domain_session_id}`;
the IDs identify the process-local capacity owner, or null when free. No queue
or concurrent domain execution is implied. Extras can converse while a domain runs.

Setup `intent` is nonempty UTF-8 text, at most 65536 bytes. `project_setup`
returns `type`, `agent_id`, `request_id`, `status`, `output`, `project`, and
nullable `architect_decision`; failures also contain `error_type`. Non-Chief
characters refer to the Chief without invoking a model. Setup activity never
enters extras history or counts as a domain Run. The explicit intent accompanies
the inspected proposal as data and cannot enlarge its approved seed allowlist.
Setup/status validation failures use the same type and valid IDs with
`status:error`, `error_type`, `output`, `project`, and `architect_decision`.
A busy connection service slot returns the correlated `service_busy` error;
status discovery and setup have separate slots from extras and domain controls.

### Configured project discovery and setup (M12)

One project is frozen from `WORKSPACE_ROOT_DIR` / `PLAZA_WORKSPACE_ROOT_DIR` at
startup. Relative paths use the selected configuration directory. Clients cannot
supply paths or switch projects; restart the bridge to change the binding.

```json
{"type":"describe_workspace","request_id":"discover-1"}
```

```json
{
  "type":"workspace_state", "request_id":"discover-1",
  "project_id":"repository-key", "stage":"ready", "reason":null,
  "architect_decision":null, "workspace_id":null,
  "project_path":"/projects/example",
  "worktree_path":null, "branch":null, "changed_files":null,
  "reservation":null,
  "memory":{"path":"/projects/example/.git/plaza/session-memory",
            "status":"saved","revision":4,"error_type":null}
}
```

Stages are exactly `unconfigured`, `needs_architect`, `preparing`, `reviewing`,
`initializing`, `ready`, `failed`. Unavailable identity/worktree/status fields are
null. The listener is available during bootstrap. Character status observes bounded
filter-disabled Git status (counts, never contents); `truncated:true` means counts
are only the observed prefix. It cannot initialize Git or invoke a model.
An existing healthy external reservation permits observation and NPC memory, but
local Start returns `workspace_busy`. Reservation is null or
`{domain_id,domain_session_id,cleanup_failed}`. External held-marker observations
are advisory: `cleanup_failed:false` does not prove the foreign owner's teardown
is healthy. A free lock with an unclean marker requires operator inspection.

Existing Git projects bootstrap automatically. Empty/non-Git/unborn projects
wait for an explicit `project_setup` with `systems-architect` (Chief
Architect). Other characters return a setup referral without a model call. The Chief
uses fresh context, configured backend/model/caps and disabled tools to review an
exact proposal. The bridge accepts only the exact structured approval, then
initializes `main` with the reviewed seed allowlist. Its approval suffices; there
is no extra human confirmation. Concurrent submissions report the current review.
The Chief caller keeps its absolute setup response deadline. If an in-budget
approval has started initialization that is still running at the deadline, the
reply includes the exact approval and initialization-in-progress status. The
service retains that single operation; domains remain blocked until memory is
checkpointed and setup is ready. A timed-out review never authorizes Git.
Declined/failed reviews need a new explicit Chief submission. Initialization and
setup-memory failures preserve files; a successfully initialized repository is
never initialized again to retry a failed memory save.

Configured extras turns checkpoint intent and supply labeled prior project notes
outside conversation history and instruction authority. The same response may
provide optional memory updates. Only the visible answer enters successful NPC
history; invalid optional updates do not erase it. Unconfigured extras retain tools-disabled conversation. `memory.status` is `unavailable`, `saved`, or `unsaved`; a failed save
retains the last confirmed revision. A successful task/history remains successful
when its memory checkpoint fails. Memory is bounded short-term context, not
complete history, an automatic task queue or runtime recovery.

### Domain Start, Run, Stop and observation

Each Run validates that the selected catalog agent belongs to the requested
domain before memory, history or provider admission; mismatches return
`invalid_binding`.

Every domain command requires an explicit nonempty `request_id` (at most 128
UTF-8 bytes). Domain IDs contain ASCII letters, digits, `_` or `-`, at most 128
bytes. Start obtains the process-local `domain_session_id`; all Run, background,
refocus, Stop and replay requests require that expected generation. Unknown or
stale generations fail with `session_unavailable`. No client identity is an
authentication or ownership principal.

```json
{"type":"activate_domain","domain_id":"engineering","request_id":"start-1"}
{"type":"domain_status","domain_id":"engineering","request_id":"status-1"}
```

Start emits correlated `domain_state` with `state:"activating"` before connecting,
then `state:"active"` or `domain_error`. Both packets carry `project_id`,
`workspace_id`, `domain_id`, `domain_session_id`, and `execution_state`.
`domain_status` includes `available_generations`; an unknown domain is inactive
with null generation. Start before readiness rejects `workspace_not_ready` (or
`workspace_unconfigured`). One session reserves the worktree, including idle,
background and completed work. **Stop releases the workspace after confirmed
cleanup.** Disconnect never releases a domain or cancels admitted work.

```json
{"type":"domain_query","domain_id":"engineering","domain_session_id":"generation-uuid","agent_id":"backend-architect","task":"Review the auth middleware","request_id":"run-1"}
{"type":"background_domain","domain_id":"engineering","domain_session_id":"generation-uuid","request_id":"background-1"}
{"type":"refocus_domain","domain_id":"engineering","domain_session_id":"generation-uuid","request_id":"focus-1"}
{"type":"deactivate_domain","domain_id":"engineering","domain_session_id":"generation-uuid","request_id":"stop-1"}
```

A Run is acknowledged by `domain_accepted` only after successful preflight and
intent checkpoint. It later produces one retained `domain_result`, even on error
or cancellation. Task text is bounded to 64 KiB UTF-8. A conflicting duplicate ID
or overlapping query rejects; an exact pending duplicate returns its acceptance,
and a retained completed duplicate returns its result without execution. There
is no hidden query queue. Lifecycle states are `inactive`, `activating`, `active`,
`background`, `stopping`, `cleanup_failed`; execution state is independent.

```json
{
  "type":"domain_result", "project_id":"repository-key", "workspace_id":"workspace-uuid",
  "domain_id":"engineering", "domain_session_id":"generation-uuid",
  "request_id":"run-1", "output_id":"1", "agent_id":"backend-architect",
  "task":"Review the auth middleware", "output":"Review complete.",
  "status":"success", "reason":"completed",
  "memory":{"saved":true,"revision":6,"error_type":null},
  "truncated":false
}
```

Domain terminal status is `success`, `error`, or `cancelled`, independent of memory
save status and delivery. NPC replies retain `{agent_id,task,output,status}` with
`status:"ok"` on success, plus a usable optional request ID. NPC errors add
`error_type` and `message`. Domain rejection packets use `type:"domain_error"`,
`status:"error"`, safe `error_type`/`message`, and valid supplied correlation.
No internal diagnostic UUID is fabricated into a malformed domain command.

### Replay and connection admission

```json
{"type":"resume","domain_id":"engineering","domain_session_id":"generation-uuid","cursor":"0","request_id":"replay-1"}
```

Replay returns results above the ASCII decimal-string cursor (at most 128 UTF-8 bytes) through a captured
high-water mark, ending in `resume_complete` even when empty. Results retain their
original Run request IDs; completion carries the replay request ID. Replay does
not refocus. IDs begin at `"1"` per generation. History gaps and the earliest
retained ID are explicit. Each generation retains at most 256 terminals / 4 MiB
output, each output at most 256 KiB UTF-8. At most ten domain identities and two
generations per domain are retained; live/unclean ownership is never evicted.
Nothing here restores SDK state or terminal buffers after bridge restart.

Each connection admits one NPC operation, one ordinary domain control, one Stop
and one discovery (`describe_workspace` / `domain_status`) independently. An
occupied slot returns correlated `conversation_busy` or `domain_busy`. Ordinary
Run admission releases its slot at acceptance/rejection, before terminal output;
Start holds it until active/error. Stop and discovery remain responsive while NPC
or activation work is pending. Sends are serialized, with a two-second deadline
and at most 32 queued packets. Slow/closed sinks detach delivery; domain ownership
continues. A terminal's originating connection is immutable; reconnecting clients
must replay and never steal another connection's live output.
Connection-level domain busy replies carry the current trusted project/workspace
identity and valid supplied request/domain/generation correlation. Clients settle
only that command and preserve its draft. Reconnecting to an authoritative
`unconfigured` workspace (`project_id: null`) clears the prior project binding,
NPC/domain display caches and HUD state; temporarily absent identity during setup
does not change an established binding.


| error_type | Meaning |
|---|---|
| `timeout` | NPC operation deadline expired; owned cleanup/IO may extend elapsed time |
| `auth`, `api_error` | Configured provider authentication/execution failed |
| `not_found`, `invalid_request` | Unknown agent or malformed request |
| `conversation_busy`, `domain_busy` | Connection slot or domain operation occupied |
| `workspace_unconfigured`, `workspace_not_ready`, `workspace_invalid` | Project binding/readiness failure |
| `workspace_busy` | Another domain holds the reservation |
| `memory_unavailable` | Required memory preflight or checkpoint failed |
| `session_unavailable`, `sdk_error` | Unknown/stale generation or unusable SDK owner |
| `cleanup_failed` | Cleanup is unconfirmed; ownership/evidence retained |

Shutdown drains domains, then owned NPC/setup/IO, then detaches the memory run,
and closes recording. Pending unsaved intent prevents clean run detach. No path
resets, cleans, merges, deletes operator edits, or claims host/network sandboxing.

## Current configuration and local observability (M10)

Both engines use a validated startup settings snapshot: built-ins, then default
`bridge/config.json` (or `BRIDGE_CONFIG_PATH`), then `PLAZA_<KEY>` overrides.
Restart to reload. Relative `LOG_DIR` is selected-config-relative. The complete
defaults, environment syntax, model-tier/advisor resolution and recovery
instructions are in [Quick start](../QUICKSTART.md#bridge-settings-and-archives-m10).
Conversation/domain tiers default to Haiku/Sonnet; all four explicit model tiers
are available. The symbolic advisor helper is reserved for future callers and
adds no advisory execution. The NPC operation deadline defaults to 60 seconds;
SDK disconnect/reaping can add approximately 20 seconds of bounded cleanup
escalation. The 4096 output-token default is passed through the supported CLI
`CLAUDE_CODE_MAX_OUTPUT_TOKENS` environment cap. It is not a disk/display bound.

Linux run manifests, per-agent JSONL transcripts and metadata-only standard logs
are current behavior. Correlation IDs are recorded internally; a usable supplied
conversation ID is also echoed on the wire. Bound credentials are redacted in
archive content, metadata and agent path selectors. `TRANSCRIPTS_ENABLED=false`
disables bodies, while events remain controlled by `LOG_LEVEL`. Record/file/total encoded-byte
bounds and age/oldest-first retention protect open files and unrelated data.
Oversized disk copies are marked truncated; wire replies and model history are
unchanged. Lock contention, unavailable storage and quota exhaustion suspend
recording and retry on later writes while service continues. Unsupported native
platforms also suspend recording; native Windows archives are not supported.

Each process creates a unique run under `LOG_DIR/runs/`; its atomic manifest
contains effective non-secret settings and clean/open lifecycle status. A crash
leaves its manifest open. Ambiguous initial manifest temps require operator
inspection before recording can resume, as documented in Quick start. Native
Godot logs are separately configured and outside this quota. Archives are not
context replay, durable user/project state, or SDK recovery.

## Current client behavior (M11/M12)

The Godot client correlates pending requests per agent and retains bounded,
session-only display history across panel dismissal and reconnect. Disconnect
fails pending requests once and archives that generation read-only; reconnect
starts fresh server model context. No display transcript or archived draft is
replayed. Frontend display limits are independent of model and disk limits.
History, resizing and keyboard controls are implemented with deterministic
coverage; owner desktop acceptance was recorded for M11; M12 desktop acceptance
remains outstanding. See the
[operating guide](../QUICKSTART.md#npc-conversation-history-and-controls-m11).
The bridge has no UI awareness, and legacy conversation clients may omit request IDs.
M12 Godot controls and physical background/refocus have deterministic and
recorded Linux live coverage. Laptop binary and M12 desktop acceptance remain
open. Worktree notes survive clean restart, while
result replay is process-local. See [M12 operations and platform limits](../QUICKSTART.md#project-work-and-domain-controls-m12)
and [bounded live evidence](../QUICKSTART.md#m12-live-evidence-and-desktop-checks).

## Planned platform evolution

The following milestones are **planned, not implemented by this document**.
Sequencing and acceptance criteria live in the [roadmap](../specs/roadmap.md);
the [bridge-first platform design](../docs/superpowers/specs/2026-10-18-bridge-first-platform-design.md)
describes the intended boundaries and open contract decisions.

| Milestone | Intended change |
|---|---|
| M13 | Durable identities scoped by user, project, and domain, with defined restart/reconnect recovery. Exact fields and recovery semantics require implementation and verification. |
| M14 | Broader isolation and workspace/runtime providers beyond the M12 cooperative local Git worktree. |
| M15 | Authenticated hosted operation with durable storage and enforced ownership/access boundaries. |

Future user/project labels are intended identity inputs, not trusted principals
or authentication in today's local protocol. Transcripts, logs, labels, and an
SDK session ID do not independently establish durable ownership or recovery.
