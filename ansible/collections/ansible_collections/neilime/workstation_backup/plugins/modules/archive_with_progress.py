#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Document the controller action that creates backups with live progress."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: archive_with_progress
short_description: Create a local backup archive with live size and elapsed-time updates
version_added: '1.0.0'
description:
  - Delegates archive creation to M(community.general.archive) with gzip compression and mode C(0600).
  - Displays compressed archive size and elapsed time every five seconds while the archive is created.
  - Progress uses the local connection and does not disclose archived filenames.
  - Check mode and tasks marked C(no_log) do not display progress.
options:
  path:
    description: Source files or directories passed to the archive module.
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
    description: Patterns excluded using the archive module's existing matching rules.
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
    description: Delegates preview behavior to the archive module without starting progress monitoring.
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
  description: Archive destination returned by the delegated archive module.
  type: str
  returned: success
"""
