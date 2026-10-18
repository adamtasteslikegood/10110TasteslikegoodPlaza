---
doc_id: PLATFORM-DECISIONS
title: Platform Decisions — engine, transport, data layer, licence, repo policy
tier: 2
authority: implementation
status: ACTIVE
doc_set_version: 0.2.15
last_updated: 2026-10
owner: adamtasteslikegood
derives_from: [META-SPEC]
supersedes: []
decides: [D-003, D-005, D-015, D-016, D-018, D-021, D-022, D-023, D-024, D-029, D-030, D-031, D-032, D-034, D-035, D-036]
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: Nine of these were already made, already evidenced,
---

# Platform Decisions

> **One line:** the sixteen project-level decisions (fifteen in force, `D-030`
> superseded) that are neither concept nor
> prototype design — engine, bridge boundary, transport, data layer, licence, and
> repository policy — and the document entitled to originate them.

This document exists because those decisions previously had no entitled home.
[`../../README.md`](../../README.md) (`PROJECT-OVERVIEW`) was named as the origin of
eight of them while declaring `authority: derived`, which
[`../../specs/meta/META-SPEC.md`](../../specs/meta/META-SPEC.md) §2 licenses to
decide *nothing new*. The layer contradicted itself. Recorded as open conflict §4.8
in [`../../specs/meta/spec-drivers-v0.2.5.md`](../../specs/meta/spec-drivers-v0.2.5.md),
tracked as [issue #11](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/11),
and closed by creating this file.

`D-005` joined them in v0.2.9 for the same reason at the opposite end of the ladder:
its origin was tier-0 `META-SPEC`, which §2 forbids to originate product decisions
at all. Open conflict §4.9, [issue #18](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/18).
Twice now the entitlement error has been found by reading the authority column
rather than the decision — the decisions themselves were never in doubt.

**Nine of these were already made, already evidenced,
and already being acted on.** What changed is which document is entitled to hold
them — `PROJECT-OVERVIEW` goes back to being purely the reconciliation of the two
axes, which is what `META-SPEC` §2 already said it was, and `META-SPEC` goes back to
deciding only about documents. `D-029` and `D-030` are the exceptions: both are new decisions
registered here because they pass the scope test in §1 — `D-029` in v0.2.12 (the
bridge agent store survives replacing the frontend), `D-030` from the `PLZG-199`
review (a review-round bound has nothing to do with the frontend). `D-031` and
`D-032` followed in v0.2.14 on the owner's instruction of 2026-10-09 (`PLZG-274`):
`D-031` supersedes `D-030`, and `D-032` is new.
`D-034`–`D-036` follow in doc set 0.2.15 on the owner's written-design/plan approval
and execution-scope ruling of 2026-10-18. They authorize M10 policy implementation;
they do not claim that the planned recorder or configuration layer has shipped.

## 1. Scope — what belongs in this document

| Belongs here | Belongs elsewhere |
|---|---|
| Engine, language, and runtime choices | How a scene is built → [`2.5D-RPG-Prototype.md`](2.5D-RPG-Prototype.md) |
| Transport and process boundaries for the bridge | What the player experiences → [`../storyboard-week1.md`](../storyboard-week1.md) |
| Where canonical data comes from and how it is derived | The department/floor/colour mapping → [`../agent-directory.md`](../agent-directory.md) |
| Licence and attribution | Sequencing and task breakdown → [`../../specs/roadmap.md`](../../specs/roadmap.md) |
| Repository and submodule policy | How documents govern each other → `META-SPEC` |

The test: **would this decision survive replacing the entire frontend?** If yes it
is a platform decision and lives here. If it dies with the 2.5D prototype, it
belongs in the promoted design. `D-003` (Godot 4) sits deliberately on the line —
it is here because the engine choice predates the 2.5D pivot and outlives it; the
pivot decided *2D rather than 3D within Godot*, which is `D-001` and lives there.

## 2. Platform

### `D-003` — Engine: Godot 4

Free, MIT-licensed, GDScript reads like Python, strong 2D and TileMap support.
Chosen over Three.js and Unity. The MIT licensing matters beyond cost: it is what
lets `D-018` hold without a licence-compatibility argument.

### `D-005` — Bridge UI-awareness: zero

The bridge never knows the UI exists. It exchanges intents and results; no
document, task, or line of code may make Layer 3 aware of Godot, scenes, sprites,
HUD, rooms, or any rendering concept.

**Swap test:** if replacing Godot with a CLI harness would require a bridge
change, the boundary is broken and the change fails review.

This is what makes `D-020` — Layer 2 named for the role, not the implementation —
architecture rather than aspiration. A CLI harness, a web UI, and the eventual 3D
world are peers of 2.5D Godot, not replacements for the layer.

*Originated here as of v0.2.9.* It was previously attributed to `META-SPEC` §5.1,
which is tier 0 and licensed to decide about documents, never about the product —
so a genuine architecture constraint was being originated by the one document
forbidden to originate it. Recorded as open conflict §4.9, settled by the owner as
option (a) on [issue #18](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/18).
`META-SPEC` §5.1 still **states** the rule and still binds agents to it — it now
cites this decision rather than making it. The rule did not change; only the
question of who was entitled to make it.

Scope note: it passes this document's own test. Replace the entire frontend and
`D-005` is not merely unaffected — it is the decision that makes the replacement
possible at all.

### `D-015` — Bridge transport: Python WebSocket, `ws://localhost:8765`

A local process, so the prototype needs no deployment story. Pairs with `D-033`
(synchronous NPC conversations with timeout) in the promoted design. Domains
execute asynchronously with buffered results under `D-034`. **This decision names a
transport, not a UI** — `D-005` still holds, and a change here that leaks a
rendering concept into the bridge fails the swap test regardless of what this
document says.

### `D-016` — Agent data layer: generated, never hand-written

`data/agents.json` is generated from the `claude-code-tresor` submodule by
[`../../scripts/generate_agents_json.py`](../../scripts/generate_agents_json.py).
The submodule is the canonical agent layer; hand-editing the JSON forks the truth.
Minimum fields per agent: `{name, role, dept, colour, tools, description}`.
Enforced in CI by `Validate Agent Data`, which regenerates and diffs.

### `D-024` — Agent data source and curation

The generator reads `subagents/` only — upstream v2.7.0 made it PRIMARY and left
`agents/` a backward-compat shim. The 133 source files carry 130 distinct slugs, so
three collisions are curated in code: `infrastructure-maintainer` is one role filed
twice (operations copy removed), while `customer-support` and `tutorial-engineer`
are different jobs sharing a label (renamed `support-ticket-handler` and
`educational-content-writer`). Result: **132 entries**.

Curation tables are keyed by *source path*, so an upstream move fails the build
rather than mis-applying a rename to the wrong agent. A new collision is a hard
error and never an auto-suffix — deciding "one role or two" means reading both
files, which is a human's call. A curation key matching nothing is also an error,
so the tables cannot rot in place.

**Before renaming or removing an agent, grep `commands/`** — 19 of the 24
orchestration commands reference agents by id, covering 26 of the 132.

> **These counts are disputed and have not been reproduced.**
> `docs/agent-directory.md` gives different numbers for the same fact, and a recount
> at the current pin matched neither. Open conflict §4.12 in
> `specs/meta/spec-drivers-v0.2.5.md`, issue #113. The instruction stands whatever
> the count is: grep `commands/` rather than trusting a number.

### `D-018` — Licence: MIT, © 2026 Adam Schoen

Matches the attribution the project already carries and the upstream
`claude-code-tresor` licensing. Resolves the former Apache-2.0 `LICENSE` file
versus MIT-in-documentation conflict in favour of the documentation.

## 3. Repository policy

### `D-021` — The submodule gitlink tracks `10110TLGP/dev`

Confirmed by the owner and by `origin/HEAD`, which points at it — that branch is
the fork's default. Bumps fast-forward the pin to its head. Recorded because "is
the pin stale?" is unanswerable without knowing the target branch, and the answer
previously lived only in someone's head.

### `D-022` — The fork's `10110TLGP/main` is reserved as its release branch

Not abandoned, not a pin target — dormant until the fork has a `release.yml` and
tagged releases, at which point it follows the same model as this repo: cut
`dev` → `main`, tag, back-sync. Until then the pin follows `dev` (`D-021`).
Recorded so nobody prunes it as stale or pins to it expecting the newer commit.

### `D-023` — Merge commits, not squash

Squash and rebase merging are **disabled in repository settings** (verified
2026-07-26). Deliberate, not a default: the squash-only rule was inherited from
`alirezarezvani/claude-code-tresor`, was never chosen for this project, and squash
merging has caused the owner real problems on other repositories. Merge commits
keep a PR's commit series intact and bisectable.

Consequences: `dev` is not linear, so "Require linear history" must stay off — it
would block every merge — and reverting a merged PR needs `git revert -m 1`.
**Do not switch to squash on a linter's or a bot's suggestion.** That is precisely
how the wrong rule arrived; see
[`../../specs/branching-strategy.md`](../../specs/branching-strategy.md) §9.

### `D-029` — Bridge agent store

The bridge maintains its own copy of agent definitions at runtime, decoupled from
the `claude-code-tresor` submodule. A sync module copies from
`claude-code-tresor/subagents/` into `bridge/agents/`; at runtime the bridge reads
only from its own store. Store format is initially `.md` files, with an upgrade
path to a structured store (database, wikilink markdown, gbrain-style index).

Passes the §1 scope test: replacing the frontend changes nothing about how the
bridge loads agent definitions. Registered in Sprint 4 (`specs/sprint-4-charter.md`
§1.4) and implemented there: T3a is `bridge/sync.py`, T3b is `bridge/agents.py`.

### `D-030` — PR review round bounds — `SUPERSEDED` by `D-031`

**Superseded in v0.2.14 (`PLZG-274`, owner instruction 2026-10-09). Kept as the
record; do not apply it.** It read: minimum 2 rounds of reading and replying to
bot/human review comments before merge; maximum 3 rounds before deciding to merge,
close the PR, or revert to draft and elevate to the owner; security findings,
branch-protection failures and ticket-linked blockers exempt from the max.

Origin: PLZG-199 review, where one round of reading missed a fixable finding
(symlink-follow in `/tmp` cache rebutted instead of fixed).

Why it went: a count of rounds measures neither thing it was meant to. The minimum
held a small, finished change open for a second pass no reviewer had anything to
say in, and the maximum put a clock on findings that deserved an answer. What the
PLZG-199 failure actually needed was every finding answered properly, and that is
what `D-031` asks for directly.

### `D-031` — Merge when every review thread is resolved; the agent merges

**The agent working a PR into `dev` merges it once every condition below holds.
The number of review rounds is not a condition, in either direction.** No owner
merge is needed, and a PR is not held open waiting for one.

1. **Checks.** Every required status check is green on the head commit, and no
   other CI job is failing for a reason the PR caused.
2. **Reviews have landed.** The review runs triggered by the head commit have
   finished, and all three review surfaces — inline comments, conversation
   comments, review bodies — have been re-read since the last push.
3. **Every thread is resolved.** Each inline thread carries a reply and is marked
   resolved, and each conversation comment and review body that raises a point has
   a reply. Machine check for the threads: the PR's GraphQL `reviewThreads` has no
   node with `isResolved: false`. GitHub enforces this part — the `dev` ruleset
   requires conversation resolution since 2026-10-09 — so an open thread blocks
   the merge button, and resolving a thread without answering it is the breach.
4. **Each resolution is one of three things**, said in the reply:
   - **Fixed** — the commit that fixed it.
   - **Rebutted** — a concrete technical reason, verified against the file rather
     than the comment.
   - **Deliberately not fixed now** — the reason it does not affect the work this
     PR exists to do, plus the `PLZG` ticket that carries it if anything is owed
     later. A valid finding outside the PR's concern is resolved this way rather
     than by growing the PR.

**"Not fixed now" is a resolution, not an exit.** It answers a finding that is
beside the PR's purpose; it does not answer one about whether the change is
correct. A reply that only says "out of scope" or "later" has not resolved
anything. **Three kinds of finding cannot be resolved this way** and run until
fixed or elevated: security findings, a failing required check, and anything the
PR's own ticket names as acceptance.

**What still goes to the owner.** A disagreement the agent cannot settle on the
technical merits, and any call about scope or product: reply on the thread that it
awaits the owner, leave the thread open, and do not merge. So does anything a
charter or ticket reserves to the owner by name, such as accepting evidence the
owner has to read.

**Out of scope: `dev` into `main`.** The instruction was about PRs into `dev` and
said nothing about releases, so this decision does not extend to them. Who merges
a release is undecided here and unchanged in practice — the owner has made every
one — until the owner says otherwise.

Origin: owner instruction, session of 2026-10-09 (`PLZG-274`), after Sprint 6 —
whose charter had the loop open PRs and never merge them, so four finished PRs
waited on one person. Supersedes `D-030`.

Passes the §1 scope test: review process is frontend-agnostic.

### `D-032` — The board follows the work; the agent moves it

**Jira is moved at the moment the thing it describes happens, by the agent doing
the work — not afterwards and not by the owner.**

| Event | Board change |
|---|---|
| A sprint's first task starts | The agent starts the Jira sprint |
| Work on a ticket starts (its branch is created) | Ticket to `In Progress` — the branch automation does this; the agent does it by hand if the rule did not fire |
| The ticket's PR is merged and its acceptance command exits 0 | The agent moves the ticket to `Done`, with the evidence in a comment |
| Every ticket in the sprint is `Done` and the sprint's close gate exits 0 | The agent closes the Jira sprint |

Starting and closing a sprint are **pre-authorised** by this decision. A loop
plan or skill that routes "destructive or irreversible" actions to a human does
not catch them; nothing else about that escalation rule changes. `Done` still
needs verify evidence, and a sprint with an open ticket or a red close gate is
not closed — the agent reports what is open instead.

Why: Sprint 6's sprint sat in `future` in Jira for the whole of its work, because
starting it was the owner's step. It was started and closed in the same minute
on 2026-10-09, so Jira's sprint report shows none of the flow. A board that
moves late records when someone remembered, not when the work happened, and the
flow measures in [`../delivery-coordinates.md`](../delivery-coordinates.md) are
built on those timestamps.

Charters written under `D-028` may still set per-sprint policy — WIP caps, retry
budgets, what the owner must read — but not reassign these transitions back to
the owner without saying why.

Origin: owner instruction, session of 2026-10-09 (`PLZG-274`). The ids these
transitions act on are defined in `DELIVERY-COORDINATES` (`D-026`), not here.

Passes the §1 scope test: when the board moves has nothing to do with the frontend.

### `D-034` — Domain execution is asynchronous with buffered results

**Owner ruling, 2026-10-18:** NPC conversations are synchronous with timeout
protection (`DESIGN-25D` `D-033`, superseding `D-006`); domains execute
asynchronously, with buffered results and the existing turn/budget caps. Domain work can continue while focus
is elsewhere. This records the intended distinction already represented by the
backend; it does not add streaming, authenticated ownership, restart recovery or
Godot domain controls. Those client controls and live proof remain M12 work.

The ruling resolves the former unqualified synchronous-bridge mismatch in
[`SPEC-DRIVERS-025` §4.13](../../specs/meta/spec-drivers-v0.2.5.md).
The M10 defaults in `D-035` retain 20 domain turns and a USD 1.0 budget.

### `D-035` — Centralized non-secret bridge configuration (M10)

**Approved policy, not a runtime completion claim.** Ratified from the
owner-approved `BRIDGE-PLATFORM-DESIGN` §5 on 2026-10-18.

Use a committed, non-secret `bridge/config.json` containing defaults. Built-in
defaults are the fallback; the default JSON file, or the file selected by
`BRIDGE_CONFIG_PATH`, overlays them; documented `PLAZA_<KEY>` environment overrides
win last. An explicitly selected missing/unreadable file, invalid JSON, unknown
key, unsupported version, wrong type or invalid bound fails startup with a useful
setting-specific error. Resolve relative LOG_DIR paths against the selected
configuration file's directory. Read settings once at startup; restart to reload.

The following is the approved complete initial settings set for implementation:

```json
{
  "CONFIG_VERSION": 1,
  "HAIKU_MODEL": "claude-haiku-4-5",
  "SONNET_MODEL": "claude-sonnet-4-6",
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

Model assignments use explicit provider IDs. These values are current defaults,
not a claim about the latest available release; confirm any replacement ID with
the provider before changing it. Both engines resolve their selected tier through
the same config. Agent Markdown `model:` frontmatter remains prompt data and does
not silently override execution settings. Per-agent model overrides can be added
in a later schema if a concrete workflow needs them.

Validate positive numeric limits, finite budgets/timeouts, boolean transcript
enablement, INFO/DEBUG/WARNING/ERROR log levels, and the supported haiku/sonnet
tiers. CONTEXT_MAX_MESSAGES is an even integer of at least 2 to preserve complete
exchanges; it is independent of transcript retention. Require
4096 ≤ record bytes ≤ file bytes ≤ total bytes. Age is a positive integer in days.
Do not accept credentials in this config or write them into the effective-settings
manifest; continue using existing environment credential bindings. No guessed
model IDs, automatic upgrades, or model fallback after an API error.

### `D-036` — Bounded local JSONL archives and diagnostics (M10)

**Approved policy, not a runtime completion claim.** Ratified from the
owner-approved `BRIDGE-PLATFORM-DESIGN` §§4/6 on 2026-10-18.
Keep model context, client display history, recorded transcripts, diagnostic events
and SDK execution sessions distinct. Changing transcript retention must not trim
live prompt context, reset a conversation, or delete authoritative workspace state.
Use append-only JSONL for transcripts and Python standard logging for diagnostics.
JSONL provides an inspection archive, not automatic conversation restoration or a
second authoritative history. M10 local project labels provide no authentication
or multi-user isolation. Durable application state remains separate M13 work.

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
Never invent a provider session ID for a Messages API conversation. Serialize
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

All three decisions pass the §1 scope test: replacing the frontend leaves domain
execution, settings and recording policy intact. `D-005` continues to require zero
bridge awareness of rendering concepts.

## 4. Adding a decision here

Same procedure as any entitled document —
[`../../specs/meta/META-SPEC.md`](../../specs/meta/META-SPEC.md) §8 — plus one
scope check: run the frontend-replacement test in §1 first. A decision that dies
with the 2.5D prototype belongs in [`2.5D-RPG-Prototype.md`](2.5D-RPG-Prototype.md),
not here. Add the `D-nnn` to this file's `decides:` list and to
[`../../specs/meta/decision-register.md`](../../specs/meta/decision-register.md);
`scripts/validate_specs.py` fails the build if the two disagree, and now also fails
if a document declares `decides:` without an authority licensed to originate.

*Doc set version: 0.2.15 · Last updated: October 2026*
