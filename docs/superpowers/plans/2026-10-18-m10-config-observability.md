# M10 — Bridge configuration and local observability implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the local bridge one validated settings source and inspectable,
bounded run/agent archives without changing conversation ownership, wire behavior
or domain execution semantics.

**Architecture:** Load an immutable settings object at process startup and inject
it into both engines. A small standard-library storage module owns the writer
lock, JSONL segments, manifests and retention. A recorder integrates that storage
with Python standard logging and captures execution outcomes at their source.
Storage failure suspends recording while the bridge continues serving.

**Tech stack:** Existing Python 3.11+ CI contract; `anthropic==0.121.0`,
`claude-agent-sdk==0.2.136`, `websockets==17.0.1`, `pytest==9.1.1`,
`pytest-asyncio==1.4.0`; standard-library JSON, logging and OS file locks. No new
runtime dependency or logging framework.

**Spec:** [BRIDGE-PLATFORM-DESIGN §§4–6](../specs/2026-10-18-bridge-first-platform-design.md).
The owner approved the written design before PR #339 merged. Planning baseline:
`origin/dev` at `b6a0564`, including merged review-workflow PR #343.

## Execution readiness

**Approved, 2026-10-18:** the owner approved this plan and the written design.
The documentation prerequisites below are satisfied by doc set 0.2.15: `D-033`
supersedes `D-006` with synchronous NPC calls and timeout; `D-034` authorizes async
buffered domains with existing caps; `D-035`/`D-036` ratify M10 settings and local
observability. Conflict §4.13 is resolved by that ruling; issue #341's external
update is separate. M10 implementation is in progress and acceptance remains
outstanding. Owner merge and no sprint changes remain the session constraints.

**Original pre-approval checklist (retained as history; satisfied above):**

- Record written-spec approval and register the newly approved M10 platform
  policies at their entitled implementation tier, as the spec's §8 requires.
  Use `docs/designs/platform-decisions.md` and `specs/meta/decision-register.md`
  for platform decisions; update the design status, registry and affected
  references consistently. If locked decisions change, apply the doc-set version
  procedure in `specs/meta/META-SPEC.md` §8. Do not invent approval or reuse IDs.
- Obtain the owner's ruling on [issue #341](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/issues/341),
  recorded in [open conflict §4.13](../../../specs/meta/spec-drivers-v0.2.5.md).
  Recommended ruling: synchronous, timeout-protected NPC conversations;
  asynchronous domain execution with buffered results and existing turn/budget
  caps. This is a recommendation, not a change to locked `D-006`. If the owner
  chooses synchronous execution for both engines, revise this plan before runtime
  wiring. Keep policy ratification separate from feature implementation.

## Global constraints

- M10 only. M11 gets its own plan: NPC display history, request-ID wire echo,
  resizing, scrolling and keyboard controls. M12–M15 need separate designs.
- Preserve `D-005`/`D-020`: bridge code has no frontend/rendering awareness.
  Preserve `D-015`'s localhost WebSocket and `D-029`'s bridge-owned agent store.
- Use exactly the schema/defaults in design §5. Precedence is built-ins → default
  `bridge/config.json` or `BRIDGE_CONFIG_PATH` → documented `PLAZA_<KEY>` overrides.
  An absent default file may use built-ins; an explicitly selected missing file
  fails. Unreadable files, malformed JSON, unknown keys, unsupported version and
  invalid values fail startup before clients connect or SDK clients are built.
- Reject booleans as numeric limits, non-finite numbers and fractional integer
  limits. Context is even and at least 2; tiers are `haiku`/`sonnet`; levels are
  INFO/DEBUG/WARNING/ERROR; age is a positive integer; enforce
  `4096 ≤ record bytes ≤ file bytes ≤ total bytes`. Model IDs are nonempty strings;
  use the approved IDs, with no automatic fallback or upgrade.
- Resolve relative `LOG_DIR` against the selected config directory (the default
  config directory when using built-ins). Load once; restart to reload. No
  credentials in config or manifests; preserve existing credential precedence.
