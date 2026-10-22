"""Blocking, bounded project inspection and owned execution worktree bootstrap.

Async callers must run these filesystem/Git operations in a worker thread.
No command resets, cleans, fetches, or imports uncommitted source files.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from uuid import UUID, uuid4

from bridge import project_files as files
from bridge.agent_bindings import DOMAIN_IDS


class WorkspaceError(ValueError):
    """Safe code/message for clients; raw Git and filesystem errors stay private."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProjectInspection:
    root: Path
    root_identity: tuple[int, int]
    common_git_dir: Path | None
    project_id: str | None
    head_commit: str | None
    source_branch: str | None


@dataclass(frozen=True)
class ExecutionWorkspace:
    project_id: str
    workspace_id: str
    project_root: Path
    common_git_dir: Path
    worktree_path: Path
    git_dir: Path
    branch: str
    initial_commit: str
    source_identity: tuple[int, int]
    domain_id: str = "core"


def _invalid(message: str = "Project workspace identity or registration is invalid"):
    return WorkspaceError("workspace_invalid", message)


def _git(
    root: Path,
    *args: str,
    timeout: int = 5,
    config_overrides: tuple[str, ...] = (),
    max_output_bytes: int | None = None,
) -> str:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="", LC_ALL="C")
    configuration = [
        "core.hooksPath=" + os.devnull,
        "core.fsmonitor=false",
        *config_overrides,
    ]
    command = [
        "git",
        "--no-lazy-fetch",
        "--no-optional-locks",
        *[arg for value in configuration for arg in ("-c", value)],
        "-C",
        os.fspath(root),
        *args,
    ]
    if max_output_bytes is not None:
        return _bounded_git_output(command, environment, timeout, max_output_bytes)
    result = subprocess.run(
        command,
        capture_output=True,
        env=environment,
        timeout=timeout,
        check=True,
    )
    return os.fsdecode(result.stdout).removesuffix("\n")


def git_without_filters(
    root: Path, *args: str, timeout: int = 5, max_output_bytes: int | None = None
) -> str:
    """Run Git without hooks/fsmonitor or external clean/smudge/process filters.

    Resolve effective filter names in this actual checkout, including conditional
    config. Override every driver only for this command, retaining built-in Git
    conversions. Filtered files (e.g. LFS pointers) keep their committed content.
    Use this blocking helper for later changed-file discovery as well as checkout:
    ordinary ``git status`` can execute clean/process filters and fsmonitor hooks.
    The caller must provide the validated checkout top-level as ``root``.
    Driver names containing '=' fail closed: Git's ``-c key=value`` transport
    cannot represent those complete keys without splitting the subsection.
    """
    try:
        keys = _git(
            root,
            "config",
            "--null",
            "--name-only",
            "--get-regexp",
            r"^filter\..*\.(clean|smudge|process|required)$",
        )
    except subprocess.CalledProcessError as error:
        if error.returncode != 1:
            raise
        keys = ""
    names = sorted({key.rsplit(".", 1)[0] for key in keys.split("\0") if key})
    if any("=" in name for name in names):
        raise _invalid("Git filter driver name cannot be safely overridden")
    overrides = [f"core.worktree={root}"]
    for name in names:
        overrides.extend(
            (
                f"{name}.clean=",
                f"{name}.smudge=",
                f"{name}.process=",
                f"{name}.required=false",
            )
        )
    return _git(
        root,
        *args,
        timeout=timeout,
        config_overrides=tuple(overrides),
        max_output_bytes=max_output_bytes,
    )


def _identity(path: Path) -> tuple[int, int]:
    info = path.stat()
    return info.st_dev, info.st_ino


def _key(common: Path) -> str:
    return hashlib.sha256(os.fsencode(common)).hexdigest()[:16]


