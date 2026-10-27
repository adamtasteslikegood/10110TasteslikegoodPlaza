# M13 local acceptance and evidence

This is the owner runbook for the [approved persistence design](superpowers/specs/2026-10-26-m13-sqlite-session-persistence-design.md).
Implementation and container tests do not complete desktop, provider or OAuth
acceptance. The controller runs paid guards only after independent source review.
Do not commit private transcripts, project exports, raw logs or credentials.
Historical M12 reports keep their original hashes and observations.

## Prepare the exact reviewed runtime

Use the reviewed M13 checkout, its pinned `requirements.txt`, Git prerequisites
from [QUICKSTART](../QUICKSTART.md), and the CI-pinned Godot **4.7.1**. Set
`GODOT_BIN` to its absolute executable path and put its directory on `PATH`.
Activate the repository Python environment. Use a separate Plaza code checkout
for acceptance; do not switch branches in a bridge-managed execution worktree.
The disposable test project below is separate from that code checkout. From the
repository root:

```bash
python -m pip check
python scripts/m13_state_probe.py --help
python scripts/m12_tool_guard_probe.py --help
umask 077
M13_PRIVATE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/plaza-m13-private.XXXXXXXX")
export M13_PRIVATE_DIR
python scripts/m13_state_probe.py desktop-template --engine "$GODOT_BIN" --permission-mode dontAsk --authentication oauth --output "$M13_PRIVATE_DIR/desktop-template.json"
python scripts/m13_state_probe.py performance --engine "$GODOT_BIN" --repeats 5 --output "$M13_PRIVATE_DIR/performance.json"
python scripts/m13_state_probe.py validate --kind performance --engine "$GODOT_BIN" --report "$M13_PRIVATE_DIR/performance.json"
```

The template deliberately contains `passed:false`; writing it grants no acceptance.
It binds exact application/client/probe sources, every pinned installed dependency,
SDK/CLI version and CLI binary SHA, Python/SQLite, OS/release/architecture, and
Godot version/binary SHA. Validation recomputes this binding and rejects stale
sources, changed runtimes, missing/duplicate cases, wrong backend/mode/auth path,
oversized reports and incomplete observations. Reports are capped at 256 KiB;
new destinations are reserved before work and never overwrite old evidence.

`performance` creates three isolated processes and disposable state directories.
Representative content has eight results; dense content has ten applications,
160 retained results, 40 MiB output, 20 MiB duplicated tasks, and 3.125 MiB JSON
escape overhead, plus SQLite pages. The exact 64 MiB boundary complements those
populated measurements by padding representative state with SQLite free pages.
It is not a worst-case content workload. Each profile reports actual serialized
size, final occupied/free-page bytes, repeated Start/Stop commit latencies,
physical replacement counts, observed old-image-plus-temporary-image disk peak,
process peak RSS and increase above its pre-fixture peak, and heartbeat maximum
gap. The worker barrier requires heartbeat and committed replay progress before
release, while the writer is still pending and the committed revision unchanged.
Failed remnants can consume additional disk; the image cap is not a disk quota.
`ru_maxrss` is cumulative process high-water, which can include inherited startup
high-water on Linux. `baseline_rss_bytes` is the pre-fixture high-water;
`process_overhead_bytes` is its increase, not incremental allocated bytes or current
live RSS. Zero increase does not mean zero allocation. RSS includes fixture
construction, validation, serialization and Python views;
these measured costs do not promise a latency or total memory bound on other hosts.
Choose a private existing `TMPDIR` on the filesystem whose image writes you want
to measure (for example `TMPDIR=/absolute/private/path python ...`). `/tmp` may be
tmpfs. Record the actual filesystem and host load with the report; do not label a
container/tmpfs/overlayfs run as SSD or power-loss durability evidence.

