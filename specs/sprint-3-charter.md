---
doc_id: SPRINT-3-CHARTER
title: Sprint 3 charter — the doc set declares what is proven
tier: 3
authority: delivery
status: ACTIVE
doc_set_version: 0.2.12
last_updated: 2026-08
owner: adamtasteslikegood
derives_from: [META-SPEC, SPEC-DRIVERS-025, SPRINT-2-CHARTER]
enforcement: asserted
gates: [Validate Specs:live, Validate Delivery Coordinates:snapshot]
weakest_claim: PLZG issue is `To Do` today: **live WIP is 0.**
---

# Sprint 3 charter — the doc set declares what is proven

> **One line:** this document is the complete executable context for Sprint 3. A
> session that has read this file needs nothing from the conversation that
> produced it.

`PLZG Sprint 3` (board `169`, sprint id `45`) is **`future`**, scoped
**2026-07-31 → 2026-08-14**, carrying nine tasks. `T1`–`T8` each carry **one
Jira key**, listed per task in §5. `T0` has none by design — it is a precondition the `SessionStart` hook already
runs, and a permanently-instant item would pollute the flow data this split
exists to produce.

> This paragraph originally named **two** tickets, with `PLZG-131` as an umbrella
> over `T0`–`T4` and `T6`–`T8`. Split on the owner's instruction of 2026-08-01,
> *"individual tickets for t1-t8 as suggested for data gathering."* `PLZG-131` was
> re-scoped to this charter alone and closed. An umbrella spanning the sprint never
> transitions, so it inflates work-item age and holds a WIP slot while contributing
> no throughput signal — which is why Sprint 2's flow was unmeasurable.

The machine-readable half is [`sprint-3-loop-plan.json`](sprint-3-loop-plan.json),
the shape `delivery_loop_gate.py` consumes. **The two must agree. A disagreement
is a defect to fix, not a precedence to apply** — patch both in the same change,
and if which one is right is genuinely unclear, stop and record it in the
open-conflict register per `META-SPEC` §4.

An earlier draft of this paragraph said the loop plan wins because it is checked
by a gate. That was wrong twice over: passing a shape validator is not authority,
and inventing a tie-break rule in a tier-3 document is precisely the unilateral
reconciliation §4 forbids. Kept as a note because the error is an easy one — "the
machine-checked artifact must be the real one" sounds like this repo's own
reasoning, and is not.

Open questions that were *not* settled in the session that produced this charter
are recorded as comments on `PLZG-131`, not left in the transcript.

**Sprint goal:** every governed document declares which of its claims about state
are proven and by what — and the tier ladder gains a home for delivery policy.

> **Sprint 2 was still `active` in Jira** (sprint id `44`) when this charter was
> written, despite the repo recording `CLOSE-OK` on 2026-07-30 and every committed
> item sitting `Done` — an instance of R2 (§6) visible in the sprint object itself.
> Sprint 3 was created in `future` state precisely so it needed no change to that.
> **Resolved 2026-08-01:** sprint 44 closed with all 11 items `Done` and resolved.
>
> This block also claimed the two disagreed on the end date, `08-13` against
> `08-14`, and that the charter was the bug. **Retracted — there was no
> disagreement** (`PLZG-144`). The Agile API returns UTC, and every sprint boundary
> here is 17:00 PT, which is 00:00 UTC the next day; reading `endDate[:10]` shifts
> every end date forward by one. `SPRINT-2-CHARTER` was right. Kept rather than
> deleted because the lesson is not the date: **querying the owning system is
> necessary and not sufficient** — the value still has to be read in that system's
> units. That failure survived a check against Jira.

Decided in a `/grill-with-specs` interrogation on 2026-07-31, following Sprint 2's
close. Where a number came from a measurement, the command that produced it is
given so it can be re-run rather than trusted.

## 0. Before anything else

```bash
scripts/check_sync.sh          # a SessionStart hook already runs this
```

## 1. What Sprint 2 actually delivered, measured

Sprint 2 opened and closed on **2026-07-30**, 09:43–18:08 — one day, not the
planned fortnight. Verified against Jira, not against the charter.

