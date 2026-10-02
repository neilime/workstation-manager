#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Create project backups under the managed user's permissions."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: archive_with_progress
short_description: Create a local backup archive with live size and elapsed-time updates
version_added: '1.0.0'
description:
  - Streams a tar archive with fast gzip compression and mode C(0600).
  - Excludes Git metadata and files ignored by standard Git rules, including nested repositories.
  - Prunes excluded directories without traversing their contents and never follows symbolic links.
  - Publishes the archive only after successful creation, using a C(.partial) staging file.
  - Displays compressed archive size and elapsed time every five seconds while the archive is created.
  - Progress uses the local connection and does not disclose archived filenames.
  - Check mode and tasks marked C(no_log) do not display progress.
options:
  path:
    description: Source files or directories to archive, relative to their common parent.
    type: list
    elements: path
    required: true
  dest:
    description:
      - Destination path for the gzip archive.
      - Relative destinations resolve against the playbook directory.
    type: path
    required: true
  exclusion_patterns:
    description: Shell wildcard patterns matched against archive entry paths to exclude files and directory contents.
    type: list
    elements: str
    default: []
author:
  - workstation-manager contributors (@neilime)
attributes:
  action:
    description: Creates the archive under the task's privileges and reports progress from the controller.
    support: full
  check_mode:
    description: Inspects sources without writing an archive or starting progress monitoring.
    support: full
"""

EXAMPLES = r"""
- name: Create backup archive
  neilime.workstation_backup.archive_with_progress:
    path:
      - /home/user/Documents/dev-projects
    dest: /media/backup/workstation-backup.tar.gz
    exclusion_patterns:
      - '*/.git/*'
"""

RETURN = r"""
dest:
  description: Absolute archive destination.
  type: str
  returned: success
arcroot:
  description: Common parent used for relative archive paths.
  type: str
  returned: success
archived_count:
  description: Number of included entries, including directory and symbolic link entries.
  type: int
  returned: success
"""

# Ansible requires runtime imports after the module documentation.
# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_backup.plugins.module_utils.project_archive import (  # noqa: E402
    ProjectArchiveWriter,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Create the archive without changing execution user or privilege escalation."""

    module = AnsibleModule(
        argument_spec={
            "path": {"type": "list", "elements": "path", "required": True},
            "dest": {"type": "path", "required": True},
            "exclusion_patterns": {"type": "list", "elements": "str", "default": []},
        },
        supports_check_mode=True,
    )
    module.get_bin_path("git", required=True)
    module.get_bin_path("tar", required=True)
    module.get_bin_path("gzip", required=True)
    try:
        result = ProjectArchiveWriter(module.run_command).create(
            module.params["path"],
            module.params["dest"],
            module.params["exclusion_patterns"],
            check_mode=module.check_mode,
        )
    except (OSError, ValueError) as error:
        module.fail_json(msg=f"Backup archive operation failed: {error}", changed=False)
    module.exit_json(**result)


if __name__ == "__main__":
    main()