The [latest boundary-correction Linux measurement](../specs/evidence/m13-state-performance-linux-2026-10-27-boundary-correction.json)
was freshly measured after QA drained, from dirty `4217a142` with the final
`3b82ff23` runtime/test content, using a new private overlayfs TMPDIR. Its
196-source digest is
`0b28db6e8df0b61ac3e8347cd7adf2b7286fcb668724181f3e3c84143b28d315`.
The dense 66,478,080-byte image measured 549,863,424 bytes cumulative peak RSS
(496,934,912 above baseline), five commits of 287.63–510.20 ms, and a maximum
heartbeat gap of 225.67 ms. Each of the three profiles completed nine or ten
heartbeats and five committed replay reads before the deliberately blocked writer
released. The exact 64 MiB boundary profile has mostly free pages; it is separate
from the dense populated profile. These remain material owner/deployment costs,
with no invented SLO or physical SSD/power-loss claim.

Strict incoming-byte validation also adds bounded receiver work. An actual
2,097,517-byte escaped frame's test sampling window measured 320.25 ms versus
112.77 ms before validation; that window includes scheduling, parsing and UI
application, rather than isolated guard time. This is a container observation,
not owner-desktop acceptance or a latency promise. Actual producer maximum frames
remain covered; nonproducer vertical-tab metadata can be conservatively rejected
within four bytes of the nested limit due to Godot's escaping representation.
Provider, owner desktop and OAuth acceptance remain separate and pending. The
[earlier final-review-fix receipt](../specs/evidence/m13-state-performance-linux-2026-10-27-final-review-fix.json),
[October 27 pre-fix receipt](../specs/evidence/m13-state-performance-linux-2026-10-27.json)
and [October 26 checkpoint](../specs/evidence/m13-state-performance-linux-2026-10-26.json)
keep their original bytes, source/runtime bindings and measurements.

## Authenticate and run the reviewed guard campaign

Use the owner's existing chosen login. Inspect only safe fields from the bundled
CLI's `auth status --json` locally; never publish the full response or request,
copy, extract or print tokens. Confirm the CLI reports the intended authenticated
method. API-key acceptance and OAuth acceptance are separate observations.
A safe read-only preflight prints only allowlisted status fields:

```bash
python - <<'PY_AUTH'
import json
import subprocess
from pathlib import Path
import claude_agent_sdk
cli = Path(claude_agent_sdk.__file__).parent / "_bundled/claude"
result = subprocess.run([str(cli), "auth", "status", "--json"],
                        capture_output=True, text=True, timeout=10)
status = json.loads(result.stdout)
method = status.get("authMethod", status.get("auth_method"))
print(json.dumps({"exit_code": result.returncode,
                  "logged_in": status.get("loggedIn", status.get("logged_in")) is True,
                  "auth_method": method if method in ("api_key", "oauth", "claudeAi", "none") else "unrecognized"}))
PY_AUTH
```

An unavailable, unrecognized or unauthenticated method remains pending. An
already authenticated `claudeAi` method is the CLI's account-login path; verify
its account/billing context locally without publishing identity fields.
Unsetting an API key does not prove OAuth is available. Cloud Task 10 has no OAuth
login and cannot provide fresh OAuth evidence; the owner laptop must do so using
its existing login. If auth is unavailable, leave that path pending.

These are explicit paid commands. Each run stops at the first failed case, with
no automatic retry. Inspect its report before authorizing another run:

```bash
python scripts/m12_tool_guard_probe.py --permission-mode dontAsk --output "$M13_PRIVATE_DIR/guard-dontAsk.json"
# Inspect the first report before deliberately running the second mode.
python scripts/m12_tool_guard_probe.py --permission-mode bypassPermissions --output "$M13_PRIVATE_DIR/guard-bypassPermissions.json"
```

The complete matrix is **33 cases per mode**, at most 31 model queries, model
`claude-haiku-5-5`, 45 seconds and USD 0.20 per case. Original Read/Edit/Bash,
MCP/delegated and cancellation controls remain. Four new Bash sentinels run
through the owner's installed production `PreToolUse` callback, the production
session `_ExecutionReadiness`, real coordinator commits and manager authority:
storage failure and stale execution before the callback; storage failure and
same-application execution replacement during awaited readiness. Both timings
must report the expected reason, observed transition, no sentinel or successful
tool/PostToolUse result, and clean owned SDK/process/hook shutdown. The storage
fixture injects a failure at its disposable image replacement boundary; it does
not claim a physical full-disk event. MCP/delegation remain probe-only tools.

