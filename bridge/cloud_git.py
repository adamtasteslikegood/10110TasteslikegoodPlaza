"""Git sync of one department branch between its worktree and GitHub.

A cloud department keeps its local worktree, but its agent runs on the cloud
runner, which clones the branch from GitHub and pushes it back after each run.
This is the only module of the bridge that talks to a Git remote.

Local commands go through ``git_without_filters`` (no hook, fsmonitor or
clean/smudge/process filter of the repository runs). The three network commands
(``ls-remote``, ``fetch``, ``push``) go through ``_network_git``, which builds the
same command line and environment as ``workspace._git`` but allows the
``NETWORK_PROTOCOLS`` transports, and first refuses a repository configuration
that could run a command or send a push elsewhere. No ``--force`` is used, and
the only refspec pushed is the workspace branch. Blocking: async callers run
these functions in a worker thread.
"""

import json
import os
from pathlib import Path
import re
import subprocess

from bridge import cloud_log
from bridge import project_files as files
from bridge.workspace import WorkspaceError, git_without_filters

# The transports a network command may use. Tests add "file" for a bare origin.
NETWORK_PROTOCOLS = ("https", "ssh")
NETWORK_TIMEOUT = 120
LOCAL_TIMEOUT = 60
DETAIL_LIMIT = 300

_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_BRANCH = re.compile(r"plaza/workspace-[A-Za-z0-9_-]+")
_NAME = r"([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)"
_REPO = r"([A-Za-z0-9_.-]+?)"
_GITHUB_FORMS = (
    re.compile(rf"https://github\.com/{_NAME}/{_REPO}(?:\.git)?"),
    re.compile(rf"git@github\.com:{_NAME}/{_REPO}(?:\.git)?"),
    re.compile(rf"ssh://git@github\.com/{_NAME}/{_REPO}(?:\.git)?"),
)

# Repository-level (scope local or worktree) keys that can run a command or
# send a push elsewhere. The user's global configuration is trusted.
_UNSAFE_SECTIONS = frozenset({"credential", "http", "url", "protocol", "bundle"})
_UNSAFE_KEYS = frozenset(
    {
        ("core", "sshcommand"),
        ("core", "gitproxy"),
        ("core", "askpass"),
        ("core", "alternaterefscommand"),
        ("ssh", "variant"),
        ("fetch", "bundleuri"),
    }
)
_UNSAFE_ORIGIN = frozenset({"pushurl", "proxy", "uploadpack", "receivepack", "vcs"})


class CloudSyncError(Exception):
    """A refused or failed sync. ``detail`` is for the log, never a credential."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = _scrub(detail)
        super().__init__(f"{code}: {self.detail}")


def _scrub(text: str) -> str:
    return cloud_log.USERINFO.sub(r"\1", text)[:DETAIL_LIMIT]


def _fault(args, error: BaseException) -> CloudSyncError:
    words = list(args)
    while words[:1] == ["-c"]:
        words = words[2:]
    command = words[0] if words else "git"
    output = getattr(error, "stderr", None) or getattr(error, "output", None) or b""
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    if isinstance(error, subprocess.CalledProcessError):
        what = f"exit {error.returncode}"
    elif isinstance(error, subprocess.TimeoutExpired):
        what = "timed out"
    else:
        what = type(error).__name__
    # Scrub before cutting, so a cut cannot leave half a userinfo behind.
    text = cloud_log.USERINFO.sub(r"\1", " ".join(str(output).split()))
    return CloudSyncError("git_failed", f"git {command} {what}: {text}")


def _local(root: Path, *args: str, answers: tuple[int, ...] = ()) -> str | int:
    """Run a local command; an exit code in ``answers`` is returned, not raised."""
    try:
        return git_without_filters(root, *args, timeout=LOCAL_TIMEOUT)
    except subprocess.CalledProcessError as error:
        if error.returncode in answers:
            return error.returncode
        raise _fault(args, error) from None
    except (subprocess.TimeoutExpired, OSError, WorkspaceError) as error:
        raise _fault(args, error) from None


def _check_config(root: Path, expected: str) -> None:
    """Refuse unsafe repository keys, and an origin other than ``expected``."""
    listing = _local(root, "config", "--show-scope", "--list", "-z")
    fields = listing.split("\0")
    for scope, entry in zip(fields[0::2], fields[1::2]):
        if scope not in ("local", "worktree"):
            continue
        key = entry.split("\n", 1)[0]
        section, _, rest = key.partition(".")
        subsection, _, variable = rest.rpartition(".")
        section, variable = section.lower(), variable.lower()
        if (
            section in _UNSAFE_SECTIONS
            or (section, variable) in _UNSAFE_KEYS
            or (
                section == "remote"
                and subsection == "origin"
                and variable in _UNSAFE_ORIGIN
            )
        ):
            raise CloudSyncError(
                "unsafe_config", f"repository {scope} configuration sets {key}"
            )
    # The worktree's own view of origin (config.worktree, includeIf onbranch)
    # can differ from the project's: read it from the root the command uses.
    seen = _origin_repo(root)
    if seen.lower() != expected.lower():
        raise CloudSyncError("not_github", f"the worktree's origin is {seen}")


def _network_git(root: Path, *args: str, expected: str) -> str:
    """Run ls-remote, fetch or push with the machine's login and no repo hooks.

    ``expected`` is the project's GitHub repository; origin as seen from
    ``root`` must be exactly that one repository.
    """
    _check_config(root, expected)
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        GIT_TERMINAL_PROMPT="0",
        GIT_ALLOW_PROTOCOL=":".join(NETWORK_PROTOCOLS),
        LC_ALL="C",
    )
    command = [
        "git",
        "--no-lazy-fetch",
        "--no-optional-locks",
        "-c",
        "core.hooksPath=" + os.devnull,
        "-c",
        "core.fsmonitor=false",
        "-C",
        os.fspath(root),
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            env=environment,
            timeout=NETWORK_TIMEOUT,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        raise _fault(args, error) from None
    return os.fsdecode(result.stdout).removesuffix("\n")


def _normalise(url: str) -> str | None:
    for form in _GITHUB_FORMS:
        match = form.fullmatch(url)
        if match and match.group(2) not in (".", ".."):
            return f"https://github.com/{match.group(1)}/{match.group(2)}"
    return None


def github_repo(project_root: Path) -> str:
    """The origin's GitHub repository; its fetch and push URLs must agree."""
    return _origin_repo(project_root)


