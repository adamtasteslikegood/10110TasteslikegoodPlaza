"""Direct, fail-closed workspace checks with owned and drained filesystem workers."""

import asyncio
from pathlib import Path

import anyio
from claude_agent_sdk.types import HookCallback

from bridge.failure_diagnostics import readiness_category, tool_correlation

from bridge.project_memory import MemorySnapshot, ProjectMemoryStore, TurnIntent
from bridge.workspace import ExecutionWorkspace, WorkspaceError, validate_workspace
from bridge.workspace_lease import WorkspaceLease

CHECK_TIMEOUT = 5


class HookTasks:
    """Generation-owned handlers, independent of SDK/control-ID settlement.

    The pinned SDK cancels detached handlers without awaiting them. Retain each
    actual task until it finishes, including owned_io's cancellation drain.
    """

    LIMIT = 64

    def __init__(self, on_exhausted):
        self._tasks = set()
        self._closed = False
        self._on_exhausted = on_exhausted

    @property
    def active_count(self):
        return sum(not task.done() for task in self._tasks)

    def wrap(self, callback):
        async def tracked(*args):
            if self._closed:
                return denial()
            if self.active_count >= self.LIMIT:
                self.close_admission()
                self._on_exhausted()
                return denial()
            task = asyncio.current_task()
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return await callback(*args)

        return tracked

    def close_admission(self):
        self._closed = True

    async def drain(self):
        self.close_admission()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        # No kernel-IO timeout can safely abandon a worker or release its lease.
        # Shutdown response-write errors are expected; all tasks must settle.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


def denial(
    reason: str = "Readiness check failed; stop and review setup with the Chief Architect.",
) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


async def owned_io(function, *args, **kwargs):
    """Cancellation never abandons a synchronous writer or releases its ownership.

    A kernel operation may outlive its cooperative deadline. Drain it and preserve
    cancellation, so a late begin checkpoint never authorizes a model invocation.
    The lifecycle caller settles that nonexecuted intent after consistency returns.
    """
    worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
        if not worker.cancelled():
            worker.exception()
        raise


class ReadinessService:
    def __init__(
        self,
        workspace: ExecutionWorkspace,
        lease_runtime_root: Path,
        memory: ProjectMemoryStore,
    ):
        self.workspace = workspace
        self.lease_runtime_root = lease_runtime_root
        self.memory = memory

    def _validate(self):
        if any(
            getattr(self.memory.workspace, key) != getattr(self.workspace, key)
            for key in (
                "project_id",
                "common_git_dir",
                "project_root",
                "source_identity",
            )
        ):
            raise WorkspaceError("workspace_invalid", "Project memory binding changed")
        validate_workspace(self.workspace, runtime_root=self.lease_runtime_root)

    async def prepare_turn(self, turn: TurnIntent) -> MemorySnapshot:
        def prepare():
            self._validate()
            if turn.domain_id != self.workspace.domain_id or (
                turn.workspace_id is not None
                and turn.workspace_id != self.workspace.workspace_id
            ):
                raise WorkspaceError(
                    "workspace_invalid", "Turn workspace binding changed"
                )
            return self.memory.begin_turn(turn)

        return await owned_io(prepare)

    async def check_tool(
        self, lease: WorkspaceLease, *, cwd: str, tool_name: str, tool_use_id: str
    ) -> MemorySnapshot:
        def check():
            if (
                lease.workspace != self.workspace
                or not isinstance(tool_name, str)
                or not tool_name
                or not isinstance(tool_use_id, str)
                or not tool_use_id
                or len(tool_name.encode()) > 256
                or len(tool_use_id.encode()) > 256
            ):
                raise WorkspaceError(
                    "workspace_invalid",
                    "Tool workspace or correlation is invalid",
                    readiness_category="tool_correlation_invalid",
                )
            if not isinstance(cwd, str) or Path(cwd) != self.workspace.worktree_path:
                raise WorkspaceError(
                    "workspace_invalid",
                    "Tool cwd differs from owned worktree root",
                    readiness_category="cwd_mismatch",
                )
            self._validate()
            try:
                lease.validate()
            except WorkspaceError as error:
                raise WorkspaceError(
                    error.code,
                    "Workspace lease is invalid",
                    readiness_category="lease_invalid",
                ) from None
            # Every tool reads the current consistent revision. NPC checkpoints
            # legitimately advance it while this session holds the reservation.
            return self.memory.load()

        return await owned_io(check)

    def pre_tool_hook(self, lease: WorkspaceLease, *, on_denied=None) -> HookCallback:
        async def check(data, tool_use_id, context):
            category = None
            try:
                if (
                    not isinstance(data, dict)
                    or data.get("hook_event_name") != "PreToolUse"
                    or data.get("tool_use_id") != tool_use_id
                ):
                    raise WorkspaceError(
                        "workspace_invalid",
                        "Invalid hook correlation",
                        readiness_category="tool_correlation_invalid",
                    )
                with anyio.fail_after(CHECK_TIMEOUT):
                    await self.check_tool(
                        lease,
                        cwd=data.get("cwd"),
                        tool_name=data.get("tool_name"),
                        tool_use_id=tool_use_id,
                    )
                return {}
            except Exception as error:
                category = readiness_category(error)
            except asyncio.CancelledError:
                # Shutdown closes the owned CLI; never convert cancellation to {}.
                category = "readiness_cancelled"
            if on_denied is not None:
                try:
                    on_denied(
                        dict(
                            readiness_category=category,
                            **tool_correlation(data, tool_use_id),
                        )
                    )
                except Exception:
                    pass  # Diagnostics can never turn a failed check into approval.
            guidance = {
                "cwd_mismatch": "Keep tool root cwd at the owned worktree; use a scoped command or subshell for subdirectories. Stop and review setup before restarting.",
                "branch_changed": "Keep the active owned branch; do not checkout another branch. Stop and review ownership with the Chief Architect before restarting; no automatic reset or checkout repair.",
            }.get(
                category,
                "Stop and review setup with the Chief Architect before restarting.",
            )
            return denial(f"Readiness failed ({category}). {guidance}")

        return check
