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
    result = synchronize_git(str(source), publish=True)
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
    assert synchronize_git(str(source), publish=True)["changed"]
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
        synchronize_git(str(source), publish=True)
    assert git(source, "rev-parse", "HEAD") == head


def test_dry_run_does_not_fetch_commit_or_push(repositories):
    """A preview uses local tracking state and performs no network or write operations."""

    source, remote, _temporary = repositories
    original = git(source, "rev-parse", "HEAD")
    remote.rename(remote.with_name("unavailable.git"))
    (source / "dot_settings").write_text("edited\n")
    result = synchronize_git(str(source), dry_run=True, publish=True)
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
        synchronize_git(str(source), publish=True)
    assert git(remote, "rev-parse", "main") == original
    assert git(source, "rev-parse", "HEAD") != original
    assert synchronize_git(str(source))["state"]["ahead"] == 1


def test_publication_uses_tracking_branch_when_local_name_differs(repositories):
    """Publication follows the configured remote branch rather than the local name."""

    source, remote, _temporary = repositories
    git(source, "branch", "-m", "workstation")
    (source / "dot_settings").write_text("edited\n")
    state = synchronize_git(str(source), publish=True)["state"]
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
