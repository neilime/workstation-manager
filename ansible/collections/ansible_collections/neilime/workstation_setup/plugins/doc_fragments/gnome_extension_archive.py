# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Shared documentation for managed GNOME extension archive checks."""

from __future__ import annotations


# Ansible documentation fragments are declarative containers.
class ModuleDocFragment:  # pylint: disable=too-few-public-methods
    """Document the pinned artifact and Shell compatibility inputs."""

    DOCUMENTATION = r"""
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
