#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Expose selected AI skills without overwriting user files."""

from __future__ import annotations

# Each Ansible module requires its own metadata and thin adapter entrypoint.
# pylint: disable=duplicate-code
DOCUMENTATION = r"""
---
module: ai_skill_links
short_description: Expose selected AI skills without overwriting user files
version_added: "1.0.0"
description:
  - Expose selected AI skills without overwriting user files.
  - Runs as the resolved user and supports previews without mutations or process launches.
options:
  directory:
    description: Absolute provider skill directory.
    type: path
    required: true
  state_path:
    description: Absolute path recording links created by this module.
    type: path
    required: true
  skills:
    description: Selected skill names, absolute source roots and relative subdirectories.
    type: list
    elements: dict
    required: true
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Report planned changes or deferred verification without mutations.
    support: full
"""
EXAMPLES = r"""
- name: Expose a declared skill
  neilime.workstation_setup.ai_skill_links:
    directory: /home/user/.copilot/skills
    state_path: /home/user/.local/state/workstation-manager/ai-tools/copilot-skills.json
    skills:
      - name: review
        root: /home/user
        subdirectory: .agents/skills/review
"""
RETURN = r"""
deferred:
  description: Skill names whose sources are unavailable in check mode.
  type: list
  elements: str
  returned: success
"""
# pylint: enable=duplicate-code

# Ansible requires metadata before runtime imports.
# pylint: disable=wrong-import-position
from pathlib import Path  # noqa: E402

from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.ai_skill_links import (  # noqa: E402
    AiSkillLinks,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Validate arguments and delegate the operation to the owning helper."""
    module = AnsibleModule(
        argument_spec={
            "directory": {"type": "path", "required": True},
            "state_path": {"type": "path", "required": True},
            "skills": {"type": "list", "elements": "dict", "required": True},
        },
        supports_check_mode=True,
    )
    try:
        result = AiSkillLinks().reconcile(
            Path(module.params["directory"]),
            Path(module.params["state_path"]),
            module.params["skills"],
            module.check_mode,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        module.fail_json(msg=f"Cannot reconcile AI skills: {error}")
    module.exit_json(**result)


if __name__ == "__main__":
    main()
