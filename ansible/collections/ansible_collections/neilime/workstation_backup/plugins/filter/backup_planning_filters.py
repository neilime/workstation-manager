"""Filter plugins for backup planning and manifest rendering."""

from __future__ import annotations

from ansible_collections.neilime.workstation_backup.plugins.module_utils.backup_planning import (
    BackupManifestContentBuilder,
    BackupPathPlanBuilder,
    BackupRequestedPathsBuilder,
    BrowserBookmarkPlanBuilder,
)

_requested_paths_builder = BackupRequestedPathsBuilder()
_path_plan_builder = BackupPathPlanBuilder()
_bookmark_plan_builder = BrowserBookmarkPlanBuilder()
_manifest_builder = BackupManifestContentBuilder()


# pylint: disable=too-few-public-methods
class FilterModule:
    """Expose backup planning helpers as Ansible filters."""

    def filters(self) -> dict[str, object]:
        """Return the filters provided by this collection."""

        return {
            "backup_requested_paths": _requested_paths_builder.build,
            "backup_path_plan": _path_plan_builder.build,
            "backup_bookmark_plan": _bookmark_plan_builder.build,
            "backup_manifest_content": _manifest_builder.build,
        }
