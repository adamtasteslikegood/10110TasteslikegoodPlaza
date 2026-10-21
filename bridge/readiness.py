"""Direct, fail-closed workspace checks with owned and drained filesystem workers."""

import asyncio
from pathlib import Path

import anyio
from claude_agent_sdk.types import HookCallback

from bridge.project_memory import MemorySnapshot, ProjectMemoryStore, TurnIntent
from bridge.workspace import ExecutionWorkspace, WorkspaceError, validate_workspace
from bridge.workspace_lease import WorkspaceLease

CHECK_TIMEOUT = 5


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
        if self.memory.workspace != self.workspace:
            raise WorkspaceError("workspace_invalid", "Project memory binding changed")
        validate_workspace(self.workspace, runtime_root=self.lease_runtime_root)

    async def prepare_turn(self, turn: TurnIntent) -> MemorySnapshot:
        def prepare():
            self._validate()
            return self.memory.begin_turn(turn)

        return await owned_io(prepare)

    async def check_tool(
        self, lease: WorkspaceLease, *, cwd: str, tool_name: str, tool_use_id: str
    ) -> MemorySnapshot:
        def check():
            if (
                lease.workspace != self.workspace
                or not isinstance(cwd, str)
                or Path(cwd) != self.workspace.worktree_path
                or not isinstance(tool_name, str)
                or not tool_name
                or not isinstance(tool_use_id, str)
                or not tool_use_id
                or len(tool_name.encode()) > 256
                or len(tool_use_id.encode()) > 256
            ):
                raise WorkspaceError(
                    "workspace_invalid", "Tool workspace or correlation is invalid"
                )
            self._validate()
            lease.validate()
            # Every tool reads the current consistent revision. NPC checkpoints
            # legitimately advance it while this session holds the reservation.
            return self.memory.load()

        return await owned_io(check)

    def pre_tool_hook(self, lease: WorkspaceLease) -> HookCallback:
        async def check(data, tool_use_id, context):
            try:
                if (
                    not isinstance(data, dict)
                    or data.get("hook_event_name") != "PreToolUse"
                    or data.get("tool_use_id") != tool_use_id
                ):
                    return denial()
                with anyio.fail_after(CHECK_TIMEOUT):
                    await self.check_tool(
                        lease,
                        cwd=data.get("cwd"),
                        tool_name=data.get("tool_name"),
                        tool_use_id=tool_use_id,
                    )
                return {}
            except Exception:
                return denial()
            except asyncio.CancelledError:
                # Shutdown closes the owned CLI; never convert cancellation to {}.
                return denial()

        return check
