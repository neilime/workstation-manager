"""Distinguish file replacements from Chezmoi's current-input transformations."""

from __future__ import annotations

import json
from pathlib import PurePosixPath


# pylint: disable=too-few-public-methods
class ChezmoiConflictClassifier:
    """Classify replacements using source metadata and the actual target types."""

    @staticmethod
    def replacement_conflicts(candidates: list[str], managed_files_json: str, regular_targets: list[str]) -> list[str]:
        """Exempt native modifiers only when their current targets are regular files.

        The metadata must come from ``managed --include=files --path-style=all``.
        It describes desired source types, so current targets must also be
        inspected without following links. Neither current type changes nor a
        modifier descendant may exempt a conflicting path.
        """
        try:
            managed_files = json.loads(managed_files_json)
        except (TypeError, ValueError) as error:
            raise ValueError("Chezmoi returned invalid managed-file metadata.") from error
        if not isinstance(managed_files, dict):
            raise TypeError("Chezmoi returned invalid managed-file metadata.")

        conflicts = []
        for candidate in candidates:
            target = candidate[3:]
            if target not in regular_targets or target not in managed_files:
                conflicts.append(candidate)
                continue
            entry = managed_files[target]
            if not isinstance(entry, dict) or not isinstance(entry.get("sourceRelative"), str):
                raise TypeError("Chezmoi returned invalid managed-file metadata.")
            source = entry["sourceRelative"]
            if not source:
                raise ValueError("Chezmoi returned invalid managed-file metadata.")
            # Chezmoi recognizes modify_ only as the first source basename prefix.
            if not PurePosixPath(source).name.startswith("modify_"):
                conflicts.append(candidate)
        return conflicts
