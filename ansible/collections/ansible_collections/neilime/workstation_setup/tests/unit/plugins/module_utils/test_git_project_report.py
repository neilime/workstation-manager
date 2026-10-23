"""Unit tests for the managed Git project report helper script."""

from __future__ import annotations

import importlib.util
import pathlib
import stat
import subprocess
import sys
from types import ModuleType

import pytest

SCRIPT_PATH = (
    pathlib.Path(__file__).parents[4]
    / "roles"
    / "development_tooling"
    / "files"
    / "git_project_report"
    / "git_project_report.py"
)


def load_script_module(path=SCRIPT_PATH) -> ModuleType:
    """Import the helper script as a Python module for unit testing."""

    spec = importlib.util.spec_from_file_location(path.stem, path)
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


def test_render_report_uses_one_summary_line_per_dirty_repository(tmp_path) -> None:
    """Report size depends on dirty repository count, not the number of changed files."""
    module = load_script_module()
    report = module.ScanReport(
        projects_directory=tmp_path,
        projects_directory_exists=True,
        repository_count=3,
        dirty_repositories=[
            module.RepositoryStatus("team/small", "main", [" M tracked.txt"]),
            module.RepositoryStatus("team/large", "feature", [f"?? file-{index}.txt" for index in range(1000)]),
        ],
        errors=[],
    )

    assert module.render_report(report).splitlines() == [
        f"Git project report for {tmp_path}",
        "2 of 3 Git repositories have local changes.",
        "",
        "- team/small [main]: 1 changed file",
        "- team/large [feature]: 1000 changed files",
    ]


@pytest.mark.parametrize("has_local_changes", [False, True])
def test_render_report_preserves_scan_errors_without_claiming_all_clean(tmp_path, has_local_changes) -> None:
    """Inspection failures stay actionable even when no local changes were found."""
    module = load_script_module()
    report = module.ScanReport(
        projects_directory=tmp_path,
        projects_directory_exists=True,
        repository_count=3,
        dirty_repositories=[module.RepositoryStatus("changed", "main", [" M tracked.txt"])]
        if has_local_changes
        else [],
        errors=[module.ScanError("unreadable", "Permission denied")],
    )

    rendered = module.render_report(report)

    if has_local_changes:
        assert "1 of 3 Git repositories have local changes." in rendered
        assert "- changed [main]: 1 changed file" in rendered
    else:
        assert "No local changes found in 2 inspected Git repositories." in rendered
    assert rendered.endswith("\n\nScan errors:\n- unreadable: Permission denied")
    assert "are clean" not in rendered


def test_notification_failures_are_reported_to_the_caller(tmp_path, monkeypatch, capsys) -> None:
    """A notification failure must fail the scheduled command and explain the error."""
    module = load_script_module()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **_options: subprocess.CompletedProcess(command, 1, "", "Cannot save Git report\n"),
    )
    assert module.main(["--projects-directory", str(tmp_path / "missing"), "--notify"]) == 1
    output = capsys.readouterr()
    assert "Projects directory does not exist yet." in output.out
    assert output.err == "Cannot save Git report\n"


def test_saved_report_is_private_and_replaced_without_following_file_links(tmp_path) -> None:
    """Refreshing the saved report preserves other files and keeps report contents private."""
    module = load_script_module(SCRIPT_PATH.with_name("git_project_notification.py"))
    notifications = module.GitReportNotifications(tmp_path)
    notifications.save("First report\n")
    assert stat.S_IMODE(notifications.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(notifications.path.parent.stat().st_mode) == 0o700
    preserved = tmp_path / "unmanaged.txt"
    preserved.write_text("Preserved\n")
    notifications.path.unlink()
    notifications.path.symlink_to(preserved)
    notifications.save("Updated report\n")
    assert notifications.path.read_text() == "Updated report\n"
    assert not notifications.path.is_symlink()
    assert preserved.read_text() == "Preserved\n"
    assert sorted(path.name for path in notifications.path.parent.iterdir()) == ["latest.txt"]


def test_report_storage_rejects_a_symlinked_application_directory(tmp_path) -> None:
    """A managed report must not be published into a redirected storage directory."""
    module = load_script_module(SCRIPT_PATH.with_name("git_project_notification.py"))
    notifications = module.GitReportNotifications(tmp_path)
    notifications.path.parent.parent.mkdir()
    notifications.path.parent.symlink_to(tmp_path)
    with pytest.raises(ValueError, match="must not be a symlink"):
        notifications.save("Private report\n")
    assert not (tmp_path / "latest.txt").exists()
