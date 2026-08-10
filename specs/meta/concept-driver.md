---
doc_id: CONCEPT-DRIVER
title: Concept Driver — the storyboard as the origin of concept
tier: 0
authority: constitution
status: ACTIVE
doc_set_version: 0.2.12
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [META-SPEC]
supersedes: []
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: those were never in dispute and are registered as
---

# Concept Driver — the storyboard as the origin of concept

> **One line:** the fiction has exactly one author of record —
> [`docs/storyboard-week1.md`](../../docs/storyboard-week1.md) — and this file is
> the contract it is held to, plus the index that makes every scene citable.

This document governs the concept axis. It does not *contain* the concept; it
points at the document that does, defines the shape each scene must take, and
gives every beat a stable id so a milestone, a task, or a Jira issue can cite
`SB-09` instead of paraphrasing a paragraph.

## 1. The origination rule

`STORYBOARD-W1` is the **only** document in the set permitted to originate concept
or narrative decisions — the story, the player, the world, the characters, the
fiction of the office.

- Every other document derives from it. None may invent a beat, a character, or a
  narrative premise and then expect the storyboard to catch up.
- Edits to `STORYBOARD-W1` are concept changes and require explicit human sign-off.
- Adding *structure* — the `SB-nn` ids in this index, contract fields, cross-links —
  is an alignment edit and is allowed without sign-off. Changing what happens in a
  beat is not.
- When a promoted design changes how a scene is *built*, the scene itself is
  untouched. Rendering is an implementation concern (`DESIGN-25D`); what the
  co-founder experiences is a concept concern (`STORYBOARD-W1`).

Why the separation is worth the ceremony: the whole product thesis is that the
tutorial *is* the onboarding. If narrative drifts from what the software actually
configures, the thesis quietly stops being true and nothing in the build fails.

## 2. The dual-purpose scene contract

Every scene is two things at once. A scene that specifies only one layer is
incomplete. Required fields:

| Field | Meaning |
|---|---|
| **Id** | `SB-nn`. Stable. Survives renumbering and reordering. |
| **Title** | The scene name as it reads in the storyboard. |
| **Type** | Cutscene · Exploration · Dialogue · Encounter · Tutorial · Player choice · Event · Cinematic. |
| **Characters** | Agent ids where the character *is* an agent; `—` for the scripted assistant and the Founder NPC. |
| **Location** | Room or zone. Narrative "floors" render as rooms/zones in 2.5D. |
| **Game layer** | What the co-founder experiences. |
| **Real layer** | What actually gets configured, generated, or activated. |
| **Unlock** | What the world opens up, if anything. |
| **Milestone** | Which of M1–M8 the scene proves. `—` if it proves none yet. |
| **Department** | Which department the scene touches, per [`docs/agent-directory.md`](../../docs/agent-directory.md). |

Two locked constraints the contract enforces, both easy to violate by accident:

- **The in-world assistant is not an agent.** It is a scripted navigation guide and
  the player's always-on companion, distinct from every agent NPC (`D-010`).
  Scenes must not blur the two.
- **Unlocks are earned, never handed over.** Completed tasks gate rooms; onboarding
  completion *is* world expansion (`D-009`).

## 3. Scene index

Ids are assigned against the real storyboard. The 14 numbered scenes span Days 0–3;
the four Days 4–5 beats are addressable too and take `SB-15`–`SB-18`.