def _origin_repo(root: Path) -> str:
    found = []
    for args in (("--all",), ("--push", "--all")):
        output = _local(root, "remote", "get-url", *args, "origin", answers=(2,))
        urls = output.splitlines() if isinstance(output, str) else []
        if len(urls) != 1:
            raise CloudSyncError(
                "not_github", "origin needs exactly one fetch and one push URL"
            )
        repo = _normalise(urls[0])
        if repo is None:
            # The URL itself is not logged: it may carry a token in any form.
            raise CloudSyncError("not_github", "origin is not a GitHub repository URL")
        found.append(repo)
    if found[0].lower() != found[1].lower():
        raise CloudSyncError(
            "not_github", f"origin pushes to {found[1]}, not {found[0]}"
        )
    return found[0]


def _branch(workspace) -> str:
    branch = workspace.branch
    if not isinstance(branch, str) or not _BRANCH.fullmatch(branch):
        raise CloudSyncError("git_failed", "workspace branch is not a plaza branch")
    return branch


def _require_clean(root: Path) -> None:
    if _local(root, "status", "--porcelain"):
        raise CloudSyncError("dirty", "the department worktree has local changes")


def _local_tip(root: Path, branch: str) -> str:
    if (
        _local(root, "rev-parse", "--symbolic-full-name", "HEAD")
        != f"refs/heads/{branch}"
    ):
        raise CloudSyncError("git_failed", "the worktree is not on its branch")
    return _local(root, "rev-parse", "--verify", "HEAD^{commit}")


def _has_commit(root: Path, commit: str) -> bool:
    # Exit 1 is the answer "no such commit"; 128 (e.g. a corrupt object) is a fault.
    found = _local(
        root, "rev-parse", "-q", "--verify", f"{commit}^{{commit}}", answers=(1,)
    )
    return found != 1


def _is_ancestor(root: Path, older: str, newer: str) -> bool:
    return _local(root, "merge-base", "--is-ancestor", older, newer, answers=(1,)) == ""


def _fetch(root: Path, branch: str, expected: str) -> None:
    _network_git(
        root,
        "fetch",
        "--no-tags",
        "--no-recurse-submodules",
        "--no-auto-maintenance",
        "origin",
        f"refs/heads/{branch}",
        expected=expected,
    )


def _push(root: Path, branch: str, expected: str) -> None:
    _network_git(
        root,
        "push",
        "--no-verify",
        "--no-follow-tags",
        "--no-signed",
        "--recurse-submodules=no",
        "origin",
        f"refs/heads/{branch}:refs/heads/{branch}",
        expected=expected,
    )


def _fast_forward(root: Path, commit: str) -> None:
    # A repository's merge.verifySignatures would run its gpg.program, and
    # auto-maintenance would start a background gc after the merge.
    _local(
        root,
        "-c",
        "maintenance.auto=false",
        "-c",
        "gc.auto=0",
        "merge",
        "--ff-only",
        "--no-stat",
        "--no-verify-signatures",
        commit,
    )
    if _local(root, "rev-parse", "--verify", "HEAD^{commit}") != commit:
        raise CloudSyncError("git_failed", "fast-forward did not reach the commit")


