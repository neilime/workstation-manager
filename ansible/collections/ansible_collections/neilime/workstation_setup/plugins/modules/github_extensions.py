#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Install exact GitHub extension revisions as the managed user."""

# Ansible requires the shared option/author documentation schema.
# pylint: disable=duplicate-code
DOCUMENTATION = r"""
---
module: github_extensions
short_description: Manage pinned GitHub CLI extensions
version_added: "1.0.0"
description:
  - Installs selected release tags or commits and verifies the installed revisions.
  - Replaces outdated selected extensions, refusing locally modified script checkouts.
  - Leaves unselected extensions installed.
options:
  home:
    description: Absolute home directory of the managed user.
    type: path
    required: true
  record:
    description: Absolute path to the managed revision record.
    type: path
    required: true
  extensions:
    description: Mapping of OWNER/gh-NAME repositories to release tags or full commit revisions.
    type: dict
    required: true
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Inspect installed extensions and local changes without installing anything.
    support: full
"""

EXAMPLES = r"""
- name: Install selected GitHub extensions
  neilime.workstation_setup.github_extensions:
    home: /home/user
    record: /home/user/.local/state/workstation-manager/gh-extensions.json
    extensions: "{{ workstation_manager_resolved.development.github.extensions }}"
"""

RETURN = r"""
changed:
  description: Whether any selected extension required installation.
  type: bool
  returned: always
"""

# pylint: enable=duplicate-code

# Ansible requires runtime imports after documentation.
# pylint: disable=wrong-import-position
from pathlib import Path  # noqa: E402

from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.github_extensions import (  # noqa: E402
    GitHubExtensions,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Run gh privately so failed requests cannot expose inherited authentication."""
    module = AnsibleModule(
        argument_spec={
            "home": {"type": "path", "required": True},
            "record": {"type": "path", "required": True},
            "extensions": {"type": "dict", "required": True},
        },
        supports_check_mode=True,
    )
    home, record = (Path(module.params[name]) for name in ("home", "record"))
    if not home.is_absolute() or not record.is_absolute():
        module.fail_json(msg="GitHub extension paths must be absolute")
    try:
        changed = GitHubExtensions(home, record, module.run_command).ensure(
            module.params["extensions"], check_mode=module.check_mode
        )
    # Ansible adapters share this required result/error protocol.
    # pylint: disable=duplicate-code
    except (OSError, ValueError) as error:
        module.fail_json(msg=str(error))
    module.exit_json(changed=changed)


if __name__ == "__main__":
    main()
