"""Unit tests for the managed workstation configuration drift helper script."""

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
    / "config_drift_check"
    / "files"
    / "config_drift_check"
    / "config_drift_check.py"
)


def load_script_module(path=SCRIPT_PATH) -> ModuleType:
    """Import the helper script as a Python module for unit testing."""

    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load the configuration drift helper script")

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


def write_fake_chezmoi(path: pathlib.Path, status_lines: int) -> pathlib.Path:
    """Create a stand-in chezmoi executable returning a fixed number of status lines."""

    status_output = "".join(f" M dot_file_{index}\n" for index in range(status_lines))
    script = path / "chezmoi"
    script.write_text(
        "#!/bin/sh\n"
        "for argument in \"$@\"; do\n"
        "  case \"$argument\" in\n"
        f"    status) printf '%s' '{status_output}'; exit 0 ;;\n"
        "    source-path) printf '%s\\n' \"$FAKE_SOURCE\"; exit 0 ;;\n"
        "  esac\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def make_source_behind_upstream(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return a Chezmoi-style source checkout that is one commit behind its upstream."""

    remote = tmp_path / "remote.git"
    remote.mkdir()
    run_git(remote, "init", "--bare", "--initial-branch=main")

    source = tmp_path / "source"
    source.mkdir()
    run_git(source, "init", "--initial-branch=main")
    run_git(source, "remote", "add", "origin", str(remote))
    (source / "dot_file_0").write_text("base\n", encoding="utf-8")
    run_git(source, "add", "dot_file_0")
    run_git(source, "commit", "-m", "Initial commit")
    run_git(source, "push", "--set-upstream", "origin", "main")

    other = tmp_path / "other"
    other.mkdir()
    run_git(other, "clone", str(remote), ".")
    (other / "dot_file_1").write_text("remote\n", encoding="utf-8")
    run_git(other, "add", "dot_file_1")
    run_git(other, "commit", "-m", "Upstream update")
    run_git(other, "push", "origin", "main")

    return source


def test_has_drift_requires_local_change_or_remote_behind() -> None:
    """Drift is actionable only for local changes or a confirmed upstream gap."""

    module = load_script_module()
    assert module.ConfigDriftReport(chezmoi_available=True, local_change_count=1).has_drift
    assert module.ConfigDriftReport(chezmoi_available=True, remote_checked=True, behind=2).has_drift
    assert not module.ConfigDriftReport(chezmoi_available=True, behind=5).has_drift
    assert not module.ConfigDriftReport(chezmoi_available=True, remote_checked=True, ahead=3).has_drift


def test_scan_reports_missing_chezmoi_without_claiming_drift() -> None:
    """A missing chezmoi must be reported as an actionable note, not silent drift."""

    module = load_script_module()
    report = module.scan_config_drift("definitely-not-a-real-chezmoi-binary")

    assert report.chezmoi_available is False
    assert report.has_drift is False
    assert "Chezmoi is not installed" in module.render_report(report)


def test_scan_detects_local_changes_and_upstream_gap(tmp_path) -> None:
    """A populated source with a remote gap reports counts and upstream distance."""

    module = load_script_module()
    chezmoi = write_fake_chezmoi(tmp_path, status_lines=2)
    source = make_source_behind_upstream(tmp_path)

    report = module.scan_config_drift(str(chezmoi), source_dir=str(source))

    assert report.chezmoi_available is True
    assert report.local_change_count == 2
    assert report.remote_checked is True
    assert report.behind == 1
    assert report.ahead == 0
    assert report.has_drift is True


def test_scan_skips_remote_comparison_without_upstream(tmp_path) -> None:
    """A source without an upstream is annotated instead of reported as up to date."""

    module = load_script_module()
    chezmoi = write_fake_chezmoi(tmp_path, status_lines=0)
    source = tmp_path / "source"
    source.mkdir()
    run_git(source, "init", "--initial-branch=main")

    report = module.scan_config_drift(str(chezmoi), source_dir=str(source))

    assert report.remote_checked is False
    assert report.has_drift is False
    assert any("no upstream" in note for note in report.notes)


def test_render_report_counts_files_without_exposing_contents(tmp_path) -> None:
    """The report summarises counts and branch state, never managed file contents."""

    module = load_script_module()
    report = module.ConfigDriftReport(
        chezmoi_available=True,
        source_directory=str(tmp_path),
        local_change_count=3,
        remote_checked=True,
        behind=2,
        ahead=1,
        upstream="origin/main",
    )

    lines = module.render_report(report).splitlines()

    assert "3 managed files differ from the configuration source." in lines
    assert "The configuration source is 2 commits behind its upstream." in lines
    assert "The source has 1 unpublished commit; run backup to save them." in lines
    assert not any("dot_file" in line for line in lines)


def test_render_report_preserves_scan_errors_without_claiming_clean(tmp_path) -> None:
    """Inspection failures stay visible so a failed scan is never read as in sync."""

    module = load_script_module()
    report = module.ConfigDriftReport(
        chezmoi_available=True,
        source_directory=str(tmp_path),
        local_change_count=0,
        errors=["chezmoi status: Permission denied"],
    )

    rendered = module.render_report(report)

    assert "Managed files match the configuration source." in rendered
    assert rendered.endswith("\n\nScan errors:\n- chezmoi status: Permission denied")


def test_build_notification_mentions_local_and_published_changes() -> None:
    """The notification body explains the drift and proposes applying the configuration."""

    module = load_script_module()
    report = module.ConfigDriftReport(
        chezmoi_available=True,
        local_change_count=1,
        remote_checked=True,
        behind=3,
    )

    title, body = module.build_notification(report)

    assert title == "Workstation configuration drift detected"
    assert "1 local file changed" in body
    assert "3 published updates" in body
    assert "Run setup" in body


def test_notification_failures_are_reported_to_the_caller(tmp_path, monkeypatch, capsys) -> None:
    """A notification failure must fail the scheduled command and explain the error."""

    module = load_script_module()
    chezmoi = write_fake_chezmoi(tmp_path, status_lines=1)
    source = tmp_path / "source"
    source.mkdir()
    run_git(source, "init", "--initial-branch=main")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **_options: subprocess.CompletedProcess(command, 1, "", "Cannot notify\n"),
    )

    exit_code = module.send_notification(
        module.ConfigDriftReport(chezmoi_available=True, local_change_count=1),
        [["Update now", "sh -lc true"]],
    )

    assert exit_code == 1
    assert capsys.readouterr().err == "Cannot notify\n"


def test_saved_report_is_private_and_replaced_without_following_file_links(tmp_path) -> None:
    """Refreshing the saved report preserves other files and keeps report contents private."""

    module = load_script_module(SCRIPT_PATH.with_name("config_drift_notification.py"))
    notifications = module.ConfigDriftNotifications(tmp_path)
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

    module = load_script_module(SCRIPT_PATH.with_name("config_drift_notification.py"))
    notifications = module.ConfigDriftNotifications(tmp_path)
    notifications.path.parent.parent.mkdir()
    notifications.path.parent.symlink_to(tmp_path)
    with pytest.raises(ValueError, match="must not be a symlink"):
        notifications.save("Private report\n")
    assert not (tmp_path / "latest.txt").exists()
