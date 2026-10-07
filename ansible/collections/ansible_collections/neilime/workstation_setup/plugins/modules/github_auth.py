#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Verify a persistent GitHub login for the managed workstation account."""

# Ansible requires the shared option/author documentation schema.
# pylint: disable=duplicate-code
DOCUMENTATION = r"""
---
module: github_auth
short_description: Establish persistent GitHub authentication in the OS credential store
version_added: "1.0.0"
description:
  - Verifies stored authentication with inherited token overrides removed from child processes.
  - Reuses valid logins or authenticates using a supplied token or an interactive terminal.
  - Requires a working OS credential store and rejects plaintext credential storage.
  - Configures the Git credential helper for the managed user's login.
options:
  home:
    description: Absolute managed-user home directory.
    type: path
    required: true
  host:
    description: GitHub hostname.
    type: str
    required: true
  account:
    description: Required GitHub username for the persistent login.
    type: str
    required: true
  token:
    description: Optional authentication token, passed privately on standard input.
    type: str
    default: ''
  terminal:
    description: Interactive terminal path; empty disables interactive login.
    type: path
    default: ''
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Inspect stored credentials without logging in or changing configuration.
    support: full
"""

EXAMPLES = r"""
- name: Verify the user's GitHub login
  neilime.workstation_setup.github_auth:
    home: /home/user
    host: github.com
    account: example-user
"""

RETURN = r"""
authenticated:
  description: Whether an active login was verified in the OS credential store.
  type: bool
  returned: success
account:
  description: Verified active GitHub account.
  type: str
  returned: success
"""

# pylint: enable=duplicate-code

# Ansible requires runtime imports after documentation.
# pylint: disable=wrong-import-position
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.github_auth import (  # noqa: E402
    GitHubAuthentication,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Keep credential output private and report only actionable failure descriptions."""
    module = AnsibleModule(
        argument_spec={
            "home": {"type": "path", "required": True},
            "host": {"type": "str", "required": True},
            "account": {"type": "str", "required": True},
            "token": {"type": "str", "default": "", "no_log": True},
            "terminal": {"type": "path", "default": ""},
        },
        supports_check_mode=True,
    )
    params = module.params
    if not Path(params["home"]).is_absolute() or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", params["host"]) is None:
        module.fail_json(msg="GitHub authentication requires an absolute user home and a hostname")
    overrides = [
        name
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
        if os.environ.get(name)
    ]
    if overrides:
        module.warn("Stored GitHub login is checked without token overrides: " + ", ".join(overrides))
    try:
        authentication = GitHubAuthentication(Path(params["home"]), params["host"], params["account"])
        if module.check_mode and not Path("/usr/bin/gh").is_file():
            module.exit_json(changed=True, authenticated=False, account="")
        result = authentication.ensure(
            token=params["token"],
            terminal=params["terminal"],
            check_mode=module.check_mode,
        )
    except subprocess.TimeoutExpired:
        module.fail_json(
            msg="GitHub authentication timed out; check connectivity and unlock the desktop credential store"
        )
    except OSError:
        module.fail_json(
            msg="Cannot access the GitHub CLI, credential store, or terminal; run setup from the managed user's desktop"
        )
    except ValueError as error:
        module.fail_json(msg=str(error))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
