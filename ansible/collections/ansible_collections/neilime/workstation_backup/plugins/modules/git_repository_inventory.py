#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Collect Git project recovery metadata while excluding ignored nested repos."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: git_repository_inventory
short_description: Collect Git recovery metadata for project repositories
version_added: '1.0.0'
description:
  - Discovers repositories with physical .git directories beneath the project directory.
  - Excludes nested repositories ignored by their enclosing repository's standard Git ignore rules.
  - Reads commits, branches, remotes, and local changes without fetching or modifying repositories.
options:
  projects_directory:
    description: Absolute directory containing the managed user's projects.
    type: path
    required: true
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Inventory collection only reads local files and Git metadata.
    support: full
"""

EXAMPLES = r"""
- name: Collect project Git inventory
  neilime.workstation_backup.git_repository_inventory:
    projects_directory: /home/user/Documents/dev-projects
"""

RETURN = r"""
repositories:
  description: Repository recovery records, ordered by their absolute root paths.
  type: list
  elements: dict
  returned: success
"""

# Ansible requires runtime imports after the module documentation.
# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_backup.plugins.module_utils.git_inventory import (  # noqa: E402
    GitRepositoryInventoryBuilder,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Build the inventory under the managed user's Git configuration and permissions."""

    module = AnsibleModule(
        argument_spec={"projects_directory": {"type": "path", "required": True}},
        supports_check_mode=True,
    )
    module.get_bin_path("git", required=True)
    try:
        repositories = GitRepositoryInventoryBuilder(module.run_command).build(module.params["projects_directory"])
    except (OSError, ValueError) as error:
        module.fail_json(msg=str(error), changed=False)
    module.exit_json(changed=False, repositories=repositories)


if __name__ == "__main__":
    main()