- JSONL is a diagnostic archive, not restored model context or SDK recovery.
  Context bounds, disk retention and future UI display bounds are independent.
- One unique run per bridge process; one OS writer lock per log root, held for
  the recording lifetime. No stale-PID substitute. Count encoded bytes plus LF;
  quota includes manifests, events, transcripts and atomic-write temporary bytes.
- Prune age first, then oldest eligible files. Never follow symlinks or remove
  unrelated files, SDK data, worktrees or authoritative state. Protect live files;
  seal rotated segments before pruning. Admit every write under the same lock.
- Disk-full, read-only, lock contention and quota exhaustion suspend recording
  with stderr diagnostics. They do not fail requests. Retry on later writes;
  never report success for records that were not written.
- User-facing replies and live context are never truncated for disk bounds.
  Bodies occur only in transcripts; diagnostic events contain whitelisted metadata.
- Owner retains the merge step in this session. Keep tickets outside active
  sprints; use a real PLZG key if available and never invent one. No sprint changes.

## Review focus

1. Environment strings, JSON booleans-as-integers and NaN can bypass superficial
   validation; Task 1 exercises them and all ordering/boundary rules.
2. Unicode JSON escaping, LF and atomic manifest replacement can exceed a byte
   cap even when content fits; Task 2 measures actual on-disk bytes under pressure.
3. A second writer, a crashed writer or a symlink can invalidate ownership and
   pruning assumptions; Task 2 uses subprocesses and external-file sentinels.
4. Domain completion can arrive after disconnect and can be delivered again on
   resume; Task 4 proves one outcome archive with the originating correlation.
5. Recorder exceptions or provider errors containing credential strings can break
   service or leak secrets; Tasks 3–5 inject failures and credential sentinels.

## File map and dependencies

| Owner | Files | Responsibility |
|---|---|---|
| Task 1 | `bridge/config.py`, `bridge/config.json`, `bridge/tests/test_config.py` | Settings, validation and model-tier resolution |
| Task 2 | `bridge/log_storage.py`, `bridge/tests/test_log_storage.py` | Exclusive writer, bounded bytes, manifests, retention, JSONL reader |
| Task 3 | `bridge/observability.py`, `bridge/tests/test_observability.py` | Record schema, request context, standard logging adapter |
| Task 4 | `bridge/conversation.py`, `bridge/domain_session.py`, `bridge/domain_manager.py`, `bridge/server.py`, `bridge/bridge.py`; their existing tests | Startup/engine/lifecycle wiring |
| Task 5 | `bridge/tests/test_observability_integration.py`, `.gitignore`, `QUICKSTART.md`, `bridge/PROTOCOL.md`, `CHANGELOG.md` | End-to-end failure proof and operating instructions |

Order: 1 → 2 → 3 → 4 → 5. One fresh builder per task, then a fresh reviewer for
spec compliance and code quality. No concurrent implementation workers on shared
files. Keep a task ledger and review evidence in an ignored controller workspace;
commit only intentional product changes. Run the whole-branch review after Task 5.

### Task 1: Load and validate immutable bridge settings

**Model defaults updated, 2026-10-18:** the owner confirmed the official
provider IDs `claude-haiku-5-5` and `claude-sonnet-5-5`; Task 1 defaults
and assertions use these replacements under the existing D-035 policy.

**Files:** Create the three Task 1 files above.

**Interfaces:**

- `ConfigError(ValueError)`; frozen `BridgeConfig` with lowercase attributes
  corresponding to every uppercase JSON key in design §5, plus
  `source_path: pathlib.Path` identifying the selected configuration location.
- `load_config(path: Path | None = None, *, environ: Mapping[str, str] | None = None) -> BridgeConfig`.
  A supplied path takes precedence over `BRIDGE_CONFIG_PATH`; both are explicit.
- `default_config() -> BridgeConfig` returns validated built-ins with the default
  source directory, without reading JSON or environment overrides.
