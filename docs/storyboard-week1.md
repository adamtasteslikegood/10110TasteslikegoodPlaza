---
doc_id: STORYBOARD-W1
title: 10110 TastesLike Plaza — Week 1 Storyboard
tier: 1
authority: concept
status: ACTIVE
doc_set_version: 0.2.9
last_updated: 2026-04
owner: adamtasteslikegood
derives_from: []
decides: [D-002, D-008, D-009, D-010, D-019]
---

# 10110 TastesLike Plaza — Week 1 Storyboard

> The tutorial arc. Every scene has a dual purpose: game narrative layer + real onboarding layer.
> Details can evolve and be swapped out as the story develops — this outline is the spine.

---

## Dual-purpose scene map

| Game layer | Real layer |
|---|---|
| Player arrives at empty office | User initializes workspace |
| Meet the receptionist / Core agent | First agent interaction / CLI intro |
| Tour the Engineering floor | Discover 60+ engineering roles |
| Hire / meet first employee | Configure / invoke first subagent |
| First project sprint | Real task delegation via agent |
| Tutorial "business" generating output | Actual agent output piping in |

---

## Day 0 — Friday Evening: "The Call Before the Keys"

**Setting:** Player at home / last remote session. Video call comes in.
**Mood:** Nostalgic, excited, slightly nervous. End of an era; beginning of something real.

### Scene 1 — Founder's video call · `SB-01`
- **Type:** Cutscene
- **Characters:** Founder NPC
- **Beat:** Founder recaps the journey — pizza sessions, late commits, rotating locations, remote standups. "Tomorrow we get real offices." Introduces the building name: 10110 TastesLike Plaza. Sets emotional stakes: this is a real company now.
- **Real layer:** Establishes context for what the workspace is and why it matters.
- **Notes:** Warm, conversational tone. Not a corporate intro. Two people who built something together.

### Scene 2 — Meet your assistant · `SB-02`
- **Type:** Tutorial / onboarding gate
- **Characters:** In-world assistant (nav guide — NOT an agent NPC)
- **Beat:** After the call, a chat window appears. The assistant introduces itself and explains its role: navigating the office, managing schedule, checking on tasks. This is the player's always-on companion — separate from the agent characters.
- **Real layer:** Introduces the assistant UI that will eventually route to a real API.
- **Unlock:** Assistant chat UI activated.
- **Notes:** Tone should be warm and slightly playful, not robotic. Name TBD — worth designing intentionally.

### Scene 3 — Keys in hand (preview pan) · `SB-03`
- **Type:** Cinematic (no interaction required)
- **Beat:** Brief 3D flyover of the empty building exterior at night. Lights off except the lobby. Text overlay: "10110 TastesLike Plaza — move-in day tomorrow."
- **Real layer:** World reveal. Sets visual tone.
- **Notes:** This is the vibe-setter. Take time with the lighting and sound design even in the grey-box version.

---

## Day 1 — Saturday Morning: "First Keys, Empty Halls"

**Setting:** Player arrives solo. Building is mostly empty. Only 3 Core agents present — unpacking.
**Mood:** Quiet, exploratory, slightly eerie in a good way. The space is full of potential.
**Mechanic focus:** Movement controls. Free exploration. No tasks yet.

### Scene 4 — Lobby arrival · `SB-04`
- **Type:** Exploration
- **Beat:** Player enters the lobby. Box maze, covered furniture, cable runs on the floor. Assistant narrates via chat: "This is yours now. Want a quick tour?" — player can accept or explore freely.
- **Unlock:** Movement tutorial (optional).
- **Notes:** The offer-to-tour should feel optional, not mandatory. Some players will just explore.

### Scene 5 — Meet the Systems Architect · `SB-05`
- **Type:** Dialogue
- **Characters:** `systems-architect` (Core agent)
- **Location:** Server room
- **Beat:** Core agent #1 found in the server room, cable in hand. Brief intro: "I design how everything connects." First taste of agent-as-character interaction pattern.
- **Notes:** This scene establishes the interaction template that all future NPC meetings follow.

### Scene 6 — Security Auditor at the door · `SB-06`
- **Type:** Dialogue
- **Characters:** `security-auditor` (Core agent)
- **Beat:** Security Auditor is walking the building's access points. Mentions needing to review configs before the full team arrives. Plants the seed for a real task later.
- **Real layer:** Foreshadows the config review task that will be the player's first real agent delegation.

### Scene 7 — Your office (setup prompt) · `SB-07`
- **Type:** Player choice
- **Location:** Player's personal office
- **Beat:** Player finds their office. Desk, chair, blank walls. Assistant asks: "Want to set up your workspace?" — first configuration moment. Name the company, pick a domain color tag, set preferences.
- **Unlock:** Player config / persona.
- **Notes:** Keep this lightweight. 2–3 choices max. More can be unlocked later.

---

## Day 2 — Monday: "Doors Open, Team Trickles In"

**Setting:** Department leads arrive one by one. Each arrival is an event.
**Mood:** Busy, exciting, slightly chaotic. Real company energy for the first time.
**Mechanic focus:** Meeting NPCs. Understanding what each department does.

### Scene 8 — Engineering floor opens · `SB-08`
- **Type:** Event
- **Characters:** `backend-architect`, `python-specialist`, `js-specialist` (+ 1–2 others TBD)
- **Location:** Floor 2
- **Beat:** Engineering floor lights up on the building map. Brief intro meeting: each character explains what they can do in one sentence. Sprint board appears on the wall for the first time.
- **Real layer:** Engineering domain becomes accessible. Sprint board introduces PM tutorial mechanic.
- **Unlock:** Engineering floor + sprint board UI.

