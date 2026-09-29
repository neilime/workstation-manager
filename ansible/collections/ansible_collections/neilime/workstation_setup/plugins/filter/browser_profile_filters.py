"""Filter plugins for browser profile paths and recovery reports."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    browser_profile_paths,
    browser_profile_reporting,
    browser_profile_sync,
)

_planner = browser_profile_paths.BrowserProfilePathsPlanner()


# pylint: disable=too-few-public-methods
class FilterModule:
    """Expose managed browser profile helpers as Ansible filters."""

    def filters(self) -> dict[str, object]:
        """Return the filters provided by this collection."""

        return {
            "browser_profile_directory": _planner.build_profile_directory,
            "browser_recovery_report": browser_profile_reporting.browser_recovery_report,
            "browser_recovery_inspection": browser_profile_reporting.browser_recovery_inspection,
            "browser_sync_report": browser_profile_reporting.browser_sync_report,
            "browser_sync_directions": browser_profile_sync.browser_sync_directions,
        }