| Id | Scene | Type | Milestone | Department |
|---|---|---|---|---|
| `SB-01` | Founder's video call | Cutscene | — | — |
| `SB-02` | Meet your assistant | Tutorial | M4 | — |
| `SB-03` | Keys in hand (preview pan) | Cinematic | M2 | — |
| `SB-04` | Lobby arrival | Exploration | **M1** | — |
| `SB-05` | Meet the Systems Architect | Dialogue | **M4** (needs M3) | Core |
| `SB-06` | Security Auditor at the door | Dialogue | M4 | Core |
| `SB-07` | Your office (setup prompt) | Player choice | M1 | — |
| `SB-08` | Engineering floor opens | Event | M2, M3 | Engineering |
| `SB-09` | Product Manager drops by | Dialogue | M7 | Product |
| `SB-10` | Design lead hallway run-in | Encounter | M2 | Design |
| `SB-11` | End of day assistant debrief | Tutorial | M4 | — |
| `SB-12` | Morning standup (war room) | Cutscene / interactive | M7 | Engineering, Product |
| `SB-13` | Coding lesson (language lab) | Tutorial | **M8** | Engineering |
| `SB-14` | Task result arrives | Event | **M8** | — |
| `SB-15` | Unlock: Marketing floor | Event | post-M8 | Marketing |
| `SB-16` | Unlock: Research wing | Event | post-M8 | Research |
| `SB-17` | Unlock: AI/Automation floor | Event | M5 (Phase 2 gate) | AI & Automation |
| `SB-18` | End of Week 1 founder check-in | Cutscene | post-M8 | — |

The critical path reads through the fiction as `SB-04` → `SB-05` → `SB-14`: walk
the lobby, talk to someone real, get real output back.

## 4. Reconciliation record — `ALIGNED-SPEC-025` §01.3

**Status: resolved. `STORYBOARD-W1` wins. §01.3 is `SUPERSEDED`.**

[`specs/aligned-spec-v0.2.5.md`](../aligned-spec-v0.2.5.md) §01.3 proposed a
14-scene spine and labelled itself, honestly, a "proposed reconstruction" because
the real file "was not retrievable in this research pass." Its own caveats section
asked for exactly this reconciliation before treating it as authoritative. The real
file was read; the two do not match.

| §01.3 proposed | Actual storyboard | Resolution |
|---|---|---|
| Opens at dawn with "The Keys" | Opens the **evening before** with the founder's video call (`SB-01`) | Day 0 is real and was missing entirely. Storyboard wins. |
| "The Lobby Guide" introduces the assistant on arrival | Assistant is introduced off-site the night before (`SB-02`) | Storyboard wins. The assistant predates the building. |
| No player-configuration beat | "Your office (setup prompt)" sets player config (`SB-07`) | Restored. This is where `GameState.player_config` originates. |
| No coding-lesson beat | "Coding lesson (language lab)" (`SB-13`) — a real agent invocation | Restored. This is an M8 proof, not optional colour. |
| "Compliance Corner" — an RA/QM department scene | No such scene | **Dropped.** RA/QM is not in the submodule's ten departments; the aligned spec's own Document B lists it as a v1.x–v2.0 *extension room*. §01.3 pulled deferred scope into the tutorial. |
| "The Exec Suite", "The Retro", "Grand Opening" | No equivalents; Week 1 closes on the founder check-in (`SB-18`) | Dropped as invented. |
| 14 beats total | 14 numbered scenes **plus** four Days 4–5 unlock beats = 18 | Index carries all 18. |

Both versions agree on the co-founder framing, tutorial-as-onboarding, earned
unlocks, and the M1/M4/M8 spine — those were never in dispute and are registered as
`D-002`, `D-008`, and `D-009` in [`decision-register.md`](decision-register.md).

**Why this mattered enough to write down:** until this pass, the document that
`CLAUDE.md`, `specs/README.md`, and `Docs/files/README.md` all called the source of
truth contained an invented version of the document *it itself* designated as the
concept source of truth. Any agent that read the aligned spec top-to-bottom and
started building would have built the wrong week.

## 5. Open concept questions

Owned by `STORYBOARD-W1` §"Still to define"; repeated here because they block
scene-level acceptance criteria and therefore block tasks:

1. The in-world assistant — name and personality.
2. The tutorial startup's company name.
3. Player character name and customisation depth.
4. Dialogue scripts for Day 0 (`SB-01`–`SB-03`) and Day 1 (`SB-05`, `SB-06`).
5. Sound design and music direction.
6. Visual style for grey-box versus final art.

These are concept decisions. Only the human owner may close them, and the close
lands in `STORYBOARD-W1` first — never here, and never in a task.

*Doc set version: 0.2.12 · Last updated: August 2026*