### Scene 9 — Product Manager drops by · `SB-09`
- **Type:** Dialogue
- **Characters:** `product-manager-orchestrator`
- **Location:** Player's office
- **Beat:** PM knocks, enters, drops a roadmap on the desk. "We should align on Week 1 priorities." This introduces the task/delegation mechanic — player assigns their first task to an agent.
- **Real layer:** First actual agent task delegation. This is the core loop working for the first time.
- **Unlock:** Task delegation mechanic.

### Scene 10 — Design lead hallway run-in · `SB-10`
- **Type:** Encounter (organic, not scripted meeting)
- **Characters:** `ui-designer`
- **Location:** Design floor corridor
- **Beat:** Player passes the design floor, Design lead is pinning mood boards. Quick intro. "When you're ready to make this place look less like a warehouse, find me."
- **Unlock:** Design floor (locked until a task is completed).
- **Notes:** Keep this brief and memorable. This character should have a strong personality.

### Scene 11 — End of day assistant debrief · `SB-11`
- **Type:** Tutorial
- **Beat:** Assistant summarizes Day 2: who you met, what's unlocked, what's pending. Introduces schedule view and message inbox. Player sees first "completed task" report from an agent.
- **Real layer:** First agent output appears in the game world (even if scripted in the prototype).
- **Notes:** This is the moment the game starts feeling like a real tool, not just a game.

---

## Day 3 — Tuesday: "First Real Sprint"

**Setting:** Player runs their first actual workflow.
**Mood:** Focused. Work mode. The novelty wears off slightly and the actual job begins.
**Mechanic focus:** Task assignment, tracking, and completion with visible output.

### Scene 12 — Morning standup (war room) · `SB-12`
- **Type:** Cutscene / interactive
- **Characters:** Engineering team + PM
- **Location:** War room / meeting room
- **Beat:** First morning standup. Player chairs it. Each character gives a one-line status. Player assigns a real task — code review or architecture review — to an agent. This is the PM tutorial moment.
- **Real layer:** Player actually configures and invokes an agent for the first time via game UI.
- **Unlock:** Task tracking board.

### Scene 13 — Coding lesson (language lab) · `SB-13`
- **Type:** Tutorial
- **Characters:** Language specialist (player's choice of language)
- **Location:** Language lab room
- **Beat:** Player chooses a language specialist and has a tutorial coding session. The specialist walks through a real concept using the agent's actual capabilities. First time the game tutorial = real tool usage in a direct and visible way.
- **Real layer:** Language specialist agent is actually invoked. Output is real.
- **Unlock:** Language lab room. (16 language specialists available.)

### Scene 14 — Task result arrives · `SB-14`
- **Type:** Event
- **Beat:** The agent the player assigned work to delivers output — appears in the inbox, assistant notifies, player reviews it.
- **Real layer:** First moment real agent output enters the game world. The I/O pipe in miniature.
- **Notes:** This scene should feel significant. Consider a small celebration moment — animation, sound, acknowledgment from the PM character.

---

## Days 4–5: "Unlock Gates + Remaining Domains"

**Structure:** Completed tasks gate new floors. Each unlock is earned, not handed over.

### Unlock: Marketing floor · `SB-15`
- **Gate:** Complete first sprint task
- **Characters:** `content-creator`, `growth-hacker`
- **Beat:** Floor activates. Characters introduce reporting, social, content capabilities. Player sees first marketing report generated by an agent.

### Unlock: Research wing · `SB-16`
- **Gate:** Day 4 (time-based)
- **Characters:** `competitive-intelligence-mx`, `market-research-analyst`
- **Beat:** Research team arrives with a competitive landscape doc already prepared. Demonstrates proactive agent behavior — agents can surface insights unprompted.

### Unlock: AI/Automation floor (the engine room) · `SB-17`
- **Gate:** Complete coding lesson
- **Characters:** `ai-engineer`, `automation-architect-aa`
- **Beat:** Meta-layer scene. These characters explain how the agents actually work. Introduces orchestration, MCPs, and pipelines in plain language through dialogue. The "explain the game's own engine" moment.
- **Unlock:** CLI pipe intro (Phase 2 gate).

### Scene — End of Week 1 founder check-in · `SB-18`
- **Type:** Cutscene
- **Characters:** Founder NPC (returns from Day 0)
- **Beat:** Founder calls again. Reviews what the player accomplished. "Now we build something." Sets up Week 2 — real product work, real agent pipelines, real output. Tutorial arc closes here.
- **Unlock:** Full office + free play mode. Tutorial complete.

---

## Scene type key

| Label | Meaning |
|-------|---------|
| Cutscene | Non-interactive narrative moment |
| Exploration | Player moves freely, no required interaction |
| Dialogue | Triggered conversation with NPC |
| Encounter | Organic hallway / accidental meeting |
| Tutorial | Guided instruction + mechanic introduction |
| Player choice | Configuration or decision moment |
| Event | Something happens in the world (not initiated by player) |
| Cinematic | Camera-controlled fly-through or pan |

---

## Still to define

- [ ] In-world assistant name and personality
- [ ] Company name for the tutorial startup
- [ ] Player character name / customization depth
- [ ] Specific dialogue scripts for Day 0 and Day 1
- [ ] Sound design / music direction
- [ ] Visual style for grey-box vs final art

---

*Last updated: April 2026*
