#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Verify remote Git recovery state before backup."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: git_sync
short_description: Verify or explicitly publish a Git checkout
version_added: '1.0.0'
description:
  - Fetches the existing tracking branch and reports unpublished changes.
  - Publication rejects behind or diverged branches without merging or resetting files.
  - Commits and pushes only when publication is explicitly requested.
options:
  source:
    description: Path to the existing Git checkout.
    type: path
    required: true
  publish:
    description: Commit all source changes and push the current branch to its upstream.
    type: bool
    default: false
  github_token:
    description: Optional token scoped to HTTPS requests to github.com.
    type: str
    default: ''
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Inspect local state without fetching, committing, or pushing; remote completion remains unverified.
    support: full
"""

EXAMPLES = r"""
- name: Inspect Chezmoi recovery state
  neilime.workstation_backup.git_sync:
    source: /home/user/.local/share/chezmoi
"""

RETURN = r"""
state:
  description: Branch, upstream commit, worktree status, ahead and behind counts, and remote verification state.
  type: dict
  returned: success
"""

# Ansible requires runtime imports after the module documentation.
# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_backup.plugins.module_utils.git_sync import (  # noqa: E402
    synchronize_git,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Run the Git completion check as the target user."""

    module = AnsibleModule(
        argument_spec={
            "source": {"type": "path", "required": True},
            "publish": {"type": "bool", "default": False},
            "github_token": {"type": "str", "default": "", "no_log": True},
        },
        supports_check_mode=True,
    )
    try:
        result = synchronize_git(
            module.params["source"],
            run_command=module.run_command,
            publish=module.params["publish"],
            dry_run=module.check_mode,
            github_token=module.params["github_token"],
        )
    except (OSError, ValueError) as error:
        module.fail_json(msg=str(error))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
