# M13 bounded SQLite session persistence

**Status:** proposed for owner review; implementation is not authorized by this document.
**Baseline:** #373 delivered in PR #376 (`a2d340a`); design branch also incorporates
current dev `1bb3a19`. Earlier runtime/paid evidence keeps its original bindings.

## 1. Intent and confirmed direction

A player can stop work, close the game/bridge, return to the same configured
project and recover the department's application session and retained results.
The agent receives a bounded recap when a fresh SDK runtime first handles work.
Restoring history never silently re-runs a task or claims an SDK process survived.

Adam has already selected: stdlib SQLite; project-scoped continuity; application
identity survives restart unless intentionally ended; **Stop preserves the session,
End session is separate**; and **restore a bounded conversation recap for the
agent alongside project notes** (October 26 Pacific). Do not ask these again.
Hetzner-in-B and both auth paths remain recorded later-phase inputs, not cloud
features delivered here. The user is configuring Confluence's separate Actions token.

This increment includes local session/history persistence, accepted-work recovery,
explicit End, the minimum client changes to discover/replay saved sessions, and
bounded model-context restoration. NPC extras' conversational runtime/history,
UI drafts/layout/read-position persistence, execution backends, remote stores,
provider-session resume, cross-host leases and sandboxing are outside this increment.
Three Markdown project notes and M10 diagnostic archives retain separate contracts.

## 2. Approaches and proposed builder choices

These are recommendations for review, **not choices attributed to Adam**.

- **Recommended: asynchronous durable worker plus an event-loop memory view.**
  Keep replay/lookups responsive; serialize writes off the event loop and publish
  a new view only after durable success. This preserves admission's no-await
  critical section while making durable I/O ownership explicit.
- **Alternative: fully asynchronous SQLite reads and writes.** Avoid a replay
  cache, but migrate replay and duplicate lookup callers and install admission
  fences before every await. Reasonable later; a wider first persistence change.
- Running filesystem commits directly in synchronous `MemoryStore.append()` is
  rejected: a slow/full filesystem would stall other clients and shutdown control.

**Storage recommendation:** initially use SQLite in memory inside the single
worker, persisting its serialized SQLite image through the existing anchored,
no-follow, fsync/atomic-replace project-file primitives. The saved file is a valid
SQLite database, not JSON/JSONL. This deliberately uses **no WAL/journal sidecars**.
The older proposal's WAL detail was not an owner answer. Conventional file/WAL
SQLite is an alternative once its database/sidecar opening and recovery can meet
an explicitly reviewed filesystem contract. Prechecking a filename does not make
SQLite's subsequent pathname opens equivalent to the anchored file helpers.

Trade-off: every state commit copies/writes the bounded image, so this favors
one local user and bounded state over write throughput. Measure commit latency
and memory before calling it acceptable; later migrate storage mechanics under
the same lifecycle contract. No claim that this is the eventual remote substrate.

## 3. Ownership, files and limits

One state database per configured repository's validated **common Git directory**:
`<common-git-dir>/plaza/application-state/state.sqlite3`, with a stable
`writer.lock` beside it. It is shared by that project's department worktrees,
not by unrelated repositories. Never locate it using an untrusted client path.
Store and check the existing canonical `project_id` in the image. A copied image,
renamed-root identity mismatch, unsafe file, or wrong schema fails visibly; no
silent adoption, deletion, empty replacement or debug-log import.

Existing databases load when the configured project is ready. A missing database
is created on the first explicit Start, not by approaching an NPC or refreshing
status. No database is created for an unset/non-Git/unprepared project; Chief
Architect bootstrap remains the prerequisite. Status can report a missing new
store without calling a model. Reopening existing state calls no model either.

Persist a small initialization manifest containing the store-instance UUID and
initializing/ready state through the same safe file primitives. Create it before
the initial database, then mark ready only after the image is durable. Only the
absence of **both** manifest and image permits first initialization. A missing
image after initialization, an orphan image, or an interrupted initializing marker
is a visible inspection/recovery condition, not permission to silently create an
empty store. The implementation plan must include both crash boundaries here.

A bridge holds the existing safe OS-lock abstraction on a validated stable inode
for the database writer lifetime. A second bridge for that project may not claim
writer authority; it reports `state_store_busy` rather than opening a competing
writer. Read-only UI observation through the owning bridge remains available.
This is single-host cooperation, not containment against arbitrary same-user Bash.

Proposed fixed initial bounds:

- Serialized image: **64 MiB**; at most **128 sessions** and **10 domains** per project.
- Each session's replay window: existing **256 terminals / 4 MiB output-text UTF-8**;
  each output remains capped at **256 KiB** and each task at **64 KiB**.
