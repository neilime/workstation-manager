"""Exercise Git inventory discovery against disposable project repositories."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from ansible_collections.neilime.workstation_backup.plugins.module_utils import (
    git_inventory,
)


def run_command(arguments: list[str], *, environ_update: dict[str, str]) -> tuple[int, str, str]:
    """Run local read-only probes with the same environment overrides as Ansible."""

    result = subprocess.run(
        arguments, env={**os.environ, **environ_update}, check=False, capture_output=True, text=True
    )
    return result.returncode, result.stdout, result.stderr


def git(repository: Path, *arguments: str) -> str:
    """Run Git only inside a temporary fixture."""

    result = subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def create_repository(repository: Path, *, empty: bool = False) -> None:
    """Create a repository whose inventory reads never need network access."""

    repository.mkdir(parents=True)
    git(repository, "init", "--initial-branch=main")
    if not empty:
        (repository / "README.md").write_text("fixture\n")
        git(repository, "add", "README.md")
        git(
            repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "Initial"
        )


@pytest.fixture(name="projects")
def projects_fixture(tmp_path, monkeypatch) -> Path:
    """Isolate ignore configuration and all Git state from the developer's account."""

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    projects = tmp_path / "projects with spaces"
    projects.mkdir()
    return projects


@pytest.mark.parametrize("ignore_source", [".gitignore", "tools/.gitignore", ".git/info/exclude", "global"])
def test_ignored_dependency_repositories_are_skipped(projects, ignore_source):
    """Ignore rules must omit even empty dependency checkouts before metadata reads."""

    repository = projects / "open-source/twbs-helper-module"
    create_repository(repository)
    ignore_file = repository / ignore_source
    if ignore_source == "global":
        ignore_file = projects / "global-ignore"
        git(repository, "config", "core.excludesFile", str(ignore_file))
    ignore_file.parent.mkdir(parents=True, exist_ok=True)
    ignore_file.write_text("vendor/\n" if ignore_source == "tools/.gitignore" else "tools/vendor/\n")
    create_repository(repository / "tools/vendor/phpstan/extension-installer", empty=True)
    inventory = git_inventory.GitRepositoryInventoryBuilder(run_command).build(str(projects))
    assert [record["relative_path"] for record in inventory] == ["open-source/twbs-helper-module"]


def test_visible_nested_projects_and_ignore_negation_are_preserved(projects):
    """Nested checkouts stay eligible when Git says their root is not ignored."""

    repository = projects / "parent"
    create_repository(repository)
    (repository / ".gitignore").write_text("tools/vendor/*\n!tools/vendor/keep/\n")
    create_repository(repository / "tools/vendor/skip", empty=True)
    create_repository(repository / "tools/vendor/keep")
    create_repository(repository / "tools/independent project")
    create_repository(projects / "vendor/standalone")
    inventory = git_inventory.GitRepositoryInventoryBuilder(run_command).build(str(projects))
    assert [record["relative_path"] for record in inventory] == [
        "parent",
        "parent/tools/independent project",
        "parent/tools/vendor/keep",
        "vendor/standalone",
    ]


def test_repository_metadata_and_local_changes_are_preserved_without_mutation(projects):
    """The inventory retains its recovery schema and does not refresh the Git index."""

    repository = projects / "project"
    create_repository(repository)
    git(repository, "remote", "add", "upstream", "https://example.invalid/upstream.git")
    git(repository, "remote", "add", "origin", "https://example.invalid/project.git")
    (repository / "README.md").write_text("local modification\n")
    (repository / "local-note.txt").write_text("untracked fixture\n")
    head = git(repository, "rev-parse", "HEAD")
    index = (repository / ".git/index").read_bytes()
    inventory = git_inventory.GitRepositoryInventoryBuilder(run_command).build(str(projects))
    assert inventory == [
        {
            "relative_path": "project",
            "root_path": str(repository),
            "head_commit": head,
            "branch": "main",
            "primary_remote_name": "origin",
            "primary_remote_url": "https://example.invalid/project.git",
            "remotes": [
                {"name": "origin", "url": "https://example.invalid/project.git"},
                {"name": "upstream", "url": "https://example.invalid/upstream.git"},
            ],
            "has_local_modifications": True,
            "status_lines": [" M README.md", "?? local-note.txt"],
        }
    ]
    assert git(repository, "rev-parse", "HEAD") == head
    assert (repository / ".git/index").read_bytes() == index


