---
doc_id: DELIVERY-COORDINATES
title: Delivery coordinates — which board, which space, which key
tier: 2
authority: taxonomy
status: ACTIVE
doc_set_version: 0.2.10
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [PROJECT-OVERVIEW]
decides: [D-026]
enforcement: asserted
gates: [Validate Delivery Coordinates:snapshot, Validate Specs:live]
weakest_claim: two Python scripts are the only other place a key legitimately appears
---

# Delivery coordinates

> **One line:** this document is the source of truth for every Atlassian
> identifier this repo uses. Nothing else in the doc set originates one.

`D-026` designates this file as the taxonomy authority for delivery
coordinates, the same way `D-017` designates `AGENT-DIRECTORY` for the
department taxonomy. Every other mention — `CLAUDE.md`, `README.md`,
`QUICKSTART.md`, any guide — **cites this table rather than restating it**. The
two Python scripts are the only other place a key legitimately appears, because
they have to execute it; when a script and this table disagree, the script is
the fact and this table is the bug.

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
| Linear `PLZG` ↔ Jira `PLZG` | **two-way, the default** | Live delivery work. |
| Jira `TO` → Linear | one-way, retained | Lets closures on the ~dozen existing `TO`-linked Linear issues propagate. |

What it was before: Linear `PLZG` ↔ Jira **`TO`** two-way, plus Jira `PLZG` →
Linear one-way. The two-way leg pointed at the deprecated board, so **anything
filed in Linear was created in `TO`**.

The `TO` → Linear leg is deliberately **not** deleted. Removing it would orphan
the existing Linear issues that point at `TO`; keeping it one-way means closing
them still syncs.

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

*Last updated: July 2026*
