# M11 NPC conversation history and controls implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retain bounded per-NPC display conversations, correlate late replies,
and make the existing Godot chat panel resizable and keyboard accessible.

**Architecture:** The existing BridgeClient owns a pure RefCounted display store
and a bounded request-ID map. The panel renders snapshots and owns presentation,
geometry, scrolling and focus. Python adds optional conversation request-ID echo;
provider context, local archives and domain execution retain their M10 ownership.

**Tech Stack:** Pinned Godot 4.7.1 / GDScript, existing Python/WebSocket bridge,
existing pytest/unittest and Godot headless scenes; no new runtime dependencies.

**Spec:** [BRIDGE-PLATFORM-DESIGN §7](../specs/2026-10-18-bridge-first-platform-design.md).
The owner approved that written design, including M11 resizing/key bindings, and
has now instructed continuation of the build after merged PRs #346 and #348.
Preserve the previously selected subagent-driven execution method. This plan is
an implementation artifact under that approved scope, not a new product policy
or a claim that the owner separately reviewed this newly written plan.

## Global constraints

- M11 only. No M12 domain UI, durable state, worktrees, assistant overlay, map,
  streaming, cross-restart display persistence or history download endpoint.
- Preserve D-005/D-015: the Python bridge has no frontend awareness. Request IDs
  are opaque protocol metadata. Legacy requests and existing response fields work.
- Preserve generated agent facts, four existing autoloads, GameEvents signal
  arities and D-007 progressive reveal for new visible replies. No fifth autoload.
- One outstanding request per known agent, indexed by unique client request ID;
  multiple agents may queue on a serial connection. Never guess reply attribution.
- Project settings `plaza/chat/history_max_messages=200` and
  `plaza/chat/history_max_bytes=1048576` bound each known agent across all retained
  generations, including drafts, pending/failed messages and archived drafts.
- Oldest terminal exchanges are evictable; pending content is protected. Reject
  inadmissible draft/input changes visibly. Shorten oversized display replies at
  valid Unicode boundaries with an explicit marker inside the byte bound. Never
  shorten the submitted task, live reply or model context to fit display storage.
- Keep a completion slot and a bounded truncation/error marker available while
  admitting pending content; those reservations do not permit exceeding actual
  configured limits. Do not retain unbounded seen-ID sets or empty generations.
- Disconnect fails every pending request once and archives that generation as
  read-only. Actual reconnect starts a visibly fresh context; no automatic replay
  or silent copying of archived drafts into the fresh editable generation.
- Panel minimum is 480×260 logical pixels when it fits, otherwise viewport size.
  All controls remain reachable after resize/reflow. Retain desired dimensions
  during temporary viewport clamps; preferences are session-only.
- PgUp/PgDn also work while composing; Ctrl+Home/End applies to transcript focus;
  Enter submits once; Escape releases focus preserving draft/pending; Tab and
  Shift+Tab traverse enabled controls. Native composer editing remains intact.
- Owner retains merge; existing ticket waiver and no-sprint-change constraints
  persist. Preserve nine pre-existing untracked Soundtrack WAV import files.

## Review focus

1. Late/mismatched/duplicate/no-ID packets must not clear another request or
   animate a hidden agent's reply. Tests cover malformed packets and generations.
2. Aggregate bounds must include drafts/failures/repeated reconnects; tests use
   tiny limits, Unicode, protected pending content and many empty reconnects.
3. Actual child controls can exceed a clamped panel minimum; geometry/input tests
   inspect real scene rectangles at small and normal viewport sizes.
4. Programmatic scrollbar changes must not masquerade as manual scrolling;
   reading position remains stable across reveal, restored history and resizing.
5. Transcript text contains the first-turn nonce: live recall must inspect only
   the current assistant span in the rendered label, never the whole transcript.

## File map and task boundaries

