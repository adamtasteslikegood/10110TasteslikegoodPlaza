---
doc_id: DELIVERY-COORDINATES
title: Delivery coordinates — which board, which space, which key
tier: 2
authority: taxonomy
status: ACTIVE
doc_set_version: 0.2.12
last_updated: 2026-08
owner: adamtasteslikegood
derives_from: [PROJECT-OVERVIEW]
decides: [D-026]
enforcement: asserted
gates: [Validate Delivery Coordinates:snapshot, Validate Specs:live]
weakest_claim: **There is a Linear workspace, and it syncs.**
---

# Delivery coordinates

> **One line:** this document is the source of truth for every Atlassian
> identifier this repo uses. Nothing else in the doc set originates one.

`D-026` designates this file as the taxonomy authority for delivery
coordinates, the same way `D-017` designates `AGENT-DIRECTORY` for the
department taxonomy. Every other mention — `CLAUDE.md`, `README.md`,
`QUICKSTART.md`, any guide — **cites this table rather than restating it**.
**No script is a second source any more**: since `PLZG-109` both Python scripts
read their coordinates from the environment and hold none. Keys still *appear*
in prose elsewhere — guides cite them, and citing is the point — but nothing
else *originates* one, which is what `D-026` actually forbids. § *What derives from this*
has said so since 2026-07-31.

> ***Retired 2026-08-03, kept as history.*** This paragraph used to continue:
> *"The two Python scripts are the only other place a key legitimately appears,
> because they have to execute it; when a script and this table disagree, the
> script is the fact and this table is the bug."* That tie-break settled a
> disagreement that can no longer happen. **Kept rather than deleted because it
> is *why* the coordinates were centralised** — a future hardcoded coordinate is
> the failure it was written against, and deleting the reasoning invites someone
> to re-add one without knowing what it cost. Retired alongside the matching
> clause in `D-026`'s register row, under `PLZG-137`.

This document exists because that rule was absent and the coordinates drifted.
`post_to_confluence.py` published Plaza status reports into `TLG`, a sibling
product's space, for as long as the fallback existed. Separately, `CLAUDE.md`
simultaneously carried a rule saying "never copy the project key into this file"
and a table copying the project key into that file — two agent-authored
statements, both defensible, in direct contradiction. A reference mapping needs
one entitled home, not a convention.

## Jira

Two projects serve this repo on `tasteslikegood.atlassian.net`. They are not
interchangeable — verified against the site, not inferred from prose.

| Key | Name | Type | Role |
|---|---|---|---|
| `PLZG` | 10110 Plaza Delivery | software, company-managed | **Delivery. This is the key that goes in a PR title.** |
| `TO` | `[DEPRECATED] 10110 Tasteslikegood Plaza — see PLZG` | business, team-managed | **DEPRECATED — do not file here.** |

### Why `TO` is deprecated

Deprecated **2026-07-28**; to be sundowned, then archived. It is vestigial — a
leftover of a misconfigured `tasteslikegood-dev` site where the recipe app and
this project were combined. The other site's service board lives on that `-dev`
site and has already been renamed there; **this site has no public-facing
service board at all**, which is why renaming `TO` here was safe.

What it mostly holds is recipe-app work stranded by that misconfiguration. Of
the 52 issues open on 2026-07-28, 50 were recipe-app; the 2 Plaza strays
`TO-125` and `TO-126` moved to `PLZG-102` and `PLZG-103`. Plaza's original
`TO-19`–`TO-35` had already migrated to `PLZG` on 2026-04-27. **That count is a
snapshot, not a standing figure** — ten more Plaza issues (`TO-127`–`TO-136`)
arrived afterwards via the Linear sync described below, so re-query before
citing a number. `TO` is also the origin of the
`feature/TO-1-prototype-initialization` branch name, which is not evidence the
board is live.

Until archival, treat it as **read-only by policy** — file nothing there by
hand, and move anything found there to `PLZG` rather than working it in place.
Read that as an instruction to people and agents, **not as a description of the
board's actual state**: a Linear sync kept writing to `TO` for a day after this
was first written (see § Linear ↔ Jira sync), and `TO-127`–`TO-136` are the
result.

The `[DEPRECATED]` prefix was applied precisely because the old name kept
attracting Plaza work — that is how `TO-125` and `TO-126` were misfiled. The
rename used `PUT /rest/api/3/project/TO` with the credential in `.env`; the MCP
server exposes no project-update tool, but REST does, so this is not a UI-only
operation.

## Confluence

Space **`PLZA`** ("10110 Tasteslikegood Plaza"), parent page **`11075756`** —
the space home, `https://tasteslikegood.atlassian.net/wiki/x/rACp`.

