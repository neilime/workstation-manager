#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Verify MCP startup and declared authentication checks."""

from __future__ import annotations

# Each Ansible module requires its own metadata and thin adapter entrypoint.
# pylint: disable=duplicate-code
DOCUMENTATION = r"""
---
module: ai_mcp_probe
short_description: Verify MCP startup and declared authentication checks
version_added: "1.0.0"
description:
  - Verify MCP startup and declared authentication checks.
  - Runs as the resolved user and supports previews without mutations or process launches.
options:
  servers:
    description: Resolved local stdio server configurations, including private environment values.
    type: dict
    required: true
  authentication_checks:
    description: Optional read-only tool calls keyed by server name to verify authenticated service access.
    type: dict
    default: {}
  home:
    description: Absolute home of the resolved user.
    type: path
    required: true
  timeout:
    description: Maximum seconds to wait for each protocol response.
    type: int
    default: 30
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Report planned changes or deferred verification without mutations.
    support: full
"""
EXAMPLES = r"""
- name: Verify provisioned local MCP servers
  neilime.workstation_setup.ai_mcp_probe:
    home: /home/user
    servers: "{{ workstation_ai_servers }}"
  no_log: true
"""
RETURN = r"""
verified:
  description: Names whose initialization and tool discovery passed.
  type: list
  elements: str
  returned: success
access_verified:
  description: Names whose declared authentication and service access checks passed.
  type: list
  elements: str
  returned: success
  sample: [context7]
deferred:
  description: Names whose execution was deferred in check mode.
  type: list
  elements: str
  returned: success
"""
# pylint: enable=duplicate-code

# Ansible requires metadata before runtime imports.
# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.mcp_stdio import (  # noqa: E402
    McpStdioSession,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Validate arguments and delegate the operation to the owning helper."""
    module = AnsibleModule(
        argument_spec={
            "servers": {"type": "dict", "required": True, "no_log": True},
            "home": {"type": "path", "required": True},
            "authentication_checks": {"type": "dict", "default": {}, "no_log": True},
            "timeout": {"type": "int", "default": 30},
        },
        supports_check_mode=True,
    )
    if not 1 <= module.params["timeout"] <= 300:
        module.fail_json(msg="MCP verification timeout must be between 1 and 300 seconds")
    if module.check_mode:
        module.exit_json(changed=False, verified=[], access_verified=[], deferred=list(module.params["servers"]))
    verified, access_verified = [], []
    try:
        for name, server in module.params["servers"].items():
            environment = {"HOME": module.params["home"], "PATH": "/usr/local/bin:/usr/bin:/bin", **server["env"]}
            with McpStdioSession(server["command"], server["args"], environment, module.params["timeout"]) as session:
                available_tools = session.tools()
                check = module.params["authentication_checks"].get(name)
                if check:
                    session.check_access(check, available_tools)
                    access_verified.append(name)
            verified.append(name)
    except (OSError, ValueError, KeyError, TypeError):
        module.fail_json(
            msg="MCP startup or authentication/access verification failed; check the declared credentials, executable, "
            "prerequisites and client logs privately. No server output is logged."
        )
    module.exit_json(changed=False, verified=verified, access_verified=access_verified, deferred=[])


if __name__ == "__main__":
    main()