| | |
|---|---|
| Committed | 9 (`PLZG-106`–`112`, `114`, `115`) — all `Done` |
| Unplanned, also landed | `PLZG-117`, `119`, `124`, `125`, `128` |
| Correctly out of scope | `PLZG-113` (still `To Do`) |
| Loop tasks | 10, **1 attempt each** — the 3-attempt and 12-iteration budgets never bound |

Three charter claims did not survive a live check. Recorded because the sprint's
own goal was *"make every doc claim about state match the system that owns it."*

They are numbered subsections rather than a list so that `§1.1`–`§1.3` elsewhere
in this document resolve to something real — per `META-SPEC` §6, item 2, a
section an agent can be pointed at without loading the file.

That cite is written `§6, item 2` and not `§6.2` deliberately. `META-SPEC` §6 is
a flat numbered list with no `### 6.x` headings, so a decimal cite would resolve
to nothing — the very defect the subsections above exist to fix, reproduced in
the sentence explaining the fix. `CLAUDE.md` already records this trap against
the same section: *"item 6. (Not a `§6.6`; that subsection does not exist)"*.
Section 5 is cited as `§5.5` elsewhere in this file because that form has repo-
wide precedent — `CLAUDE.md` and `decision-register.md` both use it — and is not
the same case.

### 1.1 The definition-of-done gate is green on a claim that is now false

`scripts/validate_delivery_coordinates.py` exits 0 reporting `wip=1`. Every open
PLZG issue is `To Do` today: **live WIP is 0.** The gate reads
`data/plzg-flow-snapshot.json`, frozen at 14:20 on 2026-07-30. `as_of` is read
only to print it — there is no staleness check, so the gate will still pass in
2027 reporting a July 2026 board.

### 1.2 The `In Progress` fix did not take

The single WIP item was `PLZG-125`, created 14:14 and snapshotted 14:20 — six
minutes, one ticket, the one whose subject was the gate itself. The other 13
completions went `To Do` → `Done`.

### 1.3 The forecast blackout cannot lift, despite 14 completions

§3 of the Sprint 2 charter requires *"10+ completions carrying real
`started→resolved` timestamps, drawn from a window containing no zero-throughput
weeks."* Thirteen of fourteen have no `started` at all, and all landed inside one
day — the window is a single point. The condition reads satisfiable-on-count; it
is not.

**The blackout therefore stays in force.** Sprint 3 carries no date commitment.

## 2. The diagnosis

All three are one defect: **a claim that was true once, written down, then read as
canon.** The ladder models *who may decide* (`tier` + `authority`) and *whether a
document is current* (`status`). It models nothing about **whether a claim has
been verified, and by what** — so `status: ACTIVE` gets read as "everything here
is true," and a document has no way to say *"this is the intent; nothing checks it
yet."*

`specs/branching-strategy.md` is the case that proves the gap. `CLAUDE.md` carries
a hand-written warning that it is "intended policy, not active rules" because the
frontmatter has no way to say so.

The constitution already believes the remedy — §5.7 *"deterministic over
generative"*, §5.8 *"acceptance criteria must be machine-checkable"* — but applies
it only to task acceptance, never to its own prose.

## 3. The amendment — two decisions

Both are **rules about documents**, so tier-0 `META-SPEC` is entitled to originate
them (§2: *"Rules about documents. Never product decisions."*). This is the first
time the register carries a `constitution`-originated row; it needs a new section.

### `D-027` — the `enforcement` axis

Every governed document declares `enforcement`, alongside `tier` and `authority`.

| Value | Meaning |
|---|---|
| `enforced` | A named CI gate re-derives every state claim on every run. |
| `asserted` | Verified by a human at a stated date. Nothing re-checks. |
| `intended` | Aspiration. Explicitly not yet true. |
| `n/a` | The document makes no claims about state. Off the scale, not on its bottom rung. |

Four rules, each chosen against a stated alternative:

1. **Per document, not per claim.** A per-claim marker is more precise and
   unenforceable — it asks a validator to parse prose. Per-document is greppable
   and an agent learns the trust level before reading a word.