def inspect_project(root: Path) -> ProjectInspection:
    """Inspect locally without lazy fetching; only an absent branch is unborn.

    Git must support --no-lazy-fetch; unknown options fail closed. An existing
    branch whose commit is unavailable/corrupt is invalid, never an init target.
    """
    try:
        root = Path(root).resolve(strict=True)
        with files.directory(root):
            identity = _identity(root)
        try:
            bare = _git(root, "rev-parse", "--is-bare-repository")
        except subprocess.CalledProcessError as error:
            if error.returncode != 128 or os.path.lexists(root / ".git"):
                raise _invalid()
            return ProjectInspection(root, identity, None, None, None, None)
        if bare != "false":
            raise _invalid("A non-bare project checkout is required")
        top = Path(_git(root, "rev-parse", "--show-toplevel")).resolve(strict=True)
        if top != root:
            raise _invalid("Configured project must be a Git top-level directory")
        common = Path(
            _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        ).resolve(strict=True)
        with files.directory(common):
            pass
        try:
            branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        except subprocess.CalledProcessError:
            branch = None
        try:
            commit = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
        except subprocess.CalledProcessError:
            if branch is None:
                raise _invalid()
            # Resolve HEAD only one hop: a dangling branch symref still exists,
            # even when recursive symbolic-ref would name an absent target.
            branch_ref = _git(root, "symbolic-ref", "--quiet", "--no-recurse", "HEAD")
            if not branch_ref.startswith("refs/heads/"):
                raise _invalid()
            try:
                _git(root, "show-ref", "--exists", branch_ref)
            except subprocess.CalledProcessError as error:
                # --exists examines references, not object availability. Only
                # exit 2 establishes absence; malformed refs/errors fail closed.
                if error.returncode != 2:
                    raise _invalid()
            else:
                raise _invalid("Project HEAD refers to an unavailable commit")
            commit = None
        return ProjectInspection(root, identity, common, _key(common), commit, branch)
    except WorkspaceError:
        raise
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        raise _invalid("Project inspection failed") from None


def _decode(data: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate metadata key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("invalid metadata constant")

    value = json.loads(data, object_pairs_hook=unique, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object")
    return value


def _encode(value: dict) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True) + "\n"
    ).encode()


def _record_path(common: Path, domain_id="core") -> Path:
    if domain_id is None:
        return common / "plaza/workspace.json"
    if domain_id not in DOMAIN_IDS:
        raise _invalid("Unknown department")
    return common / "plaza/workspaces" / f"{domain_id}.json"


def _read_record(common: Path, domain_id="core") -> dict:
    value = _decode(
        files.read_regular(_record_path(common, domain_id), max_bytes=16384)
    )
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != (1 if domain_id is None else 2)
        or (domain_id is not None and value.get("domain_id") != domain_id)
        or value.get("state") != "ready"
        or value.get("common_git_dir") != str(common)
        or value.get("common_identity") != list(_identity(common))
        or value.get("project_id") != _key(common)
    ):
        raise _invalid("Recorded project ownership is invalid or incomplete")
    if not isinstance(value.get("workspace_id"), str):
        raise _invalid()
    UUID(value["workspace_id"])
    return value


