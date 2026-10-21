#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Configure a verified managed-user Docker login to GitHub Container Registry."""

# Ansible requires the shared option/author documentation schema.
# pylint: disable=duplicate-code
DOCUMENTATION = r"""
---
module: ghcr_auth
short_description: Authenticate Docker to GHCR with credentials stored in the keyring
version_added: "1.0.0"
description:
  - Verifies the configured GitHub account and uses its saved login by default, requiring C(write:packages).
  - Accepts a separate registry token for automation, including GitHub Actions job tokens.
  - Uses Docker's Secret Service helper and passes the token only over standard input.
  - Validates the registry login and stored credential before merging Docker configuration.
  - Preserves unrelated Docker settings and registry credentials.
  - Does not pull, push, or delete images.
options:
  home:
    description: Absolute managed-user home directory.
    type: path
    required: true
  account:
    description: Expected github.com username.
    type: str
    required: true
  terminal:
    description: User terminal for native GitHub permission authorization when needed.
    type: path
    default: ''
  token:
    description:
      - Optional registry token with pull and push permissions granted by its issuer.
      - Does not replace the managed user's GitHub CLI login.
      - GitHub Actions tokens require C(packages:write) and access to the target package.
    type: str
    default: ''
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Inspect configuration and credentials without refreshing permissions or logging into GHCR.
    support: full
"""

EXAMPLES = r"""
- name: Verify Docker's GHCR login for the managed user
  neilime.workstation_setup.ghcr_auth:
    home: /home/user
    account: example-user
"""

RETURN = r"""
authenticated:
  description: Whether registry login and secure credential storage were verified during this run.
  type: bool
  returned: success
  sample: true
account:
  description: Configured GitHub account.
  type: str
  returned: success
  sample: example-user
"""
# pylint: enable=duplicate-code

# Ansible requires runtime imports after documentation.
# pylint: disable=wrong-import-position
import re  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.ghcr_auth import (  # noqa: E402
    GhcrAuthentication,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Return only status metadata; subprocess and credential output stay private."""
    # The standard Ansible result/error adapter is intentionally shared.
    # pylint: disable=duplicate-code
    module = AnsibleModule(
        argument_spec={
            "home": {"type": "path", "required": True},
            "account": {"type": "str", "required": True},
            "terminal": {"type": "path", "default": ""},
            "token": {"type": "str", "default": "", "no_log": True},
        },
        supports_check_mode=True,
    )
    home, account = Path(module.params["home"]), module.params["account"]
    if not home.is_absolute() or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]*", account) is None:
        module.fail_json(msg="GHCR authentication requires an absolute user home and a GitHub account")
    if module.check_mode and not all(
        Path(binary).is_file()
        for binary in ("/usr/bin/gh", "/usr/bin/docker", "/usr/local/bin/docker-credential-secretservice")
    ):
        module.exit_json(changed=True, authenticated=False, account=account)
    try:
        result = GhcrAuthentication(home, account).ensure(
            token=module.params["token"], terminal=module.params["terminal"], check_mode=module.check_mode
        )
    except subprocess.TimeoutExpired:
        module.fail_json(msg="GHCR authentication timed out; check network access and unlock the desktop keyring")
    except OSError:
        module.fail_json(
            msg="Cannot access Docker, GitHub CLI, or their credential store; rerun setup from the desktop"
        )
    except ValueError as error:
        module.fail_json(msg=str(error))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