Until 2026-07-28 `post_to_confluence.py` posted into space **`TLG`**
("Tasteslikegood.org") under `15925249`, with a fallback to `15695959` — both
sprint-planning pages of the sibling product, neither a Plaza report parent. The
fallback was removed with the fix. **Do not reintroduce one:** a fallback that
silently writes into another product's space is exactly how the reports ended up
there. If the parent page is unreachable the script exits 1, and that is the
correct behaviour.

## Keys that are not this repo's

Real projects on the same Atlassian site, belonging to the owner's **other**
repositories:

| Key | Name | Belongs to |
|---|---|---|
| `RCP` | Tasteslikegood Recipes Delivery | the recipe app |
| `KAN` | Tasteslikegood-dot-Org | the org site |

There is no `TAS` key. A PR title in this repo carrying `RCP`, `KAN` or `TAS` is
a policy pasted from another repo and not adapted — treat it as the smell it is,
and fix the title rather than the board.

## Linear ↔ Jira sync

**There is a Linear workspace, and it syncs.** An earlier version of this
document said there was no Linear board at all; that was wrong, and wrong in the
direction this repo keeps failing in — asserting infrastructure is absent is
still a claim about state, and it was the mechanism behind the drift below.

Corrected topology, set by the owner on 2026-07-29:

| Link | Direction | Purpose |
|---|---|---|
| Linear `OFFICE` ↔ Jira `PLZG` | **two-way, the default** | Live delivery work. Linear's prefix was itself `PLZG` until 2026-08-09; see below. |
| Jira `TO` → Linear | one-way, retained | Lets closures on the ~dozen existing `TO`-linked Linear issues propagate. |

What it was before: Linear `PLZG` ↔ Jira **`TO`** two-way, plus Jira `PLZG` →
Linear one-way. The two-way leg pointed at the deprecated board, so **anything
filed in Linear was created in `TO`**.

The `TO` → Linear leg is deliberately **not** deleted. Removing it would orphan
the existing Linear issues that point at `TO`; keeping it one-way means closing
them still syncs.

### Pull requests drive status, and no longer drive `Done`

Configured by the owner across 2026-08-08/09 — Linear rules on both teams, the old Jira
merge rule disabled, and **two new Jira automations: one on branch creation, one on PR
creation**, each moving `To Do` items to `In Progress`.

| GitHub event | Intended status | Verified 2026-08-10 |
|---|---|---|
| **Branch** created carrying the key | `In Progress` | **works, and correctly scoped** |
| PR opened | `In Progress` | works, but **over-matches** — see below |
| Ready to merge / review requested | `In Review` | not yet tested |
| PR merged | **nothing** — `Done` is a human transition | holds |

**Tested deliberately, not inferred.** `PLZG-129` was fixed on branch
`fix/PLZG-129-sprint-2-gate-resolver`, whose *name* carries only `PLZG-129` while its
*commit body* cites `PLZG-118` three times and `PLZG-117` once. Both `PLZG-129` and
`PLZG-118` were `To Do` before the push.

**The branch rule is immune to prose mentions, and the dev-info API shows why:**

| Issue | `pullrequest` links | `branch` links | Moved on push? |
|---|---|---|---|
| `PLZG-129` | 3 | **1** | yes, within 10s |
| `PLZG-118` | 2 | **0** | no |

Only a key in the **branch name** produces a `branch` link. Mentions in commit messages
and PR bodies produce `pullrequest` and `commit` links instead. So the branch trigger
cannot be fooled by a citation — the failure mode that made the old merge rule produce
five false `Done` states.

**The PR-creation rule can be, and was.** Opening PR #146 moved `PLZG-118` to
`In Progress` although that PR does not touch it; it was merely cited. Stable across
four polls over 60 seconds, so not transient. Reverted by hand.

**Why that is worse than it sounds.** The blast radius is far smaller than the old rule
— `In Progress` is not `Done`, and nothing is falsely reported complete — but the damage
lands exactly on what these rules exist to produce. A false `In Progress` inflates WIP,
one of the Kanban Guide's four mandatory measures and the quantity
`validate_delivery_coordinates.py` clause (b) requires to agree with `work_item_age`. It
also stamps a false `started` timestamp, the input to cycle time and therefore to the
`specs/sprint-3-charter.md` §1.3 forecast blackout. **The mechanism meant to make flow
data trustworthy currently pollutes it.**

