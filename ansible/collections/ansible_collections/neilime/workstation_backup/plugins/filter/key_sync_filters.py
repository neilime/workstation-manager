"""Filter plugins for backup-time secret-manager key synchronization."""

from __future__ import annotations

from ansible_collections.neilime.workstation_backup.plugins.module_utils.key_sync import (
    BitwardenGpgKeySyncPlanner,
    BitwardenSshKeySyncPlanner,
)

_ssh_key_sync_planner = BitwardenSshKeySyncPlanner()
_gpg_key_sync_planner = BitwardenGpgKeySyncPlanner()


# pylint: disable=too-few-public-methods
class FilterModule:
    """Expose backup key sync helpers as Ansible filters."""

    def filters(self) -> dict[str, object]:
        """Return the filters provided by this collection."""

        return {
            "backup_ssh_key_sync_actions": _ssh_key_sync_planner.build,
            "backup_gpg_key_sync_actions": _gpg_key_sync_planner.build,
        }
