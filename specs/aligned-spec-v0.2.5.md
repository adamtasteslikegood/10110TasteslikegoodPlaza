---
doc_id: ALIGNED-SPEC-025
title: Aligned Specification Set v0.2.5 (research input)
tier: 4
authority: research
status: SUPERSEDED
doc_set_version: 0.2.12
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: []
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: The repository confirms there is no Godot project and no `agents.json` yet.
---

# 10110 TastesLike Plaza — Aligned Specification Set v0.2.5

> ## ⚠️ This document is a research input, not the source of truth
>
> Its normative content was promoted into the meta layer and now lives there:
> the document hierarchy and binding agent rules in
> [`meta/META-SPEC.md`](meta/META-SPEC.md), the locked decisions in
> [`meta/decision-register.md`](meta/decision-register.md), the concept contract
> and scene index in [`meta/concept-driver.md`](meta/concept-driver.md).
>
> **§01.3 is superseded.** Its 14-scene spine was a reconstruction written when
> the real storyboard could not be retrieved, and it does not match
> [`../docs/storyboard-week1.md`](../docs/storyboard-week1.md) — it omits Day 0
> entirely, moves the assistant's introduction, drops the player-configuration
> and coding-lesson beats, and invents an RA/QM department scene from deferred
> scope. The side-by-side reconciliation is in
> [`meta/concept-driver.md`](meta/concept-driver.md) §4.
>
> Everything else here — the findings, the ecosystem survey, the Document A
> bridge architecture, the Document B taxonomy, and the caveats — is retained as
> rationale worth citing. Cite it as research (`ALIGNED-SPEC-025`); do not quote
> it as law.

 
## TL;DR
 
- The Plaza repo has already made the two decisions this doc set must ratify: `docs/designs/2.5D-RPG-Prototype.md` (status `PROMOTED`, dated 2026-04-27) pivots the prototype from 3D first-person to 2.5D top-down, and `CLAUDE.md` names a synchronous Python WebSocket bridge as Layer 3 — so v0.2.5’s real job is to resolve the two-doc-tree conflict, elevate the Week 1 Storyboard to source-of-truth, and encode the UI-agnostic bridge rule.
- The office-department metaphor is grounded in real inventory: the wired-in agent layer is the `adamtasteslikegood/claude-code-tresor` submodule (133 agents across 10 categories), while the broader `alirezarezvani/claude-skills` (v2.11.1, 355 skills / 18 domains) supplies the taxonomy the floors should mirror.
- This is the aligned v0.2.5 set: a META-SPEC (“specs for specs”), revised outlines for 00–04, a conceptual UI-agnostic bridge ARCHITECTURE, and a department→floor taxonomy — all formatted for direct lift into Confluence pages and Jira epics.
## Key Findings
 
### 1. The Plaza repo is “mission-stated, not coded” — and that is accurate, not aspirational
 
The repository confirms there is no Godot project and no `agents.json` yet. What exists is planning docs, a working CI lint pipeline, Atlassian glue scripts (`generate_report.py`, `post_to_confluence.py`), a Gemini-CLI automation suite, and the agent layer wired as a git submodule. The repo README still pitches “a first-person 3D office world,” and the repo’s own `CLAUDE.md` flags the tension directly: two parallel doc trees “say slightly different things.” `Docs/` (capital D) is the original 3D-first-person set; `docs/designs/` (lowercase) is the newer 2.5D scope-reduction that supersedes it.  This is exactly the conflict v0.2.5 exists to resolve.
 
### 2. The 2.5D + synchronous-bridge decisions are already committed in-repo
 
`docs/designs/2.5D-RPG-Prototype.md` is `PROMOTED` and carries a `/plan-ceo-review` header dated 2026-04-27.  Accepted scope: 2.5D top-down (Godot 2D, Pokémon/Stardew Valley style), one generic agent sprite color-tinted per department, one generic silhouette portrait for dialogue, a Python WebSocket bridge that enforces synchronous execution with timeout protection, a Godot typewriter effect that fakes streaming over a full JSON response, and a “Wait or Delegate” UX. Deferred: true WebSocket streaming, unique per-agent sprites, and 3D first-person. This maps cleanly onto the user’s stated “gstack session” decisions (2.5D Godot UI; 3D deferred to v2.0–3.0).
 
### 3. The four-layer architecture already isolates the UI — the bridge rule just needs to be made explicit
 
