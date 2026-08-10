---
doc_id: SPRINT-4-CHARTER
title: Sprint 4 charter — the agent bridge layer
tier: 3
authority: delivery
status: ACTIVE
doc_set_version: 0.2.12
last_updated: 2026-08
owner: adamtasteslikegood
derives_from: [META-SPEC, SPEC-DRIVERS-025, SPRINT-3-CHARTER]
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: Sprint 4 is Jira sprint 48 on board 169, state future
---

# Sprint 4 charter — the agent bridge layer

> **One line:** this document is the complete executable context for Sprint 4. A
> session that has read this file needs nothing from the conversation that
> produced it.

Sprint 4 is Jira sprint 48 on board 169, state future (created 2026-08-10).
The forecast blackout from Sprint 3 §1.3 carries forward — no date commitment.

**Sprint goal:** M7 + M8 — write the agent bridge layer. Done when
`tests/smoke_test.tscn` exits 0 with a real Claude agent response rendered
in-engine via the typewriter effect.

The machine-readable half is [`sprint-4-loop-plan.json`](sprint-4-loop-plan.json),
the shape `delivery_loop_gate.py` consumes. **The two must agree. A disagreement
is a defect to fix, not a precedence to apply** — patch both in the same change.

## 1. Context

### 1.1 Critical path

M1 → M4 → M8. M1 done (v0.2.8), M4 done (v0.2.8). M5 (chat UI) and M6
(unlock/map) are **not** on the critical path and are explicitly out of scope.
This sprint delivers the two remaining legs: M7 (Python bridge) and M8 (first
live agent output in-world).

### 1.2 What changed from the roadmap

`specs/roadmap.md` M7 shows `subprocess.run(["claude", f"@{agent_id}", task])`.
**This is replaced by a direct Claude SDK call.** The bridge uses the `anthropic`
Python SDK with `client.messages.create()`, passing agent definitions as system
prompts. No subprocess, no CLI dependency.

Auth: `ANTHROPIC_API_KEY` environment variable, resolved by the bare `Anthropic()`
constructor. For the owner's personal usage under TOS for apps using long-lived
tokens.

### 1.3 Forecast blackout (carried from Sprint 3)

Still in force. Only 5 of the 10 required `started→resolved` timestamps exist
(4 from Sprint 3 + 1 from Sprint 2). Sprint 4 carries **no date commitment**.
The sprint ends when M8 is demonstrable in-engine or the iteration cap is hit.

### 1.4 New decision: D-029

**Bridge agent store.** The bridge maintains its own copy of agent definitions,
decoupled from the `claude-code-tresor` submodule at runtime. A sync module
copies from `claude-code-tresor/subagents/` into `bridge/agents/`. At runtime the
bridge reads only from its own store — never the submodule directly. Store format
is initially `.md` files, with an upgrade path to a structured store (database,
wikilink markdown, gbrain-style index). Origin: `docs/designs/platform-decisions.md`.

## 2. Relevant decisions

| Id | Decision | Enforced by |
|---|---|---|
| `D-005` | Bridge zero UI awareness | Swap test at review |
| `D-006` | Synchronous with timeout | Bridge implementation |
| `D-007` | Typewriter effect, frontend-only | Godot dialogue panel |
| `D-014` | No versioned API contract pre-M8 | Policy |
| `D-015` | Python WebSocket, `localhost:8765` | Bridge implementation |
| `D-016` | Agent data generated, never hand-edited | CI: Validate Agent Data |
| `D-025` | GDScript file layout: scenes/ | File tree |
| `D-029` | Bridge owns agent store at runtime | Bridge implementation |

## 3. Budgets

| Budget | Cap |
|---|---|
| Retry cap per task | 3 attempts |
| Iteration cap (sprint) | 12 iterations |
| API cost cap | None — Claude Max 5x subscription |
| Model floor | `claude-opus-4-6` (xhigh/high for coding) |
| Model ceiling | `claude-opus-5` (high++ for planning/investigation) |
| `claude-fable-5` | By explicit choice only |
| Model routing | Script incoming to `scripts/` — develop here, adapt to agent layer |
| PR review cycle cap | 2 rounds per PR |

## 4. Scope

### 4.1 In scope

| Task | Title | Jira | Acceptance |
|---|---|---|---|
| T0 | Fetch and reconcile against origin/dev | — | `scripts/check_sync.sh --strict` |
| T1 | Sprint charter, loop plan, D-029, Jira sprint | PLZG-170 | `python3 scripts/validate_specs.py && test -f specs/sprint-4-charter.md && test -f specs/sprint-4-loop-plan.json` |
| T2 | `bridge/bridge.py` — WebSocket + Claude SDK | PLZG-171 | `python3 -m py_compile bridge/bridge.py` |
| T3a | `bridge/sync.py` — sync module (D-029) | PLZG-172 | `python3 -m py_compile bridge/sync.py` |
| T3b | `bridge/agents.py` — agent store loader | PLZG-173 | `python3 -m py_compile bridge/agents.py` |
| T4 | `scenes/bridge/ws_client.gd` — Godot WS client | PLZG-174 | `godot --headless tests/smoke_test.tscn` |
| T5 | Wire dialogue → bridge → response → typewriter | PLZG-175 | `godot --headless tests/smoke_test.tscn` |
| T6 | Smoke test: assert real agent response | PLZG-176 | `godot --headless tests/smoke_test.tscn` |
| T7 | Sprint close | PLZG-177 | `python3 scripts/validate_specs.py && godot --headless tests/smoke_test.tscn` |

### 4.2 Out of scope

- M5 (assistant chat UI) and M6 (unlock/map system). Not on the critical path.
- True WebSocket streaming (deferred per `D-006`).
- Unique agent sprites (deferred per `D-011`, `D-012`).
- Model routing script implementation (incoming to `scripts/`, wired later).

## 5. Ownership

Adam owns and reviews all tasks. Three review layers:

1. **`claude-review.yml`** — automated independent reviewer on every PR.
2. **`/codex` adversarial reviewer** — Codex headless, sends diffs with
   instructions. Surfaces things Claude misses.
3. **Adam** — manual review on auth-sensitive (T2) and integration (T5) tasks.

## 6. Risks

| # | Failure mode | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Auth doesn't work locally. `ANTHROPIC_API_KEY` untested in a local Python bridge context. | Medium | T2 is standalone with manual verify. Test `Anthropic()` resolution before wiring. |
| R2 | D-005 boundary violation. Bridge learns about Godot. | Medium | Swap test in every review. `/codex` adversarial adds second eyes. |
| R3 | Submodule empty — agent loader fails. | ~~High~~ Low | **Mitigated by D-029.** Bridge reads from its own store, not the submodule. |
| R4 | WebSocket stability. Version/protocol mismatches. | Low-Medium | `wscat`/`websocat` test before Godot integration. D-006 timeout protection. |
| R5 | Scope creep into M5/M6. | Low | Charter scopes M7+M8 only. M5/M6 not on critical path. |

R6 (API cost runaway) retired — Claude Max 5x subscription with opus-4-6 to opus-5 band.

*Last updated: August 2026*
