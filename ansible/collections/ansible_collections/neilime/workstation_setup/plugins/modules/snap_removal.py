#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Remove optional Snap installations after verifying data recovery."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: snap_removal
short_description: Remove Snap with verified data preservation
version_added: "1.0.0"
description:
  - Rejects installations that depend on Snap for boot or encryption.
  - Archives application data and verifies the archive before removal.
  - Purges Snap packages and residual state without removing unrelated packages.
options:
  state:
    description: Inspect boot dependencies or converge Snap to absence.
    type: str
    choices: [inspected, absent]
    default: absent
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Inspect without stopping services, archiving data, or removing packages.
    support: full
"""

EXAMPLES = r"""
- name: Remove Snap with verified data preservation
  neilime.workstation_setup.snap_removal:
    state: absent
"""

RETURN = r"""
backup_archive:
  description: Root-only recovery archive retained outside all Snap directories.
  type: str
  returned: success
"""

# Ansible requires runtime imports after module documentation.
# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.snap_removal import (  # noqa: E402
    SnapRemoval,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Run the Snap removal workflow under Ansible's privilege and check-mode policy."""
    module = AnsibleModule(
        argument_spec={
            "state": {"type": "str", "choices": ["inspected", "absent"], "default": "absent"},
        },
        supports_check_mode=True,
    )
    removal = SnapRemoval(module.run_command)
    try:
        if module.params["state"] == "inspected":
            removal.inspect()
            result = {"changed": False, "backup_archive": ""}
        else:
            result = removal.remove("/var/backups/workstation-manager/snap", check_mode=module.check_mode)
    except (OSError, ValueError, KeyError) as error:
        module.fail_json(msg=f"Snap removal is incomplete: {error}")
    module.exit_json(**result)


if __name__ == "__main__":
    main()
