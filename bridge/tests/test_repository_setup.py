"""Architect approval commits exact raw trees in disposable repositories only."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from bridge import repository_setup as setup
from bridge.workspace import WorkspaceError


def git(root, *args, data=None):
    return subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(root),
            *args,
        ],
        input=data,
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout


def project(tmp_path, *, unborn=False):
    root = tmp_path / "project"
    root.mkdir()
    if unborn:
        git(root, "init", "-b", "owner-topic")
    return root


def approve(proposal):
    return setup.parse_init_approval(
        proposal,
        dict(
            proposal_id=proposal.proposal_id,
            digest=proposal.digest,
            approved=True,
            reason="Reviewed exact seed manifest",
        ),
    )


def committed_paths(root):
    return {
        os.fsdecode(path)
        for path in git(root, "ls-tree", "-r", "--name-only", "-z", "HEAD").split(b"\0")
        if path
    }


def test_empty_approved_repo_starts_on_main(tmp_path):
    root = project(tmp_path)
    proposal = setup.build_init_proposal(root)
    assert proposal.initial_branch == "main" and proposal.seed_files == ()
    assert not proposal.unborn and not (root / ".git").exists()
    inspection = setup.initialize_repository(proposal, approve(proposal))
    assert inspection.source_branch == "main" and inspection.head_commit
    assert committed_paths(root) == set()
    assert git(root, "status", "--porcelain") == b""
    assert git(root, "remote") == b""
    assert (
        git(root, "show", "-s", "--format=%an <%ae>|%cn <%ce>", "HEAD").strip()
        == b"Plaza Bridge <plaza-bridge@localhost>|Plaza Bridge <plaza-bridge@localhost>"
    )


def test_populated_repo_commits_only_reviewed_seed(tmp_path):
    root = project(tmp_path)
    (root / ".gitignore").write_text("ignored/\n*.cache\n!keep.cache\n")
    (root / ".gitattributes").write_text("*.txt text eol=lf filter=unsafe\n")
    included = {
        ".gitignore",
        ".gitattributes",
        "README.txt",
        "-dash\tnewline\n.txt",
        "keep.cache",
        "run.sh",
        "nested/.gitignore",
        "nested/keep.txt",
    }
    for name in [
        "README.txt",
        "-dash\tnewline\n.txt",
        "keep.cache",
        "run.sh",
        ".env",
        ".env.example",
        "credentials.json",
        "private.pem",
        "id_ed25519",
        "secret.key",
        "drop.cache",
        "ignored/data.txt",
        "node_modules/package/file",
        "dist/generated.txt",
        "nested-repo/a.txt",
        "nested/keep.txt",
        "nested/drop.txt",
    ]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture-only\r\n")
    (root / "nested/.gitignore").write_text("drop.txt\n")
    (root / "run.sh").chmod(0o755)
    git(root / "nested-repo", "init", "-b", "topic")
    (root / "symlink.txt").symlink_to(root / "README.txt")
    (root / "symlink-dir").symlink_to(root / "nested", target_is_directory=True)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    proposal = setup.build_init_proposal(root)
    assert {item.relative_path for item in proposal.seed_files} == included
    assert not (root / ".git").exists()
    setup.initialize_repository(proposal, approve(proposal))
    assert committed_paths(root) == included
    for item in proposal.seed_files:
        assert (
            git(root, "show", "HEAD:" + item.relative_path)
            == before[root / item.relative_path]
        )
        assert (
            item.sha256 == hashlib.sha256(before[root / item.relative_path]).hexdigest()
        )
    assert (
        next(
            item.mode for item in proposal.seed_files if item.relative_path == "run.sh"
        )
        == 0o100755
    )
    assert all(path.read_bytes() == value for path, value in before.items())
    assert git(root, "remote") == b""


@pytest.mark.parametrize("object_format", ["sha1", "sha256"])
def test_unborn_prior_index_survives_without_entering_commit(tmp_path, object_format):
    root = project(tmp_path)
    git(root, "init", "-b", "owner-topic", "--object-format=" + object_format)
    (root / "unapproved-staged.txt").write_text("old index only")
    git(root, "add", "unapproved-staged.txt")
    (root / "unapproved-staged.txt").unlink()
    (root / "seed.txt").write_bytes(b"raw\r\n")
    (root / ".env").write_bytes(b"FAKE_SECRET_FIXTURE")
    (root / "private-only.txt").write_text("info excluded")
    (root / ".git/info/exclude").write_text("private-only.txt\n")
    (root / ".gitattributes").write_text("*.txt filter=unsafe text eol=lf\n")
    sentinel = tmp_path / "executed"
    script = tmp_path / "program.sh"
    script.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(sentinel))}\ncat\n")
    script.chmod(0o755)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ["reference-transaction", "pre-commit", "post-commit"]:
        (hooks / name).write_bytes(script.read_bytes())
        (hooks / name).chmod(0o755)
    for key, value in [
        ("core.hooksPath", str(hooks)),
        ("core.fsmonitor", str(script)),
        ("filter.unsafe.clean", str(script)),
        ("filter.unsafe.process", str(script)),
        ("filter.unsafe.required", "true"),
        ("commit.gpgsign", "true"),
        ("gpg.program", str(script)),
    ]:
        git(root, "config", key, value)
    original_index = (root / ".git/index").read_bytes()
    original_config = (root / ".git/config").read_bytes()
    proposal = setup.build_init_proposal(root)
    assert proposal.unborn
    assert "private-only.txt" not in {
        item.relative_path for item in proposal.seed_files
    }
    setup.initialize_repository(proposal, approve(proposal))
    assert committed_paths(root) == {"seed.txt", ".gitattributes"}
    assert git(root, "show", "HEAD:seed.txt") == b"raw\r\n"
    assert (root / ".git/index").read_bytes() == original_index
    assert (root / ".git/config").read_bytes() == original_config
    assert (root / ".env").read_bytes() == b"FAKE_SECRET_FIXTURE"
    assert not sentinel.exists()
    assert git(root, "symbolic-ref", "--short", "HEAD").strip() == b"main"
    assert git(root, "remote") == b""


@pytest.mark.parametrize(
    "change", ["bytes", "add", "remove", "mode", "symlink", "root", "root_symlink"]
)
def test_final_tree_change_invalidates_approval(tmp_path, change):
    root = project(tmp_path)
    seed = root / "seed.txt"
    seed.write_text("reviewed")
    proposal = setup.build_init_proposal(root)
    identity = root.stat().st_ino
    if change == "bytes":
        seed.write_text("modified")
        assert root.stat().st_ino == identity
    elif change == "add":
        (root / "extra.txt").write_text("unreviewed")
    elif change == "remove":
        seed.unlink()
    elif change == "mode":
        seed.chmod(0o755)
    elif change == "symlink":
        seed.unlink()
        seed.symlink_to(tmp_path / "outside")
    else:
        root.rename(tmp_path / "saved")
        if change == "root":
            root.mkdir()
            (root / "seed.txt").write_text("reviewed")
        else:
            root.symlink_to(tmp_path / "saved", target_is_directory=True)
    with pytest.raises(WorkspaceError):
        setup.initialize_repository(proposal, approve(proposal))
    assert not (root / ".git").exists()


@pytest.mark.parametrize(
    "failure", ["denial", "digest", "id", "competing", "conflicting_main", "partial"]
)
def test_denial_stale_digest_competing_init_and_partial_failure(
    tmp_path, monkeypatch, failure
):
    root = project(tmp_path, unborn=failure == "conflicting_main")
    (root / "seed.txt").write_text("preserved")
    proposal = setup.build_init_proposal(root)
    approval = approve(proposal)
    if failure == "denial":
        approval = replace(approval, approved=False)
    elif failure == "digest":
        approval = replace(approval, digest="0" * 64)
    elif failure == "id":
        approval = replace(approval, proposal_id="other")
    elif failure == "competing":
        git(root, "init", "-b", "other")
    elif failure == "conflicting_main":
        (root / ".git/refs/heads/main").write_text("ref: refs/heads/missing\n")
    else:
        original = subprocess.run

        def interrupted(args, **kwargs):
            if args[0] == "git" and "commit-tree" in args:
                raise OSError("simulated failure")
            return original(args, **kwargs)

        monkeypatch.setattr(subprocess, "run", interrupted)
    with pytest.raises(WorkspaceError) as error:
        setup.initialize_repository(proposal, approval)
    assert (root / "seed.txt").read_text() == "preserved"
    if failure in {"denial", "digest", "id"}:
        assert not (root / ".git").exists()
    if failure == "partial":
        assert (root / ".git").is_dir()
        assert "after" in str(error.value) and "retained" in str(error.value)
        monkeypatch.setattr(subprocess, "run", original)
        with pytest.raises(WorkspaceError):
            setup.initialize_repository(proposal, approval)


@pytest.mark.parametrize(
    "payload",
    [None, "yes", {}, {"approved": "true"}, {"approved": 1}, {"approved": True}],
)
def test_malformed_approval_never_mutates(tmp_path, payload):
    root = project(tmp_path)
    proposal = setup.build_init_proposal(root)
    with pytest.raises(WorkspaceError):
        setup.parse_init_approval(proposal, payload)
    assert not (root / ".git").exists()


@pytest.mark.parametrize("limit", ["files", "bytes", "proposal"])
def test_inventory_requires_actionable_narrowing(tmp_path, limit):
    root = project(tmp_path)
    if limit == "bytes":
        (root / "large.txt").write_bytes(b"x" * (8 * 1024 * 1024 + 1))
    else:
        for index in range(257 if limit == "files" else 256):
            (
                root / (("long" * 50 if limit == "proposal" else "file") + str(index))
            ).touch()
    with pytest.raises(WorkspaceError, match="[Nn]arrow"):
        setup.build_init_proposal(root)
    assert not (root / ".git").exists()


def test_two_processes_publish_only_one_approved_commit(tmp_path):
    root = project(tmp_path)
    (root / "seed.txt").write_text("reviewed")
    proposal = setup.build_init_proposal(root)
    payload = asdict(proposal)
    payload["root"] = str(proposal.root)
    script = """
