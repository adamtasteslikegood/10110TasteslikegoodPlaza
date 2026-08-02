---
doc_id: SPRINT-2-CHARTER
title: Sprint 2 charter — delivery decisions locked 2026-07-30
tier: 3
authority: derived
status: ACTIVE
doc_set_version: 0.2.10
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [ROADMAP, DELIVERY-COORDINATES, META-SPEC]
enforcement: asserted
gates: [Validate Specs:live, Validate Delivery Coordinates:snapshot]
weakest_claim: The proving artifact is a new stdlib-only `scripts/validate_delivery_coordinates.py`
---

# Sprint 2 charter — delivery decisions locked 2026-07-30

> **One line:** this document is the complete executable context for Sprint 2. A
> session that has read this file needs nothing from the conversation that
> produced it.

`PLZG Sprint 2` (board `169`, sprint id `44`) is **active**, running
**2026-07-30 → 2026-08-13**, with nine committed items.

**Sprint goal:** make every doc claim about state match the system that owns it —
and automate the sync check that catches the next drift.

This charter exists because the decisions below were reached in a `/cs:grill-pm`
interrogation, and a decision that lives only in a transcript is not a decision.
Everything needed to execute is written here. Where a number came from a
measurement, the command that produced it is given so it can be re-run rather
than trusted.

## 0. Before anything else

Run the sync. Per CLAUDE.md § *Sync the environment before anything else*:

```bash
git fetch origin && git status
git rev-list --left-right --count HEAD...origin/dev   # ahead / behind
```

**This is not ceremony.** The grill that produced this charter began from a
checkout 31 commits behind `origin/dev` and generated three findings that were
already fixed upstream. See § 6 R1.

## 1. Definition of done, and the command that proves it

Sprint 2 is done when **nothing live routes to Jira `TO`, and PLZG can report all
four Kanban flow measures.**

The proving artifact is a new stdlib-only `scripts/validate_delivery_coordinates.py`
that exits 0 when both hold:

- **(a)** No executable script and no `ACTIVE` governed doc references project
  `TO`. `CHANGELOG.md` and any `status: SUPERSEDED` doc are exempt — they are
  history, and history is allowed to mention a deprecated board.
- **(b)** A committed PLZG snapshot yields `wip > 0` and a non-empty
  `work_item_age`.

Clause (b) is the one that matters. Without it a rename-only sundown passes green
while flow remains unmeasurable.

Follow the existing validator idiom — `scripts/validate_specs.py`, stdlib only,
no `pip install` step — so it can join CI as a sibling job. Do not introduce a
new dependency or a new language to do this.

## 2. Flow measurement — the state this sprint starts from

Measured 2026-07-29 via `jira_snapshot_bridge.py --to flow`, before any planning.
That script is plugin-provided, not in this repo — see § 9 for how to resolve its
path. Kanban Guide (May 2025) makes four measures mandatory; **two were
unreportable.**

| Measure | Value at sprint start |
|---|---|
| total / done | 83 / 42 |
| **WIP** | **0** |
| throughput | 2.75 items/week over 15.3 weeks |
| cycle time | p50 9d, p85 104d — `created→resolved` approximation |
| work item age | *empty* |

WIP was 0 and age empty because the board used **only `To Do` and `Done`**, and
because no sprint was active.

**The fix is behavioural, not structural.** PLZG's workflow already offers
`In Progress` (status id `3`, category `indeterminate`, transition id `21`,
`isAvailable: true`). Nobody used it. No Jira admin change is required.

Verify with:

```bash
# transitions available on any open PLZG issue
curl -s -H "Authorization: Basic $AUTH" \
  "https://tasteslikegood.atlassian.net/rest/api/3/issue/PLZG-114/transitions"
```

### WIP limit: 3

Derived, not guessed — Little's Law: `WIP = throughput × cycle time`
≈ `2.75/wk × ~1wk target` ≈ 3. The spreadsheet of record is
`docs/assets/agile-littles-law.ods`.

### What clause (b) asserts, and what it deliberately does not

It asserts `work_item_age` is non-empty and `wip > 0`. It does **not** assert
conformance to a Service Level Expectation. Asserting an SLE now would be
forecasting on contaminated data — see § 3. Prove the pipe emits the measures
this sprint; earn the SLE next sprint.

