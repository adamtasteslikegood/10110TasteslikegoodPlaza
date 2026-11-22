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

The request/response examples below describe this implementation branch. NPC
conversation history and SDK processes remain process-local. M13 adds bounded
project-scoped application-session persistence and domain protocol v2; restoration
never resumes an SDK process or starts work. Final M13 evidence/acceptance remains
pending. See the [M13 operating guide](../docs/m13-session-persistence.md).

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
  reconnect/restart recovery for extras. M13 domain sessions have the separate
  bounded application history/recap contract below.

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
department's workspace and current application/execution state; extras have null workspace/state.
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
Stop and explicitly Start a fresh execution to recover. Observing failure leaves
the existing execution, lease and capacity intact until Stop. Capacity is `{limit:1, available, domain_id, domain_session_id}`;
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

### Domain Start, Run, Stop, End and observation (v2)

Each Run validates that the selected catalog agent belongs to the requested
domain before memory, history or provider admission; mismatches return
`invalid_binding`.

Every domain command (including `describe_workspace`) requires integer
`protocol_version:2` and an explicit nonempty `request_id` (at most 128 UTF-8
bytes). A missing/invalid version returns `upgrade_required` before execution.
Domain IDs contain ASCII letters, digits, `_` or `-`, at most 128 bytes. Commands
accept exactly the documented fields. Start and End require
`expected_domain_revision`, a decimal string in 0..9223372036854775807; stale
revisions return `stale_domain_revision`. Observe status before a deliberate
retry. No client identity is an authentication or ownership principal.

```json
{"type":"describe_workspace","protocol_version":2,"request_id":"workspace-1"}
{"type":"domain_status","protocol_version":2,"domain_id":"core","request_id":"status-1"}
{"type":"activate_domain","protocol_version":2,"domain_id":"core","expected_domain_revision":"0","request_id":"start-1"}
```

Start lazily prepares/reuses the selected department worktree and may connect an
SDK owner, but makes zero model queries. Send is an explicit `domain_query`.
Start emits correlated `domain_state` with `state:"activating"` before connecting,
then `state:"active"` or `domain_error`. Both packets carry `project_id`,
`workspace_id`, `domain_id`, stable application `domain_session_id`, fresh
`execution_id`, `domain_revision` and `execution_state`. A fresh explicit Start
reuses the open application session; after End it creates a new application UUID.
`domain_status` includes `saved_sessions` (application ID, creation/End attribution
and decimal-string highwater), including ended-only history. An unknown domain
is inactive with null application/execution and revision `"0"`. Start before readiness rejects `workspace_not_ready` (or
`workspace_unconfigured`). One session reserves the worktree, including idle,
background and completed work. **Stop releases the workspace after confirmed
cleanup, preserving application identity and history.** Disconnect never releases
a domain, cancels admitted work or Ends the application session. Explicit End
requires confirmed orderly cleanup and settled requests, records actor/time and
retains history; failed End preserves the session/draft. Game/bridge exit and
crash do not End. The application UUID is not a provider-session resume token.

```json
{"type":"domain_query","protocol_version":2,"domain_id":"core","domain_session_id":"application-uuid","execution_id":"execution-uuid","agent_id":"systems-architect","task":"Review the auth middleware","request_id":"run-1"}
{"type":"background_domain","protocol_version":2,"domain_id":"core","domain_session_id":"application-uuid","execution_id":"execution-uuid","request_id":"background-1"}
{"type":"refocus_domain","protocol_version":2,"domain_id":"core","domain_session_id":"application-uuid","execution_id":"execution-uuid","request_id":"focus-1"}
{"type":"deactivate_domain","protocol_version":2,"domain_id":"core","domain_session_id":"application-uuid","execution_id":"execution-uuid","request_id":"stop-1"}
{"type":"end_domain_session","protocol_version":2,"domain_id":"core","domain_session_id":"application-uuid","expected_domain_revision":"2","request_id":"end-1"}
```