import json, sys
from pathlib import Path
from bridge.repository_setup import *
from bridge.workspace import WorkspaceError
value = json.loads(sys.argv[1])
value['root'] = Path(value['root'])
value['root_identity'] = tuple(value['root_identity'])
value['seed_files'] = tuple(SeedFile(**item) for item in value['seed_files'])
proposal = RepoInitProposal(**value)
approval = RepoInitApproval(proposal.proposal_id, proposal.digest, True, 'reviewed')
try:
    result = initialize_repository(proposal, approval)
    print('ready:' + result.head_commit)
except WorkspaceError as error:
    print(error.code)
"""
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda _: subprocess.run(
                    [sys.executable, "-c", script, json.dumps(payload)],
                    capture_output=True,
                    text=True,
                    timeout=40,
                ),
                range(2),
            )
        )
    assert all(result.returncode == 0 for result in results), [
        result.stderr for result in results
    ]
    assert sum(result.stdout.startswith("ready:") for result in results) == 1
    assert git(root, "rev-list", "--count", "HEAD").strip() == b"1"
    assert committed_paths(root) == {"seed.txt"}


def test_tree_tampering_is_detected_before_commit(tmp_path, monkeypatch):
    root = project(tmp_path, unborn=True)
    (root / "seed.txt").write_text("reviewed")
    proposal = setup.build_init_proposal(root)
    original = subprocess.run

    def tamper(args, **kwargs):
        if args[0] == "git" and "update-index" in args:
            kwargs["input"] = kwargs["input"].replace(
                b"\tseed.txt\0", b"\tunapproved.txt\0"
            )
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", tamper)
    with pytest.raises(WorkspaceError):
        setup.initialize_repository(proposal, approve(proposal))
    assert not (root / ".git/refs/heads/main").exists()


def test_source_change_after_staging_invalidates_approval(tmp_path, monkeypatch):
    root = project(tmp_path, unborn=True)
    (root / "seed.txt").write_text("reviewed")
    proposal = setup.build_init_proposal(root)
    original = subprocess.run

    def mutate(args, **kwargs):
        result = original(args, **kwargs)
        if args[0] == "git" and "write-tree" in args:
            (root / "seed.txt").write_text("changed after staging")
        return result

    monkeypatch.setattr(subprocess, "run", mutate)
    with pytest.raises(WorkspaceError):
        setup.initialize_repository(proposal, approve(proposal))
    assert (root / "seed.txt").read_text() == "changed after staging"
    assert not (root / ".git/refs/heads/main").exists()


def test_dangling_main_conflict_is_rejected_before_object_writes(tmp_path):
    root = project(tmp_path, unborn=True)
    (root / "seed.txt").write_text("reviewed")
    proposal = setup.build_init_proposal(root)
    conflict = root / ".git/refs/heads/main"
    conflict.write_text("ref: refs/heads/missing\n")
    before = set((root / ".git/objects").rglob("*"))
    with pytest.raises(WorkspaceError):
        setup.initialize_repository(proposal, approve(proposal))
    assert set((root / ".git/objects").rglob("*")) == before
    assert conflict.read_text() == "ref: refs/heads/missing\n"


def test_credential_private_key_names_never_enter_proposal(tmp_path):
    root = project(tmp_path)
    names = [
        "private_key",
        "private-key.backup",
        "service-account.json",
        "service_account.json",
        "production.env",
        ".azure/token",
        ".config/gcloud/application_default_credentials.json",
    ]
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("FAKE-CREDENTIAL-FIXTURE")
    proposal = setup.build_init_proposal(root)
    assert proposal.seed_files == ()
    assert not (root / ".git").exists()


def test_global_templates_programs_and_git_environment_are_not_used(
    tmp_path, monkeypatch
):
    root = project(tmp_path)
    (root / "seed.txt").write_bytes(b"raw\r\n")
    (root / ".gitattributes").write_text("*.txt filter=unsafe text eol=lf\n")
    sentinel = tmp_path / "program-ran"
    template = tmp_path / "template"
    (template / "hooks").mkdir(parents=True)
    script = template / "hooks/reference-transaction"
    script.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(sentinel))}\ncat\n")
    script.chmod(0o755)
    (template / "unexpected-template-file").write_text("must not copy")
    home = tmp_path / "home"
    home.mkdir()
    config = home / ".gitconfig"
    for key, value in [
        ("init.templateDir", str(template)),
        ("core.hooksPath", str(template / "hooks")),
        ("core.fsmonitor", str(script)),
        ("filter.unsafe.clean", str(script)),
        ("filter.unsafe.process", str(script)),
        ("filter.unsafe.required", "true"),
        ("commit.gpgsign", "true"),
        ("gpg.program", str(script)),
    ]:
        git(root, "config", "--file", str(config), key, value)
    monkeypatch.setenv("HOME", str(home))
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-b", "other")
    index = tmp_path / "inherited-index"
    index.write_bytes(b"UNCHANGED INDEX FIXTURE")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(index))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(template / "hooks"))
    before = config.read_bytes()
    proposal = setup.build_init_proposal(root)
    result = setup.initialize_repository(proposal, approve(proposal))
    assert result.root == root and result.source_branch == "main"
    assert not sentinel.exists()
    assert not (root / ".git/unexpected-template-file").exists()
    assert index.read_bytes() == b"UNCHANGED INDEX FIXTURE"
    assert config.read_bytes() == before
    assert not (other / ".git/refs/heads/other").exists()


@pytest.mark.parametrize("tampering", ["blob", "mode", "type"])
def test_complete_tree_blob_mode_type_verification(tmp_path, monkeypatch, tampering):
    root = project(tmp_path, unborn=True)
    (root / "seed.txt").write_bytes(b"reviewed\r\n")
    proposal = setup.build_init_proposal(root)
    original = subprocess.run

    def tamper(args, **kwargs):
        if args[0] == "git":
            if tampering == "blob" and "hash-object" in args:
                kwargs["input"] = b"transformed\n"
            if "update-index" in args:
                if tampering == "mode":
                    kwargs["input"] = kwargs["input"].replace(b"100644 ", b"100755 ")
                if tampering == "type":
                    kwargs["input"] = kwargs["input"].replace(b"100644 ", b"120000 ")
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", tamper)
    with pytest.raises(WorkspaceError):
        setup.initialize_repository(proposal, approve(proposal))
    assert not (root / ".git/refs/heads/main").exists()
    assert (root / "seed.txt").read_bytes() == b"reviewed\r\n"


@pytest.mark.parametrize(
    "command",
    [
        "read-tree",
        "hash-object",
        "update-index",
        "write-tree",
        "ls-tree",
        "cat-file",
        "commit-tree",
        "update-ref",
        "symbolic-ref",
    ],
)
def test_partial_failure_preserves_unborn_index_config_and_sources(
    tmp_path, monkeypatch, command
):
    root = project(tmp_path, unborn=True)
    (root / "old.txt").write_text("index fixture")
    git(root, "add", "old.txt")
    (root / "old.txt").unlink()
    (root / "seed.txt").write_text("source fixture")
    (root / ".env").write_text("FAKE_SECRET_FIXTURE")
    proposal = setup.build_init_proposal(root)
    before_index = (root / ".git/index").read_bytes()
    before_config = (root / ".git/config").read_bytes()
    original = subprocess.run

    def interrupted(args, **kwargs):
        if args[0] == "git" and command in args:
            # Only fail the mutation operation; read-only classification may use
            # symbolic-ref before the attempt has started.
            if command != "symbolic-ref" or (
                "HEAD" in args and "refs/heads/main" in args
            ):
                raise OSError("simulated tool interruption")
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", interrupted)
    with pytest.raises(WorkspaceError, match="retained"):
        setup.initialize_repository(proposal, approve(proposal))
    assert (root / ".git/index").read_bytes() == before_index
    assert (root / ".git/config").read_bytes() == before_config
    assert (root / "seed.txt").read_text() == "source fixture"
    assert (root / ".env").read_text() == "FAKE_SECRET_FIXTURE"
    monkeypatch.setattr(subprocess, "run", original)
    with pytest.raises(WorkspaceError):
        setup.initialize_repository(proposal, approve(proposal))


def test_competing_commit_before_publication_invalidates_approval(
    tmp_path, monkeypatch
):
    root = project(tmp_path, unborn=True)
    (root / "seed.txt").write_text("reviewed")
    proposal = setup.build_init_proposal(root)
    original = subprocess.run
    competitor = None

    def compete(args, **kwargs):
        nonlocal competitor
        result = original(args, **kwargs)
        if args[0] == "git" and "write-tree" in args:
            tree = result.stdout.strip().decode()
            commit_args = [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-C",
                str(root),
                "commit-tree",
                tree,
                "-m",
                "competing owner commit",
            ]
            competitor = original(
                commit_args, capture_output=True, env=kwargs["env"], check=True
            ).stdout.strip()
            original(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-C",
                    str(root),
                    "update-ref",
                    "refs/heads/owner-topic",
                    competitor.decode(),
                ],
                capture_output=True,
                check=True,
            )
        return result

    monkeypatch.setattr(subprocess, "run", compete)
    with pytest.raises(WorkspaceError):
        setup.initialize_repository(proposal, approve(proposal))
    assert not (root / ".git/refs/heads/main").exists()
    assert git(root, "rev-parse", "HEAD").strip() == competitor


def test_new_index_is_installed_without_overwriting_competing_index(
    tmp_path, monkeypatch
):
    root = project(tmp_path)
    (root / "seed.txt").write_text("reviewed")
    proposal = setup.build_init_proposal(root)
    original_replace = setup.files.atomic_replace

    # Race the final filesystem installation, after any optimistic absence check.
    def competing_index(path, data):
        if path.parent == root / ".git":
            (root / ".git/index").write_bytes(b"COMPETING INDEX FIXTURE")
        return original_replace(path, data)

    monkeypatch.setattr(setup.files, "atomic_replace", competing_index)
    with pytest.raises(WorkspaceError):
        setup.initialize_repository(proposal, approve(proposal))
    assert (root / ".git/index").read_bytes() == b"COMPETING INDEX FIXTURE"


def test_full_approval_payload_rejects_non_boolean_and_unencodable_reason(tmp_path):
    root = project(tmp_path)
    proposal = setup.build_init_proposal(root)
    for approved, reason in [(1, "yes"), ("true", "yes"), (True, "\ud800")]:
        payload = dict(
            proposal_id=proposal.proposal_id,
            digest=proposal.digest,
            approved=approved,
            reason=reason,
        )
        with pytest.raises(WorkspaceError):
            setup.parse_init_approval(proposal, payload)


def test_local_excludes_file_is_honored_without_changing_config(tmp_path):
    root = project(tmp_path, unborn=True)
    (root / "private.txt").write_text("excluded fixture")
    (root / "keep.txt").write_text("reviewed")
    exclude = tmp_path / "local-excludes"
    exclude.write_text("*.txt\n")
    git(root, "config", "core.excludesFile", str(exclude))
    (root / ".git/info/exclude").write_text("!keep.txt\n")
    before = (root / ".git/config").read_bytes()
    proposal = setup.build_init_proposal(root)
    assert {seed.relative_path for seed in proposal.seed_files} == {"keep.txt"}
    setup.initialize_repository(proposal, approve(proposal))
    assert committed_paths(root) == {"keep.txt"}
    assert (root / ".git/config").read_bytes() == before
    assert (root / "private.txt").read_text() == "excluded fixture"


def promisor_fetch_sentinel(root, tmp_path):
    sentinel = tmp_path / "upload-pack-ran"
    script = tmp_path / "upload-pack.sh"
    script.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(sentinel))}\nexit 1\n")
    script.chmod(0o755)
    git(root, "config", "remote.origin.promisor", "true")
    git(root, "config", "remote.origin.url", str(tmp_path / "local-remote"))
    git(root, "config", "remote.origin.uploadpack", str(script))
    return sentinel


@pytest.mark.parametrize(
    "entry", ["proposal", "inspection", "initialize", "final_inspection"]
)
def test_missing_head_never_executes_promisor_fetch(tmp_path, monkeypatch, entry):
    root = project(tmp_path, unborn=True)
    (root / "seed.txt").write_text("preserved fixture")
    sentinel = promisor_fetch_sentinel(root, tmp_path)
    before_config = (root / ".git/config").read_bytes()
    proposal = setup.build_init_proposal(root)
    missing = "1" * 40 + "\n"
    if entry != "final_inspection":
        (root / ".git/refs/heads/owner-topic").write_text(missing)
    else:
        original = subprocess.run

        def corrupt_after_head_selection(args, **kwargs):
            result = original(args, **kwargs)
            if (
                args[0] == "git"
                and "symbolic-ref" in args
                and args[-2:] == ["HEAD", "refs/heads/main"]
            ):
                (root / ".git/refs/heads/main").write_text(missing)
            return result

        monkeypatch.setattr(subprocess, "run", corrupt_after_head_selection)
    caught = None
    try:
        if entry == "proposal":
            setup.build_init_proposal(root)
        elif entry == "inspection":
            setup.inspect_project(root)
        else:
            setup.initialize_repository(proposal, approve(proposal))
    except WorkspaceError as error:
        caught = error
    # Assert the actual execution boundary even if resolution otherwise fails.
    assert not sentinel.exists()
    assert caught is not None
    assert (root / ".git/config").read_bytes() == before_config
    assert (root / "seed.txt").read_text() == "preserved fixture"
    if entry != "final_inspection":
        assert not (root / ".git/refs/heads/main").exists()


@pytest.mark.parametrize(
    "malformed", ["missing_object", "invalid_oid", "dangling_symref", "nonbranch_head"]
)
def test_existing_unresolvable_head_is_never_classified_unborn(tmp_path, malformed):
    root = project(tmp_path, unborn=True)
    branch_ref = root / ".git/refs/heads/owner-topic"
    if malformed == "missing_object":
        branch_ref.write_text("1" * 40 + "\n")
    elif malformed == "invalid_oid":
        branch_ref.write_text("invalid object id\n")
    elif malformed == "dangling_symref":
        branch_ref.write_text("ref: refs/heads/missing\n")
    else:
        (root / ".git/HEAD").write_text("ref: refs/tags/missing\n")
    with pytest.raises(WorkspaceError):
        setup.build_init_proposal(root)
    assert not (root / ".git/refs/heads/main").exists()


def test_plumbing_missing_blob_never_executes_promisor_fetch(tmp_path, monkeypatch):
    root = project(tmp_path, unborn=True)
    (root / "seed.txt").write_text("reviewed fixture")
    sentinel = promisor_fetch_sentinel(root, tmp_path)
    proposal = setup.build_init_proposal(root)
    original = subprocess.run

    def remove_blob(args, **kwargs):
        if args[0] == "git" and "cat-file" in args:
            oid = args[-1]
            (root / ".git/objects" / oid[:2] / oid[2:]).unlink()
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", remove_blob)
    caught = None
    try:
        setup.initialize_repository(proposal, approve(proposal))
    except WorkspaceError as error:
        caught = error
    assert not sentinel.exists()
    assert caught is not None
    assert not (root / ".git/refs/heads/main").exists()
    assert (root / "seed.txt").read_text() == "reviewed fixture"


def test_inspection_rejects_git_without_required_option_support(tmp_path, monkeypatch):
    root = project(tmp_path)
    binary = tmp_path / "bin"
    binary.mkdir()
    git_script = binary / "git"
    git_script.write_text(
        "#!/bin/sh\necho 'unknown option: --no-lazy-fetch' >&2\nexit 129\n"
    )
    git_script.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    with pytest.raises(WorkspaceError):
        setup.inspect_project(root)
    assert not (root / ".git").exists()
