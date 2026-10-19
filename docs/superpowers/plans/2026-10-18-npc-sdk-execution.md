# NPC execution through Claude Code, with explicit API compatibility

**Goal:** Make Claude Code through the Claude Agent SDK the default NPC runtime,
while preserving useful Messages API code behind an explicit API-key-only switch.

**Authority:** Owner clarification, 2026-10-18: normal model execution must run
through Claude Code/Agent SDK; subsequent clarification explicitly retains direct
API code as an optional fallback/switch. This plan applies that instruction and
records it as platform decision D-037. No separate implementation authorization
is required. Existing D-033/D-034 execution timing and domain scope remain intact.

**Architecture:** Shared asynchronous conversation validation/history facade;
two small adapters. Fresh SDK client per NPC request, with bounded serialized
history and deterministic cleanup. The explicit API adapter uses AsyncAnthropic.
The frontend wire protocol and Godot presentation remain unchanged.

Technical design/source evidence: `/workspace/plaza-npc-sdk-design.md`.
Governance inventory: `/workspace/plaza-npc-sdk-doc-audit.md`.
These are local implementation research, not new product-policy authorities.

## Global constraints

- `CONVERSATION_BACKEND` is a nonsecret central setting, exactly `claude_code`
  (built-in and shipped default) or `messages_api` (explicit opt-in).
  `PLAZA_CONVERSATION_BACKEND` follows existing environment precedence.
  Invalid values fail configuration validation. Never select a backend merely
  because a credential exists, and never automatically fall back after failure.
- Default execution reaches the real Claude Agent SDK and Claude Code. It does
  not construct Anthropic clients or call a model HTTP API directly. Preserve
  native Claude Code credential handling; do not require an API key for default
  operation, read credential files, or convert OAuth to direct API credentials.
- Preserve the documented digit-zero token alias by mapping it to canonical
  `CLAUDE_CODE_OAUTH_TOKEN` only when canonical is absent/empty. Native CLI still
  chooses its authentication source. No credential values in diagnostics.
- Explicit `messages_api` requires nonempty `ANTHROPIC_API_KEY`, rejects known
  OAuth/setup-token forms before HTTP, and never reads OAuth/auth-token fallbacks.
  An explicitly supplied key must not accidentally add an inherited Bearer header.
  Retain useful API behavior/dependency; this mode is separately identified.
- Preserve exact legacy response shapes and optional request-ID echo, full task
  and successful reply content, D-005 UI independence, current model assignments,
  60-second configured execution deadline, 4096 output-token cap, 40-message
  success-only per-connection/per-agent context, and independent display/disk bounds.
- SDK clients are fresh per call: one query, no retained clients, resume/continue,
  copied session IDs or SDK history beyond the explicitly bounded transcript.
  Serialize roles/content as JSON data; preserve original user text. The facade
  commits history only after terminal success and cleanup, not from a worker.
- NPC chat remains text-only: no built-in tools, MCP tools, skills or newly
  enabled project hooks/plugins. Use installed supported SDK options. Respect
  mandatory managed policy; do not promise it can be suppressed. Domain behavior
  and permission policy remain unchanged.
- Consume typed assistant and terminal messages. Require actual successful
  terminal completion; no partial-success responses after error, timeout, output
  truncation or unexpected tool execution. Ignore thinking/tool/user echoes;
  avoid duplicating text repeated in the terminal result. Preserve error fields.
- Cancellation, execution deadline, peer disconnect and shutdown drain the SDK
  worker and disconnect/reap the child. Use cancellation compatible with the
  installed AnyIO cleanup scopes; raw asyncio cancellation must not strand it.
  Cleanup may extend beyond the execution deadline; document the bounded SDK
  escalation rather than promising instantaneous teardown.
- Capture only observed SDK session IDs in request-local recorder metadata,
  including errors/cancellation when available. No extra wire fields or shared
  last-session state; no fabricated API provider session ID or durable resume claim.
- No M12 domain UI, durability, worktrees, new model tiers, permission expansion,
  automatic retries/fallback policy, Godot redesign or frozen-evidence rewrite.
  M11 desktop acceptance remains outstanding. Owner retains merge; ticket waiver
  persists. Preserve nine pre-existing untracked Soundtrack WAV import files.

## Task 1: Record the owner runtime requirement

**Files:** Platform authority, decision register, resolved-conflict record,
21 governed metadata versions/current-set mirrors, registry plan exemption,
compact CLAUDE binding pointer and this plan.

- Record D-037 in PLATFORM-DECISIONS, its entitled `decides` list and register:
  default Claude Code/Agent SDK, explicit API-key-only Messages API compatibility,
  no automatic fallback. Preserve D-033/D-034 and prior historical decisions.
- Record the owner-resolved mismatch in spec-driver conflict history; no new
  approval question. Advance doc set 0.2.15 -> 0.2.16 together, preserving dated
  proof and historical version prose. Follow the documentation audit's targets.
- Describe requirements as requirements while runtime correction is in progress;
  do not claim new SDK execution before Task 2 or live proof before Task 4.
  Active operating-description refresh belongs to Task 4.
- Keep CLAUDE <=200 lines. Register this plan as an execution-plan exemption.
- Run governed validator and whitespace checks; self-review authoritative
  origin, owner exception, historical preservation and exact weakest-claim quotes.
  Commit scoped policy/plan prerequisite and write Task 1 report.