The repo defines: Layer 4 real agent execution (exists — claude-code, gemini-cli, MCP, SSH); Layer 3 I/O bridge (TODO — Python WebSocket, synchronous with timeout); Layer 2 Godot 4 engine (TODO — now 2.5D); Layer 1 data + config (exists upstream as the submodule; 137+ agent `.md` files → `agents.json`). Three Godot autoloads are specified: `AgentRegistry` (loads `data/agents.json`), `GameEvents` (signal bus: `npc_approached`, `npc_left`, `task_completed`, `floor_unlocked`), and `GameState` (tracks `unlocked_floors`, `completed_tasks`, `player_config`; gates doors). The critical-path milestones are M1 (navigate world) → M4 (proximity dialogue from `AgentRegistry`) → M8 (player question → bridge → real `claude @agent-name` CLI → response rendered).
 
### 4. The real skill inventory is large, departmentalized, and moving fast
 
- **`adamtasteslikegood/claude-code-tresor` (the wired-in submodule, the project’s canonical agent layer):** organized under `subagents/` into `core/` (8), `engineering/` (54), `design/` (7), `marketing/` (11), `product/` (9), `leadership/` (14), `operations/` (6), `research/` (7), `ai-automation/` (9), `account-customer-success/` (8) — 133 agents total as of the v2.7.0 unified structure, with a color-coding system (10 team colors) and standardized YAML frontmatter (`name`, `description`, `category`, `team`, `color`, `tools`, `model`, `capabilities`).
- **`alirezarezvani/claude-skills` (the broader library the taxonomy should echo):** v2.11.1, 355 production-ready skills across 18 domains, 602 Python tools, 731 reference guides, 99 agents, 109 slash commands, 83 marketplace plugins.  Domains include engineering (core + POWERFUL), product, marketing, c-level-advisor, project-management (with bundled Atlassian MCP), ra-qm-team (compliance), compliance-os, business-growth, business-operations, commercial, finance, research, research-ops, productivity, and markdown-html. It explicitly positions itself against gstack and recently rebuilt its product and PM routers as `context: fork` “agent-harness” orchestrators. 
### 5. Spec-driven development is a real, validated methodology — and it backs the project’s core hypothesis
 
The project’s thesis (“spec quality = AI output quality”) is the mainstream position in the spec-driven-development (SDD) movement:
 
- **GitHub Spec Kit** codifies a **Constitution → Specify → Plan → Tasks → Implement** loop (supporting 25+ agents including Claude Code, Copilot, and Gemini CLI) and states the shift plainly: *“We’re moving from ‘code is the source of truth’ to ‘intent is the source of truth.’ With AI the specification becomes the source of truth and determines what gets built… This isn’t because documentation became more important. It’s because AI makes specifications executable.”* Specs are framed *“not as static documents, but as living, executable artifacts that evolve with the project.”*
- **BMAD** (“Breakthrough Method for Agile AI-Driven Development,” creator Brian Madison; MIT-licensed at `github.com/bmad-code-org/BMAD-METHOD`) organizes 12–19 agents into agile roles (Analyst, PM, Architect, Product Owner, Scrum Master, Developer, QA, Orchestrator) across a two-phase flow (Agentic Planning → Context-Engineered Development) in which *“documents become the source of truth, code becomes temporal.”*
- **gstack** (Garry Tan, YC) uses persona-based skills moving through Think → Plan → Build → Review → Test → Ship → Reflect  with a “thin harness, fat skills”  philosophy. Tan’s `THIN_HARNESS_FAT_SKILLS.md` (created 2026-04-09) argues the models are already smart, so scaffolding should be minimal and capability should live in the skills.
- **The instruction-budget caveat is real but has two distinct sources.** The academic “curse of instructions” finding (Harada et al., 2024, benchmark *ManyIFEval*) shows prompt-level accuracy decays as roughly (instruction-level accuracy)^n — following ten simultaneous instructions succeeded only ~15% of the time for GPT-4o and ~44% for Claude 3.5 Sonnet. Separately and more practically, Garry Tan reports cutting his `CLAUDE.md` from ~20,000 lines to ~200 lines of “just pointers to documents” after “the model’s attention degraded” — the origin of the ~200-line working rule of thumb used below. (The academic paper tests ≤10 instructions and does not itself state a “150–200” ceiling; treat that number as Tan’s practitioner heuristic, not a measured limit.)
-----
 
## Details
 
The rest of this document is the **aligned v0.2.5 documentation set**, drafted for direct placement into Confluence/Jira. Each top-level section below is designed to become one Confluence page (or Jira epic). Suggested Confluence space: **TLGP** (TastesLike Plaza). Suggested Jira project: **TO** (already in use per the repo’s Atlassian scripts).
 
-----
 
## DOCUMENT 0 — META-SPEC: “Specs for Specs” (v0.2.5)
 
*Confluence page title suggestion: `00_META_SPEC — How AI Agents Read & Write Specs for the Plaza`*
 
### 0.1 Purpose & the core hypothesis
 
