# M13 decisions and questions for Adam

**Status: working review queue; not a specification, decision register or implementation approval.**
**Resume from the live [PR #376 state](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/pull/376):** checkpoints below describe their capture times. When that PR is merged and #373 closed, phase 1 is delivered; continue with the bounded persistence design rather than repeating extraction or branch reconciliation. M13 remains In Progress.

Prepared October 23, 2026 (America/Los_Angeles). Tracks reconciliation for [GitHub #373](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/373) and PLZG-290. No new D-numbers are assigned here.

## Historical instructions — research reconciliation round (completed)

Reconcile the published docs/research and planning histories with the latest M12 fixes on `origin/dev`. Preserve research and recorded owner answers. Do not implement the store/backends, open a PR, change locked decisions, or invent new planning decisions in this round. Keep explicit questions where governing text or agent-authored absolutes conflict with the direction of the project.

Temporary integration isolation is an operational boundary, not the long-term architecture or delivery destination. The next session should review these entries with Adam, reconcile approved decisions across their entitled sources, then open the appropriate PR to `dev`. Implementation follows that alignment.

This file is a non-authoritative working queue. The entitled decision register remains [specs/meta/decision-register.md](specs/meta/decision-register.md); the governing conflict protocol remains [META-SPEC](specs/meta/META-SPEC.md) and the canonical open-conflict register remains [spec-drivers §4](specs/meta/spec-drivers-v0.2.5.md). This file does not silently supersede either. Once approved, actionable governance conflicts must be recorded/resolved there through the normal process.

## Verified branch inventory and interruption checkpoint

Observed remotely before reconciliation (historical tips; see the resumed checkpoint below):

| Ref | Observed tip | Finding |
|---|---|---|
| `origin/dev` | `971ac2fa70515bbd20f0627a5b7e2a766a7288c2` | Latest M12 readiness/clipboard/runtime fixes; M12 acceptance is now Done in Jira. Some repository summaries still describe acceptance as open. |
| `origin/docs/add_notes_Docs` | `f37bff31a2aeae2e716e73b841a19dae3c89489a` | Imported UI notes, research snapshots, diagrams and owner-local config changes; 1 unique commit and 21 commits behind dev at inspection. |
| `origin/plaza/workspace-integration` | `122cbc74e9b76c751b9cf57479bf0c1c8a1d7e46` | Research, proposed store/backend plan, recorded owner answers, and SQLite amendments to two M12 documents; 4 unique commits and 48 commits behind dev at inspection. |
| `origin/docs/cloudflare-durable-objects-research` | `47373a365b9facc1aa01a17d11009377f63e743a` | Ancestor of workspace-integration; retain its provenance. |
| `origin/feat/373-domain-session-store-extraction` | Not found | Both remote-ref inspection and GitHub branch lookup found no such remote branch. Adam subsequently confirmed the feature branch is laptop-local and its work was pushed to plaza/workspace-integration; that is the approved planning target. |

The remote fetch configuration originally selected only dev; the named research/integration refs were explicitly fetched before comparison. A successful generic fetch alone would not have refreshed them.

### Historical interruption checkpoint

Before the environment recovered, in the existing isolated cloud worktree, a local branch `docs/PLZG-290-reconcile-notes` was created from the docs tip above. A `--no-commit --no-ff` merge of dev applied without textual conflicts. Before any merge commit/push, the execution environment became unavailable. The existing top-level `work` checkout was not changed. No remote merge, rebase, force-push, PR or implementation was performed at this checkpoint. This working file is being saved directly to the docs branch through the GitHub connector so the review queue survives the environment interruption.

### Research-reconciliation checkpoint — both histories reconciled

Adam confirmed `origin/plaza/workspace-integration` as the planning target. The workspace recovered. The interrupted staged merge was saved as a patch, aborted without discarding unrelated work, and rebuilt after incorporating remote checkpoint `421225e` into the local docs history. This docs reconciliation merges dev `971ac2f` without rewriting ancestry. Runtime/config/UI/tests/dependencies now match dev; the old owner-local `bridge/config.json` edits remain in original commit history, but are not the reconciled product defaults. Sixteen imported Markdown files were individually indexed as non-authoritative provenance/research; vendor snapshots and copied notes were not edited.

Docs reconciliation was validated and pushed as merge `3604d05` on `docs/add_notes_Docs`. That updated docs history is now merged into the confirmed planning history `plaza/workspace-integration`, preserving both original parents and all research commits. Both resulting histories contain dev `971ac2f`; the planning branch is the combined integration candidate for the next session, while the docs branch remains the narrower notes-import history. No rebase, force push, dev update, new PR or implementation is part of this round.

Mechanical integration findings: runtime/config/UI/tests/dependencies and all historical acceptance artifacts match dev byte-for-byte; the decision register, platform decisions, meta-spec, storyboard and roadmap are unchanged from dev. The two SQLite amendments are **pre-existing planning-branch edits from `122cbc7`**, preserved with their existing provenance, not newly authored/ratified by this merge. Their governance propagation remains Q01. Registry changes are individual exemptions for 30 imported non-authoritative Markdown files; governed authority rows and doc-set version remain unchanged. The twelve duplicated raw snapshots are byte-identical and retained at both paths; the lowercase research index is the reading entry point. Research/plan annotations expose the review gate without changing the recorded owner answers or phase tasks.

Final validation, published tips and issue handoff are recorded in #373 and PLZG-290. The open questions below are the next session's work; completing a merge does not resolve a product question.

## Recorded owner direction: retain, do not repeatedly ask

The planning branch's [owner-answers section](docs/superpowers/plans/2026-10-23-domain-session-store-execution-backend.md#owner-answers-adam-2026-10-23---supersede-the-open-questions-above), commit `47373a3`, and the existing #373 comment record these answers:

- SQLite accepted for the later local store; three Markdown project notes remain a separate responsibility.
- Resume application session identity across bridge restarts unless intentionally ended by the user or bridge; persist end state and attribution.
- Support subscription OAuth and API-key auth paths. Actual remote credential policy/feasibility remains to be established.
- Hetzner is a second host in mode B, built with B; sessions need host identity and unavailable-host behavior.

These are recorded answers, not findings that the platform is already implemented. Preserve them. Next-session review should settle remaining semantics and governance propagation, rather than re-ask an answered question because an older paragraph remains above the answers.

## Registered decisions and governing claims needing reconciliation

State vocabulary: **clarify scope** means no new product decision is presumed; **propagate recorded answer** means owner direction exists but entitled documents/semantics need alignment; **Adam decision** means an unresolved material choice; **verify claim** means inspect evidence before treating the statement as fact.

| ID / state | Source and actual scope | M13 issue to settle | Next-session action / evidence |
|---|---|---|---|
| Q01 — clarify scope / propagate recorded answer | [M12 design §3](docs/superpowers/specs/2026-10-21-m12-domain-execution-design.md), [M12 plan](docs/superpowers/plans/2026-10-21-m12-project-execution.md), and [roadmap M13](specs/roadmap.md): M12 adds no database; M13 already names SQLite. | Do not turn a milestone limit into “Adam never permits databases.” Planning commit `122cbc7` already appends owner-attributed SQLite scope amendments to both M12 documents, outside dev. | Preserve those edits as existing branch history; compare with entitled D-038/D-039 sources and roadmap before the future PR. Confirm intended wording/ratification rather than silently treating integration as new approval. |
| Q02 — propagate recorded answer / Adam decision on exact semantics | [D-034 / D-039](specs/meta/decision-register.md), M12 generation/replay rules, roadmap M13: no automatic SDK recovery is implied by existing state. | Stable application session identity is distinct from reviving an SDK process or resuming a Claude provider session. What survives restart, Stop, explicit End, cancellation, crash and cleanup uncertainty? | Preserve the recorded “resume unless intentionally ended” answer. Define which current controls mean End, who may set it, cursor/generation rules, and SDK start behavior; update all entitled sources together. Do not equate recorded history with permission to run tools. |
| Q03 — Adam decision | D-038 owns one configured project per bridge and one worktree per project/department, with immutable owned branch and session-length reservation. The plan adds `host_id`. | How are project/domain/session/host identities combined across laptop and Hetzner? Is a DO keyed by domain, project+domain, or session? The plan says one per domain in places; analysis says per session. | Define the stable key and writer/lease authority, host unavailability and split-brain behavior before relay work. Do not weaken local Git/memory readiness on reconnect or host handoff. |
| Q04 — clarify scope / Adam decision for remote transport | [D-015](docs/designs/platform-decisions.md): local Python WebSocket endpoint. [D-005 / D-020](specs/meta/decision-register.md): UI independence, interchangeable clients. | Remote authenticated relay needs an explicit transport/trust boundary. The analysis incorrectly calls D-005 a local-Godot assumption. | Preserve D-005/D-020; propose any remote endpoint/auth/TLS changes against D-015 in its entitled home. No frontend-specific bridge awareness is required by a new backend. |
| Q05 — Adam decision on guarantee | D-038/D-039 protect workspace ownership and project memory; worktrees are not a host sandbox. [Roadmap M14](specs/roadmap.md) owns broader concurrency/isolation. | A durable queue, DO single writer or file-based lease is not filesystem/network/process containment. The owner wants containment considered before higher-risk real work. | Set the required containment boundary and sequence relative to persistence/relay. Define permitted local/remote access and failure recovery. No provider or sandbox is selected merely by preserving a research page. |
| Q06 — clarify scope / Adam decision on stored data | [D-036 / D-039](docs/designs/platform-decisions.md): diagnostic archives and three project notes are different stores. M13 application state is not recovered from debug logs. | Proposed event packets, prompts, output, memory, credentials and source snippets need explicit classifications, bounds and retention. “No prompt bodies” does not define what arbitrary output may contain. | Define local and mirrored schemas, retention/deletion/access/redaction, and which contents may leave each host. Keep TODO/HANDOFF/PROGRESS separate from the domain event store and preserve visible persistence failures. |
| Q07 — verify claim / preserve guard contract | [Guard evidence guide](QUICKSTART.md#m12-live-evidence-and-desktop-checks), `bridge/tool_guard_evidence.py`: actual twelve-source/runtime/mode-bound evidence. | Phase 3 says existing guard evidence should still pass after backend extraction. A change to a guarded source can invalidate those fingerprints even if behavior is intended to remain equivalent. | Determine affected guard sources per phase; run fresh bounded evidence when required. Never rehash historical observations to pass. Both permission modes and selected live mode remain distinct evidence. |
| Q08 — clarify scope | [D-007 / D-033 / D-034](specs/meta/decision-register.md): frontend typewriter, complete extras replies and asynchronous buffered domain results. | Store extraction does not introduce provider streaming. Analysis discusses per-chunk latency; the proposal includes dense output IDs and emit ordering. | Define an event precisely, preserve current packet/cursor/cap behavior in phase 1, and treat any actual streaming/protocol change as a separately approved decision. |
| Q09 — clarify scope / preserve runtime policy | [D-037](docs/designs/platform-decisions.md): Claude Code via Agent SDK default; explicit API-key-only Messages API opt-in, no fallback. | This is not a blanket “SDK must always be OAuth-only” rule. Supporting SDK OAuth and API keys locally does not prove either works or is permitted remotely. | Preserve existing local policy and the recorded desire for both auth paths. Verify remote policy, injection and secret lifecycle before cloud credentials or deployment. No automatic auth/backend fallback. |
| Q10 — clarify scope | [D-029](specs/meta/decision-register.md): bridge-owned agent-definition store with a future structured-store path. | Agent-definition storage, project notes, domain replay state and execution backends are different responsibilities despite all being called “store.” | Identify each store's ownership and schema; do not use D-029 to authorize unrelated persistence or make agent definitions depend on a cloud provider. |
| Q11 — Adam decision / sequencing | [Roadmap M13–M15](specs/roadmap.md): local structured state, broader isolation/concurrency, authenticated hosted durability; provider still unselected. | Proposed A → A+B → C and mandatory Hetzner-in-B expand the roadmap. Security/isolation may need earlier work or combined milestones. | Review sequencing and acceptance gates with Adam. Record provider direction separately from feasibility and selection. Do not let the older “optional VPS in phase 5” paragraphs override the later owner answers. |

## Agent-authored statements, stale summaries and delivery questions

| ID / state | Verified statement / evidence | Reconciliation needed before implementation |
|---|---|---|
| Q12 — verify claim | Research analysis says “Godot is the only client” and treats walking away/return as wholly unmet. Existing M12 includes plain-client testing, background/refocus and replay while the bridge stays alive. | Correct the analysis's baseline after comparing with current dev; isolate the genuine missing behavior: restart/host durability. Preserve the original snapshot/provenance when annotating it. |
| Q13 — propagate recorded answer | The plan's concluding owner answers supersede its earlier open questions. Earlier phases still say SQLite must be asked again, VPS is optional/later, and contain prior recommendation text. | Make the eventual reviewed plan internally consistent using the recorded answers, retaining an audit trail. Do not treat this round as permission to introduce new architecture decisions. |
| Q14 — verify claim | #373's delivery section currently targets `plaza/workspace-integration`; Adam now explicitly says integration isolation is temporary and the next session should open a PR to dev after review. | Update the task and handoff after the actual target branch is confirmed/reconciled. Do not implement phase 1 or open a PR in this round; do not turn temporary isolation into a permanent ban on dev integration. |
| Q15 — historical fact update | Current dev summaries in CLAUDE/QUICKSTART/roadmap still describe M12 as awaiting laptop acceptance. [PLZG-289](https://tasteslikegood.atlassian.net/browse/PLZG-289) is now Done with the owner's filled checklist, 29/29 local guards in each mode and clean shutdown evidence. | Queue consistent delivery-status updates for the next reviewed PR, preserving original evidence/source bindings. This is a fact reconciliation, not a new platform decision. Do not restamp historical paid reports. |
| Q16 — imported provenance / review before PR | `Docs/files/` (capital D) contains UI-copied notes, research snapshots, diagrams and raw Cloudflare pages. `docs/research/cloudflare-durable-objects/` carries another research collection. The archived `arch_convo_full.md` is copied selectable UI text, not a runtime transcript. | Preserve provenance and explicitly distinguish copied text from logged execution. Completed: all twelve raw snapshots match byte-for-byte; the lowercase research README is the reading entry point, with both archives retained. Continue the pre-PR privacy review; do not silently edit vendor snapshots or delete research. Review imported artifacts for owner-local/private material before future PR publication. |
| Q17 — integration mechanics | The docs commit changes `bridge/config.json`: owner-local workspace path, permission bypass true and a larger conversation token cap. Those are not research documentation. | Recommended reconciliation: use dev's product defaults in the reconciled tree and preserve owner settings in original commit history/local setup guidance; do not accidentally ship laptop paths or alter execution behavior in a docs-only round. Record the actual choice when applied. Docs reconciliation selects dev defaults; original owner-local settings remain recoverable in commit `f37bff3`. This is a mechanical integration choice, not a new permission or settings policy. |
| Q18 — validator finding | The conflict-free preliminary docs+dev merge fails `python3 scripts/validate_specs.py` with 16 imported Markdown paths under `Docs/files/` missing from the document registry. | Register each imported non-authoritative snapshot individually with a provenance-based exemption, or add proper frontmatter if it truly belongs in the governed set. Completed: the docs merge indexed 16 paths; the planning merge indexed 14 more. The validator passes without changing authority or the doc-set version. Further research/decision questions remain open. Do not disable the validator, create blanket exemptions, grant imported text decision authority or bump decision versions just to pass. |

## Historical research-reconciliation checklist

- [x] Confirm the planning ref with Adam: `origin/plaza/workspace-integration`; fetch all named remote refs explicitly.
- [x] Preserve and rebuild the interrupted local merge, incorporating remote checkpoint `421225e` before further integration.
- [x] Merge dev `971ac2f` into the docs history without rewriting ancestry; retain dev product defaults and index the imported snapshots. Spec validation passed before publication: 23 governed documents, doc set 0.2.18.
- [x] Merge updated docs history `3604d05` into the confirmed planning branch, retaining research commits, recorded owner answers and pre-existing SQLite amendments.
- [x] Check byte identity of runtime/config, tests, dependencies, UI and evidence against dev `971ac2f`; no implementation change remains.
- [x] Resolve registry coverage and check added internal file links without changing decision authority; preserve all earlier acceptance artifacts unchanged.
- [x] Classify Q01–Q18 by scope clarification, recorded-answer propagation, verification or remaining Adam decision; integration resolves Q17, snapshot comparison in Q16, and registry coverage in Q18; privacy review and product choices remain open. Product choices remain open.
- [x] Publish the validated reconciled histories without force pushing; exact old/new tips and dev ancestry are recorded in #373 and PLZG-290.
- [x] Record the final branch/ref state and next-session review gate in #373 and PLZG-290; the task remains open and unimplemented.
- [ ] **Next session with Adam:** settle unresolved product choices; propagate approved rulings through entitled source docs, decision register, roadmap, plans, summaries and canonical conflict register; validate the whole set.
- [ ] Then open the appropriate PR to dev. Start M13 implementation only after the planning/governance alignment is approved.

## How to maintain this file

For each new item, cite the exact document/heading or D-number, quote the narrow conflicting claim, distinguish a current rule from historical evidence and an agent's extrapolation, state what owner decision is actually missing, and list every document that must change together. Record the eventual owner answer and implementing commit. Do not mark an issue resolved merely because it was discussed.

Completed rows stay as provenance with links to the canonical resolution. This file is a review queue, not a second canonical decision register.

## Additional reference — October 24, 2026

[Brayden/chat source review](docs/research/cloudflare-durable-objects/brayden-chat-review.md)
adds a concrete Workers/SQLite DO/React Router comparison for Q02–Q09 and Q11.
It demonstrates per-channel durable message storage plus a shared authorization/
notification DO; it does not demonstrate execution isolation or cursor-based
agent recovery. The review records socket-memory/hibernation, pagination,
persist/notify, initialization and auth findings at a pinned external commit.
No open owner decision is resolved or changed by adding this reference.

## Cloudflare plan and messaging facts — October 24, 2026

Owner confirms an existing Workers Paid subscription at $5/month plus usage.
This records existing budget/account context, not a universal prerequisite:
free-tier experiments are possible, and some individual products have their own
plan requirements. It does not prove remote Claude execution/auth feasibility
or authorize deployment. Account subscription
and quotas were not independently read from the authenticated dashboard.

Official documentation was rechecked using the Cloudflare docs connector and
public pages requested with `Accept: text/markdown`:

- [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/):
  paid includes 10M requests and 30M CPU milliseconds/month. Free daily quotas
  are a different plan, not additive to the paid allowances. Per-invocation
  maximum CPU time is distinct from aggregate included usage and container runtime.
- [DO pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/):
  paid includes 1M requests and 400,000 GB-s/month; duration and SQLite storage/rows
  have their own meters. Hibernation eligibility matters for socket-heavy costs.
- [Containers pricing](https://developers.cloudflare.com/containers/platform/pricing/):
  paid includes 25 GiB-hours memory, 375 vCPU-minutes and 200 GB-hours disk/month,
  with resource-specific overages. Containers included does not mean unlimited
  containers at no additional cost. Claude/provider usage is separate.
- [Queues architecture](https://developers.cloudflare.com/queues/reference/how-queues-works/)
  and [delivery guarantees](https://developers.cloudflare.com/queues/reference/delivery-guarantees/):
  asynchronous work delivery, at least once, no guaranteed publication ordering.
  One configured consumer path can scale out; HTTP pull permits multiple concurrent
  workers. This is not independent topic subscriptions each receiving every event.
  A retryable agent job therefore needs deduplication/idempotency and host affinity.
- [Queues pricing](https://developers.cloudflare.com/queues/platform/pricing/):
  1M operations/month included on paid, then $0.40/M operations. A normal small
  message consumes write/read/delete operations (typically three), not one.
- [K2](https://developers.cloudflare.com/k2/) and
  [its guarantees](https://developers.cloudflare.com/k2/reference/delivery-guarantees/):
  a currently documented public-beta durable log on Workers Paid, with independent
  subscriptions and at-least-once delivery. Closer to a Pub/Sub-style fan-out log
  than Queues; availability, retention, beta terms and pricing need evaluation
  before selection. No ordering/deduplication guarantee should be inferred.

The reviewed near-term sequence is unchanged: owner/governance review, align the
approved docs, PR to dev, then the local in-memory store extraction. Later choose
whether any asynchronous dispatch/fan-out service is actually required. Queues
or K2 would still require a designed session/replay/retention contract and would
not itself provide workspace guards or an execution sandbox. K2 as an event-log
backend is an option to evaluate, not a selected implementation. No new
vendor/product decision is made in this note.

Next owner question under Q02: map existing Stop/cancel behavior versus explicit
intentional session End onto the recorded stable-session/resume requirement.
A possible design is Stop current execution while retaining the session, with a
separate explicit End; that is a recommendation to discuss, not a settled answer.

## Owner clarification and immediate tooling priority — October 24, 2026

Adam confirms the Workers Paid month starts October 24 and the $5 is already
spent. Do not turn account-plan status or hypothetical overages into a development
pause. Use actual product-specific usage and included allowances to estimate the
month-end cost. Check-ins are scheduled for three days and one week from this
clarification (October 27 and October 31 Pacific). How free allowances are
accounted for within the paid allocations should be checked against actual
billing/usage, not invented or assumed to stack. The advertised $0.30/M Worker
request rate is not a universal price for DO, container, CPU or queue operations.

**Immediate requested work:** a local UUID minter and persistent PR-lifecycle
issue/finding state, followed by a design for shared Cloudflare DO state analogous
to relay mode B. The goal is stable identity and continuity across agent sessions
and after a PR closes, including uniquely identified follow-up issues. Adam hopes
that shared tooling can exercise a live DO-backed session-state service before
Plaza's later B/C implementation, supplying operational experience.

Inspection found the checked-in `.claude/hooks/pretooluse-pr-review-nudge.sh`
queries current GitHub review-thread state; `.claude/pr-workflow.md` requires
follow-up tickets for deferred work. No dedicated finding-UUID minter or durable
PR-lifecycle ledger was found in those repo files. Existing project-memory UUIDs
are not evidence of this tooling being implemented.

**Scope confirmed by Adam:** shared tooling for all projects, Plaza first consumer.
The existing home is `adamtasteslikegood/codex-pr-review-gate-cc`; its issue #29
already specifies local persisted lifecycle UUIDs first (A), then a DO store
evaluation (B). This is not a new Plaza-only PR hook or Python/SQLite service.
This is workflow/tooling state and must not automatically be equated with the
in-game DomainSessionStore or overwrite its identity/replay contract.

Required outcome: mint an identity once for a logical record and retain a durable
mapping so later sessions reuse it; record originating repo/PR/review evidence,
state/disposition and linked GitHub/Jira follow-ups; retain records after PR
closure. A later relay must preserve those identities rather than minting them
again. Exact schema, UUID version, storage location, concurrency/idempotency,
reconciliation rules, gate integration and migration need a bounded design once
component ownership is settled. These are requirements/review notes, not new
canon, an implementation design approval or a deployed service claim.

### Shared gate handoff

Located and read the existing shared gate repository, its working rules and
issue [#29](https://github.com/adamtasteslikegood/codex-pr-review-gate-cc/issues/29).
The issue reproduces unrelated same-ordinal findings in two checkout roots
adopting the wrong external issue after a lost response. The local increment is
a random `lifecycleId` persisted in the existing TypeScript plugin record before
filing, retained across retries and changed on fresh/reset lifecycle; exact
UUID-bearing filing marks replace ordinal/PR/generation-only adoption. Earlier
marked issues must not be adopted through title fallback. No new local database
or generic UUID server is needed for A. B remains the shared authenticated DO
ledger/driver-lease design, not implemented here.

A bounded local design is committed in the separate gate repo's isolated
`fix/29-lifecycle-identity` worktree (commit `449c6ce`), at
`docs/superpowers/specs/2026-10-24-lifecycle-filing-identity-design.md`, pending
owner design review. No product implementation or gate PR has been made yet.
Preflight also found the gate's actual plugin-test harness/generated types are
not provisioned in this cloud checkout; the Plaza SDK CLI does not expose that
repo's plugin-test command. This is a verification setup issue to solve/report,
not a passing test result and not a reason to invent a substitute harness.

## Active Plaza next step — October 25, 2026

The owner directs this project to continue M13–M15 if it does not actually depend
on shared gate #29. Remote issue/source inspection confirms that #373's local
in-memory extraction has no dependency on the shared UUID minter, DO service or
Cloudflare account. Keep gate #29 in its separate repository; do not serialize
Plaza development behind that tooling task.

The [bounded #373 design](docs/superpowers/specs/2026-10-25-m13-memory-store-extraction-design.md)
was approved by Adam on 2026-10-26 for planning and implementation. It preserves current replay/admission/retention and
packet contracts, including the retained duplicate-request lookup that shares
the existing deque. The [bounded implementation plan](docs/superpowers/plans/2026-10-26-m13-memory-store-extraction.md)
records the extraction, verification and continuation state. The broader Q02–Q11 questions remain relevant to persistence and
remote execution, not prerequisites to extracting an unchanged in-memory store.
No new canon, persistence, recovery or provider decision is ratified by this note.


## #373 implementation checkpoint — October 26, 2026

The in-memory boundary is implemented in `bridge/domain_store.py` and consumed
by `DomainSession`. The store owns append/ID allocation, output-text UTF-8 byte
and count retention, retained-request lookup and replay metadata. Execution,
checkpointing, snapshots, truncation and delivery remain in the session. Native
execution used one fresh whole-change review; no correctness findings were raised.

This is phase 1 only. Phase 2 still waits for phase-1 merge and a separately
approved durable lifecycle/recovery contract. Q02–Q11 and the broader governance
alignment queue remain open; the extraction does not settle those questions.
The shared gate repository's #29 remains independent. Final verification and
exact tested versions are recorded in the implementation plan.


## Current delivery checkpoint — October 25, 2026 Pacific

Adam authorized the next steps after #373 implementation. This supersedes the
historical research-only hold above for the bounded extraction and its dev PR;
it does not authorize phase 2 or silently decide the remaining product choices.
Earlier implementation records dated October 26 use UTC (October 25 Pacific).

Reconciliation for the phase-1 delivery:

- **Q01 clarified:** M12's no-database sentence limits M12. Its two branch-recorded
  SQLite amendments preserve the already recorded later-store answer. Roadmap
  M13 already calls for SQLite; D-038/D-039 are not database prohibitions. No
  locked decision or doc-set version change is needed for an in-memory extraction.
- **Q04/Q08/Q09/Q10 clarified for this increment:** D-005/D-020 remain UI
  independence, current packets remain buffered terminals, D-037 remains SDK
  default with the existing auth paths, and agent definitions/project notes/
  terminal history remain separate stores. Remote trust and auth remain open.
- **Q07 verified:** all twelve guarded sources and the acceptance file are
  unchanged by #373, and both actual runtime activation checks passed. Future
  changes to guarded sources require appropriately fresh evidence.
- **Q12 corrected:** analysis baseline is explicitly historical; existing
  plain-client/background/replay behavior is acknowledged. D-005 is no longer
  described as assuming a local Godot client.
- **Q13 reconciled:** the proposal's phase text now reflects recorded SQLite,
  stable-identity, dual-auth and Hetzner-in-B answers, labels the async interface
  as a superseded sketch, and points phase 1 to the approved synchronous design.
  Unapproved WAL/location, DO-key/replica and host/containment details remain
  proposals for bounded review, not new implementation commitments.
- **Q14 delivery resumed:** integration isolation was temporary; the next artifact
  is the PR to dev. #373 remains open until delivery completes; phase 2 waits.
- **Q15 corrected:** CLAUDE, QUICKSTART, roadmap and M12 design now distinguish
  completed owner acceptance at `971ac2f` from historical reports that were open
  at capture. M12 is Done; M13 is In Progress. Historical evidence is untouched.
- **Q16 reviewed for this PR:** imported UI text, research, diagrams and vendor
  snapshots remain in their original supplied form. The two copied chat artifacts
  are selectable UI text, not logged session transcripts. Credential-pattern and
  assignment scanning of all added text artifacts found no candidates; narrative
  audit/rotation references are not independent verification or raw key material.
  This is a bounded privacy review, not proof that arbitrary text cannot be
  sensitive. No private laptop recordings or acceptance artifacts were added.
- **Q17/Q18 remain mechanically resolved:** shipped config defaults are dev's;
  individually indexed research imports do not gain decision authority.

Remaining product decisions: Q02 generation/cursor/interrupted-work semantics
(the Stop/End split is answered below);
Q03 stable identity/DO keys/writer/host authority; Q04 remote transport/auth;
Q05 containment guarantees and sequencing; Q06 stored/mirrored data and retention;
Q09 remote credential feasibility/policy; Q11 provider and milestone sequencing.
These need the appropriate future bounded designs. Recorded owner answers are
not questions to repeat. Their unresolved details do not block phase-1 delivery.

Atlassian reconnection succeeded: PLZG-290 is In Progress with implementation
and verification comment 11509. This supersedes the earlier connector failure
as a current blocker; its original failure record remains historical.

### Q02 owner answer — October 25, 2026 Pacific

Adam selected: **“Yes — separate Stop from End session (recommended)”** in
response to the question: “For the next M13 persistence design, should Stop halt
execution and release the workspace while preserving the application session,
with a separate End session control that closes it permanently? This would mean
a crash/restart does not end the session, and reconnect alone never starts agent
work.”

Carry this answer into the next bounded persistence design. Stop must retain
the durable application session; End is a separate intentional lifecycle action.
Release still requires confirmed cleanup; uncertainty must retain existing
ownership evidence. This records a future requirement, not implemented durable
identity, a new End control, history deletion, automatic SDK recovery or approval
of the whole persistence design. Other Q02 details (execution generations,
cursors and interrupted-work representation) remain for that design.


### Dev PR and review checkpoint

[PR #376](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/pull/376)
now carries the reconciled research history, approved extraction and factual
status updates to dev. A fresh independent pre-delivery review of
`971ac2f..94aba28` found no Critical, Important or Minor issues; 21 focused cases,
123 authored links/anchors and all twelve raw snapshot pairs were verified.
Original artifact/vendor whitespace is preserved; whitespace-clean claims apply
to the authored extraction/reconciliation range, not verbatim imports.

Initial CI correctly rejected the expired October 9 board-flow snapshot. A fresh,
complete live Jira reading (three pages, 267 unique issues: 184 Done and 3 In
Progress) and board 169's empty active-sprint listing support the updated
`data/plzg-flow-snapshot.json`. Work-item age is explicitly since creation, not
cycle time. No historical sprint or M12 acceptance file was restamped, no new
aging threshold or forecast was invented, and no validator was weakened.

Review/check completion and dev merge are the remaining phase-1 delivery work.
Phase 2 still requires its bounded persistence design; the new Stop/End answer
is an input, not approval of that whole design.


The current-dev merge (`7aff235`, including publisher PR #375) preserves both
registry additions and the later live flow reading. Existing PM-tool requirements
must be installed alongside the bridge requirements for the combined test suite;
the initial local run lacked `requests` and produced 17 publisher setup errors.
Installing `scripts/pm/requirements.txt` made all 17 publisher cases pass, without
source changes. The complete combined regression is rerun before merge; its final
result is recorded on PR #376. The historical 2,013-test extraction run remains
accurate for its original baseline rather than being overwritten with new counts.

## SQLite persistence design started — October 26, 2026 Pacific

Phase 1 is delivered: PR #376 merged as `a2d340a`; #373 is closed. The
post-merge 90-case acceptance and both runtime verifications passed. Combined
regression was 2,033 tests plus 118 subtests; historical reports remain bound
to their original sources. PLZG-290 stays In Progress (comment 11512).

Adam requested the bounded SQLite persistence design. He will configure the
separate Confluence publisher's Actions token; that activation task does not
block local design work. No persistence implementation or dependency changes
are authorized by this design-start checkpoint.

Confirmed inputs: stdlib SQLite; project/repository isolation; persistent
application identity unless intentionally ended; Stop preserves that identity;
End is separate; crash/restart does not End; reconnect alone never executes
agent tools; cleanup uncertainty retains ownership evidence; three Markdown
project notes remain separate from application state and diagnostic archives.

Reconnaissance against the merged implementation:

- `bridge/domain_store.py` owns synchronous terminal-only append/lookup/replay.
  IDs and duplicate detection are bounded by retention; a fresh store is empty.
- `DomainManager._new_session` currently creates a fresh UUID after a clean Stop.
  `shutdown()` calls Stop, so durable End cannot be inferred from shutdown.
- Query admission installs `_inflight` before suspension. Existing project-memory
  preparation precedes acceptance/tools, but accepted-request state is not yet an
  authoritative SQLite record. Recovery must distinguish interrupted accepted
  work from terminal results and never silently retry it.
- Session cleanup waits for owned work, then releases only on confirmed cleanup.
  SQLite workers must participate in that drain; cancellation cannot leave an
  unowned write or a falsely clean status.
- Godot retains its domain buckets during connection uncertainty. Restored server
  identity/history discovery must support a fresh game process as well as a
  temporarily disconnected existing client; SQLite alone does not supply that UI.
- `project_files.py` anchors safe metadata operations and refuses symlinks and
  hardlinks. SQLite's own database/journal/WAL opening is a separate integration
  concern; the existing helper is not automatically a safe SQLite filesystem VFS.

Additional design items:

| ID | Design requirement / open detail | Source / disposition |
|---|---|---|
| Q19 | Pick the SQLite location, OS writer ownership and database/sidecar safety strategy; define corrupt/unsafe/full/read-only/busy behavior without silent recreation. | Existing `project_files.py`, common-Git metadata, D-038/D-039; technical alternatives not yet selected. |
| Q20 | Reconcile synchronous replay/admission with durable I/O and commit-before-publish. Treat SQLite and Markdown updates as distinct commits with honest reconciliation rather than claiming a cross-store transaction. | Approved phase-1 design explicitly deferred durable caller/ownership semantics; `domain_session.py` preparation/save/cleanup paths. |
| Q21 | Decide whether reopening supplies a bounded conversation recap to the fresh SDK runtime, or only restores visible history/identity alongside existing project notes. Any recalled content remains continuity data, not authority or a task queue. | Answered October 26: Adam selects the bounded agent recap alongside project notes. Stable identity does not by itself answer model-context restoration. |
| Q22 | Define session/history/request retention, schema migration and disk limits separately from replay's 256-entry / 4 MiB output-text window; avoid silently promising lifetime deduplication or unlimited storage. | `MemoryStore` contract and Q06. Quotas/archival details require explicit design rather than inherited assumptions. |

Next: settle the pending model-context question; compare the durable-I/O
approaches; write the bounded design with lifecycle/schema/failure/acceptance
contracts; run a fresh builder check; obtain approval before an implementation
plan or product changes. Existing recorded answers must not be asked again.


### Bounded persistence design — owner recap answer and builder handoff

Adam accepted the bounded conversation recap and asked to proceed/handoff. The
[proposed SQLite design](docs/superpowers/specs/2026-10-26-m13-sqlite-session-persistence-design.md)
covers durable identity, accepted-work recovery, explicit End, execution fencing,
minimum client restoration and a bounded deterministic recap. Q21 is answered.
The worker/cache split, sidecar-free serialized SQLite image, quotas, backend
default and protocol-version proposal are **builder recommendations**, not owner
choices or implementation approval. A fresh builder check precedes design handoff.

The Confluence environment secret is owner-reported configured. A protected-dev
publisher rerun was dispatched to verify actual activation; do not infer success
from configuration alone. This is separate from SQLite implementation authority.


The fresh builder check returned “nothing important left.” The draft additionally
clarifies the initialization manifest (a lost database must not silently become
an empty new session) and startup-only memory/SQLite discontinuities. These are
builder recommendations for review. Q19/Q20/Q22 have proposed resolutions in the
written design; they are not marked canonically resolved before owner approval.
No runtime code or dependency installation was part of this design work.


Confluence activation is now verified: protected-dev workflow dispatch
[40285487133](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/actions/runs/40285487133)
completed successfully, including publisher verification and the apply job. This
supersedes the earlier missing-secret blocker. It publishes committed dev; this
proposed design branch is not included until its own reviewed delivery.

Phase-2 tracking: [GitHub #380](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/380).
The written design is ready for owner review, with the fresh builder check complete.
Do not start implementation from an accepted recap preference alone; approval of
the full written contract precedes writing-plans. No design PR or runtime change
has been opened by this design handoff.


### October 26 — SQLite design approved; implementation plan handoff

Adam explicitly approved the complete written SQLite design and requested the
implementation plan and handoff. This supersedes the earlier proposed/review
status above: Q19/Q20/Q22 now have approved bounded resolutions in that design;
Q21 remains the confirmed bounded recap. No runtime implementation is claimed.

The [ten-task implementation plan](docs/superpowers/plans/2026-10-26-m13-sqlite-session-persistence.md)
fixes module boundaries, shared record/command interfaces, initialization/crash
proof, durable admission/publication, protocol-v2 fencing, Stop/End, recap, both
Godot work surfaces, maintenance and the actual evidence campaign. Recommended
execution is subagent-driven with fresh task reviews plus whole-branch review.
The prior phase-1 native choice was specific to that extraction. Review this plan
and confirm execution method before implementation, per writing-plans handoff.

Tracking remains GitHub #380 / PLZG-290 In Progress. Confluence publisher activation
is verified; this design/plan branch has not been published through dev. Fetch dev
and inspect status before execution; preserve the unrelated work checkout, old
guard evidence and private laptop logs. No cloud resources or new dependencies
were created in this planning step.

Adam approved the ten-task implementation plan and explicitly selected subagent-driven development. Execution started October 26 in the existing isolated worktree; per-task implementer/review gates and a final whole-branch review apply. Progress ledger: `.superpowers/sdd/m13-sqlite-session-persistence/progress.md` (local scratch); committed task receipts will also be recorded in the plan. No further plan/method approval is pending.

SQLite implementation checkpoint: Task1 safe image ownership and Task2 bounded repository are committed and independently reviewed (`0f4209e`, `77a1b96`). Task2 focused coverage is121passes onPython3.12/3.11. No live domain persistence behavior is claimed yet; coordinator/lifecycle/protocol/recap/UI integration and acceptance remain Tasks3–10. Continue from Task3, using plan receipts and per-plan SDD ledger; do not redo completed tasks.

Current SQLite execution checkpoint: Tasks1–5 independently reviewed and complete through `e2a9922`. The actual manager/server Run pipeline now commits accepted/dispatch/terminal state and replays one durable history; 588 covering tests pass onPython3.12/3.11. Next is Task6 crash/request recovery and notes/ownership reconciliation, then bounded recap, Godotv2, maintenance/docs and final actual evidence. This is not shipped acceptance. Minor R2 fixture reply handling is carried to Task8/final review. Do not redo Tasks1–5; use committed plan receipts and ignored per-plan ledger for active progress.

Task6 reviewed complete through `4b9d28d`: real process crash recovery, exact owned note reconciliation and cleanup-safe End. Inherited blanket note recovery is deferred for domain turns in both backends; extras/direct-store defaults remain. Legacy domain notes without a retained SQL request may remain pending until exact/operator recovery—truthful compatibility condition, no invented outcome or automatic reset. Next Task7 bounded recap; Tasks8–10 still required. No shipped/live acceptance claim.

Task7 reviewed complete through `ba17ec6`: bounded quoted conversation recap on the first actual invocation per fresh execution, exact source metadata, strict malformed-state rejection. Next Task8 Godotv2/history/End controls. BackendTasks1–7 reviewed; UI/maintenance/final actual evidence still pending. No full feature/live acceptance claim.

Task8 independently reviewed complete through `dce7203`: protocol-v2 restored history, separate End controls, explicit Start/Run, full public cache limits and storage continuity ownership. Tasks1–8 implementation gates are complete; remaining Task9 offline maintenance/operator alignment and Task10 final QA/performance/fresh live acceptance are required. Two Minor client findings (duplicate pending settlement and notice-prefix scroll anchors) are assigned to Task10/final review, not silently closed. No shipped acceptance or dev merge is claimed.

### Task9 resolved maintenance clarifications — October 26, 2026

The implementation handoff resolves export as observational: it may include an
open-but-stopped application session or unreconciled historical execution rows
when the same project writer lock is exclusively held. Persisted unstopped rows
do not establish a live owner; export performs no crash cleanup or SDK activation.
A live writer blocks either command. The approved design's active-session
restriction remains strict for destructive deletion: `ended_at` is required even
after Stop, with a durable exclusive backup before commit. This is an
implementation clarification of the approved export/delete scope, not a new
locked decision or imported recovery path.

The version-1 JSON export/backup ceiling is 512 MiB (8 × the 64 MiB image limit),
counted incrementally in actual UTF-8 bytes before output creation. This allows
bounded JSON quoting/envelope expansion without changing runtime image quotas;
physical disk/fsync failures remain possible. Canonical selected records and the
source image receive separate SHA256 metadata. There is no restore/import/reset
command. The [operator guide](docs/m13-session-persistence.md) carries these rules
and the approved successor for exact owned domain-note reconciliation. No new
unresolved governing conflict was found; locked decisions, historical contracts
and paid evidence remain unchanged. Final M13 acceptance remains Task10 work.

Task9 independently reviewed complete through `2e2fffd`: offline lock-respecting export and backup-before-delete of ended sessions, plus aligned operator docs. 200 focused tests pass on Python3.12/3.11. One Minor platform-error wording correction joins the two client minors in Task10/final QA. Continue Task10 full regression/performance/fresh actual evidence; Tasks1–9 are not shipped acceptance.


Task10 local implementation/QA handoff: the three deferred client/documentation
minors are resolved, plus deterministic Stop/status ordering and actual terminal
wire/display-budget regressions found by final QA. Valid2MiB frames settle before
unchanged1MiB/200-entry whole-row retention; raw oversize rejects before parsing,
and protected unsaved notice fields stay bounded. The required scene gates include
real saved/unsaved control-heavy wire, frozen replay and oversize negative controls.
Bounded source/runtime/completeness receipts, representative/dense/exact64MiB
probes and the [owner runbook](docs/m13-live-acceptance.md) are implemented.
Full valid-layout Python passes2,419 +118 subtests on final production code;
a later probe-only bounded read-only release-observation fix passes425 covering
tests. Final pinned Godot/npm gates (store338/transport104, integration2+61) and
static/spec checks pass. The [Task 10 synthetic performance record](specs/evidence/m13-state-performance-linux-2026-10-27.json)
binds actual measured bytes/runtime, made on dirty34d2584 before boundary-fix
commit; the [October26 checkpoint](specs/evidence/m13-state-performance-linux-2026-10-26.json)
is unchanged. Neither is provider or desktop acceptance. Dense cumulative peak
RSS550,031,360B and max heartbeat gap248.09ms are explicit review concerns;
pre-release barrier heartbeat/replay progress is proven separately. Initial11fail,
setup-invalid interrupted and diagnosed observer-race failures remain in the
private task receipt, not reclassified as passing gates. Independent Task10/
whole-branch reviews, actual fresh33-case guards in both modes, owner laptop/
desktop/OAuth observations, reviewed PR/tracking and merge remain with the
controller/owner. M14/M15 remain planned; no fresh OAuth login exists in this
cloud runtime and no token request/copy is part of acceptance.

Task10 implementation independently reviewed through `26d49dd` with no findings. Local full production-boundary coverage is2,419 tests+118subtests, followed by425 covering observer-helper tests and final pinned npm nine scenes/2+61 integrations. Additional confirmed Stop correlation, large-frame/cache and diagnostic snapshot races were fixed with regressions. Dense66,478,080B state measured550,031,360B peak RSS high-water and248.09ms max heartbeat gap; these costs are explicit, with no invented SLO. All deferred minors are resolved. Continue controller whole-branch review, fresh33-case pair, hosted current-head CI/PR and owner desktop/OAuth; no final M13 acceptance/merge is claimed.


Final whole-branch review fix wave (October 27): recovered and saved history now
use a correlated project/store/application envelope independent of unavailable
current worktrees, without changing schema v1 or frozen terminals. Current
null↔known observations are permitted; known-workspace replacement and live
result identity remain fenced. Both real game surfaces have crash/reopen and
unavailable-worktree regressions. Draft prose and delivery checkboxes are corrected.
Final full required-Godot Python passes2,435+118subtests; sequential npm passes
nine scenes (store399/transport119) and2+67integrations; static/spec checks and
270 isolated Python3.11 tests pass. Earlier failed/interrupted attempts remain
preserved in the private final-fix report. The [new final-review-fix performance receipt](specs/evidence/m13-state-performance-linux-2026-10-27-final-review-fix.json)
is a fresh measurement on dirty879e142: dense66,478,080B, peak550,002,688B,
commits341.70–493.23ms, max heartbeat gap206.82ms; all profiles prove pre-release
heartbeat/replay progress. Historical receipts remain unchanged. Scoped re-review,
fresh actual33+33 guards, owner desktop/OAuth, hosted current-head CI and reviewed
PR/tracking/merge remain pending; the old SDK acceptance envelope remains stale.
