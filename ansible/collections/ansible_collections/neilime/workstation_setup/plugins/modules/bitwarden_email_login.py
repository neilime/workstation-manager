#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Authenticate Bitwarden email/password logins while handling emailed codes privately."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: bitwarden_email_login
short_description: Log in to Bitwarden with email and password
version_added: '1.0.0'
description:
  - Logs in to Bitwarden with email/password and returns the raw session token from C(bw login --raw).
  - Handles emailed two-step and new-device verification prompts without echoing codes into captured output.
  - Returns retryable failure reasons for rejected credentials or missing interactive verification.
author:
  - workstation-manager contributors (@neilime)
options:
  email:
    description: Bitwarden account email address.
    type: str
    required: true
  password:
    description: Bitwarden vault password.
    type: str
    required: true
  interactive:
    description: Whether the current run can prompt on the controlling terminal for emailed verification codes.
    type: bool
    default: false
attributes:
  check_mode:
    description: Authentication always executes even in check mode because later recovery checks need a live session.
    support: none
"""

EXAMPLES = r"""
- name: Log in with email/password and prompt privately for any emailed verification codes
  neilime.workstation_setup.bitwarden_email_login:
    email: "{{ bitwarden_collection_email }}"
    password: "{{ bitwarden_collection_password }}"
    interactive: "{{ bitwarden_collection_interactive }}"
  register: bitwarden_collection_email_password_login
  no_log: true
"""

RETURN = r"""
failure_reason:
  description: Safe retry reason when the login was rejected.
  returned: always
  type: str
  sample: email_password_rejected
session:
  description: Raw session token returned by C(bw login --raw).
  returned: on success
  type: str
"""

# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils import bitwarden_auth  # noqa: E402

# pylint: enable=wrong-import-position


def main() -> None:
    """Execute Bitwarden email/password login with hidden verification-code prompts."""

    module = AnsibleModule(
        argument_spec={
            "email": {"type": "str", "required": True},
            "password": {"type": "str", "required": True, "no_log": True},
            "interactive": {"type": "bool", "default": False},
        },
        supports_check_mode=False,
    )
    try:
        result = bitwarden_auth.login_with_email_password(
            module.params["email"],
            module.params["password"],
            interactive=module.params["interactive"],
        )
    except (OSError, ValueError) as error:
        module.fail_json(msg=str(error))
    module.exit_json(changed=False, failure_reason=result.failure_reason, session=result.session)


if __name__ == "__main__":
    main()
