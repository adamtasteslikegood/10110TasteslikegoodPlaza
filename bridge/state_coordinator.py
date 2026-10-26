"""Owned application-state worker and committed, nonblocking event-loop views.

Cancellation detaches callers, never submitted repository work. After any store
failure admission stays closed until explicit reconciliation; commands are never
retried. Repository construction, reconciliation and final close share one thread.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Callable
from uuid import uuid4

from bridge.application_state import (
    RequestRecord,
    StateCommand,
    StateCommit,
    StateError,
    StateRepository,
    StateView,
)
from bridge.domain_protocol import DomainCommandError
from bridge.domain_store import ReplayWindow
from bridge.sqlite_state import SQLiteStateRepository, initial_image, replay_session


class LazySQLiteStateRepository:
    """Worker-only owner of both repository and StateImage, initialized by Start.

    reconcile() reopens the connection against the retained image/lock. An
    interrupted initialization cannot be silently adopted or recreated.
    """

    def __init__(self, common_git_dir: Path, project_id: str):
        self._common_git_dir = common_git_dir
        self._project_id = project_id
        self._image = None
        self._repository = None
        self._initialization_failed = False

    def _attach(self, *, initialize=False):
        from bridge.state_image import StateImage

        if self._repository is not None:
            return
        if self._initialization_failed:
            raise StateError("state_store_invalid")
        try:
            image = StateImage.open(
                self._common_git_dir,
                self._project_id,
                initialize=initialize,
                initial_image=lambda instance: initial_image(
                    self._project_id, instance
                ),
            )
        except StateError:
            if initialize:
                self._initialization_failed = True
            raise
        if image is not None:
            try:
                repository = SQLiteStateRepository(image)
            except BaseException:
                image.close()
                raise
            self._image, self._repository = image, repository

    def load(self) -> StateView | None:
        self._attach()
        return self._repository.load() if self._repository is not None else None

    def apply(self, command: StateCommand) -> StateCommit:
        if self._repository is None:
            if command.kind != "start":
                raise StateError("state_store_invalid")
            self._attach(initialize=True)
        return self._repository.apply(command)

    def reconcile(self) -> StateView | None:
        if self._image is not None:
            # Reading the live namespace alone cannot settle a failed rename
            # directory fsync. Confirm durable bytes and directory first, while
            # retaining the same anchored image and writer authority.
            self._image.confirm_durable()
        if self._repository is not None:
            self._repository.close()
            self._repository = None
            # Retain the exact image owner: reopening its connection must not
            # release/reacquire writer authority across an uncertain replace.
            self._repository = SQLiteStateRepository(self._image)
            return self._repository.load()
        if self._image is not None:
            self._repository = SQLiteStateRepository(self._image)
            return self._repository.load()
        return self.load()

    def close(self) -> None:
        try:
            if self._repository is not None:
                self._repository.close()
                self._repository = None
        finally:
            if self._image is not None:
                self._image.close()
                self._image = None


class _VolatileImage:
    """Only bytes, no filesystem imports, paths, locks or durable promises."""

    def __init__(self, project_id):
        self.project_id, self.instance_id = project_id, str(uuid4())
        self._data = initial_image(project_id, self.instance_id)

    def read(self):
        return self._data

    def replace(self, data):
        self._data = data


class VolatileStateRepository:
    """Explicit memory lifecycle, sharing the same pure SQLite validation rules.

    Distinct from MemoryStore's terminal-only contract. No durable image is ever
    read, imported or written; a new owner always starts a discontinuous history.
    """

    def __init__(self, project_id: str):
        self._project_id = project_id
        self._repository = None

    def load(self) -> StateView | None:
        return self._repository.load() if self._repository is not None else None

    def apply(self, command: StateCommand) -> StateCommit:
        if self._repository is None:
            if command.kind != "start":
                raise StateError("state_store_invalid")
            self._repository = SQLiteStateRepository(_VolatileImage(self._project_id))
        return self._repository.apply(command)

    def reconcile(self) -> StateView | None:
        return self.load()

    def close(self) -> None:
        if self._repository is not None:
            self._repository.close()
            self._repository = None


class StateCoordinator:
    def __init__(self, repository_factory: Callable[[], StateRepository]):
        self._factory = repository_factory
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="plaza-state"
        )
        self._repository = None
        self._worker_view = self._view = None
        self._worker_health = self._health = None
        self._worker_uncertain = False
        self._failed_base = None
        self._uncertain_transaction_id = None
        self._next_transaction_id = 0
        self._operations = set()
        self._opening = self._closing_task = None
        self._reconciling_task = None
        self._closing = self._closed = False

    @property
    def admission_open(self) -> bool:
        return (
            self._opening is not None
            and self._opening.done()
            and self._health is None
            and (self._reconciling_task is None or self._reconciling_task.done())
            and not self._closing
        )

    @property
    def health(self) -> str | None:
        """Safe storage error code; readable history does not imply healthy admission."""
        return self._health

    @property
    def uncertain_transaction_id(self) -> int | None:
        """Local acknowledgement identity, never an SDK retry/resume token."""
        return self._uncertain_transaction_id

    def _owned(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._operations.add(task)

        def completed(done):
            self._operations.discard(done)
            if not done.cancelled():
                done.exception()  # Detached callers still own/observe failures.

        task.add_done_callback(completed)
        return task

    async def _run(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, function, *args
        )

    def _worker_open(self):
        try:
            self._repository = self._factory()
            self._worker_view = self._repository.load()
            return self._worker_view
        except StateError as error:
            self._worker_health = error.code
            raise
        except Exception:
            self._worker_health = "state_store_failed"
            raise StateError("state_store_failed") from None

    async def _open_owned(self):
        try:
            self._view = deepcopy(await self._run(self._worker_open))
        except StateError as error:
            self._health = error.code
            raise

    async def open(self) -> None:
        if self._closing:
            raise StateError("state_store_failed")
        if self._opening is None:
            self._opening = self._owned(self._open_owned())
        await asyncio.shield(self._opening)

    def _worker_commit(self, command):
        if self._worker_health is not None:
            raise StateError(self._worker_health)
        try:
            commit = self._repository.apply(command)
            self._worker_view = deepcopy(commit.view)
            return commit
        except Exception as error:
            if not isinstance(error, StateError):
                error = StateError("state_store_failed")
            self._worker_health = error.code
            self._failed_base = self._worker_view
            self._worker_uncertain = error.uncertain
            if self._failed_base is None:
                # First Start may have durably initialized revision zero before
                # its lifecycle mutation failed. Capture that instance identity.
                try:
                    self._failed_base = self._repository.load()
                except Exception:
                    pass
            raise error from None

    async def _commit_owned(self, transaction_id, command):
        try:
            commit = await self._run(self._worker_commit, command)
            self._view = deepcopy(commit.view)
            return deepcopy(commit)
        except StateError as error:
            self._health = error.code
            if error.uncertain:
                self._uncertain_transaction_id = transaction_id
            raise

    async def commit(self, command: StateCommand) -> StateCommit:
        if not self.admission_open:
            raise StateError(self._health or "state_store_failed")
        self._next_transaction_id += 1
        task = self._owned(
            self._commit_owned(self._next_transaction_id, deepcopy(command))
        )
        return await asyncio.shield(task)

    def _worker_reconcile(self):
        # The worker has its own gate, independent of event-loop acknowledgements
        # and already queued work. Failed inspection must never leave it open.
        self._worker_health = self._worker_health or "state_store_uncertain"
        try:
            if self._repository is None:
                raise StateError(self._worker_health)
            reconcile = getattr(self._repository, "reconcile", None)
            if not callable(reconcile):
                raise StateError(self._worker_health)
            view = reconcile()
            prior = self._failed_base or self._worker_view
            if prior is not None:
                revisions = {prior.revision}
                if self._worker_uncertain:
                    revisions.add(prior.revision + 1)
                if (
                    view is None
                    or view.project_id != prior.project_id
                    or view.instance_id != prior.instance_id
                    or view.revision not in revisions
                ):
                    raise StateError("state_store_invalid")
            elif view is not None:
                raise StateError("state_store_invalid")
            self._worker_view = deepcopy(view)
        except StateError as error:
            self._worker_health = error.code
            raise
        except Exception:
            self._worker_health = "state_store_failed"
            raise StateError("state_store_failed") from None
        self._worker_health = None
        self._worker_uncertain = False
        self._failed_base = None
        return view

    async def _reconcile_owned(self, pending):
        try:
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._view = deepcopy(await self._run(self._worker_reconcile))
            self._health = None
            self._uncertain_transaction_id = None
        except StateError as error:
            self._health = error.code
            raise
        except Exception:
            self._health = "state_store_failed"
            raise StateError("state_store_failed") from None

    async def reconcile(self) -> None:
        """Drain submitted work, then inspect committed revision under retained lock.

        Health recovery authorizes storage only. The manager must still fence
        unfinished accepted/dispatched work before admitting another execution.
        """
        if self._closing:
            raise StateError("state_store_failed")
        if self._reconciling_task is not None and not self._reconciling_task.done():
            await asyncio.shield(self._reconciling_task)
            return
        # Fence admission synchronously even when called on a healthy store.
        self._health = self._health or "state_store_uncertain"
        pending = tuple(self._operations)
        # Ownership starts before waiting for preceding work, so concurrent
        # shutdown cannot close the repository ahead of this reconciliation.
        self._reconciling_task = self._owned(self._reconcile_owned(pending))
        await asyncio.shield(self._reconciling_task)

    def snapshot(self) -> StateView | None:
        return deepcopy(self._view)

    def replay(self, session_id: str, cursor: int) -> ReplayWindow:
        if type(cursor) is not int or cursor < 0:
            raise DomainCommandError()
        if self._view is None:
            raise DomainCommandError("session_unavailable")
        return replay_session(self._view, session_id, cursor)

    def find_request(self, session_id: str, request_id: str) -> RequestRecord | None:
        if self._view is None:
            return None
        return deepcopy(
            next(
                (
                    r
                    for r in self._view.requests
                    if r.session_id == session_id and r.request_id == request_id
                ),
                None,
            )
        )

    def _worker_close(self):
        if self._repository is not None:
            self._repository.close()
            self._repository = None

    async def _close_owned(self):
        try:
            pending = tuple(self._operations)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            await self._run(self._worker_close)
        finally:
            self._executor.shutdown(wait=True)
            self._closed = True

    async def close(self) -> None:
        """Repeated cancellation cannot abandon the worker or release its lock early."""
        self._closing = True
        if self._closing_task is None:
            self._closing_task = asyncio.create_task(self._close_owned())
        cancelled = False
        while not self._closing_task.done():
            try:
                await asyncio.shield(self._closing_task)
            except asyncio.CancelledError:
                cancelled = True
        self._closing_task.result()
        if cancelled:
            raise asyncio.CancelledError()