- `BridgeConfig.model_for(tier: str) -> str` and
  `BridgeConfig.effective_settings() -> dict[str, object]` (only schema keys,
  uppercase names, resolved LOG_DIR string; never environment/credentials).

- [ ] **1. Write failing tests** for complete default-file/built-in agreement;
  partial-file overlay; explicit-path/env precedence; CWD-independent relative
  paths; startup-only snapshot; setting-specific errors for every invalid input
  class in the constraints. Parse override values using JSON scalar syntax for
  numeric/boolean keys and raw strings for textual keys; reject unknown
  `PLAZA_` names and non-object/duplicate-key JSON. Test both accepted endpoints
  and rejected adjacent values for context/byte limits, and empty model/path values.
  Pin the model defaults to `claude-haiku-5-5` and `claude-sonnet-5-5` and assert
  `CONTEXT_MAX_MESSAGES == 40`, transcript toggle `true`, INFO level and all §5
  timeout/token/turn/budget/byte/age defaults. Credential keys must be rejected.

  ```python
  assert default_config().haiku_model == "claude-haiku-5-5"
  assert default_config().sonnet_model == "claude-sonnet-5-5"
  assert default_config().context_max_messages == 40
  assert config.log_dir == (selected_path.parent / "logs").resolve()
  with pytest.raises(ConfigError, match="CONTEXT_MAX_MESSAGES"):
      load_config(selected_path, environ={"PLAZA_CONTEXT_MAX_MESSAGES": "3"})
  ```

- [ ] **2. Run red:** `.venv/bin/python -m pytest bridge/tests/test_config.py -q`.
  Expect missing config API failures, not a dependency/setup error.
- [ ] **3. Implement** the interfaces, committed JSON and strict validation.
  Keep loading explicit; importing modules must not read files or credentials.
- [ ] **4. Run green:** repeat the focused command; all configuration cases pass.
- [ ] **5. Commit:** `feat: centralize validated bridge settings` with only the
  three Task 1 paths staged.

### Task 2: Store runs safely within retention and byte bounds

**Files:** Create `bridge/log_storage.py`, `bridge/tests/test_log_storage.py`.

**Consumes:** Task 1 `BridgeConfig` and `effective_settings()`.

**Produces:**

- `RunLogWriter(config: BridgeConfig, project_label: str, *, clock: Callable[[], datetime] | None = None)`;
  attributes `run_id: str`, `is_recording: bool`.
- `append(kind: Literal["event", "transcript"], record: dict[str, object], *, agent_id: str | None = None) -> bool`.
  Transcript paths require a valid agent ID; invalid paths return false with a
  diagnostic and no filesystem effects. Writer stamps `schema_version`, `seq`,
  `timestamp`, `run_id`; sequence is run-wide and monotonic across both streams.
- `close(*, clean: bool = True) -> None` (idempotent, releases the lock even when
  manifest finalization fails). `clean=False` never marks a clean shutdown.
- `iter_jsonl(path: Path, *, on_diagnostic: Callable[[str], None]) -> Iterator[dict[str, object]]`.
  Ignore an unterminated final line with a diagnostic; diagnose and skip malformed
  complete lines without rewriting the source. It is an inspection utility only.

- [ ] **1. Write failing tests** for the §6 directory layout, UUID/time uniqueness,
  atomic manifest start/end/settings/status and crash-left-open semantics. Spawn
  real local processes to prove exclusion for one root, independent roots and
  lock release after forced termination. Use stdlib OS advisory locks (POSIX
  `flock`; Windows locking equivalent); unsupported locking suspends recording.
- [ ] **2. Add byte/retention tests:** UTF-8 including multibyte characters, JSON
  escaping and LF; event and transcript rollover before overflow; bounded records
  with `truncated: true`, `original_content_bytes` and a visible content marker.
  Test metadata that cannot fit the record bound: skip visibly, never write an
  oversized record. Assert input dictionaries are unchanged.
  Exercise age pruning, oldest-first quota pruning, rotation sealing, current-run
  sealed segments, protected active files, empty managed folders and atomic
  manifest replacement with both old and temporary bytes charged. Check total
  owned bytes after *each* mutation, including initial/replacement manifests.
