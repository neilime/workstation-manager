#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Apply one approved direction of browser metadata synchronization."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: browser_profile_sync
extends_documentation_fragment:
  - neilime.workstation_setup.browser_profiles
short_description: Synchronize approved native profile metadata
version_added: '1.0.0'
description:
  - Restores saved profile metadata locally or updates existing vault records from local metadata.
  - Restore also enables Sync everything for declared profiles without changing their pairing or setup state.
  - Preserves recovery words and unrelated browser settings; never deletes profile records.
  - Gracefully closes a running browser, verifies applied changes, and reopens its desktop session.
  - Returns a blocker before synchronization if Brave cannot close safely or its profile remains locked.
author:
  - workstation-manager contributors (@neilime)
options:
  direction:
    description: Save local metadata to Bitwarden or restore stored metadata and enable Sync everything locally.
    type: str
    required: true
    choices: [save, restore]
  collection_id:
    description: Configured recovery collection which must still contain the approved records.
    type: str
    required: true
  session:
    description: Current unlocked Bitwarden session for approved vault writes.
    type: str
    required: true
attributes:
  check_mode:
    description: Report pending metadata synchronization without writing files or vault records.
    support: full
"""

EXAMPLES = r"""
- name: Restore approved browser metadata
  neilime.workstation_setup.browser_profile_sync:
    user_data_dir: /home/user/.config/BraveSoftware/Brave-Browser
    profiles: "{{ workstation_manager_browser_profiles }}"
    direction: restore
    session: "{{ bitwarden_collection_session }}"
    collection_id: "{{ workstation_manager_resolved.secrets.bitwarden.browser_profiles_collection_id }}"
  no_log: true
"""

RETURN = r"""
blocked:
  description: Whether the closed-browser precondition prevented synchronization before any changes.
  returned: always
  type: bool
blocker:
  description: Safe instructions for resolving a running browser or remaining profile lock.
  returned: when blocked
  type: str
"""

# pylint: disable=wrong-import-position
from contextlib import nullcontext  # noqa: E402

from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (  # noqa: E402
    browser_lifecycle,
    browser_profile_arguments,
    browser_profile_sync,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Run metadata synchronization as the managed browser user."""

    arguments = browser_profile_arguments.browser_profile_argument_spec()
    arguments.update(
        {
            "direction": {"type": "str", "required": True, "choices": ["save", "restore"]},
            "collection_id": {"type": "str", "required": True},
            "session": {"type": "str", "required": True, "no_log": True},
        }
    )
    module = AnsibleModule(argument_spec=arguments, supports_check_mode=True)
    try:
        lifecycle = (
            nullcontext() if module.check_mode else browser_lifecycle.closed_browser(module.params["user_data_dir"])
        )
        with lifecycle:
            changed = browser_profile_sync.sync_browser_profiles(
                module.params["user_data_dir"],
                module.params["profiles"],
                module.params["direction"],
                browser_profile_sync.BrowserVault(
                    module.params["session"], module.params["collection_id"], module.run_command
                ),
                check_mode=module.check_mode,
            )
    except (browser_profile_sync.BrowserSyncBlocked, browser_lifecycle.BrowserLifecycleBlocked) as error:
        module.exit_json(changed=False, blocked=True, blocker=str(error))
    # Standard Ansible error/result handling must remain in each executable module.
    # pylint: disable=duplicate-code
    except (OSError, ValueError) as error:
        module.fail_json(msg=str(error))
    module.exit_json(changed=changed, blocked=False)


if __name__ == "__main__":
    main()