| Task | Files | Deliverable |
|---|---|---|
| 1 | `bridge/server.py`, conversation/runtime/loopback tests, `bridge/PROTOCOL.md` | Optional opaque request-ID echo on conversation success/errors |
| 2 | `scenes/bridge/conversation_store.gd` + `.uid`, store headless scene/script + `.uid`, project display-limit settings | Pure bounded per-agent display state |
| 3 | `scenes/bridge/ws_client.gd`, `autoload/GameEvents.gd`, transport headless fixtures | Correlated requests and connection lifecycle |
| 4 | `scenes/hud/dialogue_panel.gd/.tscn`, small geometry helper + `.uid` if useful, project input actions, UI headless scenes, existing smoke/live harness | Restored history, resize/scroll/focus controls and honest rendering proof |
| 5 | `package.json`, `.github/workflows/ci.yml`, integration tests, operating docs, current-state design/roadmap/index/registry/CLAUDE summaries, CHANGELOG | Discoverable acceptance, test instructions and truthful handoff |

Tasks run 1 → 2 → 3 → 4 → 5 with fresh builders and independent reviews. Policy
changes are not required: this applies the approved §7 scope within existing
D-005/D-007/D-015/D-016 boundaries. Keep document-set version 0.2.15 unless a real
locked-decision change is discovered; do not invent new decisions for mechanics.

### Task 1: Echo conversation request IDs without changing legacy clients

**Consumes:** Current BridgeServer RequestContext, caller-owned histories and
existing protocol response builders. **Produces:** For conversation requests with
a nonempty, non-whitespace string `request_id`, every returned success/error
(including validation failures) includes that exact ID. Requests without a usable
ID preserve their previous response shape; malformed JSON has no trusted ID.
Domain/lifecycle routing semantics remain unchanged.

- [ ] Add failing Python cases for typed/default conversation success, provider
  error, invalid agent/task validation and simultaneous clients with distinct IDs.
  Keep an exact legacy response-shape case with no supplied ID. Verify recorder
  identity remains the same ID and wire errors still retain existing fields.
- [ ] Run the new cases and observe failure before implementing narrow echo at
  the dispatch conversation boundary. Do not add UI fields to the Python bridge.
- [ ] Update the existing runtime no-echo assertion explicitly for supplied IDs;
  retain its recording/duration assertions. Update current protocol documentation.
- [ ] Run focused server/runtime/loopback cases, full bridge pytest, Black and
  fatal lint on changes; commit `feat: echo conversation request identifiers`.

### Task 2: Build bounded session display state

**Files:** Store helper and dedicated headless store test scene/script; generated
Godot `.uid` files committed. Add the two frontend project settings above.

**Produces:** `class_name ConversationStore`, extends RefCounted, constructed as
`ConversationStore.new(is_known_agent: Callable, max_messages: int, max_bytes: int)`.
The predicate is supplied by existing AgentRegistry.has_agent; unknown IDs cannot
allocate state. No networking, autoload, disk/provider I/O or test-only backdoors.

Interface used by Tasks 3–4:

- `begin_connection() -> int`: advance generation on real socket open; bounded
  metadata and fresh editable context. `generation: int`, `connected: bool`.
- `disconnect_connection(message: String) -> Array[String]`: finalize pending once, archive
  the generation/draft read-only, return failed request IDs.
- `set_draft(agent_id: String, text: String) -> bool`: atomic bounded admission;
  false leaves the prior draft intact. Empty drafts consume no message slot.
- `start_request(agent_id: String, request_id: String, text: String) -> bool`:
  require current connection/known agent/no pending request; move matching draft
  into one pending user message without double counting; reserve a terminal slot.
- `complete_request(agent_id: String, request_id: String, generation: int,
  text: String) -> bool`, and `fail_request(agent_id: String, request_id: String,
  generation: int, kind: String, message: String) -> bool`: only matching current
  pending exchange changes; fit display terminal content without changing caller text.
- `snapshot(agent_id: String) -> Dictionary`: deep copy containing `messages`,
  `draft`, `pending`, `connected`, `generation`, `scroll`, `follow`, `omitted`,
  `content_bytes`, `message_count`. Message records contain `request_id`, `role`,
  `content`, `status`, `generation`, `truncated`, `original_bytes` as applicable.