- [ ] **3. Add ownership/failure tests:** recognize managed runs by a matching
  schema/run-ID manifest and exact segment names; leave unknown files untouched.
  Refuse unsafe log-root/managed paths; never traverse symlink files/directories.
  External sentinels survive startup and pruning. Inject ENOSPC/EACCES at creation,
  append, flush and replacement (chmod alone is ineffective under root). Verify
  false results, stderr diagnostics, later recovery and no quota overrun. A partial
  failed append must be rolled back or its segment sealed before another record;
  partial writes cannot turn two records into an apparently valid completed one.
  Cover malformed earlier and incomplete final JSONL records in the reader.
- [ ] **4. Run red:** `.venv/bin/python -m pytest bridge/tests/test_log_storage.py -q`.
  Expect missing storage API failures.
- [ ] **5. Implement** a single serialized write path with a thread lock plus the
  lifetime OS lock. Acquire ownership before making a run; keep the lock file
  outside the manifest/event/transcript quota. Use exclusive creation for new
  runs, atomic manifest replacement and flush after complete records. Recheck
  admission on every append; never prune files currently writable by this run.
  Reclaim sealed files before opening a new segment. Failure diagnostics go
  directly to stderr to avoid logging recursion; rate-limit repeated identical
  diagnostics and announce recovery. Do not add a queue or background log service.
- [ ] **6. Run green:** Task 1 and 2 focused suites pass, including subprocess
  crash/exclusion assertions with bounded timeouts.
- [ ] **7. Commit:** `feat: add bounded bridge run storage` with Task 2 paths only.

### Task 3: Define correlated records and standard diagnostics

**Files:** Create `bridge/observability.py`, `bridge/tests/test_observability.py`.

**Consumes:** `BridgeConfig`, `RunLogWriter.append()`/`close()`.

**Produces:**

- Frozen `RequestContext(connection_id: str | None, request_id: str, agent_id: str | None, engine: str, model: str | None, domain_id: str | None = None)`.
  Run identity comes from the writer; contexts never contain task bodies.
- `BridgeRecorder(config: BridgeConfig, project_label: str, *, writer: RunLogWriter | None = None, redactions: tuple[str, ...] = ())`.
- `event(name: str, context: RequestContext | None = None, *, outcome: str | None = None, duration_ms: float | None = None, domain_state: str | None = None) -> bool`.
- `message(context: RequestContext, role: Literal["user", "assistant", "error"], content: str, outcome: str, *, output_id: str | None = None, provider_session_id: str | None = None) -> bool`.
- `close(*, clean: bool = True) -> None`; same idempotent/failure contract as writer.

- [ ] **1. Write failing tests** for required record fields, optional IDs omitted
  when absent, input/success/failure distinction and ordered records from multiple
  worker threads. `TRANSCRIPTS_ENABLED=false` suppresses message records while
  lifecycle/error diagnostics remain available. Repeated failures recover visibly;
  false writer results never become successful capture claims.
- [ ] **2. Test standard logging** at all four levels: INFO includes ordinary
  lifecycle, DEBUG adds routing detail, WARNING/ERROR filter events accordingly.
  Keep manifests and enabled transcripts independent of diagnostic filtering.
  Assert no message bodies in metadata events or stderr, no raw exception text,
  no duplicated handlers after repeated setup/close, and no callback recursion.
  Replace exact nonempty injected credential strings with `[REDACTED]` in disk
  copies and diagnostics, without mutating caller data. Test a provider error
  containing a fake credential; never serialize SDK options or the environment.
- [ ] **3. Run red:** `.venv/bin/python -m pytest bridge/tests/test_observability.py -q`.
- [ ] **4. Implement** the schema/facade and a small `logging.Handler` adapter
  routing whitelisted metadata to the bounded event writer. Use Python standard
  stderr logging; remove only handlers owned by this recorder on close. Disk-only
  redaction precedes byte fitting. Every public recorder call isolates storage
  failures; never catch cancellation or process-exit signals as ordinary errors.