2. **A document's value is its weakest claim.** Consequence accepted knowingly:
   `enforced` is **empty on day one**. `CLAUDE.md` is proven on `npm test` and
   unproven on the ~200-line budget; `AGENT-DIRECTORY`'s counts are gate-backed
   but its `{{rolels}}` template artifacts are not; `META-SPEC` §2 is enforced and
   §6 is not. The emptiness is the finding — *no governed document in this set is
   fully machine-backed* is true, currently invisible, and is the thing worth
   surfacing. `enforced` is a rung to earn, which is "canon when they work" in
   mechanical form.
3. **State claims only.** `authority` governs decisions — who may make them.
   `enforcement` governs claims about the repository, the board, the running
   system, the tooling. Without this scoping the axis is a category error:
   weakest-claim would stamp `intended` on `STORYBOARD-W1` and
   `DECISION-REGISTER`, the two documents that define canon. **An `intended` value
   restricts nothing about originating decisions** — `STORYBOARD-W1` keeps
   `D-002` regardless.
4. **A snapshot gate is not enforcement.** `gates:` entries are typed `live` (the
   gate re-derives from the system that owns the fact) or `snapshot` (it reads
   committed data). **`enforced` requires `live` coverage; snapshot-only caps at
   `asserted`.** This falls out of the definitions: `asserted` *is* "a human
   verified it at a stated date, nothing re-checks," which is exactly what
   `data/plzg-flow-snapshot.json` is. Wrapping it in a CI job re-reads; it does
   not re-check. Without this rule the new axis would have stamped the
   §1.1 defect `enforced` — the highest tier of trust.

**Consequence of `intended`:** that document's factual assertions may not be
relied on as current. Re-verify against the owning system before acting. This is
CLAUDE.md's opening rule turned from a paragraph everyone skims into a
per-document label. It is the only consequence; there are no others.

### `D-028` — the `delivery` authority

Adds `delivery` to the `authority` vocabulary, licensed at tier 3 to originate
**time-boxed operational policy that expires with its artifact**.

Closes open conflict §4.10, which has stood since 2026-07-30: the ladder models
what the product is (tiers 1–2) and what order it is built in (tier 3), with no
authority for *how work is governed while it is built*. `SPRINT-2-CHARTER`
**declared** `derived` — licensed to originate nothing — while setting a WIP limit,
retry budgets, a review gate and a forecast blackout that nothing else set. Both
charters declare `delivery` since `T7`; the past tense here is the gap `D-028`
closed, not the current state.

Chosen over §4.10's other candidate, an expiring `P-nnn` policy class, on the
Sprint 2 evidence: of the four policies named, **only two were ever exercised** —
the budgets never bound (1 attempt per task) and WIP peaked at 1 against a limit
of 3. Permanent ids and expiry machinery for parameters that expired unexercised
is a register of things that did not happen. `delivery` instead reuses machinery
that exists: one enum value, enforced by the same `x-may-originate` check that
closed §4.8. No new id space, no second register.

**When §4.10 is closed it must say the finding was resolved by amendment, not by
correction** — the reviewer was right, and the charter was not always fine.

## 4. Definition of done, and the command that proves it

`python3 scripts/validate_specs.py` exits 0 with six new checks, and
`tests/spec_enforcement_matrix.sh` proves each fails when it should.

1. Every governed document declares `enforcement` from the enum. Absence fails —
   no default.
2. `enforced` / `asserted` declare a non-empty `gates:` list. **Any** declared
   gate, on **any** enforcement value, names a job that **exists in
   `.github/workflows/ci.yml`** and is typed `live` or `snapshot`. The two
   halves are scoped differently on purpose, widened in `PLZG-134` after review:
   *requiring* gates is about what the value claims, so it applies only to
   values claiming CI backing; requiring a named job to *exist* is about the
   claim being checkable, and a nonexistent job is equally false on an
   `intended` or `n/a` document. Scoping both halves together left a hole
   nothing would have reported. Encoded as **`job:type` strings** — `[Validate Specs:live]` —
   not as `{job, type}` objects. Corrected in `PLZG-133` under `META-SPEC` §4
   rule 1: `parse_frontmatter()` accepts only `key: scalar` and `key: [a, b]`,
   so the object form **silently misparses** to `['{job: X', 'type: live}']`
   rather than failing. Tier 0 owns how frontmatter is encoded, so this
   tier-3 charter is patched to match the schema rather than the reverse.
