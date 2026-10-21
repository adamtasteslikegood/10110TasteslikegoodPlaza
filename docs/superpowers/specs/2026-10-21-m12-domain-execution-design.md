---
doc_id: M12-DOMAIN-EXECUTION-DESIGN
title: M12 — Domain execution with a dedicated Git worktree
tier: 2
authority: implementation
status: DRAFT
doc_set_version: 0.2.16
last_updated: 2026-10
owner: adamtasteslikegood
derives_from: [PLATFORM-DECISIONS, DESIGN-25D, BRIDGE-PLATFORM-DESIGN]
supersedes: []
enforcement: intended
gates: [Validate Specs:live]
weakest_claim: M12 execution and its acceptance checks are not implemented by this specification.
---

# M12 — Domain execution with a dedicated Git worktree

**Deliver real agent work in a selected project's dedicated worktree, let the
player leave it running, and return to inspect the outcome through either client.**

## 1. Intent, approval and scope

The owner approved the M12 design direction on 2026-10-21: explicit Start/Run,
walking away backgrounds work, reliable correlated results, plain-client parity,
and real Agent SDK acceptance. The same instruction adds a dedicated execution
Git worktree now, separating agent edits from the checkout running the game and
bridge. The owner expects orchestration to grow toward independent parallel
workspaces, containers/VMs and integrated environment/data services.

