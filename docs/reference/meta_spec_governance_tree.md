---
doc_id: GOVERNANCE-TREE
title: Meta-specs — the governed tree
tier: 4
authority: summary
status: ACTIVE
doc_set_version: 0.2.11
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [META-SPEC]
enforcement: asserted
gates: [Validate Specs:live]
weakest_claim: Every line of it was wrong by the time anyone read it
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
     │     taxonomy       ├─ docs/agent-directory.md               D-017, all agent counts
     │                    └─ docs/delivery-coordinates.md          D-026, every Atlassian id
     │     derived        └─ README.md                             reconciles, decides nothing
     ▼
  tier 3   derived       ├── specs/roadmap.md
     │                   ├── specs/task-tracker.md
     │                   ├── specs/branching-strategy.md
     │                   └── specs/sprint-2-charter.md      PLZG Sprint 2, decisions locked
     ▼
  tier 4   summary       ├── docs/README.md  specs/README.md  docs/quick-reference.md
     │                   └── docs/reference/meta_spec_governance_tree.md   ← you are here
     │     research      ├── specs/aligned-spec-v0.2.5.md     SUPERSEDED — cite, don't obey
     │                   ├── docs/reference/agile/Agile_Expaiined.md    onboarding reading
     │                   └── docs/reference/agile/Agile_like_im_5.md     plain-language companion
           historical    └── Docs/files/README.md

                          LOWER TIER WINS
                          tier 4 is authoritative over NOTHING — including this file

  exempt[] — .md inside the surface that is not a spec (all 5 are root files):
      CLAUDE.md · CONTRIBUTING.md · QUICKSTART.md · CHANGELOG.md · report.md
      reasons given: "process, not specification" / "machine-written, not authored"

  never scanned at all:
      .claude/   scenes/   autoload/   tests/   scripts/   data/   bridge/
      docs/assets/**  *.html  *.svg  *.pptx     ← non-.md

```

## Where the live state lives

**This diagram is a picture, not a status board.** For what is registered right
now — and whether the set currently passes — run the validator. It reads
`specs/meta/doc-registry.json`, which is the machine-readable truth this file
only illustrates:

```bash
python3 scripts/validate_specs.py
```

An earlier revision carried a hand-copied "✗ currently failing" list naming three
unregistered files under `docs/assets/Agile Explained - The Untold Story of the
Story/`. Every line of it was wrong by the time anyone read it: the duplicate was
deleted, the two guides moved to `docs/reference/agile/` and are now registered
tier 4 `research`, and that directory holds only `.pptx`/`.html`, which the
validator cannot see. The block was removed rather than corrected — **a snapshot
of transient state does not belong in a document**, because the document has no
way to notice when it stops being true. That is the same failure
[`specs/sprint-2-charter.md`](../../specs/sprint-2-charter.md) § 8 was written
about.

**This would look good with a mermaid or other flow-diagram**
