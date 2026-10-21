"""One configured project: owned bootstrap, trusted setup, cached observations."""

import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from bridge.agents import load_agent
from bridge.conversation import ConversationEngine
from bridge.conversation_backend import ExecutionMetadata
from bridge.project_memory import MemorySnapshot, ProjectMemoryStore
from bridge.readiness import ReadinessService, owned_io
from bridge.repository_setup import (
    build_init_proposal,
    initialize_repository,
    parse_init_approval,
)
from bridge.workspace import (
    WorkspaceError,
    _decode,
    inspect_project,
    load_workspace,
    prepare_worktree,
    validate_workspace,
    git_without_filters,
)
from bridge.workspace_lease import observe_reservation

REFERRAL = "Talk to the Chief Architect to prepare this project, then come back and we can work on it."


async def review_repository(config, proposal, *, deadline=None):
    """Fresh configured tools-disabled adapter; no history or memory preflight."""
    engine = ConversationEngine(config=config)
    definition = load_agent("systems-architect")
    if definition is None:
        raise WorkspaceError(
            "repository_approval_invalid", "Chief Architect definition is unavailable"
        )
    payload = asdict(proposal)
    payload["root"] = str(proposal.root)
    instructions = (
        "\nReview the exact repository initialization proposal supplied as JSON data. "
        "Initialize main and seed only the reviewed allowlist, or an empty commit if empty. "
        "Credentials, ignored/generated files, symlinks and nested repositories are excluded. "
        "Return only an object with exactly proposal_id, digest, approved (boolean), reason "
        "(UTF-8 text at most 4096 bytes). Copy the exact proposal_id and digest. "
        "Do not invoke tools or request a second human confirmation."
    )
    remaining = (
        config.conversation_timeout_seconds
        if deadline is None
        else deadline - asyncio.get_running_loop().time()
    )
    if remaining <= 0:
        raise TimeoutError()
    raw = await engine._backend.complete(
        definition=definition + instructions,
        messages=[dict(role="user", content=json.dumps(payload, ensure_ascii=True))],
        model=engine.model,
        timeout=remaining,
        max_output_tokens=config.conversation_max_output_tokens,
        metadata=ExecutionMetadata(),
    )
    try:
        return _decode(raw.encode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        raise WorkspaceError(
            "repository_approval_invalid", "Chief Architect decision must be exact JSON"
        ) from None


class ProjectService:
    def __init__(self, config, *, runtime_root: Path, owner_run_id: str, reviewer=None):
        self._config, self._runtime_root, self._owner_run_id = (
            config,
            runtime_root,
            owner_run_id,
        )
        self._reviewer = reviewer
        self._workspace = self._memory = self._readiness = self._lease = None
        self._bootstrap_task = self._setup_task = None
        self._attached = self._closing = False
        self._initialized = False
        self._snapshot = dict(
            type="workspace_state",
            project_id=None,
            stage="unconfigured" if config.workspace_root_dir is None else "preparing",
            reason=None,
            architect_decision=None,
            workspace_id=None,
            project_path=(
                str(config.workspace_root_dir) if config.workspace_root_dir else None
            ),
            worktree_path=None,
            branch=None,
            changed_files=None,
            reservation=None,
            memory=dict(
                path=None, status="unavailable", revision=None, error_type=None
            ),
        )

    @property
    def owner_run_id(self):
        return self._owner_run_id

    async def start(self):
        if self._bootstrap_task is None and not self._closing:
            self._bootstrap_task = asyncio.create_task(
                self._bootstrap(), name="project-bootstrap"
            )

    def snapshot(self):
        return deepcopy(self._snapshot)

    def _failure(self, error):
        self._snapshot.update(
            stage="failed",
            reason=getattr(
                error,
                "code",
                "timeout" if isinstance(error, TimeoutError) else "workspace_invalid",
            ),
        )

    async def _bootstrap(self):
        if self._config.workspace_root_dir is None:
            return
        try:
            project = await owned_io(inspect_project, self._config.workspace_root_dir)
            self._snapshot["project_id"] = project.project_id
            if project.head_commit is None:
                self._snapshot.update(
                    stage="needs_architect", reason="repository_setup_required"
                )
                return
            await self._prepare(project)
        except Exception as error:
            self._failure(error)

    async def _prepare(self, project, setup=None):
        def prepare():
            workspace = load_workspace(project, runtime_root=self._runtime_root)
            if workspace is None:
                workspace = prepare_worktree(project, runtime_root=self._runtime_root)
            reservation = observe_reservation(workspace)
            if reservation and reservation["cleanup_failed"]:
                raise WorkspaceError(
                    "cleanup_failed", "Workspace requires operator inspection"
                )
            self._workspace = workspace
            self._snapshot.update(
                project_id=workspace.project_id,
                workspace_id=workspace.workspace_id,
                worktree_path=str(workspace.worktree_path),
                branch=workspace.branch,
                reservation=reservation,
            )
            self._memory = ProjectMemoryStore(workspace)
            self._snapshot["memory"]["path"] = str(
                workspace.common_git_dir / "plaza/session-memory"
            )
            self.publish_memory(self._memory.initialize())
            self._memory.attach_run(self.owner_run_id)
            self._attached = True
            if setup:
                result = self._memory.checkpoint_setup(*setup, workspace.initial_commit)
                self.publish_memory(result)
                if not result.saved:
                    raise WorkspaceError(
                        "memory_unavailable", "Setup checkpoint was not saved"
                    )
            self._readiness = ReadinessService(
                workspace, self._runtime_root, self._memory
            )

        await owned_io(prepare)
        self._snapshot.update(stage="ready", reason=None)
        snapshot = await self.refresh_snapshot()
        if snapshot["stage"] != "ready":
            raise WorkspaceError(
                snapshot["reason"], "Final workspace observation failed"
            )

    async def interact_setup(self, agent_id, request_id, *, deadline=None):
        stage = self._snapshot["stage"]
        if stage in ("ready", "unconfigured"):
            return None
        if agent_id != "systems-architect":
            return REFERRAL
        if stage in ("preparing", "reviewing", "initializing"):
            return "Project preparation or Chief Architect review is in progress."
        if self._closing or self._initialized:
            return "Project setup needs operator inspection; initialized files were preserved."
        if deadline is None:
            deadline = (
                asyncio.get_running_loop().time()
                + self._config.conversation_timeout_seconds
            )
        self._snapshot.update(stage="reviewing", reason=None, architect_decision=None)
        self._setup_task = asyncio.create_task(
            self._setup(deadline), name="chief-project-setup"
        )
        # A caller's response budget never cancels approved initialization. The
        # service retains that task through completion and shutdown drainage.
        done, _ = await asyncio.wait(
            {self._setup_task},
            timeout=max(0, deadline - asyncio.get_running_loop().time()),
        )
        if done:
            return self._setup_task.result()
        decision = self._snapshot["architect_decision"]
        if decision is not None and decision["approved"]:
            state = self._snapshot["stage"]
            status = (
                "initialization in progress"
                if state == "initializing"
                else "project setup " + state
            )
            return (
                "Chief Architect approval: "
                + json.dumps(decision, ensure_ascii=True)
                + ". "
                + status
                + "."
            )
        return "Chief Architect review deadline expired; no initialization was approved. Review cleanup may still be in progress."

    async def _setup(self, deadline):
        try:
            async with asyncio.timeout_at(deadline):
                proposal = await owned_io(
                    build_init_proposal, self._config.workspace_root_dir
                )
                payload = (
                    await self._reviewer(proposal)
                    if self._reviewer is not None
                    else await review_repository(
                        self._config, proposal, deadline=deadline
                    )
                )
                approval = parse_init_approval(proposal, payload)
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError()
            self._snapshot["architect_decision"] = asdict(approval)
            if not approval.approved:
                raise WorkspaceError(
                    "repository_setup_denied", "Chief Architect declined setup"
                )
            self._snapshot["stage"] = "initializing"

            def initialize():
                project = initialize_repository(proposal, approval)
                self._initialized = True
                return project

            project = await owned_io(initialize)
            await self._prepare(project, (proposal, approval))
            return "Chief Architect approved setup. Project workspace and memory are ready."
        except Exception as error:
            self._failure(error)
            return (
                "Project setup failed: "
                + self._snapshot["reason"]
                + ". Existing files were preserved."
            )

    def require_workspace(self):
        if self._snapshot["stage"] != "ready" or self._workspace is None:
            code = (
                "workspace_unconfigured"
                if self._config.workspace_root_dir is None
                else "workspace_not_ready"
            )
            raise WorkspaceError(code, REFERRAL)
        return self._workspace

    def require_memory(self):
        self.require_workspace()
        if self._memory is None:
            raise WorkspaceError("memory_unavailable", "Project memory is unavailable")
        return self._memory

    def require_readiness(self):
        self.require_memory()
        return self._readiness

    def publish_reservation(self, lease):
        self._lease = lease
        self._snapshot["reservation"] = dict(
            domain_id=lease.domain_id,
            domain_session_id=lease.domain_session_id,
            cleanup_failed=False,
        )

    def publish_cleanup(self, lease, *, clean):
        if lease is not self._lease:
            return
        if clean and not lease.held:
            self._lease = None
            self._snapshot["reservation"] = None
        elif not clean:
            self._snapshot["reservation"]["cleanup_failed"] = True

    def publish_memory(self, result):
        value = self._snapshot["memory"]
        if isinstance(result, MemorySnapshot) or result.saved:
            if value["revision"] is not None and result.revision < value["revision"]:
                return
            value.update(status="saved", revision=result.revision, error_type=None)
        else:
            value.update(status="unsaved", error_type=result.error_type)

    async def refresh_snapshot(self):
        workspace = self._workspace
        if workspace is None:
            return self.snapshot()

        def observe():
            validate_workspace(workspace, runtime_root=self._runtime_root)
            reservation = observe_reservation(workspace)
            cap = 256 * 1024
            output = git_without_filters(
                workspace.worktree_path,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=normal",
                timeout=5,
                max_output_bytes=cap,
            )
            truncated = len(output.encode("utf-8", "surrogateescape")) >= cap
            records = output.split("\0")[:-1]
            count = untracked = index = 0
            while index < len(records):
                entry = records[index]
                count += 1
                untracked += entry.startswith("??")
                index += 2 if "R" in entry[:2] or "C" in entry[:2] else 1
            return reservation, dict(
                total=count,
                tracked=count - untracked,
                untracked=untracked,
                truncated=truncated,
            )

        try:
            reservation, changed = await owned_io(observe)
            if self._lease is None:
                self._snapshot["reservation"] = reservation
            self._snapshot["changed_files"] = changed
        except Exception as error:
            self._failure(error)
        return self.snapshot()

    async def close(self):
        self._closing = True
        for task in (self._bootstrap_task, self._setup_task):
            if task is not None:
                await _join(task)
        if self._attached:
            await owned_io(self._memory.detach_run, self.owner_run_id)
            self._attached = False


async def _join(task):
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    return task.result()