This written specification is **DRAFT, awaiting review**. Detailed choices below,
including the session-length workspace reservation, are proposed implementation
decisions. M12 execution and its acceptance checks are not implemented by this specification.
Tracking: [PLZG-289](https://tasteslikegood.atlassian.net/browse/PLZG-289).

M10/M11 laptop operation was accepted by the owner on 2026-10-21 using local
`dev`, both Claude subscription and API-token authentication. The output cap was
a setting. This supplies the predecessor acceptance; it is not a new cloud run.

| Now: M12 | Later design work |
|---|---|
| One selected Git project; one dedicated execution worktree | Multiple projects and independent concurrent execution workspaces |
| Process-local domain context, lifecycle, replay and workspace reservation | Durable history, task recovery and authenticated ownership |
| Local Claude Code through Agent SDK, existing query caps | Containers, VMs, microVMs, network isolation and managed runtimes |
| Explicit Godot controls and equivalent plain-client operations | Additional clients and orchestration across providers |

The minimum worktree boundary moves forward from the original M14 scope. M13's
local state and M14's broader isolation may be reordered or combined in their
designs; integrated providers can offer both. M15 remains the hosted durability
and ownership capability, with no provider selected. A durable object alone does
not specify an execution filesystem or sandbox.

## 2. Verified baseline and changes required

Source baseline: `origin/dev` at `142b17a`, inspected 2026-10-21. Existing domain,
manager, protocol, server and runtime-wiring tests pass (112 checks). They do not
establish M12 acceptance. Current source has these relevant limits:

- `bridge/server.py` holds a single last-connected output socket and serially
  awaits NPC requests; domain controls can wait behind an NPC response.
- `bridge/domain_session.py` retains an SDK client, replaces its tracked task on
  overlapping submissions, and falls back to the process CWD for execution.
- Domain errors lack consistent correlation; SDK errors can replay as success;
  empty resume has no acknowledgement and output IDs restart on reactivation.
- Godot's `ws_client.gd` accepts only NPC responses. Its connection generation
  cannot also represent longer-lived domain work.

Preserve `D-005`/`D-020` client independence, `D-033` NPC timing, `D-034`
asynchronous domains and existing per-query turn/budget caps, and `D-037` default
SDK execution. No storyboard, unlock/map or model-provider change is proposed.

## 3. Component boundaries

| Unit | Owns | Receives / returns |
|---|---|---|
| Workspace manager | Selected project, validated execution location, exclusive reservation | Immutable workspace descriptor and reservation handle |
| Domain coordinator | Session generation, lifecycle, one pending query, bounded terminal results | UI-independent commands, acknowledgements and snapshots |
| SDK worker | Connect/query/receive/disconnect in one owning task | Workspace CWD, agent prompt, configured caps; terminal outcome |
| Transport | Per-connection command routing and delivery | Correlated messages; no global destination socket |
| `BridgeClient` + domain store | Client domain snapshots, drafts, cursors and deduplication | Domain events separate from existing NPC events |
| Domain HUD | Explicit controls, proximity anchor, results and input focus | Existing NPC signals and domain snapshots |

Use a small immutable `ExecutionWorkspace` descriptor: opaque process-local
`workspace_id`, canonical project root, repository common directory, registered
worktree directory, named branch and initial commit. Only the local workspace
manager understands Git administration. The SDK worker receives the validated
execution CWD; never change the bridge process CWD with `os.chdir`.

This seam lets a later workspace provider supply a different location/runtime.
Implement one local Git mechanism now, without an empty plugin framework,
provider registry, database or speculative container backend. Domain IDs,
execution request IDs, workspace IDs and provider session IDs remain distinct.

## 4. Workspace selection and reservation

### 4.1 Explicit project and execution location

Add startup options `--project-root PATH` and `--execution-worktree PATH` to the
bridge entry point; both must be supplied together. These are operator-selected
local paths, never client-supplied paths in WebSocket requests. If omitted, NPC
chat remains available and domain Start returns `workspace_unconfigured`.

Setup uses Git to create one named, dedicated linked worktree from an explicitly
selected project commit. The operating guide will provide the tested setup
procedure. The bridge validates that existing worktree; it never silently creates,
switches, resets, cleans, merges or removes it. Uncommitted changes and secret
files in the source checkout are not copied. The project can be Plaza itself or
another Git repository; agent definitions still come from the bridge agent store.

Canonicalize paths and inspect Git with argument arrays and sanitized Git override
variables. Require an existing non-bare project, an execution path equal to its
Git top-level, a live registration in `git worktree list --porcelain -z`, the same
canonical Git common directory as the project, a distinct per-worktree Git
directory, and a named branch distinct from the source checkout's branch.
Reject detached, missing, prunable, locked-for-maintenance or mismatched trees.

Execution and runtime checkout paths must be disjoint in both directions after
symlink resolution; execution and selected source checkout must also be disjoint.
The author's nested `.claude/worktrees/` directory is therefore not a valid
runtime execution location. Revalidate under the reservation immediately before
SDK startup; identity/branch changes fail closed. Never use `worktree_path or
base_path`, the bridge CWD, or an arbitrary client path as a fallback.

Dirty execution files are retained and allowed: this worktree is where previous
work lives. Show its branch/path and changed-file status before Start. Validation
does not overwrite an operator's work or prove that another editor is idle.

### 4.2 One reservation for the connected SDK session

**Start acquires the workspace; Stop releases it after SDK teardown.** In this
minimum single-worktree configuration, only one domain can own a connected SDK
session at a time. Other domain Starts return `workspace_busy` identifying the
current domain. Within that domain, a second Run while busy returns `domain_busy`.
There is no hidden queue. NPC conversations remain available independently.

Hold a POSIX advisory file lock in the worktree's Git administrative directory
across all cooperating bridge processes, plus an in-process coordinator guard.
Unsupported lock platforms reject domain startup; they do not run unlocked.
Background, query completion, idle time and socket loss retain the reservation.
The UI says **Stop to release workspace**, including after a task finishes.
This preserves native domain SDK context without leaving idle SDK clients outside
the reservation. Independent parallel workspaces will lift this initial limit.

Keep the lock file inode stable: recovery never unlinks or replaces that file.
Before SDK startup, write an unclean-execution marker beside the lock, fsync its
contents, atomically rename it, and fsync its containing directory. Failure to
make the marker durable rejects startup. Remove it and fsync the directory only
after the owned SDK worker/CLI is confirmed stopped. An interrupted
startup or uncertain teardown keeps the marker and rejects further Starts.
A restarted bridge encountering it requires explicit operator inspection and
recovery; a free lock, missing PID or elapsed timeout is not sufficient evidence.
This small operational marker prevents unsafe reuse; it does not restore domain
state or implement M13 persistence. Never store credentials or prompt bodies in it.

Git worktrees separate ordinary working files and indexes but share repository
objects, refs, config and hooks. They do not confine host filesystem/network
access or daemonized tool processes. M12 promises correct configured CWD,
cooperative reservation and supported SDK worker/CLI cleanup, not sandbox
containment or termination of every arbitrary tool descendant. Report detected
residual work as uncertain teardown and retain the marker. No automatic Git
integration or cleanup occurs on success, failure, cancellation or Stop.

## 5. Domain and execution lifecycle

Start validates/reserves the workspace, creates a fresh `domain_session_id`, and
starts an SDK worker. That worker owns connect, each query/response and disconnect
within one async context, following `conversation_sdk.py`'s cancellation pattern.
`ACTIVE` is acknowledged only after successful connection. Activation failure
cleans up, releases only after confirmed teardown, and returns a correlated error.

The coordinator separates foreground/background state from execution state
(`idle`, `running`, `stopping`, `cleanup_failed`). Background preserves in-flight
work and native SDK context. Refocus changes visibility and requests replay.
Successful completion returns to idle while keeping the workspace reservation.
SDK-reported failures retain partial text with error status and terminal reason;
transport failures do not change an already-recorded execution success. A broken
SDK transport rejects further Run commands until Stop drains it and a new Start
creates fresh context; it never reconnects or retries a tool task silently.

Stop cancels pending work through the owning worker, drains shielded cleanup,
records one cancellation terminal when needed, and then reports `DEACTIVATED`.
Repeated lifecycle commands are idempotent. Uncertain cleanup is visibly failed,
not a successful Stop; ownership and the unclean marker remain until resolved.
Reactivation after a clean Stop creates a fresh generation and fresh SDK context.

Bridge shutdown uses the same drain path. Socket disconnect only removes a
delivery destination: it neither cancels domain work nor releases its workspace.
After bridge restart, old client generations become unavailable; no request is
automatically resubmitted. The worktree files remain for review.

## 6. Protocol and replay

Preserve existing NPC request/response shapes. Domain commands retain their
current names and gain nonempty opaque request IDs, strict scalar validation and
correlated replies. Bound identifiers to 128 UTF-8 bytes and task/draft input to
64 KiB; reject malformed/oversized values before admission. Domain IDs must be
nonempty ASCII letters/digits/hyphen/underscore, not paths. No client request can
choose filesystem paths or SDK options. Run/background/refocus/Stop and replay
require the expected `domain_session_id`; a mismatch returns `session_unavailable`
and never affects a newer session. Duplicate accepted requests within the retained
result window return their existing state/outcome rather than executing again.
Clients never automatically retry an uncertain Run.

| Message | Required behavior |
|---|---|
| `describe_workspace` | Read-only configured/invalid/unconfigured status, branch/path, changed-file summary and current reservation; no SDK startup |
| `domain_status` | Read-only current state and available generation IDs for a domain; no activation or refocus |
| `activate_domain` | Correlated `activating` state after reservation with the new generation, then active/error after SDK connect; no Run until active |
| `domain_query` | One `domain_accepted` reply before any terminal, or a correlated rejection; never silently queued |
| `domain_result` | Exactly one stored terminal per admitted query: success, error or cancelled; includes original request ID, agent, task, partial/full output and terminal reason |
| `background_domain`, `refocus_domain`, `deactivate_domain` | Correlated state/error acknowledgement, including execution state |
| `resume` | Generation-aware replay after cursor, then `resume_complete`, even for zero results; current state and replay high-water mark included |

All domain-scoped packets carry `domain_id`; state/results also carry
`domain_session_id` and `workspace_id`. Terminal results add monotonic string
`output_id`. Clients deduplicate by `(domain_session_id, output_id)` rather than
NPC connection generation. Errors carry `status`, `error_type`, safe `message`
and the usable request/domain identifiers; malformed input never guesses identity.
Use `workspace_unconfigured`, `workspace_invalid`, `workspace_busy`, `domain_busy`,
`session_unavailable`, `invalid_request`, `sdk_error` and `cleanup_failed` as
explicit domain failures. SDK turn/budget exhaustion is an error terminal with
its observed reason, preserving partial output.

Store terminals before delivery. Push a query's terminal only to its originating
live connection; connecting or closing another client cannot redirect it. Another
local client first obtains the generation through `domain_status`, then deliberately
resumes that process-local domain. `describe_workspace` supplies the pre-Start
preview; its snapshot is advisory and admission always revalidates. This
is a trusted single-operator service, not authenticated ownership. Client focus
and consumed cursors are local; a lifecycle label from another client must not
open a panel, mark results read or remove buffered results.

Resume echoes the known generation or returns `session_unavailable`; a cursor
from a different generation never hides fresh results. Snapshot the high-water
mark for replay and allow live delivery to interleave, with client deduplication.
Keep at most 256 terminal entries and 4 MiB of UTF-8 output per generation;
cap each retained output at 256 KiB with an explicit truncation flag. Retain up
to ten domain IDs and two generations per domain; reject excess identities.
If a cursor predates retained data, report `history_gap` and the earliest retained
ID. Client display uses independent bounds of 200 entries and 1 MiB per domain,
including retained generations and drafts, with a visible omitted-entry count.

The socket reader must continue dispatching bounded domain controls while an NPC
call is pending; keep NPC calls serialized within their connection. Accept at
most one ordinary in-flight control per connection until its acknowledgement or
rejection, not until an admitted task completes (`domain_query` releases the slot
at `domain_accepted`). Stop and shutdown may preempt a pending Start using its
`activating` generation. Read-only discovery also remains available; all handlers
use bounded admission. A second ordinary control receives a correlated busy
rejection. Clients await refocus/background acknowledgement before a dependent
resume; busy errors retain their recoverable state. Shared workspace admission
remains server-enforced.

## 7. Godot interaction

Use the current `BridgeClient` autoload with a separate pure domain store and
domain signals. Demultiplex domain packets before NPC validation. A compact
domain panel presents workspace/branch, lifecycle, task state, Start, Run, Refocus,
Background/Close and Stop. NPC text, drafts, focus rules and provider context keep M11 semantics.

The explicit domain action at an NPC uses its existing `AgentRegistry` department
and captures that NPC as the interaction anchor. Start creates a session; Run
submits the task. Only leaving that anchor backgrounds its foreground domain and
hides/releases the execution panel. Another NPC's departure has no effect.
Returning to the anchor refocuses/replays an existing backgrounded session; it
never starts one or submits another task. Walking into a room starts no runtime.

Keep a passive global indicator while the panel is hidden. Explicit Refocus from
that indicator opens the results remotely and detaches the proximity anchor;
subsequent NPC proximity cannot hide that remotely opened view. Explicitly opening
domain work at an NPC reattaches it. Background/close releases the panel's keyboard
focus; Escape only releases keyboard focus, preserving the task and draft.
Incoming results never steal focus or replace a visible NPC response. Busy
rejections retain draft input. Rendered unread counts use the client's consumed
cursor, rather than treating every server-buffered output as unread.

## 8. Verification and completion boundary

Keep all existing bridge, Godot smoke and M11 integration gates. Add these
machine-checkable cases with actual Git worktrees and fake SDK synchronization:

1. Valid worktree selection reaches the exact SDK CWD. Same/overlapping runtime
   paths, symlink aliases, wrong repository, detached/unregistered trees and
   changed identities fail before SDK startup. No missing-path fallback occurs.
   Read-only workspace discovery provides the pre-Start preview without a lease.
2. Start A reserves the workspace across idle, Run completion, background and
   disconnect. Start B is rejected across both domains and bridge processes;
   it succeeds only after A's Stop finishes teardown. Repeated Start/Stop is safe.
3. Cancellation during connect, query and disconnect drains the owner task;
   uncertain cleanup retains the marker. Killing the bridge during execution
   makes a restart refuse workspace reuse pending explicit recovery. Stop preempts
   slow activation; marker durability precedes SDK spawn and recovery preserves
   lock-file identity.
4. Godot Run A, walk out of its actual NPC area, converse with B, release fake
   SDK completion, return to A and read the terminal from the rendered domain
   label. Assert one execution, no NPC overwrite and no duplicate replay.
5. Two WebSocket clients cannot steal pushes or disable each other's delivery.
   Reconnect replays without rerunning; empty replay, generation changes, bounded
   retention, history gaps and malformed/busy replies settle deterministically.
   Discovery permits a fresh client to attach, while stale-generation mutations
   cannot start, stop or alter a replacement session.
6. SDK exception, reported failure, cap exhaustion and cancellation each yield
   one accurate terminal; partial text remains inspectable. Edits survive every
   terminal state and Stop; no branch merge/reset/removal is performed.

Then run one bounded **real SDK tool task** in a disposable test project's
dedicated linked worktree. Start from a clean runtime checkout. Hold an external
release gate until Godot has acknowledged backgrounding and an unrelated NPC chat
has completed, then let the SDK create a unique file containing a nonce available
only after release. Assert the result file was absent before release and capture
the subsequent tool action; merely delaying a final response does not pass.
The harness controls the gate, not creation of the result file. Verify exact
file content and canonical location; inspect it and the terminal after Refocus.
The plain client retrieves the same generation/output through the same protocol.

Record tested commits, project/worktree identity, configured and observed CWD,
request/session/output IDs, SDK evidence, auth mode (never secrets), timestamps,
task outcome, Stop/cleanup outcome, and before/after runtime/source Git status,
HEAD and tracked-file hashes. Runtime/source tracked files and status remain
unchanged; expected result edits exist only in the execution tree. Shared Git
administrative metadata and ordinary runtime logs are not claimed immutable.

The live run is separate from deterministic CI and from the owner's prior M11
laptop acceptance. M12 closes only after implementation merges, automated gates
pass, the real tool/background/plain-client evidence is recorded, and desktop
controls have been accepted. This draft satisfies none of those runtime gates.

## 9. Written-spec handoff

Review this document before writing the implementation plan. On approval,
register the execution-workspace policy at `PLATFORM-DECISIONS` and its decision
register, following META-SPEC versioning before implementation; preserve the
minimum-now versus scalable-later distinction. No locked decision is silently
amended here. The plan must split workspace/SDK ownership, protocol, Godot and
verification tasks with tests and exact dependencies, using this approved spec.

*Last updated: October 2026*
