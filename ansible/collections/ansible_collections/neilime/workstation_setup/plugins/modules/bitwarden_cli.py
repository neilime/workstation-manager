#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Keep Bitwarden authentication secrets inside the managed module process."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: bitwarden_cli
short_description: Run Bitwarden authentication and synchronization privately
version_added: '1.0.0'
description:
  - Runs the Bitwarden CLI with credentials passed inside the module rather than the task environment.
  - Prevents connection tracing from disclosing authentication environment variables.
  - Returns command status for the role's authentication diagnostics and synchronization retries.
  - Tasks must use C(no_log=true) because unlocking returns a new session token.
author:
  - workstation-manager contributors (@neilime)
options:
  operation:
    description: Authentication or synchronization operation to execute.
    type: str
    required: true
    choices: [status, login, unlock, sync]
  session:
    description: Existing unlocked session token, or empty to avoid an inherited session.
    type: str
    default: ''
  password:
    description: Vault password, required for unlocking.
    type: str
    default: ''
  client_id:
    description: Personal API client identifier, required for login.
    type: str
    default: ''
  client_secret:
    description: Personal API client secret, required for login.
    type: str
    default: ''
attributes:
  check_mode:
    description: Authentication and synchronization require execution even during recovery previews.
    support: none
"""

EXAMPLES = r"""
- name: Synchronize the unlocked vault without exposing its session to connection tracing
  neilime.workstation_setup.bitwarden_cli:
    operation: sync
    session: "{{ bitwarden_collection_session }}"
  register: bitwarden_collection_sync
  no_log: true
"""

RETURN = r"""
rc:
  description: Bitwarden CLI exit status.
  returned: always
  type: int
  sample: 0
stdout:
  description: Successful status JSON or the private unlock token; empty for other operations or failures.
  returned: always
  type: str
"""

# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402

# pylint: enable=wrong-import-position


def main() -> None:
    """Execute only supported vault operations with private process-local credentials."""
    module = AnsibleModule(
        argument_spec={
            "operation": {"type": "str", "required": True, "choices": ["status", "login", "unlock", "sync"]},
            "session": {"type": "str", "default": "", "no_log": True},
            "password": {"type": "str", "default": "", "no_log": True},
            "client_id": {"type": "str", "default": "", "no_log": True},
            "client_secret": {"type": "str", "default": "", "no_log": True},
        },
        supports_check_mode=False,
    )
    operation = module.params["operation"]
    argv = [module.get_bin_path("bw", required=True), operation]
    environment = {"BW_SESSION": module.params["session"], "BW_NOINTERACTION": "true"}
    if operation == "login":
        if not module.params["client_id"] or not module.params["client_secret"]:
            module.fail_json(msg="Bitwarden API login requires client_id and client_secret")
        argv.append("--apikey")
        environment.update(BW_CLIENTID=module.params["client_id"], BW_CLIENTSECRET=module.params["client_secret"])
    elif operation == "unlock":
        if not module.params["password"]:
            module.fail_json(msg="Bitwarden unlock requires password")
        argv.extend(["--passwordenv", "BITWARDEN_PASSWORD", "--raw"])
        environment["BITWARDEN_PASSWORD"] = module.params["password"]
    rc, stdout, _stderr = module.run_command(argv, environ_update=environment)
    module.exit_json(
        changed=operation == "login" and rc == 0,
        failed=rc != 0,
        rc=rc,
        stdout=stdout if rc == 0 and operation in {"status", "unlock"} else "",
    )


if __name__ == "__main__":
    main()
