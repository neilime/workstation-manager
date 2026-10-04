"""Unit tests for backup planning and manifest rendering."""

from __future__ import annotations

import pytest
from ansible_collections.neilime.workstation_backup.plugins.module_utils.backup_planning import (
    BackupManifestContentBuilder,
    BackupPathPlanBuilder,
    BackupRequestedPathsBuilder,
)


def test_requested_paths_builder_appends_extra_paths_with_home_expansion() -> None:
    """Extra paths should be appended and `~` should resolve against home."""

    # Arrange
    builder = BackupRequestedPathsBuilder()
    default_paths = [{"label": "projects", "path": "/workspace/projects"}]

    # Act
    requested_paths = builder.build(
        default_paths,
        "~/Downloads:/srv/shared:",
        "/home/emilien",
    )

    # Assert
    assert requested_paths == [
        {"label": "projects", "path": "/workspace/projects"},
        {"label": "extra", "path": "/home/emilien/Downloads"},
        {"label": "extra", "path": "/srv/shared"},
    ]


def test_path_plan_builder_splits_present_and_missing_paths() -> None:
    """Path stats should render include and missing manifest lines."""

    # Arrange
    builder = BackupPathPlanBuilder()
    stats_results = [
        {
            "item": {
                "label": "workstation-manager-user-config",
                "path": "/home/emilien/.config/workstation-manager",
            },
            "stat": {"exists": True},
        },
        {
            "item": {
                "label": "dev-projects",
                "path": "/home/emilien/Documents/dev-projects",
            },
            "stat": {"exists": False},
        },
    ]

    # Act
    plan = builder.build(stats_results, "\t")

    # Assert
    assert plan == {
        "include_paths": ["/home/emilien/.config/workstation-manager"],
        "archive_root": "/home/emilien",
        "manifest_lines": [
            "include\tworkstation-manager-user-config\t/home/emilien/.config/workstation-manager",
            "missing\tdev-projects\t/home/emilien/Documents/dev-projects",
        ],
    }


def test_path_plan_normalizes_extra_paths_before_choosing_the_common_root() -> None:
    """The plan and writer must agree when an extra source uses parent-directory segments."""

    plan = BackupPathPlanBuilder().build(
        [
            {"item": {"label": "dev-projects", "path": "/home/user/Documents/dev-projects"}, "stat": {"exists": True}},
            {"item": {"label": "extra", "path": "/home/user/../../srv/shared"}, "stat": {"exists": True}},
        ],
        "\t",
    )
    assert plan["archive_root"] == "/"


def test_manifest_content_builder_renders_header_and_records() -> None:
    """Manifest content should render header lines before plan records."""

    # Arrange
    builder = BackupManifestContentBuilder()

    # Act
    content = builder.build(
        [
            "include\tworkstation-manager-user-config\t/home/emilien/.config/workstation-manager",
            "export\tgit-repositories\t/tmp/backup/repositories.json",
        ],
        {
            "timestamp": "20260518T120000Z",
            "archive_path": "/tmp/backup/archive.tar.gz",
            "dry_run": False,
            "tab_character": "\t",
            "newline_character": "\n",
        },
    )

    # Assert
    assert content == (
        "created_at\t20260518T120000Z\n"
        "archive\t/tmp/backup/archive.tar.gz\n"
        "dry_run\t0\n"
        "include\tworkstation-manager-user-config\t/home/emilien/.config/workstation-manager\n"
        "export\tgit-repositories\t/tmp/backup/repositories.json\n"
    )


def test_manifest_reports_skips_without_claiming_full_recovery() -> None:
    """Skipped categories must survive in the sidecar without vault item metadata."""

    content = BackupManifestContentBuilder().build(
        [],
        {
            "timestamp": "fixture",
            "archive_path": "archive.tar.gz",
            "dry_run": False,
            "tab_character": "\t",
            "newline_character": "\n",
            "recovery_skips": ["chezmoi", "ssh-keys", "ssh-keys", "browser-sync"],
        },
    )
    assert "recovery_status\tincomplete\n" in content
    assert content.count("recovery_skipped\tssh-keys\n") == 1
    assert "recovery_skipped\tchezmoi\n" in content
    assert "recovery_skipped\tbrowser-sync\n" in content


@pytest.mark.parametrize("skips", ["chezmoi", ["unknown"], [{"secret": "synthetic"}]])
def test_manifest_rejects_unknown_or_sensitive_skip_records(skips) -> None:
    """Only known category labels may enter the public manifest."""

    with pytest.raises(ValueError, match="known backup recovery categories"):
        BackupManifestContentBuilder().build(
            [],
            {
                "timestamp": "fixture",
                "archive_path": "archive.tar.gz",
                "dry_run": False,
                "tab_character": "\t",
                "newline_character": "\n",
                "recovery_skips": skips,
            },
        )
