#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Run and verify Brave Sync after the user selects a machine action."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: browser_recovery_sync
extends_documentation_fragment:
  - neilime.workstation_setup.browser_profiles
short_description: Synchronize Brave and verify recovery automatically
version_added: '1.0.0'
description:
  - Gracefully closes the managed browser, checks its native Sync interface, and reopens its previous desktop session.
  - Compares recovery codes privately with Bitwarden and waits for fresh successful Sync without pending changes.
  - Saves local recovery codes after a backup direction choice or joins stored chains during setup or approved backup recovery.
  - Never exposes a debugging port, exports recovery codes, or removes profile locks.
author:
  - workstation-manager contributors (@neilime)
options:
  action:
    description: Run Sync, save local recovery codes, or join stored recovery chains.
    type: str
    required: true
    choices: [sync, save, restore, retry]
  collection_id:
    description: Recovery collection containing the selected browser notes.
    type: str
    required: true
  session:
    description: Current unlocked Bitwarden session.
    type: str
    required: true
attributes:
  check_mode:
    description: Report the required verification without starting Brave or writing vault records.
    support: full
"""

EXAMPLES = r"""
- name: Synchronize browser recovery
  neilime.workstation_setup.browser_recovery_sync:
    user_data_dir: /home/user/.config/BraveSoftware/Brave-Browser
    profiles: "{{ workstation_manager_browser_profiles }}"
    action: sync
    session: "{{ bitwarden_collection_session }}"
    collection_id: "{{ workstation_manager_resolved.secrets.bitwarden.browser_profiles_collection_id }}"
  no_log: true
"""

RETURN = r"""
recovery_error:
  description: Safe explanation of a failed automatic operation, without raw browser or vault output.
  returned: on a handled failure
  type: str
verified:
  description: All inspected profiles completed fresh Sync and their recovery codes match their vault notes.
  returned: always
  type: bool
issues:
  description: Safe profile identities and remaining issue categories, without secrets or browsing data.
  returned: always
  type: list
  elements: dict
summary:
  description: Plain-language report of remaining problems.
  returned: always
  type: str
actions:
  description: Machine actions supported for remaining problems.
  returned: always
  type: dict
"""

# pylint: disable=wrong-import-position,bad-indentation
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (  # noqa: E402
    browser_lifecycle,
    browser_live_sync,
    browser_profile_arguments,
    browser_profile_sync,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Execute as the resolved desktop user and return sanitized results only."""

    arguments = browser_profile_arguments.browser_profile_argument_spec()
    arguments.update(
        {
            "action": {"type": "str", "required": True, "choices": ["sync", "save", "restore", "retry"]},
            "collection_id": {"type": "str", "required": True},
            "session": {"type": "str", "required": True, "no_log": True},
        }
    )
    module = AnsibleModule(argument_spec=arguments, supports_check_mode=True)
    vault = browser_profile_sync.BrowserVault(
        module.params["session"],
        module.params["collection_id"],
        module.run_command,
    )
    try:
        result = browser_live_sync.sync_browser_recovery(  # noqa: E111
            module.params["user_data_dir"],
            module.params["profiles"],
            module.params["action"],
            vault,
            check_mode=module.check_mode,
        )
    except browser_lifecycle.BrowserLifecycleBlocked as error:
        module.exit_json(
            changed=False,
            verified=False,
            issues=[],
            summary=str(error),
            actions={"retry": "Retry the automatic close request and browser verification."},
        )
    except ValueError as error:
        # Helpers expose fixed diagnostics, never raw CDP or vault responses.
        module.fail_json(msg="Automatic browser recovery failed", recovery_error=str(error))
    except OSError:
        module.fail_json(
            msg="Automatic browser recovery failed",
            recovery_error="Check Brave installation and desktop access before retrying.",
        )
    module.exit_json(**result)


if __name__ == "__main__":
    main()