def sync_before_start(workspace, *, may_push: bool = True) -> str:
    """Make the branch tip the same here and on origin; return that tip.

    With ``may_push`` false (the runner's last push failed or its run was
    lost), a branch this machine would have to push is refused instead.
    """
    root, branch = Path(workspace.worktree_path), _branch(workspace)
    _require_clean(root)
    local = _local_tip(root, branch)
    expected = github_repo(Path(workspace.project_root))
    ref = f"refs/heads/{branch}"
    listing = _network_git(
        root, "ls-remote", "--heads", "origin", ref, expected=expected
    )
    remote = None
    for line in listing.splitlines():
        sha, _, name = line.partition("\t")
        if name == ref:
            remote = sha
    if remote is None:
        _push_unless_held(root, branch, expected, may_push)
        return local
    if remote == local:
        return local
    _fetch(root, branch, expected)
    remote = _local(root, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
    if remote == local:
        return local
    if _is_ancestor(root, local, remote):
        _fast_forward(root, remote)
        return remote
    if _is_ancestor(root, remote, local):
        _push_unless_held(root, branch, expected, may_push)
        return local
    raise CloudSyncError("diverged", f"local {local[:12]} and origin {remote[:12]}")


def _push_unless_held(root: Path, branch: str, expected: str, may_push: bool) -> None:
    if not may_push:
        raise CloudSyncError(
            "unsynced",
            "the runner's last push did not arrive; this machine's commits must wait",
        )
    _push(root, branch, expected)


def _holds(root: Path, commit: str, local: str) -> bool:
    """Whether the branch tip ``local`` is ``commit`` or has it as an ancestor."""
    return commit == local or (
        _has_commit(root, commit) and _is_ancestor(root, commit, local)
    )


def holds_commit(workspace, commit) -> bool:
    """Whether the worktree's branch holds ``commit``; local git only, no fetch.

    A commit that is only in the object store, fetched but not merged, is not held.
    """
    root, branch = Path(workspace.worktree_path), _branch(workspace)
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        return False
    return _holds(root, commit, _local_tip(root, branch))


def fast_forward_to(workspace, commit: str) -> bool:
    """Move the worktree to exactly ``commit``, which the runner pushed.

    Return True when origin's branch was already past ``commit`` (a second
    writer pushed after the runner): the worktree is then behind GitHub, and
    the caller keeps the cloud note unsynced. A branch that already holds
    ``commit`` (as its tip or an ancestor) is left as it is, with no network
    call, and False is returned: at Start the bridge may just have pushed
    commits newer than the runner's last push.
    """
    root, branch = Path(workspace.worktree_path), _branch(workspace)
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise CloudSyncError("diverged", "the runner's commit is not a commit id")
    local = _local_tip(root, branch)
    if _holds(root, commit, local):
        return False
    _require_clean(root)
    expected = github_repo(Path(workspace.project_root))
    _fetch(root, branch, expected)
    # The commit must be on origin's branch, not only somewhere in the store.
    fetched = _local(root, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
    if not _has_commit(root, commit) or not (
        commit == fetched or _is_ancestor(root, commit, fetched)
    ):
        raise CloudSyncError("diverged", f"commit {commit[:12]} is not on origin")
    if not _is_ancestor(root, local, commit):
        raise CloudSyncError(
            "diverged", f"local {local[:12]} is not behind {commit[:12]}"
        )
    _fast_forward(root, commit)
    return fetched != commit


def _note(workspace) -> Path:
    return (
        Path(workspace.common_git_dir) / "plaza/cloud" / f"{workspace.domain_id}.json"
    )


def mark_cloud(workspace, *, unsynced: bool) -> None:
    """Record whether the cloud may hold commits this machine lacks."""
    note = _note(workspace)
    try:
        with files.directory(note.parent, create=True):
            pass
        files.atomic_replace(note, json.dumps({"unsynced": bool(unsynced)}).encode())
    except OSError as error:
        raise CloudSyncError(
            "git_failed", f"cloud note not written: {type(error).__name__}"
        ) from None


def check_switch_to_local(workspace) -> None:
    """Refuse a switch back to local while the cloud may be ahead or work is dirty."""
    note = _note(workspace)
    try:
        data = json.loads(files.read_regular(note, max_bytes=4096))
    except FileNotFoundError:
        return
    except OSError:
        # Unreadable is not proof either way: still refuse, but say so.
        raise CloudSyncError("git_failed", "the cloud note could not be read") from None
    except ValueError:
        data = None
    if not isinstance(data, dict) or data.get("unsynced") is not False:
        raise CloudSyncError("unsynced", "the cloud may hold commits not fetched here")
    _require_clean(Path(workspace.worktree_path))
    try:
        files.durable_unlink(note)
    except OSError as error:
        raise CloudSyncError(
            "git_failed", f"cloud note not removed: {type(error).__name__}"
        ) from None