- `save_view(agent_id: String, scroll: float, follow: bool) -> void`: bounded
  per-agent view state. The helper does not emit global UI/transport notifications;
  BridgeClient owns notification ordering after complete mutations.

- [ ] Write headless failures for two agents, drafts/scroll, unknown-agent
  rejection, one pending per agent, matching/duplicate/stale completion, failures,
  disconnect/reconnect, archived draft and fresh context with no replay.
- [ ] With tiny limits, prove exact message/UTF-8 accounting, draft movement,
  oldest whole-exchange eviction, protected pending admission, oversized Unicode
  reply marker, repeated reconnects with and without messages, and snapshot-copy
  isolation. Include byte-zero-space/slot exhaustion at terminal completion.
- [ ] Implement the store with ordered bounded messages and derived/coalesced
  generation boundaries, not unbounded generation containers or seen-ID sets.
- [ ] Run import and the store headless scene using pinned Godot 4.7.1, verify
  generated UIDs, commit `feat: retain bounded NPC display conversations`.

### Task 3: Own request correlation and lifecycle in BridgeClient

**Consumes:** Task 1 echo and Task 2 exact store interface.
**Produces:** Existing `BridgeClient` owns `conversations: ConversationStore` and
`_pending_requests[request_id] = {agent_id, generation}`; no permanent completed-ID
set. `send_query(agent_id: String, task: String) -> String` returns the admitted
ID or empty on rejection. Unique IDs combine session randomness, generation and
counter; at most one pending per known agent. Add wrappers
`conversation_snapshot(agent_id) -> Dictionary`, `set_draft(agent_id, text) -> bool`,
`save_conversation_view(agent_id, scroll, follow) -> void` for panel access.

Preserve old GameEvents signal arities; add
`conversation_changed(agent_id: String, reason: String, request_id: String)`.
Reasons are `input`, `reply`, `failure`, `draft`, `connection`, `view`. Mutate store
and remove only the matching pending map entry before notifications. The panel
never owns pending state or discards hidden-agent results.

- [ ] Write failing transport/lifecycle checks with a real loopback fake WebSocket
  peer or the smallest ordinary transport boundary. Assert exact outgoing ID/task,
  pending registration before synchronous send failure, A and B pending, hidden A
  success then B failure, duplicates/unknown/stale/mismatched/no-ID/malformed packets.
- [ ] Implement unique IDs and validated response types. Uncorrelated malformed
  packets cannot guess an agent or clear a request; use a protocol diagnostic or
  explicitly fail the entire broken connection when appropriate.
- [ ] Advance generation only on actual open; on close fail every pending request
  once, clear map, archive draft/history and notify affected views. Offline send
  rejection preserves the draft without changing a read-only archived generation.
- [ ] Run store plus transport scenes and Python echo tests. Commit
  `feat: correlate NPC requests across focus and reconnect`.

### Task 4: Render history and implement resize, scrolling and focus

**Consumes:** BridgeClient wrappers/signal and store snapshots. **Produces:** The
existing HUD scene retains its essential node paths; bounded desired/current panel
geometry and per-agent scroll/follow/draft restoration. A small pure geometry
helper may expose `clamp_rect(rect: Rect2, viewport: Vector2, minimum: Vector2)`
and `resize_rect(rect: Rect2, delta: Vector2, edges: int, viewport: Vector2,
minimum: Vector2) -> Rect2` if it reduces the panel's responsibilities.

- [ ] Add headless scene failures for A→B→A, hidden success and independent error,
  per-agent draft/pending/scroll restoration, disconnect archives and new-context
  notices. An unrelated NPC-left signal cannot close the selected agent's panel.
- [ ] Render snapshot records with plain-text role/status/boundary labels; show
  introduction only for empty history. Restore all cached messages immediately.
  New visible assistant reply starts reveal at its span; older text stays visible.
  Retain identifiable assistant spans for live harness readback from BodyLabel.