This project’s founding bet is that **planning/spec quality is not a precondition of AI output quality — it IS AI output quality.** Modern coding agents were “dropped into” a spec/board/agile/scrum world by the software engineers who built them, so they excel exactly there. Therefore the highest-leverage work on 10110 TLG Plaza is not code; it is the quality, hierarchy, and consistency of these specs. The Meta-Spec is the contract that makes that leverage real: it tells any AI agent (Claude Code, Codex, Gemini CLI, or a human) HOW to read, write, and update every other document in this set.
 
This is consistent with the broader industry position that “intent is the source of truth” and that specifications are “living, executable artifacts that evolve with the project.” 
 
### 0.2 The “spirit not sprint” principle
 
Rigor in service of play. The office metaphor is treated as a serious UX thesis — the socialized mental model humans already have for delegating work — not as decoration. Documents may be playful in tone; they must be rigorous in structure. A spec that is fun to read but ambiguous to an agent has failed.
 
### 0.3 Document hierarchy & the direction of truth
 
Decisions flow in ONE direction. When two documents conflict, the higher-priority one wins, and the lower one must be patched (never silently — see §0.6).
 
```
CONCEPT SOURCE OF TRUTH
   01_WEEK1_STORYBOARD.md   ← the heart. Concept & narrative decisions live here.
        │  (concept decisions flow down)
        ▼
   00_PROJECT_OVERVIEW.md   ← canonical statement of what/why + locked decisions
        │
        ▼
   02_PROTOTYPE_ROADMAP.md  ← what we build, in what order (M1→M4→M8)
        │
        ▼
   03_PM_TASK_TRACKER.md    ← granular tasks; mirrors Jira project TO
        │
        ▼
   04_QUICK_REFERENCE.md    ← one-page derived summary; never authoritative
 
IMPLEMENTATION SOURCE OF TRUTH (separate axis)
   docs/designs/*.md (promoted /plan-ceo-review outputs)
        → authoritative for HOW to build (2.5D pivot lives here)
```
 
**Rule:** The **Week 1 Storyboard is the source of truth for concept and narrative**; the **latest PROMOTED design doc is the source of truth for implementation.** `00_PROJECT_OVERVIEW` reconciles the two into a single canonical statement. If `Docs/files/00–04` (the historical 3D set) conflicts with a promoted 2.5D design, the design wins on implementation and the Storyboard wins on concept.
 
### 0.4 Versioning convention
 
- The doc SET carries a single semantic version. **This release is v0.2.5.** (0 = pre-prototype; .2 = second aligned concept revision; .5 = the alignment/reconciliation patch that resolves the two-doc-tree split.)
- First `1.0.0` is cut when the M1→M4→M8 prototype is demonstrable in-engine (matching the repo’s stated “first tag” trigger).
- 3D world work is explicitly **v2.0–v3.0** scope and MUST NOT be pulled forward into v0.x/v1.x specs except as clearly-labelled “Future / Deferred” notes.
- Every document ends with a footer: `*Doc set version: 0.2.5 · Last updated: <month> 2026*` (extends the repo’s existing `*Last updated: <month> 2026*` convention).
- Individual docs may carry a `Status:` field: `DRAFT | ALIGNED | PROMOTED | HISTORICAL`.
### 0.5 Conventions for AI-consumable specs
 
1. **BLUF headers.** Every doc opens with a one-line pitch and a “Decisions locked in this doc” table.
1. **Small, addressable sections.** Use hierarchical numbering (0.5.1) so an agent can be pointed at one section without loading the whole file — a direct mitigation of the instruction-overload problem.
1. **Decision tables over prose.** Locked decisions live in `| Decision | Choice | Reason |` tables.
1. **Every requirement carries rationale.** State not just the rule but why, so an agent regenerating work respects the constraint rather than “fixing” it.
1. **The rebuild test.** Any spec should be complete enough that a fresh agent session, given only the specs, could regenerate the intended artifact.  If it can’t, the spec is under-specified.
1. **Instruction budget (the ~200-line rule).** Keep binding/standing instructions in any single working context lean; prefer “pointers to documents” over one monolith. This follows Garry Tan’s reported practice of trimming his `CLAUDE.md` from ~20,000 lines to ~200 lines after attention degraded — and the academic *curse of instructions* finding that success on simultaneous instructions decays multiplicatively (following 10 at once succeeded only ~15% for GPT-4o, ~44% for Claude 3.5 Sonnet).
1. **Playful tone is allowed in narrative fields; forbidden in acceptance criteria.** Acceptance criteria must be machine-checkable.
### 0.6 Rules for AI agents working on this project (BINDING)
 