- Terminal JSON uses UTF-8 (`ensure_ascii=False`) with a **2 MiB packet cap**;
  account separately for task/metadata/control-character escaping, not just output.
- At most one accepted unfinished Run per domain; current global execution capacity
  remains one. A 2 MiB logical completion allowance is checked/reserved at admission.
  This reduces quota failures; it cannot guarantee against physical ENOSPC/fsync failure.
- Recap: **16 KiB UTF-8 total**, defined below. No unbounded transcript prompt.

The image limit includes SQLite pages/metadata. Compact after deletions before
size validation. Atomic replacement can temporarily require old and new images
(up to 128 MiB), plus validated remnants from failed writes; report that separately
rather than claiming 64 MiB is a total disk quota. Failed temporary files retain
inspection evidence. Never automatically prune unrecognized files to make space.

At quota, new work/Start fails clearly before tools when possible. Reads and Stop
remain available; no oldest-session deletion to fake a successful save. End does
not delete history. Provide an **offline, lock-respecting maintenance CLI** to
export a session and explicitly delete selected ended sessions after backup;
refuse active sessions, unsafe output paths and concurrent writers. Its operations
are local operator actions, not model-triggered bridge commands. Exact CLI flags
and module decomposition are implementation-plan choices.

## 4. State model and schema

Use one worker-owned `sqlite3.Connection`; no event-loop thread accesses it.
Require Python's stdlib serialize/deserialize support at startup; absence is a
visible unsupported-runtime condition, never an unsafe pathname/WAL fallback.
Parameterized SQL only; schema version starts at 1. Validate integrity, project
identity, allowed schema objects, row bounds and foreign keys on load before use;
disable extension loading and trusted-schema features. Reject newer/incompatible
schemas and corrupt images while preserving the bytes. Versioned migrations need
an immutable pre-migration backup and atomic replacement; v1 does not invent an
upgrade path for unknown formats.

Logical records (exact SQL/index names are builder choices):

| Record | Required data and invariant |
|---|---|
| Project metadata | schema version, store-instance UUID matching the initialization manifest, project_id, monotonically increasing durable revision |
| Domain | domain_id, nullable current open session, monotonically increasing domain_revision |
| Application session | UUID, domain, created_at, nullable ended_at/ended_by (`user` or `bridge`), terminal highwater; one open session per domain |
| Execution | UUID, application session, boot UUID, start/stop times, execution/cleanup outcome; never authority that an old process is alive |
| Request | session + request_id unique, execution_id, originating agent, bounded task and digest, project-memory turn_id/revision, accepted/dispatched/terminal/recovered disposition, completion allowance |
| Terminal | session + dense numeric output_id unique, request correlation, frozen terminal packet, output UTF-8 byte count |

Store no credentials, environment dumps, raw SDK objects, complete guidance files
or provider-process recovery tokens. Application task/output text **can itself
contain sensitive content**; it is local cleartext, mode 0600 inside mode 0700
metadata directories, not a secret vault. Diagnostic transcript opt-out is separate
from application persistence. Proposed startup setting `DOMAIN_STATE_BACKEND`
(`sqlite` default / explicit `memory`, with `PLAZA_` override) makes that distinction
visible. No automatic fallback to memory on storage failure. Memory mode reports
its non-durability and still uses the explicit Stop/End lifecycle within that process.
Changing backend is startup-only. Memory mode does not modify/import the prior
SQLite history; returning to SQLite resumes its saved session, not the intervening
volatile session. Make that discontinuity visible instead of inventing continuity.

Completed request records expire with their retained terminals, preserving the
existing bounded duplicate window. Unfinished requests cannot be evicted as old
history. Retrying an identical retained request returns its saved disposition;
conflicting task/agent content is rejected. This is not lifetime exactly-once
execution, nor proof of external tool side effects after a crash.

## 5. Durable I/O and publication contract

Keep `MemoryStore`'s phase-1 synchronous semantics. Add a persistence coordinator
and repository contract rather than claiming a synchronous network/disk store is
already a drop-in replacement. Loaded replay views must preserve their actual
IDs/highwater, including when every retained terminal has been trimmed.

The worker stages a candidate SQLite revision, serializes it, validates the size,
then uses the safe atomic replacement primitive (file fsync, rename, parent fsync).
Only a successful durable replacement permits the event-loop coordinator to
publish its associated immutable memory view and acknowledge the operation.
The worker never mutates the event loop's deque/session objects.

A known failed write keeps the last published view and closes work admission.
An uncertain rename/fsync outcome also closes admission; inspect/reopen the image
under the same writer authority to reconcile revisions. Do not advance visible
highwater, report saved=true, reuse an output ID, or blindly retry a tool because
acknowledgement failed. A readable prior view may remain available with an explicit
persistence warning; it is not evidence the last attempted write committed.

