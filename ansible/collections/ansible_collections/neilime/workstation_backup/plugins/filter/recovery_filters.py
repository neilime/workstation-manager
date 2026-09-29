"""Expose the shared recovery decision validation and rendering helpers."""

from __future__ import annotations

from ansible_collections.neilime.workstation_backup.plugins.module_utils.recovery import (
    recovery_decision,
    recovery_decision_id,
)


# pylint: disable=too-few-public-methods
class FilterModule:
    """Filters for source-independent backup decisions."""

    def filters(self) -> dict[str, object]:
        """Return the supported decision filters."""

        return {"recovery_decision": recovery_decision, "recovery_decision_id": recovery_decision_id}