1. **Never violate UI-agnosticism of the bridge layer.** No document, task, or line of code may make the agent bridge (Layer 3) aware of Godot, scenes, sprites, HUD, or any UI concept. The bridge speaks in intents and results only. Violating this is a hard-fail review gate. (See Document A.)
1. **Never silently reconcile conflicting docs.** If two docs disagree, flag it to the human owner as an open question; do not pick a side unilaterally. (This rule is inherited in spirit from the repo’s own `CLAUDE.md`, which instructs: “note the inconsistency rather than silently aligning them.”)
1. **The Storyboard is sacred.** Edits to `01_WEEK1_STORYBOARD.md` are concept changes and require explicit human sign-off. Everything else aligns to it, not the reverse.
1. **Don’t invent infrastructure.** Do not reference `npm test`, `godot --headless`, or `agents.json` as if they exist. State what is runnable today.
1. **Respect the critical path.** If a change risks M1, M4, or M8, say so explicitly.
1. **2.5D is the ceiling for v0.x/v1.x.** Any 3D proposal is out of scope and must be filed as Future.
1. **Deterministic over generative where possible.** Prefer scripted/deterministic logic in tools and gates (echoing the skill library’s “algorithm over AI” principle).
1. **Cite the source doc.** When an agent makes a decision, it names which spec section authorized it.
### 0.7 How decisions flow (worked example)
 
A concept decision (“the player is a co-founder, mid-spectrum”) originates in the Storyboard → is ratified as a locked decision in `00_PROJECT_OVERVIEW` → shapes a milestone in `02_PROTOTYPE_ROADMAP` (M1 player-controller framing) → becomes tasks in `03_PM_TASK_TRACKER` / Jira TO → is summarized (non-authoritatively) in `04_QUICK_REFERENCE`. No step may originate a concept decision except the Storyboard.
 
-----
 
## DOCUMENT 00 — PROJECT_OVERVIEW (v0.2.5 revision)
 
*Status: ALIGNED. Patches the historical 3D-first-person overview to the 2.5D + UI-agnostic-bridge reality.*
 
### 00.1 One-line pitch (revised)
 
> A **2.5D office world** that is a graphical interface layer over a real AI agent workspace — the tutorial *is* the onboarding, and the characters *are* the agents. (The “next metaverse” is not a 3D world; it’s the office as a shared mental model for delegating work.)
 
**Change note:** prior pitch said “first-person 3D office world.” Per the promoted 2.5D design, “3D” → “2.5D,” and “first-person” is removed. 3D first-person is preserved as a v2.0–3.0 aspiration.
 
### 00.2 Concept
 
TastesLike Plaza is a navigable 2.5D top-down office environment (Pokémon/Stardew Valley register) rendered as an alternative GUI skin over 130+ real AI agent roles organized into departments. The graphics are deliberately “good enough” — the thesis is that the **UI organization**, not the fidelity, gives humans a way to sort out work the way we’ve been socialized: by walking into the right department and delegating to the right person. Reading a flat list of 350 skills requires a chess-master/multi-PhD mind; walking into “Engineering” and talking to a person does not.
 
### 00.3 The player (unchanged — this is a Storyboard-owned decision)
 
A co-founder / tech lead moving a remote-first startup into its first physical office. Deliberately mid-spectrum between “solo founder from scratch” (empty office) and “new hire at an established company.” Day 0: they have the keys and walk in this weekend before anyone arrives.
 
### 00.4 System architecture (4 layers, reaffirmed)
 
|Layer|Name                    |Status            |Note                                                                       |
|-----|------------------------|------------------|---------------------------------------------------------------------------|
|4    |Real agent execution    |EXISTS            |claude-code, gemini-cli, MCP, SSH                                          |
|3    |UI-agnostic agent bridge|TODO (Phase 2)    |Python WebSocket, synchronous w/ timeout; **zero UI awareness** (see Doc A)|
|2    |Frontend (2.5D Godot)   |TODO (Phase 1)    |One of several swappable frontends                                         |
|1    |Data + config           |EXISTS (submodule)|130+ agent `.md` → `data/agents.json`                                      |
 
**New in v0.2.5:** Layer 2 is reframed from “the Godot game engine” to “**the current frontend, which happens to be 2.5D Godot.**” This makes room for CLI, web, and future-3D frontends without touching Layers 3–4.
 
### 00.5 Locked decisions (v0.2.5)
 
|Decision             |Choice                                              |Reason                                                |
|---------------------|----------------------------------------------------|------------------------------------------------------|
|Rendering            |2.5D top-down (Godot 2D)                            |Sufficient; UI organization is the value, not fidelity|
|3D world             |Deferred to v2.0–3.0                                |Scope discipline (“10x check”)                        |
|Bridge UI-awareness  |Zero                                                |Enables swappable frontends; hard review gate         |
|Bridge formality     |Conceptual, not a versioned API contract yet        |Premature contracts ossify a pre-prototype            |
|Bridge execution     |Synchronous with timeout; typewriter fakes streaming|Simplicity for prototype; true streaming deferred     |
|Agent sprite         |One generic sprite, department color-tint           |Scope reduction; unique sprites deferred              |
|Player framing       |Co-founder, mid-spectrum                            |Empowering but guided (Storyboard-owned)              |
|Engine               |Godot 4 (over Three.js, Unity)                      |Free, MIT, GDScript≈Python, strong 2D                 |
|Tutorial = onboarding|Yes, same thing                                     |Completing in-game tasks configures real agents       |
|Unlock mechanic      |Completed tasks gate rooms/floors                   |Onboarding completion = world expansion               |
 
