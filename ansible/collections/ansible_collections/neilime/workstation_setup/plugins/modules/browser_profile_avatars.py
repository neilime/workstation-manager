#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Recover configured browser avatars using bounded private Bitwarden reads."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: browser_profile_avatars
short_description: Read browser avatar attachments into memory
version_added: '1.0.0'
description:
  - Downloads configured attachments with at most two concurrent Bitwarden CLI processes.
  - Returns all enriched profiles only after every attachment has been downloaded successfully.
  - Each download allows four attempts with a 120-second timeout and five seconds between attempts.
  - Requires an already synchronized vault and runs as the managed browser user.
  - Tasks must use C(no_log=true) because returned profiles contain private image data.
author:
  - workstation-manager contributors (@neilime)
options:
  profiles:
    description:
      - Sanitized browser profile records loaded from the Bitwarden collection.
      - Each record requires a unique canonical C(id) profile slug.
      - Records with C(avatar_attachment_id) also require a canonical C(item_id) UUID.
      - Other metadata is preserved without modification.
    type: list
    elements: dict
    required: true
  session:
    description: Current unlocked Bitwarden session, passed only inside the module process.
    type: str
    required: true
  appdata_dir:
    description: Absolute path to the managed user's synchronized Bitwarden CLI cache.
    type: path
    required: true
attributes:
  check_mode:
    description: Reads attachments during previews without changing browser files or vault records.
    support: full
"""

EXAMPLES = r"""
- name: Recover browser avatar attachments privately
  neilime.workstation_setup.browser_profile_avatars:
    profiles: "{{ workstation_manager_browser_profiles }}"
    session: "{{ bitwarden_collection_session }}"
    appdata_dir: "{{ bitwarden_collection_appdata_dir }}"
  no_log: true
"""

RETURN = r"""
profiles:
  description: Complete profile metadata with configured attachments added as base64 C(avatar_png) values.
  returned: success
  type: list
  elements: dict
  sample:
    - id: work
      item_id: 11111111-1111-4111-8111-111111111111
      avatar_attachment_id: sample-avatar
      avatar_png: c3ludGhldGljLWltYWdl
"""

# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_avatars import (  # noqa: E402
    BrowserAvatarRecovery,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Read private images as the managed user and publish no partial result on failure."""

    module = AnsibleModule(
        argument_spec={
            "profiles": {"type": "list", "elements": "dict", "required": True},
            "session": {"type": "str", "required": True, "no_log": True},
            "appdata_dir": {"type": "path", "required": True},
        },
        supports_check_mode=True,
    )
    try:
        recovery = BrowserAvatarRecovery(
            module.params["session"], module.params["appdata_dir"], module.get_bin_path("bw", required=True)
        )
        profiles = recovery.read(module.params["profiles"])
    except ValueError as error:
        module.fail_json(msg=str(error), exception=None)
    module.exit_json(changed=False, profiles=profiles)


if __name__ == "__main__":
    main()
