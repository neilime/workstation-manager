#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Read-only native Brave inventory and local Sync configuration inspection."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: browser_profile_inspection
extends_documentation_fragment:
  - neilime.workstation_setup.browser_profiles
short_description: Inspect Brave profile, theme color, and local Sync configuration drift
version_added: '1.0.0'
description:
  - Compares sanitized Bitwarden collection profiles with native registrations and Preferences files.
  - Compares the first configured palette color with the native profile theme.
  - Returns profile metadata, declared native theme color observations, and local Sync configuration booleans only.
  - Never returns encrypted seeds or recovery words, and never modifies browser files.
  - Local settings do not prove that synchronization with the server has completed.
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Inspection is read-only in all modes.
    support: full
"""

# Keep each module example self-contained with the same valid profile declaration.
# pylint: disable=duplicate-code
EXAMPLES = r"""
- name: Inspect browser profiles before backup
  neilime.workstation_setup.browser_profile_inspection:
    user_data_dir: /home/user/.config/BraveSoftware/Brave-Browser
    profiles:
      - id: personal
        label: Personal
        item_id: 11111111-1111-4111-8111-111111111111
  register: browser_inspection
"""

# pylint: enable=duplicate-code

RETURN = r"""
profiles:
  description: Observed profiles with declaration references and local Sync boolean metadata.
  returned: always
  type: list
  elements: dict
drift:
  description: Added, missing, renamed, unregistered, incomplete, or theme color profile diagnostics.
  returned: always
  type: list
  elements: dict
sync_issues:
  description: Local Sync configuration issues grouped by native profile directory.
  returned: always
  type: list
  elements: dict
"""

# Ansible requires runtime imports after the module documentation.
# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (  # noqa: E402
    browser_profile_arguments,
    browser_profile_inspection,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Inspect the target user's profiles without writing or querying the Sync server."""

    module = AnsibleModule(
        argument_spec=browser_profile_arguments.browser_profile_argument_spec(),
        supports_check_mode=True,
    )
    try:
        result = browser_profile_inspection.inspect_browser_profiles(
            module.params["user_data_dir"], module.params["profiles"]
        )
    except (OSError, ValueError) as error:
        module.fail_json(msg=str(error))
    module.exit_json(changed=False, **result)


if __name__ == "__main__":
    main()
