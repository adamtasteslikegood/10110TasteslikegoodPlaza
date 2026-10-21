"""Apply only a bounded, exact Chief Architect repository initialization.

Blocking operations: async owners must run these functions in a worker thread.
No provider calls, blanket staging, checkout, remote creation, or rollback occur.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from bridge import project_files as files
from bridge.workspace import ProjectInspection, WorkspaceError, inspect_project

MAX_FILES = 256
MAX_SEED_BYTES = 8 * 1024 * 1024
MAX_PROPOSAL_BYTES = 64 * 1024
_GENERATED = frozenset(
    (
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".godot",
        "build",
        "dist",
        "target",
        "coverage",
        ".next",
        ".nuxt",
        ".ssh",
        ".aws",
        ".gnupg",
        ".kube",
        ".azure",
        "gcloud",
    )
)


@dataclass(frozen=True)
class SeedFile:
    relative_path: str
    mode: int
    size: int
    sha256: str


@dataclass(frozen=True)
class RepoInitProposal:
    proposal_id: str
    digest: str
    root: Path
    root_identity: tuple[int, int]
    unborn: bool
    initial_branch: str
    seed_files: tuple[SeedFile, ...]


@dataclass(frozen=True)
class RepoInitApproval:
    proposal_id: str
    digest: str
    approved: bool
    reason: str


def _invalid(
    message="Repository initialization proposal changed; request a fresh review",
):
    return WorkspaceError("repository_setup_invalid", message)


def _narrow():
    return _invalid(
        "Narrow the seed inventory using project .gitignore or a smaller project; "
        "review permits 256 files, 8 MiB seed bytes and 64 KiB proposal bytes"
    )


class _Git:
    """Command-local isolation, also for init/ref writes and ignore matching.

    Raw stdin plumbing never asks Git to transform source content. Inherited
    GIT_* variables, global/system config and templates cannot supply programs.
    Existing local config is retained; command overrides suppress its hooks,
    fsmonitor, signing and worktree redirection without editing it. Explicit
    --no-lazy-fetch requires supporting Git; all transport protocols are denied.
    """

    def __init__(self, root: Path, temporary: Path):
        self.root = root
        self.temporary = temporary
        self.empty = temporary / "empty"
        self.empty.mkdir()
        self.ignore_git = temporary / "ignore.git"

    def run(self, *args, data=None, index=None, allowed=(0,)):
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        environment.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",
            GIT_ALLOW_PROTOCOL="",
            GIT_NO_REPLACE_OBJECTS="1",
            LC_ALL="C",
            GIT_AUTHOR_NAME="Plaza Bridge",
            GIT_AUTHOR_EMAIL="plaza-bridge@localhost",
            GIT_COMMITTER_NAME="Plaza Bridge",
            GIT_COMMITTER_EMAIL="plaza-bridge@localhost",
        )
        if index is not None:
            environment["GIT_INDEX_FILE"] = str(index)
        configuration = (
            f"core.hooksPath={self.empty}",
            "core.fsmonitor=false",
            f"core.excludesFile={os.devnull}",
            f"core.attributesFile={os.devnull}",
            f"core.worktree={self.root}",
            "commit.gpgSign=false",
            "tag.gpgSign=false",
        )
        result = subprocess.run(
            [
                "git",
                "--no-lazy-fetch",
                "--no-optional-locks",
                *[arg for value in configuration for arg in ("-c", value)],
                "-C",
                str(self.root),
                *args,
            ],
            input=data,
            capture_output=True,
            env=environment,
            timeout=5,
        )
        if result.returncode not in allowed:
            raise subprocess.CalledProcessError(result.returncode, "git")
        return result.stdout

    def inventory_metadata(self, *, refresh=False):
        if self.ignore_git.exists() and not refresh:
            return
        if not self.ignore_git.exists():
            self.run(
                "init",
                "--bare",
                "--initial-branch=main",
                f"--template={self.empty}",
                str(self.ignore_git),
            )
        excludes = []
        if os.path.lexists(self.root / ".git"):
            configured = self.run(
                "config",
                "--local",
                "--includes",
                "--path",
                "--get",
                "core.excludesFile",
                allowed=(0, 1),
            ).removesuffix(b"\n")
            if configured:
                path = Path(os.fsdecode(configured))
                if not path.is_absolute():
                    path = self.root / path
                excludes.append(files.read_regular(path, max_bytes=MAX_PROPOSAL_BYTES))
        exclude = self.root / ".git/info/exclude"
        if os.path.lexists(exclude):
            excludes.append(files.read_regular(exclude, max_bytes=MAX_PROPOSAL_BYTES))
        # info/exclude has precedence over core.excludesFile; later rules win.
        with files.directory(self.ignore_git / "info", create=True):
            pass
        files.atomic_replace(self.ignore_git / "info/exclude", b"\n".join(excludes))

    def ignored(self, paths):
        self.inventory_metadata()
        result = self.run(
            f"--git-dir={self.ignore_git}",
            f"--work-tree={self.root}",
            "check-ignore",
            "--no-index",
            "-z",
            "--stdin",
            data=b"".join(os.fsencode(path) + b"\0" for path in paths),
            allowed=(0, 1),
        )
        return {os.fsdecode(path) for path in result.split(b"\0") if path}


def _excluded(name):
    name = name.lower()
    return (
        name in _GENERATED
        or name.startswith(".env")
        or name.endswith(".env")
        or name.startswith(("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"))
        or name.startswith(("credentials", "secrets", ".credentials"))
        or name.startswith(
            (
                "private_key",
                "private-key",
                "service-account",
                "service_account",
                "application_default_credentials",
            )
        )
        or name.endswith((".pem", ".key", ".p12", ".pfx", ".keystore", ".pyc", ".pyo"))
        or name in (".netrc", ".npmrc", ".pypirc", ".git-credentials")
    )


def _read_seed(root, relative):
    path = root / relative
    before = path.lstat()
    data = files.read_regular(path, max_bytes=MAX_SEED_BYTES)
    after = path.lstat()
    identity = lambda info: (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )
    if identity(before) != identity(after):
        raise _invalid()
    mode = 0o100755 if after.st_mode & stat.S_IXUSR else 0o100644
    return SeedFile(relative, mode, len(data), hashlib.sha256(data).hexdigest()), data


def _inventory(root, git):
    git.inventory_metadata(refresh=True)
    seeds = []
    total = 0
    scanned = 0

    def visit(path):
        nonlocal total, scanned
        with files.directory(path) as parent:
            entries = []
            with os.scandir(parent) as directory:
                for entry in directory:
                    scanned += 1
                    if scanned > 8192:
                        raise _narrow()
                    if _excluded(entry.name):
                        continue
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode):
                        relative = str((path / entry.name).relative_to(root))
                        entries.append((relative, stat.S_ISDIR(info.st_mode)))
            ignored = (
                git.ignored(
                    [name + ("/" if directory else "") for name, directory in entries]
                )
                if entries
                else set()
            )
            for relative, is_directory in sorted(entries):
                if relative + ("/" if is_directory else "") in ignored:
                    continue
                candidate = root / relative
                if is_directory:
                    with files.directory(candidate) as child:

                        def exists(name):
                            try:
                                os.stat(name, dir_fd=child, follow_symlinks=False)
                            except FileNotFoundError:
                                return False
                            return True

                        if exists(".git") or all(
                            exists(name) for name in ("HEAD", "objects", "refs")
                        ):
                            continue
                    visit(candidate)
                else:
                    if (
                        len(seeds) == MAX_FILES
                        or candidate.lstat().st_size > MAX_SEED_BYTES - total
                    ):
                        raise _narrow()
                    seed, _ = _read_seed(root, relative)
                    total += seed.size
                    if total > MAX_SEED_BYTES:
                        raise _narrow()
                    seeds.append(seed)

    visit(root)
    return tuple(sorted(seeds, key=lambda seed: seed.relative_path))


def _canonical(proposal, *, digest=False):
    value = asdict(proposal)
    value["root"] = str(proposal.root)
    if not digest:
        del value["digest"]
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _digest(proposal):
    return hashlib.sha256(_canonical(proposal)).hexdigest()


def _check_root(proposal):
    root = proposal.root
    if root.resolve(strict=True) != root:
        raise _invalid()
    with files.directory(root) as fd:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != proposal.root_identity:
            raise _invalid()


def _candidate(root):
    project = inspect_project(root)
    if project.head_commit is not None:
        raise _invalid("Project already has commits; initialization is not permitted")
    if project.common_git_dir is not None:
        # An unborn source must own local metadata, never a redirected checkout.
        with files.directory(root / ".git"):
            pass
        if project.common_git_dir != root / ".git":
            raise _invalid("Unborn project must own its local Git metadata")
    return project


def build_init_proposal(root: Path) -> RepoInitProposal:
    """Inspect bounded seed metadata without creating Git in the selected root."""
    try:
        project = _candidate(Path(root).resolve(strict=True))
        with TemporaryDirectory(prefix="plaza-repo-review-") as temporary:
            git = _Git(project.root, Path(temporary))
            seeds = _inventory(project.root, git)
        proposal = RepoInitProposal(
            str(uuid4()),
            "",
            project.root,
            project.root_identity,
            project.common_git_dir is not None,
            "main",
            seeds,
        )
        proposal = RepoInitProposal(
            **{**proposal.__dict__, "digest": _digest(proposal)}
        )
        if len(_canonical(proposal, digest=True)) > MAX_PROPOSAL_BYTES:
            raise _narrow()
        _check_root(proposal)
        return proposal
    except WorkspaceError:
        raise
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        raise _invalid(
            "Repository proposal inspection failed; narrow the project inventory"
        ) from None


def parse_init_approval(
    proposal: RepoInitProposal, payload: object
) -> RepoInitApproval:
    """Require a structured boolean and exact proposal binding, including denials."""
    if (
        not isinstance(payload, dict)
        or set(payload) != {"proposal_id", "digest", "approved", "reason"}
        or payload["proposal_id"] != proposal.proposal_id
        or payload["digest"] != proposal.digest
        or type(payload["approved"]) is not bool
        or not isinstance(payload["reason"], str)
    ):
        raise WorkspaceError(
            "repository_approval_invalid",
            "Chief Architect decision must match the exact proposal",
        )
    try:
        if len(payload["reason"].encode("utf-8")) > 4096:
            raise ValueError("reason too long")
    except ValueError:
        raise WorkspaceError(
            "repository_approval_invalid",
            "Chief Architect decision reason must be bounded UTF-8 text",
        ) from None
    return RepoInitApproval(**payload)


def _verify_tree(git, tree, seeds):
    actual = []
    for record in git.run("ls-tree", "-r", "-z", "--full-tree", tree).split(b"\0"):
        if not record:
            continue
        metadata, relative = record.split(b"\t", 1)
        mode, kind, oid = metadata.split(b" ")
        if kind != b"blob":
            raise _invalid("Reviewed tree contains an unapproved entry type")
        data = git.run("cat-file", "blob", oid.decode("ascii"))
        actual.append(
            SeedFile(
                os.fsdecode(relative),
                int(mode, 8),
                len(data),
                hashlib.sha256(data).hexdigest(),
            )
        )
    if tuple(sorted(actual, key=lambda seed: seed.relative_path)) != seeds:
        raise _invalid("Final Git tree differs from the reviewed seed manifest")


def _install_index(git_dir, data):
    # Link a complete fsynced file into an absent destination atomically. A
    # rename/replace would clobber a competing writer between check and install.
    temporary = git_dir / f".plaza-reviewed-{uuid4().hex}.index"
    files.atomic_replace(temporary, data)
    with files.directory(git_dir) as parent:
        os.link(
            temporary.name,
            "index",
            src_dir_fd=parent,
            dst_dir_fd=parent,
            follow_symlinks=False,
        )
        os.unlink(temporary.name, dir_fd=parent)
        os.fsync(parent)


def initialize_repository(
    proposal: RepoInitProposal, approval: RepoInitApproval
) -> ProjectInspection:
    """Commit exact raw reviewed bytes under a canonical-directory bootstrap lock.

    Each attempt is recorded durably outside the source. An interrupted attempt
    retains its completed-step marker and Git metadata; its approval cannot replay.
    A fresh explicit proposal is required after deliberate operator inspection.
    """
    lock = None
    stage = "approval validation"
    attempted = False
    marker = None
    try:
        approval = parse_init_approval(proposal, asdict(approval))
        if not approval.approved:
            raise WorkspaceError(
                "repository_setup_denied",
                approval.reason or "Chief Architect declined repository setup",
            )
        if proposal.initial_branch != "main" or _digest(proposal) != proposal.digest:
            raise _invalid()
        UUID(proposal.proposal_id)
        if len(_canonical(proposal, digest=True)) > MAX_PROPOSAL_BYTES:
            raise _narrow()
        _check_root(proposal)
        key = hashlib.sha256(os.fsencode(proposal.root)).hexdigest()
        managed = proposal.root.parent / ".plaza-worktrees/bootstrap"
        with files.directory(managed, create=True):
            pass
        try:
            lock = files.FileLock.acquire(managed / f"{key}.lock")
        except BlockingIOError:
            raise WorkspaceError(
                "workspace_busy", "Repository initialization is in progress"
            ) from None
        marker = managed / f"{key}-{proposal.proposal_id}.json"
        if os.path.lexists(marker):
            raise _invalid(
                "Initialization was already attempted; inspect retained metadata and request a fresh review"
            )
        _check_root(proposal)
        project = _candidate(proposal.root)
        if (project.common_git_dir is not None) != proposal.unborn:
            raise _invalid()
        with TemporaryDirectory(prefix="plaza-repo-init-") as temporary:
            git = _Git(proposal.root, Path(temporary))
            if _inventory(proposal.root, git) != proposal.seed_files:
                raise _invalid()
            if proposal.unborn:
                # show-ref misses dangling symbolic refs. Reject those before
                # writing objects too; the publication CAS remains essential.
                git.run(
                    "show-ref", "--verify", "--quiet", "refs/heads/main", allowed=(1,)
                )
                git.run("symbolic-ref", "--quiet", "refs/heads/main", allowed=(1,))
                refs = git.run("for-each-ref", "--format=%(refname)", "refs/heads/main")
                if refs:
                    raise _invalid("main already exists; request a fresh review")

            def record(state):
                lock.validate()
                files.atomic_replace(
                    marker,
                    json.dumps(
                        dict(
                            proposal_id=proposal.proposal_id,
                            digest=proposal.digest,
                            state=state,
                            completed_step=stage,
                        ),
                        sort_keys=True,
                    ).encode()
                    + b"\n",
                )

            stage = "proposal revalidation"
            record("creating")
            attempted = True
            if not proposal.unborn:
                git.run(
                    "init",
                    "--initial-branch=main",
                    f"--template={git.empty}",
                    str(proposal.root),
                )
            stage = "Git metadata preparation"
            record("creating")
            index = Path(temporary) / "reviewed.index"
            git.run("read-tree", "--empty", index=index)
            entries = []
            for seed in proposal.seed_files:
                current, data = _read_seed(proposal.root, seed.relative_path)
                if current != seed:
                    raise _invalid()
                oid = git.run(
                    "hash-object", "-w", "--no-filters", "--stdin", data=data
                ).strip()
                entries.append(
                    f"{seed.mode:o} ".encode()
                    + oid
                    + b"\t"
                    + os.fsencode(seed.relative_path)
                    + b"\0"
                )
            git.run(
                "update-index",
                "-z",
                "--index-info",
                data=b"".join(entries),
                index=index,
            )
            tree = git.run("write-tree", index=index).decode("ascii").strip()
            _verify_tree(git, tree, proposal.seed_files)
            _check_root(proposal)
            if _inventory(proposal.root, git) != proposal.seed_files:
                raise _invalid()
            _candidate(proposal.root)
            stage = "reviewed tree verification"
            record("creating")
            commit = (
                git.run("commit-tree", tree, "-m", "Initialize reviewed project")
                .decode("ascii")
                .strip()
            )
            stage = "initial commit object creation"
            record("creating")
            object_format = git.run("rev-parse", "--show-object-format").strip()
            zero = "0" * {b"sha1": 40, b"sha256": 64}[object_format]
            _check_root(proposal)
            _candidate(proposal.root)
            git.run("update-ref", "--no-deref", "refs/heads/main", commit, zero)
            stage = "main ref publication"
            record("creating")
            git.run("symbolic-ref", "HEAD", "refs/heads/main")
            stage = "main HEAD selection"
            record("creating")
            # New init creates no index. Never replace an existing unborn index.
            if not proposal.unborn:
                index_path = proposal.root / ".git/index"
                if os.path.lexists(index_path):
                    raise _invalid(
                        "New repository index appeared during initialization"
                    )
                _install_index(
                    index_path.parent,
                    files.read_regular(index, max_bytes=MAX_PROPOSAL_BYTES * 4),
                )
            result = inspect_project(proposal.root)
            if (
                result.root_identity != proposal.root_identity
                or result.head_commit != commit
                or result.source_branch != "main"
            ):
                raise _invalid()
            stage = "repository initialization"
            record("ready")
            return result
    except (
        WorkspaceError,
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        if attempted:
            raise _invalid(
                f"Repository initialization failed after {stage}; files and Git metadata retained for inspection; request a fresh review"
            ) from None
        if isinstance(error, WorkspaceError):
            raise
        raise _invalid(
            "Repository initialization validation failed; source files preserved"
        ) from None
    finally:
        if lock is not None:
            lock.close()
