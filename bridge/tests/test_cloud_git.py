"""Git sync of one department branch, against a bare repository in tmp_path."""

import json
import os
import subprocess

import pytest

from bridge import cloud_git
from bridge.cloud_git import (
    CloudSyncError,
    check_switch_to_local,
    fast_forward_to,
    github_repo,
    mark_cloud,
    sync_before_start,
)
from bridge.tests.test_workspace import git, repository
from bridge.workspace import inspect_project, prepare_worktree


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """A global Git configuration of the test's own; the machine's is not read."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        "[user]\n\tname = Fixture\n\temail = fixture@example.invalid\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    return home


@pytest.fixture
def file_protocol(monkeypatch):
    """The bare origin is a path remote; allow it only for this test."""
    monkeypatch.setattr(
        cloud_git, "NETWORK_PROTOCOLS", (*cloud_git.NETWORK_PROTOCOLS, "file")
    )


def setup(tmp_path):
    """A project with a bare origin and an engineering worktree."""
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True
    )
    root = repository(tmp_path)
    git(root, "remote", "add", "origin", str(origin))
    git(root, "push", "-q", "origin", "main")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    workspace = prepare_worktree(
        inspect_project(root), domain_id="engineering", runtime_root=runtime
    )
    return origin, workspace


def remote_tip(origin, branch):
    found = git(
        origin, "for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}"
    )
    return found or None


def commit(root, name, text="change\n"):
    (root / name).write_text(text)
    git(root, "add", name)
    git(root, "commit", "-q", "-m", name)
    return git(root, "rev-parse", "HEAD")


def other_clone(tmp_path, origin, branch):
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", "-b", branch, str(origin), str(other))
    return other


def head(workspace):
    return git(workspace.worktree_path, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Owner/Repo",
        "https://github.com/Owner/Repo.git",
        "git@github.com:Owner/Repo",
        "git@github.com:Owner/Repo.git",
        "ssh://git@github.com/Owner/Repo",
        "ssh://git@github.com/Owner/Repo.git",
    ],
)
def test_github_repo_normalises_the_three_forms(tmp_path, url):
    root = repository(tmp_path)
    git(root, "remote", "add", "origin", url)
    assert github_repo(root) == "https://github.com/Owner/Repo"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "https://gitlab.com/Owner/Repo",
        "https://github.com.evil.example/Owner/Repo",
        "http://github.com/Owner/Repo",
        "https://user:secret@github.com/Owner/Repo",
        "https://github.com/Owner/Repo/extra",
        "git@github.com:Owner",
        "/srv/git/repo.git",
    ],
)
def test_github_repo_refuses_another_host_and_no_origin(tmp_path, url):
    root = repository(tmp_path)
    if url is not None:
        git(root, "remote", "add", "origin", url)
    with pytest.raises(CloudSyncError) as raised:
        github_repo(root)
    assert raised.value.code == "not_github"
    assert "secret" not in raised.value.detail


def test_github_repo_refuses_two_origin_urls(tmp_path):
    root = repository(tmp_path)
    git(root, "remote", "add", "origin", "https://github.com/Owner/Repo")
    git(root, "config", "--add", "remote.origin.url", "https://github.com/Other/Repo")
    with pytest.raises(CloudSyncError) as raised:
        github_repo(root)
    assert raised.value.code == "not_github"


@pytest.mark.parametrize("how", ["pushurl", "pushinsteadof"])
def test_a_push_url_that_is_not_the_same_repository_is_refused(
    tmp_path, isolated_home, how
):
    root = repository(tmp_path)
    git(root, "remote", "add", "origin", "https://github.com/Owner/Repo")
    if how == "pushurl":
        git(root, "config", "remote.origin.pushurl", "git@github.com:Other/Repo.git")
    else:
        with open(isolated_home / ".gitconfig", "a") as config:
            config.write(
                '[url "https://github.com/Other/"]\n'
                "\tpushInsteadOf = https://github.com/Owner/\n"
            )
    with pytest.raises(CloudSyncError) as raised:
        github_repo(root)
    assert raised.value.code == "not_github"


def test_a_branch_missing_on_origin_is_pushed(tmp_path, file_protocol):
    origin, workspace = setup(tmp_path)
    assert remote_tip(origin, workspace.branch) is None
    tip = sync_before_start(workspace)
    assert tip == head(workspace) == remote_tip(origin, workspace.branch)


def test_local_ahead_is_pushed_and_local_behind_is_fast_forwarded(
    tmp_path, file_protocol
):
    origin, workspace = setup(tmp_path)
    sync_before_start(workspace)
    ahead = commit(workspace.worktree_path, "ahead.txt")
    assert sync_before_start(workspace) == ahead
    assert remote_tip(origin, workspace.branch) == ahead

    other = other_clone(tmp_path, origin, workspace.branch)
    behind = commit(other, "cloud.txt")
    git(other, "push", "-q", "origin", workspace.branch)
    assert sync_before_start(workspace) == behind
    assert head(workspace) == behind
    assert (workspace.worktree_path / "cloud.txt").read_text() == "change\n"

    # Equal tips: nothing moves on either side.
    assert sync_before_start(workspace) == behind
    assert remote_tip(origin, workspace.branch) == behind


def test_a_dirty_worktree_is_refused_before_anything_is_sent(tmp_path, file_protocol):
    origin, workspace = setup(tmp_path)
    (workspace.worktree_path / "untracked.txt").write_text("draft\n")
    with pytest.raises(CloudSyncError) as raised:
        sync_before_start(workspace)
    assert raised.value.code == "dirty"
    assert remote_tip(origin, workspace.branch) is None


def test_a_diverged_branch_is_refused_and_nothing_moves(tmp_path, file_protocol):
    origin, workspace = setup(tmp_path)
    sync_before_start(workspace)
    other = other_clone(tmp_path, origin, workspace.branch)
    theirs = commit(other, "cloud.txt")
    git(other, "push", "-q", "origin", workspace.branch)
    ours = commit(workspace.worktree_path, "local.txt")
    with pytest.raises(CloudSyncError) as raised:
        sync_before_start(workspace)
    assert raised.value.code == "diverged"
    assert head(workspace) == ours
    assert remote_tip(origin, workspace.branch) == theirs


def test_fast_forward_to_takes_exactly_the_named_commit(tmp_path, file_protocol):
    origin, workspace = setup(tmp_path)
    sync_before_start(workspace)
    other = other_clone(tmp_path, origin, workspace.branch)
    named = commit(other, "first.txt")
    past = commit(other, "second.txt")
    git(other, "push", "-q", "origin", workspace.branch)
    assert remote_tip(origin, workspace.branch) == past
    fast_forward_to(workspace, named)
    assert head(workspace) == named
    assert (workspace.worktree_path / "first.txt").exists()
    assert not (workspace.worktree_path / "second.txt").exists()


def test_fast_forward_to_refuses_a_commit_that_is_not_ahead(tmp_path, file_protocol):
    origin, workspace = setup(tmp_path)
    sync_before_start(workspace)
    other = other_clone(tmp_path, origin, workspace.branch)
    theirs = commit(other, "cloud.txt")
    git(other, "push", "-q", "origin", workspace.branch)
    ours = commit(workspace.worktree_path, "local.txt")
    with pytest.raises(CloudSyncError) as raised:
        fast_forward_to(workspace, theirs)
    assert raised.value.code == "diverged"
    assert head(workspace) == ours
    # A commit that is nowhere, and a value that is not a commit id at all.
    for missing in ("0" * 40, "--upload-pack=touch"):
        with pytest.raises(CloudSyncError) as raised:
            fast_forward_to(workspace, missing)
        assert raised.value.code == "diverged"
    assert head(workspace) == ours


def test_only_the_workspace_branch_is_ever_pushed(tmp_path, file_protocol):
    origin, workspace = setup(tmp_path)
    git(workspace.worktree_path, "branch", "side")
    git(workspace.worktree_path, "tag", "v-local")
    git(workspace.project_root, "config", "push.default", "matching")
    git(workspace.project_root, "config", "push.followTags", "true")
    sync_before_start(workspace)
    commit(workspace.worktree_path, "ahead.txt")
    git(workspace.worktree_path, "tag", "-a", "-m", "t", "v-annotated")
    sync_before_start(workspace)
    refs = git(origin, "for-each-ref", "--format=%(refname)").split()
    assert sorted(refs) == sorted(["refs/heads/main", f"refs/heads/{workspace.branch}"])


def test_fast_forward_to_does_nothing_when_the_commit_is_already_here(
    tmp_path, monkeypatch
):
    origin, workspace = setup(tmp_path)
    first = head(workspace)
    second = commit(workspace.worktree_path, "local.txt")

    def no_network(*args, **kwargs):
        raise AssertionError("network git must not run")

    monkeypatch.setattr(cloud_git, "_network_git", no_network)
    (workspace.worktree_path / "untracked.txt").write_text("draft\n")
    fast_forward_to(workspace, second)
    fast_forward_to(workspace, first)
    assert head(workspace) == second


@pytest.mark.parametrize(
    "key, value",
    [
        ("core.sshCommand", "touch pwned"),
        ("credential.helper", "!touch pwned"),
        ("url.https://evil.example/.insteadOf", "https://github.com/"),
    ],
)
def test_repository_level_transport_config_is_refused(
    tmp_path, file_protocol, key, value
):
    origin, workspace = setup(tmp_path)
    git(workspace.project_root, "config", key, value)
    with pytest.raises(CloudSyncError) as raised:
        sync_before_start(workspace)
    assert raised.value.code == "unsafe_config"
    assert key.split(".")[-1].lower() in raised.value.detail.lower()
    assert value not in raised.value.detail
    assert remote_tip(origin, workspace.branch) is None


def test_worktree_scope_transport_config_is_refused(tmp_path, file_protocol):
    origin, workspace = setup(tmp_path)
    git(workspace.project_root, "config", "extensions.worktreeConfig", "true")
    git(
        workspace.worktree_path,
        "config",
        "--worktree",
        "remote.origin.receivepack",
        "touch pwned",
    )
    with pytest.raises(CloudSyncError) as raised:
        sync_before_start(workspace)
    assert raised.value.code == "unsafe_config"
    assert "receivepack" in raised.value.detail
    assert remote_tip(origin, workspace.branch) is None


def test_a_file_remote_is_refused_without_the_test_allowance(tmp_path):
    origin, workspace = setup(tmp_path)
    assert cloud_git.NETWORK_PROTOCOLS == ("https", "ssh")
    with pytest.raises(CloudSyncError) as raised:
        sync_before_start(workspace)
    assert raised.value.code == "git_failed"
    assert remote_tip(origin, workspace.branch) is None


def test_a_repository_filter_and_fsmonitor_are_never_run(tmp_path, file_protocol):
    origin, workspace = setup(tmp_path)
    sync_before_start(workspace)
    other = other_clone(tmp_path, origin, workspace.branch)
    (other / ".gitattributes").write_text("*.dat filter=mark\n")
    git(other, "add", ".gitattributes")
    commit(other, "data.dat", "one\n")
    git(other, "push", "-q", "origin", workspace.branch)

    marker = tmp_path / "marker"
    touch = f"touch {marker}"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("post-merge", "post-checkout", "pre-push", "reference-transaction"):
        hook = hooks / name
        hook.write_text(f"#!/bin/sh\n{touch}\n")
        hook.chmod(0o755)
    monitor = tmp_path / "fsmonitor"
    monitor.write_text(f"#!/bin/sh\n{touch}\nexit 1\n")
    monitor.chmod(0o755)
    project = workspace.project_root
    git(project, "config", "filter.mark.clean", touch)
    git(project, "config", "filter.mark.smudge", f"{touch}; cat")
    git(project, "config", "filter.mark.required", "true")
    git(project, "config", "core.fsmonitor", str(monitor))
    git(project, "config", "core.hooksPath", str(hooks))

    assert sync_before_start(workspace) == head(workspace)
    assert (workspace.worktree_path / "data.dat").read_text() == "one\n"
    later = commit(other, "data.dat", "two\n")
    git(other, "push", "-q", "origin", workspace.branch)
    fast_forward_to(workspace, later)
    assert (workspace.worktree_path / "data.dat").read_text() == "two\n"
    assert not marker.exists()

    # The configuration is live: plain Git runs it.
    os.utime(workspace.worktree_path / "data.dat", (0, 0))
    git(workspace.worktree_path, "status", "--porcelain")
    assert marker.exists()


def test_the_cloud_note_gates_the_switch_to_local(tmp_path):
    origin, workspace = setup(tmp_path)
    note = workspace.common_git_dir / "plaza/cloud" / f"{workspace.domain_id}.json"
    mark_cloud(workspace, unsynced=True)
    assert json.loads(note.read_text()) == {"unsynced": True}
    with pytest.raises(CloudSyncError) as raised:
        check_switch_to_local(workspace)
    assert raised.value.code == "unsynced"
    assert note.exists()

    mark_cloud(workspace, unsynced=False)
    (workspace.worktree_path / "untracked.txt").write_text("draft\n")
    with pytest.raises(CloudSyncError) as raised:
        check_switch_to_local(workspace)
    assert raised.value.code == "dirty"
    assert note.exists()

    (workspace.worktree_path / "untracked.txt").unlink()
    check_switch_to_local(workspace)
    assert not note.exists()


@pytest.mark.parametrize("content", [b"not json", b'{"unsynced": "no"}', b"[]"])
def test_an_unreadable_note_is_unsynced(tmp_path, content):
    origin, workspace = setup(tmp_path)
    mark_cloud(workspace, unsynced=False)
    note = workspace.common_git_dir / "plaza/cloud" / f"{workspace.domain_id}.json"
    note.write_bytes(content)
    with pytest.raises(CloudSyncError) as raised:
        check_switch_to_local(workspace)
    assert raised.value.code == "unsynced"


def test_without_a_note_no_git_runs(tmp_path, monkeypatch):
    origin, workspace = setup(tmp_path)

    def no_git(*args, **kwargs):
        raise AssertionError("git must not run")

    monkeypatch.setattr(cloud_git, "git_without_filters", no_git)
    monkeypatch.setattr(cloud_git, "_network_git", no_git)
    (workspace.worktree_path / "untracked.txt").write_text("draft\n")
    check_switch_to_local(workspace)


def test_a_git_fault_is_git_failed_with_a_short_scrubbed_detail(tmp_path, monkeypatch):
    origin, workspace = setup(tmp_path)

    def failing(*args, **kwargs):
        raise subprocess.CalledProcessError(
            128,
            ["git"],
            stderr=b"fatal: https://user:hunter2@github.com/O/R " + b"x" * 1000,
        )

    monkeypatch.setattr(cloud_git, "git_without_filters", failing)
    with pytest.raises(CloudSyncError) as raised:
        sync_before_start(workspace)
    assert raised.value.code == "git_failed"
    assert "hunter2" not in raised.value.detail
    assert "https://github.com/O/R" in raised.value.detail
    assert len(raised.value.detail) <= 300
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
