---
doc_id: SPRINT-3-CHARTER
title: Sprint 3 charter — the doc set declares what is proven
tier: 3
authority: derived
status: ACTIVE
doc_set_version: 0.2.9
last_updated: 2026-07
owner: adamtasteslikegood
derives_from: [META-SPEC, SPEC-DRIVERS-025, SPRINT-2-CHARTER]
---

# Sprint 3 charter — the doc set declares what is proven

> **One line:** this document is the complete executable context for Sprint 3. A
> session that has read this file needs nothing from the conversation that
> produced it.

`PLZG Sprint 3` (board `169`, sprint id `45`) is **`future`**, scoped
**2026-07-31 → 2026-08-14**, carrying nine tasks under two tickets:
**`PLZG-131`** (this charter and the `META-SPEC` amendment, `T0`–`T4` and
`T6`–`T8`) and **`PLZG-130`** (`T5`, the snapshot staleness check).

Open questions that were *not* settled in the session that produced this charter
are recorded as a comment on `PLZG-131`, not left in the transcript.

**Sprint goal:** every governed document declares which of its claims about state
are proven and by what — and the tier ladder gains a home for delivery policy.

> **Sprint 2 is still `active` in Jira** (sprint id `44`, ends 2026-08-14) despite
> the repo recording `CLOSE-OK` on 2026-07-30 and all nine committed items sitting
> `Done`. Sprint 3 was created in `future` state precisely so it needs no change to
> that. Closing sprint 44 is a human call and is **not** a task below. Note also
> that `SPRINT-2-CHARTER` states the window as 2026-07-30 → **08-13** while the
> board says **08-14** — the board owns this, so the charter is the bug. Both are
> instances of R2 (§6), now visible in the sprint object itself.

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

### Three charter claims that did not survive a live check

Recorded because the sprint's own goal was *"make every doc claim about state
match the system that owns it."*

1. **The definition-of-done gate is green on a claim that is now false.**
   `scripts/validate_delivery_coordinates.py` exits 0 reporting `wip=1`. Every
   open PLZG issue is `To Do` today: **live WIP is 0.** The gate reads
   `data/plzg-flow-snapshot.json`, frozen at 14:20 on 2026-07-30. `as_of` is read
   only to print it — there is no staleness check, so the gate will still pass in
   2027 reporting a July 2026 board.

2. **The `In Progress` fix did not take.** The single WIP item was `PLZG-125`,
   created 14:14 and snapshotted 14:20 — six minutes, one ticket, the one whose
   subject was the gate itself. The other 13 completions went `To Do` → `Done`.

3. **The forecast blackout cannot lift, despite 14 completions.** §3 of the
   Sprint 2 charter requires *"10+ completions carrying real `started→resolved`
   timestamps, drawn from a window containing no zero-throughput weeks."* Thirteen
   of fourteen have no `started` at all, and all landed inside one day — the
   window is a single point. The condition reads satisfiable-on-count; it is not.

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
declares `derived` — licensed to originate nothing — while setting a WIP limit,
retry budgets, a review gate and a forecast blackout that nothing else sets.

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
2. `enforced` / `asserted` declare a non-empty `gates:` list, each entry naming a
   job that **exists in `.github/workflows/ci.yml`**, each typed `live` or
   `snapshot`.
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
job absent from `ci.yml`; a `weakest_claim` not present in its file; a stale
snapshot. Shape it after `tests/check_sync_matrix.sh`, which builds its own
fixtures and needs no network.

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

Sequenced. `T1`–`T3` must land before `T6`, and `T2` before the charter can
declare its own authority (see §7).

| | Item | Acceptance |
|---|---|---|
| `T0` | Fetch / reconcile. **Blocking, exempt from the attempt cap.** | `scripts/check_sync.sh --strict` |
| `T1` | Amend `META-SPEC` — define the `enforcement` axis (§3 `D-027`) and add `delivery` to the authority vocabulary (§3 `D-028`). Add `decides: [D-027, D-028]`. | `validate_specs.py` |
| `T2` | Extend `spec-frontmatter.schema.json` — `enforcement` enum, `gates[]` of `{job, type}`, `weakest_claim`, `authority` += `delivery` with `x-may-originate: true`. | `validate_specs.py` |
| `T3` | Extend `validate_specs.py` — DoD checks 1–5, reading permitted values **from the schema**, never restated in the script. | `tests/spec_enforcement_matrix.sh` |
| `T4` | `tests/spec_enforcement_matrix.sh` + a `Spec Enforcement Matrix` CI job. | the matrix, exit 0 |
| `T5` | Snapshot staleness check in `validate_delivery_coordinates.py` — **`PLZG-130`**. | `validate_delivery_coordinates.py` |
| `T6` | Migrate 23 documents — assign `enforcement`, `gates`, `weakest_claim`; registry entries; `n/a` reasons. | `validate_specs.py` |
| `T7` | Re-point `SPRINT-2-CHARTER` to `authority: delivery`; close §4.10 with the resolved-by-amendment note; register `D-027`/`D-028`. | `validate_specs.py` |
| `T8` | Bump `doc_set_version` 0.2.9 → 0.2.10 across the set; CHANGELOG under `[Unreleased]`. | `validate_specs.py` |

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

- **R1 — the migration is self-attested.** 23 documents get a value and the
  validator cannot check the values are honest. *Mitigation:* `weakest_claim`
  verbatim-match (DoD check 5) makes each value falsifiable in ten seconds. This
  reduces the risk; it does not remove it (§4).
- **R2 — the board still measures fiction.** Live WIP is 0 and `PLZG-113` sits
  `To Do` while its work merged. *Mitigation:* none this sprint. Named so the next
  charter does not re-derive it as new.

## 7. The sequencing constraint

**This charter cannot declare the authority it creates.** `authority: delivery`
does not exist until `T2` lands, so the frontmatter above declares `derived` —
the conservative reading §4.10 established, understating its standing rather than
claiming one not yet granted.

Flip it to `delivery` under `T7`, in the same change that closes §4.10. Recorded
because a later reader will otherwise see a charter declaring `derived` while
§3 argues that is wrong, and read it as drift rather than as sequence.

---

*Last updated: July 2026*
