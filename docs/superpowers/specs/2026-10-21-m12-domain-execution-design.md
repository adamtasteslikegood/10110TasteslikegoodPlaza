---
doc_id: M12-DOMAIN-EXECUTION-DESIGN
title: M12 — Project worktree, short-term memory and domain execution
tier: 2
authority: implementation
status: ACTIVE
doc_set_version: 0.2.18
last_updated: 2026-10
owner: adamtasteslikegood
derives_from: [PLATFORM-DECISIONS, DESIGN-25D, BRIDGE-PLATFORM-DESIGN]
supersedes: []
enforcement: intended
gates: [Validate Specs:live]
weakest_claim: M12 execution and its acceptance checks are not implemented by this specification.
---

# M12 — Project worktree, short-term memory and domain execution

**Bind the bridge to one configured project, prepare its execution worktree and
three-file memory, and let the player leave real work running and return to it.**

## 1. Intent, approval and scope

The owner approved the M12 design direction on 2026-10-21: explicit Start/Run,
walking away backgrounds work, reliable correlated results, plain-client parity,
and real Agent SDK acceptance. The same instruction adds a dedicated execution
Git worktree now, separating agent edits from the checkout running the game and
bridge. The owner expects orchestration to grow toward independent parallel
workspaces, containers/VMs and integrated environment/data services.

The owner's subsequent clarification makes the three-file memory a **native
bridge feature for any selected project**, not instructions for developing Plaza.
The bridge uses `WORKSPACE_ROOT_DIR` from its configuration, with an environment
override, and one project per game/bridge session. It creates a dedicated worktree
when missing, creates missing memory files, and reads existing files. It must
not share memory across repositories. This supersedes the earlier operator-only
worktree setup and the mistakenly added Plaza development-session notes.
For an empty/non-Git directory, the owner explicitly chose **Chief Architect
confirms; bridge proceeds**, without another human approval prompt. New
repositories start on `main`, then enter the same workspace/memory flow.
Setup is part of gameplay: other NPCs direct the player to the Chief Architect;
talking to that agent triggers review. Every agent checks Git, worktree and memory
readiness before tools run, enforced by the bridge as well as agent context.