## 3. Forecast blackout — in force

**Sprint 2 carries no date commitment. Not even a p85 range.** It is scoped by
item count (9) and a timebox (2 weeks). Whatever lands, lands.

The timebox is a control, not a forecast. If 9 items do not fit in 2 weeks, that
is the first honest throughput datapoint this project owns.

### Why forecasting is refused

The sample is large enough (42 completions) but **non-stationary**, which is
worse than small. True `resolutiondate` distribution:

```
2026-04-15   17
2026-04-27    9
             --- 11-week gap, zero completions ---
2026-07-12    6
2026-07-28    9
2026-07-29    1
```

Monte Carlo resamples historical weekly throughput and assumes the future is
drawn from the same distribution. An 11-week dormancy inside the sample breaks
that assumption: the model cannot distinguish *"team paused"* from *"team is
slow"*, so it silently prices dormancy into every forecast.

The two defensible bases disagree by ~3x:

| basis | p50 | p85 | p95 |
|---|---|---|---|
| full data (2.75/wk) | 5 wk | 10 wk | 15 wk |
| backfill excluded (2.16/wk) | 7 wk | 14 wk | 20 wk |

Same question, 14 vs 10 weeks at p85. Publishing either would be a single-point
promise wearing a percentile costume (Vacanti, *When Will It Be Done?*).

### Condition to lift the blackout

**10+ completions carrying real `started→resolved` timestamps, drawn from a
window containing no zero-throughput weeks.** This is an exit criterion, not a
judgement call. The earliest it can be satisfied is the end of Sprint 2.

## 4. Ownership and accountability

| Role | Who |
|---|---|
| Owner, every task | adam schoen |
| Reviewer, every task | adam schoen |
| Escalation reviewer | adam schoen |
| Executor | `agent`, except where a task requires a judgement call |

`delivery_loop_gate.py` enforces this as gate **G2** — an agent-executed task
with no named human reviewer blocks the plan.

### The rule that makes solo self-review non-circular

**Every task must carry `acceptance.cmd`. Never `acceptance.criterion`.**

With one human, a second reviewer is fiction. The honest substitute is machine
verification: adam reviewing adam's prose is self-attestation; adam reviewing an
exit code is not. Gate **G3** enforces it — prose acceptance without a measurable
threshold blocks the plan.

Verified empirically 2026-07-30: a probe plan with `owner == reviewer` **passed**
when acceptance was a `cmd`, and was blocked when it was prose. Self-review is
accepted; unverifiable acceptance is not.

### Two standing gaps this sprint closes

1. **All 83 PLZG issues were `UNASSIGNED`.** Unassigned work and a WIP limit do
   not compose — you cannot hold a limit or read work item age against nobody.
   Assign the nine Sprint 2 items.
2. **Agents were ~47% of commit volume with no reviewer of record** — last 90
   days: `adam schoen` 41, `Claude` 30, `copilot-swe-agent[bot]` 7.

**Do not rely on `claude-review.yml` as the reviewer of record.** It is advisory
(`continue-on-error`), never a required check, and per CLAUDE.md it cannot review
changes to itself while still reporting green.

## 5. Budgets

| Budget | Value |
|---|---|
| Attempts per task | 3 |
| Iterations per goal | 12 |
| Escalation reviewer | adam schoen |

**One addition to the standard caps: task `T0` (fetch / reconcile) is exempt from
the attempt cap and blocks every other task.**

The cap that matters here is not the count but the precondition. A loop that
burns three attempts against stale state has spent its budget learning nothing.
What caught the error in § 6 R1 was fetching the owning system, not a retry.

## 6. Owned risks

Output of a pre-mortem (Klein, HBR 2007) — *"it is six months later and Sprint 2
failed; why?"* Generic risks were discarded; these three are carried.

### R1 — Ghost work · **already materialised**

An agent executes from a stale checkout and "fixes" what is already fixed
upstream, re-introducing regressions and colliding on merge.

*Evidence, not hypothesis:* the grill producing this charter ran 31 commits
behind and asserted `generate_report.py` hardcodes `project = "TO"`. That file
already read `ATLASSIAN_JIRA_PROJECT_KEY`.

**Owner:** adam schoen.
**Mitigation:** `T0` fetch/reconcile as a blocking precondition (§ 5); automated
by `PLZG-114`.

