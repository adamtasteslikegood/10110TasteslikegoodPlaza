# M13 decisions and questions for Adam

**Status: working review queue; not a specification, decision register or implementation approval.**
Prepared October 23, 2026 (America/Los_Angeles). Tracks reconciliation for [GitHub #373](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/373) and PLZG-290. No new D-numbers are assigned here.

## Owner instructions for this round

Reconcile the published docs/research and planning histories with the latest M12 fixes on `origin/dev`. Preserve research and recorded owner answers. Do not implement the store/backends, open a PR, change locked decisions, or invent new planning decisions in this round. Keep explicit questions where governing text or agent-authored absolutes conflict with the direction of the project.

Temporary integration isolation is an operational boundary, not the long-term architecture or delivery destination. The next session should review these entries with Adam, reconcile approved decisions across their entitled sources, then open the appropriate PR to `dev`. Implementation follows that alignment.

This file is a non-authoritative working queue. The entitled decision register remains [specs/meta/decision-register.md](specs/meta/decision-register.md); the governing conflict protocol remains [META-SPEC](specs/meta/META-SPEC.md) and the canonical open-conflict register remains [spec-drivers §4](specs/meta/spec-drivers-v0.2.5.md). This file does not silently supersede either. Once approved, actionable governance conflicts must be recorded/resolved there through the normal process.

## Verified branch inventory and interruption checkpoint

Observed remotely before reconciliation:

| Ref | Observed tip | Finding |
|---|---|---|
| `origin/dev` | `971ac2fa70515bbd20f0627a5b7e2a766a7288c2` | Latest M12 readiness/clipboard/runtime fixes; M12 acceptance is now Done in Jira. Some repository summaries still describe acceptance as open. |
| `origin/docs/add_notes_Docs` | `f37bff31a2aeae2e716e73b841a19dae3c89489a` | Imported UI notes, research snapshots, diagrams and owner-local config changes; 1 unique commit and 21 commits behind dev at inspection. |
| `origin/plaza/workspace-integration` | `122cbc74e9b76c751b9cf57479bf0c1c8a1d7e46` | Research, proposed store/backend plan, recorded owner answers, and SQLite amendments to two M12 documents; 4 unique commits and 48 commits behind dev at inspection. |
| `origin/docs/cloudflare-durable-objects-research` | `47373a365b9facc1aa01a17d11009377f63e743a` | Ancestor of workspace-integration; retain its provenance. |
| `origin/feat/373-domain-session-store-extraction` | Not found | Both remote-ref inspection and GitHub branch lookup found no such branch. Asked Adam whether workspace-integration is the intended target; do not fabricate or silently substitute the missing branch. |

The remote fetch configuration originally selected only dev; the named research/integration refs were explicitly fetched before comparison. A successful generic fetch alone would not have refreshed them.

**Reconciliation is incomplete.** In the existing isolated cloud worktree, a local branch `docs/PLZG-290-reconcile-notes` was created from the docs tip above. A `--no-commit --no-ff` merge of dev applied without textual conflicts. Before any merge commit/push, the execution environment became unavailable. The existing top-level `work` checkout was not changed. No remote merge, rebase, force-push, PR or implementation was performed at this checkpoint. This working file is being saved directly to the docs branch through the GitHub connector so the review queue survives the environment interruption.

On resumption, fetch and inspect again. The remote docs tip will have advanced to include this file. Do not commit a stale interrupted merge without incorporating that new history. Preserve the interrupted state before choosing its recovery; do not blanket reset unrelated work.

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
| Q16 — imported provenance / review before PR | `Docs/files/` (capital D) contains UI-copied notes, research snapshots, diagrams and raw Cloudflare pages. `docs/research/cloudflare-durable-objects/` carries another research collection. The archived `arch_convo_full.md` is copied selectable UI text, not a runtime transcript. | Preserve provenance and explicitly distinguish copied text from logged execution. Compare duplicate raw pages by content before choosing a canonical index; do not silently edit vendor snapshots or delete research. Review imported artifacts for owner-local/private material before future PR publication. |
| Q17 — integration mechanics | The docs commit changes `bridge/config.json`: owner-local workspace path, permission bypass true and a larger conversation token cap. Those are not research documentation. | Recommended reconciliation: use dev's product defaults in the reconciled tree and preserve owner settings in original commit history/local setup guidance; do not accidentally ship laptop paths or alter execution behavior in a docs-only round. Record the actual choice when applied. No config reconciliation has been committed yet. |
| Q18 — validator finding | The conflict-free preliminary docs+dev merge fails `python3 scripts/validate_specs.py` with 16 imported Markdown paths under `Docs/files/` missing from the document registry. | Register each imported non-authoritative snapshot individually with a provenance-based exemption, or add proper frontmatter if it truly belongs in the governed set. Audit the additional lowercase research/plan files when merged too. Do not disable the validator, create blanket exemptions, grant imported text decision authority or bump decision versions just to pass. |

## Next-session review and integration checklist

- [ ] Confirm the actual planning ref with Adam (pending question above); fetch all named remote refs explicitly.
- [ ] Inspect the interrupted local merge and preserve its state; incorporate this remotely saved checkpoint before any branch push.
- [ ] Merge current dev into the docs history without rewriting published ancestry; resolve owner-local config deliberately and validate docs.
- [ ] Merge the updated docs history into the confirmed planning branch; retain research commits, recorded owner answers and the provenance of pre-existing SQLite amendments.
- [ ] Check byte identity of runtime, tests, dependencies and UI against current dev; any remaining non-doc change needs explicit explanation. No implementation is authorized in this round.
- [ ] Resolve registry coverage and internal links without changing decision authority. Preserve all earlier acceptance artifacts unchanged.
- [ ] Mark each Q row as resolved, clarification-only, or awaiting Adam; add source/commit/ruling references as the working queue evolves.
- [ ] Push reconciled branches only after validation; record exact old/new tips and whether each contains current dev.
- [ ] Update #373's handoff with the actual branch/ref state and pending review gates.
- [ ] **Next session with Adam:** settle unresolved product choices; propagate approved rulings through entitled source docs, decision register, roadmap, plans, summaries and canonical conflict register; validate the whole set.
- [ ] Then open the appropriate PR to dev. Start M13 implementation only after the planning/governance alignment is approved.

## How to maintain this file

For each new item, cite the exact document/heading or D-number, quote the narrow conflicting claim, distinguish a current rule from historical evidence and an agent's extrapolation, state what owner decision is actually missing, and list every document that must change together. Record the eventual owner answer and implementing commit. Do not mark an issue resolved merely because it was discussed.

Completed rows stay as provenance with links to the canonical resolution. This file is a review queue, not a second canonical decision register.