## Task 2: Implement both execution adapters and bounded SDK lifetime

**Files:** `bridge/config.py`, `bridge/config.json`, `bridge/conversation.py`,
small SDK/API adapter module(s), `bridge/server.py`, affected Python fixtures
and unit/runtime/wire/observability tests. No Godot production changes.

- Add central selector/dataclass/validation/manifest propagation. Default stays
  Claude Code even with an API key. Old config files inherit that default.
- Convert facade and server invocation to async; remove conversation to_thread.
  Preserve shared validation and copied bounded successful history. Keep the
  direct API implementation in its explicitly selected async adapter.
- Use ClaudeSDKClient/ClaudeAgentOptions from pinned 0.2.136. Exact required
  options include `tools=[]`, `allowed_tools=[]`, `strict_mcp_config=True`,
  `mcp_servers={}`, `setting_sources=[]`, `skills=[]`, `plugins=[]`,
  `permission_mode="dontAsk"`, `max_turns=1`, disabled thinking, inline
  `disableAllHooks`, `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, and supported print/no-session-
  persistence arguments. Do not add unsupported max_tokens options. Follow the
  installed-source design evidence for environment/auth and cleanup details.
- Use request-local completion/session metadata. Backend failures do not select
  the other adapter. Missing API credentials fail before HTTP in explicit mode.
- Preserve existing validation/correlation/history/recording tests while migrating
  provider fixtures to the actual new adapter seam. Domain fakes remain independent.
- Meaningful RED/GREEN tests cover selector/default/no-fallback, API-only auth and
  real offline HTTP headers, native credential alias, exact SDK options, fresh
  sessions/bounded prompts, typed terminal errors/empty/Unicode output and no
  duplicate text, cancellation before/during connect/receive/cleanup, repeated
  cancellation, peer disconnect/shutdown, no late mutation, distinct observed IDs
  for simultaneous callers, and exact old wire shapes.
- Run covering bridge/config/runtime/correlation/observability suites, Black and
  fatal lint. Full UI integration migration belongs to Task 3. Commit and report.

## Task 3: Preserve end-to-end acceptance on the default SDK path

**Files:** Real Godot/Python integration provider fixture, live-runner dependency/
credential checks and tests, any required existing CI/npm wiring. No UI redesign.

- Update the real Godot/BridgeServer deterministic integration to substitute the
  SDK boundary, not the whole engine. Preserve delayed hidden A success/B failure,
  disconnect/reconnect, request IDs, bounded Unicode display and full underlying
  model context. Decode the serialized prompt to prove per-agent isolation and
  fresh context after reconnect. Explicit API compatibility gets separate tests.
- Update live readiness to require Agent SDK/Claude Code, not the low-level
  Anthropic import or an API-key environment variable as universal prerequisites.
  Native saved credentials may exist. Do not claim credential presence proves
  authentication. Never force the API backend just to make the smoke pass.
- Add a test proving default-path failures cannot create an Anthropic client.
  Ensure both credential types follow the same SDK route in controlled tests.
- Run full `.venv/bin/python -m pytest bridge/tests/ tests/ -q`, pinned Godot
  npm/headless/integration gates, Black/fatal lint/spec validator/actionlint and
  diff checks. Verify actual positive markers; keep skips and unavailable live
  credentials distinct from passes. No additional real model calls by builder.
- Notify controller when listener checks finish and port 8765 is free; controller
  runs copied temporary-plan two-client smoke through the real SDK/CLI with cloud
  API credentials. Do not overwrite frozen Sprint 6 evidence. Commit and report.

## Task 4: Finalize accurate operating docs and reviewable correction

**Files:** Current README/QUICKSTART/PROTOCOL/CLAUDE/CHANGELOG, design/roadmap/index/
registry summaries and central setting examples/counts, as identified by audit.

- Describe implemented default runtime, explicit API mode/key requirement,
  native subscription/API credential ownership, no automatic fallback, bounded
  serialized NPC context and fresh SDK session lifetime. Document output cap and
  execution deadline vs teardown; preserve independent display/disk limits.
- Qualify old API smoke as direct-provider compatibility evidence, not SDK proof.
  Add new SDK/CLI evidence only after controller actually observes it. Cloud
  API-key-through-SDK proof does not complete laptop subscription or desktop QA.
- Keep M11 desktop/readback outstanding and M12–M15 planned. Historical baseline,
  archived plans and frozen sprint evidence stay honest. Register/reference D-037
  and config selector consistently; preserve all exact metadata mirrors.
- Validate docs, Black/lint as applicable and diff checks; commit and report.
  Controller owns final whole-branch review, one complete fix wave if required,
  scoped re-review, push/PR to dev and hosted-review handling. Owner retains merge.

## Execution and handoff

Use fresh task builders and independent spec/quality review after each task.
One implementation worker at a time. Ledger/reports/diffs for this plan live in
`.superpowers/sdd/npc-sdk-execution/`; do not reopen completed M11 implementation.
Controller coordinates live calls and never patches production fixes itself.
Stop at the concrete laptop subscription/desktop test boundary when independent
checks and the corrective PR are complete; do not diagnose the original 429 as
resolved unless the user's subscription path actually succeeds.