- [ ] **5. Run green:** the config/storage/observability suites pass.
- [ ] **6. Commit:** `feat: correlate bridge transcripts and diagnostic events`.

### Task 4: Wire startup, conversation and domain execution

**Files:** Modify the five runtime files and existing tests in the file map;
add shared temporary-config/recorder fixtures to `bridge/tests/conftest.py`.

**Consumes:** Tasks 1–3; existing protocol request parsing and agent-ID validation.

**Interfaces:**

- Preserve `ConversationEngine(client=None, model=None, timeout=None, *, config: BridgeConfig | None = None)`;
  explicit existing constructor overrides still win. Use configured token/context
  bounds; expose read-only `model: str` for recording.
- Preserve `DomainSession(domain_id: str, base_path: str | None = None, *, config: BridgeConfig | None = None, recorder: BridgeRecorder | None = None)` and
  `DomainManager(base_path=None, *, config: BridgeConfig | None = None, recorder: BridgeRecorder | None = None)`.
- Extend `DomainManager.handle_domain_query(request, on_output=None, *, context: RequestContext | None = None)` and
  `DomainSession.submit_query(agent_id, task, request_id, on_output=None, *, context: RequestContext | None = None)`.
  Carry the immutable originating context into `_execute_query`, not a mutable
  server-wide "current request" slot. Expose `DomainSession.model: str`.
- Preserve `BridgeServer(base_path=None, *, config: BridgeConfig | None = None, recorder: BridgeRecorder | None = None)`;
  extend `dispatch_raw(raw_message: str, histories=None, *, connection_id: str | None = None)` and
  `dispatch(data: dict, histories=None, *, connection_id: str | None = None)`.
  Add idempotent `close(*, clean: bool = True) -> None` for the owned recorder.
- Omitted config uses validated built-in defaults for isolated engine/server
  construction through `default_config()`; omitted recorder disables disk recording there. The actual
  `server.serve()` composition root loads the file/environment once, constructs
  one recorder and injects it into the server and both engines. This avoids
  hidden disk writes; deterministic tests continue to mock provider clients.

- [ ] **1. Add failing tests** proving both tiers, timeout, max tokens, context
  trimming, SDK turns/budget use the injected config; constructor overrides and
  existing auth tests still pass. Changing env/files after construction has no
  effect. Patch SDK/network clients in all deterministic tests.
- [ ] **2. Add routing/lifecycle tests** for start/stop, connection open/close,
  receipt/routing/completion/failure/duration and domain state transitions. One
  UUID per WebSocket connection; internal UUID when no usable request ID exists.
  Respect existing valid request IDs in archives. Rejected/malformed requests
  get metadata diagnostics; invalid agent IDs never create transcript paths.
  Preserve all existing response fields; no conversation request-ID echo in M10.
- [ ] **3. Test outcome ownership:** conversation input/reply or input/failure
  recorded around the awaited engine call. Domain input and final outcome recorded
  once at `_execute_query`; no extra transcript on `_push_output` or resume.
  SDK exception/cancellation produces an error/cancelled archive with sanitized
  category, then preserves current exception/cancellation behavior. A push failure
  after buffered success is a delivery event, not a second execution failure.
  Late domain completion retains the original connection/request IDs. Use actual
  SDK result-session IDs only when observed; do not label the bridge-assigned
  UUID5 as a provider-confirmed session ID. Messages API records omit that field.
- [ ] **4. Run red:** `.venv/bin/python -m pytest bridge/tests/test_conversation.py bridge/tests/test_domain_session.py bridge/tests/test_domain_manager.py bridge/tests/test_server.py -q`.
- [ ] **5. Implement** injection and capture at those boundaries. Retain existing
  per-connection/per-agent context and async domain delivery; do not redesign the
  single-socket domain push mechanism in this milestone. Shutdown releases recorder
  resources in `finally`; failed startup closes any already-open recorder. A
  graceful stop can close the manifest, but exceptions/cancellation without a
  deliberate normal stop must not be marked clean. Invalid config exits with a
  concise setting-specific error and no network initialization.
