# `.claude/` — agent configuration

Not a governed tree. `scripts/validate_specs.py` only scans `docs/`, `specs/`, `Docs/`, and the
root `README.md`, so nothing here needs frontmatter or a `doc-registry.json` entry.

## `settings.json` — enabled skill plugins

Declares the [`alirezarezvani/claude-skills`](https://github.com/alirezarezvani/claude-skills)
marketplace (as `claude-code-skills`) and enables **six** plugins at **project scope**. The
marketplace is declared here as well as in the user's own settings so a fresh contributor
checkout resolves the plugins without extra setup.

### Two marketplaces, and why only one is declared

`extraKnownMarketplaces` lists `claude-code-skills` and **not** `claude-plugins-official`.
That asymmetry is correct and deliberate — do not "fix" it by adding the second.

| Marketplace | Origin | Declared here? |
|---|---|---|
| `claude-plugins-official` | **Anthropic's official marketplace.** Ships with Claude Desktop, Cowork and Claude Code; appears under its own tab in the plugin UI, separate from personal marketplaces. | **No** — it is built in and resolves without registration. |
| `claude-code-skills` | Third-party (`alirezarezvani/claude-skills`). A personal marketplace, which must be added explicitly before its plugins resolve. | **Yes** — a fresh checkout cannot resolve it otherwise. |

Verified by the repository owner against a live install (2026-07-30). Recorded here
because an automated PR review flagged `superpowers@claude-plugins-official` as
unverifiable from a sandboxed runner with no network — a correct statement about that
runner, and the wrong conclusion about the marketplace. Provenance of a built-in
marketplace is not checkable from inside CI; it is checkable by the owner, and this
table is that check.

| Skill | Why it's here |
|---|---|
| `zero-hallucination-coder` | Grounds code in verified references. Directly serves the META-SPEC binding rules *don't-invent-infrastructure* and *cite-the-source-doc* — this repo has repeatedly been bitten by invented `npm test`-style commands. |
| `grill-with-docs` | Interrogates a plan against the docs it claims to follow. Matches the tier ladder and the conflict protocol in `specs/meta/META-SPEC.md`. Invoke it through `skills/grill-with-specs` — see below. |
| `code-tour` | Persona-targeted walkthroughs — useful for onboarding onto the three autoloads and the `scenes/` layout. |
| `collab-proof` | Post-session retrospective that calibrates what the agent actually got right. |
| `pm-skills` | Atlassian administration — nine skills plus an `atlassian` MCP server. Added 2026-07-28 for the Jira/Confluence overhaul. |
| `superpowers` | Process discipline — brainstorming, systematic-debugging, TDD, plan execution. From the **official** marketplace, hence `@claude-plugins-official` rather than `@claude-code-skills`. Enabled 2026-07-29. |

### `pm-skills` — the largest single addition

It ships **nine** skills (`atlassian-admin`, `atlassian-templates`, `confluence-expert`,
`jira-expert`, `meeting-analyzer`, `pm-skills`, `scrum-master`, `senior-pm`,
`team-communications`) and three commands (`/cs:pm`, `/cs:pm-loop`, `/cs:grill-pm`) — more
than doubling this project's skill count on its own. It was enabled anyway because this
repo really does administer two Jira projects (`PLZG`, `TO`) and a Confluence space
(`PLZA`), and `atlassian-admin` is the tool for that work.

Checked for name collisions before enabling: none of the nine collide with the other five,
the user-scope `agent-harness` / `write-a-skill`, or the gstack suite.

**Known issue — `pm-skills` bundles a deprecated MCP endpoint.** Its `.mcp.json` pins
`https://mcp.atlassian.com/v1/sse`, which Atlassian deprecated on 2026-06-30; every call
through it emits a deprecation banner. The official `atlassian` plugin uses
`https://mcp.atlassian.com/v1/mcp/authv2`. **Prefer `mcp__plugin_atlassian_atlassian__*`
tools.** Editing the vendored marketplace file is futile — it is clobbered on plugin
update — so the fix belongs upstream at `alirezarezvani/claude-skills`.

If the Atlassian overhaul finishes and this stops being used, disabling it again is reasonable.

### Why the set is small — and whose rule that is

**The owner's actual instruction was: import skills without duplications.** The small
fixed set was an *agent's* addition on top of that ask, not a policy the owner set. It was
written up here as though it were project law, which is how a Claude-authored constraint
ends up being enforced against the person it was invented for. Corrected 2026-07-28.

So: dedupe before adding — that rule stands and comes from the owner. Treat the rest of
this section as *rationale worth knowing*, not a gate to argue with a request over.

The rationale: the upstream marketplace ships **88 plugins carrying 342 distinct skills**
(358 counting the skills that appear in both a bundle and a standalone plugin). Enabling
all of them is a bad idea on evidence — this machine had 222 user-scope skills registered
with the Gemini CLI, and the symptom was an agent that looped without ever committing to
an action. Skill-selection quality degrades as the catalogue grows. That is a real cost to
weigh, not a number to enforce.

Count the skills from `marketplace.json` — resolve each plugin's `source` and glob
`<source>/skills/*/SKILL.md`. Do **not** count the fork's `.gemini/skills/` mirror: it holds 436
entries because it also contains slash-commands and gemini-only entries, and at least one dangling
symlink.

### Widening the set

Add one line per plugin to `enabledPlugins`, in the form `<plugin-name>@claude-code-skills`.
Plugin names come from `.claude-plugin/marketplace.json` in the marketplace repo.

Two exclusions are intentional and should not be undone casually:

- **`agenthub`** — ships skills named `init` and `run`, which collide with Claude Code built-ins.
- **`karpathy-coder`** — functionally duplicates the existing user-level `karpathy-guidelines`.

Before adding a plugin, check its skill names against what is already available (user-level
`~/.claude/skills`, the gstack suite, and built-ins) so the catalogue stays free of duplicates.

## `skills/`

Project-local skills committed to the repo.

- **`review-specs`** — the governed-document review pass used when reviewing a PR or branch here.
- **`grill-with-specs`** — the adapter that points `grill-with-docs` at this repo. The upstream
  skill assumes a `CONTEXT.md` glossary and one ADR file per decision under `docs/adr/`, and it
  creates both lazily if they are missing. Neither exists here and neither should: the equivalent
  authorities are `specs/meta/META-SPEC.md` §2 for vocabulary and `specs/meta/decision-register.md`
  for `D-nnn` decisions. The adapter remaps those paths, swaps the three upstream validators for
  `scripts/validate_specs.py` (they parse formats this repo does not use), and adds the tier and
  origin questions the register needs answered before a row can be written.

The adapter is a separate skill rather than an edit to the plugin because the plugin lives in
`~/.claude/plugins/cache/` and is replaced wholesale on the next install or version bump.
