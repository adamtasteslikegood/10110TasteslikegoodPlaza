# Bridge Domain Architecture — Design Spec

> **One line:** Evolve the bridge from single-request pipe to domain-scoped parallel
> sessions, with the current bridge.py becoming a lightweight conversation engine.

**Origin:** Confluence brainstorm
"[Background Execution, Agent Grouping, and Workflow Orchestration in Virtual Environments](https://tasteslikegood.atlassian.net/wiki/x/AYCFAw)"
— extracted from the post-M8 e2e demo session.

**Drives:** Phase 1 implementation via superpowers writing-plans → executing-plans.

**Builds on:** M8 (proven), D-005 (zero UI awareness), D-006 (sync with timeout),
D-014 (no versioned contract until post-M8 — we're post-M8), D-015 (ws://localhost:8765),
D-029 (bridge owns its agent store).

**Caveat from the owner:** The meta-spec doc system has grown more authoritative in
tone than the accuracy of its claims warrant. Docs guide spec-driven development;
they are not absolute blockers. Contradictions are flagged as improvement points,
not silently reconciled. When a decision is needed to move forward, it is elevated
with questions grouped in natural batches.

---

## §1 Vision & Problem Statement

M8 proved the pipe. A player walks up to an NPC, types a question, gets a live
Claude response with typewriter rendering via OAuth SDK auth. The bridge works —
and immediately reveals its limits: it's one-request-at-a-time, the player is
frozen during the call, and walking away kills the interaction.

The next evolutionary step is **domain-scoped sessions.** Instead of one blocking
request, the bridge manages long-lived sessions scoped to departments (domains).
Engineering agents share a session boundary. The player can walk away and come back.
Multiple domains can run in parallel.

The current `bridge.py` doesn't get replaced — it gets a role. It becomes the
**conversation engine**, one of two bridge engines:

| Engine | Handles | Model tier | Session model |
|---|---|---|---|
| **Conversation engine** (evolved `bridge.py`) | NPC chat, story content, background agent presence | Fast/cheap (Haiku) | Stateless single-request |
| **Domain session engine** (new) | Real engineering work, task execution, multi-agent coordination | Full capability (Opus/Sonnet) | Persistent, domain-scoped |

Both engines live in Layer 3. Both obey D-005 (zero UI awareness). The frontend
doesn't know which engine handled a response.

---

## §2 Domain Model

A **domain** maps to the department taxonomy from D-017 — the nine departments plus
Core, each with a fixed hex tint. Not all domains are equal or simultaneous.

### Growth-locked to storyboard

The tutorial gates which domains are active. Each active domain is a running process
boundary with real resource cost.

| Phase | Active domains | Storyboard gate |
|---|---|---|
| Day 1 | Engineering | SB-05 (meet Systems Architect) |
| Day 2–3 | + Project Management | Natural fit — orchestration, task tracking |
| Day 3–4 | + Executive (Board Meeting event) | Foreground takeover → fades to background |
| Day 4–5 | + Product/Marketing | Background slot |
| Post-tutorial | + Security (splits from Engineering) | When story/system are ready |
| Free play | All 9 available | Player-driven activation |

### Domain boundaries

**Domain activation is a game state event**, not a bridge concern. The frontend tells
the bridge "activate domain X" — the bridge doesn't know *why*. D-005 at work: the
bridge knows domain IDs and activation state, never storyboard beats or game progress.

**A domain is not 132 individual agent sessions.** It's a shared process boundary for
agents within a department. The Systems Architect and DevOps Engineer share the
Engineering domain session — they can reference each other's context, hand off work,
and coordinate without routing through the UI.

---

## §3 Session Lifecycle

A domain session has five states:

```
INACTIVE → ACTIVATING → ACTIVE → BACKGROUNDED → DEACTIVATED
                          ↑           │
                          └───────────┘  (player refocuses)
```

**INACTIVE** — Domain exists in config but isn't running. No resources consumed.
Every domain before its storyboard gate fires.

**ACTIVATING** — The frontend sent an activation request. The bridge is spinning up
the session: loading agent definitions for that domain, initializing the runtime,
establishing the process boundary. Short-lived transitional state.

**ACTIVE** — The domain session is running and the player is interacting with an
agent in this domain. Queries are processed at full capability. Responses return
and queue for typewriter.

**BACKGROUNDED** — The player walked away (broke focus). Key behavior: **in-flight
queries keep running.** The session accumulates output into a buffer. On refocus,
buffered output replays via the typewriter effect. New queries from other systems
(game events, inter-domain coordination) can still arrive.

The bridge tracks a **resume cursor** per domain — the last output position the
frontend consumed. On refocus, the frontend sends "resume from cursor X" and gets
everything since.

**DEACTIVATED** — Session torn down, resources freed. Only on explicit game events
or system pressure. Session state can be persisted for reactivation.

### Conversation engine has none of this

The conversation engine stays stateless request/response. An NPC chat outside an
active domain session goes through the conversation engine — fire and forget, Haiku
model, no background state.

### Frontend surface

A domain has a `state` field and an `unread_count`. That's the bridge's entire UI
surface. The frontend decides how to render that — D-005 holds.

---

## §4 Runtime Evaluation

Three candidates for the domain session engine runtime.

### What domain sessions require

- Long-lived agent processes (not one-shot API calls)
- Tool use (file read/write, shell commands, MCP servers)
- Agent-to-agent coordination within a domain
- Timeout and error recovery
- Session state that survives focus changes
- Future: worktree isolation, claim system integration

### Candidate 1: Anthropic Messages API (current approach, scaled up)

Wrap `client.messages.create()` in a session manager.

| Strength | Weakness |
|---|---|
| Known, working, proven in M8 | No native tool use loop |
| Simple mental model | No agent-to-agent coordination primitives |
| Full control over every call | Session management entirely DIY |
| Works with OAuth tokens today | Scaling = building an agent framework from scratch |

**Verdict:** Right for the conversation engine (which it already is). Wrong foundation
for domain sessions.

### Candidate 2: Claude Agent SDK (`claude-agent-sdk==0.2.136`)

Purpose-built for agent processes. Native agent loop, tool use, MCP integration,
structured output.

| Strength | Weakness |
|---|---|
| Native agent loop with tool use | Newer, less battle-tested |
| MCP server integration built-in | Per-agent, not per-domain — needs domain boundary wrapper |
| Structured output, conversation history | Auth model may differ from bridge's OAuth flow |
| Designed for this problem class | Adds dependency beyond raw Anthropic SDK |

**Key design point:** The SDK is agent-scoped. The domain session manager instantiates
SDK agents within a domain boundary and coordinates them — the SDK handles the agent
loop, the domain manager handles the boundary.

### Candidate 3: Claude Code as subprocess

Spawn `claude` CLI processes per domain with worktree cwd.

| Strength | Weakness |
|---|---|
| Full Claude Code capability set | Subprocess management is heavier |
| Worktree isolation is natural | Harder to coordinate programmatically |
| MCP, tool use, multi-agent built in | Output capture needs stdout/stderr parsing |
| Auth handled by Claude Code's flow | Less programmatic control than SDK |

**Natural fit for Phase 3:** Maps to the worktree-per-domain model. Each domain is
"a Claude Code session doing engineering work in its own branch."

### Recommendation: Hybrid

```
Layer 3 — Bridge
├── Domain Session Manager (new)
│   ├── Engineering Domain → Agent SDK runtime
│   ├── PM Domain → Agent SDK runtime
│   └── Executive Domain → Agent SDK runtime
├── Conversation Engine (evolved bridge.py)
│   └── Messages API — stateless, Haiku, NPC chat
└── Protocol layer (shared WebSocket, message routing)
```

**Agent SDK for domain sessions** — programmatic control over agent processes, tool
permissions, structured output, MCP integration, all from Python.

**Messages API for conversation engine** — one-shot Haiku calls for personality-driven
NPC interactions. Already working, already right.

**Claude Code subprocess for Phase 3** — worktree-isolated engineering. Addition to
the SDK-based domain manager, not replacement.

---

## §5 Architecture Layers

The 4-layer model stays intact. Domain sessions live entirely in Layer 3:

```
Layer 4 — Real agent execution     (EXISTS)
  Claude API, MCP servers, tools, file system

Layer 3 — Bridge                   (EVOLVING)
  ┌─────────────────────────────────────────────────┐
  │  Protocol Layer (WebSocket server)              │
  │  ├── Message routing (domain vs conversation)   │
  │  ├── Resume cursor tracking                     │
  │  └── Unread count management                    │
  │                                                 │
  │  Domain Session Manager          (NEW)          │
  │  ├── Session lifecycle (5 states)               │
  │  ├── Agent SDK runtime per domain               │
  │  ├── Output buffer (backgrounded accumulation)  │
  │  ├── Agent coordination within domain           │
  │  └── [Phase 3] Claim registry, worktree mgmt   │
  │                                                 │
  │  Conversation Engine             (EVOLVED)      │
  │  ├── Messages API, stateless                    │
  │  ├── Haiku model, NPC chat / story content      │
  │  └── Low-cost background agent replies          │
  └─────────────────────────────────────────────────┘

Layer 2 — Current frontend        (PARTIAL)
  2.5D Godot client
  Knows: domain IDs, session states, unread counts, output text
  Doesn't know: which engine handled a response

Layer 1 — Data + config           (EXISTS)
  agents.json (Godot), bridge/agents/ (bridge store, D-029)
```

### Extended Protocol

Exercising D-014 — we're post-M8, the protocol can formalize:

```json
// Domain session request
{
  "type": "domain_query",
  "domain_id": "engineering",
  "agent_id": "systems-architect",
  "task": "Review the auth middleware",
  "request_id": "uuid"
}

// Conversation request (backward-compatible with current protocol)
{
  "type": "conversation",
  "agent_id": "security-auditor",
  "task": "What's your take on the new hire?",
  "request_id": "uuid"
}

// Resume after backgrounding
{
  "type": "resume",
  "domain_id": "engineering",
  "cursor": "last-seen-output-id"
}

// Response (both engines use the same shape)
{
  "agent_id": "systems-architect",
  "task": "Review the auth middleware",
  "output": "Looking at the middleware...",
  "status": "ok",
  "domain_id": "engineering",
  "request_id": "uuid",
  "output_id": "monotonic-id"
}

// Domain state notification (bridge → frontend, push)
{
  "type": "domain_state",
  "domain_id": "engineering",
  "state": "backgrounded",
  "unread_count": 3
}
```

**Backward compatibility:** A request without `type` is treated as `"conversation"`.
The existing Godot `BridgeClient` keeps working without changes until the frontend
is ready to send domain queries.

---

## §6 Claim & Worktree System (architect-for, not deliver-now)

Defines the target architecture so Phase 1 foundations don't require a tear-down.
None of this ships in Phase 1.

### Claims

A **claim** is a reservation: an agent or domain declares intent to work on
something, preventing conflicts.

```
Claim {
  claim_id: "uuid"
  domain_id: "engineering"
  agent_id: "systems-architect"
  resource_type: "file" | "task" | "story_element"
  resource_id: "bridge/bridge.py" | "PLZG-201" | "SB-05"
  granted_at: timestamp
  expires_at: timestamp
  status: "active" | "released" | "expired"
}
```

**Rules:**
- One claim per resource at a time. Second claimant gets a rejection with the
  current holder's identity.
- Claims expire. A crashed agent doesn't permanently lock a file.
- Claims are domain-scoped by default — agents within the same domain coordinate.
  Cross-domain claims are visible but not modifiable.
- The claim registry lives in the domain session manager, not in any agent.

### Worktree Isolation

Each active engineering domain gets its own git worktree:

```
repo/                          # main checkout
.worktrees/
  engineering/                 # git worktree for Engineering domain
  pm/                          # git worktree for PM domain
```

Multiple agents in the same domain share a worktree (coordinated by claims).
Different domains get different worktrees (isolated by git). Worktrees share the
git object store (cheap) with independent working trees and indexes (isolated).

**Phase 3 may spawn Claude Code processes** with `cwd` set to the domain's worktree.
The Agent SDK handles the agent loop; the worktree handles the filesystem boundary.

### Phase 1 accommodation

Three concrete requirements on Phase 1's data model:

1. Domain session object has a `claims: list` field (always empty in Phase 1)
2. Domain session config has an optional `worktree_path: str | None` (always None)
3. File operations use `self.base_path` not hardcoded paths (defaults to repo root)

No claim logic, no worktree management, no cross-domain coordination. Just the
hooks so Phase 3 isn't a rewrite.

---

## §7 Conversation Engine (evolved bridge.py)

The current `bridge.py` becomes the lightweight interaction engine for everything
that doesn't need a full agent process.

### What it handles

| Use case | Why conversation engine, not domain session |
|---|---|
| NPC small talk | No tool use or session state needed |
| Story-driven dialogue | Scripted/semi-scripted narrative content |
| Background agent presence | Agents "hanging out" — alive, not working |
| Inactive domain agents | Player talks to PM agent before PM domain activates |

### What changes from today's bridge.py

1. **Model selection.** Defaults to Haiku instead of `claude-opus-4-6`. The protocol
   layer can pass a `model` hint for exceptions.
2. **System prompt enrichment.** Adds lightweight context: department, colleagues,
   player's recent activity (passed in the request, not stored by the bridge).
3. **Message routing integration.** Becomes one of two handlers behind the protocol
   layer's router. Requests without `type` or with `type: "conversation"` land here.
4. **No architectural changes.** Stays `client.messages.create()`. Stays synchronous.
   Stays stateless. The simplicity is the point.

### Cost model

- Walk through office, chat with 5 agents → 5 Haiku calls, pennies
- Sit down with Systems Architect for code review → 1 domain session, Opus/Sonnet
- 3 backgrounded domains with auto-replies → Haiku, queued, negligible

The conversation engine is what makes a 132-agent office feel alive without
bankrupting the token budget.

---

## §8 Phase Plan

Three phases, each a demoable milestone.

### Phase 1: Persistent Domain Sessions (deliver now)

**Demo:** Player walks up to Systems Architect, asks "review the auth middleware."
Player walks away. Comes back 30 seconds later. The response typewriter-prints from
where it left off. Meanwhile, a conversation with Security Auditor in the hallway
got a Haiku reply instantly.

**Delivers:**
- Protocol layer with message routing (`domain_query` vs `conversation`)
- Domain session manager with lifecycle (INACTIVE → ACTIVE → BACKGROUNDED → ACTIVE)
- One Agent SDK runtime per active domain
- Output buffer with resume cursor
- Domain state notifications to frontend (`state`, `unread_count`)
- Conversation engine (bridge.py with model selection + routing integration)
- Backward-compatible — current Godot client works without changes

**Does not deliver:**
- No inter-agent coordination (agents in a domain work independently)
- No claims (empty `claims: []` in data model)
- No worktrees (`worktree_path: None`)
- No cross-domain anything
- Domain activation is manual/hardcoded — storyboard gating is frontend concern

### Phase 2: Multi-Agent Coordination (extend)

**Demo:** Player asks Systems Architect to "set up the deployment pipeline."
Architect delegates Terraform work to DevOps Engineer within the Engineering domain
session. Player sees both agents' output, attributed correctly.

**Delivers:**
- Agent-to-agent messaging within a domain boundary
- Task delegation and status tracking within a domain
- Shared context — agents in a domain reference each other's recent work
- Domain-scoped MCP server integration (shared tool access)

### Phase 3: Claims, Worktrees & Full Model (complete)

**Demo:** Engineering and PM domains both active. Engineering's Systems Architect
claims `bridge.py` for a refactor. PM's Scrum Master updates `specs/task-tracker.md`
in its own worktree — no conflict. Executive domain enters via Board Meeting event,
takes foreground, then fades to background with auto-replies.

**Delivers:**
- Claim registry with grant/reject/expire lifecycle
- Git worktree provisioning per engineering domain
- Cross-domain visibility (PM can see Engineering's claims)
- Claude Code subprocess integration for worktree-isolated engineering
- Domain activation API (frontend sends activation events, storyboard-gated)
- Executive board-meeting mode (foreground takeover → background fade)

### D-005 Compliance Across All Phases

The swap test holds at every phase:

| Concept | Bridge knows | Bridge doesn't know |
|---|---|---|
| Domain | ID string, activation state | Floor, color, map position |
| Agent | ID string, definition text | Sprite, position, proximity trigger |
| Focus change | "resume from cursor X" | That the player walked away from NPC |
| Board meeting | "domain X requests foreground priority" | That it's a cutscene |
| Unread output | Count and cursor position | Notification badge, typewriter |

A CLI frontend sending the same messages gets the same behavior.

---

## §9 Open Questions

### Block Phase 1 implementation planning

1. **Auth flow for Agent SDK.** The current bridge resolves OAuth tokens via env vars
   (`CLAUDE_CODE_OAUTH_TOKEN` etc.). The Agent SDK may have its own auth model. Needs
   a spike during implementation — named as a known risk.

2. **WebSocket server evolution.** Current bridge uses raw `websockets` library. The
   protocol layer adds routing, push notifications, resume cursors. The venv already
   has `starlette` + `uvicorn` — pragmatic choice deferred to implementation plan.

### Block Phase 2, name now

3. **Agent SDK scoping.** The SDK is agent-scoped; domain sessions are
   department-scoped. The mapping is "domain session manager instantiates N SDK agents
   within a domain boundary." Is there an SDK-native way to coordinate multiple
   agents, or is that our code? Investigate during Phase 1.

4. **MCP server topology.** One shared MCP server per domain? Per agent? Affects tool
   access isolation and resource usage. Falls out of SDK evaluation.

### Don't block, worth recording

5. **Domain configuration source.** Which agents belong to which domain comes from
   `data/agents.json` (`dept` field). The bridge agent store (`bridge/agents/`) doesn't
   carry department metadata today. D-029 says the bridge owns its store — leaning
   toward enriching the bridge store.

6. **Metrics and observability.** Token spend per domain, per engine, per session. Not
   Phase 1, but the data model should carry hooks (timestamps, token counts).

---

## Appendix A: Brainstorm Traceability

Maps each of the 12 extracted ideas from the Confluence brainstorm to where they
land in this spec.

| Brainstorm item | Spec section | Phase |
|---|---|---|
| Background Execution and Focus-Resume Output | §3 Session Lifecycle (BACKGROUNDED state) | 1 |
| Bridge-Layer Session Orchestration | §5 Architecture Layers (Protocol + Domain Session Manager) | 1 |
| Domain-Based Agent Grouping | §2 Domain Model | 1 |
| Agent Claims and Worktree Isolation | §6 Claim & Worktree System | 3 |
| Progressive Domain Expansion | §2 Growth-locked to storyboard | 1 (config) / 3 (activation API) |
| Executive Board-Meeting Mode | §8 Phase 3 | 3 |
| Low-Cost Background Agent Replies | §7 Conversation Engine | 1 |
| Bounded Parallel Background Domains | §3 Session Lifecycle (resource management) | 1 |
| Attention and Blocking-Component Prioritization | §8 Phase Plan (phased delivery) | All |
| Persistent Agentic Workflow Harness | §4 Runtime Evaluation (Agent SDK recommendation) | 1–3 |
| 2.5D Virtual Office Agent Experience | Out of scope — frontend (Layer 2) | — |
| Synchronized UI, Storyboard, and Runtime Evolution | §2 Growth-locked to storyboard | All |
