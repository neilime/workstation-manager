"""Unit tests for the managed Git project report helper script."""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
from types import ModuleType

SCRIPT_PATH = (
    pathlib.Path(__file__).parents[4]
    / "roles"
    / "development_tooling"
    / "files"
    / "git_project_report"
    / "git_project_report.py"
)


def load_script_module() -> ModuleType:
    """Import the helper script as a Python module for unit testing."""

    spec = importlib.util.spec_from_file_location("git_project_report_script", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load the Git project report helper script")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_git(repository_root: pathlib.Path, *arguments: str) -> None:
    """Run a Git command with a stable test identity."""

    subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "Workstation Manager",
            "GIT_AUTHOR_EMAIL": "workstation-manager@example.test",
            "GIT_COMMITTER_NAME": "Workstation Manager",
            "GIT_COMMITTER_EMAIL": "workstation-manager@example.test",
        },
    )


def initialize_repository(repository_root: pathlib.Path) -> None:
    """Create a repository with one committed file."""

    repository_root.mkdir(parents=True)
    run_git(repository_root, "init", "--initial-branch=main")
    (repository_root / "tracked.txt").write_text("base\n", encoding="utf-8")
    run_git(repository_root, "add", "tracked.txt")
    run_git(repository_root, "commit", "-m", "Initial commit")


def test_discover_git_repositories_finds_git_directories_and_files(tmp_path) -> None:
    """Repository discovery should support standard repos and worktree-style .git files."""

    module = load_script_module()
    standard_repo = tmp_path / "standard"
    worktree_repo = tmp_path / "worktree"
    standard_repo.mkdir()
    worktree_repo.mkdir()
    (standard_repo / ".git").mkdir()
    (worktree_repo / ".git").write_text("gitdir: /tmp/example\n", encoding="utf-8")

    repositories = module.discover_git_repositories(tmp_path)

    assert repositories == [standard_repo, worktree_repo]


def test_scan_projects_directory_reports_only_dirty_repositories(tmp_path) -> None:
    """The scan should ignore clean repositories and keep local changes in the report."""

    module = load_script_module()
    clean_repository = tmp_path / "clean-project"
    dirty_repository = tmp_path / "dirty-project"
    initialize_repository(clean_repository)
    initialize_repository(dirty_repository)
    (dirty_repository / "tracked.txt").write_text("base\nlocal-change\n", encoding="utf-8")
    (dirty_repository / "notes.txt").write_text("scratch\n", encoding="utf-8")

    report = module.scan_projects_directory(tmp_path)

    assert report.repository_count == 2
    assert [repository.relative_path for repository in report.dirty_repositories] == ["dirty-project"]
    assert report.dirty_repositories[0].branch == "main"
    assert report.dirty_repositories[0].status_lines == [" M tracked.txt", "?? notes.txt"]
    assert report.errors == []


def test_render_report_mentions_missing_projects_directory(tmp_path) -> None:
    """A missing projects directory should render a readable message instead of failing."""

    module = load_script_module()
    report = module.scan_projects_directory(tmp_path / "missing-projects")

    assert module.render_report(report) == (
        f"Git project report for {(tmp_path / 'missing-projects').resolve()}\nProjects directory does not exist yet."
    )
