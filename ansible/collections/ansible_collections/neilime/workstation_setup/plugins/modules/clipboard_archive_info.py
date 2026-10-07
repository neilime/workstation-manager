#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Validate a pinned Clipboard Indicator archive."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: clipboard_archive_info
short_description: Validate the pinned clipboard extension before extraction
version_added: '1.0.0'
description:
  - Checks SHA-256, extension identity, version, GNOME compatibility, and archive paths.
author:
  - workstation-manager contributors (@neilime)
options:
  path:
    description: Downloaded extension archive.
    type: path
    required: true
  sha256:
    description: Expected archive digest.
    type: str
    required: true
  version:
    description: Expected extension version.
    type: str
    required: true
  shell_version:
    description: Output of gnome-shell --version.
    type: str
    required: true
attributes:
  check_mode:
    description: Reads the archive without modifying it.
    support: full
"""
EXAMPLES = r"""
- name: Validate the configured clipboard archive
  neilime.workstation_setup.clipboard_archive_info:
    path: /tmp/clipboard.zip
    sha256: "{{ clipboard.sha256 }}"
    version: "{{ clipboard.version }}"
    shell_version: "{{ gnome_shell.stdout }}"
"""
RETURN = r"""
metadata:
  description: Verified extension metadata.
  type: dict
  returned: success
"""

# pylint: disable=wrong-import-position
import zipfile  # noqa: E402

from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.clipboard_archive import (  # noqa: E402
    ClipboardArchive,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Expose archive checks to setup orchestration."""
    module = AnsibleModule(
        argument_spec={
            "path": {"type": "path", "required": True},
            "sha256": {"type": "str", "required": True},
            "version": {"type": "str", "required": True},
            "shell_version": {"type": "str", "required": True},
        },
        supports_check_mode=True,
    )
    try:
        metadata = ClipboardArchive.validate(
            module.params["path"], module.params["sha256"], module.params["version"], module.params["shell_version"]
        )
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        module.fail_json(msg=f"Cannot install Clipboard Indicator: {error}")
    module.exit_json(changed=False, metadata=metadata)


if __name__ == "__main__":
    main()
