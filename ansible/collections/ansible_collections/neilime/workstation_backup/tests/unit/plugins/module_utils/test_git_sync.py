"""Exercise Git completion checks against disposable local repositories."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from ansible_collections.neilime.workstation_backup.plugins.module_utils import git_sync


def run_command(arguments: list[str], *, environ_update: dict[str, str]) -> tuple[int, str, str]:
    """Run the helper's command against disposable repositories without Ansible."""

    result = subprocess.run(
        arguments,
        env=environ_update,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode, result.stdout, result.stderr


def synchronize_git(source: str, **options) -> dict:
    """Exercise the production helper with the isolated subprocess adapter."""

    return git_sync.synchronize_git(source, run_command=run_command, **options)


def git(path: Path, *arguments: str) -> str:
    """Run Git only inside a temporary fixture."""

    return subprocess.run(
        ["git", "-C", str(path), *arguments],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


@pytest.fixture(name="repositories")
def repositories_fixture(tmp_path, monkeypatch):
    """Create an isolated checkout and bare recovery repository."""

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in list(os.environ):
        if key.startswith("GIT_CONFIG_") and key not in {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"}:
            monkeypatch.delenv(key)
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare", "--initial-branch=main")
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "--initial-branch=main")
    git(source, "config", "user.email", "fixture@example.invalid")
    git(source, "config", "user.name", "Fixture")
    git(source, "remote", "add", "origin", str(remote))
    (source / "dot_settings").write_text("initial\n")
    git(source, "add", ".")
    git(source, "commit", "-m", "Initial")
    git(source, "push", "-u", "origin", "main")
    return source, remote, tmp_path


def advance_remote(repositories):
    """Publish an independent upstream commit without touching the source."""

    source, remote, tmp_path = repositories
    peer = tmp_path / "peer"
    git(tmp_path, "clone", str(remote), str(peer))
    git(peer, "config", "user.email", "fixture@example.invalid")
    git(peer, "config", "user.name", "Fixture")
    (peer / "remote_settings").write_text("upstream\n")
    git(peer, "add", ".")
    git(peer, "commit", "-m", "Upstream")
    git(peer, "push")
    return source


def test_clean_checkout_reports_verified_remote_commit(repositories):
    """A clean checkout reports the current remote commit without making changes."""

    source, remote, _temporary = repositories
    result = synchronize_git(str(source))
    assert not result["changed"]
    assert result["state"] == {
        "repo_root": str(source),
        "branch": "main",
        "upstream": "origin/main",
        "upstream_commit": git(remote, "rev-parse", "main"),
        "status": "",
        "ahead": 0,
        "behind": 0,
        "needs_publish": False,
        "remote_verified": True,
    }


def test_dirty_inspection_does_not_commit_or_push(repositories):
    """Inspection reports unpublished edits while preserving both repository heads."""

    source, remote, _temporary = repositories
    original = git(remote, "rev-parse", "main")
    (source / "dot_settings").write_text("edited\n")
    state = synchronize_git(str(source))["state"]
    assert state["needs_publish"]
    assert "dot_settings" in state["status"]
    assert git(source, "rev-parse", "HEAD") == original
    assert git(remote, "rev-parse", "main") == original


def test_approved_publication_commits_and_verifies_remote(repositories):
    """Explicit publication commits local changes and verifies the remote copy."""

    source, remote, _temporary = repositories
    (source / "dot_settings").write_text("edited\n")
    (source / "new_settings").write_text("new\n")
    result = synchronize_git(str(source), action="publish")
    assert result["changed"]
    assert not result["state"]["needs_publish"]
    assert result["state"]["remote_verified"]
    assert git(source, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert git(remote, "show", "main:new_settings") == "new"
    assert git(source, "status", "--porcelain") == ""


def test_existing_unpushed_commits_are_published_without_extra_commit(repositories):
    """Publishing existing commits must not create an unnecessary extra commit."""

    source, remote, _temporary = repositories
    (source / "dot_settings").write_text("edited\n")
    git(source, "commit", "-am", "User commit")
    head = git(source, "rev-parse", "HEAD")
    assert synchronize_git(str(source))["state"]["ahead"] == 1
    assert synchronize_git(str(source), action="publish")["changed"]
    assert git(remote, "rev-parse", "main") == head


@pytest.mark.parametrize("diverged", [False, True])
def test_behind_or_diverged_inspection_reports_but_publication_refuses(repositories, diverged):
    """Upstream changes are reported without allowing an unsafe publication."""

    source = advance_remote(repositories)
    if diverged:
        (source / "dot_settings").write_text("local\n")
        git(source, "commit", "-am", "Local")
    head = git(source, "rev-parse", "HEAD")
    state = synchronize_git(str(source))["state"]
    assert state["behind"] == 1
    assert state["ahead"] == int(diverged)
    with pytest.raises(ValueError, match="behind or diverged"):
        synchronize_git(str(source), action="publish")
    assert git(source, "rev-parse", "HEAD") == head


def test_dry_run_does_not_fetch_commit_or_push(repositories):
    """A preview uses local tracking state and performs no network or write operations."""

    source, remote, _temporary = repositories
    original = git(source, "rev-parse", "HEAD")
    remote.rename(remote.with_name("unavailable.git"))
    (source / "dot_settings").write_text("edited\n")
    result = synchronize_git(str(source), dry_run=True, action="publish")
    assert not result["changed"]
    assert not result["state"]["remote_verified"]
    assert result["state"]["needs_publish"]
    assert not (source / ".git/FETCH_HEAD").exists()
    assert git(source, "rev-parse", "HEAD") == original
    with pytest.raises(ValueError, match="Could not fetch"):
        synchronize_git(str(source))


@pytest.mark.parametrize("unusable", ["no_upstream", "detached"])
def test_unpublished_or_detached_checkout_fails_clearly(repositories, unusable):
    """A checkout without a usable tracking branch cannot pass recovery checks."""

    source = repositories[0]
    if unusable == "no_upstream":
        git(source, "branch", "--unset-upstream")
        message = "no upstream"
    else:
        git(source, "checkout", "--detach")
        message = "detached HEAD"
    with pytest.raises(ValueError, match=message):
        synchronize_git(str(source))


def test_deleted_remote_branch_does_not_pass_via_stale_tracking_ref(repositories):
    """Cached tracking refs cannot hide the removal of the recovery branch."""

    source, remote, _temporary = repositories
    git(remote, "update-ref", "-d", "refs/heads/main")
    assert git(source, "rev-parse", "origin/main")
    with pytest.raises(ValueError, match="Could not fetch"):
        synchronize_git(str(source))


def test_rejected_push_keeps_local_commit_and_fails_backup(repositories):
    """A failed push preserves local work and cannot report a successful backup."""

    source, remote, _temporary = repositories
    original = git(remote, "rev-parse", "main")
    hook = remote / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    (source / "dot_settings").write_text("edited\n")
    with pytest.raises(ValueError, match="Could not push"):
        synchronize_git(str(source), action="publish")
    assert git(remote, "rev-parse", "main") == original
    assert git(source, "rev-parse", "HEAD") != original
    assert synchronize_git(str(source))["state"]["ahead"] == 1


def test_publication_uses_tracking_branch_when_local_name_differs(repositories):
    """Publication follows the configured remote branch rather than the local name."""

    source, remote, _temporary = repositories
    git(source, "branch", "-m", "workstation")
    (source / "dot_settings").write_text("edited\n")
    state = synchronize_git(str(source), action="publish")["state"]
    assert state["branch"] == "workstation"
    assert state["upstream"] == "origin/main"
    assert git(source, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert git(remote, "branch", "--list", "workstation") == ""


def test_github_token_is_scoped_in_environment_and_absent_from_arguments(repositories, monkeypatch):
    """GitHub credentials are passed through scoped configuration, never arguments."""

    source = repositories[0]
    original_run = subprocess.run
    calls = []

    def record_run(arguments, *, check, **kwargs):
        calls.append((arguments, kwargs["env"]))
        return original_run(arguments, check=check, **kwargs)

    monkeypatch.setattr(subprocess, "run", record_run)
    token = "synthetic-test-token"
    synchronize_git(str(source), github_token=token)
    assert calls
    for arguments, environment in calls:
        assert token not in " ".join(arguments)
        assert environment["GIT_CONFIG_COUNT"] == "1"
        assert environment["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
        assert environment["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
        assert environment["GIT_TERMINAL_PROMPT"] == "0"


@pytest.mark.parametrize("local_state", ["clean", "committed", "dirty"])
def test_approved_merge_preserves_both_histories_without_publishing(repositories, local_state):
    """Reconciliation incorporates upstream, saves local edits, and waits for publication."""

    source, remote, _temporary = repositories
    original = git(source, "rev-parse", "HEAD")
    advance_remote(repositories)
    upstream = git(remote, "rev-parse", "main")
    if local_state != "clean":
        (source / "dot_settings").write_text("local\n")
        if local_state == "committed":
            git(source, "commit", "-am", "Local")
            original = git(source, "rev-parse", "HEAD")
        else:
            (source / "untracked_settings").write_text("preserved\n")
    # Global preferences must not prevent a fast-forward or launch an editor.
    git(source, "config", "merge.ff", "false")
    git(source, "config", "core.editor", "false")
    result = synchronize_git(str(source), action="merge")
    assert result["changed"]
    assert result["state"]["behind"] == 0
    assert result["state"]["needs_publish"] == (local_state != "clean")
    assert result["state"]["status"] == ""
    assert git(remote, "rev-parse", "main") == upstream
    assert git(source, "merge-base", "HEAD", original) == original
    assert git(source, "merge-base", "HEAD", upstream) == upstream
    assert (source / "remote_settings").read_text() == "upstream\n"
    if local_state == "clean":
        assert git(source, "rev-parse", "HEAD") == upstream
    else:
        assert (source / "dot_settings").read_text() == "local\n"
        if local_state == "dirty":
            assert git(source, "show", "HEAD:untracked_settings") == "preserved"
        assert synchronize_git(str(source), action="publish")["changed"]
        assert git(remote, "rev-parse", "main") == git(source, "rev-parse", "HEAD")
    assert not synchronize_git(str(source), action="merge")["changed"]


def test_merge_conflict_preserves_local_edits_and_requires_manual_resolution(repositories):
    """Conflicts cannot be silently committed or published by a subsequent backup."""

    source, remote, temporary = repositories
    advance_remote(repositories)
    peer = temporary / "peer"
    (peer / "dot_settings").write_text("upstream conflicting edit\n")
    git(peer, "commit", "-am", "Upstream conflict")
    git(peer, "push")
    upstream = git(remote, "rev-parse", "main")
    (source / "dot_settings").write_text("local conflicting edit\n")
    with pytest.raises(git_sync.GitSyncError, match="git merge --abort") as failure:
        synchronize_git(str(source), action="merge")
    assert failure.value.changed
    assert git(remote, "rev-parse", "main") == upstream
    assert git(source, "show", "HEAD:dot_settings") == "local conflicting edit"
    assert git(source, "diff", "--name-only", "--diff-filter=U") == "dot_settings"
    # Even staged conflict resolution must not silently finish an ongoing merge.
    (source / "dot_settings").write_text("manual resolution\n")
    git(source, "add", "dot_settings")
    for action in ("inspect", "merge", "publish"):
        with pytest.raises(git_sync.GitSyncError, match="unfinished Git operation") as failure:
            synchronize_git(str(source), action=action)
        assert not failure.value.changed
    git(source, "merge", "--abort")
    assert (source / "dot_settings").read_text() == "local conflicting edit\n"
    assert git(source, "status", "--porcelain") == ""


def test_dry_run_merge_leaves_tracking_refs_index_and_worktree_untouched(repositories):
    """Even a requested merge is read-only in check mode, with no network access."""

    source, remote, _temporary = repositories
    advance_remote(repositories)
    synchronize_git(str(source))
    original = git(source, "rev-parse", "HEAD")
    fetch_head = (source / ".git/FETCH_HEAD").read_bytes()
    (source / "dot_settings").write_text("local\n")
    index = (source / ".git/index").read_bytes()
    remote.rename(remote.with_name("unavailable.git"))
    result = synchronize_git(str(source), action="merge", dry_run=True)
    assert not result["changed"]
    assert result["state"]["behind"] == 1
    assert not result["state"]["remote_verified"]
    assert git(source, "rev-parse", "HEAD") == original
    assert (source / ".git/FETCH_HEAD").read_bytes() == fetch_head
    assert (source / ".git/index").read_bytes() == index
    assert (source / "dot_settings").read_text() == "local\n"


def test_merge_without_remote_drift_does_not_commit_local_edits(repositories):
    """A stale reconciliation choice must not save edits when no merge is needed."""

    source = repositories[0]
    original = git(source, "rev-parse", "HEAD")
    (source / "dot_settings").write_text("local\n")
    assert not synchronize_git(str(source), action="merge")["changed"]
    assert git(source, "rev-parse", "HEAD") == original
    assert (source / "dot_settings").read_text() == "local\n"


def test_unknown_action_is_rejected(repositories):
    """Approving reconciliation cannot implicitly approve publication."""

    with pytest.raises(ValueError, match="Choose one Git action"):
        synchronize_git(str(repositories[0]), action="merge-and-publish")


def test_remote_update_during_merge_requires_another_decision(repositories):
    """A merge cannot report completion when its upstream advances again."""

    source, remote, temporary = repositories
    advance_remote(repositories)
    peer = temporary / "peer"

    def update_remote_after_merge(arguments, *, environ_update):
        result = run_command(arguments, environ_update=environ_update)
        if arguments[3] == "merge":
            (peer / "remote_settings").write_text("new upstream\n")
            git(peer, "commit", "-am", "Concurrent change")
            git(peer, "push")
        return result

    with pytest.raises(git_sync.GitSyncError, match="changed during reconciliation") as failure:
        git_sync.synchronize_git(str(source), action="merge", run_command=update_remote_after_merge)
    assert failure.value.changed
    assert git(source, "rev-parse", "HEAD") != git(remote, "rev-parse", "main")
    assert (source / "remote_settings").read_text() == "upstream\n"


@pytest.mark.parametrize("behind", [False, True])
def test_use_remote_discards_local_commits_edits_and_untracked_files(repositories, behind):
    """Remote replacement works for ahead-only and diverged branches without a push."""

    source, remote, _temporary = repositories
    if behind:
        advance_remote(repositories)
    upstream = git(remote, "rev-parse", "main")
    (source / "dot_settings").write_text("local commit\n")
    git(source, "commit", "-am", "Local")
    (source / "dot_settings").write_text("staged\n")
    git(source, "add", ".")
    (source / "dot_settings").write_text("unstaged\n")
    (source / "untracked").mkdir()
    (source / "untracked/file").write_text("discard\n")
    (source / ".git/info/exclude").write_text("ignored\n")
    (source / "ignored").write_text("preserve\n")
    result = synchronize_git(str(source), action="use-remote")
    assert result["changed"]
    assert not result["state"]["needs_publish"]
    assert result["state"]["behind"] == 0
    assert git(source, "rev-parse", "HEAD") == upstream
    assert git(remote, "rev-parse", "main") == upstream
    assert (source / "dot_settings").read_text() == "initial\n"
    assert not (source / "untracked").exists()
    assert (source / "ignored").read_text() == "preserve\n"
    assert git(source, "stash", "list") == ""
    assert not synchronize_git(str(source), action="use-remote")["changed"]


def test_use_remote_dry_run_preserves_every_local_change(repositories):
    """A requested discard cannot mutate files, commits, or refs in check mode."""

    source, remote, _temporary = repositories
    advance_remote(repositories)
    synchronize_git(str(source))
    (source / "dot_settings").write_text("local commit\n")
    git(source, "commit", "-am", "Local")
    original = git(source, "rev-parse", "HEAD")
    (source / "untracked").write_text("local file\n")
    fetch_head = (source / ".git/FETCH_HEAD").read_bytes()
    remote.rename(remote.with_name("unavailable.git"))
    result = synchronize_git(str(source), action="use-remote", dry_run=True)
    assert not result["changed"]
    assert not result["state"]["remote_verified"]
    assert git(source, "rev-parse", "HEAD") == original
    assert (source / "untracked").read_text() == "local file\n"
    assert (source / ".git/FETCH_HEAD").read_bytes() == fetch_head


def test_use_remote_preserves_ignored_files_that_remote_would_overwrite(repositories):
    """Reset must not destroy ignored local data when upstream starts tracking its path."""

    source = advance_remote(repositories)
    original = git(source, "rev-parse", "HEAD")
    (source / ".git/info/exclude").write_text("remote_settings\n")
    (source / "remote_settings").write_text("ignored local data\n")
    with pytest.raises(git_sync.GitSyncError, match="overwrite ignored") as failure:
        synchronize_git(str(source), action="use-remote")
    assert not failure.value.changed
    assert git(source, "rev-parse", "HEAD") == original
    assert (source / "remote_settings").read_text() == "ignored local data\n"


def test_use_remote_refuses_nested_repositories_before_discarding_anything(repositories):
    """A nested checkout must not be removed or hidden by a source reset."""

    source = advance_remote(repositories)
    original = git(source, "rev-parse", "HEAD")
    nested = source / "nested"
    nested.mkdir()
    git(nested, "init", "--initial-branch=main")
    (source / "dot_settings").write_text("preserve\n")
    with pytest.raises(git_sync.GitSyncError, match="nested Git repository") as failure:
        synchronize_git(str(source), action="use-remote")
    assert not failure.value.changed
    assert git(source, "rev-parse", "HEAD") == original
    assert (source / "dot_settings").read_text() == "preserve\n"
    assert (nested / ".git").is_dir()


def test_use_remote_does_not_clean_files_exposed_by_new_ignore_rules(repositories):
    """Removing upstream ignore rules cannot delete previously ignored user data."""

    source, _remote, temporary = repositories
    (source / ".gitignore").write_text("private-data\n")
    git(source, "add", ".")
    git(source, "commit", "-m", "Ignore private data")
    git(source, "push")
    advance_remote(repositories)
    peer = temporary / "peer"
    git(peer, "rm", ".gitignore")
    git(peer, "commit", "-m", "Remove ignore rule")
    git(peer, "push")
    (source / "private-data").write_text("preserve\n")
    with pytest.raises(git_sync.GitSyncError, match="replacement is incomplete") as failure:
        synchronize_git(str(source), action="use-remote")
    assert failure.value.changed
    assert (source / "private-data").read_text() == "preserve\n"


@pytest.mark.parametrize("location", ["source", "upstream"])
def test_use_remote_refuses_submodules_on_either_side(repositories, location):
    """A source reset must not delete or replace another managed repository."""

    source, remote, temporary = repositories
    advance_remote(repositories)
    owner = source if location == "source" else temporary / "peer"
    git(owner, "-c", "protocol.file.allow=always", "submodule", "add", str(remote), "nested")
    git(owner, "commit", "-m", "Add submodule")
    if location == "upstream":
        git(owner, "push")
    original = git(source, "rev-parse", "HEAD")
    (source / "dot_settings").write_text("preserve\n")
    with pytest.raises(git_sync.GitSyncError, match="submodules") as failure:
        synchronize_git(str(source), action="use-remote")
    assert not failure.value.changed
    assert git(source, "rev-parse", "HEAD") == original
    assert (source / "dot_settings").read_text() == "preserve\n"