### 00.6 Attribution
 
MIT-licensed adaptation of `alirezarezvani/claude-code-tresor` via the `adamtasteslikegood/claude-code-tresor` fork (the project’s canonical agent layer). Original contributions © 2026 Adam Schoen. (Note: the repo currently shows both Apache-2.0 and MIT in different places — a licensing inconsistency to resolve as a v0.2.5 cleanup task.)
 
-----
 
## DOCUMENT 01 — WEEK1_STORYBOARD (v0.2.5 — the heart; light-touch alignment only)
 
*Status: ALIGNED. This is the source of truth for concept. Only alignment edits are permitted; narrative is preserved.*
 
### 01.1 Why this is the heart
 
The Storyboard is where game narrative and real onboarding are the same 14 scenes. Every other doc derives from it. Its function in the hierarchy: it is the ONLY document permitted to originate concept and narrative decisions. It is dual-layer by design — each scene has a **Game Layer** (what the player experiences) and an **Onboarding Layer** (what real agent capability gets configured/activated).
 
### 01.2 The dual-purpose scene contract
 
Each of the 14 scenes MUST specify:
 
- **Scene # & title**
- **Game Layer:** the in-world beat (where, who, what the co-founder does)
- **Onboarding Layer:** the real configuration/activation the scene performs (e.g., generating `agents.json`, first bridge call, unlocking a department)
- **Department(s) touched:** maps to the taxonomy in Document B
- **Milestone tie:** which of M1/M4/M8 (or later) the scene proves
- **Acceptance criteria:** machine-checkable where possible
### 01.3 Proposed 14-scene spine (v0.2.5 alignment scaffold)
 
> **Alignment note:** The repo confirms `Docs/files/01_WEEK1_STORYBOARD.md` exists and defines 14 scenes, but its verbatim body was not retrievable in this pass. The spine below is a **proposed reconstruction** consistent with the confirmed concept (co-founder walks into a new office; tutorial = onboarding; M1→M4→M8) and must be reconciled against the actual file before it is treated as authoritative. Titles/beats are provisional.
 
1. **The Keys** — Game: co-founder unlocks the empty office at dawn. Onboarding: profile/instance init (`10110 TastesLike Plaza` address created). Milestone: M1.
1. **Lights On** — Game: player walks the ground floor. Onboarding: `agents.json` generated from the submodule’s agent `.md` files. Milestone: M1/M3.
1. **The Lobby Guide** — Game: meet the scripted nav assistant (not an agent). Onboarding: tutorial framing; controls. Milestone: M1.
1. **First Knock** — Game: approach the first NPC (Operations, ground floor). Onboarding: proximity dialogue panel populated from `AgentRegistry`. Milestone: M4.
1. **The Ask** — Game: player poses a real question to the NPC. Onboarding: first live bridge call → `claude @agent-name` → typewriter response. Milestone: M8.
1. **Wait or Delegate** — Game: a longer task; player chooses to wait or send it as a background delegation. Onboarding: teaches sync-vs-delegated UX. Milestone: M8+.
1. **The Engineering Floor** — Game: unlock Engineering. Onboarding: activates the engineering agent cluster. Department: Engineering.
1. **Design & Marketing** — Game: unlock the creative floor. Onboarding: activates design + marketing clusters. Departments: Design, Marketing.
1. **Product Standup** — Game: a product NPC frames a small roadmap task. Onboarding: connects to PM tooling (Jira project TO). Department: Product.
1. **The Exec Suite** — Game: leadership floor; strategic framing. Onboarding: activates C-level advisory personas. Department: Leadership & Strategy.
1. **The Basement** — Game: AI & Automation / server room. Onboarding: reveals the bridge + core agents. Department: AI & Automation / Core.
1. **Compliance Corner** — Game: meet RA/QM. Onboarding: activates compliance skills; introduces guardrails. Department: RA/QM (see Doc B expansion).
1. **The Retro** — Game: end-of-week reflection with the team. Onboarding: session handoff / progress persistence. Milestone: cross-cutting.
1. **Grand Opening** — Game: the team “moves in”; office is live. Onboarding: full department set unlocked; player graduates from tutorial. Milestone: prototype-complete framing.
### 01.4 Alignment edits applied in v0.2.5
 
