"""Build backup-only browser profile exports with sanitized preferences."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_paths import (
    BrowserProfilePathsPlanner,
)


# pylint: disable=too-few-public-methods
class BrowserBackupExportBuilder:
    """Read local browser profile files and remove secret-bearing preference trees."""

    _SENSITIVE_SUBTREE_PATHS = (
        ("account_info",),
        ("autofill",),
        ("brave_sync_v2",),
        ("extensions", "settings"),
        ("gaia_cookie",),
        ("gcm",),
        ("signin",),
        ("sync",),
    )
    _SENSITIVE_KEY_PATTERN = re.compile(
        r"(?:^|[_-])(auth|cookie|credential|oauth|passphrase|password|private|secret|seed|token)(?:$|[_-])",
        re.IGNORECASE,
    )

    def build(
        self,
        browser_name: str,
        timestamp: str,
        user_data_dir: str,
        profiles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Return a JSON-safe export payload for the inspected profiles."""

        if not isinstance(browser_name, str) or browser_name == "":
            raise ValueError("Browser export requires a non-empty browser name")
        if not isinstance(timestamp, str) or timestamp == "":
            raise ValueError("Browser export requires a non-empty timestamp")

        root = BrowserProfilePathsPlanner().validate_user_data_dir(user_data_dir)

        directories: set[str] = set()
        exported_profiles = []
        for profile in profiles:
            exported = self._export_profile(root, profile, directories)
            if exported is not None:
                exported_profiles.append(exported)

        return {
            "browser": browser_name,
            "created_at": timestamp,
            "profiles": exported_profiles,
        }

    def _export_profile(
        self,
        root: Path,
        profile: dict[str, Any],
        directories: set[str],
    ) -> dict[str, Any] | None:
        if not isinstance(profile, dict):
            raise ValueError("Browser export profiles must be objects")

        directory = profile.get("directory")
        label = profile.get("label")
        if not isinstance(directory, str) or directory == "":
            raise ValueError("Browser export profiles require a directory")
        if not isinstance(label, str) or label == "":
            raise ValueError("Browser export profiles require a label")
        if directory in directories:
            raise ValueError("Browser export profiles must have unique directories")
        directories.add(directory)

        profile_root = root / directory
        if profile_root.is_symlink():
            raise ValueError(f"Refusing symlinked browser profile: {directory}")

        bookmarks_present, bookmarks = self._read_json_object(profile_root / "Bookmarks")
        preferences_present, preferences = self._read_json_object(profile_root / "Preferences")

        exported: dict[str, Any] = {
            "directory": directory,
            "label": label,
            "bookmarks_present": bookmarks_present,
            "preferences_present": preferences_present,
        }
        profile_id = profile.get("id")
        if profile_id is not None:
            if not isinstance(profile_id, str) or profile_id == "":
                raise ValueError("Browser export profile ids must be strings")
            exported["id"] = profile_id
        if bookmarks_present:
            exported["bookmarks"] = bookmarks
        if preferences_present:
            exported["preferences"] = self._sanitize_preferences(preferences or {})
        return exported

    def _read_json_object(self, path: Path) -> tuple[bool, dict[str, Any] | None]:
        if path.is_symlink():
            raise ValueError(f"Refusing symlinked browser export file: {path.parent.name}/{path.name}")
        try:
            with path.open(encoding="utf-8") as handle:
                content = json.load(handle)
        except FileNotFoundError:
            return False, None
        except (ValueError, UnicodeError) as error:
            raise ValueError(f"Invalid JSON in browser export file: {path.parent.name}/{path.name}") from error
        if not isinstance(content, dict):
            raise ValueError(f"Expected a JSON object in browser export file: {path.parent.name}/{path.name}")
        return True, content

    def _sanitize_preferences(self, preferences: dict[str, Any]) -> dict[str, Any]:
        sanitized = self._sanitize_value(preferences, ())
        if not isinstance(sanitized, dict):
            raise ValueError("Sanitized browser preferences must stay object-shaped")
        return sanitized

    def _sanitize_value(self, value: Any, path: tuple[str, ...]) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError("Browser preference keys must be strings")
                next_path = path + (key,)
                if self._is_sensitive_path(next_path) or self._is_sensitive_key(key):
                    continue
                sanitized[key] = self._sanitize_value(child, next_path)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_value(item, path) for item in value]
        return value

    def _is_sensitive_path(self, path: tuple[str, ...]) -> bool:
        return any(path[: len(prefix)] == prefix for prefix in self._SENSITIVE_SUBTREE_PATHS)

    def _is_sensitive_key(self, key: str) -> bool:
        return bool(self._SENSITIVE_KEY_PATTERN.search(key))
