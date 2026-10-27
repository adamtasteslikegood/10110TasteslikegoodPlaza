# M13 session persistence and offline maintenance

The [owner-approved M13 design](superpowers/specs/2026-10-26-m13-sqlite-session-persistence-design.md)
and the [platform successor contract](designs/platform-decisions.md#approved-m13-successor-contract--october-26-2026)
authorize this local application-session behavior. Implementation is on the M13
branch; local QA/performance are recorded, while independent final review, fresh
guard/live evidence and owner acceptance remain pending.
Historical M12 reports keep their original source/runtime/mode bindings.
The [M13 live acceptance runbook](m13-live-acceptance.md) supplies source-bound
performance/desktop receipts and reviewed guard-campaign commands.

## Configure continuity at startup

`DOMAIN_STATE_BACKEND` defaults to `sqlite`; the only alternative is explicit
`memory`. Configuration precedence is built-ins, the selected JSON file, then
`PLAZA_` overrides. `BRIDGE_CONFIG_PATH` selects the file; programmatic explicit
config paths take precedence over that selector. Relative workspace/log paths,
including environment overrides, resolve against the selected file's directory.
An unprefixed `DOMAIN_STATE_BACKEND` environment variable is not an override.
For example, `PLAZA_DOMAIN_STATE_BACKEND=memory` selects process-only continuity
when starting the bridge. The shipped `bridge/config.json` selects `sqlite`.

Changing backend requires a bridge restart. Memory mode does not read, import,
modify or delete SQLite history; returning to SQLite exposes the saved project
history again. Each memory boot has a new continuity identity. Clients distinguish
backend and continuity identity before comparing revisions, so an older SQLite
view cannot inherit cached memory history or lifecycle. An unsent draft in a kept-open
game can remain across the switch; it is client process state, not backend draft
persistence or an import. SQLite's continuity ID is
its persisted store-instance UUID, initially null before the first image exists.
No storage error silently switches to memory.

The configured project must pass existing Chief/bootstrap readiness. Its validated
common Git directory supplies `<common-git-dir>/plaza/application-state/`, shared
by linked worktrees of that repository. Separate clones have separate identities.
The directory contains `state.sqlite3`, `manifest.json` and stable `writer.lock`.
Status on a genuinely new store creates no image; the first explicit Start
initializes it. Only absence of both image and manifest permits initialization.

## Stop, End and recovered history

**Stop work** drains the execution and releases ownership after confirmed cleanup;
it preserves the application `domain_session_id`, retained results and cursor.
**End session** separately records `ended_at` and `ended_by` (`user` or `bridge`)
after orderly cleanup and unfinished-request settlement. End retains history.
Failed End keeps the session and draft. The next explicit Start after End creates
a new application UUID. Every fresh explicit Start otherwise reuses the open
application UUID and creates a fresh `execution_id`; neither ID is an SDK resume
token. Closing the game, disconnect, bridge exit and crash never imply End.

Reconnect/status/replay restore only committed results, with their original
decimal-string output IDs and highwater. They never start SDK/model/tools or
resubmit a task. Saved ended sessions remain discoverable even when no open
session exists. Uncommitted live answers display an unsaved state and are not
claimed as restored history. The two work surfaces share this lifecycle.

Saved history remains readable when the current department worktree or its
registration is unavailable. Start/Run still require current readiness. The
client requests `resume` with optional `replay_format: "history_v1"`; each
`domain_history` reply contains exactly `type`, `protocol_version`, `request_id`,
`project_id`, `domain_id`, `domain_session_id`, `state_store`, and `terminal`.
The envelope binds the validated project/store namespace and catalog session to
the same-connection pending resume. Its `terminal` is the original frozen packet,
including its original IDs; replay never adds current workspace facts to it.
An original project identity, when present, must match the envelope. Historical
workspace identity is metadata, independent of current readiness. Completion
uses that same pending resume/store binding and does not change lifecycle authority.
Direct/live results retain their project/workspace checks. Omitting `replay_format`
preserves the original plain replay response for existing v2 clients.

Terminal JSON remains capped at 2 MiB. The fixed envelope shape permits at most
4 KiB additional metadata and 2 MiB + 4 KiB total; the transport reserves another
4 KiB for framing. Ordinary packets keep their 2 MiB cap. Outbound JSON uses
compact UTF-8, matching stored packet accounting instead of expanding Unicode
into ASCII escapes. Display retention stays at 1 MiB / 200 entries; receipt
settles before a whole oversized display row is omitted. The client uses the
transport's actual byte count, with canonical fixed-envelope overhead subtraction,
to avoid Godot numeric reserialization changing boundary sizes. Noncanonical
whitespace or metadata escapes count conservatively toward the terminal limit.
SQLite schema v1 and
unknown/corrupt-image refusal are unchanged; this adds no migration or reset.

An accepted request with no committed dispatch is recovered as `not_executed`.
Committed dispatch without a saved terminal is `interrupted`, with unknown outcome:
external changes may have occurred. A committed terminal is replayed unchanged,
including an earlier unsaved-note status. Recovery never retries tools or invents
success. Note reconciliation reports current facts separately from that packet.

M13 refines historical M12 blanket startup recovery for **domain** pending notes:
both backends protect them until exact retained-request/turn identity, valid
project/workspace readiness and held ownership permit reconciliation. Extras and
direct-store legacy defaults remain. A legacy domain note with no retained SQL
request can remain pending, particularly after a memory restart. Preserve it,
inspect the actual worktree/notes/ownership, compare any retained task evidence
and establish the outcome before a specific operator repair. The CLI below
does not reconcile notes or clear ownership; restarting or deleting state is not
proof that work completed or that cleanup is safe.

Each execution's first actual Run receives a deterministic quoted recap: the
latest four normal completed task/result pairs, chronological, plus at most one
bounded historical recovery notice. Errors/cancellations can be normal pairs;
synthetic recovered results occur only in the notice. Task/answer excerpts are at
most 1 KiB/2 KiB; the whole recap, including labels and notice, is at most 16 KiB
both in UTF-8 and as escaped JSON string content. It is unverified prior context,
never instruction authority or a task queue. No model summarizer runs; after End,
a new session receives no old conversation recap. Shared project notes still apply.

## Content, limits and runtime

Task and output text are local **cleartext** and may contain sensitive material.
Metadata directories are mode 0700 and stored files mode 0600, with no symlinks or
hardlinks. This is cooperative local protection, not a secret vault or host
sandbox. Do not put exports into source control or share them indiscriminately.
Application state, three Markdown project notes and M10 diagnostic archives are
separate. Disabling diagnostic transcripts does not disable application persistence;
diagnostic archive pruning/import does not manage this store. Authentication and
the SDK-default/explicit API-key-only modes remain unchanged (D-037).

| Bound | Limit |
|---|---|
| Serialized SQLite image | 64 MiB, including SQLite pages/metadata |
| Project history | 128 sessions, 10 domains |
| Replay per session | 256 terminals and 4 MiB output-text UTF-8 |
| Each task / output | 64 KiB / 256 KiB UTF-8 |
| Each terminal JSON packet | 2 MiB UTF-8, including escaped metadata |
| Aggregate Godot display retention | 200 entries / 1 MiB serialized snapshot |
| Admission completion allowance | 2 MiB logical allowance per unfinished request |
| Offline JSON export/backup | 512 MiB UTF-8, separately from the image quota |

The client admits valid terminal frames up to 2 MiB before applying its smaller
display budget. A received saved result settles its request and advances its
receipt cursor even when whole-row eviction omits its text; the omission notice
remains visible. Unsaved answers never acquire a durable output ID. Raw frames
above 2 MiB are rejected before JSON parsing. Escaped wire bytes and decoded
display bytes differ, particularly for control characters; each bound applies
to its own representation. Protected fault notices retain only bounded fields.

There is one unfinished accepted Run per domain and one global execution slot.
Completed duplicate recognition lasts only while its terminal remains retained;
unfinished requests do not expire. The logical allowance cannot prevent physical
ENOSPC or fsync failures. No history is automatically deleted to admit work.
Reads and Stop remain available at quota where the underlying store is healthy.
Deletion compacts the in-memory image before the 64 MiB check and atomic save.
Atomic replacement can require old plus new images (up to 128 MiB), plus validated
temporary remnants from failed writes. The image cap is not a total disk quota;
never prune unrecognized files to make room.

Python 3.11+ must provide stdlib SQLite `serialize`/`deserialize`. Safe storage
requires POSIX `O_NOFOLLOW`, `O_DIRECTORY`, directory fsync and `fcntl.flock`.
Detected missing SQLite serialization or POSIX/open capabilities produce
`state_store_unsupported`. An earlier safe-file directory/open primitive failure
can instead produce `state_store_invalid`; other locking/filesystem failures also
fail closed with storage errors. There is no
pathname SQLite, WAL/journal-sidecar or JSONL fallback. Native Windows durability
is not established. Existing Git/worktree prerequisites still apply. Linux
Python 3.12 and pinned 3.11 focused tests are recorded in the Task 9 receipt;
this does not establish support on untested hosts/filesystems.

## Offline export and selected deletion

Stop work normally, then stop the bridge and wait for confirmed cleanup before
maintenance. The CLI acquires the same project writer lock for its whole
operation, including backup and commit; a running bridge that owns the store
causes `state_store_busy`. A free state lock alone does not prove SDK cleanup.
Use the configured repository's Git top-level checkout as `--workspace`; clients
and models cannot invoke maintenance through the wire protocol.

```bash
python scripts/domain_state.py --workspace /absolute/project export \
  --session APPLICATION_UUID --output /absolute/private/session-export.json
python scripts/domain_state.py --workspace /absolute/project delete-ended \
  --session ENDED_APPLICATION_UUID --backup /absolute/private/ended-backup.json
```

The output parent must already exist. Relative output paths use the operator's
current directory; `..` components, symlink components, existing output paths,
directories and hardlinks are refused. Each output is created exclusively as a
private regular file; it cannot overwrite an existing file. The CLI preflights
the complete encoded byte count, streams deterministic UTF-8 JSON
(`ensure_ascii=False`, sorted keys, compact separators), then fsyncs the file and
anchored parent before reporting success. It checks file/parent identity around
durability. Incomplete owned outputs are removed when safely possible; if cleanup
itself fails, preserve/inspect the remaining partial file and choose a new path.

The version-1 JSON envelope includes `format_version`, SQLite `schema_version`,
project/store-instance identity and source `state_revision`. `records` holds the
selected session, its executions, retained requests and retained terminal records;
expired history is not reconstructed. `image_sha256` hashes the exact source
SQLite image; `records_sha256` hashes the canonical UTF-8 `records` object using
the same encoding above. These are integrity/correlation metadata, not encryption
or a claim that the exported JSON is a complete database image. No import/restore
command is provided.

Export permits any retained session, including open/stopped sessions and
unreconciled old execution rows, while the bridge is offline and the lock is held.
This is the approved observational interpretation of the design's active-session
restriction: destructive deletion requires End; persisted unstopped rows alone do
not prove a live owner. Export neither classifies crash work nor cleans up SDK
ownership. A live writer blocks both commands. `delete-ended` refuses open sessions even after Stop, and does
not End on the operator's behalf. It creates and durably confirms a full selected
session export before calling the repository's `delete_ended` transaction.
Backup/open/write/fsync failure leaves the image unchanged. Successful deletion
preserves project/store-instance identity, domain revisions and every retained
session's highwater, while incrementing the store revision. A later image-save
failure retains the already durable backup; it may require inspection before retry.

Successful operations print `session_exported` or `ended_session_deleted`, exit 0.
Errors print a bounded code to stderr, exit 1; argument errors exit 2. CLI-only
codes include `state_store_missing` (no initialized store), `session_unavailable`
(unknown/malformed session), `session_not_ended` and `state_output_invalid`
(existing or lexically unsafe output). Unsafe filesystem paths and output I/O
failures can also produce `state_store_failed`.

| Storage condition | Operator response |
|---|---|
| `state_store_busy` | Stop the owning bridge normally; establish actual cleanup before retrying. Never remove `writer.lock`. |
| `state_store_invalid` | Preserve image, manifest and temporary evidence. Inspect corruption, unsafe links/modes, project identity and initialization state; no empty recreation. |
| Missing image after initialization / orphan image / initializing manifest | Preserve all artifacts; these fail visibly as invalid rather than creating a new identity. |
| `state_store_unsupported` | Use a supported runtime/OS and compatible schema; do not downgrade or rewrite an unknown image. |
| `state_store_quota` | Export, explicitly End eligible sessions through the owner, then delete selected ended sessions offline after backup. Retain enough transient disk space. |
| `state_store_failed` | Check permissions/free space and preserve evidence; verify image/backup before a deliberate retry. |
| `state_store_uncertain` | A rename may have occurred without confirmed durability. Keep the backup and all artifacts; inspect/reopen the actual committed image and ownership before any new action. Never claim deletion/save from the failed acknowledgement. |

There is no destructive generic reset repair. Renaming a root, copying a foreign
image, removing a manifest/lock, changing permissions indiscriminately or clearing
pending notes does not establish project continuity or safe worktree ownership.

*Last updated: October 2026*
