#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Seed native Brave profiles while preserving existing browser data."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: browser_profiles
extends_documentation_fragment:
  - neilime.workstation_setup.browser_profiles
short_description: Seed native Brave profile registrations
version_added: '1.0.0'
description:
  - Registers profiles loaded from the Bitwarden collection in Brave Local State.
  - Seeds a name only when a profile has no Preferences file.
  - Applies the first configured palette color as the native profile theme.
  - Refuses changes when Brave holds its user data directory lock.
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Report whether profiles need initialization without writing files.
    support: full
"""

# Keep each module example self-contained with the same valid profile declaration.
# pylint: disable=duplicate-code
EXAMPLES = r"""
- name: Register Personal profile
  neilime.workstation_setup.browser_profiles:
    user_data_dir: /home/user/.config/BraveSoftware/Brave-Browser
    profiles:
      - id: personal
        label: Personal
        item_id: 11111111-1111-4111-8111-111111111111
"""

# pylint: enable=duplicate-code

RETURN = r""""""

# Ansible requires runtime imports after the module documentation.
# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (  # noqa: E402
    browser_profile_arguments,
    browser_profile_seed,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Run native browser profile initialization as the target desktop user."""

    module = AnsibleModule(
        argument_spec=browser_profile_arguments.browser_profile_argument_spec(),
        supports_check_mode=True,
    )
    try:
        changed = browser_profile_seed.seed_browser_profiles(
            module.params["user_data_dir"],
            module.params["profiles"],
            module.check_mode,
        )
    except (OSError, ValueError) as error:
        module.fail_json(msg=str(error))
    module.exit_json(changed=changed)


if __name__ == "__main__":
    main()