3. `enforced` requires at least one `live` gate.
4. `n/a` carries a one-line reason in `doc-registry.json`, in the shape of the
   existing `exempt` block — so claiming it is visible rather than silent.
5. `asserted` / `intended` carry a `weakest_claim` that **appears verbatim in the
   document**. Substring match. This is what makes a value falsifiable: a
   reviewer checks the quote in ten seconds, and a fabricated audit fails the
   build.
6. `validate_delivery_coordinates.py` fails when the snapshot's `as_of` predates
   the current sprint window.

**The test matrix is not optional.** Checks 1–5 can pass vacuously, which is how
`tests/smoke_test.tscn` passed until v0.2.8. Fixtures must assert failure for: a
document claiming `enforced` on a `snapshot`-only gate; a `gates:` entry naming a
job absent from `ci.yml` **on an `intended` or `n/a` document, not merely an
`asserted` one** — that job-existence half was widened to every enforcement
value in `PLZG-134`, and a fixture using `asserted` would have failed before the
widening too, so it cannot prove the new branch works; a `weakest_claim` not
present in its file. Shape it
after `tests/check_sync_matrix.sh`, which builds its own fixtures and needs no
network.

**The stale-snapshot fixture is `T5`'s, not `T4`'s.** `T4` and `T5` share this
acceptance command, so if `T4` shipped that fixture too, `T5` would pass the
moment `T4` did and could be marked done having changed nothing.

### What this deliberately cannot catch

**Nothing stops a document quoting a trivially true sentence as its weakest
claim.** `CLAUDE.md` could cite "this repo is a running Godot prototype" and call
itself `asserted` while the 200-line budget goes unmentioned. The validator checks
the quote is *real*, never that it is the *weakest*.

This is the third appearance of the same limitation — `authority` cannot check
subject matter (§4.8), `constitution` cannot check whether a decision is
product-shaped (§4.9), and now `enforcement` cannot check whether a claim is the
weakest. Each was found by a human asking what the new gate deliberately could not
see. Ask it again here.

**Accepted cost:** `weakest_claim` duplicates prose into JSON, so editing that
sentence breaks the build until the registry is updated. Chosen knowingly — the
breakage is the feature, since editing your weakest claim is exactly when the
value should be re-examined.

## 5. Scope — nine items

**One valid order — `T0 → T1 → T2 → T6 → T3 → T4 → T5 → T7 → T8`.** The table
below is by task id, which is *not* the running order: `T6` runs before `T3`.

This is **one linearization of an under-constrained graph, not a schedule.**
Nothing depends on `T5`, so once `T4` lands it may run any time — including
alongside `T7` and `T8`. No edge was invented to make this line look mandatory:
`T5` and `T7` are genuinely unrelated, and a fake dependency would misreport the
critical path. The authority is `depends_on` in
[`sprint-3-loop-plan.json`](sprint-3-loop-plan.json), where `blocks` is exactly
its inverse. `§5.1` says why the order is what it is.