Every SQLite worker is tracked and drained through existing owned-I/O patterns.
Cancellation/timeouts detach callers, not writers. Stop/shutdown may not abandon
a worker and claim clean release. A completed storage failure is distinguished
from an unsettled worker: execution ownership can release only after actual SDK,
metadata and worker cleanup is confirmed, while the persistence failure stays
visible. End cannot succeed without its durable end marker.

## 6. Run, crash and cross-store ordering

Admission installs the local pending record before suspension, then:

1. Validate current execution identity, binding, Git/worktree/ownership/readiness.
2. Prepare the existing Markdown pending turn; record its turn_id and revision.
3. Durably record the accepted request plus completion allowance; only then emit
   `domain_accepted`. If this fails, do not call the model/tools; settle the
   Markdown intent as not executed when safely possible.
4. Durably mark dispatch intent **before** invoking `owner.execute`. This marker
   is conservative: a crash immediately after it may precede any actual SDK call.
5. Execute with existing guards. Finish project notes using the real outcome,
   retaining the existing visible memory-save failure behavior.
6. Atomically persist the terminal, request disposition, highwater and replay
   trimming; publish the new memory view; then record/deliver the terminal.

These are **not** one transaction across Markdown, SQLite and external tools.
On boot, accepted-but-not-dispatched requests become a durable not-executed result;
dispatched-without-terminal requests become an interrupted/unknown-outcome result.
Use the next output ID and a fixed public explanation; never fabricate success
or automatically retry. A committed terminal lost before delivery replays exactly.

Reconcile a pending Markdown turn only after workspace readiness/ownership allows
it, by exact turn_id and observed current note state. Do not overwrite an already
completed note with an invented interrupted outcome. SQLite recovery can display
an interruption while notes remain unavailable; surface the discrepancy. Existing
unclean run/worktree markers are preserved and continue blocking tools until the
normal operator-reviewed recovery. No crash-recovery code deletes those markers.

If result persistence fails after tools, show a bounded persistence error and any
available partial/final text as **uncommitted**, without a fake durable output_id.
Leave the SQL request unresolved/uncertain as appropriate; a later reopen must
not infer that the visible answer proves a committed terminal. Allow a clear,
explicit recovery path, not disabled controls with only “project ready”.

## 7. Stop, End and execution fencing

| Action | Application session | SDK/workspace | Durable history |
|---|---|---|---|
| Status/reopen/replay | Reuse saved open ID | No SDK start, reservation or model call | Read bounded committed history |
| Explicit Start | Reuse open ID, or create a new one after End | New execution UUID; fresh SDK runtime; normal readiness/reservation | Preserve prior outputs/highwater |
| Run | Same open ID | Explicit current execution only | Accepted/dispatch/terminal commits as above |
| Stop | Remains open | Stop/drain; release only when confirmed | Preserve identity/results; record observed stop outcome |
| End session | Persist ended_at and actor; no automatic replacement session | Orderly Stop first; failure leaves End unsuccessful | Retained, read-only; deletion is separate |
| Bridge/game exit or crash | Does not End | Clean shutdown uses Stop; crash means no live-worker assumption | Recover committed records and mark incomplete requests honestly |

Application identity and execution identity must be different. Reusing the old
wire session ID alone would let delayed commands target a newer SDK generation.
Propose **domain protocol version 2**, advertised in workspace/capability facts:

- `domain_session_id` becomes the stable application session UUID.
- `execution_id` is new per explicit activation and required on query/background/
  refocus/deactivate controls. Reject old execution tokens; replayed terminals from
  older executions remain history, not current lifecycle updates.
- Domain status carries a persisted monotonic decimal-string `domain_revision`.
  Activate and End include `expected_domain_revision` (compare-and-set), including
  first Start at revision `0`; increment it on lifecycle changes and recovery.
  This fences stale Start/End even when no open session currently exists.
- `end_domain_session` includes session ID and expected domain revision; the actor
  comes from the bridge's control path, not a client-supplied attribution string.
- Resume remains read-only, addressed by application session and cursor; terminal
  packets preserve existing fields/IDs and add execution correlation. Saved frozen
  memory-result fields remain historical; current readiness/memory facts are separate.

Old clients must receive a clear upgrade-required capability/error rather than
silently operating without fencing. No new client-supplied filesystem paths.
Current and ended sessions are enumerated as bounded saved-session metadata;
resume can target an ended session read-only. The game initially restores the
open session, otherwise the latest ended session. Start after End is explicit.

