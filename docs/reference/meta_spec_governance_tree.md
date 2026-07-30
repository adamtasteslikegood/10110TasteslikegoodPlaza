---
doc_id: GOVERNANCE-TREE
title: Meta-specs — the governed tree
tier: 4
authority: summary
status: ACTIVE
doc_set_version: 0.2.9
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [META-SPEC]
---

# Meta-specs — the governed tree

> **Authority: none.** This is a visual restatement of the tier ladder that
> `specs/meta/META-SPEC.md` owns. Where this diagram and META-SPEC disagree,
> META-SPEC wins and this file is the bug.

## The governed tree:

```graph
GOVERNED SURFACE  =  rglob("*.md") over  docs/  specs/  Docs/   +  root README.md
                     └─ only .md. .html/.svg/.pptx are invisible.

  tier 0   constitution ├── specs/meta/META-SPEC.md          the ladder, authority vocab,
   meta                 ├── specs/meta/concept-driver.md      conflict protocol
   layer                ├── specs/meta/decision-register.md   every D-nnn
     │                  └── specs/meta/spec-drivers-v0.2.5.md open-conflict register
     │      summary     └── specs/meta/README.md
     ▼                        rules about documents — NEVER product decisions
  tier 1   concept      └── docs/storyboard-week1.md         SB-01..SB-18, sole concept origin
     ▼
  tier 2   implementation ├─ docs/designs/2.5D-RPG-Prototype.md    active design
     │                    └─ docs/designs/platform-decisions.md    D-003/005/015/016/018/021-024
     │     taxonomy       └─ docs/agent-directory.md               D-017, all agent counts
     │     derived        └─ README.md                             reconciles, decides nothing
     ▼
  tier 3   derived       ├── specs/roadmap.md
     │                   ├── specs/task-tracker.md
     │                   └── specs/branching-strategy.md
     ▼
  tier 4   summary       ├── docs/README.md  specs/README.md  docs/quick-reference.md
           research      ├── specs/aligned-spec-v0.2.5.md     SUPERSEDED — cite, don't obey
           historical    └── Docs/files/README.md

                          LOWER TIER WINS

  exempt[] — .md inside the surface that is not a spec (all 5 are root files):
      CLAUDE.md · CONTRIBUTING.md · QUICKSTART.md · CHANGELOG.md · report.md
      reasons given: "process, not specification" / "machine-written, not authored"

  never scanned at all:
      .claude/   scenes/   autoload/   tests/   scripts/   data/   bridge/
      docs/assets/*.html  *.svg  *.pptx        ← non-.md

```

```graph
  ✗ currently failing:
      docs/assets/Agile Explained - The Untold Story of the Story/
        ├── Agile_Expaiined.md                 unregistered .md  → FAIL
        ├── agile_a_practical_explaination..md byte-identical dup → FAIL
        ├── Agile_like_im_5.md                 unregistered .md  → FAIL
        ├── agile-explained.pptx               invisible — fine
        ├── agile-interactive.html             invisible — fine
        └── agile-interactive-offline.html     invisible — fine
```

**This would look good with a mermaid or other flow-diagram**
