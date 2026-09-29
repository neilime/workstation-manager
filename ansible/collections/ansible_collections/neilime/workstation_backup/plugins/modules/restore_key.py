#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Restore and verify one explicitly approved recovery key."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: restore_key
short_description: Restore one selected SSH or GPG recovery key
version_added: '1.0.0'
description:
  - Restores one approved Bitwarden key locally and verifies the resulting values.
  - GPG imports preserve unrelated keys and fail if local-only packets prevent an exact match.
author:
  - workstation-manager contributors (@neilime)
options:
  kind:
    description: Kind of recovery key.
    type: str
    required: true
    choices: [ssh, gpg]
  user_home:
    description: Absolute home directory of the managed user.
    type: path
    required: true
  key_item:
    description: Sensitive Bitwarden item containing the selected key fields.
    type: dict
    required: true
  identity:
    description: Previously approved SSH name or GPG fingerprint.
    type: str
    required: true
attributes:
  check_mode:
    description: Compare expected values without replacing local keys.
    support: full
"""

EXAMPLES = r"""
- name: Restore an approved key
  neilime.workstation_backup.restore_key:
    kind: ssh
    user_home: /home/user
    key_item: "{{ approved_vault_item }}"
    identity: id_ed25519
  no_log: true
"""

RETURN = r""""""

# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_backup.plugins.module_utils import (  # noqa: E402
    key_restore,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Restore as the resolved managed user without returning key material."""

    module = AnsibleModule(
        argument_spec={
            "kind": {"type": "str", "required": True, "choices": ["ssh", "gpg"]},
            "user_home": {"type": "path", "required": True},
            "key_item": {"type": "dict", "required": True, "no_log": True},
            "identity": {"type": "str", "required": True},
        },
        supports_check_mode=True,
    )
    try:
        changed = key_restore.restore_key(**module.params, run_command=module.run_command, check_mode=module.check_mode)
    # Standard Ansible error/result handling must remain in each executable module.
    # pylint: disable=duplicate-code
    except (OSError, ValueError) as error:
        module.fail_json(msg=str(error))
    module.exit_json(changed=changed)


if __name__ == "__main__":
    main()
