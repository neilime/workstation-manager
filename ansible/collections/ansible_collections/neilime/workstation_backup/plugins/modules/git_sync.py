#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Verify remote Git recovery state before backup."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: git_sync
short_description: Verify or explicitly reconcile a Git checkout
version_added: '1.0.0'
description:
  - Fetches the existing tracking branch and reports unpublished changes.
  - Explicit merging commits local edits and fast-forwards or merges the tracking branch without pushing.
  - Publication rejects behind or diverged branches until reconciled.
  - Remote replacement discards local source edits and commits only when explicitly requested.
  - Pushes only when publication is explicitly requested.
options:
  source:
    description: Path to the existing Git checkout.
    type: path
    required: true
  publish:
    description: Commit all source changes and push the current branch to its upstream.
    type: bool
    default: false
  merge:
    description:
      - Commit all source changes, then fast-forward or merge the tracking branch without rewriting history.
      - Conflicts stop synchronization and must be resolved or aborted manually in the source checkout.
      - Cannot be combined with O(publish).
    type: bool
    default: false
  reset_to_upstream:
    description:
      - Discard tracked source edits, non-ignored untracked files, and local-only commits from the current branch.
      - Replace the source checkout with the fetched tracking branch without pushing or modifying home files.
      - Refuses nested repositories, submodules, and replacements that would overwrite ignored files.
      - Cannot be combined with O(merge) or O(publish). Obtain explicit user confirmation before requesting this action.
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
    description:
      - Inspect local state without fetching or modifying Git state; remote completion remains unverified.
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
            "merge": {"type": "bool", "default": False},
            "reset_to_upstream": {"type": "bool", "default": False},
            "github_token": {"type": "str", "default": "", "no_log": True},
        },
        supports_check_mode=True,
    )
    requested_actions = [
        action
        for option, action in (("merge", "merge"), ("publish", "publish"), ("reset_to_upstream", "use-remote"))
        if module.params[option]
    ]
    if len(requested_actions) > 1:
        module.fail_json(msg="Merging, remote replacement, and publishing require separate decisions.")
    action = requested_actions[0] if requested_actions else "inspect"
    try:
        result = synchronize_git(
            module.params["source"],
            run_command=module.run_command,
            action=action,
            dry_run=module.check_mode,
            github_token=module.params["github_token"],
        )
    except (OSError, ValueError) as error:
        module.fail_json(msg=str(error), changed=getattr(error, "changed", False))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
