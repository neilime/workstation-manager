"""Filter plugins for managed browser profile path helpers."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    browser_profile_paths,
)

_planner = browser_profile_paths.BrowserProfilePathsPlanner()


# pylint: disable=too-few-public-methods
class FilterModule:
    """Expose managed browser profile helpers as Ansible filters."""

    def filters(self) -> dict[str, object]:
        """Return the filters provided by this collection."""

        return {
            "browser_profiles_root_dir": _planner.build_profiles_root_dir,
            "browser_profile_directory": _planner.build_profile_directory,
            "has_valid_browser_profile_id": _planner.has_valid_profile_id,
        }
