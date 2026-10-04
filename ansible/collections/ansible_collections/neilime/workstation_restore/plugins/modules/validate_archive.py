#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Validate a workstation archive before restoring it into a home directory."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: validate_archive
short_description: Validate workstation recovery archive paths
version_added: "1.0.0"
description:
  - Checks member names, links and target paths before a workstation restore.
  - Resolves shortened single-source archive paths to their original home subdirectory.
options:
  path:
    description: Archive to validate.
    required: true
    type: path
  target_home:
    description: User home receiving the restored files.
    required: true
    type: path
  manifest_path:
    description: Matching backup manifest used to resolve the original archive root when available.
    type: path
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Validate the archive without writing files.
    support: full
"""

EXAMPLES = r"""
- name: Validate recovery archive
  neilime.workstation_restore.validate_archive:
    path: /tmp/workstation-manager-backup.tar.gz
    target_home: /home/user
"""

RETURN = r"""
members:
  description: Number of validated archive entries.
  returned: success
  type: int
destination:
  description: Validated extraction directory inside the target home.
  returned: success
  type: str
destination_exists:
  description: Whether the extraction directory already exists.
  returned: success
  type: bool
"""

# Ansible requires runtime imports after the module documentation.
# pylint: disable=wrong-import-position
import tarfile  # noqa: E402

from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_restore.plugins.module_utils.restore_planning import (  # noqa: E402
    ArchiveRestorePlanner,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Validate the archive without writing any target data."""

    module = AnsibleModule(
        argument_spec={
            "path": {"type": "path", "required": True},
            "target_home": {"type": "path", "required": True},
            "manifest_path": {"type": "path"},
        },
        supports_check_mode=True,
    )
    try:
        result = ArchiveRestorePlanner().build(
            module.params["path"], module.params["target_home"], module.params["manifest_path"]
        )
    except (OSError, ValueError, tarfile.TarError) as error:
        module.fail_json(msg=str(error))
    module.exit_json(changed=False, **result)


if __name__ == "__main__":
    main()