- [ ] **6. Run green:** `.venv/bin/python -m pytest bridge/tests/ -q`.
  Existing response/history/buffer/credential tests and new wiring tests all pass.
- [ ] **7. Commit:** `feat: wire bridge settings and execution recording` with
  only Task 4 paths staged.

### Task 5: Prove the full lifecycle and document operation

**Files:** Create integration test and modify operating docs/ignore/changelog
listed in the file map. No Godot source or generated agent data changes.

**Consumes:** The complete startup/config/recorder path from Tasks 1–4.

- [ ] **1. Add an integration test** using loopback WebSockets, a real
  temporary recorder and deterministic fake provider clients. Run two connections
  and two agents; assert ordered per-agent disk records with distinct connection
  IDs, unchanged response text and unchanged two-turn model context. Include a
  response larger than a disk record; archived truncation must not affect wire or
  context. Force rotation/pruning with valid small byte settings and inspect
  manifests, event segments and transcripts through `iter_jsonl`.
- [ ] **2. Add service-failure proof** for contending writers, read-only/ENOSPC
  injection and subsequent recording recovery while requests still succeed.
  Set `TRANSCRIPTS_ENABLED=false` in a separate run and assert no transcript files.
  Assert credentials and task bodies never appear in event/stderr output. Start a
  second process after forced termination: it obtains the lock, creates a new run,
  and leaves the previous manifest unclean/open.
- [ ] **3. Run:** `.venv/bin/python -m pytest bridge/tests/test_observability_integration.py -q`.
  If a case fails, add only missing lifecycle fixes to the owning module and
  rerun; if already green, retain the evidence. No test-only public API.
- [ ] **4. Document** exact keys/defaults and env syntax, config path precedence,
  restart-to-reload, model tiers, log folder inspection, retention suspension and
  recovery, and `TRANSCRIPTS_ENABLED=false`. Clarify archive versus live context
  versus future durable state, and leave request-ID wire echo marked M11 intended.
  Document Godot `--log-file`/`--verbose` separately; its files are outside bridge
  quota. Ignore repository `.local/bridge-logs/`; custom external log roots remain
  the operator's choice. Do not ignore the committed `bridge/config.json`.
- [ ] **5. Verify green**, with no live model calls required for deterministic gates:

  ```bash
  .venv/bin/python -m pytest bridge/tests/ -q
  .venv/bin/python -m black --check .
  .venv/bin/python -m flake8 . --select=E9,F63,F7,F82
  python3 scripts/validate_specs.py
  PATH=/workspace/.plaza-tools/bin:$PATH npm test
  git diff --check
  ```

  Expect all bridge cases collected/passing, formatter/linter/spec validation
  exit 0 and Godot headless smoke success. Existing CI already discovers
  `bridge/tests/`; do not add a parallel CI/test framework. Preserve existing
  real two-client conversation gates; run a bounded API-backed two-client smoke
  only after deterministic gates, using bound credentials and a temporary LOG_DIR.
  Avoid updating frozen historical sprint evidence; report live smoke separately.
- [ ] **6. Commit:** `docs: document M10 configuration and recording operation`.

## Handoff and completion

After readiness conditions and plan review, run subagent-driven development:
fresh builder → fresh spec/quality review → fixes → next task. Each task reports
changed paths, test commands/results, remaining risks and its commit. The
controller resolves cross-task interface issues and records findings in the ledger.

After the whole-branch review, open a focused M10 PR to `dev` with evidence for
settings precedence, byte/retention bounds, writer exclusion/recovery and unchanged
legacy chat behavior. Read all review surfaces and address findings; leave merge
to the owner. Only then plan M11's Godot history/correlation, resizing and input
controls against the shipped M10 baseline. M10 does not claim durable sessions.

*Last updated: October 2026*
