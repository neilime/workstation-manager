"""Filter plugins for Bitwarden GPG key restoration helpers."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_gpg_keys import (
    BitwardenGpgKeyRestorePlanner,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.git_gpg_signing import (
    GitGpgSigningPlanner,
)

_planner = BitwardenGpgKeyRestorePlanner()
_git_signing_planner = GitGpgSigningPlanner()


# pylint: disable=too-few-public-methods
class FilterModule:
    """Expose Bitwarden GPG restore helpers as Ansible filters."""

    def filters(self) -> dict[str, object]:
        """Return the filters provided by this collection."""

        return {
            "bitwarden_gpg_key_restore_plan": _planner.build_plan,
            "gpg_git_signing_fingerprint": _git_signing_planner.signing_fingerprint,
        }