### R2 — The board measures fiction

If ticket closure lags reality, WIP and work-item-age readings describe a board
nobody transitions, and the § 3 blackout never honestly lifts.

*Evidence:* `PLZG-105` sat in `To Do` while its subject was fixed on
`origin/dev`.

**Owner:** adam schoen.
**Mitigation:** audit open items against `origin/dev` **before** adopting WIP
discipline. Done once on 2026-07-30 — it closed exactly one ticket (`PLZG-105`).
Six others were checked and found live, several worse than filed. **Do not assume
a batch is stale because one member was.**

### R3 — "Deprecated" mistaken for "archived"

`TO` is renamed, not archived, and the Jira `TO` → Linear leg is deliberately
retained.

`docs/delivery-coordinates.md` states the rule this project already learned the
hard way: **a board is only read-only if nothing has write access to it.** It was
earned when the Linear sync minted `TO-127`–`TO-136` for a full day *after*
deprecation.

**Owner:** adam schoen.
**Mitigation:** enumerate every writer — syncs, automations, webhooks — and
repoint before archiving. **Archive, never delete:** `TO` holds ~50 recipe-app
issues that are `RCP`'s history.

### Deliberately not carried

`.env` secret leakage. `.env` is gitignored and `git log --all -- .env` returns
empty — never committed. Real concern, not a Sprint 2 risk.

## 7. Sprint 2 scope — nine items

Every item was verified live against `origin/dev` on 2026-07-30 before being
committed to the sprint. None was taken on faith from its ticket text.

| Key | Item |
|---|---|
| `PLZG-106` | CHANGELOG `[Unreleased]` contradicts itself on which board `generate_report.py` queries |
| `PLZG-107` | CLAUDE.md exceeds META-SPEC §6's ~200-line instruction budget |
| `PLZG-108` | QUICKSTART.md casts doubt on whether the Godot prototype exists |
| `PLZG-109` | QUICKSTART.md redacts the Confluence page id/space that other files publish |
| `PLZG-110` | QUICKSTART.md's `.env` template is missing `ATLASSIAN_JIRA_PROJECT_KEY` |
| `PLZG-111` | `docs/delivery-coordinates.md` rollover comments |
| `PLZG-112` | CHANGELOG `[Unreleased]` retracts "no Linear board" while an older bullet contradicts it |
| `PLZG-114` | SessionStart hook enforcing environment sync |
| `PLZG-115` | `validate_specs.py` fails on unregistered reference docs |

### Findings that make several of these worse than filed

- **`PLZG-110`** — QUICKSTART still documents `ATLASSIAN_API_TOKEN_BASE64_USEREMAIL`
  and `ATLASSIAN_URL` only. Following it today produces a `.env` that makes
  `generate_report.py` **exit 1**. Its line *"Both will crash with a `KeyError`"*
  is also stale: it is now a guarded `sys.exit(1)`.
- **`PLZG-108`** — QUICKSTART line 3 says the prototype's *"status, existence,
  instructions ... subject to change"*, directly contradicting CLAUDE.md's
  "running Godot prototype, M1/M3/M4 done".
- **`PLZG-109`** — QUICKSTART shows `<confluence_page_id>` and
  `____ ("Your Confluence Home Page goes Here")` while `post_to_confluence.py`
  hardcodes `parent_page_id = "11075756"`.
- **`PLZG-111` / `PLZG-112`** — both `CHANGELOG.md` and
  `docs/delivery-coordinates.md` still assert **"`TO-127`–`TO-136` still need
  triage into `PLZG`"**. That is false: they were bulk-closed 2026-07-29
  10:09–10:10 and already exist as `PLZG-104`–`113`.

### Explicitly out of scope

- **Overhauling PLZG.** The measured blocker was one unused transition, not a
  restructure. An overhaul is unforecastable under § 3 anyway.
- **`PLZG-113`** (index governed docs into gbrain) — feature work, not
  truth-reconciliation.
- **Archiving `TO`.** Blocked on R3's writer enumeration.

## 8. Corrections log — claims this charter retracts

Recorded because the failure mode being fixed is *confident claims about state
that was true somewhere else*. A fresh session should know which earlier
statements were wrong.