- “First-person” perspective language → top-down/2.5D throughout.
- “Floors” retained as narrative but noted as “rooms/zones” in 2.5D implementation.
- Streaming responses → typewriter-over-full-JSON (implementation alignment only; narrative unaffected).
-----
 
## DOCUMENT 02 — PROTOTYPE_ROADMAP (v0.2.5 — re-scoped for 2.5D first)
 
*Status: ALIGNED. 3D deferred to v2–3.*
 
### 02.1 Phasing
 
- **Phase 1 — Frontend (2.5D Godot):** Layer 2. Milestones M1–M4.
- **Phase 2 — UI-agnostic bridge:** Layer 3. Milestones M5–M8.
- **Phase 3+ — Alternate frontends & 3D (v2.0–3.0):** CLI/web frontends, then the “3D grand theft office space.” Explicitly out of v1.0.
### 02.2 Milestone table (M1→M4→M8 preserved)
 
|ID|Milestone                                                          |Layer|2.5D change                                                                                       |
|--|-------------------------------------------------------------------|-----|--------------------------------------------------------------------------------------------------|
|M1|Godot 4 project; player navigates world                            |2    |Top-down sprite + point-and-click nav (NavigationRegion2D / NavigationAgent2D), not FPS controller|
|M2|Rooms/zones + department color-tinting                             |2    |Generic sprite, per-dept tint                                                                     |
|M3|`data/agents.json` generated from submodule                        |1→2  |Min fields `{name, role, dept, color, tools, description}`                                        |
|M4|Proximity dialogue panel from `AgentRegistry`                      |2    |Area2D triggers `GameEvents.npc_approached`                                                       |
|M5|Bridge skeleton (ws://localhost:8765)                              |3    |Synchronous + timeout                                                                             |
|M6|Intent/result message schema (conceptual)                          |3    |No UI terms in payloads                                                                           |
|M7|“Wait or Delegate” routing                                         |2↔3  |Short blocks; long delegates                                                                      |
|M8|End-to-end: question → bridge → `claude @agent` → typewriter render|2+3  |The proof-of-concept keystone                                                                     |
 
### 02.3 Explicitly deferred (v2.0–3.0)
 
True WebSocket streaming; unique per-agent sprites; 3D first-person world; multiplayer/shared office; persistent shared memory (“gbrain”-style) across sessions.
 
-----
 
## DOCUMENT 03 — PM_TASK_TRACKER (v0.2.5 outline)
 
*Status: ALIGNED. Mirrors Jira project TO. Confluence table → Jira epics/tasks.*
 
### 03.1 Epic structure (proposed Jira epics)
 
- **TO-EPIC-A: Doc alignment (v0.2.5)** — reconcile two doc trees; resolve license inconsistency; land Meta-Spec; patch 00/01/02/04.
- **TO-EPIC-B: Data layer (M3)** — write `agents.json` generator over the submodule; schema; validation.
- **TO-EPIC-C: Frontend Phase 1 (M1–M4)** — Godot project, autoloads (`AgentRegistry`, `GameEvents`, `GameState`), 2.5D nav, dialogue panel.
- **TO-EPIC-D: Bridge Phase 2 (M5–M8)** — WebSocket server, intent/result schema, timeout, wait/delegate.
- **TO-EPIC-E: Taxonomy** — map departments→rooms per Document B; keep in sync with submodule.
### 03.2 Task template (each task)
 
`Title | Epic | Milestone tie | Source spec section | Acceptance criteria (machine-checkable) | UI-agnostic-bridge risk? (Y/N)`
 
### 03.3 Definition of Done (project-wide)
 
A task is Done when: acceptance criteria pass; no bridge UI-awareness introduced; the change is reflected upward in the correct spec; and the doc-set version footer is bumped if a locked decision changed.
 
-----
 
## DOCUMENT 04 — QUICK_REFERENCE (v0.2.5 — one page, derived, non-authoritative)
 
*Status: ALIGNED. Never the source of truth; regenerated from 00–03.*
 
- **What:** 2.5D office world = GUI over real AI agents. Tutorial = onboarding.
- **Player:** co-founder moving remote-first startup into first office.
- **Layers:** 4 exec · 3 UI-agnostic bridge · 2 frontend (2.5D Godot) · 1 data.
- **Critical path:** M1 navigate → M4 dialogue → M8 live agent call.
- **Golden rule:** the bridge never knows the UI exists.
- **Heart:** the 14-scene Week 1 Storyboard.
- **Version:** doc set v0.2.5; first `1.0` at in-engine M8.
- **Out of scope now:** 3D, streaming, unique sprites (all v2–3).
-----
 
## DOCUMENT A — ARCHITECTURE: The UI-Agnostic Agent Bridge (conceptual)
 
*Status: ALIGNED. Conceptual only — explicitly NOT a versioned API contract yet.*
 
### A.1 The one rule
 
**The bridge (Layer 3) has ZERO awareness of the UI (Layer 2).** It does not know Godot exists, does not know what a sprite/room/HUD/scene is, and never returns UI instructions. It exchanges **intents** (from any frontend) and **results** (from the agent runtime). This is what allows a CLI, a web UI, or a future “3D grand theft office space” to swap in as the frontend with zero bridge changes.
 
### A.2 Why conceptual, not a formal contract (yet)
 
At pre-prototype stage, freezing a versioned API contract would ossify decisions before M8 has taught us anything. v0.2.5 defines the bridge’s *responsibilities and boundaries* in prose; a formal, versioned schema is a post-M8 deliverable (target: v1.x). This mirrors gstack’s “thin harness, fat skills” instinct — keep the connective layer minimal and let capability live in the agents.
 
### A.3 Conceptual message flow
 
```
[ Frontend: 2.5D Godot | CLI | Web | future 3D ]
        │  intent {agent_id, prompt, mode: wait|delegate, correlation_id}
        ▼
[ Layer 3: UI-agnostic bridge ]  ── synchronous, timeout-protected
        │  spawns//invokes
        ▼
[ Layer 4: agent runtime ]  claude @agent-name / gemini-cli / MCP
        │  raw result (JSON)
        ▼
[ Layer 3 ] returns result {status, payload, timing, correlation_id}
        │
        ▼
[ Frontend ] decides how to render (Godot fakes streaming via typewriter)
```
 
### A.4 Boundary rules (binding)
 
1. Intents contain agent + task semantics only — never sprite/room/scene/HUD terms.
1. Results contain data + status only — never “show panel,” “animate,” or any render directive.
1. Rendering choices (typewriter effect, “wait vs delegate” animation) live entirely in the frontend.
1. The bridge is stateless about the UI; any UI state (unlocked rooms, progress) lives in the frontend’s `GameState`, never in the bridge.
1. Swap test: if replacing Godot with a CLI would require any bridge change, the boundary has been violated.
### A.5 Frontend-swap matrix
 
|Frontend                     |Status                     |Consumes intents?|Renders how                |
|-----------------------------|---------------------------|-----------------|---------------------------|
|2.5D Godot                   |v0.x/v1.0 (primary)        |Yes              |Dialogue panel + typewriter|
|CLI                          |Possible now (test harness)|Yes              |stdout                     |
|Web UI                       |v2.0 candidate             |Yes              |DOM                        |
|3D “grand theft office space”|v2.0–3.0                   |Yes              |3D scene                   |
 
-----
 
## DOCUMENT B — Department / Skill Taxonomy (office floors ↔ real inventory)
 
*Status: ALIGNED. Maps the 2.5D office layout to the real submodule + skills-library inventory.*
 
### B.1 Two source inventories
 
1. **Canonical for THIS project:** the `adamtasteslikegood/claude-code-tresor` submodule — 133 agents across `core, engineering, design, marketing, product, leadership, operations, research, ai-automation, account-customer-success`.
1. **Aspirational/broader mirror:** `alirezarezvani/claude-skills` v2.11.1 — 355 skills across 18 domains (adds finance, RA/QM compliance, compliance-os, business-operations, commercial, research-ops, productivity, project-management, markdown-html).
The office layout should reflect (1) for the prototype and be *extensible* toward (2).
 
### B.2 Floor / room ↔ department map (v0.2.5)
 
|Floor / Zone     |Department                |Submodule count|Tint (from repo)|Skills-library counterpart           |
|-----------------|--------------------------|---------------|----------------|-------------------------------------|
|Basement / server|Core Agents               |8              |Star            |(cross-cutting)                      |
|Basement / server|AI & Automation           |9              |Indigo `#6366F1`|engineering (POWERFUL: agent/RAG/MCP)|
|Floor 1          |Operations                |6              |Teal `#14B8A6`  |business-operations                  |
|Floor 1          |Account & Customer Success|8              |Cyan `#06B6D4`  |business-growth                      |
|Floor 2          |Engineering               |54             |Blue `#3B82F6`  |engineering (core + POWERFUL)        |
|Floor 2          |Product                   |9              |Purple `#8B5CF6`|product-team + project-management    |
|Floor 2          |Research                  |7              |Orange `#F97316`|research + research-ops              |
|Floor 3          |Design                    |7              |Pink `#EC4899`  |product-team (UX/UI)                 |
|Floor 3          |Marketing                 |11             |Green `#10B981` |marketing-skill (8 pods)             |
|Floor 4 (exec)   |Leadership & Strategy     |14             |Gold `#F59E0B`  |c-level-advisor                      |
 
### B.3 Extension rooms (map to skills-library domains not yet in the submodule)
 
Reserve future rooms for: **Finance** (finance domain), **Compliance / RA-QM** (ra-qm-team + compliance-os), **Commercial / Deal Desk** (commercial), **Productivity** (productivity). These become new floors/rooms in v1.x–v2.0 as the agent layer grows.
 
### B.4 Taxonomy sync rule
 
`data/agents.json` is generated FROM the submodule; the office layout is generated FROM the taxonomy table above. When the submodule adds/renames agents, regenerate both — never hand-edit `agents.json`.
 
-----
 
## Recommendations
 
**Stage 1 — Land the alignment (this week; TO-EPIC-A).**
 
1. Commit the Meta-Spec (Document 0) as `Docs/files/00_META_SPEC.md` and set the whole set to footer `v0.2.5`.
1. Patch `01_WEEK1_STORYBOARD.md` with ONLY the §01.4 alignment edits; do not rewrite narrative. **Before treating §01.3 as authoritative, retrieve the real 14-scene file and reconcile.**
1. Deprecate the 3D-first-person language in `Docs/files/00–04` by adding a banner: “Superseded on implementation by `docs/designs/2.5D-RPG-Prototype.md`; retained for concept history.”
1. Resolve the Apache-2.0-vs-MIT license inconsistency (pick one; the repo text says MIT).
   *Benchmark to advance:* all five core docs carry `Status: ALIGNED` and a v0.2.5 footer; no unresolved 3D-first-person implementation claims remain.
**Stage 2 — Prove the data + frontend spine (TO-EPIC-B, C; M1–M4).**
5. Write the `agents.json` generator over the submodule (M3) with the min-field schema; validate counts against the taxonomy table.
6. Stand up the Godot 4 project with the three autoloads and 2.5D point-and-click nav (`NavigationRegion2D` + `NavigationAgent2D`); land M1 then M4.
*Benchmark to advance to Stage 3:* proximity dialogue panel renders live from `AgentRegistry` for at least one department.
 
**Stage 3 — Prove the UI-agnostic bridge (TO-EPIC-D; M5–M8).**
7. Build the synchronous WebSocket bridge; define the intent/result message shape in prose (Document A), NOT as a frozen versioned contract.
8. Enforce the **swap test** in code review: any PR that leaks UI terms into the bridge fails.
9. Land M8 end-to-end with the typewriter render.
*Benchmark to cut v1.0:* M8 is demonstrable in-engine (the repo’s own stated first-tag trigger).
 
**Threshold that would change the plan:** if a formal multi-frontend need arrives earlier than v2.0 (e.g., a web demo is required for fundraising), promote the bridge’s conceptual message shape to a versioned contract at that point — but not before, to avoid premature ossification.
 
**Adopt selectively from the ecosystem, don’t rebuild it.** Borrow SDD’s Constitution→Specify→Plan→Tasks→Implement discipline (GitHub Spec Kit) and BMAD’s docs-as-source-of-truth, but keep the bridge thin (gstack’s “thin harness, fat skills”). The claude-skills library already solves the “capability” layer; the Plaza’s job is the UI-organization layer on top.
 
## Caveats
 
- **The 14-scene Storyboard body was not retrievable in this research pass.** The file is confirmed to exist at `Docs/files/01_WEEK1_STORYBOARD.md` with 14 scenes, but its verbatim content could not be opened (the repo isn’t web-indexed and direct raw-file fetches were blocked). The scene spine in §01.3 is a **proposed reconstruction**, not the actual scenes — reconcile before treating as authoritative.
- **Repo counts vary by source and are moving fast.** The submodule README historically cites “137+” agents while the v2.7.0 unified `subagents/` structure enumerates 133; `claude-skills` moved from ~337 to 355 skills within the research window. Treat all counts as point-in-time.
- **License inconsistency in the repo itself:** the GitHub page shows Apache-2.0 while README/CLAUDE.md say MIT. Flagged as a cleanup task, not resolved here.
- **“gstack session” interpretation:** the user’s “gstack session” refers to a working session whose decisions (2.5D, UI-agnostic bridge) this doc encodes. gstack itself (Garry Tan’s YC Claude Code stack) is the ecosystem reference point, not a dependency of the Plaza; claude-skills explicitly positions against it.
- **The ~150–200 instruction ceiling is a practitioner heuristic, not a measured limit.** It derives from Garry Tan’s account of trimming his `CLAUDE.md` to ~200 lines, not from the academic “curse of instructions” paper (Harada et al., 2024), which tests ≤10 instructions and reports multiplicative accuracy decay rather than a specific line ceiling.
- **Some ecosystem figures are single-source or promotional** (e.g., gstack star counts, “rebuilt a startup in 3 weeks” claims, Steve Yegge’s “1000x” productivity quote in Tan’s thin-harness doc). These are context, not load-bearing facts for the spec.
- **No versioned bridge API is proposed by design.** If a reviewer expects a formal schema in v0.2.5, that is intentionally deferred to post-M8.