def _from_record(
    value: dict, project_root: Path, source_identity: tuple[int, int]
) -> ExecutionWorkspace:
    for key in ("worktree_path", "git_dir", "branch", "initial_commit"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise _invalid()
    return ExecutionWorkspace(
        value["project_id"],
        value["workspace_id"],
        project_root,
        Path(value["common_git_dir"]),
        Path(value["worktree_path"]),
        Path(value["git_dir"]),
        value["branch"],
        value["initial_commit"],
        source_identity,
        value.get("domain_id", "core"),
    )


def _disjoint(execution: Path, *others: Path) -> None:
    execution = execution.resolve()
    for other in others:
        other = other.resolve()
        if execution.is_relative_to(other) or other.is_relative_to(execution):
            raise _invalid("Execution, source and runtime paths must be disjoint")


def _registrations(root: Path) -> list[dict[str, str]]:
    data = _git(root, "worktree", "list", "--porcelain", "-z")
    records = []
    for block in data.split("\0\0"):
        if not block:
            continue
        value = {}
        for entry in block.split("\0"):
            if entry:
                key, _, text = entry.partition(" ")
                value[key] = text
        records.append(value)
    return records


def validate_workspace(workspace: ExecutionWorkspace, *, runtime_root: Path) -> None:
    """Recheck persisted and actual Git state; dirty execution files are allowed."""
    try:
        common = workspace.common_git_dir
        if common != common.resolve(strict=True):
            raise _invalid()
        value = _read_record(common, workspace.domain_id)
        _check_migration(common)
        if (
            _from_record(value, workspace.project_root, workspace.source_identity)
            != workspace
        ):
            raise _invalid("Workspace differs from recorded ownership")
        _validate_tree(workspace, runtime_root=runtime_root)
    except WorkspaceError:
        raise
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        raise _invalid() from None


def _validate_tree(workspace: ExecutionWorkspace, *, runtime_root: Path) -> None:
    common, path = workspace.common_git_dir, workspace.worktree_path
    if path != path.resolve(
        strict=True
    ) or workspace.project_root != workspace.project_root.resolve(strict=True):
        raise _invalid()
    _disjoint(path, workspace.project_root, runtime_root)
    source = inspect_project(workspace.project_root)
    execution = inspect_project(path)
    if (
        source.root_identity != workspace.source_identity
        or source.common_git_dir != common
        or source.project_id != workspace.project_id
        or execution.common_git_dir != common
        or execution.project_id != workspace.project_id
        or execution.source_branch != workspace.branch
        or source.source_branch is None
        or source.source_branch == workspace.branch
        or execution.head_commit is None
        or workspace.branch
        not in (
            {f"plaza/workspace-{workspace.project_id}-{workspace.domain_id}"}
            | (
                {f"plaza/workspace-{workspace.project_id}"}
                if workspace.domain_id == "core"
                else set()
            )
        )
    ):
        raise _invalid("Project or execution branch identity changed")
    actual_git = Path(_git(path, "rev-parse", "--absolute-git-dir")).resolve(
        strict=True
    )
    if (
        actual_git != workspace.git_dir
        or actual_git == common
        or not actual_git.is_relative_to(common / "worktrees")
    ):
        raise _invalid("Execution must have its own registered Git directory")
    with files.directory(actual_git):
        pass
    files.read_regular(path / ".git", max_bytes=16384)
    backref = files.read_regular(actual_git / "gitdir", max_bytes=16384)
    if Path(os.fsdecode(backref).removesuffix("\n")) != path / ".git":
        raise _invalid("Execution Git directory points to another checkout")
    matches = [
        record
        for record in _registrations(workspace.project_root)
        if record.get("worktree") == str(path)
    ]
    if len(matches) != 1:
        raise _invalid("Execution is not registered")
    record = matches[0]
    if (
        any(key in record for key in ("locked", "prunable", "detached", "bare"))
        or record.get("branch") != f"refs/heads/{workspace.branch}"
        or record.get("HEAD") != execution.head_commit
    ):
        raise _invalid("Execution registration is stale or unavailable")
    _git(path, "cat-file", "-e", f"{workspace.initial_commit}^{{commit}}")


def _check_idle(workspace: ExecutionWorkspace) -> files.FileLock:
    try:
        lock = files.FileLock.acquire(workspace.git_dir / "plaza-execution.lock")
    except BlockingIOError:
        raise WorkspaceError(
            "workspace_busy", "Workspace is reserved by a domain"
        ) from None
    try:
        if os.path.lexists(workspace.git_dir / "plaza-unclean.json"):
            raise WorkspaceError(
                "cleanup_failed",
                "Workspace requires operator inspection after uncertain cleanup",
            )
        return lock
    except BaseException:
        lock.close()
        raise


def prepare_worktree(
    project: ProjectInspection, *, domain_id: str = "core", runtime_root: Path
) -> ExecutionWorkspace:
    """Create one owned slot or reuse its recorded identity without repairing it."""
    bootstrap_lock = None
    execution_lock = None
    try:
        if inspect_project(project.root) != project:
            raise _invalid("Configured project changed during preparation")
        if project.common_git_dir is None or project.head_commit is None:
            raise WorkspaceError(
                "workspace_not_ready", "Project needs Chief Architect initialization"
            )
        if project.source_branch is None:
            raise _invalid("Configured source must use a named branch")
        common = project.common_git_dir
        with files.directory(common / "plaza", create=True):
            pass
        try:
            bootstrap_lock = files.FileLock.acquire(common / "plaza/bootstrap.lock")
        except BlockingIOError:
            raise WorkspaceError(
                "workspace_busy", "Project workspace preparation is in progress"
            ) from None
        record_path = _record_path(common, domain_id)
        legacy = _record_path(common, None)
        if os.path.lexists(legacy):
            old = _decode(files.read_regular(legacy, max_bytes=16384))
            if old.get("state") != "migrated":
                if domain_id != "core" or os.path.lexists(record_path):
                    raise _invalid(
                        "Incomplete legacy Core migration requires inspection"
                    )
                old = _read_record(common, None)
                workspace = _from_record(old, project.root, project.root_identity)
                _validate_tree(workspace, runtime_root=runtime_root)
                execution_lock = _check_idle(workspace)
                with files.directory(record_path.parent, create=True):
                    pass
                old.update(schema_version=2, domain_id="core")
                files.atomic_replace(record_path, _encode(old))
                files.atomic_replace(
                    legacy,
                    _encode(
                        dict(
                            state="migrated",
                            schema_version=1,
                            workspace_id=workspace.workspace_id,
                        )
                    ),
                )
                validate_workspace(workspace, runtime_root=runtime_root)
                return workspace
            _check_migration(common)
        with files.directory(record_path.parent, create=True):
            pass
        if os.path.lexists(record_path):
            workspace = _from_record(
                _read_record(common, domain_id), project.root, project.root_identity
            )
            validate_workspace(workspace, runtime_root=runtime_root)
            execution_lock = _check_idle(workspace)
            return workspace
        name = (
            re.sub(r"[^a-zA-Z0-9_-]+", "-", project.root.name).strip("-")[:80]
            or "project"
        )
        path = (
            project.root.parent
            / ".plaza-worktrees"
            / f"{name}-{project.project_id}"
            / domain_id
            / "execution"
        )
        branch = f"plaza/workspace-{project.project_id}-{domain_id}"
        _disjoint(path, project.root, runtime_root)
        # Validate each parent before Git sees it; occupied slots are never adopted.
        with files.directory(path.parent, create=True):
            if os.path.lexists(path):
                raise _invalid("Execution location is already occupied")
        if any(
            record.get("worktree") == str(path)
            for record in _registrations(project.root)
        ):
            raise _invalid("Execution location has a stale registration")
        try:
            _git(
                project.root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"
            )
        except subprocess.CalledProcessError as error:
            if error.returncode != 1:
                raise
        else:
            raise _invalid("Execution branch already exists without ownership")
        value = dict(
            schema_version=2,
            domain_id=domain_id,
            state="creating",
            project_id=project.project_id,
            workspace_id=str(uuid4()),
            common_git_dir=str(common),
            common_identity=list(_identity(common)),
            worktree_path=str(path),
            branch=branch,
            initial_commit=project.head_commit,
        )
        files.atomic_replace(record_path, _encode(value))
        _git(
            project.root,
            "worktree",
            "add",
            "--no-checkout",
            "-b",
            branch,
            str(path),
            project.head_commit,
            timeout=30,
        )
        # Only this fresh owned slot is populated. These commands neither switch
        # nor reset an existing checkout, and never run configured external code.
        git_without_filters(path, "read-tree", project.head_commit, timeout=30)
        git_without_filters(path, "checkout-index", "--all", timeout=30)
        git_dir = Path(_git(path, "rev-parse", "--absolute-git-dir")).resolve(
            strict=True
        )
        value["git_dir"] = str(git_dir)
        workspace = _from_record(value, project.root, project.root_identity)
        _validate_tree(workspace, runtime_root=runtime_root)
        execution_lock = _check_idle(workspace)
        value["state"] = "ready"
        files.atomic_replace(record_path, _encode(value))
        validate_workspace(workspace, runtime_root=runtime_root)
        return workspace
    except WorkspaceError:
        raise
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        raise _invalid(
            "Workspace preparation failed; existing files were preserved"
        ) from None
    finally:
        if execution_lock is not None:
            execution_lock.close()
        if bootstrap_lock is not None:
            bootstrap_lock.close()


def _check_migration(common):
    legacy = _record_path(common, None)
    if not os.path.lexists(legacy):
        return
    value = _decode(files.read_regular(legacy, max_bytes=16384))
    if value.get("state") != "migrated":
        raise _invalid("Legacy Core workspace requires explicit Start migration")
    core = _read_record(common, "core")
    if core["workspace_id"] != value.get("workspace_id"):
        raise _invalid("Conflicting Core migration records")


def load_legacy_workspace(
    project: ProjectInspection, *, runtime_root: Path
) -> ExecutionWorkspace | None:
    """Validate a pending Core adoption without writing or taking ownership.

    Reservation observation is separate; explicit Start must revalidate and hold
    the bootstrap/execution locks before it can migrate this record.
    """
    try:
        if inspect_project(project.root) != project:
            raise _invalid()
        common = project.common_git_dir
        if common is None or not os.path.lexists(_record_path(common, None)):
            return None
        value = _decode(files.read_regular(_record_path(common, None), max_bytes=16384))
        if value.get("state") == "migrated":
            return None
        if os.path.lexists(_record_path(common, "core")):
            raise _invalid("Incomplete legacy Core migration requires inspection")
        workspace = _from_record(
            _read_record(common, None), project.root, project.root_identity
        )
        if workspace.domain_id != "core":
            raise _invalid("Legacy ownership must belong to Core")
        _validate_tree(workspace, runtime_root=runtime_root)
        return workspace
    except WorkspaceError:
        raise
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        raise _invalid() from None


def load_workspace(
    project: ProjectInspection, *, domain_id: str = "core", runtime_root: Path
) -> ExecutionWorkspace | None:
    """Observe existing ownership without bootstrapping or taking idle exclusion."""
    try:
        if inspect_project(project.root) != project:
            raise _invalid()
        if project.common_git_dir is None:
            return None
        _check_migration(project.common_git_dir)
        if not os.path.lexists(_record_path(project.common_git_dir, domain_id)):
            return None
        workspace = _from_record(
            _read_record(project.common_git_dir, domain_id),
            project.root,
            project.root_identity,
        )
        validate_workspace(workspace, runtime_root=runtime_root)
        return workspace
    except WorkspaceError:
        raise
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        raise _invalid() from None


def _bounded_git_output(command, environment, timeout, limit):
    """Drain at most limit stdout bytes; terminate/reap on cap or deadline."""
    import selectors
    import time

    output = bytearray()
    deadline = time.monotonic() + timeout
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment
    ) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while len(output) < limit:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise subprocess.TimeoutExpired(command, timeout)
                    chunk = os.read(
                        process.stdout.fileno(), min(65536, limit - len(output))
                    )
                    if not chunk:
                        code = process.wait(
                            timeout=max(0.001, deadline - time.monotonic())
                        )
                        if code:
                            raise subprocess.CalledProcessError(code, command)
                        break
                    output.extend(chunk)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
    return os.fsdecode(bytes(output))
