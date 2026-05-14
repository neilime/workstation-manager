"""Filter plugins for Bitwarden SSH key restoration helpers."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_ssh_keys import (
    BitwardenSshKeyRestorePlanner,
)

_planner = BitwardenSshKeyRestorePlanner()


# pylint: disable=too-few-public-methods
class FilterModule:
    """Expose Bitwarden SSH restore helpers as Ansible filters."""

    def filters(self) -> dict[str, object]:
        """Return the filters provided by this collection."""

        return {
            "bitwarden_ssh_key_restore_plan": _planner.build_plan,
        }
