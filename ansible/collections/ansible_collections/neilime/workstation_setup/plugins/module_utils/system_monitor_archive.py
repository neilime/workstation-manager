"""Validate a reviewed Vitals system monitor archive before installation."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils.gnome_extension_archive import (
    GnomeExtensionArchive,
)

IDENTITY = ("Vitals@CoreCoding.com", "Vitals")


# pylint: disable=too-few-public-methods
class SystemMonitorArchive:
    """Verify artifact identity, supported Shell versions, and extraction safety."""

    @staticmethod
    def validate(path: str, checksum: str, version: str, shell_version: str) -> dict[str, object]:
        """Return metadata only for the exact pinned, compatible archive."""
        return GnomeExtensionArchive.validate(path, checksum, version, shell_version, IDENTITY)
