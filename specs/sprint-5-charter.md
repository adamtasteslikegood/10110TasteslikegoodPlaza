---
doc_id: SPRINT-5-CHARTER
title: Sprint 5 charter — board reconciliation and doc consolidation
tier: 3
authority: delivery
status: HISTORICAL
doc_set_version: 0.2.14
last_updated: 2026-10
owner: adamtasteslikegood
derives_from: [META-SPEC, SPEC-DRIVERS-025, SPRINT-4-CHARTER]
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: The board had 114 non-Done items at the start of 2026-10-05
---

# Sprint 5 charter — board reconciliation and doc consolidation

> **The gate is frozen with the sprint.** `scripts/sprint_5_gate.py` was green at
> the close and is expected to fail now: it compares live board and document state
> with evidence captured then. Owner ruling, `PLZG-268`, 2026-10-07 — a closed
> sprint's gate is a record, not a live check; its evidence is not re-stamped.

> **HISTORICAL.** Sprint 5 is closed (Jira `completeDate` 2026-10-06T20:50Z, the
> afternoon of 2026-10-06 PDT), with both gates green and all seven tickets in the
> Jira sprint Done — `PLZG-229`, which carried this charter, and the six task
> tickets `PLZG-230`–`PLZG-235`. Everything below is as written while it was planned and run — "started",
> "still in force" and other present-tense statements about the sprint and the
> board describe that time, not now.

> **One line:** this document is the complete executable context for Sprint 5. A
> session that has read this file needs nothing from the conversation that
> produced it.

Sprint 5 is Jira sprint `51` on board `169`, started 2026-10-06 with a
one-week window ending 2026-10-13 (owner decision; the window is Jira's
required end date, not a delivery forecast). `docs/delivery-coordinates.md` § *Board and
sprints* owns those identifiers (`D-026`); `python3 scripts/sprint_5_gate.py t5`
re-reads them from Jira.
The forecast blackout from Sprint 3 §1.3 carries forward — no date commitment.

**Sprint goal:** reconcile the board and consolidate the governed doc set. Done
when (A) the board is triaged — non-Done items are either genuine backlog or
closed — and (B) `python3 scripts/validate_specs.py` passes with ≤19 governed
documents.

> **Re-scoped 2026-10-05, owner decision.** Gate B read ≤14 until review showed
> it could not be reached: the registry holds 28 governed documents and only 9
> are tier-4, so removing every one leaves 19. The five further removals the
> earlier draft listed included the Sprint 2 and 3 charters, which
> `SPRINT-4-CHARTER` and `SPRINT-3-CHARTER` derive from — ungoverning them fails
> the validator. The target is now the nine tier-4 documents and nothing else.

The machine-readable half is [`sprint-5-loop-plan.json`](sprint-5-loop-plan.json),
the shape `delivery_loop_gate.py` consumes. **The two must agree. A disagreement
is a defect to fix, not a precedence to apply** — patch both in the same change.

## 1. Context

### 1.1 Sprint 4 closed — critical path complete

Sprint 4 delivered M7 (Python bridge with Claude SDK) and M8 (first live agent
output in-world). All 9 loop tasks completed (`T0`, `T1`, `T2`, `T3a`, `T3b`,
`T4`–`T7`), spanning 8 Jira-backed tasks (`PLZG-170`–`PLZG-177`). The proof-of-
concept critical path M1 → M4 → M8 is done. Next code milestones are M2 (grey-
box office), M5 (assistant chat UI) and M6 (unlock + map system).

### 1.2 Why housekeeping before code

