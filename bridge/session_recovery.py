"""Conservative crash facts; classification never retries SDK or tool work."""

from copy import deepcopy

from bridge.application_state import StateCommand, StateView


def _classify(view, execution_ids, observed_at):
    commands = []
    terminals = {(t.session_id, t.request_id): t for t in view.terminals}
    sessions = {s.session_id: s for s in view.sessions}
    requests_by_execution = {}
    for request in view.requests:
        requests_by_execution.setdefault(request.execution_id, []).append(request)
    for execution in view.executions:
        if execution.execution_id not in execution_ids:
            continue
        requests = requests_by_execution.get(execution.execution_id, ())
        unfinished = [
            r for r in requests if r.disposition in {"accepted", "dispatched"}
        ]
        for request in unfinished:
            accepted = request.disposition == "accepted"
            reason = "not_executed" if accepted else "interrupted"
            output = (
                "The bridge stopped before this request was dispatched. The task was not executed."
                if accepted
                else "The bridge stopped after dispatch was recorded. The execution outcome is unknown; external changes may have occurred."
            )
            commands.append(
                StateCommand(
                    "recover",
                    dict(
                        session_id=request.session_id,
                        request_id=request.request_id,
                        timestamp=observed_at,
                        packet=dict(
                            type="domain_result",
                            protocol_version=2,
                            domain_id=sessions[request.session_id].domain_id,
                            domain_session_id=request.session_id,
                            execution_id=request.execution_id,
                            request_id=request.request_id,
                            agent_id=request.agent_id,
                            task=request.task,
                            status="error",
                            reason=reason,
                            error_type=reason,
                            output=output,
                            recovered=True,
                            memory=dict(
                                saved=False,
                                revision=None,
                                error_type="memory_reconciliation_pending",
                            ),
                        ),
                    ),
                )
            )
        if execution.stopped_at is not None or unfinished:
            continue
        # A saved terminal remains the authoritative packet, even if its delivery
        # or the following lifecycle acknowledgement never reached the caller.
        saved = next(
            (r for r in requests if (r.session_id, r.request_id) in terminals), None
        )
        if saved is not None:
            commands.append(
                StateCommand(
                    "recover",
                    dict(
                        session_id=saved.session_id,
                        request_id=saved.request_id,
                        packet=deepcopy(
                            terminals[saved.session_id, saved.request_id].packet
                        ),
                        timestamp=observed_at,
                    ),
                )
            )
        else:
            commands.append(
                StateCommand(
                    "stop",
                    dict(
                        execution_id=execution.execution_id,
                        outcome="interrupted",
                        timestamp=observed_at,
                    ),
                )
            )
    return tuple(commands)


def classify_recovery(
    view: StateView, boot_id: str, *, observed_at: str
) -> tuple[StateCommand, ...]:
    """Pure old-boot classification; boot IDs are epochs, never liveness probes.

    The owner supplies one actual UTC observation so this function has no clock
    or filesystem effects. Same-boot owners are deliberately excluded.
    """
    return _classify(
        view,
        {e.execution_id for e in view.executions if e.boot_id != boot_id},
        observed_at,
    )


def classify_owned_orphans(view, execution_ids, *, observed_at):
    """Internal explicit settlement after the manager proves its own cleanup."""
    return _classify(view, set(execution_ids), observed_at)


async def reconcile_memory(service, request, terminal, *, lease):
    """Reconcile only the exact retained turn under actual ready ownership.

    Result describes current note facts separately from the immutable SQL
    terminal. No new worktree, run marker cleanup, or provider work is performed.
    """
    # Keep classification usable by the explicit memory backend without loading
    # any disk adapter. Only the explicitly owned notes path imports filesystem IO.
    from bridge.project_memory import MemoryError
    from bridge.readiness import owned_io
    from bridge.workspace import WorkspaceError
    from bridge.workspace_lease import WorkspaceLease

    failure = dict(saved=False, revision=None, note_state=None)
    try:
        if not isinstance(lease, WorkspaceLease) or not lease.held:
            return dict(failure, error_type="memory_ownership_unavailable")
        if (
            request.disposition != "recovered"
            or not terminal.packet.get("recovered")
            or terminal.session_id != request.session_id
            or terminal.request_id != request.request_id
            or terminal.packet.get("execution_id") != request.execution_id
            or terminal.packet.get("reason") not in {"not_executed", "interrupted"}
        ):
            return dict(failure, error_type="memory_turn_mismatch")
        readiness = service.require_readiness(lease.domain_id)
        memory = service.require_memory()

        def reconcile():
            readiness._validate()
            if (
                readiness.workspace != lease.workspace
                or lease.domain_session_id != request.session_id
            ):
                raise WorkspaceError("workspace_invalid", "Recovery ownership changed")
            lease.validate()
            result = memory.reconcile_turn(
                request,
                domain_id=lease.domain_id,
                workspace_id=lease.workspace.workspace_id,
                outcome=(
                    "error"
                    if terminal.packet["reason"] == "not_executed"
                    else "interrupted"
                ),
                output=terminal.packet["output"],
            )
            lease.validate()
            return result

        return await owned_io(reconcile)
    except (MemoryError, WorkspaceError) as error:
        return dict(failure, error_type=error.code)
