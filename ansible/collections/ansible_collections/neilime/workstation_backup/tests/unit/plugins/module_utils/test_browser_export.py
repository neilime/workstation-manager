"""Unit tests for backup-only browser profile export sanitization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ansible_collections.neilime.workstation_backup.plugins.module_utils.browser_export import (
    BrowserBackupExportBuilder,
)


def test_builder_exports_bookmarks_and_sanitized_preferences(tmp_path: Path) -> None:
    """Bookmarks should be preserved while Sync and token-bearing preference data is removed."""

    root = tmp_path / "Brave-Browser"
    profile = root / "Default"
    profile.mkdir(parents=True)
    (profile / "Bookmarks").write_text(
        json.dumps({"roots": {"bookmark_bar": {"children": [{"name": "Docs", "url": "https://example.invalid"}]}}})
    )
    (profile / "Preferences").write_text(
        json.dumps(
            {
                "profile": {"name": "Personal"},
                "browser": {"show_home_button": True},
                "brave_sync_v2": {"seed": "secret-seed"},
                "sync": {"keep_everything_synced": True},
                "extensions": {
                    "theme": {"id": "user_color_theme_id"},
                    "settings": {"abcdefghijklmnop": {"token": "secret-token"}},
                },
                "nested": {"api_token": "redact-me", "safe": "keep-me"},
                "pinned_tabs": [{"url": "https://example.invalid"}],
            }
        )
    )

    export = BrowserBackupExportBuilder().build(
        "brave",
        "20261001T120000Z",
        str(root),
        [{"id": "personal", "label": "Personal", "directory": "Default"}],
    )

    assert export["browser"] == "brave"
    assert export["created_at"] == "20261001T120000Z"
    profile_export = export["profiles"][0]
    assert profile_export["bookmarks"]["roots"]["bookmark_bar"]["children"][0]["url"] == "https://example.invalid"
    assert profile_export["preferences"]["profile"]["name"] == "Personal"
    assert profile_export["preferences"]["browser"]["show_home_button"] is True
    assert profile_export["preferences"]["pinned_tabs"] == [{"url": "https://example.invalid"}]
    assert profile_export["preferences"]["nested"] == {"safe": "keep-me"}
    assert "sync" not in profile_export["preferences"]
    assert "brave_sync_v2" not in profile_export["preferences"]
    assert "settings" not in profile_export["preferences"]["extensions"]


def test_builder_marks_missing_profile_files_without_inventing_content(tmp_path: Path) -> None:
    """Missing files should remain absent in the export instead of becoming empty JSON objects."""

    root = tmp_path / "Brave-Browser"
    (root / "Default").mkdir(parents=True)

    export = BrowserBackupExportBuilder().build(
        "brave",
        "fixture",
        str(root),
        [{"label": "Personal", "directory": "Default"}],
    )

    assert export["profiles"] == [
        {
            "directory": "Default",
            "label": "Personal",
            "bookmarks_present": False,
            "preferences_present": False,
        }
    ]


def test_builder_rejects_symlinked_export_files(tmp_path: Path) -> None:
    """Symlinked browser files must not be followed into unrelated locations."""

    root = tmp_path / "Brave-Browser"
    profile = root / "Default"
    profile.mkdir(parents=True)
    target = tmp_path / "outside.json"
    target.write_text("{}")
    (profile / "Preferences").symlink_to(target)

    with pytest.raises(ValueError, match="symlinked browser export file"):
        BrowserBackupExportBuilder().build(
            "brave",
            "fixture",
            str(root),
            [{"label": "Personal", "directory": "Default"}],
        )
