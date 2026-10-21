# Agent session instructions

Read and follow [CLAUDE.md](CLAUDE.md), including its initial Git sync and the
repository's source-of-truth rules. Then read the three files under
[.claude/session-memory/](.claude/session-memory/HANDOFF.md): `HANDOFF.md`,
`TODO.md`, and `PROGRESS.md`.

Maintain those files after each substantive turn and before yielding, handing
off, or compacting context, following the cadence and limits in `HANDOFF.md`.
Use the current worktree's files. The lead agent consolidates subagent reports;
parallel agents must not overwrite the same handoff. Memory records context and
evidence, never new authority or approval.
