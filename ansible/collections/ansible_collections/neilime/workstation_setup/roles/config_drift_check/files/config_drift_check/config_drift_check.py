"""Report drift between the workstation and its managed workstation-config source.

The check is read-only and privilege-free so it can run unattended on a user
timer. It inspects the Chezmoi-managed dotfiles for local changes and, when the
network and credentials allow, whether the Chezmoi source is behind its upstream.
No file contents are emitted because managed templates can hold sensitive data;
only counts and branch state are reported.
"""

# This helper is installed standalone per role and deliberately mirrors the
# git_project_report scanner structure, so cross-file similarity is expected.
# pylint: disable=duplicate-code

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

GIT_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ConfigDriftReport:
    """The aggregated drift result for the managed workstation configuration."""

    # A drift report aggregates several independent signals (local changes and the
    # separate upstream comparison); grouping them would obscure the flat result.
    # pylint: disable=too-many-instance-attributes
    chezmoi_available: bool
    source_directory: str | None = None
    local_change_count: int = 0
    remote_checked: bool = False
    behind: int = 0
    ahead: int = 0
    upstream: str | None = None
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        """Return whether an actionable difference from the managed source exists."""

        return self.local_change_count > 0 or (self.remote_checked and self.behind > 0)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chezmoi-bin",
        default="chezmoi",
        help="Path to the chezmoi executable (defaults to the one on PATH).",
    )
    parser.add_argument(
        "--source-dir",
        default="",
        help="Chezmoi source directory; inspected directly when provided.",
    )
    parser.add_argument(
        "--chezmoi-config",
        default="",
        help="Chezmoi configuration file passed through to chezmoi.",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Save the report and show a clickable desktop notification when drift is found.",
    )
    parser.add_argument(
        "--action",
        action="append",
        nargs=2,
        default=[],
        metavar=("LABEL", "COMMAND"),
        help="Add a proposed notification action; LABEL is the button text and COMMAND runs in a terminal.",
    )
    return parser.parse_args(argv)