| Claim made during the grill | Correction |
|---|---|
| The board is `PLAG` | No such project. It is **`PLZG`**, id `10206`. |
| `generate_report.py:51` hardcodes `project = "TO"` | True locally, **false on `origin/dev`** — it reads `ATLASSIAN_JIRA_PROJECT_KEY`. |
| `docs/delivery-coordinates.md` is not on `dev` | It **is** on `origin/dev`. The local checkout was 31 commits behind. |
| `PLZG-105` and `PLZG-110` are both already fixed | Only `105`. **`110` is live and worse than filed.** |
| 26 completions landed on 2026-04-27 | Based on `updated`. True `resolutiondate`: 17 on 04-15, 9 on 04-27. |
| "Sprint 0" | Sprint 1 is closed; **Sprint 2** already existed in `future` state. |

## 9. Tooling notes

### Use the official Atlassian connector

Prefer `mcp__plugin_atlassian_atlassian__*` (official, `https://mcp.atlassian.com/v1/mcp/authv2`).

The `pm-skills` plugin bundles its own `.mcp.json` pinned to the **deprecated**
`https://mcp.atlassian.com/v1/sse`, which emits a deprecation banner on every
call. Editing the vendored marketplace file is futile — it is clobbered on plugin
update. Raise it upstream at `alirezarezvani/claude-skills`.

### Atlassian admin via REST

The MCP server exposes no project-update tool; REST does. Credentials are in
`.env` (auto-loaded via `direnv`). Build the header without printing the token:

```bash
AUTH=$(python3 -c "
import base64
env=dict(l.strip().split('=',1) for l in open('.env') if '=' in l and not l.startswith('#'))
print(base64.b64encode(f\"{env['ATLASSIAN_EMAIL'].strip()}:{env['ATLASSIAN_API_TOKEN'].strip()}\".encode()).decode())
")
```

### The machine-readable plan, and where its tooling lives

**`delivery_loop_gate.py` and `jira_snapshot_bridge.py` are not in this repo, and
must not be vendored into it.** They ship with the `pm-skills` plugin, which
`.claude/settings.json` enables at project scope — so a fresh checkout resolves
them through the plugin, not through `scripts/`. Nothing under `scripts/` here is
theirs; that directory is this repo's own Python tooling (`validate_specs.py`,
`generate_agents_json.py`).

Resolve the path rather than hardcoding it — the plugin lives under a versioned
cache directory whose exact location varies by install:

```bash
PM_SCRIPTS=$(find ~/.claude/plugins -path '*/pm-skills/scripts' -type d -print -quit)
```

`specs/sprint-2-loop-plan.json` carries the same decisions in the shape
`delivery_loop_gate.py` consumes. Verify before executing:

```bash
python3 "$PM_SCRIPTS/delivery_loop_gate.py" \
  --plan specs/sprint-2-loop-plan.json --mode plan --output human
# -> Verdict: PLAN-OK   (exit 0)
```

**If `PM_SCRIPTS` comes back empty, the plugin is not installed** — that is a real
blocker for verifying the plan, not something to work around by reimplementing the
gate. Enable `pm-skills` (see `.claude/README.md`) and re-run.

An earlier revision of this section wrote `"$PM/scripts/delivery_loop_gate.py"`
with `$PM` defined nowhere in the tree — it existed only in the session that wrote
the charter. Caught by the independent reviewer as `PLZG-117`. That is precisely
the failure § 8 and the opening line of this document are about, reproduced inside
the document making the claim: **"a session that has read this file needs nothing
from the conversation that produced it"** was false for one command, in a file
whose whole purpose is that sentence.

## 10. Outstanding, and not this sprint's

- **A live leaked credential.** GitGuardian incident `35204935` — a Google Cloud
  secret in `adamtasteslikegood/tasteslikegoodtheangularsvegancookbook` at
  `Google_Cloud_App_Designs/app-template-5_terraform_code_2026-03-04T21_09_21Z/main.tf:103`.
  `PLZG-100` tracked it here and was **closed as misfiled** — closing the ticket
  did not rotate the key, and deleting the file will not remove it from history.
  Belongs to the cookbook repo.
- **Repoint GitGuardian** away from `PLZG`, or this recurs (R3's rule).
- **`TO-127`–`TO-136` triage** — already complete; the docs claiming otherwise
  are `PLZG-111` / `PLZG-112`.

---

*Last updated: July 2026*
