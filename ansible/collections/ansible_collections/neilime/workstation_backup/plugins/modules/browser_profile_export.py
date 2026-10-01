#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Export browser bookmarks plus sanitized non-secret preferences for backup."""

from __future__ import annotations

# Module documentation intentionally repeats standard Ansible metadata.
# pylint: disable=duplicate-code
DOCUMENTATION = r"""
---
module: browser_profile_export
short_description: Export browser bookmarks and sanitized preferences for backup
version_added: '1.0.0'
description:
  - Reads local browser profile Bookmarks and Preferences files without mutation.
  - Removes known secret-bearing preference trees and secret-like keys from the exported preferences.
  - Produces a backup-only payload; setup restore continues to rely on Bitwarden and browser Sync.
options:
  browser:
    description: Selected browser adapter name.
    type: str
    required: true
  timestamp:
    description: Backup timestamp shared with the main archive and manifest.
    type: str
    required: true
  user_data_dir:
    description: Absolute native browser user-data directory.
    type: path
    required: true
  profiles:
    description: Browser profiles returned by native inspection.
    type: list
    elements: dict
    required: true
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description:
      - Fully supported because export only reads existing browser files.
    support: full
"""

EXAMPLES = r"""
- name: Export Brave bookmarks and sanitized preferences
  neilime.workstation_backup.browser_profile_export:
    browser: brave
    timestamp: 20261001T120000Z
    user_data_dir: /home/user/.config/BraveSoftware/Brave-Browser
    profiles:
      - directory: Default
        id: personal
        label: Personal
"""

# pylint: enable=duplicate-code

RETURN = r"""
export:
  description: Backup-only browser profile export payload.
  type: dict
  returned: success
"""

# Ansible requires runtime imports after the module documentation.
# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_backup.plugins.module_utils.browser_export import (  # noqa: E402
    BrowserBackupExportBuilder,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Read local browser files and return a sanitized export payload."""

    module = AnsibleModule(
        argument_spec={
            "browser": {"type": "str", "required": True},
            "timestamp": {"type": "str", "required": True},
            "user_data_dir": {"type": "path", "required": True},
            "profiles": {"type": "list", "elements": "dict", "required": True},
        },
        supports_check_mode=True,
    )
    try:
        export = BrowserBackupExportBuilder().build(
            module.params["browser"],
            module.params["timestamp"],
            module.params["user_data_dir"],
            module.params["profiles"],
        )
    except (OSError, ValueError) as error:
        module.fail_json(msg=str(error), changed=False)
    module.exit_json(changed=False, export=export)


if __name__ == "__main__":
    main()
