---
doc_id: SPRINT-6-CHARTER
title: Sprint 6 charter — walkable office and live conversation proof
tier: 3
authority: delivery
status: ACTIVE
doc_set_version: 0.2.13
last_updated: 2026-10
owner: adamtasteslikegood
derives_from: [META-SPEC, SPEC-DRIVERS-025, SPRINT-5-CHARTER]
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: Sprint 6 is Jira sprint `120` on board `169`, state `future`
---

# Sprint 6 charter — walkable office and live conversation proof

> **One line:** this document is the complete executable context for Sprint 6. A
> session that has read this file needs nothing from the conversation that
> produced it.

Sprint 6 is Jira sprint `120` on board `169`, state `future`, created 2026-10-06
under epic `PLZG-256`. Its window is 2026-10-07 → 2026-10-21 — Jira's required
dates, not a delivery forecast. `docs/delivery-coordinates.md` § *Board and
sprints* owns those identifiers (`D-026`); `python3 scripts/sprint_6_gate.py t1`
re-reads them from Jira. Starting and closing the sprint are the owner's.

**Sprint goal:** the office is walkable room to room, and a command proves the
agent bridge carries a real conversation in-engine. Done when both gates pass:

- **Gate A (CI, every PR)** — `godot --headless tests/smoke_test.tscn` exits 0
  having walked a body into every room.
- **Gate B (local, credentialed)** — `python3 scripts/sprint_6_gate.py live`
  exits 0: two real turns through the bridge, from Godot and from a client that
  knows nothing about Godot, with the transcript committed and read by the owner.

The machine-readable half is [`sprint-6-loop-plan.json`](sprint-6-loop-plan.json),
the shape `delivery_loop_gate.py` consumes. **The two must agree. A disagreement
is a defect to fix, not a precedence to apply** — patch both in the same change.

## 1. Context

### 1.1 Owner ruling: the milestones serve the prototype

Locked 2026-10-06, in the planning session that produced this charter. Asked
whether Sprint 6 was "M2", the owner answered that what needs doing is rooms
that are walkable and live proof that the bridge works with a live
conversation — and that where the milestone list does not match that, the
milestone list is what changes. `specs/roadmap.md` is rewritten in this charter's
change accordingly: M2 loses its navigation mesh, and M8 says what proves it.

This is a ruling about sequencing documents. It does not change a storyboard
beat or a locked `D-nnn`; a fix that would need either is escalated (§3).

### 1.2 Neither half of the goal was proven by a command

Read from the tree on 2026-10-06:

- `tests/smoke_test.gd` emits `agent_response_received` with the literal string
  "Hello from the bridge." and checks the label. It opens no socket. The
  `Bridge Unit Tests` CI job installs `pytest` and `websockets` and never calls
  a model. M8's ✅ was asserted by a simulated reply.
- `scenes/world/office.gd` builds a lobby, a corridor and the server room. The
  player's office, the engineering floor and the war room do not exist, and no
  test moves a body through a doorway.

### 1.3 Forecast blackout — still in force, re-measured

Carried from Sprint 3 §1.3, and this time measured rather than carried on
trust. Read from Jira status history on 2026-10-06, items resolved since
2026-07-30: 120 resolved, 41 with a started→resolved pair, **20 of those under
one hour**; cycle time p50 0.1 days, p85 46.6 days; weekly throughput
29 · 7 · 8 · 2 · 6, then five weeks of zero, then 63 in the Sprint 5 triage
week. Half the sample is bookkeeping and the window contains a pause, so the
lift condition — ten or more real timestamps from a window with no
zero-throughput week — is unmet. Sprint 6 carries **no date commitment**. It
ends when both gates pass or the iteration cap is hit.

What Sprint 6 does about it: each task ticket moves to In Progress when its
work starts and to Done when its acceptance command exits 0, never in bulk at
close. `sprint_6_gate.py t7` refuses a ticket whose two transitions are less
than an hour apart.

### 1.4 This charter takes the governed set from 19 to 20

