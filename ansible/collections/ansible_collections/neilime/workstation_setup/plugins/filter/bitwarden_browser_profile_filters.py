"""Expose sanitized browser declarations from a Bitwarden collection."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_browser_profiles import (
    bitwarden_browser_profiles,
)


# pylint: disable=too-few-public-methods
class FilterModule:
    """Ansible filters for browser profile recovery records."""

    def filters(self) -> dict:
        """Return the collection parser."""

        return {"bitwarden_browser_profiles": bitwarden_browser_profiles}
