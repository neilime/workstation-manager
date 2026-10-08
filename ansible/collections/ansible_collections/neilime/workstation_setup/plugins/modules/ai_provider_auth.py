#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ensure the managed user's native AI provider login is available."""

from __future__ import annotations

# Each Ansible module owns its argument and return documentation.
# pylint: disable=duplicate-code
DOCUMENTATION = r"""
---
module: ai_provider_auth
short_description: Reuse native provider logins or start interactive sign-in
version_added: "1.0.0"
description:
  - Checks native provider authentication without making a model request.
  - Requires a ChatGPT account session for Codex and uses native OAuth for interactive sign-in.
  - Connects native login to the user's real terminal when credentials are missing.
  - Ignores inherited automation tokens when checking persistent account sessions.
  - Defers all client execution in check mode.
options:
  home:
    description: Absolute managed-user home directory.
    type: path
    required: true
  provider:
    description: Native client whose account session is managed.
    type: str
    choices: [codex, copilot]
    required: true
  executable:
    description: Absolute path to the provisioned client executable.
    type: path
    required: true
  host:
    description: Required GitHub hostname for Copilot.
    type: str
    default: ''
  account:
    description: Required GitHub account for Copilot.
    type: str
    default: ''
  terminal:
    description: Terminal path for native sign-in; empty disables interactive login.
    type: path
    default: ''
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Defer authentication without starting clients or changing credentials.
    support: full
"""
EXAMPLES = r"""
- name: Check the managed user's Codex login
  neilime.workstation_setup.ai_provider_auth:
    home: /home/user
    provider: codex
    executable: /usr/local/bin/codex
"""
RETURN = r"""
authenticated:
  description: Whether the native client reports an available login.
  type: bool
  returned: success
  sample: true
deferred:
  description: Whether client execution was deferred in check mode.
  type: bool
  returned: success
  sample: false
"""
# pylint: enable=duplicate-code

# Ansible requires metadata before runtime imports.
# pylint: disable=wrong-import-position
import re  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.ai_auth import (  # noqa: E402
    AiProviderAuthentication,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Validate inputs and return sanitized authentication outcomes."""
    module = AnsibleModule(
        argument_spec={
            "home": {"type": "path", "required": True},
            "provider": {"type": "str", "required": True, "choices": ["codex", "copilot"]},
            "executable": {"type": "path", "required": True},
            "host": {"type": "str", "default": ""},
            "account": {"type": "str", "default": ""},
            "terminal": {"type": "path", "default": ""},
        },
        supports_check_mode=True,
    )
    values = module.params
    if not Path(values["home"]).is_absolute() or not Path(values["executable"]).is_absolute():
        module.fail_json(msg="AI authentication requires an absolute home and client executable")
    if values["provider"] == "copilot" and (
        not values["account"].strip() or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", values["host"]) is None
    ):
        module.fail_json(msg="Copilot authentication requires the configured GitHub account and hostname")
    try:
        authentication = AiProviderAuthentication(
            Path(values["home"]),
            values["provider"],
            values["executable"],
            host=values["host"],
            account=values["account"],
        )
        result = authentication.ensure(terminal=values["terminal"], check_mode=module.check_mode)
    except subprocess.TimeoutExpired:
        module.fail_json(msg="AI authentication timed out; check connectivity and complete the provider's native login")
    except OSError:
        module.fail_json(msg="Cannot access the AI client or terminal; run setup from the managed user's desktop")
    # Each module reports validation errors and owns its executable entrypoint.
    # pylint: disable=duplicate-code
    except ValueError as error:
        module.fail_json(msg=str(error))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
