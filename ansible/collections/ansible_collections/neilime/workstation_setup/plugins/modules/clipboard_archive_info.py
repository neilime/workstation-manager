#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Validate a pinned Clipboard Indicator archive."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: clipboard_archive_info
short_description: Validate the pinned clipboard extension before extraction
extends_documentation_fragment:
  - neilime.workstation_setup.gnome_extension_archive
version_added: '1.0.0'
description:
  - Checks the Clipboard Indicator artifact's SHA-256, identity, version, GNOME compatibility, and archive paths.
author:
  - workstation-manager contributors (@neilime)
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
  description: Verified Clipboard Indicator metadata.
  type: dict
  returned: success
"""

# pylint: disable=wrong-import-position
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (  # noqa: E402
    gnome_extension_archive_module,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.clipboard_archive import (  # noqa: E402
    ClipboardArchive,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Expose archive checks to setup orchestration."""
    gnome_extension_archive_module.run_archive_module(ClipboardArchive.validate, "Clipboard Indicator")


if __name__ == "__main__":
    main()