| | Ticket | Item | Acceptance |
|---|---|---|---|
| `T0` | — | Fetch / reconcile. **Blocking, exempt from the attempt cap.** | `scripts/check_sync.sh --strict` |
| `T1` | `PLZG-132` | Amend `META-SPEC` — define the `enforcement` axis (§3 `D-027`) and add `delivery` to the authority vocabulary (§3 `D-028`). **Atomically:** register both rows, add `decides: [D-027, D-028]`, and bump `doc_set_version` → **0.2.10**. See §5.1. | `validate_specs.py` |
| `T2` | `PLZG-133` | Extend `spec-frontmatter.schema.json` — `enforcement` enum, `gates[]` of `job:type` strings (see §4 check 2; **not** `{job, type}` objects, which the frontmatter parser cannot express), `weakest_claim`, `authority` += `delivery` with `x-may-originate: true`. | `validate_specs.py` |
| `T3` | `PLZG-134` | Extend `validate_specs.py` — DoD checks 1–5, reading permitted values **from the schema**, never restated in the script. | `validate_specs.py` — see §5.1 |
| `T4` | `PLZG-135` | `tests/spec_enforcement_matrix.sh` + a `Spec Enforcement Matrix` CI job. **Excludes the stale-snapshot fixture — that is `T5`'s.** | `tests/spec_enforcement_matrix.sh` |
| `T5` | `PLZG-130` | Snapshot staleness check in `validate_delivery_coordinates.py`, plus the fixture that exercises it. | `tests/spec_enforcement_matrix.sh` — see §5.1 |
| `T6` | `PLZG-136` | Migrate **all 24** governed documents — assign `enforcement`, `gates`, `weakest_claim`; registry entries; `n/a` reasons. **24 includes this charter**; it is not exempt from the axis it introduces. | `validate_specs.py` |
| `T7` | `PLZG-137` | Re-point **both** `SPRINT-2-CHARTER` **and this charter** to `authority: delivery` (§7); close §4.10 with the resolved-by-amendment note; correct `D-026`'s retired clause (GH #96). **Atomically:** bump `doc_set_version` → **0.2.11**. See §5.1. | `validate_specs.py && tests/spec_enforcement_matrix.sh` |
| `T8` | `PLZG-138` | CHANGELOG under `[Unreleased]` — the amendment as a whole. **No version bump; it belongs with the decision that caused it.** | `validate_specs.py && tests/spec_enforcement_matrix.sh` |

### 5.1 Two constraints that reshaped this table

Found by the independent reviewer on PR #104, against a draft that could not run.

**`T1` cannot claim a decision it has not registered.** `scripts/validate_specs.py`
`check_decisions()` (line 457) fails any document whose `decides:` names a `D-nnn`
absent from `decision-register.md`. So `META-SPEC` declaring
`decides: [D-027, D-028]` while the register rows land in `T7` would fail `T1`'s
own acceptance command. Registration, the `decides:` list and the prose are one
change.

**A trailing version-bump task is out of policy by construction.** `META-SPEC` §8
item 4 requires a changed locked decision and the set-wide `doc_set_version` bump
in the **same commit**. `T1` and `T7` each change locked decisions, so each carries
its own bump — 0.2.10 and 0.2.11. **Two bumps in one sprint is correct here**, not
a mistake: two unrelated decisions change, and coupling them into one version would
force them to ship together for no reason. `T8` keeps only the CHANGELOG.

**`T3` accepts on `validate_specs.py`, not the matrix.** The matrix is created by
`T4`, so accepting `T3` against it is unrunnable. `T4` is the *downstream*
non-vacuity gate: if its fixtures do not redden against `T3`'s checks, `T3` reopens.
An earlier draft said `T3` could not be `done` until `T4` passed, which deadlocked
against `T4` depending on `T3`.

**Migration runs before enforcement — `T6` before `T3`.** Check 1 makes a missing
`enforcement` value fail the build. Landing that while all 24 documents are
unmigrated means `validate_specs.py` — `T3`'s own acceptance command — can never
exit 0, with `T4` and `T6` both stuck behind it. **You do not switch on a required
field before populating it.** So `T2` adds `enforcement` as *optional*, `T6`
populates all 24, and `T3` then makes absence fail. This also settles the question
`T2` was carrying: optional first, required after migration.

**`T5` accepts on the matrix, not on the live snapshot.** `data/plzg-flow-snapshot.json`
is dated 2026-07-30, before this sprint's window, so once the staleness check exists
`validate_delivery_coordinates.py` *must* exit 1 against it — it can never prove the
task done. §4 already requires the matrix to carry a stale-snapshot fixture, so `T5`
accepts there and depends on `T4`.

> **Escalation `T5` will surface, and must not work around.** Refreshing the
> committed snapshot cannot currently satisfy clause (b) of the Sprint 2 definition
> of done, which requires `wip > 0` — live WIP is 0. **A gate that requires someone
> to be mid-task is a gate that rewards a fake transition**, which is what the
> six-minute WIP window in §1.2 actually was. Whether clause (b) should assert
> `wip > 0` at all, or only that the snapshot is fresh and honest about whatever the
> board says, is an owner decision this task surfaces — not one to settle inside it.