The board had 114 non-Done items at the start of 2026-10-05
(`project = PLZG AND statusCategory != Done`), ten of them In Progress. By 20:08
PDT that day it was 111 — five closed by T1, two filed — which is the figure
`data/plzg-flow-snapshot.json` recorded then; both numbers are right for their hour
(`PLZG-248`, from Jira's status history). An
earlier draft of this charter said 49; that figure was never re-measured and was
wrong by more than half. The governed doc set had 28 documents when this sprint was
planned — nine of them tier-4 summaries and research that disagreed with each other
and with CLAUDE.md. T3 took it to 19.
The roast-me finding: 28 governed docs that disagree is more maintenance than a
solo dev needs; the meta-specs system is valuable but oversized.

This sprint pays that debt before M2/M5/M6 so the board and doc set are
trustworthy when code work resumes.

### 1.3 Forecast blackout (carried from Sprint 3)

Still in force, carried forward by owner decision. The lift condition was **not
re-measured** for Sprint 5: the last count, taken before Sprint 4 ran, was 5 of the
10 required `started→resolved` timestamps (4 from Sprint 3 + 1 from Sprint 2).
Sprint 5 carries **no date commitment**.
The sprint ends when both gates pass or the iteration cap is hit.

## 2. Relevant decisions

| Id | Decision | Enforced by |
|---|---|---|
| `D-016` | Agent data generated, never hand-edited | CI: Validate Agent Data |
| `D-017` | Agent directory is taxonomy authority | Policy — origin `docs/agent-directory.md`; `Validate Agent Data` backs the 132 total only |
| `D-023` | Merge commits only, squash/rebase disabled | Repository merge method settings |
| `D-026` | `docs/delivery-coordinates.md` owns Atlassian identifiers | Policy |
| `D-028` | Delivery authority for time-boxed sprint policy | CI: Validate Specs (the authority-to-originate check) |
| `D-030` | PR review round bounds: minimum 2, maximum 3, with exemptions | Policy, applied by hand — origin `docs/designs/platform-decisions.md` |

## 3. Budgets

| Budget | Cap |
|---|---|
| Retry cap per task | 2 attempts (T0 precondition exempt) |
| Iteration cap (sprint) | 6 iterations |
| WIP cap | 3 |
| API cost cap | None — Claude Max 5x subscription |
| PR review rounds | `D-030`: minimum 2 rounds before merge, maximum 3 before deciding — merge, close, or revert to draft and elevate to the owner. Security findings, branch-protection failures and ticket-linked blockers are exempt from the maximum and run until resolved or elevated. |

## 4. Scope

### 4.1 In scope

| Task | Title | Jira | Acceptance | Depends on |
|---|---|---|---|---|
| T0 | Fetch and reconcile against origin/dev | — | `scripts/check_sync.sh --strict` | — |
| T1 | Clear the 7 stale In Progress items | PLZG-230 | `python3 scripts/sprint_5_gate.py t1` — PLZG-129, -199, -200, -209, -215, -221 are Done and PLZG-180 is Done with the `wont-do` label | T0 |
| T2 | Three-bucket triage of every non-Done item (Done/Keep/Won't Do) | PLZG-231 | `python3 scripts/sprint_5_gate.py t2` — the triage evidence covers every key in the pre-triage baseline and every key still open (To Do or In Progress, the sprint's own tickets excepted), and each bucket matches the ticket's status and label in Jira | T1 |
| T3 | Ungovern the 9 tier-4 docs + mark Sprint 2/3 charters HISTORICAL (28→≤19) | PLZG-232 | `python3 scripts/sprint_5_gate.py t3` — `validate_specs.py` green with ≤19 docs, all 19 documents that are not tier-4 still governed, and the Sprint 2 and 3 charters `HISTORICAL` | T0 |
| T4 | Cross-check surviving docs for state contradictions | PLZG-233 | `python3 scripts/sprint_5_gate.py t4` — every governed doc has a cross-check row with `contradiction: false`, the owning systems consulted, and a `reviewed_blob` matching the file's current content; a row may carry a dispute the document labels as such only while the conflict register holds it `OPEN`, must list every `OPEN` conflict its document cites, and the gate names what is carried | T3 |
| T5 | Sprint 5 charter and loop plan | PLZG-234 | `python3 scripts/sprint_5_gate.py t5` — the validator passes, both files exist, and Jira confirms sprint `51` is on board `169` holding every task ticket | T0 |
| T6 | Sprint close — both gates green | PLZG-235 | `python3 scripts/sprint_5_gate.py t6` — re-runs T1–T4, requires `review_complete: true` in the triage evidence, and requires `validate_delivery_coordinates.py` to pass on a refreshed flow snapshot | T1, T2, T3, T4, T5 |

**The acceptance commands need a working Jira credential.** `sprint_5_gate.py`
reads `ATLASSIAN_URL`, `ATLASSIAN_EMAIL` and `ATLASSIAN_API_TOKEN` from `./.env`,
then the environment, and proves the credential before trusting any search: Jira
answers an unauthenticated search with an empty list rather than a refusal, so a
revoked token would otherwise read as "no ticket matches". It exits 2, not 1,
when it cannot authenticate. That is not hypothetical: on 2026-10-05 the token
in the working `.env` had been revoked, and the first run reported all seven T1
keys as not Done.

**T1 was planned on a wrong assumption and has already run.** It was "transition
6 false-WIP items to Done", taking a merged PR that carries a ticket's key as
proof the ticket's work was done. Checked against `dev` on 2026-10-05, two of the
six were not done — `PLZG-180` and `PLZG-200` had their keys reused by unrelated
PRs. The outcome is in the loop plan's T1 note. The lesson generalises the one in
`docs/delivery-coordinates.md`: verify a ticket against the file, not the PR
title.

### 4.2 Out of scope

- Code milestones M2 (grey-box office), M5 (assistant chat UI), M6 (unlock/map
  system). Those come after the board is clean.
- Bridge evolution (domain-scoped sessions, Agent SDK migration). Documented in
  memory, not this sprint.
- New governed docs beyond this charter. The charter is the only temporary
  addition; Sprint 5 still targets a net reduction to ≤19 governed documents.

## 5. Ownership

Adam owns and reviews all tasks. Two automated review layers, both advisory:

1. **`claude-review.yml`** — independent reviewer. On pull-request events it runs
   for non-draft, same-repo PRs and skips Dependabot's PRs and bot-triggered events; a
   manual `workflow_dispatch` always runs.
2. **GitHub Copilot code review** — set by the ruleset on `dev`; reviews each push.

No `/codex` adversarial reviewer this sprint — the work is docs and board
operations, not code. (The Codex connector is installed but only reports that its
usage limit is reached.)

## 6. Gates

Two acceptance gates, both must pass for the sprint to close:

- **Gate A — Board triaged:** non-Done items are either deliberate backlog or
  closed. The 7 stale In Progress items are resolved (PLZG-129, -199, -200,
  -209, -215, -221 Done; PLZG-180 Won't Do). Every non-Done item in the
  pre-triage baseline has been reviewed, In Progress included.
- **Gate B — Doc consolidation:** `python3 scripts/validate_specs.py` passes
  with ≤19 governed documents (down from 28), none of the 19 non-tier-4
  documents among those removed.

**Close sequence.** T6's change lands with this charter still `ACTIVE` and the flow
snapshot still declaring Sprint 5 active, because both are true until the Jira
sprint is closed — which happens only once T6 is on `dev`. Retiring this charter to
`HISTORICAL` and re-declaring the snapshot as between sprints then move together
(`PLZG-255`).

## 7. Risks

| # | Failure mode | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Ungovern a doc that carries a live `D-nnn` decision, or that another governed doc derives from. | Medium | Grep both `D-nnn` references and the doc's `doc_id` in other documents' `derives_from` before removing it from governance. A decision must be migrated first; a `derives_from` target stays governed. T3's gate fails if any of the 19 documents named in the loop plan's `must_stay_governed` leaves the registry. |
| R2 | Bulk-close real work on the board. | Medium | Three-bucket triage (Done/Keep/Won't Do), not bulk-close. Each item reviewed individually; the non-Done set is recorded as a baseline first, so an item closed without a triage row fails T2. |
| R3 | Surviving docs still contain state contradictions. | Medium | T4 verifies each claim against the system that owns it — git, Jira, GitHub or CI — and records which. Agreement with CLAUDE.md is not verification. |

*Last updated: October 2026*