def test_detached_head_and_repositories_without_remotes_are_supported(projects):
    """A detached checkout remains recoverable without inventing a branch or remote."""

    repository = projects / "detached"
    create_repository(repository)
    git(repository, "checkout", "--detach")
    record = git_inventory.GitRepositoryInventoryBuilder(run_command).build(str(projects))[0]
    assert record["branch"] == ""
    assert record["remotes"] == []
    assert record["primary_remote_name"] == record["primary_remote_url"] == ""


def test_non_origin_remote_is_used_as_primary(projects):
    """Retain the existing fallback when there is no origin remote."""

    repository = projects / "project"
    create_repository(repository)
    git(repository, "remote", "add", "upstream", "https://example.invalid/project.git")
    record = git_inventory.GitRepositoryInventoryBuilder(run_command).build(str(projects))[0]
    assert record["remotes"] == [{"name": "upstream", "url": "https://example.invalid/project.git"}]
    assert record["primary_remote_name"] == "upstream"
    assert record["primary_remote_url"] == "https://example.invalid/project.git"


def test_discovery_does_not_follow_symlinks_or_scan_git_metadata(projects):
    """Linked directories and repositories hidden inside .git must not expand inventory scope."""

    repository = projects / "project"
    create_repository(repository)
    create_repository(repository / ".git/internal-repository")
    outside = projects.parent / "outside"
    create_repository(outside)
    (projects / "linked-project").symlink_to(outside, target_is_directory=True)
    inventory = git_inventory.GitRepositoryInventoryBuilder(run_command).build(str(projects))
    assert [record["relative_path"] for record in inventory] == ["project"]


def test_missing_projects_directory_produces_an_empty_inventory(projects):
    """A workstation without the default projects directory can still back up other sources."""

    assert git_inventory.GitRepositoryInventoryBuilder(run_command).build(str(projects / "missing")) == []


def test_invalid_projects_paths_fail(projects):
    """External paths must be absolute directories."""

    builder = git_inventory.GitRepositoryInventoryBuilder(run_command)
    with pytest.raises(ValueError, match="absolute path"):
        builder.build("relative/projects")
    file = projects / "file"
    file.write_text("fixture\n")
    with pytest.raises(ValueError, match="not a directory"):
        builder.build(str(file))


def test_ignore_check_failures_are_fatal_and_do_not_expose_diagnostics(projects):
    """Only Git's ignored and non-ignored exit codes may decide inventory coverage."""

    repository = projects / "parent"
    create_repository(repository)
    create_repository(repository / "child")

    def rejected_ignore_check(arguments, **options):
        if "check-ignore" in arguments:
            return 128, "synthetic-private-output", "synthetic-private-diagnostics"
        return run_command(arguments, **options)

    with pytest.raises(ValueError, match="Git check-ignore failed") as failure:
        git_inventory.GitRepositoryInventoryBuilder(rejected_ignore_check).build(str(projects))
    assert "synthetic-private" not in str(failure.value)


def test_directory_read_failures_are_fatal(projects, monkeypatch):
    """Discovery must not silently report an unreadable project tree as complete."""

    def unreadable_walk(_root, *, onerror, followlinks):
        assert not followlinks
        onerror(PermissionError("Cannot read fixture directory"))
        return iter(())

    monkeypatch.setattr(git_inventory.os, "walk", unreadable_walk)
    with pytest.raises(PermissionError, match="Cannot read fixture directory"):
        git_inventory.GitRepositoryInventoryBuilder(run_command).build(str(projects))