The owner **reviewed and approved this written specification on 2026-10-21**,
including the content at commit `57b631f`. The session-length reservation and
other detailed choices below are approved design requirements. M12 execution and its acceptance checks are not implemented by this specification.
Tracking: [PLZG-289](https://tasteslikegood.atlassian.net/browse/PLZG-289).

M10/M11 laptop operation was accepted by the owner on 2026-10-21 using local
`dev`, both Claude subscription and API-token authentication. The output cap was
a setting. This supplies the predecessor acceptance; it is not a new cloud run.

| Now: M12 | Later design work |
|---|---|
| One configured Git project; automatically create/reuse its dedicated worktree | Concurrent projects and independent execution workspaces |
| Bridge-owned TODO, handoff and turn-summary Markdown files per project | Structured application history, task recovery and authenticated ownership |
| Process-local SDK/domain context, replay and workspace reservation | Restored runtime state and cross-device service state |
| Local Claude Code through Agent SDK, existing query caps | Containers, VMs, microVMs, network isolation and managed runtimes |
| Explicit Godot controls and equivalent plain-client operations | Additional clients and orchestration across providers |

The minimum worktree boundary moves forward from the original M14 scope, and
bounded persistent project notes are now part of M12. M13's broader local state
and M14's broader isolation may be reordered or combined in their
designs; integrated providers can offer both. M15 remains the hosted durability
and ownership capability, with no provider selected. A durable object alone does
not specify an execution filesystem or sandbox.

### 1.1 Approved amendment — controlling current scope

Owner approval of the revised [character/domain amendment](2026-10-22-m12-character-domain-amendment.md)
at `eadb0b4` on 2026-10-22 (“ok, build it”), ratified in doc set 0.2.18,
supersedes the following sections wherever their original implementation scope
conflicts. This document retains the original delivered implementation contract
and evidence context; amendment approval is not implementation or acceptance.

| Original sections | Current approved contract |
|---|---|
| §§1, 4.1, 4.3: singleton worktree/capacity | One worktree/reservation per `(project_id, domain_id)`; same-department serialization, separate capacity limit. Safely adopt valid legacy Core in place preserving identity/path/branch/commits/dirty edits; uncertain or partial migration blocks reuse. |
| §§4.1–4.2, 6: NPC setup entry | Typed `project_setup` reaches Chief review before readiness; non-Chief referral remains reachable, never falls back to tools-disabled work. Exact inspected proposal/allowlist, `main`, no second human prompt; Start prepares the selected domain after project readiness. |
| §§4.4–4.5: NPC context/tool distinction | Catalog agents are working domain representatives; extras alone use tools-disabled conversation. Project TODO/HANDOFF/PROGRESS stays one serialized set under the common Git directory, attributing domain/agent/workspace. Fresh bounded game/work context applies to extras, setup and Runs. |
| §4.5 and §8 item 10: ordinary permission denial | Strict boolean permission setting defaults false (`dontAsk`); true uses `bypassPermissions`. Both retain Read/Edit/Bash inventory, mandatory fail-closed readiness/PreToolUse, reservation, memory and budget guards, and source/runtime/mode-bound real acceptance. |
| §§5–7: controls and role capture | NPC dialogue fronts domain state; approach/status is read-only, Start prepares/reserves, Send explicitly Runs. Shared department state captures representative per Run; leaving backgrounds. Stop remains available during idle/background ownership. Replay/status never activates, submits or steals focus. |
| §8: independent NPC conversation/live proof | Use an explicitly declared extra for independent tools-disabled conversation. Keep existing catalog agents working. Two-department service fixtures prove separation without claiming concurrency or playable second-department delivery. Laptop/OAuth acceptance stays separate from cloud API-key evidence. |

The amendment §§5–10 supply exact migration, context/configuration and acceptance
requirements. M13 richer persistence, M14 broader concurrency/isolation and M15
hosted state remain future work. Engineering's playable unlock belongs to M6 and
requires earned progression plus supported execution, preserving SB-08 arrival
and SB-09 first delegation. No storyboard beat is changed.

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
| Workspace manager | Configured project, worktree bootstrap/reuse, execution reservation | Immutable project/workspace descriptor and reservation handle |
| Project memory store | Three project-scoped Markdown files, bounded checkpoints and reads | Prior-project context and saved/degraded status |
| Readiness gate | Git/worktree/memory state, setup routing and permission before each tool | Shared readiness snapshot, Chief Architect referral or tool denial |
| Domain coordinator | Session generation, lifecycle, one pending query, bounded terminal results | UI-independent commands, acknowledgements and snapshots |
| SDK worker | Connect/query/receive/disconnect in one owning task | Workspace CWD, agent prompt, configured caps; terminal outcome |
| Transport | Per-connection command routing and delivery | Correlated messages; no global destination socket |
| `BridgeClient` + domain store | Client domain snapshots, drafts, cursors and deduplication | Domain events separate from existing NPC events |
| Domain HUD | Explicit controls, proximity anchor, results and input focus | Existing NPC signals and domain snapshots |

Use a small immutable `ExecutionWorkspace` descriptor: stable local `project_id`,
opaque `workspace_id`, canonical project root, repository common directory,
registered worktree directory, named branch and initial commit. Only the local workspace
manager understands Git administration. The SDK worker receives the validated
execution CWD; never change the bridge process CWD with `os.chdir`.

This seam lets a later workspace provider supply a different location/runtime.
Implement one local Git mechanism now, without an empty plugin framework,
provider registry, database or speculative container backend. Domain IDs,
execution request IDs, workspace IDs and provider session IDs remain distinct.

## 4. Workspace selection and reservation

### 4.1 Configured project and automatic bootstrap

Add `WORKSPACE_ROOT_DIR` to the existing `bridge/config.json` schema, overridden
by **`PLAZA_WORKSPACE_ROOT_DIR`**. Preserve existing precedence: built-ins, selected
JSON file, then environment. `BRIDGE_CONFIG_PATH` still selects the JSON file.
Relative workspace paths, including env overrides, resolve against that file's
directory, as `LOG_DIR` already does. No shell expansion, launch-CWD fallback or
competing project-root CLI flag is added. For example:

```json
{ "WORKSPACE_ROOT_DIR": "/home/user/projects/example" }
```

Built-in/shipped `null` means unconfigured: NPC chat can run without project
memory, and domain Start returns `workspace_unconfigured`. An explicit empty,
non-null non-string, missing or invalid path fails configuration instead of falling
back. The configured directory must exist; it may be an existing non-bare Git
top-level, empty, or contain non-Git project files. A subdirectory of another
repository is not silently treated as that parent project or initialized as a
nested repository. The configured project can be Plaza or another repository.
Agent definitions still come from the bridge agent store.

Resolve and freeze the project binding for the bridge lifetime. One game session
uses one such project; changing it requires restarting the bridge and a fresh
client connection. No WebSocket command chooses a directory. Project identity
is based on the canonical Git common directory, never a remote URL, basename,
agent ID or provider session. Linked worktrees of one repository belong to the
same project; separate clones remain separate even when their remotes match.

Bring up the listener while a bounded background bootstrap task inspects/prepares
the project. Discovery exposes `unconfigured`, `needs_architect`, `preparing`,
`reviewing`, `initializing`, `ready` or `failed`, with the current reason. Domain
Start before readiness returns `workspace_not_ready`. Ordinary NPC interactions
remain responsive as setup guidance/referrals; they do not launch project tools
or wait invisibly behind setup. Existing-repository bootstrap is automatic;
missing Git waits for the player to talk to the Chief Architect.

For an existing repository with a commit, under a repository-scoped bootstrap
lock at startup, locate the bridge-managed worktree recorded in that repository's
Git administrative metadata. On first use,
create it from the configured checkout's current HEAD, on a new named branch
`plaza/workspace-<project-key>`. The initial location is a sibling:
`<project-parent>/.plaza-worktrees/<project-name>-<project-key>/execution`, with
the key derived from canonical repository identity. This keeps execution outside
both source and runtime trees without modifying the source's ignore files.
Subsequent starts reuse the recorded location/branch and retain its edits.

Record versioned ownership, repository identity, worktree path, branch and initial
commit under `<git-common-dir>/plaza/`. Serialize bootstrap across bridge processes;
mark incomplete creation before invoking Git so interruption cannot masquerade as
a ready workspace. Persist ready ownership only after validation. Resume an
interrupted setup only after its recorded identity/state is reconciled; never
adopt an arbitrary occupied path or conflicting branch. A missing clean slot can
be created automatically; stale registration, incomplete setup or conflicting
ownership is surfaced as `workspace_invalid`, preserving existing files.

Worktree bootstrap creates filesystem/Git metadata and memory templates, **not a
domain SDK session or task**. New-repository review below is the explicit exception
allowing a bounded read-only model call when the player talks to the Chief
Architect before readiness. Start/Run stay explicit. Bootstrap never fetches,
copies uncommitted source changes/secrets, resets, switches, cleans, merges or removes
existing work. An existing execution worktree is not reset to the source's new
HEAD on restart. The operating guide will document location, reuse and recovery.

Canonicalize paths and inspect Git with argument arrays and sanitized Git override
variables. Require an existing non-bare project, an execution path equal to its
Git top-level, a live registration in `git worktree list --porcelain -z`, the same
canonical Git common directory as the project, a distinct per-worktree Git
directory, and a named branch distinct from the source checkout's branch.
Reject detached, missing, prunable, locked-for-maintenance or mismatched trees.

Execution and runtime checkout paths must be disjoint in both directions after
symlink resolution; execution and selected source checkout must also be disjoint.
The author's nested `.claude/worktrees/` directory is therefore not a valid
runtime execution location for this design. Revalidate under the reservation
immediately before SDK startup; identity/branch changes fail closed. Never use `worktree_path or
base_path`, the bridge CWD, or an arbitrary client path as a fallback.

Dirty execution files are retained and allowed: this worktree is where previous
work lives. Show its branch/path and changed-file status before Start. Validation
does not overwrite an operator's work or prove that another editor is idle.

Repository bootstrap and short memory updates have their own brief locks; they
do not require taking an active domain's session-length reservation. Bootstrap
must not modify/repair a worktree with an active reservation or unclean marker.
An already-running bridge can still serve NPC conversations while its domain runs.

### 4.2 Chief Architect confirmation for a new repository

An empty/non-Git configured directory enters `needs_architect`, rather than
failing or silently running `git init`. Every NPC request first checks the shared
readiness state. If the player talks to another NPC, respond through its normal
dialogue panel with a bridge-generated setup referral, such as **"Talk to the
Chief Architect to prepare this project, then come back and we can work on it."**
Do not start its normal model/tool task or auto-transfer the conversation. This
requires the player to walk to the Chief Architect and makes setup part of play.

On the player's first Chief Architect interaction while setup is needed, route
one bounded setup review to the existing **`systems-architect`** agent (the Chief
Architect role). Keep its actual registry identity; do not hand-edit generated agent data or invent another agent.
Run it through the existing configured conversation backend and timeout/caps,
with a fresh context and all model tools disabled. Domain execution remains disabled
until project setup finishes. A repository with an unborn HEAD also needs an
initial-commit proposal; preserve its existing local Git configuration.
Concurrent/repeated interactions share the current review status, not duplicate
initializations. Show the decision/outcome in that NPC's dialogue. Failed or
declined review does not retry automatically; a later explicit Chief Architect
interaction can request a fresh review. An existing malformed worktree or memory
also routes to the Chief Architect for an explanation, but this role does not
authorize automatic reset/deletion or bypass uncertain execution cleanup.

The bridge supplies a concrete initialization proposal: canonical directory,
directory identity, whether Git already exists, initial branch `main`, and a
bounded manifest of candidate seed files (relative paths, type, size and hashes).
Include a request/proposal ID and digest. Exclude credentials, ignored/generated
files, symlink traversal and nested repository contents from automatic seeding.
Large/ambiguous inventories require a narrower proposal, not blanket staging.
For an empty directory, propose an empty initial commit. Nonempty projects use
only the explicitly reviewed allowlist; remaining files stay untouched/untracked.
The review can request a narrower list, but the bridge does not perform unbounded
automatic model retries. A denial, timeout or malformed response leaves setup
pending/failed with a reason and no Git mutation.

Require a structured affirmative Chief Architect decision matching that exact
proposal and seed manifest. Free-form chat mentioning Git is not confirmation.
**The Chief Architect's confirmation is sufficient; do not ask the owner again.**
Before mutation, acquire a bootstrap lock keyed by the canonical candidate
directory (in the sibling managed-workspace metadata area), then revalidate that
directory, Git absence/unborn state and every seed file's hash/type. A competing
initialization or changed proposal invalidates approval; do not reuse it for a
different path or files. Release/reacquire locks around the model call so a slow
review cannot block unrelated project initialization.

On approval, the bridge initializes a new repository with `main` as its initial
default branch and stages only the approved allowlist in a temporary index
initialized empty, preserving any pre-existing index in an unborn repository.
Verify the complete staged tree's paths, types and contents against the approved
manifest before committing; a changed or transformed blob invalidates approval.
Create the exact reviewed tree as an identified bridge-authored initial commit
(allow-empty when appropriate). Do not use blanket `git add .`, invent the owner's commit identity, change global Git settings, add a
remote or push. Suppress inherited hooks/templates and content-transform filters
for this controlled initialization. If initialization partially fails, report the completed step and
retain files/Git metadata for a deliberate retry; never delete the directory to
roll back. Existing repositories with commits keep their current branches.
For an unborn repository, the confirmed proposal explicitly selects `main` while
retaining its prior index/configuration; a conflicting `main` ref invalidates it.

After a valid initial commit, compute repository identity and run the same
worktree bootstrap, three-file memory initialization and explicit Start/Run flow
as any pre-existing repository. Seed files are now available in the execution
worktree; excluded/untracked source files are not copied. Record the approval,
initial commit and seed/exclusion summary in project memory once it exists.

### 4.3 One reservation for the connected SDK session

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

### 4.4 Native three-file project memory

Store exactly three canonical memory files under
**`<git-common-dir>/plaza/session-memory/`**. They belong to the selected repository
and survive domain Stop, bridge restart and reuse of its execution worktree:

| File | Purpose | Bound |
|---|---|---|
| `TODO.md` | Open/completed work items with stable IDs and next actions | 16 KiB; 64 items |
| `HANDOFF.md` | Current user goal, active work, decisions, evidence, blockers and next step | 16 KiB |
| `PROGRESS.md` | Concise user/agent turn summaries and terminal outcomes, newest last | 32 KiB; 12 recent entries plus a short older recap |

This location keeps project memory independent of any particular agent's branch
and avoids committing private conversation summaries into ordinary project files.
There is no global/home-directory memory or copy from the Plaza repository.
Different repositories never read, initialize from, or update one another's files.
No `AGENTS.md`, `CLAUDE.md`, hooks or instructions are injected into the target
project. The bridge supplies the selected memory directly to its model calls.

After workspace bootstrap, read existing files and create only missing ones from
neutral templates. Each file carries a format version, project identity and
checkpoint revision. Missing-file repair preserves existing file content and
records the gap; it must not reset the other files. Reject identity mismatches,
symlink escapes, nonregular files, malformed UTF-8 and oversized inputs without
overwriting them. Read/checkpoint failure exposes `memory_unavailable` or degraded
status; it does not create a fresh empty history and call that recovery.

The bridge owns file writes through one memory store, with a short OS-level
project-memory lock shared by cooperating bridge processes. Serialize updates
from NPC conversations and domain tasks; merge against the latest revision
instead of replacing a newer snapshot with a stale model view. Use bounded
UTF-8 reads and atomic per-file temporary-write/fsync/replace. All three files
carry the same checkpoint revision; a partial multi-file commit is detected on
read and retained for inspection, never silently treated as a complete handoff.
Temporary writes and existing operational lock/ownership metadata are not extra
canonical memory documents. M12 does not claim a transactional database.

At each admitted NPC or domain turn, save a bounded user-intent summary and the
request/agent/domain identifiers as pending work. At its terminal, update the
handoff and TODO state and append one concise progress entry with outcome,
evidence references and next action. Backgrounding and Stop checkpoint lifecycle
state, without rerunning or prematurely completing the task. Do not log every
tool call. Condense old entries into the bounded recap rather than growing files.

Use an optional bounded structured `memory_delta` from the **same model call**
for a semantic summary/TODO proposal; validate fields and merge item IDs against
current state. If absent/invalid, save grounded, explicitly labeled task/result
excerpts and observed outcome. Do not guess completion or issue an extra hidden
model call to summarize. Model-authored notes are attributed proposals; bridge
execution facts and direct user instructions take precedence. Summary persistence
must also work with fake-provider fixtures, errors and cancelled tasks.
The adapter separates optional summary metadata from user-visible text; existing
NPC wire responses retain their shapes. A missing delta never exposes raw schema
data as the answer. Apply the same memory boundary to explicit API compatibility
mode; credentials still do not select a backend.

If a project-bound invocation cannot load consistent memory or persist its
pending-intent checkpoint, reject it with `memory_unavailable` before model/tool
execution. Bound lock/read/write waits; memory contention cannot hang the NPC
deadline. Setup guidance and the Chief Architect's fresh-context setup review
are the exceptions before project memory exists. Already-running work still
settles and reports any later persistence failure separately.

Load a fresh bounded snapshot before every model invocation, for both NPC and
domain work, as labeled prior-project notes rather than current user instructions
or synthetic conversation history. Saved files provide continuity, not authority
to run a task. Start after restart creates fresh SDK context; earlier pending work
is marked interrupted/unknown after ownership checks, never auto-submitted.
Current active work in another bridge process is not declared interrupted merely
because this bridge restarted. Client caches and provider state never cross a
changed project binding.

Memory failures do not rewrite task outcomes: a successful tool task with an
unsaved checkpoint remains successful with explicit unsaved-progress status.
Never retry the tool task to repair memory. Later successful saves must not claim
missing turns were durably recorded. Worktree edits and prior files are retained.
M13 still owns richer application history, restored domain state and explicit
task recovery; these persistent Markdown notes are a deliberate M12 capability.

### 4.5 Shared readiness check before tools

All NPC/domain entry points consult one workspace-state service, and every agent
tool invocation passes a bridge-controlled, catch-all SDK **`PreToolUse`** hook.
SDK 0.2.136 exposes this hook; `can_use_tool` alone is insufficient because
already-allowed tool calls can bypass that callback. Cover
all enabled built-in and external/MCP tools and delegated agent tool paths; a
prompt telling agents to check state is insufficient enforcement. If an execution
path cannot enforce the gate, do not enable its tools in M12. NPC tools remain
disabled under their existing contract; their readiness checks still determine
whether to converse with project context or refer the player for setup.
On failure return explicit `permissionDecision: "deny"`; success leaves ordinary
tool permissions unchanged. Keep this mandatory hook independent of optional
hooks and do not inherit the NPC adapter's hook-disabling settings. Verify the
pinned CLI's exception/timeout behavior: a hook failure must not become tool
authorization. These checks run directly in bridge code, not recursive model tools.

Before admitting a tool, revalidate the configured repository identity, registered
worktree and branch/CWD, current session's reservation, and readable consistent
project-memory identity/revision. Dirty execution files are allowed. Snapshot
changes, a lost lease or failed memory check deny the tool with a correlated
reason and Chief Architect/setup guidance; no automatic fallback CWD or hidden
retry. Changes detected while one tool is already running block later tools;
this check does not retroactively undo tool effects or sandbox child processes.

The bridge's own bootstrap Git/file operations use the same state service with
explicit setup capabilities: a confirmed exact initialization proposal permits
repo creation before Git/memory readiness; automatic worktree/template creation
is allowed only for the validated selected project. Agents cannot grant themselves
this exception through prompts or generic shell tools. Chief Architect review
itself has no mutating tools; the bridge applies the authorized setup operations.

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
| `describe_workspace` | Read-only project identity (once available), setup stage/Chief Architect decision, execution branch/path, changed-file summary, reservation, memory path/status and saved revision; no SDK startup or bootstrap mutation |
| `domain_status` | Read-only current state and available generation IDs for a domain; no activation or refocus |
| `activate_domain` | Correlated `activating` state after reservation with the new generation, then active/error after SDK connect; no Run until active |
| `domain_query` | One `domain_accepted` reply before any terminal, or a correlated rejection; never silently queued |
| `domain_result` | Exactly one stored terminal per admitted query: success, error or cancelled; includes original request ID, agent, task, partial/full output and terminal reason |
| `background_domain`, `refocus_domain`, `deactivate_domain` | Correlated state/error acknowledgement, including execution state |
| `resume` | Generation-aware replay after cursor, then `resume_complete`, even for zero results; current state and replay high-water mark included |

All workspace/domain packets carry `project_id` when configured. Domain-scoped
packets carry `domain_id`; state/results also carry
`domain_session_id` and `workspace_id`. Terminal results add monotonic string
`output_id`. Clients deduplicate by `(domain_session_id, output_id)` rather than
NPC connection generation. Errors carry `status`, `error_type`, safe `message`
and the usable request/domain identifiers; malformed input never guesses identity.
Use `workspace_unconfigured`, `workspace_invalid`, `workspace_busy`, `domain_busy`,
`workspace_not_ready`, `memory_unavailable`, `session_unavailable`,
`invalid_request`, `sdk_error` and `cleanup_failed` as
explicit domain failures. SDK turn/budget exhaustion is an error terminal with
its observed reason, preserving partial output.
Memory load/save status is separate from execution status and includes the latest
confirmed saved revision, or a safe failure code with `memory_unavailable`.

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
Background/Close and Stop. Show the bound project and a compact saved/unsaved/
unavailable memory indicator, plus repository-setup progress when needed. Chief
Architect confirmation is visible as agent activity; there is no extra user
approval dialog. Godot does not own a second persisted memory store
or expose project switching within a session. A changed project identity clears
client domain/draft/result caches before accepting new state. NPC wire text,
drafts and focus rules keep M11 semantics; prior-project notes are separate from
their bounded conversation transcripts.

While setup is needed, speaking to another NPC displays its Chief Architect
referral; the player walks to and interacts with the existing architect NPC to
begin review. Do not teleport, auto-open that NPC or automatically approve on
startup. Preserve normal movement, panel dismissal and NPC response correlation.
Refresh `describe_workspace` after NPC/domain terminals and lifecycle replies;
poll at a bounded rate only while setup is progressing. This updates the shared
project/memory indicator without changing the existing NPC wire shape or waiting
for an otherwise unrelated domain packet. The plain client can inspect the same
setup state and invoke the same architect interaction protocol.

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

1. Configuration selects JSON `WORKSPACE_ROOT_DIR`, env override and relative-path
   resolution correctly, independent of launch CWD. Bootstrap creates the managed
   worktree once from source HEAD, reuses it with edits intact, and reaches the
   exact SDK CWD. Same/overlapping runtime paths, symlink aliases, wrong repository,
   detached/unregistered trees, occupied locations, concurrent/incomplete bootstrap
   and changed identities fail before SDK startup. No missing-path fallback occurs.
   Read-only discovery supplies project/workspace/memory status without starting SDK.
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
7. Two distinct repositories (including clones of the same remote) receive
   separate worktrees and three-file memory. Startup creates only missing files,
   reads existing context unchanged, and never imports Plaza's development notes.
   Restart injects persisted summaries into fresh NPC/domain calls without
   resubmitting pending work or crossing project identity.
8. Interleaved NPC/domain turns and two bridge processes cannot overwrite newer
   checkpoints. Validate memory_delta, fallback excerpts, bounded recap, missing
   individual files, identity/symlink errors, oversized input, interrupted multi-file
   writes and save failures. A successful tool task with a failed save stays
   successful and visibly unsaved; no extra model request or tool retry occurs.
9. Empty and non-Git populated folders invoke the Chief Architect setup review.
   Affirmative exact-proposal confirmation produces `main`, the reviewed initial
   commit, a registered execution worktree and three memory files. Denial,
   timeout, malformed/stale approval, changed seed contents, competing setup and
   partial Git failure never become silent authorization. Check empty commits,
   explicit seed allowlists, excluded-file preservation, existing-repo bypass,
   unborn-HEAD handling with unapproved pre-staged entries, and no additional
   human prompt, remote or push. Merely starting the bridge or talking to another
   NPC cannot invoke review/init: the other NPC refers the player, who must
   interact with the Chief Architect. Observe setup progress before readiness.
10. Every tool path rechecks readiness: built-in Read/Edit/Bash, an external/MCP
    tool and delegated-agent tools. Lost leases, altered Git/worktree identity,
    unavailable/inconsistent memory and hook exception/timeout never execute the
    guarded tool. Existing ordinary permission denials still apply after readiness
    succeeds. Verify this against the pinned SDK/CLI, not only a fake hook.

Then exercise the setup flow in an empty disposable project selected through
configuration: an ordinary NPC refers the player, the player interacts with the
Chief Architect, and a real bounded review approves `main` initialization. Verify
the initial commit, dedicated worktree and three memory files, then capture the
post-bootstrap source/runtime baseline. Run one bounded **real SDK tool task**
in that worktree. Hold an external
release gate until Godot has acknowledged backgrounding and an unrelated NPC chat
has completed, then let the SDK create a unique file containing a nonce available
only after release. Assert the result file was absent before release and capture
the subsequent tool action; merely delaying a final response does not pass.
The harness controls the gate, not creation of the result file. Verify exact
file content and canonical location; inspect it and the terminal after Refocus.
The plain client retrieves the same generation/output through the same protocol.
Verify that its outcome and next step appear in the three project-memory files;
after a clean bridge restart, show that a fresh invocation receives those notes
without rerunning the completed task. A second configured repository starts with
its own memory and cannot receive the first project's nonce or notes.

Record tested commits, project/worktree identity, configured and observed CWD,
request/session/output IDs, SDK evidence, auth mode (never secrets), timestamps,
task outcome, Stop/cleanup outcome, and before/after runtime/source Git status,
HEAD and tracked-file hashes. Initialization's approved Git/seed changes are
recorded separately. During subsequent domain execution, runtime/source tracked
files and status remain unchanged; expected result edits exist only in the
execution tree. Shared Git administrative metadata and ordinary runtime logs are not claimed immutable.

The live run is separate from deterministic CI and from the owner's prior M11
laptop acceptance. M12 closes only after implementation merges, automated gates
pass, the real tool/background/plain-client evidence is recorded, and desktop
controls have been accepted. This specification satisfies none of those runtime gates.

**Implementation evidence, 2026-10-21:** Tasks 1–9 have reviewed deterministic
coverage. The [fresh guard matrix](../../../specs/evidence/m12-guard-2026-10-21.json)
and [real Linux headless flow](../../../specs/evidence/m12-live-2026-10-21.json)
passed at live-code commit `c128b543d73864099002247c7f32854e2b020c3f`, with
closed manifests, SDK/bridge exit 0 and detached ownership. Failed attempts remain
recorded separately. This proves neither a different laptop binary nor desktop
focus/controls/visible unsaved state. Implementation merge and M12 owner desktop
acceptance remain open; see the [operator checklist](../../../QUICKSTART.md#m12-live-evidence-and-desktop-checks).

## 9. Written-spec handoff

Written-spec approval is recorded on 2026-10-21. `D-038`/`D-039` register the
approved workspace/bootstrap/readiness and project-memory policies in
`PLATFORM-DECISIONS` and its decision register, with doc set 0.2.17.
The [implementation plan](../plans/2026-10-21-m12-project-execution.md) splits
configuration/bootstrap, project memory, workspace/SDK ownership, protocol, Godot
and verification tasks. The written plan is owner-approved for subagent-driven execution and execution-method
selection before runtime implementation. Minimum-now versus scalable-later scope
remains explicit.

*Last updated: October 2026*
