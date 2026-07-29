---
doc_id: DELIVERY-COORDINATES
title: Delivery coordinates — which board, which space, which key
tier: 2
authority: taxonomy
status: ACTIVE
doc_set_version: 0.2.9
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [PROJECT-OVERVIEW]
decides: [D-026]
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

What it still holds is recipe-app work stranded by that misconfiguration. Of the
52 issues open on 2026-07-28, 50 were recipe-app; the 2 Plaza strays `TO-125`
and `TO-126` moved to `PLZG-102` and `PLZG-103`. Plaza's original `TO-19`–`TO-35`
had already migrated to `PLZG` on 2026-04-27. `TO` is also the origin of the
`feature/TO-1-prototype-initialization` branch name, which is not evidence the
board is live.

Until archival, treat it as **read-only**: no new Plaza issue is ever filed
there, and anything found there is moved to `PLZG` rather than worked in place.
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

There is no Linear board here and no `TAS` key. A PR title in this repo carrying
`RCP`, `KAN` or `TAS` is a policy pasted from another repo and not adapted —
treat it as the smell it is, and fix the title rather than the board.

## What derives from this

- **PR titles.** Every PR title carries a `PLZG-###` key. Jira's GitHub
  integration links PRs, branches and commits by scanning the title, so a PR
  without one is invisible to the board. Fix a missed key by editing the title;
  the rescan picks it up.
- **`generate_report.py` holds no Jira key at all.** It reads
  `ATLASSIAN_JIRA_PROJECT_KEY` and exits 1 if unset — verified at
  `generate_report.py:26,44`. Resolution order is **real environment first, then
  `./.env`**: the script seeds from `os.environ` and `.env` only fills names not
  already set, so an exported variable silently wins over the file. **The
  deployed board is therefore in neither this table nor the script** — if a
  report comes out wrong, check the environment, then `.env`. It was pinned to
  `TO` until 2026-07-28, which is why committed reports carried a Plaza heading
  over another product's issues. Moving it to `PLZG` is pending an audit, because
  `PLZG` also holds security alerts filed for unrelated repos.
- **`post_to_confluence.py` does hard-code the parent page id** —
  `parent_page_id = "11075756"` at line 36. That single value genuinely lives in
  the script and must match this document; the space key appears only in a
  comment.
- **`report.md`.** Generated output carrying raw Jira issue titles from a
  cross-project board. Untracked and git-ignored: committing it is a disclosure
  decision, not a formatting one.

*Last updated: July 2026*
