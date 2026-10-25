"""Expose Chezmoi's file-replacement conflict classification to setup tasks."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils.chezmoi_conflicts import (
    ChezmoiConflictClassifier,
)


# pylint: disable=too-few-public-methods
class FilterModule:
    """Provide the managed-file conflict filter."""

    def filters(self) -> dict[str, object]:
        """Return the filters provided by this collection."""
        return {"chezmoi_replacement_conflicts": ChezmoiConflictClassifier.replacement_conflicts}
