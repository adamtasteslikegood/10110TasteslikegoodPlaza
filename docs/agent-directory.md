---
doc_id: AGENT-DIRECTORY
title: 10110 TastesLike Plaza — Agent Directory
tier: 2
authority: taxonomy
status: ACTIVE
doc_set_version: 0.2.7
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [PROJECT-OVERVIEW]
decides: [D-017]
---

# 10110_TastesLikePlaza - 'Employee' Directory

> **Organized collection of 133 specialized roles for software development**
>
---

## 📚 Table of Contents

1. [Overview](#overview)
2. [Directory Structure](#directory-structure)
3. [Team Categories](#team-categories)
4. [Color Legend](#color-legend)
5. [Quick Start](#quick-start)
6. [Navigation](#navigation)
7. [Installation](#installation)

---

## Overview

This directory contains a comprehensive, team-aligned organization of 133 specialized roles covering all aspects of software development, business operations, design, marketing, and more.

### Key Features

- ✨ **9 Team Categories** - Organized by business function
- 🎨 **Color-Coded** - Visual identification system
- 📁 **Hierarchical Structure** - Easy navigation and discovery
- 🔧 **Standardized Format** - Consistent YAML frontmatter
- 🤝 **Skill Integration** - Coordination with autonomous skills
- 📊 **133 roles** - Comprehensive coverage

---

## Directory Structure

```
subagents/
├── README.md                          # This file
│
├── 🔵 engineering/                    # Engineering Team (54 roles)
│   ├── backend/
│   ├── frontend/
│   ├── mobile/
│   ├── devops/
│   ├── security/
│   ├── testing/
│   ├── data/
│   ├── languages/                     # 16 language specialists
│   ├── architecture/
│   ├── code-quality/
│   ├── performance/
│   ├── debugging/
│   └── documentation/
│
├── 🎨 design/                         # Design Team (7 roles)
│   ├── ui/
│   ├── ux/
│   ├── visual/
│   └── brand/
│
├── 🌱 marketing/                      # Marketing Team (11 roles)
│   ├── content/
│   ├── social/
│   ├── growth/
│   └── seo/
│
├── 💜 product/                        # Product Team (9 roles)
│   ├── management/
│   ├── requirements/
│   ├── research/
│   └── analytics/
│
├── 🏆 leadership/                     # Leadership & Strategy (14 roles)
│   ├── finance/
│   ├── strategy/
│   ├── risk/
│   └── compliance/
│
├── 🌊 operations/                     # Operations Team (6 roles)
│   ├── analytics/
│   ├── infrastructure/
│   ├── support/
│   └── project-management/
│
├── 🔶 research/                       # Research Team (7 roles)
│   ├── market/
│   ├── user/
│   └── data/
│
├── 🧠 ai-automation/                  # AI & Automation (9 roles)
│   ├── ai-engineering/
│   ├── ml-engineering/
│   ├── automation/
│   └── prompts/
│
├── 💙 account-customer-success/       # Account & CS (8 roles)
│   ├── account-management/
│   ├── customer-success/
│   ├── support/
│   └── sales/
│
└── ⭐ core/                           # Core roles (8 production-ready)
    ├── systems-architect.md
    ├── config-safety-reviewer.md
    ├── root-cause-analyzer.md
    ├── security-auditor.md
    ├── test-engineer.md
    ├── performance-tuner.md
    ├── refactor-expert.md
    └── docs-writer.md
```

---

## Team Categories

### 1. 🔵 Engineering (54 roles)
**Color**: Blue (#3B82F6)
**Path**: `subagents/engineering/`

**Specializations**:
- Backend Development (APIs, microservices, databases)
- Frontend Development (React, Vue, Angular)
- Mobile Development (iOS, Android, cross-platform)
- DevOps & Infrastructure (CI/CD, cloud, containers)
- Security (OWASP, secure coding, compliance)
- Testing & QA (test automation, quality assurance)
- Data Engineering (ETL, pipelines, analytics)
- Language Specialists (16 languages)
- Architecture (system design, patterns)
- Code Quality (reviews, refactoring)
- Performance (optimization, profiling)
- Debugging (RCA, troubleshooting)
- Documentation (technical writing, API docs)

**Quick Start**: see [`subagents/engineering/`](../claude-code-tresor/subagents/engineering/README.md)
in the `claude-code-tresor` submodule (run `git submodule update --init --recursive`
first — it is empty in fresh checkouts).

---

### 2. 🎨 Design (7 roles)
**Color**: Magenta/Pink (#EC4899)
**Path**: `subagents/design/`

**Specializations**:
- UI Design (interface design, design systems)
- UX Research (user research, usability testing)
- Visual Design (branding, visual storytelling)
- Brand (brand guidelines, consistency)

**Key roles**: ui-designer, ux-researcher, brand-guardian, visual-storyteller, whimsy-injector

---

### 3. 🌱 Marketing (11 roles)
**Color**: Green (#10B981)
**Path**: `subagents/marketing/`

**Specializations**:
- Content Marketing (blog posts, SEO, content strategy)
- Social Media (Instagram, TikTok, Twitter/X, Reddit)
- Growth Marketing (growth hacking, viral marketing)
- SEO & ASO (search optimization, app store optimization)

**Key roles**: content-creator, growth-hacker, instagram-curator, tiktok-strategist, reddit-community-builder

---

### 4. 💜 Product (9 roles)
**Color**: Purple (#8B5CF6)
**Path**: `subagents/product/`

**Specializations**:
- Product Management (roadmap, prioritization, strategy)
- Requirements (PRD writing, requirements gathering)
- Product Research (trend analysis, user feedback)
- Product Analytics (metrics, KPIs, dashboards)

**Key roles**: product-manager-orchestrator, sprint-prioritizer, prd-writer, feedback-synthesizer, trend-researcher

---

### 5. 🏆 Leadership & Strategy (14 roles)
**Color**: Gold (#F59E0B)
**Path**: `subagents/leadership/`

**Specializations**:
- Finance (financial analysis, investment, pricing)
- Business Strategy (strategic planning, partnerships)
- Risk Management (portfolio risk, hedging, assessment)
- Compliance & Legal (regulatory compliance, legal docs)

**Key roles**: financial-analyst-fs, business-strategist-fs, risk-manager, compliance-officer-fs, legal-advisor

---

### 6. 🌊 Operations (6 roles)
**Color**: Teal (#14B8A6)
**Path**: `subagents/operations/`

**Specializations**:
- Business Analytics (reporting, insights)
- Infrastructure Operations (maintenance, optimization)
- Support Operations (customer support, tickets)
- Project Management (delivery, tracking)

**Key roles**: analytics-reporter, infrastructure-maintainer, support-responder, studio-producer

---

### 7. 🔶 Research (7 roles)
**Color**: Orange (#F97316)
**Path**: `subagents/research/`

**Specializations**:
- Market Research (competitive intelligence, market sizing)
- User Research (experience analysis, user insights)
- Data Research (deep research, web search)

**Key roles**: competitive-intelligence-mx, market-research-analyst, tam-market-sizing-mx, search-specialist

---

### 8. 🧠 AI & Automation (9 roles)
**Color**: Indigo (#6366F1)
**Path**: `subagents/ai-automation/`

**Specializations**:
- AI Engineering (LLM applications, RAG systems)
- ML Engineering (ML pipelines, model serving, MLOps)
- Automation (workflow automation, integration)
- Prompt Engineering (prompt optimization, LLM tuning)

**Key roles**: ai-engineer, ml-engineer, mlops-engineer, ai-workflow-designer-aa, automation-architect-aa

---

### 9. 💙 Account & Customer Success (8 roles)
**Color**: Cyan (#06B6D4)
**Path**: `subagents/account-customer-success/`

**Specializations**:
- Account Management (account executives, revenue)
- Customer Success (onboarding, retention)
- Customer Support (support specialists)
- Sales Engineering (technical sales, demos)

**Key roles**: account-executive-revenue-at, customer-success-manager, sales-engineer-gr

---

### 10. ⭐ Coreroles (8 production-ready)
**Path**: `subagents/core/` or `/agents/`

**Core Productionroles**:
1. **systems-architect** - System design and architecture
2. **config-safety-reviewer** - Configuration safety specialist
3. **root-cause-analyzer** - Comprehensive RCA debugging
4. **security-auditor** - Strategic security audits
5. **test-engineer** - Comprehensive testing strategy
6. **performance-tuner** - Performance optimization
7. **refactor-expert** - Code refactoring specialist
8. **docs-writer** - Technical documentation

These are the most mature, production-ready roles with comprehensive capabilities and skills integration.

---

## Color Legend

| Team | Color | Hex Code | Emoji | Example Use |
|------|-------|----------|-------|-------------|
| **Engineering** | Blue | `#3B82F6` | 🔵 | Software development, architecture, testing |
| **Design** | Magenta/Pink | `#EC4899` | 🎨 | UI/UX design, branding, visual design |
| **Marketing** | Green | `#10B981` | 🌱 | Content, growth, social media |
| **Product** | Purple | `#8B5CF6` | 💜 | Product management, requirements, research |
| **Leadership** | Gold | `#F59E0B` | 🏆 | Finance, strategy, risk, compliance |
| **Operations** | Teal | `#14B8A6` | 🌊 | Analytics, support, project management |
| **Research** | Orange | `#F97316` | 🔶 | Market research, competitive intelligence |
| **AI/Automation** | Indigo | `#6366F1` | 🧠 | AI/ML engineering, automation |
| **Account/CS** | Cyan | `#06B6D4` | 💙 | Account management, customer success |
| **Core** | Gold | `#FFD700` | ⭐ | Production-ready core roles |

### Color Usage

Colors are used in:
- **Agent Badges** - Visual identification
- **Documentation** - Color-coded sections
- **CLI Output** - Terminal formatting
- **IDE Integration** - File icons and decorations

---

## Quick Start

### 1. Find anrole

**By Category**:
```bash
# List engineering roles
ls subagents/engineering/

# List backend roles
ls subagents/engineering/backend/

# List all roles
find subagents -name "*.md" -type f
```

**By Function**:
- Need API design? → `subagents/engineering/backend/`
- Need UI design? → `subagents/design/ui/`
- Need market research? → `subagents/research/market/`
- Need testing? → `subagents/engineering/testing/`

### 2. Initialize a character by assigning $role_from_step_1

```bash
# Use @ symbol with agent name
@systems-architect Design a scalable system for 100k users
@config-safety-reviewer Review database connection settings
@root-cause-analyzer Debug production API timeout
@security-auditor Audit authentication implementation
```

### 3. Use Skills (Autonomous Helpers)

Skills work automatically in the background:
- **security-auditor skill** - OWASP scanning
- **test-generator skill** - Test scaffolding
- **secret-scanner skill** - Credential detection
- **dependency-auditor skill** - CVE checking

$charactor invoke agent-skills automatically for quick checks before deep analysis.

---

## Navigation

### Finding the Right Agent

**Decision Tree**:

```
1. What's your task domain?
   ├─ Software Development → Engineering
   ├─ Design Work → Design
   ├─ Marketing/Content → Marketing
   ├─ Product Work → Product
   ├─ Business Strategy → Leadership
   ├─ Operations → Operations
   ├─ Research → Research
   ├─ AI/ML → AI & Automation
   └─ Customer Facing → Account & CS

2. What's your specific need?
   Engineering:
   ├─ Backend work? → engineering/backend/
   ├─ Frontend work? → engineering/frontend/
   ├─ Security? → engineering/security/
   ├─ Testing? → engineering/testing/
   ├─ Performance? → engineering/performance/
   ├─ Debugging? → engineering/debugging/
   └─ Architecture? → engineering/architecture/

3. Choose $role_Descion:
   - Read agent README for capabilities
   - Check usage examples
   - Invoke with @agent-name
```

### Category READMEs

Each category has a README inside the `claude-code-tresor` submodule, under
`subagents/<category>/`. Counts are the authoritative ones from §"Agent counts"
below.

| Category | Count | README |
|---|---|---|
| Engineering | 54 | [`subagents/engineering/`](../claude-code-tresor/subagents/engineering/README.md) |
| Leadership & Strategy | 14 | [`subagents/leadership/`](../claude-code-tresor/subagents/leadership/README.md) |
| Marketing | 11 | [`subagents/marketing/`](../claude-code-tresor/subagents/marketing/README.md) |
| AI & Automation | 9 | [`subagents/ai-automation/`](../claude-code-tresor/subagents/ai-automation/README.md) |
| Product | 9 | [`subagents/product/`](../claude-code-tresor/subagents/product/README.md) |
| Account & Customer Success | 8 | [`subagents/account-customer-success/`](../claude-code-tresor/subagents/account-customer-success/README.md) |
| Core | 8 | [`subagents/core/`](../claude-code-tresor/subagents/core/) — no README upstream |
| Design | 7 | [`subagents/design/`](../claude-code-tresor/subagents/design/README.md) |
| Research | 7 | [`subagents/research/`](../claude-code-tresor/subagents/research/README.md) |
| Operations | 6 | [`subagents/operations/`](../claude-code-tresor/subagents/operations/README.md) |

Those links resolve only once the submodule is initialised
(`git submodule update --init --recursive`); the spec validator checks them when it
is and reports them as skipped when it is not.

### Agent counts

> **141 agent files = 8 core + 133 subagents**, spanning **133 distinct roles**.

Counted 2026-07-25 at `acfb923` and re-verified 2026-07-26 at **`b7ec149`** — the
current pin, head of `10110TLGP/dev` — and at `bcfe30c` (`10110TLGP/main`). All
three give the same figures.

The `b7ec149` bump merged upstream into the fork; `git diff acfb923 b7ec149` touches
only `GETTING-STARTED.md`, and `subagents/` and `agents/` are byte-identical across
the two pins. **Re-check these numbers whenever the pin moves, but a pin bump does
not automatically invalidate them** — verify against the trees, not the commit id.

| Tree | Files | What it is |
|---|---|---|
| `subagents/<category>/…/agent.md` | 133 | The catalog. Ten categories; the office taxonomy derives from these. |
| `agents/*.md` | 8 | The production-ready core, in Claude Code's **runtime** agent format. |
| **Total files** | **141** | |
| **Distinct roles** | **133** | The core eight appear in both trees. |

**Both numbers are correct — they measure different things.** Quote 141 when you
mean files on disk; quote 133 when you mean roles, NPCs, or rows in
`data/agents.json`. Say which you mean.

Three things that make a naïve count wrong:

- Agents nest **three levels down** — `subagents/<category>/<subcategory>/<agent-name>/agent.md`.
  A `maxdepth 1` count returns zero. Use `find subagents -name 'agent.md' | wc -l`.
- `agents/` and `subagents/core/` hold the **same eight roles** — byte-identical
  `name:` and `description:` for `systems-architect`, `config-safety-reviewer`,
  `root-cause-analyzer`, `security-auditor`, `test-engineer`, `performance-tuner`,
  `refactor-expert`, `docs-writer` — in two different formats. `agents/*.md` uses
  `model: inherit`, `category: engineering`, `color: blue`; the catalog copies use
  `category: "core"`, `team: "core"`, `color: "#FFD700"`, `model: claude-opus-4`,
  plus `enabled:` and `capabilities:`. They also differ in length (`security-auditor`
  is 712 lines under `agents/`, 809 under `subagents/core/`). Same role, different
  artifact — which is why 141 and 133 are both true.
- `subagents/core/` has **no README** upstream, unlike the other nine categories.

**The core eight were never a real ambiguity — upstream already decided.** An
earlier revision recorded them as an open "M3 hazard" requiring a choice of format.
Reading upstream's v2.7.0 release notes settled it: `subagents/` is **PRIMARY**, and
`agents/` is a backward-compatible shim. `agents/<name>/agent.md` are symlinks into
`subagents/core/` (8/8 verified resolving); the flat `agents/<name>.md` are
pre-v2.7.0 leftovers that were never deleted and have since diverged. The generator
reads `subagents/` only (`D-024`).

**The real collision was elsewhere, and only the generator found it.** The 133 files
carry just **130 distinct `name` slugs** — three roles exist in two departments each,
with different bodies and different tints. Upstream's own `DUPLICATE-ANALYSIS.md` is
v2.5.0, predates the consolidation, and does not cover them.

| Upstream slug | Kept | Curated | Outcome |
|---|---|---|---|
| `customer-support` | account-customer-success — analyses resolution patterns, escalation risk | operations — handles tickets, FAQs, canned responses | renamed `support-ticket-handler` |
| `infrastructure-maintainer` | engineering/devops | operations/infrastructure — same scope plus capacity planning | **removed**; one role filed twice |
| `tutorial-engineer` | engineering — builds tutorials from code | marketing — self-described "Educational content specialist" | renamed `educational-content-writer` |

`data/agents.json` therefore holds **132 entries**: 133 upstream files minus the one
removal. It is upstream *plus a reviewed curation table*, not a pure mirror — the
tables live in `scripts/generate_agents_json.py`, keyed by source path so an upstream
move fails the build rather than silently mis-applying.

**Before renaming or removing an agent, grep `commands/`.** The 19 orchestration
commands reference agents by id; 24 of 132 are referenced by at least one. None of
the four ids touched above appears in any command, which is why this curation was
safe. The most-referenced agents are the core eight (`security-auditor` in 11
commands, `systems-architect` 10, `test-engineer` 9, `performance-tuner` 8) — a
second reason the catalog copies are the ones to keep.

This supersedes the "137+" figure that appeared in `README.md`, `CLAUDE.md`, and
earlier revisions of this file. Per `D-017` this document is the taxonomy
authority — every other mention of a count derives from here.

---

## Installation

### Full Installation

```bash
# Install all roles (recommended)
./scripts/install.sh

# This installs:
# - 8 core agents (to ~/.claude/agents/)
# - 133 specialized agents (to .claude/agents/)
# - Skills (8 autonomous helpers)
# - Commands (4 workflow orchestrators)
```

### Selective Installation

```bash
# Install specific categories
./scripts/install.sh --category engineering
./scripts/install.sh --category design
./scripts/install.sh --category marketing

# Install core agents for core  roles only
./scripts/install.sh --core

# Install skills only
./scripts/install.sh --skills
```

### Directory Locations

**User-Level Agents** (global):
```
~/.claude/agents/
```

**Project-Level Agents** (project-specific):
```
.claude/agents/
```

**Precedence**: Project `.claude/*' settings overrides user '~/.claude/*'  with the same name.

---

## Agent Structure

### Agent, Role and Charcators relationships: Composition of 'Employee' = $charactor + $role

**Each potential $role maps to a defined agent of the same name**

which is the default 'engine' for the $role assigned too character too fill the 'employee directory
at the start of the game, until user customizes the properties of each 'employee' or takes manual control.
**User $charactor can 'drive' any 'employee' in the $directory 

### YAML Frontmatter

Every agent follows this structure:

```yaml
---
name: agent-name
description: Agent purpose and when to use it
tools: Tool1, Tool2, Tool3
model: inherit
color: blue
category: engineering
subcategory: backend
---

[Agent system prompt and capabilities]
```

### Required Fields

- **name**: kebab-case identifier
- **description**: When to use this agent
- **tools**: Accessible tools (Read, Write, Edit, etc.)
- **model**: Always `inherit`

### Optional Fields

- **color**: Team color code
- **category**: Primary team category
- **subcategory**: Functional sub-category
- **level**: strategic/tactical
- **depth**: comprehensive/lightweight
- **specialization**: Unique focus area

---

## Standards Integration

All Agent " roles" follow standards from `/standards/` folder:

- **Code Quality** - ESLint, Prettier, best practices
- **Git Workflows** - Conventional commits, branch strategies
- **Testing** - Test pyramid, coverage standards
- **Security** - OWASP guidelines, secure coding
- **Documentation** - Technical writing standards
- **Performance** - Performance budgets

These standards act as Standard Operating Procedures (SOPs) for consistent quality.

---

## Usage Examples

### Comprehensive Code Review

```bash
# Configuration safety review
@config-safety-reviewer Review database pool settings in config.js

# General code review
@code-reviewer Review this React component for best practices

# Security-focused review
@security-auditor Full security audit of authentication system
```

### System Architecture

```bash
# System design
@systems-architect Design scalable e-commerce platform

# Backend API design
@backend-architect Design RESTful API for user management

# Cloud infrastructure
@cloud-architect Design AWS infrastructure for microservices
```

### Testing & QA

```bash
# Comprehensive test strategy
@test-engineer Create test suite for UserService

# QA mindset testing
@qa-test-engineer Create adversarial test cases

# Performance testing
@performance-benchmarker Create load tests for API endpoints
```

### Debugging

```bash
# Comprehensive root cause analysis
@root-cause-analyzer Production API timing out under load

# Quick debugging
@debugger Fix error in payment processing

# Error patterns
@error-detective Analyze recurring 500 errors in logs
```

---

## Related Documentation - Sub-Agents that Drive the 'Charcators'/'employees' and perform tasks  

These live in the `claude-code-tresor` submodule, not in this repo. Initialise it
(`git submodule update --init --recursive`) and read them there:

- [`subagents/AGENT-INDEX.md`](../claude-code-tresor/subagents/AGENT-INDEX.md) — the complete agent list
- [`docs/archive/AGENT-CATEGORIZATION.md`](../claude-code-tresor/docs/archive/AGENT-CATEGORIZATION.md) — categorization strategy
- [`docs/archive/AGENT-DEPENDENCIES.md`](../claude-code-tresor/docs/archive/AGENT-DEPENDENCIES.md) — inter-agent relationships and workflows
- [`docs/archive/DUPLICATE-ANALYSIS.md`](../claude-code-tresor/docs/archive/DUPLICATE-ANALYSIS.md) — conflict resolution
- [`docs/archive/SUB-AGENT-STRUCTURE.md`](../claude-code-tresor/docs/archive/SUB-AGENT-STRUCTURE.md) — agent format specification
- [`docs/archive/ANTHROPIC-REFERENCE.md`](../claude-code-tresor/docs/archive/ANTHROPIC-REFERENCE.md) — official Anthropic documentation
- [`docs/archive/AGENT-INVENTORY.md`](../claude-code-tresor/docs/archive/AGENT-INVENTORY.md) — historical inventory

Note the `archive/` path on most of these: upstream has retired them into an
archive folder, so treat their contents as historical. `AGENT-INDEX.md` is the live
one.

Per `D-016`, the submodule is the canonical agent layer: `data/agents.json` is
generated from it and this data is never duplicated into this repo's tree.

---

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines on:
- Adding new roles
- Updating existing roles
- Category organization
- Testing and validation

---

## Support

- **Documentation**: [`docs/`](README.md) for design and reference, [`specs/`](../specs/README.md) for process

---
---
## Attribution:

This outline is based on the adoption of the skills, agents, sub-agents, and other souce-code and documentation from the following GitHub public repository: https://github.com/alirezarezvani/claude-code-tresor/ <---this repository which is the souce of a direct-fork of the same repository also publically available @ https://github.com/adamtasteslikegood/claude-code-tresor.git is fork of https://github.com/alirezarezvani/claude-code-tresor/ by Adam Schoen. The work of the Author, and all those Contributing to the source, that is included or appears here in its orginal or adapted form does so under the MIT LICENCE, which is also the LICENCE this document discribing a concept for a project at the afformentioned GitHub
URLs.. Original contriubtions and changes Copyright (c) © 2026 Adam Schoen.  

adapted from:

- [claude-code-tresor](https://github.com/alirezarezvani/claude-code-tresor/) "https://github.com/alirezarezvani/claude-code-tresor/"
**Version**: 2.5.0
**Last Updated**: November 15, 2025
**License**: MIT
**Author**: Alireza Rezvani 

## **License**: MIT 

```plain text

MIT License

Copyright (c) 2025 Alireza Rezvani

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


```
