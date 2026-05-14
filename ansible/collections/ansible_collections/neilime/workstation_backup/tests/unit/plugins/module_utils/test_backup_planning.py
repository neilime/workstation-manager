"""Unit tests for backup planning and manifest rendering."""

from __future__ import annotations

from ansible_collections.neilime.workstation_backup.plugins.module_utils.backup_planning import (
    BackupManifestContentBuilder,
    BackupPathPlanBuilder,
    BackupRequestedPathsBuilder,
    BrowserBookmarkPlanBuilder,
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
                "label": "chrome-config",
                "path": "/home/emilien/.config/google-chrome",
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
        "include_paths": ["/home/emilien/.config/google-chrome"],
        "manifest_lines": [
            "include\tchrome-config\t/home/emilien/.config/google-chrome",
            "missing\tdev-projects\t/home/emilien/Documents/dev-projects",
        ],
    }


def test_browser_bookmark_plan_builder_builds_export_destinations() -> None:
    """Chrome bookmark files should map to export copies and manifest lines."""

    # Arrange
    builder = BrowserBookmarkPlanBuilder()
    bookmark_files = [
        {"path": "/home/emilien/.config/google-chrome/Default/Bookmarks"},
        {"path": "/home/emilien/.config/google-chrome/Profile 2/Bookmarks"},
    ]

    # Act
    plan = builder.build(
        bookmark_files,
        "/home/emilien/.config/google-chrome",
        "/tmp/backup/browser-bookmarks",
        "\t",
    )

    # Assert
    assert plan == {
        "exports": [
            {
                "source": "/home/emilien/.config/google-chrome/Default/Bookmarks",
                "dest": "/tmp/backup/browser-bookmarks/Default/Bookmarks.json",
            },
            {
                "source": "/home/emilien/.config/google-chrome/Profile 2/Bookmarks",
                "dest": "/tmp/backup/browser-bookmarks/Profile 2/Bookmarks.json",
            },
        ],
        "manifest_lines": [
            "export\tchrome-bookmarks\t/tmp/backup/browser-bookmarks/Default/Bookmarks.json",
            "export\tchrome-bookmarks\t/tmp/backup/browser-bookmarks/Profile 2/Bookmarks.json",
        ],
    }


def test_manifest_content_builder_renders_header_and_records() -> None:
    """Manifest content should render header lines before plan records."""

    # Arrange
    builder = BackupManifestContentBuilder()

    # Act
    content = builder.build(
        [
            "include\tchrome-config\t/home/emilien/.config/google-chrome",
            "export\tchrome-bookmarks\t/tmp/backup/browser-bookmarks/Default/Bookmarks.json",
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
        "include\tchrome-config\t/home/emilien/.config/google-chrome\n"
        "export\tchrome-bookmarks\t/tmp/backup/browser-bookmarks/Default/Bookmarks.json\n"
    )