def run_command(argv: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its text result without raising on failure."""

    return subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def resolve_chezmoi(chezmoi_bin: str) -> str | None:
    """Return the absolute chezmoi executable path, or None when it is missing."""

    resolved = shutil.which(chezmoi_bin)
    if resolved:
        return resolved
    candidate = Path(chezmoi_bin)
    if candidate.is_file():
        return str(candidate)
    return None


def build_chezmoi_command(chezmoi: str, source_dir: str, config: str) -> list[str]:
    """Return the chezmoi base command that matches the managed invocation."""

    command = [chezmoi]
    if config:
        command.extend(["--config", config])
    if source_dir:
        command.extend(["--source", source_dir])
    command.extend(["--no-pager", "--no-tty"])
    return command


def inspect_local_changes(chezmoi_command: Sequence[str], errors: list[str]) -> int:
    """Return the number of managed paths that differ from the source."""

    result = run_command([*chezmoi_command, "status", "--path-style", "relative"])
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "chezmoi status failed"
        errors.append(f"chezmoi status: {message}")
        return 0
    return len([line for line in result.stdout.splitlines() if line.strip()])


def resolve_source_directory(chezmoi_command: Sequence[str], source_dir: str, errors: list[str]) -> Path | None:
    """Return the Chezmoi source directory, or None when it cannot be resolved."""

    source = source_dir
    if not source:
        result = run_command([*chezmoi_command, "source-path"])
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "chezmoi source-path failed"
            errors.append(f"chezmoi source-path: {message}")
            return None
        source = result.stdout.strip()
    if not source:
        return None
    source_path = Path(source)
    if not source_path.is_dir():
        return None
    return source_path


def inspect_upstream_state(source_directory: Path, notes: list[str]) -> tuple[bool, int, int, str | None]:
    """Return (remote_checked, behind, ahead, upstream) for the source directory.

    A best-effort fetch keeps the comparison meaningful for private repositories
    without failing the unattended check when the network or credentials are absent.
    """

    upstream_result = run_command(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        cwd=source_directory,
    )
    if upstream_result.returncode != 0:
        notes.append("Source has no upstream branch; remote comparison skipped.")
        return False, 0, 0, None
    upstream = upstream_result.stdout.strip() or None

    fetch_result = run_command(["git", "fetch", "--quiet"], cwd=source_directory)
    if fetch_result.returncode != 0:
        notes.append("Could not refresh the source from its remote; showing the last known state.")

    count_result = run_command(
        ["git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"],
        cwd=source_directory,
    )
    if count_result.returncode != 0:
        notes.append("Could not compare the source with its upstream branch.")
        return False, 0, 0, upstream

    parts = count_result.stdout.split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        notes.append("Unexpected branch comparison output; remote comparison skipped.")
        return False, 0, 0, upstream

    behind, ahead = int(parts[0]), int(parts[1])
    return True, behind, ahead, upstream


def scan_config_drift(chezmoi_bin: str, source_dir: str = "", config: str = "") -> ConfigDriftReport:
    """Inspect the managed configuration and return an aggregated drift report."""

    chezmoi = resolve_chezmoi(chezmoi_bin)
    if chezmoi is None:
        return ConfigDriftReport(
            chezmoi_available=False,
            notes=["Chezmoi is not installed; run setup to manage dotfiles first."],
        )

    errors: list[str] = []
    notes: list[str] = []
    chezmoi_command = build_chezmoi_command(chezmoi, source_dir, config)
    local_change_count = inspect_local_changes(chezmoi_command, errors)

    source_directory = resolve_source_directory(chezmoi_command, source_dir, errors)
    remote_checked = False
    behind = ahead = 0
    upstream: str | None = None
    if source_directory is not None:
        remote_checked, behind, ahead, upstream = inspect_upstream_state(source_directory, notes)

    return ConfigDriftReport(
        chezmoi_available=True,
        source_directory=str(source_directory) if source_directory is not None else None,
        local_change_count=local_change_count,
        remote_checked=remote_checked,
        behind=behind,
        ahead=ahead,
        upstream=upstream,
        notes=notes,
        errors=errors,
    )


def render_report(report: ConfigDriftReport) -> str:
    """Render a human-readable drift report without exposing file contents."""

    lines = ["Workstation configuration drift report"]

    if not report.chezmoi_available:
        lines.extend(report.notes)
        return "\n".join(lines)

    if report.source_directory:
        lines.append(f"Managed source: {report.source_directory}")
    if report.upstream:
        lines.append(f"Tracking: {report.upstream}")

    if report.local_change_count > 0:
        file_label = "file" if report.local_change_count == 1 else "files"
        lines.append(f"{report.local_change_count} managed {file_label} differ from the configuration source.")
    else:
        lines.append("Managed files match the configuration source.")

    if report.remote_checked:
        if report.behind > 0:
            commit_label = "commit" if report.behind == 1 else "commits"
            lines.append(f"The configuration source is {report.behind} {commit_label} behind its upstream.")
        else:
            lines.append("The configuration source is up to date with its upstream.")
        if report.ahead > 0:
            commit_label = "commit" if report.ahead == 1 else "commits"
            lines.append(f"The source has {report.ahead} unpublished {commit_label}; run backup to save them.")

    for note in report.notes:
        lines.append(f"Note: {note}")

    if report.errors:
        lines.append("")
        lines.append("Scan errors:")
        lines.extend(f"- {error}" for error in report.errors)

    return "\n".join(lines)


def build_notification(report: ConfigDriftReport) -> tuple[str, str]:
    """Build the notification title and body for a drifted configuration."""

    reasons: list[str] = []
    if report.local_change_count > 0:
        file_label = "file" if report.local_change_count == 1 else "files"
        reasons.append(f"{report.local_change_count} local {file_label} changed")
    if report.remote_checked and report.behind > 0:
        commit_label = "update" if report.behind == 1 else "updates"
        reasons.append(f"{report.behind} published {commit_label}")

    title = "Workstation configuration drift detected"
    body_lines = [
        "Your workstation differs from its managed configuration: " + ", ".join(reasons) + ".",
        "Run setup to apply the managed configuration, or preview the changes first.",
    ]
    return title, "\n".join(body_lines)


def send_notification(report: ConfigDriftReport, actions: Sequence[Sequence[str]]) -> int:
    """Save the report and send a notification with persistent proposed actions."""

    title, body = build_notification(report)
    command = [
        "/usr/bin/python3",
        str(Path(__file__).with_name("config_drift_notification.py")),
        "--notify",
        title,
        body,
    ]
    for label, action_command in actions:
        command.extend(["--action", label, action_command])

    notify_result = subprocess.run(
        command,
        input=render_report(report) + "\n",
        check=False,
        capture_output=True,
        text=True,
    )
    if notify_result.returncode == 0:
        return 0

    message = notify_result.stderr.strip() or notify_result.stdout.strip() or "Config drift notification failed"
    print(message, file=sys.stderr)
    return notify_result.returncode


def main(argv: Sequence[str]) -> int:
    """Run the configuration drift check."""

    arguments = parse_args(argv)
    report = scan_config_drift(arguments.chezmoi_bin, arguments.source_dir, arguments.chezmoi_config)
    print(render_report(report))

    if not arguments.notify or not report.has_drift:
        return 0

    return send_notification(report, arguments.action)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