Sprint 5's Gate B capped the set at 19, enforced by `scripts/sprint_5_gate.py
t3`, whose charter is now `HISTORICAL`. Nothing live enforces 19. Whether a
retired charter's rule outlives it is open conflict §4.11 in
[`meta/spec-drivers-v0.2.5.md`](meta/spec-drivers-v0.2.5.md) (`PLZG-249`), and
this charter does not settle it: it adds one governed document by design and
says so.

## 2. Relevant decisions

| Id | Decision | Enforced by |
|---|---|---|
| `D-005` | The bridge never knows the UI exists | Gate B runs the same two turns from a plain Python client (swap test) |
| `D-015` | Bridge transport is a local WebSocket on port 8765 | Policy |
| `D-016` | An NPC scene stores an `agent_id` and nothing else | CI: Validate Agent Data, for the data half |
| `D-023` | Merge commits only | Repository merge method settings |
| `D-025` | Scene scripts live beside their `.tscn` under `scenes/` | Policy |
| `D-026` | `docs/delivery-coordinates.md` owns Atlassian identifiers | Policy |
| `D-028` | Delivery authority for time-boxed sprint policy | CI: Validate Specs |
| `D-030` | PR review rounds: minimum 2, maximum 3, with exemptions | Policy, applied by hand |

## 3. Budgets

| Budget | Cap |
|---|---|
| Attempts per task | 3 on T2–T6, 2 on T1 and T7; T0 exempt |
| Sprint iteration cap | 8 |
| Harness controller cap | 28 — `loop_controller.py` spends one iteration per `record` and one per `verify`, so eight tasks cost 16 before any retry |
| WIP cap | 3 |
| T6 scope | at most 3 defects fixed; a fourth is filed and escalated |
| API cost cap | None — Claude Max subscription |
| PR review rounds | `D-030` |

**Escalate to Adam and stop the task** on any of: attempts exhausted; no
verification available; Gate B exiting 2 (no credential); a destructive or
irreversible action; goal drift; a fix that would change a storyboard beat or a
locked `D-nnn`; a fourth T6 defect.

**Blocked on owner is not a failure.** A PR waiting for the owner's merge burns
no attempt. The loop moves to a task whose dependencies are met, otherwise it
stops and reports.

## 4. Scope

### 4.1 In scope

| Task | Title | Jira | Acceptance | Depends on |
|---|---|---|---|---|
| T0 | Fetch and reconcile against origin/dev | — | `scripts/check_sync.sh --strict` | — |
| T1 | Charter, loop plan and roadmap rewrite | PLZG-257 | `python3 scripts/sprint_6_gate.py t1` — the validator passes, the charter is registered, and Jira confirms sprint `120` is on board `169` holding every task ticket under epic `PLZG-256` | T0 |
| T2 | Player's office, engineering floor and war room — walkable | PLZG-258 | `python3 scripts/sprint_6_gate.py t2` — `tests/room_probe.tscn` finds all five rooms in the running scene | T1 |
| T3 | Doorway triggers and locked corridors | PLZG-259 | `python3 scripts/sprint_6_gate.py t3` — every room but the lobby has a doorway trigger, and at least two corridors are locked | T2 |
| T4 | Smoke test: every room exists and is reachable (Gate A) | PLZG-260 | `python3 scripts/sprint_6_gate.py t4` — the smoke test exits 0 **and** its `SMOKE rooms_reachable:` line names all five rooms | T2, T3 |
| T5 | Live gate: two real turns, in-engine and without Godot (Gate B) | PLZG-261 | `python3 scripts/sprint_6_gate.py t5` — the runner exits 0 and the transcript shows turn 2 returning a nonce only turn 1 carried, for both clients | T1 |
| T6 | Fix what the first real Gate B run breaks | PLZG-262 | `python3 scripts/sprint_6_gate.py t6` — Gate B green, defects recorded, three or fewer | T5 |
| T7 | Sprint close — both gates green | PLZG-263 | `python3 scripts/sprint_6_gate.py t7` — T1, Gate A and Gate B re-run; transcript committed, captured inside the window and `owner_read: true`; every other task ticket Done with an hour or more between In Progress and Done; flow snapshot fresh | T4, T5, T6 |

The five rooms are `lobby`, `server-room`, `player-office`, `engineering-floor`
and `war-room`. **The probe's contract:** a room, doorway or locked corridor is
seen when its node is in the group `rooms`, `doorways` or `locked_corridors` and
carries a `room_id` metadata string; a doorway's `room_id` is the room it leads
into. Node names and types are the implementer's.

**What exists when this charter merges, and what does not.** `sprint_6_gate.py`
ships with every subcommand, and `tests/room_probe.tscn` runs. `t2`, `t3`, `t4`
and `live` all **fail** today, which is the truthful reading: no room declares
itself, the smoke test walks nowhere, and the live runner
(`scripts/sprint_6_live.py`) is T5's deliverable. The gate's own behaviour is
pinned by `tests/test_sprint_6_gate.py`, run in CI.

**Gate B needs a credential and a machine.** It exits 2, not 1, when it cannot
authenticate. An exit 2 blocks the close and cannot be waived by the agent.

### 4.2 Out of scope

- **Navigation mesh.** No NPC walks yet, so nothing would consume it. It is
  removed from M2 in the roadmap and carried by no ticket.
- **M5 (assistant chat UI).** Blocked on owner-authored content, `PLZG-62` and
  `PLZG-60`.
- **M6 (unlock and map system).** T3 adds locked corridors that ask
  `GameState.is_unlocked`; the unlock progression and the map are M6.
- **A Claude credential in CI.** Gate B is local this sprint.
- **Sprint 5's follow-ups** — `PLZG-249`, `PLZG-251`, `PLZG-252`, `PLZG-254` —
  stay in the backlog (risk R5).
- **Bridge evolution** to domain-scoped sessions or the Agent SDK, beyond what
  a T6 defect forces.

## 5. Ownership

Adam owns and reviews every task. The agent executes T1–T7.

| Action | Who |
|---|---|
| Merge a PR | Adam only. The loop opens PRs and works review rounds; it never merges. |
| Create the epic, tasks and sprint; move tickets on real start and on acceptance exit 0; comment evidence | Agent |
| Start the sprint, close the sprint | Adam |
| Run Gate B | Agent, on the owner's machine with the owner's credential |
| Accept the transcript (`owner_read: true`) | Adam only. The gate can check the flag, not who set it; an agent setting it is a breach of this charter that the gate will not catch. |

Three automated reviewers, all advisory:

1. **`claude-review.yml`** — runs on non-draft, same-repo PRs.
2. **GitHub Copilot code review** — set by the ruleset on `dev`.
3. **The owner's scheduled ChatGPT/Codex PR review** — an outside schedule, not
   the Codex connector. **It posts and pushes under the owner's account.** Two
   rules follow. A comment or push under that account is not owner approval:
   only a merge, or an instruction from Adam in a session, is sign-off. And the
   loop fetches a PR's branch before every push, because that reviewer can move
   it. Its comments go through the `D-030` rounds like any other reviewer's.

## 6. Gates

Both must pass for the sprint to close.

- **Gate A — walkable.** `tests/smoke_test.tscn` exits 0 and reports having
  walked into all five rooms. Reachability is tested by moving a body through
  each doorway in the running scene, with bounds read from the scene.
- **Gate B — live conversation.** For each of two clients — a headless Godot
  scene through `scenes/bridge/ws_client.gd`, and a plain Python WebSocket
  client — turn 1 sends a random nonce and turn 2 asks for it back without
  repeating it. Both replies are non-empty and are not the simulated string;
  turn 2's reply contains the nonce. In-engine, the reply reaches `BodyLabel`
  through the typewriter. The transcript is committed at
  `specs/evidence/sprint-6-live-transcript.json`.

**Close sequence.** T7's change lands with this charter still `ACTIVE`. The
owner closes the Jira sprint once T7 is on `dev`; retiring this charter to
`HISTORICAL` and re-declaring the flow snapshot follow together, as `PLZG-255`
did for Sprint 5. `data/plzg-flow-snapshot.json` keeps declaring
`"sprint": null` until the owner starts the sprint.

## 7. Risks

Pre-mortem run 2026-10-06. Owner of every risk: Adam.

| # | Failure mode | Mitigation |
|---|---|---|
| R1 | Gate B never really runs: the credential is missing, the script exits 2, and the sprint closes on Gate A alone. | T7 requires Gate B exit 0 and a transcript captured inside this sprint's window. Exit 2 blocks the close. |
| R2 | The live gate is flaky, a strict assertion reddens, and someone loosens it to "non-empty". | Structure is asserted, never wording: the nonce. Up to three tries per run, every try logged. |
| R3 | The bridge learns about Godot while being fixed in T6 (`D-005`). | The same two turns run from a client with no Godot. A fix that works for one client only fails review. |
| R4 | Rooms are added but sealed: a wall collider closes a doorway and the test only checks that nodes exist. | T4 moves a body through each doorway, and the gate compares the rooms the test says it reached with the plan's list. |
| R5 | The roadmap rewrite turns into another docs sprint. | T1 may touch the roadmap, this charter, the loop plan, the doc registry and delivery-coordinates, and no other governed document. |

*Last updated: October 2026*