## 8. Bounded agent recap

On the first Run of **each fresh SDK execution**, derive a recap from that
application session's retained committed data and include it beside fresh project
notes. Later Runs in the same SDK execution do not resend the same recap. Record
the supplied highwater/source range as context metadata, not a claim the provider
successfully consumed it. Restart creates a new execution only after explicit Start.

Use a deterministic extract, **no extra model call**: at most the latest four
terminal task/result pairs in chronological order. Each task excerpt is at most
1 KiB UTF-8; each answer excerpt at most 2 KiB; labels identify representative,
outcome and output ID. Include one bounded interrupted-work notice when applicable.
The entire rendered recap, labels and notices included, is at most 16 KiB UTF-8.
Clip safely at Unicode boundaries and label omissions/truncation. No replay of
current pending input as a prior instruction, no recap across projects/sessions,
and no importing M10 archives or the shared PR gate ledger.

Treat this as quoted, unverified continuity data—not instruction authority or an
automatic task queue. Fresh game/work guidance, actual current capabilities and
the player's current Run remain distinct. End followed by a new application session
gets no old-session conversation recap; shared project notes still apply. If the
state view cannot be trusted/read, fail that Run visibly rather than silently
claiming restored context. Notes failing their existing checks also remain errors.

## 9. Client behavior and governance alignment

Both working-character dialogue and the shared domain pane use the same stable
session, execution token and cursor. Reconnect discovers saved session/status and
replays without preparing work or moving focus. Show stopped/restored, ended,
interrupted/unknown and persistence-failed states distinctly; an End action is
separate from Stop. A failed End retains the session and draft. Live uncommitted
answers cannot be mistaken for saved history on reconnect. Preserve Copy/Select All,
scroll, representative attribution and the explicit Start/Run interaction.

Before implementation, propagate an approved contract through entitled sources:
platform decisions / original M12 generation scope, roadmap, protocol/client docs,
config defaults and this design. Stable application identity refines M13 behavior;
M12's historical per-generation UUID contract remains historical, not silently
reinterpreted. D-005/D-020, SDK-default D-037, D-038 readiness and D-039 notes are
preserved. No new locked D-row or provider choice is created by this proposal.

## 10. Acceptance and handoff

Implementation plan must cover independent contract, crash/process and real-client
proof, not only SQLite mocks:

- Reopen the same project after Stop/restart: same app ID and exact committed
  terminal IDs; no SDK/model/tool call until explicit Start/Run; separate execution ID.
- End survives restart with actor attribution; next explicit Start creates a new
  app ID. Failed End/uncertain cleanup never marks it ended or clears ownership.
- Crash at each boundary in §6, including commit-before-delivery and notes-before-
  terminal; correct not-executed/interrupted/replayed result with no automatic retry.
- Block/kill during a write or cancel its caller: no unowned write, premature
  success or unsafe lock/lease release; second bridge cannot write the same project.
- Interrupted first initialization, missing-after-ready and orphan images must not
  silently reset identity/history.
- Symlink/hardlink/path swaps, corrupt/newer/wrong-project images, read-only/full
  disk, quota, replacement/fsync failures: visible bounded errors and preserved data.
- Preserve replay cursor/gap/count/output-byte and bounded duplicate contracts;
  restored highwater when the retained window is empty; stale execution and lifecycle
  revision commands rejected; fresh game plus temporarily disconnected client tested.
- Recap exact byte limits/Unicode/omissions, latest representatives and interrupted
  notices; current pending task excluded; old transcript “instructions” stay quoted;
  no cross-project or post-End recap; no extra summarizer/provider call.
- Offline export/prune refuses active sessions/foreign writers and leaves a valid
  restorable image. Exercise compaction, image bounds and repeated atomic writes.
- Measure image commit latency and peak memory at representative/64 MiB bounds;
  prove event-loop heartbeat/replay remain responsive during slow durable I/O.
- Complete existing Python, pinned Godot, formatting, spec and protocol gates.
  Identify changed guarded sources and collect genuinely fresh runtime/mode/live
  evidence where required. Add any new component that authorizes tool execution
  to the guarded-source inventory and its real evidence campaign; unchanged old
  fingerprints cannot certify a new guard path. Never restamp historical reports.

Next: fresh builder check, owner design review, then the implementation plan.
No product implementation, scaffold or new dependency is part of this design work.


### Builder-check receipt

A fresh bridge/runtime builder reviewed this proposal and reported **“nothing
important left”**. Subsequent author clarification makes missing-after-initialization
state and explicit memory/SQLite backend discontinuities unambiguous. These are
proposed safety/continuity requirements, not claims about implemented behavior.