**The fix is small, and the branch rule is the reason.** `.claude/pr-workflow.md`
requires the key in the PR **title** and recommends it in the branch name ("Put it in the
branch name and commit messages too"). In practice every branch in this repo carries the
key (`type/PLZG-###-description`), so the branch rule fires. Either disable the
PR-creation rule, or condition it on the key appearing in `{{pullRequest.title}}` or
`{{branch.name}}` rather than merely being linked.

**No retroactive firing**, which is why an earlier revision of this section recorded the
`In Progress` half as *"did not fire"*. It was tested on PR #145, whose branch and PR
events **predate the rules** — so nothing was wrong with the rules, and nothing was
wrong with the observation either. Kept as a note because the trap is a general one:
*an automation cannot be tested against an event that happened before it existed*, and
reading that null result as a broken rule would have sent someone to debug a rule that
works.

**One consequence of the `OFFICE` rename that this test settles.** Linear now matches
`OFFICE-nn`, while every PR title here carries `PLZG-###` so the Jira board sees it. A
Linear-side PR rule therefore has nothing to match on any conventional PR in this repo —
harmless while Jira drives status and Linear mirrors it, but it means the Linear rules
are effectively inert here rather than redundant backups.

**What it replaced, and why.** Merging a PR used to transition every referenced
issue to `Done`. `GitHub for Jira` writes development-info links onto *every*
`PLZG` key it finds in a merged PR's title, body, branch and commits, and the rule
acted on those links — so it could not distinguish *"this PR fixes X"* from *"X is
explicitly out of scope."* It produced **five false `Done` states**: `PLZG-138`,
`PLZG-150`, `PLZG-158`, `PLZG-129` and `PLZG-142`. Two are instructive: `PLZG-129`
was closed by a commit whose message read *"Do not copy that shape forward"*, and
`PLZG-142` by a sentence reading *"is untouched here."* Both are statements that
the work was **not** done. Diagnosis in `PLZG-164`.

`PLZG-138` was the worst of them, because it was `T8` of Sprint 3 — the sprint whose
goal was *"every governed document declares which of its claims about state are
proven."* It sat `Done` for five days with no branch, no PR and no commit behind it.
That is `specs/sprint-3-charter.md` §6's risk R2 — *the board still measures fiction* — with a named
mechanism rather than an accepted unknown.

**Which tracker originated it, measured rather than assumed.** Jira transitioned
first in **8 of 8** cases, leading Linear's mirrored `completedAt` by 1.5–6.0
seconds; reopens propagate the same direction at the same speed. So Jira was the
origin and Linear the mirror, even though rules existed in both. The decisive check
is structural, though, not chronological: the keys cited in those PRs do not exist
in Linear at all, so Linear had nothing to match on — see the prefix warning below.

**The consequence this buys, now that the branch half is verified.** A branch push moves
its issue to `In Progress`, so work acquires a real `started` timestamp without anyone
remembering to set one. Sprint 3 produced only four such items, all transitioned by
hand, which is why `specs/sprint-3-charter.md` §1.3's forecast blackout could not lift.
From Sprint 4 the
timestamps arrive by construction rather than by discipline — **provided the PR rule is
scoped, since a false `In Progress` corrupts the same measure it feeds.**

### Linear is `OFFICE`; it used to be `PLZG`, and that collision is why

**Jira is `PLZG`. Linear is `OFFICE`.** Renamed by the owner on 2026-08-09, issue
numbers preserved — Linear `PLZG-90` is now `OFFICE-90`. Jira `PLZG` is the key space
this document governs, so Linear is the side that moved.

Before the rename **both trackers used `PLZG` with independent numbering**, Linear's
range running to about `90`, entirely inside Jira's `1`–`164`. A bare key therefore
resolved to two different issues depending on which tracker read it:

| Key, pre-rename | In Linear (now `OFFICE-nn`) | In Jira (unchanged) |
|---|---|---|
| `PLZG-64` | T8 — log the amendment in `CHANGELOG` | Define tutorial startup — company name |
| `PLZG-68` | Root-level docs carry no frontmatter | Decide: save game format |
| `PLZG-84` | PR #129 has no `CHANGELOG` entry | M7 — Python WebSocket bridge |
| `PLZG-90` | The PR-merge automation defect | Export 137 agent `.md` files to `agents.json` |

That was a live mis-closure path while merges drove `Done`: a PR citing a key in
`1`–`90` could be matched by Linear against its *own* issue and mirrored into Jira,
landing on an unrelated ticket. The status-automation change alone would have shrunk
the blast radius without closing it — a stray mention would still move an unrelated
ticket to `In Progress`, inflating WIP and corrupting the very flow data that change
exists to produce. The rename is what actually closes it.

**Reading older prose.** A `PLZG-nn` in the `1`–`90` range, written before 2026-08-09,
may mean either tracker; keys above `90` are unambiguously Jira. The table above will
not disambiguate beyond those four collisions. Prefer the issue title over the key
when interpreting them.
Linear URLs of the form `linear.app/tasteslikegood/issue/PLZG-nn/…` survive only by
Linear's own redirect — two are cited in `PLZG-129`'s description.

**One hazard in this family remains open.** Jira `PLZG-42` and `PLZG-55` now resolve
to **`RCP-30`** and **`KAN-73`**, having been moved to other projects, and JQL
silently follows the old key. So a citation can still retarget across *projects*,
which no prefix rename addresses.

### What "one-way" actually governs

**Creation, not the whole lifecycle.** A one-way `Jira → Linear` link stops
Linear-born items from minting Jira issues. It does **not** sever items that
were created in Jira or already carry a Jira link — those keep back-updating,
which is why the `TO` leg still propagates closures instead of orphaning a dozen
Linear issues.

Worth stating explicitly because the obvious reading of "one-way" is wrong, and
re-deriving it from the name produces the conclusion that a one-way link forces
manual status reconciliation. It does not.

The practical consequence: one-way costs you only the *automatic minting* of
delivery tickets from upstream noise. Promoting an item into `PLZG` becomes a
deliberate act — which is the difference between "observed" and "committed to",
and is the distinction a board named *Delivery* should be making.

### What this cost, and the rule it corrects

This document previously said `TO` was read-only and that "no new Plaza issue is
ever filed there." That was the intent, never an enforced fact — the sync kept
writing to it for a full day afterwards. **`TO-127` through `TO-136` are Plaza
issues created after the 2026-07-28 deprecation**, the newest at 08:50 on
2026-07-29. They are not recipe-app strays; they are this project's own review
findings, including `TO-135` (GitHub issue #43) and `TO-136` (PR #33).

So the earlier stray count is stale: the two originally migrated (`TO-125` →
`PLZG-102`, `TO-126` → `PLZG-103`) were not the end of it. **`TO-127`–`TO-136`
were triaged and closed on 2026-07-29**, between 10:09:50 and 10:10:57, and
continue as `PLZG-104`–`PLZG-113`.

That last sentence is the second thing this passage has got wrong, in the same
direction both times. It previously asserted those ten issues were still awaiting
triage, and stayed that way after they were closed — a status snapshot in a
document that has no way to notice when it stops being true. **Re-query Jira
before citing any count or status from this file**; the board owns those facts
and this table does not.

The general rule this earns: *a board is only read-only if nothing has write
access to it.* Deprecating a project in prose, or renaming it, does not close
an integration that is still pointed at it. Before declaring any board
read-only, enumerate its writers — syncs, automations, webhooks — and repoint
them first.

## What derives from this

- **PR titles.** Every PR title carries a `PLZG-###` key. Jira's GitHub
  integration links PRs, branches and commits by scanning the title, so a PR
  without one is invisible to the board. Fix a missed key by editing the title;
  the rescan picks it up.
- **`generate_report.py` holds no Jira key at all.** It reads
  `ATLASSIAN_JIRA_PROJECT_KEY` and exits 1 if unset — the `missing_vars` guard
  (line 27), the `sys.exit(1)` (line 39), and `project_key = env_vars[...]`
  (line 45). *Cite the symbol, not just the line:* this PR's own `black` reformat
  moved all three, and **not by a constant** — expanding one comprehension pushed
  the guard 25→27 but the other two 35→39 and 41→45. An earlier draft of this
  document cited the pre-reformat numbers, and the draft after that described the
  shift as a uniform "+3", which is wrong twice over. Resolution order is **real
  environment first, then
  `./.env`**: the script seeds from `os.environ` and `.env` only fills names not
  already set, so an exported variable silently wins over the file. **The
  deployed board is therefore in neither this table nor the script** — if a
  report comes out wrong, check the environment, then `.env`. It was pinned to
  `TO` until 2026-07-28, which is why committed reports carried a Plaza heading
  over another product's issues. Moving it to `PLZG` is pending an audit, because
  `PLZG` also holds security alerts filed for unrelated repos.
- **`post_to_confluence.py` no longer hard-codes the parent page id.** It reads
  `ATLASSIAN_CONFLUENCE_PARENT_PAGE_ID` and resolves the space from whatever page
  that names, so the space needs no variable of its own. Changed 2026-07-31
  (`PLZG-109`); it was `parent_page_id = "11075756"` in the script until then.
  **Both scripts are now configured the same way**, so neither holds a
  coordinate: the deployed value is in the environment, and this table records
  the one this project uses. The no-fallback rule is unchanged — an unreachable
  page exits 1 rather than posting somewhere else.
- **`report.md`.** Generated output carrying raw Jira issue titles from a
  cross-project board. Untracked and git-ignored: committing it is a disclosure
  decision, not a formatting one.

*Last updated: August 2026*