### Absorbed doc-truth defect

- **`PLZG-118` is live** — `CLAUDE.md:143` states `~/.claude/plugins/cache/<name>/<version>/`. The real shape carries a marketplace level: `cache/claude-code-skills/grill-with-docs/2.9.0/`. The ticket cites line 199; `PLZG-107` renumbered it. Fix under `T6`, since CLAUDE.md's `weakest_claim` audit reads that section anyway.

### Verified stale — close, do not work

Checked live on 2026-07-31, per the rule that a ticket does not own whether code
is fixed:

- **`PLZG-121`** — "24 release tags documented in CHANGELOG.md are not applied."
  `git tag | wc -l` returns **24**. Fixed by `PLZG-119`. **Closed 2026-07-31.**
- **`PLZG-103`** — "grill-with-specs cites `D-005`/§5.1 mis-origination as live."
  `.claude/skills/grill-with-specs/SKILL.md:80` frames it as **closed** and uses it
  as a worked example. Correct as written. **Closed 2026-07-31.**

Two of the three open tickets spot-checked this session were already fixed. Treat
the open backlog as carrying duplicate and stale rounds; re-verify before working
any of it.

### Explicitly out of scope

- **Lifting the forecast blackout.** §1.3 — the condition is not met and cannot be
  met by a sprint that has not yet produced `started` timestamps.
- **Adopting WIP discipline as a gate.** The behavioural fix failed once already
  (§1.2). Re-attempting it as policy without a mechanism is the same move twice.
- **`PLZG-113`** (index governed docs into gbrain) — feature work.
- **The Godot critical path, M5–M8.** Untouched by this sprint. Per META-SPEC §5.5:
  this sprint does not put M1 → M4 → M8 at risk, and touches no bridge boundary
  (`D-005` swap test not engaged).

## 6. Ownership, budgets, risks

Unchanged from `SPRINT-2-CHARTER` §4–§5 — owner, reviewer and escalation are all
adam schoen; executor is `agent`; 3 attempts per task, 12 iterations per goal;
`T0` exempt and blocking. **Every task carries `acceptance.cmd`, never
`acceptance.criterion`** — with one human, a second reviewer is fiction, and the
honest substitute is an exit code.

Carried risks, both materialised in Sprint 2 rather than hypothesised:

- **R1 — the migration is self-attested.** 24 documents get a value and the
  validator cannot check the values are honest. *Mitigation:* `weakest_claim`
  verbatim-match (DoD check 5) makes each value falsifiable in ten seconds. This
  reduces the risk; it does not remove it (§4).
- **R2 — the board still measures fiction.** Live WIP is 0 and `PLZG-113` sits
  `To Do` while its work merged. *Mitigation:* none this sprint. Named so the next
  charter does not re-derive it as new.

## 7. The sequencing constraint

**This charter could not declare the authority it plans.** `delivery` is created by
`D-028`, whose registered origin is tier-0 `META-SPEC` — **not this charter.** A
tier-3 document plans the amendment and is licensed to originate delivery policy
under it; it cannot originate the authority itself. `T1` made that amendment and
registered `D-028`; the frontmatter *schema* then rejected the value until `T2`
extended the enum, so it stayed undeclarable for one more task even after the
decision existed. The frontmatter above therefore declared `derived` — the
conservative reading §4.10 established, understating its standing rather than
claiming one not yet granted.

Three things had to happen, in order: **`META-SPEC` creates the authority (`T1`),
the schema learns to accept it (`T2`), the charters declare it (`T7`).** Collapsing
any of those into the others is the tier confusion `D-005` cost two releases to
unpick — and describing a tier-3 charter as *creating* an authority would be the
same error `D-028` exists to close. (`D-027` is the enforcement axis and has
nothing to do with authority origin; only `D-028` addresses this.)

That flip happened under `T7`, in the same change that closed §4.10. Recorded
because a reader of an earlier revision would otherwise have seen a charter
declaring `derived` while §3 argued that is wrong, and read it as drift rather
than as sequence.

---

*Last updated: August 2026*