Run, background, refocus and Stop require the current `execution_id`; delayed
controls fail `stale_execution`, even if the application ID still matches. End
and replay bind the application ID without granting old execution authority.
Use the actual observed revision/token rather than copying these placeholders.

A Run is acknowledged by `domain_accepted` only after successful preflight,
pending-note checkpoint and committed accepted request. Dispatch is committed
before invoking the SDK. It later produces one retained `domain_result`, even on error
or cancellation. Task text is bounded to 64 KiB UTF-8. A conflicting duplicate ID
or overlapping query rejects; an exact pending duplicate returns its acceptance,
and a retained completed duplicate returns its result without execution. There
is one unfinished accepted request per domain and no hidden query queue. Completed
duplicate recognition expires with retained terminals; unfinished requests do not
expire. Lifecycle states are `inactive`, `activating`, `active`,
`background`, `stopping`, `cleanup_failed`; execution state is independent.

```json
{
  "type":"domain_result", "project_id":"repository-key", "workspace_id":"workspace-uuid",
  "domain_id":"core", "domain_session_id":"application-uuid", "execution_id":"execution-uuid",
  "request_id":"run-1", "output_id":"1", "agent_id":"systems-architect",
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

Frozen `domain_accepted`/`domain_result` data may omit `protocol_version`; clients
allow absent version only for those frames after exact project/application/
execution/request correlation and strict flag validation. A supplied version must
be integer 2; missing execution identity fails. Historical data is never lifecycle
authority and packets are not restamped. Commands, lifecycle and negotiation are
strict v2. A failed state save exposes `committed:false`, storage `error_type` and
no `output_id` for the live result; replay never claims that answer as saved history.

### Replay and connection admission

```json
{"type":"resume","protocol_version":2,"domain_id":"core","domain_session_id":"application-uuid","cursor":"0","request_id":"replay-1"}
```

Replay returns results above the ASCII decimal-string cursor (at most 128 UTF-8 bytes) through a captured
high-water mark, ending in `resume_complete` even when empty. Results retain their
original Run request IDs; completion carries the replay request ID. Replay does
not refocus. IDs begin at `"1"` per application session and keep their values across
SQLite restart. History gaps, earliest retained ID and highwater are explicit,
including when the retained window is empty. Each session retains at most 256
terminals / 4 MiB output-text, each output at most 256 KiB UTF-8. Terminal JSON is
at most 2 MiB UTF-8. The project store allows 128 sessions/10 domains in a 64 MiB
serialized image, with a 2 MiB logical completion allowance at admission. End does
not evict history; selected ended sessions can be deleted only by the offline
backup-first maintenance CLI. Atomic replacement can require 128 MiB plus failed
temporary remnants; image size is not a total disk quota.

`state_store` reports `backend`, `durable`, `continuity`, `continuity_id` and
`error_type`. SQLite uses project continuity and its persisted instance UUID
(null before first image); memory uses process continuity and a fresh boot UUID.
Backend changes or two established differing continuity IDs retire old caches
before revision comparisons; initial null→SQLite UUID establishes continuity
without retiring an in-flight first Start/draft. Validate the complete packet
before mutation. Memory never imports/changes SQLite history. Busy, invalid,
unsupported, quota, failed and uncertain storage states fail visibly without
automatic fallback or silent recreation.

Restoration starts no SDK/model/tools: accepted-without-dispatch is `not_executed`,
dispatch-without-terminal is `interrupted`/unknown, and saved terminals replay
unchanged. Exact owned note reconciliation is reported separately through
`memory_reconciliation`. A bounded quoted recap is supplied once on the first
actual Run of each fresh execution; it does not enqueue old work or imply provider
process recovery. Details and operator recovery are in the M13 guide.

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
| `session_unavailable`, `sdk_error` | Unknown application session or unusable SDK owner |
| `upgrade_required`, `stale_execution`, `stale_domain_revision` | Protocol version or lifecycle/execution fencing failed |
| `state_store_busy`, `state_store_invalid`, `state_store_unsupported`, `state_store_quota`, `state_store_failed`, `state_store_uncertain` | Visible storage failure; no automatic fallback or empty recreation |
| `cleanup_failed` | Cleanup is unconfirmed; ownership/evidence retained |
| `work_claimed` | Opt-in relay claims: another runtime's bridge or agent holds this domain's live claim; Start is refused, or a later Run once the claim was lost (the session stays up) |
| `relay_refused` | Opt-in relay claims: the relay refused the claim (credential, grant or request) or gave an answer the bridge can't use; Start is refused, or a later Run needing a re-claim (the session stays up) |

Shutdown drains domains, then owned NPC/setup/IO, then detaches the memory run,
and closes recording. Pending unsaved intent prevents clean run detach. No path
resets, cleans, merges, deletes operator edits, or claims host/network sandboxing.

### Relay work claims (opt-in)

Off unless `RELAY_WORK_REPO` (`owner/name`) is set when the bridge starts. Then
each domain is one work claim, ref `plaza:<domain_id>`, on that repo's board at
the pr-gate relay (`pr-lifecycle-relay`, adamtasteslikegood/codex-pr-review-gate-cc).
The settings are pr-lifecycle's own: `PR_GATE_RELAY_URL`, and either
`PR_GATE_RELAY_CLIENT_ID` with `PR_GATE_RELAY_CLIENT_SECRET` (an Access service
token) or `PR_GATE_RELAY_TOKEN`. Optional: `RELAY_RUNTIME` (default `bridge`),
`RELAY_WORK_HOLDER` (default `bridge@<host>`, printable ASCII, at most 187 characters; the bridge
appends a digest of the project checkout, so two checkouts on one machine are two holders), `RELAY_WORK_BEAT_SECONDS`
(default 30, from 5 to 60, inside the relay's 120 s lease) and `RELAY_WORK_SECRET_FILE` (default
`~/.config/plaza/relay-work-secret`, made once with mode 0600, so a restarted
bridge renews its own claim at once instead of waiting for the lease to lapse).
A half-made setting stops the bridge at startup with a configuration error.

- Start claims the domain after the workspace lease, naming the workspace
  branch. A claim live under another holder refuses Start (`work_claimed`); a
  refused credential or grant does too (`relay_refused`), and so does an answer
  the bridge can't use, since the relay may have recorded a claim nothing would
  keep alive. A relay that does not answer at all (no connection, a 5xx or a
  timeout) never stops local work: the generation runs unclaimed.
- While the generation lives, a background task beats the claim. If the relay
  says it was lost (lapsed or taken over), the bridge stops beating and records
  nothing more to it; the running Run is not interrupted. The usual cause is a
  laptop sleep or a network drop longer than the lease.
- Before each later Run is admitted, a claim that is not held (lost, or never
  obtained because the relay did not answer at Start) is claimed again with the
  same holder, checkout and branch. Claimed: the Run goes ahead, beats resume and
  its checkpoint is recorded (logged `reclaimed`, or `took_over`). Held by another
  runtime: that Run is refused with `work_claimed`, and so is a refused credential
  or an unusable answer (`relay_refused`); the session stays up, so results stay
  readable, Stop works, and a later Run tries again. No answer: the Run goes
  ahead unclaimed, as at Start, and the next Run tries again. A Stop at any point
  in that re-claim, including while the old beats are being stopped, waits for
  the relay's answer (up to 15 s) and releases a claim it recorded; past that,
  the claim lapses after the lease, and a re-claim that begins or answers after
  Stop is never held or beaten.
- With claims on, `domain_state` and `resume_complete` for an activating,
  active or background generation carry `work_claim`: `held`, `lost` (the relay
  said so) or `unclaimed` (no answer yet). The field is absent when claims are
  off and once the generation is stopping or inactive. A client sees a claim
  lost during a Run right after that Run's result, since Godot then refreshes
  each working character's `agent_status`, which embeds `domain_state`; a
  refused Run makes it ask for `domain_status`.
- On a takeover the relay's `resume` (branch, commit, steps) is kept and not
  acted on: the bridge pushes nothing for this, and the local worktree and
  SQLite stay the record of its own work. (The bridge's one push is a cloud
  department's Start, below: its `plaza/workspace-*` branch, never with force,
  never after a Run.) The workspace branch is
  `plaza/workspace-<project_id>-<domain>`, where `project_id` is a digest of the
  checkout's git directory path, so two machines share a branch name only when
  their checkouts sit at the same path.
- After each Run's terminal is delivered, the claim gets a checkpoint step:
  `<status> (<reason>): <task>`, with the workspace branch and its `HEAD`.
  Another runtime can resume from that commit only once the branch is pushed;
  the bridge does not push it. For a cloud department the runner has pushed
  it already; the bridge's own push comes only at Start.
- At most 20 checkpoints wait to be sent; beyond that a Run's step is dropped
  and logged. Stop waits up to 15 s for them; if one may still be in flight
  then, it doesn't release, and the claim lapses after the lease instead.
- A clean Stop releases the claim as `paused`. Cleanup failure leaves it to lapse.
  End does not mark it done yet.

The relay holds coordination only. SQLite stays the record of the session, its
results and recap; no transcript goes to the relay. Each checkpoint does send
the Run's task text; the step is cut to 300 characters, as the relay stores it, and `PR_GATE_RELAY_URL` must be https. Relay credentials are
redacted from archives like provider credentials.

## Cloud departments (opt-in)

Off unless `CLOUD_DOMAINS` is set. A listed department runs its Claude agent on
the cloud runner (`cloud-runner/`, a Cloudflare Worker) instead of in this
bridge; every other department is exactly as above. Nothing here is deployed
or live-checked yet: the development deploy still runs the runner's earlier
code, so the feature is implemented and unit-tested only.

Settings (`bridge/config.json`, or `PLAZA_<KEY>` in the environment):

- `CLOUD_DOMAINS`: comma-separated lowercase department ids; empty (the
  default) keeps every department local. A bridge restart applies a change,
  which also guarantees no session of the department is running.
- `CLOUD_RUNNER_URL`: the runner's origin (scheme and host, optional port; no
  userinfo, path, query or fragment). https, or http for localhost only.
  Required when `CLOUD_DOMAINS` is set; a set one is checked at startup even
  with `CLOUD_DOMAINS` empty, since every run's log manifest carries it.
- `CLOUD_DOMAIN_LIMIT`: cloud departments active at once, 1 to 10, default 3.
- The caller secret is a file, not a setting: `CLOUD_RUNNER_SECRET_FILE`
  (plain environment variable), default `~/.config/plaza/cloud-runner-secret`.
  The bridge never creates it. It must hold at least 32 ASCII characters; a
  mode looser than 0600 is reset to 0600. No credential is in `BridgeConfig`,
  a log, a transcript or a packet, and the recorder redacts the secret as it
  does the relay credentials.

Wire changes, all absent for a local department:

- `domain_state` and `resume_complete` for an activating, active or background
  cloud generation carry `runs_on: "cloud"`.
- `execution_capacity` carries `pool` (`cloud` or `local`) only when
  `CLOUD_DOMAINS` is non-empty. The pools are separate: local stays one active
  department, cloud departments share `CLOUD_DOMAIN_LIMIT`.
- Start error codes: `cloud_unavailable` (the runner did not answer, or the
  bridge was given no runner), `cloud_refused` (it refused: check the
  address, the secret and the repository's token; a workspace that exists
  with another repository or branch is a 409 that shows as this),
  `cloud_sync_failed` (git sync refused, below; also a cloud note that could
  not be written, and a Start that would have pushed over a clone whose last
  push did not arrive), `cloud_run_active` (an earlier run, for instance from
  before a bridge restart, is still going on the runner; it finishes and pushes
  on its own) and `cloud_switch_refused` (a local Start, below).
- Run terminal reasons: `cloud_push_failed` (the runner could not push; the
  answer is kept and the Run ends as an error), `cloud_sync_failed` (the
  commit it pushed could not be taken here, a cloud note that could not be
  written, or a 412 from the runner at run start), `cloud_run_lost` and
  `cloud_run_active` (also a 409 at run start). A 412 has one exit today,
  `DELETE /workspaces/:name` on the runner by hand, which destroys the
  clone's unpushed commits (see "Known gaps" in `cloud-runner/README.md`).
- The reason behind a code is in the bridge log: the bridge process's stderr,
  one line per event from the `bridge.cloud` logger, `<time> bridge.cloud
  <department>: <step>: <what happened>`. These lines can carry git's and the
  runner's own words (scrubbed of the secret and of URL userinfo, cut to 300
  characters), so they never go to the `LOG_DIR` archive.

Where each command goes:

- Start asks the runner's status first, so nothing is pushed while an earlier
  run goes on. Then, for a `github.com` origin only, it pushes the workspace
  branch `plaza/workspace-<project_id>-<domain>` (never `--force`, only that
  branch), creates the runner's workspace `<project_id>-<domain>` if it is
  missing (it never changes one; another repository or branch is a 409) and
  fast-forwards the worktree to what the runner holds. If the runner's last
  run ended `lost` or with `pushError`, GitHub may lack the clone's commits:
  a Start that would have to push this machine's commits is then refused
  (`cloud_sync_failed`) instead of pushing over them. The bridge never pushes
  after a Run. Of the local readiness checks, the session's turn preparation
  still runs before every Run, and the sync checks a clean worktree and the
  workspace branch.
- Run sends the task; a recap goes with it whenever the runner does not hold
  this session's conversation. The runner's conversation key comes from the
  session id, so End starts a new conversation and keeps the workspace. The
  bridge polls every 3 s. After the run it fast-forwards the worktree to
  exactly the commit the runner reports as pushed; anything that is not a
  fast-forward is an error, never a merge. No status naming the run for
  5 minutes ends it: `transport_error` after an outage, `cloud_run_lost` after
  answers that name another run. A status naming a later run, or a 404, ends
  it at once as `cloud_run_lost`; any other refusal while polling ends it at
  once as `transport_error`. A stopped cloud run writes no project
  memory, as a local one does not.
- Stop asks the runner to stop while a run of this department's owner may be
  going on it: a Run in flight, and a run sent earlier that has no end state
  here. A run start may have started a run when it got no answer or a 2xx the
  client could not read; one refused with a redirect, a 4xx or a 502 started
  nothing (a redirect comes from what stands in front of the runner, and a 409
  says a run is already active, not that this start began one). That doubt
  ends when the runner answers a stop (200, or 404 for a workspace it
  does not know), when a status settles the run or names a later one, or when
  a poll gets a 404; polling that gave up without such an answer leaves it. A
  refused run start adds no doubt and takes none away: an earlier run still in
  doubt stays so. If the runner cannot be reached, keeps
  answering 409, refuses the stop of a run with no known number, or does not
  answer within the Stop's single 60 s budget, the stop is unclean, and a Run
  in flight ends here as stopped: the client sees `cleanup_failed` (the session
  reads only whether the stop was clean). The owner logs one line on stderr,
  `<department>: stop: unclean: <why>`, where the why is in words (for example
  "the runner kept answering 409" or "the runner did not answer in time"), and
  the owner's own reason, `cloud_unavailable`, is not in it. While the doubt
  lasts, each later Stop asks again and stays `cleanup_failed`, with the
  workspace and its place kept, and the bridge's shutdown reports
  `cleanup_failed` too. The next Start answers `cloud_run_active` until the run
  ends on the runner.

Git sync refuses with `cloud_sync_failed`, and the bridge log carries the
reason: `not_github` (origin is not on github.com, or has more than one fetch
or push URL, or differs from the project's), `dirty` (uncommitted changes),
`diverged`, `unsynced` (the cloud may hold commits this machine lacks, or this
machine's commits must not be pushed: in the switch check below it shows as
`cloud_switch_refused`; in a cloud Start whose first runner status has a
`pushError` or the state `lost`, `sync_before_start` raises it when this machine
would have to push, and the client sees `cloud_sync_failed`), `unsafe_config`
(repository configuration that could run a program or redirect a network
command; the log names the key, and `_UNSAFE_SECTIONS`, `_UNSAFE_KEYS` and
`_UNSAFE_ORIGIN` in `bridge/cloud_git.py` list them) and `git_failed`. Every
git command runs without hooks, fsmonitor or repository filters, and the
network ones allow only `https` and `ssh`.

Back to local: a note per department, `<git-common-dir>/plaza/cloud/<domain>.json`,
is written when a department starts on the cloud and says whether the cloud
may hold commits this machine lacks (`unsynced`, from the start of a Run until
its commit is here). When the runner's first status at Start is `lost` or has
a `pushError`, the note is written as unsynced before anything is pushed or
created; if that write fails the Start is refused with `cloud_sync_failed`. A
local Start of a department with a note is refused with
`cloud_switch_refused` while the note says `unsynced` or the worktree has
uncommitted changes; once both are clear the note is removed and the Start
goes on. A department with no note is not checked at all. A note that cannot
be read is refused too, with `git_failed` in the log. After a run that ended
`lost` or with `pushError`, a Start alone does not clear the note. A Run clears
it when it settles on a status that is not `lost` and has no `pushError`, and
any commit the runner reports as pushed was fast-forwarded here; the Run's own
outcome does not matter. A Run that ends `lost` or with `pushError` leaves the
note unsynced even when its commit was taken, and so does a Run that was sent
to the runner and did not come back with a settled status (a transport error, a
lost run, a stop that gave up, a start answer the client could not read). The
earlier value is put back when the start is refused with a redirect (which
never reached the runner), a 4xx or a 502, or when a Stop arrives before the
run is sent. A Stop during a Start leaves the note unsynced when the runner
named a commit that the branch here does not hold, or that could not be
checked.

Not carried to the cloud: `DOMAIN_TIER` (the runner's `MODEL` decides),
`DOMAIN_MAX_BUDGET_USD` (the AI Gateway's spend limits decide), the permission
mode and the tool guard (the runner's agent has every tool, inside its
container). `DOMAIN_MAX_TURNS` is carried, capped at 100. The runner gets
no relay credential; the bridge keeps the relay claim.

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
coverage; owner desktop acceptance was recorded for M11 and M12. See the
[operating guide](../QUICKSTART.md#npc-conversation-history-and-controls-m11).
The bridge has no UI awareness, and legacy conversation clients may omit request IDs.
The character/domain amendment's M12 owner acceptance is complete; its recorded
source/runtime/mode-bound evidence remains historical. M13 has new deterministic
coverage; final fresh guard/live acceptance remains pending. Worktree notes and
bounded committed SQLite history survive restart without execution resumption.
See [M12 operations and platform limits](../QUICKSTART.md#project-work-and-domain-controls-m12)
and [bounded live evidence](../QUICKSTART.md#m12-live-evidence-and-desktop-checks).

## Planned platform evolution

The following milestones are **planned, not implemented by this document**.
Sequencing and acceptance criteria live in the [roadmap](../specs/roadmap.md);
the [bridge-first platform design](../docs/superpowers/specs/2026-10-18-bridge-first-platform-design.md)
describes the intended boundaries and open contract decisions.

| Milestone | Intended change |
|---|---|
| M13 | Bounded local persistence is implemented on this branch as documented above; final performance/fresh guard/live acceptance remains pending. Broader user/remote state is outside this increment. |
| M14 | Broader isolation and workspace/runtime providers beyond the M12 cooperative local Git worktree. |
| M15 | Authenticated hosted operation with durable storage and enforced ownership/access boundaries. |

Future user/project labels are intended identity inputs, not trusted principals
or authentication in today's local protocol. Transcripts, logs, labels, and an
SDK session ID do not independently establish durable ownership or recovery.
