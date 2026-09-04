---
doc_id: SPRINT-5-CHARTER
title: Sprint 5 charter — board reconciliation and doc consolidation
tier: 3
authority: delivery
status: ACTIVE
doc_set_version: 0.2.13
last_updated: 2026-08
owner: adamtasteslikegood
derives_from: [META-SPEC, SPEC-DRIVERS-025, SPRINT-4-CHARTER]
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: Governed doc count matches the registry after ungoverning
---

# Sprint 5 charter — board reconciliation and doc consolidation

> **One line:** this document is the complete executable context for Sprint 5. A
> session that has read this file needs nothing from the conversation that
> produced it.

Sprint 5 is the Jira sprint recorded in `docs/delivery-coordinates.md`
(`D-026`), state future (created 2026-08-20).
The forecast blackout from Sprint 3 §1.3 carries forward — no date commitment.

**Sprint goal:** reconcile the board and consolidate the governed doc set. Done
when (A) the board is triaged — non-Done items are either genuine backlog or
closed — and (B) `python3 scripts/validate_specs.py` passes with ≤14 governed
documents.

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

The board has 49 non-Done items (6 false-WIP still marked In Progress for work
already merged, the rest To Do). The governed doc set has 28 documents — many
tier-4 summaries and research that disagree with each other and with CLAUDE.md.
The roast-me finding: 28 governed docs that disagree is more maintenance than a
solo dev needs; the meta-specs system is valuable but oversized.

This sprint pays that debt before M2/M5/M6 so the board and doc set are
trustworthy when code work resumes.

### 1.3 Forecast blackout (carried from Sprint 3)

Still in force. Only 5 of the 10 required `started→resolved` timestamps exist
(4 from Sprint 3 + 1 from Sprint 2). Sprint 5 carries **no date commitment**.
The sprint ends when both gates pass or the iteration cap is hit.

## 2. Relevant decisions

| Id | Decision | Enforced by |
|---|---|---|
| `D-016` | Agent data generated, never hand-edited | CI: Validate Agent Data |
| `D-017` | Agent directory is taxonomy authority | `docs/agent-directory.md` |
| `D-023` | Merge commits only, squash/rebase disabled | Repository merge method settings |
| `D-026` | `docs/delivery-coordinates.md` owns Atlassian identifiers | Policy |
| `D-028` | Delivery authority for time-boxed sprint policy | META-SPEC |

## 3. Budgets

| Budget | Cap |
|---|---|
| Retry cap per task | 2 attempts |
| Iteration cap (sprint) | 6 iterations |
| WIP cap | 3 |
| API cost cap | None — Claude Max 5x subscription |
| PR review cycle cap | 2 rounds per PR |

## 4. Scope

### 4.1 In scope

| Task | Title | Jira | Acceptance | Depends on |
|---|---|---|---|---|
| T0 | Fetch and reconcile against origin/dev | — | `scripts/check_sync.sh --strict` | — |
| T1 | Transition 6 false-WIP items to Done | PLZG-230 | JQL `project=PLZG AND status='In Progress'` returns 0 for PLZG-221, -215, -209, -200, -199, -180 | T0 |
| T2 | Three-bucket triage of To Do backlog (Done/Keep/Won't Do) | PLZG-231 | Every To Do item reviewed and bucketed | T1 |
| T3 | Ungovern tier-4 docs + remove additional low-authority docs from governance (28→≤14) | PLZG-232 | `python3 scripts/validate_specs.py` green with ≤14 docs | T0 |
| T4 | Cross-check surviving docs for state contradictions | PLZG-233 | No state claims in governed docs contradict CLAUDE.md or git history | T3 |
| T5 | Sprint 5 charter and loop plan | PLZG-234 | `python3 scripts/validate_specs.py && test -f specs/sprint-5-charter.md && test -f specs/sprint-5-loop-plan.json` | T0 |
| T6 | Sprint close — both gates green | PLZG-235 | `python3 scripts/validate_specs.py` (≤14 docs) AND board WIP triaged | T1, T2, T3, T4, T5 |

### 4.2 Out of scope

- Code milestones M2 (grey-box office), M5 (assistant chat UI), M6 (unlock/map
  system). Those come after the board is clean.
- Bridge evolution (domain-scoped sessions, Agent SDK migration). Documented in
  memory, not this sprint.
- New governed docs. This sprint reduces the count, it does not add to it (the
  charter itself is the sole addition).

## 5. Ownership

Adam owns and reviews all tasks. One review layer:

1. **`claude-review.yml`** — automated independent reviewer on every PR.

No `/codex` adversarial reviewer this sprint — the work is docs and board
operations, not code.

## 6. Gates

Two acceptance gates, both must pass for the sprint to close:

- **Gate A — Board triaged:** non-Done items are either deliberate backlog or
  closed. The 6 false-WIP items (PLZG-221, -215, -209, -200, -199, -180) are
  transitioned to Done. Every remaining To Do item has been reviewed.
- **Gate B — Doc consolidation:** `python3 scripts/validate_specs.py` passes
  with ≤14 governed documents (down from 28). Governed doc count matches the registry after ungoverning.

## 7. Risks

| # | Failure mode | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Ungovern a doc that carries a live `D-nnn` decision. | Medium | Grep `D-nnn` references before removing any doc from governance. If a doc originates a decision, the decision must be migrated first. |
| R2 | Bulk-close real work on the board. | Medium | Three-bucket triage (Done/Keep/Won't Do), not bulk-close. Each item reviewed individually. |
| R3 | Surviving docs still contain state contradictions. | Medium | T4 cross-check task explicitly verifies against CLAUDE.md and git history. |

*Last updated: August 2026*
