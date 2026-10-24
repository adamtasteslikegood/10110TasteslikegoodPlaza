"""Task 6's declared service seam, backed by real workspace/memory components."""

import asyncio

from bridge.domain_sdk import SDKOutcome, CleanupOutcome
from bridge.observability import RequestContext
from bridge.project_memory import ProjectMemoryStore, MemoryError
from bridge.readiness import ReadinessService
from bridge.tests.test_workspace import bootstrap


class FakeProjectService:
    owner_run_id = "domain-test-run"
    initialized = False

    def __init__(self, tmp_path):
        _, runtime, self.workspace = bootstrap(tmp_path, domain_id="engineering")
        self.memory = ProjectMemoryStore(self.workspace)
        self.memory.initialize()
        self.memory.attach_run(self.owner_run_id)
        self.readiness = ReadinessService(self.workspace, runtime, self.memory)
        self.capacity = None
        self.reservation = None
        self.memory_result = None

    def capacity_snapshot(self, domain_id=None):
        return dict(
            limit=1,
            available=self.capacity is None,
            domain_id=self.capacity.domain_id if self.capacity else None,
            domain_session_id=(
                self.capacity.domain_session_id if self.capacity else None
            ),
        )

    def reserve_capacity(self, owner):
        from bridge.workspace import WorkspaceError

        if self.capacity is not None and self.capacity is not owner:
            raise WorkspaceError("capacity_limit", "Capacity reserved")
        self.capacity = owner

    def release_capacity(self, owner):
        if self.capacity is owner:
            self.capacity = None

    async def prepare_domain(self, domain_id):
        from bridge.workspace import prepare_worktree, inspect_project
        from bridge.readiness import owned_io

        self.workspace = await owned_io(
            prepare_worktree,
            inspect_project(self.workspace.project_root),
            domain_id=domain_id,
            runtime_root=self.readiness.lease_runtime_root,
        )
        self.readiness = ReadinessService(
            self.workspace, self.readiness.lease_runtime_root, self.memory
        )
        return self.workspace

    def workspace_snapshot(self, domain_id):
        return dict(
            self.snapshot(),
            workspace_id=(
                self.workspace.workspace_id
                if domain_id == self.workspace.domain_id
                else None
            ),
        )

    def require_workspace(self, domain_id="engineering"):
        return self.workspace

    def require_memory(self):
        return self.memory

    def require_readiness(self, domain_id="engineering"):
        return self.readiness

    def publish_reservation(self, lease):
        self.reservation = lease

    def publish_cleanup(self, lease, *, clean):
        if clean and self.reservation is lease:
            self.reservation = None

    def publish_memory(self, result):
        self.memory_result = result

    def snapshot(self):
        return dict(
            type="workspace_state",
            project_id=self.workspace.project_id,
            workspace_id=self.workspace.workspace_id,
            stage="ready",
        )

    async def refresh_snapshot(self, domain_id=None):
        return self.workspace_snapshot(domain_id) if domain_id else self.snapshot()

    def close(self):
        try:
            self.memory.detach_run(self.owner_run_id)
        except MemoryError:
            # An intentionally failed save leaves truthful pending-run evidence.
            # Dispose only this temporary fixture's OS handles, preserving files.
            for lock in self.memory._runs.values():
                lock.close()


class FakeOwner:
    def __init__(self, config, workspace, lease, readiness):
        self.config, self.workspace, self.lease = config, workspace, lease
        self.started = asyncio.Event()
        self.executing = asyncio.Event()
        self.stopped = asyncio.Event()
        self.connect_gate = None
        self.execute_gate = None
        self.stop_gate = None
        self.calls = []
        self.outcome = SDKOutcome("done", "success", "completed", "provider", None)
        self.clean = True

    @property
    def healthy(self):
        return self.started.is_set() and not self.stopped.is_set()

    async def start(self):
        self.started.set()
        if self.connect_gate:
            await self.connect_gate.wait()
        if self.stopped.is_set():
            raise RuntimeError("stopped")

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        self.executing.set()
        if self.execute_gate:
            await self.execute_gate.wait()
        if self.stopped.is_set():
            return SDKOutcome("partial", "cancelled", "stopped", "provider", None)
        return self.outcome

    async def stop(self):
        self.stopped.set()
        if self.connect_gate:
            self.connect_gate.set()
        if self.execute_gate:
            self.execute_gate.set()
        if self.stop_gate:
            await self.stop_gate.wait()
        return CleanupOutcome(self.clean, None if self.clean else "failure")


def context(request="run", connection="origin", agent="backend-architect"):
    return RequestContext(connection, request, agent, "domain", "model", "engineering")


def query(request="run", generation="generation", **changes):
    values = dict(
        type="domain_query",
        domain_id="engineering",
        domain_session_id=generation,
        request_id=request,
        agent_id="backend-architect",
        task="Build something",
    )
    values.update(changes)
    return values


async def collect_until(session, packets, count=1):
    async with asyncio.timeout(3):
        while len([p for p in packets if p["type"] == "domain_result"]) < count:
            await asyncio.sleep(0.001)
