# GBrain semantic search — per-machine, not repo infrastructure

> Split out of `CLAUDE.md` under `PLZG-107` to hold that file to META-SPEC §6's ~200-line
> instruction budget. Nothing in CI touches GBrain and a contributor without it loses no gate.


<!-- gstack-gbrain-search-guidance:start -->

GBrain is a per-machine semantic index, not part of this repo — nothing in CI
touches it and a contributor without it loses no gate. Prefer it over Grep when
the question is semantic or you don't yet know the identifier; Grep stays right
for exact strings, regex, multiline patterns and file globs.

**Coverage: code *and* the governed doc set, as of 2026-07-29.** The source
carries **39 file-backed pages — 26 markdown + 13 code** — so `specs/meta/`,
`docs/designs/`, `docs/storyboard-week1.md`, the decision register and this file
are all searchable alongside the Python tooling, the CI workflow YAML,
`data/agents.json` and `package.json`. Guidance written before that sync claimed
the documents were absent, because until then only code was indexed.

**Sync with `--strategy auto`, never bare and never `--strategy code`.** Strategy
is chosen per run, but the source stores a *single* `last_commit` bookmark shared
by every strategy. A `--strategy code` run advances that bookmark past commits
whose only changes were markdown, and those doc edits are then skipped
permanently — the bookmark says they are already synced. `auto` walks both file
classes under one bookmark and is the only setting that keeps them consistent:

```bash
gbrain sync --source "$(cat .gbrain-source)" --strategy auto --no-pull
```

This matters because `/sync-gbrain` issues `--strategy code` on its own. After
running that skill, re-run the `auto` sync above or the docs silently go stale —
a stale-bookmark skip reports success.

**One source per path subtree.** `gbrain sources add` refuses any path
overlapping an existing source in either direction; a subdirectory and a parent
both count. The worktree root is already claimed as a code source, so a separate
`docs/`-or-`specs/` markdown source **cannot** be registered. That is why
documents and code share one source rather than living in two.

**The walker enumerates git-tracked files, which is what keeps `report.md` out.**
That file is generated output whose content is Vegangenius Chef recipe-app rows
under a "10110 Tasteslikegood Plaza" heading (see § Python scripts). While it was
still tracked it got indexed and became the top hit at **0.92** for any Plaza
status question, answering with the wrong project's data; the page was deleted by
hand. It is now untracked and gitignored, so the walker skips it — but that is a
side effect of a disclosure decision, not a search safeguard. If it is ever
re-tracked it will be re-indexed, and the fix is
`gbrain delete report --source "$(cat .gbrain-source)"` after the sync.

**Verify a `D-nnn` citation by Reading the register, not from a search hit.**
Retrieval returns the chunk it judges closest, and adjacent rows in a decision
table look near-identical to an embedding. Use gbrain to *find* the row, then
open `specs/meta/decision-register.md` to confirm its id, status and origin
before citing them. A governed claim sourced only from a search snippet is the
defect class `.claude/skills/review-specs` exists to catch.

**This worktree is pinned to a worktree-scoped source** via `.gbrain-source` in
the repo root (kubectl-style context, gitignored). `gbrain search`, `query`,
`code-def`, `code-refs`, `code-callers` and `code-callees` route there by default
from anywhere under the worktree — no `--source` flag. Sibling worktrees each
carry their own pin, so results match the code on disk.

Symbol extraction is **partial**: `code-def` resolves some symbols (`main`) and
misses others (`check_decisions`, which `code-refs` finds fine). A `count: 0`
from `code-def` is not proof a symbol is undefined — fall back to `code-refs` or
Grep before concluding anything.

Two corpora are reachable from the CLI: this worktree's code and documents
(auto-pinned), and `~/.gstack/` curated memory as source `gstack-artifacts-adam`.

The agent `.md` bodies in `claude-code-tresor` are **not** indexed and do not
need to be: `data/agents.json` already carries every agent's `name`, `role`,
`dept`, `description` and `tools`, and answers agent-selection queries as the top
hit. Index the submodule only if you are authoring agent prompts in the fork, and
then as an *isolated* source (`--no-federated`), so the submodule's 342
markdown files — of which 133 are actual `agent.md` bodies — cannot outrank
this project's 39 pages on Plaza questions. The same reasoning
rules out indexing the `alirezarezvani/claude-skills` marketplace: Claude Code
selects skills from SKILL.md frontmatter in the plugin cache, a different
mechanism from semantic search, so indexing 2,717 files would buy dilution and
no better skill selection.

Embeddings are billed to the OpenAI account (`text-embedding-3-large`). A sync
whose per-page output reads `Error embedding …: You exceeded your current quota`
still reports every stage `OK` while writing zero searchable chunks — run an
actual `gbrain search` against a known file before trusting a green sync.

<!-- gstack-gbrain-search-guidance:end -->