Build a new private envelope from both unchanged fresh reports, checking current
source and local runtime, without activating or modifying old artifacts:

```bash
python - <<'PY'
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import claude_agent_sdk
from bridge.domain_sdk import check_acceptance
from bridge.tool_guard_evidence import VERSIONS, acceptance_envelope
from scripts.evidence_output import FreshEvidenceOutput
p = Path(os.environ["M13_PRIVATE_DIR"])
records = [json.loads((p / ("guard-" + mode + ".json")).read_text())
           for mode in ("dontAsk", "bypassPermissions")]
cli = Path(claude_agent_sdk.__file__).parent / "_bundled/claude"
versions = {"sdk": importlib.metadata.version("claude-agent-sdk"),
            "anyio": importlib.metadata.version("anyio"),
            "cli": subprocess.check_output([str(cli), "--version"], text=True).strip()}
assert versions == VERSIONS
with cli.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
assert all(r["cli_sha256"] == digest for r in records)
envelope = acceptance_envelope(records)
for mode in ("dontAsk", "bypassPermissions"):
    check_acceptance(envelope, None, mode)
with FreshEvidenceOutput(p / "guard-envelope.json") as output:
    output.publish_json(envelope)
print("Both current-source/current-runtime modes accepted; activation remains separate")
PY
```

After independent source review and genuinely fresh complete 33-case reports,
the controller may install that unchanged private envelope with this explicit
local operation. The committed envelope now contains the fresh 33-case pair
recorded below for the reviewed cloud API-key runtime. A different source/runtime
must obtain matching evidence; owner desktop and OAuth acceptance remain pending.
Preserve the exact existing envelope before replacement:

```bash
python - <<'PY_INSTALL'
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import tempfile
import claude_agent_sdk
from bridge.domain_sdk import ACCEPTANCE_PATH, check_acceptance, _verify_runtime
from bridge.tool_guard_evidence import VERSIONS
private = Path(os.environ["M13_PRIVATE_DIR"])
payload = (private / "guard-envelope.json").read_bytes()
assert len(payload) <= 4 * 1024 * 1024
envelope = json.loads(payload)
cli = Path(claude_agent_sdk.__file__).parent / "_bundled/claude"
assert {"sdk": importlib.metadata.version("claude-agent-sdk"),
        "anyio": importlib.metadata.version("anyio"),
        "cli": subprocess.check_output([str(cli), "--version"], text=True).strip()} == VERSIONS
with cli.open("rb") as stream:
    fingerprint = hashlib.file_digest(stream, "sha256").hexdigest()
for mode in ("dontAsk", "bypassPermissions"):
    record = check_acceptance(envelope, None, mode)
    assert record["cli_sha256"] == fingerprint
# Read/write exact original bytes; exclusive backup never replaces prior evidence.
old = ACCEPTANCE_PATH.read_bytes()
backup = private / "guard-acceptance-before-m13.json"
with backup.open("xb") as stream:
    stream.write(old)
    stream.flush()
    os.fsync(stream.fileno())
parent = os.open(private, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(parent)
finally:
    os.close(parent)
# Stage exclusively on the target filesystem, then atomically install once.
with tempfile.NamedTemporaryFile(dir=ACCEPTANCE_PATH.parent,
                                 prefix=".m13-acceptance-", delete=False) as stage:
    stage.write(payload)
    stage.flush()
    os.fsync(stage.fileno())
    staged = Path(stage.name)
# Recheck exact sources immediately before publication; no fingerprint mutation.
for mode in ("dontAsk", "bypassPermissions"):
    check_acceptance(envelope, None, mode)
os.replace(staged, ACCEPTANCE_PATH)
parent = os.open(ACCEPTANCE_PATH.parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(parent)
finally:
    os.close(parent)
for mode in ("dontAsk", "bypassPermissions"):
    _verify_runtime(mode)
print("Installed unchanged fresh pair; both local runtime checks passed")
PY_INSTALL
```

