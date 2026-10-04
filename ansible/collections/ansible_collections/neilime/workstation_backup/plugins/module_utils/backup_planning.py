"""Pure helpers for building backup plans and manifest content."""

from __future__ import annotations

import os
from typing import Any

from ansible_collections.neilime.workstation_backup.plugins.module_utils.recovery import (
    RECOVERY_SCOPES,
)

# pylint: disable=too-few-public-methods


class BackupRequestedPathsBuilder:
    """Build the effective list of requested backup paths."""

    def build(
        self,
        default_paths: list[dict[str, str]],
        extra_paths_raw: str,
        home_directory: str,
    ) -> list[dict[str, str]]:
        """Append extra paths while expanding `~` against the user home."""

        requested_paths = [dict(item) for item in default_paths]

        for raw_path in extra_paths_raw.split(":"):
            if raw_path == "":
                continue

            requested_paths.append(
                {
                    "label": "extra",
                    "path": (raw_path.replace("~", home_directory, 1) if raw_path.startswith("~") else raw_path),
                }
            )

        return requested_paths


class BackupPathPlanBuilder:
    """Build include-path and manifest data from stat results."""

    def build(
        self,
        path_stats_results: list[dict[str, Any]],
        tab_character: str,
    ) -> dict[str, Any]:
        """Keep archive paths stable even when a requested source is missing."""

        include_paths: list[str] = []
        manifest_lines: list[str] = []

        for result in path_stats_results:
            item = result["item"]
            path = item["path"]
            label = item["label"]
            exists = bool(result.get("stat", {}).get("exists"))

            if exists:
                include_paths.append(path)
                manifest_lines.append(f"include{tab_character}{label}{tab_character}{path}")
                continue

            manifest_lines.append(f"missing{tab_character}{label}{tab_character}{path}")

        return {
            "include_paths": include_paths,
            "manifest_lines": manifest_lines,
            "archive_root": (
                os.path.commonpath(
                    [os.path.dirname(os.path.abspath(result["item"]["path"])) for result in path_stats_results]
                )
                if path_stats_results
                else ""
            ),
        }


class BackupManifestContentBuilder:
    """Render backup manifest text content."""

    def build(
        self,
        manifest_lines: list[str],
        metadata: dict[str, Any],
    ) -> str:
        """Return the manifest payload written by the backup workflow."""

        timestamp = str(metadata["timestamp"])
        archive_path = str(metadata["archive_path"])
        dry_run = bool(metadata["dry_run"])
        tab_character = str(metadata["tab_character"])
        newline_character = str(metadata["newline_character"])
        header_lines = [
            f"created_at{tab_character}{timestamp}",
            f"archive{tab_character}{archive_path}",
            f"dry_run{tab_character}{'1' if dry_run else '0'}",
        ]
        recovery_skips = metadata.get("recovery_skips", [])
        if not isinstance(recovery_skips, list) or any(
            not isinstance(scope, str) or scope not in RECOVERY_SCOPES for scope in recovery_skips
        ):
            raise ValueError("recovery_skips must list known backup recovery categories")
        if recovery_skips:
            header_lines.append(f"recovery_status{tab_character}incomplete")
            header_lines.extend(f"recovery_skipped{tab_character}{scope}" for scope in dict.fromkeys(recovery_skips))
        return newline_character.join(header_lines + manifest_lines) + newline_character
