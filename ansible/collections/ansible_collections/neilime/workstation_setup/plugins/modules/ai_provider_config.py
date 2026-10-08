#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Reconcile private MCP configuration while preserving user entries."""

from __future__ import annotations

# Each Ansible module requires its own metadata and thin adapter entrypoint.
# pylint: disable=duplicate-code
DOCUMENTATION = r"""
---
module: ai_provider_config
short_description: Reconcile private MCP configuration while preserving user entries
version_added: "1.0.0"
description:
  - Reconcile private MCP configuration while preserving user entries.
  - Runs as the resolved user and supports previews without mutations or process launches.
options:
  path:
    description: Absolute native client configuration path; symlinks are rejected.
    type: path
    required: true
  state_path:
    description: Absolute private ownership-state path containing entry digests only.
    type: path
    required: true
  format:
    description: Native client serialization format.
    type: str
    choices: [json, toml]
    required: true
  key:
    description: Native root key containing the server map.
    type: str
    required: true
  servers:
    description: Resolved stdio launch fields, possibly containing secret environment values.
    type: dict
    required: true
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Report planned changes or deferred verification without mutations.
    support: full
"""
EXAMPLES = r"""
- name: Configure MCP servers for a client
  neilime.workstation_setup.ai_provider_config:
    path: /home/user/.copilot/mcp-config.json
    state_path: /home/user/.local/state/workstation-manager/ai-tools/copilot.json
    format: json
    key: mcpServers
    servers: {}
  no_log: true
"""
RETURN = r"""{}"""
# pylint: enable=duplicate-code

# Ansible requires metadata before runtime imports.
# pylint: disable=wrong-import-position
from pathlib import Path  # noqa: E402

from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.ai_provider_config import (  # noqa: E402
    AiProviderConfiguration,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Validate arguments and delegate the operation to the owning helper."""
    module = AnsibleModule(
        argument_spec={
            "path": {"type": "path", "required": True},
            "state_path": {"type": "path", "required": True},
            "format": {"type": "str", "choices": ["json", "toml"], "required": True},
            # Native document property, not an authentication key.
            "key": {"type": "str", "required": True, "no_log": False},
            "servers": {"type": "dict", "required": True, "no_log": True},
        },
        supports_check_mode=True,
    )
    try:
        changed = AiProviderConfiguration().reconcile(
            Path(module.params["path"]),
            Path(module.params["state_path"]),
            module.params["format"],
            module.params["key"],
            module.params["servers"],
            module.check_mode,
        )
    except (OSError, ValueError, TypeError):
        module.fail_json(
            msg="Cannot reconcile MCP configuration: check its syntax, symlinks, permissions "
            "and conflicting user entries. No configuration values are logged."
        )
    module.exit_json(changed=changed)


if __name__ == "__main__":
    main()
