"""Filter plugins for editor settings sync helpers."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    editor_settings_sync,
)

_planner = editor_settings_sync.VscodeSettingsSyncPlanner()


# pylint: disable=too-few-public-methods
class FilterModule:
    """Expose editor settings sync helpers as Ansible filters."""

    def filters(self) -> dict[str, object]:
        """Return the filters provided by this collection."""

        return {
            "vscode_settings_sync_state_dir": _planner.build_sync_state_dir,
            "has_vscode_editor_package": _planner.has_vscode_editor_package,
            "should_request_vscode_settings_sync": _planner.should_request_sync,
            "should_remind_vscode_settings_sync": _planner.should_remind_sync,
        }
