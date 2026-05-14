"""Pure helpers for building backup plans and manifest content."""

from __future__ import annotations

from typing import Any

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
                    "path": (
                        raw_path.replace("~", home_directory, 1)
                        if raw_path.startswith("~")
                        else raw_path
                    ),
                }
            )

        return requested_paths


class BackupPathPlanBuilder:
    """Build include-path and manifest data from stat results."""

    def build(
        self,
        path_stats_results: list[dict[str, Any]],
        tab_character: str,
    ) -> dict[str, list[str]]:
        """Return include paths plus manifest lines for present and missing paths."""

        include_paths: list[str] = []
        manifest_lines: list[str] = []

        for result in path_stats_results:
            item = result["item"]
            path = item["path"]
            label = item["label"]
            exists = bool(result.get("stat", {}).get("exists"))

            if exists:
                include_paths.append(path)
                manifest_lines.append(
                    f"include{tab_character}{label}{tab_character}{path}"
                )
                continue

            manifest_lines.append(f"missing{tab_character}{label}{tab_character}{path}")

        return {
            "include_paths": include_paths,
            "manifest_lines": manifest_lines,
        }


class BrowserBookmarkPlanBuilder:
    """Build browser bookmark export and manifest data."""

    def build(
        self,
        bookmark_files: list[dict[str, Any]],
        chrome_config_dir: str,
        bookmarks_export_dir: str,
        tab_character: str,
    ) -> dict[str, list[dict[str, str]] | list[str]]:
        """Return bookmark export copies and their manifest lines."""

        exports: list[dict[str, str]] = []
        manifest_lines: list[str] = []
        chrome_prefix = f"{chrome_config_dir.rstrip('/')}/"

        for bookmark_file in bookmark_files:
            source_path = bookmark_file["path"]
            relative_path = (
                source_path.removeprefix(chrome_prefix)
                if source_path.startswith(chrome_prefix)
                else source_path.lstrip("/")
            )
            destination_path = f"{bookmarks_export_dir}/{relative_path}.json"

            exports.append({"source": source_path, "dest": destination_path})
            manifest_lines.append(
                f"export{tab_character}chrome-bookmarks{tab_character}{destination_path}"
            )

        return {
            "exports": exports,
            "manifest_lines": manifest_lines,
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
        return newline_character.join(header_lines + manifest_lines) + newline_character