- [ ] Write actual input/geometry failures for edge/corner drags, minimum/clamps,
  small viewport child rectangles, desktop shrink/grow, wheel/scrollbar, paging,
  composer/native Home/End/copy, transcript Ctrl+Home/End, Enter once, Escape,
  Tab/Shift+Tab, and player position while GUI owns focus. Keep the existing player
  focus guard unless these checks expose a specific defect.
- [ ] Add named project InputMap actions `chat_page_up`, `chat_page_down`,
  `chat_oldest`, `chat_newest`, `chat_submit`, `chat_release_focus`,
  `chat_focus_next`, `chat_focus_previous`. Bind exact modifiers per §7 and verify
  serialized events under pinned 4.7.1. Keep one submission path, no double Enter.
- [ ] Implement viewport-coordinate edge/corner resizing and adaptive layout. Save
  desired dimensions separately from clamped geometry. Release chat focus without
  clearing draft/pending; keep explicit enabled-control focus order.
- [ ] Follow only when previously at bottom; manual upward scrolling stops follow,
  bottom/Ctrl+End resumes it. Preserve reading position through layout changes;
  use guards around programmatic scrollbar updates.
- [ ] Update smoke to admit a matched request/result and inspect transcript roles;
  preserve all existing world/registry/scene/typewriter-band assertions. Update
  live_conversation.gd so `received` is the current assistant span actually read
  from BodyLabel, never the whole transcript or just the signal payload. Sample
  reveal relative to that span. Add a regression ensuring an incorrect second
  reply cannot pass because turn-one user text contains the nonce.
- [ ] Run all Godot store/transport/UI scenes and existing smoke; Python live
  harness tests as relevant. Commit `feat: add usable NPC chat history and controls`.

### Task 5: Integrate gates and prepare desktop acceptance

**Consumes:** Completed Tasks 1–4. **Produces:** Existing CI/npm discover all M11
headless scenes; operating docs and current-state summaries match shipped code
while desktop verification remains explicitly outstanding until actually done.

- [ ] Add M11 headless commands to existing npm/CI Godot gates, preserving current
  validate/import/smoke gates and bridge tests. No new parallel test framework.
- [ ] Exercise a complete delayed-response/reconnect path with deterministic fake
  provider and real client/bridge wiring. Keep failure/draft/content bounds honest.
- [ ] Update QUICKSTART, PROTOCOL, CHANGELOG and relevant README/CLAUDE/design/
  roadmap/index/registry summaries. Explain independent model/display/disk limits,
  fresh-context reconnects, frontend settings and all controls. Keep CLAUDE under
  200 lines; update exact weakest_claim quotes if changed. Do not claim M11 desktop
  acceptance or M12 completion from headless/API tests.
- [ ] Run `.venv/bin/python -m pytest bridge/tests/ tests/ -q`, Black, fatal Python
  lint excluding local .venv, `python3 scripts/validate_specs.py`, pinned `npm test`,
  each M11 scene, and `git diff --check`. Investigate actual failures; do not rerun
  unchanged passing gates merely to expand the checklist.
- [ ] Controller runs a bounded real Godot+Python API smoke using copied temporary
  plan/output and LOG_DIR, preserving frozen Sprint 6 evidence. Inspect actual
  assistant-only recall, correlation and no transcript replay. This is distinct
  from a manual desktop test and must not be presented as that test.
- [ ] Publish an exact desktop checklist: A→B→A/draft/late success and B failure;
  drag all edges/corners; shrink/grow the desktop; wheel/scrollbar/manual reading
  during reveal; paging/focus/native edits; disconnect/reconnect notices. Record
  user results before calling complete M11 acceptance.
- [ ] Commit, independent final review, push/open focused M11 PR to dev. Read all
  review surfaces and job logs. Owner retains merge; do not expand into M12 before
  the desktop acceptance boundary is resolved.

## Handoff

Use the approved subagent-driven method, fresh context per builder/reviewer and
one implementation worker at a time. Record progress/review evidence in the
ignored controller workspace. Check interfaces after each task, fix real findings,
and preserve resulting commits on the PR branch. The final handoff distinguishes
implemented/tested code from the local desktop verification owed by the owner.
