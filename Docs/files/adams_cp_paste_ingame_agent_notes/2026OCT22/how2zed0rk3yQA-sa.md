- [Context 61a01203-df4f-4cf5-9595-ba248287dfb5]

### You · security-auditor (submitted):

hey how's security roound thhese parts? 

### Assistant · security-auditor (success · memory saved):

I'll start with a quick read-only look at the execution worktree.

No real secrets in tracked files. Next I'll look at the bridge's network surface, the workflows, and the Claude settings.

Two things are still open: how the bridge server binds and who can reach it, and how the Claude review workflow is triggered.

```json
{
  "answer": "Security here looks decent for a local-first prototype. I found no critical issues, and a few things are worth tightening. This was a read-only spot check of the execution worktree (`.../execution`). I changed nothing. I did not run a dependency CVE audit (`pip-audit`/`npm audit`) or the test suite.\n\n**What looks good**\n- **Secrets:** The pattern scan of 419 tracked files found no real keys, tokens or private keys. The only hits were test fixtures and doc examples. `.env` and `gha-creds-*.json` are gitignored, and `.env.example` has blank placeholders only. `report.md` is ignored on purpose because it holds raw Jira titles.\n- **Bridge socket:** `bridge/server.py` binds to `localhost:8765` and sets `origins=[None]`. That rejects any browser connection that sends an `Origin` header, which blocks cross-site WebSocket hijacking from web pages.\n- **Agent tool lockdown:** `domain_sdk.py` gives agents only `Read`, `Edit` and `Bash`. It runs them with `permission_mode=\"dontAsk\"`, empty MCP servers, plugins and skills, `setting_sources=[]`, `strict_mcp_config`, and a turn and budget cap. A `PreToolUse` guard sits on every tool call. `guarded_transport.py` fails closed if the control channel breaks, with a watchdog on guard timeouts. The bundled CLI is pinned by version and SHA-256 hash, so a swapped binary is rejected.\n- **Logging:** `observability.py` logs metadata only (no task text or provider options) and hashes identities.\n- **CI:** `claude-review.yml` pins third-party actions to commit SHAs. It only reviews same-repo, non-draft, non-bot PRs, validates the PR number with a regex, and checks the base branch. Other workflows use `contents: read`.\n- **Subprocess use:** The `subprocess` calls in `bridge/` use argument lists. I saw no `shell=True`, `eval`, `pickle` or `yaml.load`.\n\n**Worth tightening (none critical)**\n1. **No auth on the local socket (medium).** Any local process or user on the machine can connect to `ws://localhost:8765` and drive agents that have `Bash`. The origin rule only stops browsers. If this machine is ever shared, add a per-session token handshake, or use a unix socket with 0600 permissions.\n2. **Bash is only as safe as the guard (medium).** `Bash` in the execution worktree is arbitrary command execution. `guarded_transport.py` says it is \"not a host sandbox\". The guard is the only boundary, so a bug there means full user-level access. Consider an OS-level sandbox (bubblewrap, container, or a separate low-privilege user) as a second layer. This matches the project's own caveat.\n3. **`claude-review.yml` permissions (low-medium).** It has `contents: write` and `id-token: write`, and it commits fixes to PR branches. The same-repo-only gate is good. Still, a compromised or malicious branch from a collaborator could steer the model that holds write access. Branch protection and required human review on `main` and `dev` matter here.\n4. **Marketplace plugins in `.claude/settings.json` (low).** `claude-code-skills` (an `alirezarezvani/claude-skills` GitHub marketplace) is enabled with several plugins. These are unpinned third-party prompts and hooks that load into dev sessions. Pin a ref or vendor what you actually use.\n5. **`.gstack/tmp/*` is committed (low).** These are Codex review outputs and a PR review JSON. I found no secrets in them, but tmp artifacts shouldn't be tracked, so gitignore and remove them.\n6. **Env alias oddity (low).** `domain_sdk.py` reads `CLAUDE_CODE_0AUTH_TOKEN` (a zero, not an O) as a fallback for the OAuth token. It looks like a deliberate workaround for a typo'd variable. Make sure that variable isn't set in shared shells and that the alias is documented or removed.\n7. **Reminder from your notes (not verified here):** the leaked GCP secret in the cookbook repo is still marked unrotated. That is probably the biggest real exposure you have, and it isn't in this repo.\n\n**Suggested next steps, in order**\n1. Rotate the GCP secret.\n2. Add a token handshake on the bridge socket.\n3. Run `pip-audit` against `requirements.txt` and a repo-wide secret scan over git history (`gitleaks`). I only scanned the current tree.\n4. Pin the plugin marketplace and untrack `.gstack/tmp`.\n\nI can do any of these, or go deeper on the tool guard in `readiness.py`, if you want."
}
```

### Human Readable Format by BOOP-GTK:

```yaml
answer: >-
  Security here looks decent for a local-first prototype. I found no critical
  issues, and a few things are worth tightening. This was a read-only spot check
  of the execution worktree (`.../execution`). I changed nothing. I did not run
  a dependency CVE audit (`pip-audit`/`npm audit`) or the test suite.


  **What looks good**

  - **Secrets:** The pattern scan of 419 tracked files found no real keys,
  tokens or private keys. The only hits were test fixtures and doc examples.
  `.env` and `gha-creds-*.json` are gitignored, and `.env.example` has blank
  placeholders only. `report.md` is ignored on purpose because it holds raw Jira
  titles.

  - **Bridge socket:** `bridge/server.py` binds to `localhost:8765` and sets
  `origins=[None]`. That rejects any browser connection that sends an `Origin`
  header, which blocks cross-site WebSocket hijacking from web pages.

  - **Agent tool lockdown:** `domain_sdk.py` gives agents only `Read`, `Edit`
  and `Bash`. It runs them with `permission_mode="dontAsk"`, empty MCP servers,
  plugins and skills, `setting_sources=[]`, `strict_mcp_config`, and a turn and
  budget cap. A `PreToolUse` guard sits on every tool call.
  `guarded_transport.py` fails closed if the control channel breaks, with a
  watchdog on guard timeouts. The bundled CLI is pinned by version and SHA-256
  hash, so a swapped binary is rejected.

  - **Logging:** `observability.py` logs metadata only (no task text or provider
  options) and hashes identities.

  - **CI:** `claude-review.yml` pins third-party actions to commit SHAs. It only
  reviews same-repo, non-draft, non-bot PRs, validates the PR number with a
  regex, and checks the base branch. Other workflows use `contents: read`.

  - **Subprocess use:** The `subprocess` calls in `bridge/` use argument lists.
  I saw no `shell=True`, `eval`, `pickle` or `yaml.load`.


  **Worth tightening (none critical)**

  1. **No auth on the local socket (medium).** Any local process or user on the
  machine can connect to `ws://localhost:8765` and drive agents that have
  `Bash`. The origin rule only stops browsers. If this machine is ever shared,
  add a per-session token handshake, or use a unix socket with 0600 permissions.

  2. **Bash is only as safe as the guard (medium).** `Bash` in the execution
  worktree is arbitrary command execution. `guarded_transport.py` says it is
  "not a host sandbox". The guard is the only boundary, so a bug there means
  full user-level access. Consider an OS-level sandbox (bubblewrap, container,
  or a separate low-privilege user) as a second layer. This matches the
  project's own caveat.

  3. **`claude-review.yml` permissions (low-medium).** It has `contents: write`
  and `id-token: write`, and it commits fixes to PR branches. The same-repo-only
  gate is good. Still, a compromised or malicious branch from a collaborator
  could steer the model that holds write access. Branch protection and required
  human review on `main` and `dev` matter here.

  4. **Marketplace plugins in `.claude/settings.json` (low).**
  `claude-code-skills` (an `alirezarezvani/claude-skills` GitHub marketplace) is
  enabled with several plugins. These are unpinned third-party prompts and hooks
  that load into dev sessions. Pin a ref or vendor what you actually use.

  5. **`.gstack/tmp/*` is committed (low).** These are Codex review outputs and
  a PR review JSON. I found no secrets in them, but tmp artifacts shouldn't be
  tracked, so gitignore and remove them.

  6. **Env alias oddity (low).** `domain_sdk.py` reads `CLAUDE_CODE_0AUTH_TOKEN`
  (a zero, not an O) as a fallback for the OAuth token. It looks like a
  deliberate workaround for a typo'd variable. Make sure that variable isn't set
  in shared shells and that the alias is documented or removed.

  7. **Reminder from your notes (not verified here):** the leaked GCP secret in
  the cookbook repo is still marked unrotated. That is probably the biggest real
  exposure you have, and it isn't in this repo.


  **Suggested next steps, in order**

  1. Rotate the GCP secret.

  2. Add a token handshake on the bridge socket.

  3. Run `pip-audit` against `requirements.txt` and a repo-wide secret scan over
  git history (`gitleaks`). I only scanned the current tree.

  4. Pin the plugin marketplace and untrack `.gstack/tmp`.


  I can do any of these, or go deeper on the tool guard in `readiness.py`, if
  you want.
```

---
~~~javascript
                                                                            o.@@@o@o
                                                                            ( ,   ")'@
                                                                              0  0 @  *@@*  
[1] - (c) 2026 10110TasteslikegoodPlaza - AI.writes._all__({ Re:='served' })`__~~__  `   '8*8 .. .__ . #$% EOF

~~~

exit f(n) = 0
   
