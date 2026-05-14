"""Filter plugins for primary browser planning helpers."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    primary_browser_policies,
)

_policies_planner = primary_browser_policies.PrimaryBrowserPoliciesPlanner()


# pylint: disable=too-few-public-methods
class FilterModule:
    """Expose primary browser helpers as Ansible filters."""

    def filters(self) -> dict[str, object]:
        """Return the filters provided by this collection."""

        return {
            "primary_browser_policy_payload": _policies_planner.build_policy_payload,
        }
