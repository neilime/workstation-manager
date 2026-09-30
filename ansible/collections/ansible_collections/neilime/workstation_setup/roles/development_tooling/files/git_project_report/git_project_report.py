"""Report Git repositories with local work in progress under a projects directory."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class RepositoryStatus:
    """A repository with local work in progress."""

    relative_path: str
    branch: str
    status_lines: list[str]

    @property
    def change_count(self) -> int:
        """Return the number of worktree changes reported by Git."""

        return len(self.status_lines)


@dataclass(frozen=True)
class ScanError:
    """A repository that could not be inspected cleanly."""

    relative_path: str
    message: str


@dataclass(frozen=True)
class ScanReport:
    """The complete scan result for a projects directory."""

    projects_directory: Path
    projects_directory_exists: bool
    repository_count: int
    dirty_repositories: list[RepositoryStatus]
    errors: list[ScanError]


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Scan a projects directory for Git repositories and report the "
            "repositories that still have local work in progress."
        )
    )
    parser.add_argument(
        "--projects-directory",
        required=True,
        help="Absolute path to the managed projects directory.",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Show the report summary through notify-send after printing it.",
    )
    return parser.parse_args(argv)


def display_path(relative_path: str) -> str:
    """Normalize the root-relative path shown in reports."""

    return "." if relative_path == "." else relative_path


def discover_git_repositories(projects_directory: Path) -> list[Path]:
    """Return repository roots that contain a Git directory or worktree file."""

    repository_roots: set[Path] = set()
    for current_root, directory_names, file_names in os.walk(projects_directory):
        if ".git" in directory_names or ".git" in file_names:
            repository_roots.add(Path(current_root))
        if ".git" in directory_names:
            directory_names.remove(".git")

    return sorted(repository_roots)


def run_git(repository_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run Git in a repository and capture the text result."""

    return subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def resolve_branch_name(repository_root: Path) -> str:
    """Return the symbolic branch name or a detached-HEAD label."""

    branch_result = run_git(repository_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch_result.returncode == 0:
        branch_name = branch_result.stdout.strip()
        if branch_name:
            return branch_name

    head_result = run_git(repository_root, "rev-parse", "--short", "HEAD")
    if head_result.returncode == 0:
        return f"detached@{head_result.stdout.strip()}"

    stderr = branch_result.stderr.strip() or head_result.stderr.strip() or "unknown Git error"
    raise RuntimeError(stderr)


def inspect_repository(repository_root: Path, projects_directory: Path) -> RepositoryStatus | ScanError | None:
    """Return a dirty repository, a scan error, or None for a clean repository."""

    relative_path = os.path.relpath(repository_root, projects_directory)
    status_result = run_git(repository_root, "status", "--porcelain", "--untracked-files=all")
    if status_result.returncode != 0:
        message = status_result.stderr.strip() or status_result.stdout.strip() or "git status failed"
        return ScanError(relative_path=relative_path, message=message)

    status_lines = [line for line in status_result.stdout.splitlines() if line]
    if not status_lines:
        return None

    try:
        branch_name = resolve_branch_name(repository_root)
    except RuntimeError as error:
        return ScanError(relative_path=relative_path, message=str(error))

    return RepositoryStatus(
        relative_path=relative_path,
        branch=branch_name,
        status_lines=status_lines,
    )


def scan_projects_directory(projects_directory: Path) -> ScanReport:
    """Scan a projects directory for repositories with work in progress."""

    resolved_projects_directory = projects_directory.expanduser().resolve()
    if not resolved_projects_directory.exists():
        return ScanReport(
            projects_directory=resolved_projects_directory,
            projects_directory_exists=False,
            repository_count=0,
            dirty_repositories=[],
            errors=[],
        )

    repository_roots = discover_git_repositories(resolved_projects_directory)
    dirty_repositories: list[RepositoryStatus] = []
    errors: list[ScanError] = []

    for repository_root in repository_roots:
        inspection = inspect_repository(repository_root, resolved_projects_directory)
        if inspection is None:
            continue
        if isinstance(inspection, ScanError):
            errors.append(inspection)
            continue
        dirty_repositories.append(inspection)

    dirty_repositories.sort(key=lambda repository: repository.relative_path)
    errors.sort(key=lambda error: error.relative_path)

    return ScanReport(
        projects_directory=resolved_projects_directory,
        projects_directory_exists=True,
        repository_count=len(repository_roots),
        dirty_repositories=dirty_repositories,
        errors=errors,
    )


def render_report(report: ScanReport) -> str:
    """Render the terminal-friendly report text."""

    lines = [f"Git project report for {report.projects_directory}"]

    if not report.projects_directory_exists:
        lines.append("Projects directory does not exist yet.")
        return "\n".join(lines)

    if report.repository_count == 0:
        lines.append("No Git repositories found.")
        return "\n".join(lines)

    if report.dirty_repositories:
        lines.append(
            f"{len(report.dirty_repositories)} of {report.repository_count} "
            "Git repositories have local work in progress."
        )
        for repository in report.dirty_repositories:
            lines.append("")
            lines.append(f"- {display_path(repository.relative_path)} [{repository.branch}]")
            for status_line in repository.status_lines:
                lines.append(f"  {status_line}")
    else:
        lines.append(f"All {report.repository_count} Git repositories are clean.")

    if report.errors:
        lines.append("")
        lines.append("Scan errors:")
        for error in report.errors:
            lines.append(f"- {display_path(error.relative_path)}: {error.message}")

    return "\n".join(lines)


def build_notification(report: ScanReport) -> tuple[str, str]:
    """Build the notification title and body."""

    if not report.projects_directory_exists:
        return (
            "Git project report: projects directory missing",
            str(report.projects_directory),
        )

    if report.repository_count == 0:
        return (
            "Git project report: no repositories found",
            str(report.projects_directory),
        )

    if not report.dirty_repositories and not report.errors:
        return (
            "Git project report: all clean",
            f"All {report.repository_count} repositories are clean.",
        )

    title_parts: list[str] = []
    if report.dirty_repositories:
        title_parts.append(f"{len(report.dirty_repositories)} repos with work in progress")
    else:
        title_parts.append("no work in progress")
    if report.errors:
        title_parts.append(f"{len(report.errors)} scan errors")

    body_lines: list[str] = []
    for repository in report.dirty_repositories[:5]:
        body_lines.append(
            f"{display_path(repository.relative_path)} [{repository.branch}] - {repository.change_count} changes"
        )
    remaining_repositories = len(report.dirty_repositories) - min(len(report.dirty_repositories), 5)
    if remaining_repositories > 0:
        body_lines.append(f"+{remaining_repositories} more repositories")

    for error in report.errors[:3]:
        body_lines.append(f"{display_path(error.relative_path)} - {error.message}")
    remaining_errors = len(report.errors) - min(len(report.errors), 3)
    if remaining_errors > 0:
        body_lines.append(f"+{remaining_errors} more scan errors")

    return (
        f"Git project report: {', '.join(title_parts)}",
        "\n".join(body_lines),
    )


def send_notification(report: ScanReport) -> int:
    """Send the summary through notify-send."""

    title, body = build_notification(report)
    notify_result = subprocess.run(
        [
            "notify-send",
            "--app-name=workstation-manager",
            "--expire-time=15000",
            title,
            body,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if notify_result.returncode == 0:
        return 0

    message = notify_result.stderr.strip() or notify_result.stdout.strip() or "notify-send failed"
    print(message, file=sys.stderr)
    return notify_result.returncode


def main(argv: Sequence[str]) -> int:
    """Run the report command."""

    arguments = parse_args(argv)
    report = scan_projects_directory(Path(arguments.projects_directory))
    print(render_report(report))

    if not arguments.notify:
        return 0

    return send_notification(report)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