A failed validation/write/runtime check stops this operation. Preserve the backup,
staging file and reports for inspection; do not automatically roll back, restamp,
repair or rerun paid probes. Activation alone establishes no desktop/OAuth proof.
The [existing activation contract](../QUICKSTART.md#m12-live-evidence-and-desktop-checks)
continues to apply. No hash substitution,
changed observations, evidence override, automatic retries or fallback is allowed.
Keep raw failed/partial runs in the private directory. Another runtime/OS needs
new evidence; a Linux report cannot activate an unrelated laptop CLI binary.

## Current cloud guard receipt

Independent implementation review is resolved through `acf1d72`. Actual API-key
campaigns passed **33 cases in each permission mode** on the pinned SDK/CLI,
without changing guarded sources, prompts or limits. Both strict source validators
and production `_verify_runtime` checks passed. The installed envelope is the
unchanged fresh aggregate, SHA256
`b1c4b84ce675f8d44463964ac588ad392c8471fa3283154ce718a4dabab728f2`.
The private original report hashes are:

- `dontAsk`: `07a3468643240a73f7e64f39c11f33ba1d208f454d839a71ec0111a1df810aba`.
- `bypassPermissions`: `8af1e757874319cecdea66a5865b8ce2a0bf5307574b0def16ca49252a05dd05`.

An earlier bypass attempt stopped after 18 passing cases without finalizing.
Its exact incomplete checkpoint is retained privately; it is not accepted and
was not combined with another run. Offline inspection found no Python parent/group
kill operation or cgroup OOM event. A Claude child had SIGKILL exit status; the
sender remains unknown. One deliberate fresh full campaign used an external
supervisor and separate POSIX session, retained the same sources/runtime/limits,
and exited0 with a complete accepted report. This does not explain or reclassify
the interrupted attempt. A no-model 180-second control exited normally.

The original fixed envelope was backed up byte-for-byte before atomic replacement;
historical M12 evidence is unchanged. Raw private reports, logs and interruption
artifacts are not published. This receipt establishes cloud API-key guard coverage,
not owner desktop/OAuth acceptance or a dev merge.

## Desktop lifecycle checklist

Use a disposable Git project so failure exercises cannot affect working data.
Create one with `git init -b main`, configure its local author, add a small README,
and commit it. Set an absolute `M13_PROJECT` to that directory. Start the bridge
with the validated project and SQLite explicitly selected; keep its process ID:

```bash
PLAZA_WORKSPACE_ROOT_DIR="$M13_PROJECT" PLAZA_DOMAIN_STATE_BACKEND=sqlite PLAZA_TRANSCRIPTS_ENABLED=false python bridge/bridge.py >"$M13_PRIVATE_DIR/bridge-first.log" 2>&1 &
M13_BRIDGE_PID=$!
"$GODOT_BIN" --path .
```

Use the Chief's explicit project review/bootstrap flow. Readiness must be ready
before Start. Choose one permission mode for the desktop flow and record it;
repeat on the other mode only if actual desktop coverage is required. Record the
safe UUIDs, decimal output IDs/highwater/revisions and observed states in a copy
of the template named `desktop-observed.json`. For each case set `passed:true`
only after observing its expected behavior and add a short `observed` summary
(up to 2 KiB, with no task/answer transcript). Keep failed cases false.

1. Explicitly Start, then Run a harmless task with a recognizable synthetic nonce.
   Record application ID A, execution E1 and saved output ID. Stop: history and A
   remain, the execution becomes inactive and ownership is released. Terminate
   the bridge normally (`kill -INT "$M13_BRIDGE_PID"; wait "$M13_BRIDGE_PID"`).
   Restart it with the same command into a new `bridge-restart.log`. Reopen a
   fresh game: exact saved IDs/text and highwater return, without SDK/model/tool
   work. Status/replay/NPC approach must not Start or Run.
2. Explicit Start reuses A and creates E2 distinct from E1. The first explicit Run
   receives the deterministic latest-four-pair recap, chronological, task excerpts
   <=1 KiB, answer excerpts <=2 KiB, rendered total <=16 KiB. The current task is
   excluded; prior instructions remain quoted data. A second Run in E2 receives
   no second recap. Inspect locally without committing private messages.
3. End session explicitly after orderly cleanup. Restart: A remains selectable,
   ended with actor attribution; its selected history is read-only. The next
   explicit Start creates application B and a new execution. Failed End must
   retain the open identity, history and draft. Both dialogue and domain pane
   must expose separate Stop and End. Test a scrolled result anchor through a
   persistence notice change and pane/dialogue handoff without focus theft.
4. Disconnect/reconnect one client and start a fresh game while history exists.
   Exact IDs remain; uncertain requests require explicit reconciliation, never
   automatic resubmission. Stale Run/Stop/End tokens from E1 cannot control E2.
   A second bridge on the same configured project must fail closed for writes.
5. After normal Stop/bridge shutdown, restart once with
   `PLAZA_DOMAIN_STATE_BACKEND=memory`: show process-only history and a fresh
   continuity ID, without importing/deleting SQLite history. Stop/shutdown again,
   restart with explicit SQLite and observe the original saved project history.
6. Finish with normal Stop and bridge SIGINT; wait for exit 0 and released
   ownership. Closing/crashing the game or bridge does not End the application.

## Deterministic crash and storage exercises

Do not race a manual kill against an unknown boundary in a real project. These
commands run the production server/storage in disposable repositories with
explicit barriers; the crash harness kills the child at the named boundary and
reopens actual committed images. They never call providers:

```bash
python -m pytest bridge/tests/test_state_crash.py -q
python -m pytest bridge/tests/test_state_coordinator.py bridge/tests/test_state_image.py bridge/tests/test_session_recovery.py -q
PLAZA_REQUIRE_GODOT=1 python -m pytest bridge/tests/test_godot_history_reopen.py bridge/tests/test_domain_lifecycle_v2.py -q
```

The crash matrix includes initialization intent/image-before-ready,
notes-before-accept, accepted-before-dispatch, dispatched-before-SDK,
notes-before-terminal and terminal-commit-before-delivery. Expected states:
accepted work becomes `not_executed`; dispatched work becomes `interrupted` with
unknown tool effects; a committed terminal replays its original ID. No automatic
SDK retry or implicit End occurs. Interrupted initialization blocks empty
recreation. Keep these automated observations separate from actual desktop and
provider attestations; copy the relevant safe case result into the owner receipt
only when its stated acceptance scope is observed.

For a visible failed-storage exercise, stop work/bridge normally in the disposable
project and preserve its state directory with a private filesystem backup. Find
its authoritative directory with
`git -C "$M13_PROJECT" rev-parse --path-format=absolute --git-common-dir`, then
`plaza/application-state/`. Move only `state.sqlite3` to a private sibling backup
while the bridge is stopped, leaving the ready manifest and stable writer lock.
Restart: show bounded `state_store_invalid`, saved admission closed, no empty
recreation or memory fallback. Stop the bridge; restore those exact original
bytes to the same private regular-file path (0600), then restart and verify the
same identity/history. Never delete the manifest/lock or run a generic reset.
This is missing-image recovery, not a live write failure. The deterministic
storage tests separately inject replace/fsync errors and prove unsaved results,
closed admission, retained locks and explicit reconciliation before reuse.
For a real disk/fsync fault, preserve all images/temp remnants privately, Stop,
inspect/reconcile with the operator guide; never silently discard unsaved text.

Validate the completed owner receipt at the exact final source/runtime:

```bash
python scripts/m13_state_probe.py validate --kind desktop --engine "$GODOT_BIN" --permission-mode dontAsk --authentication oauth --report "$M13_PRIVATE_DIR/desktop-observed.json"
```

Exit 0 means the bound checklist contains complete owner attestations. It does
not independently prove their truth or replace reviewed guard/provider evidence.
If OAuth, an actual UI interaction, a crash boundary or recovery remains
unobserved, leave it pending and state that boundary in the delivery report.

*Last updated: October 2026*
