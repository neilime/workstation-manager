# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Shared documentation for browser profile module arguments."""

from __future__ import annotations


# Ansible documentation fragments are declarative containers.
class ModuleDocFragment:  # pylint: disable=too-few-public-methods
    """Document the profile schema consumed by setup and inspection."""

    DOCUMENTATION = r"""
options:
  user_data_dir:
    description: Absolute path to the native Brave user data directory.
    required: true
    type: path
  profiles:
    description: Sanitized browser profile records loaded from the Bitwarden collection.
    type: list
    elements: dict
    default: []
    suboptions:
      id:
        description: Stable lowercase profile slug.
        type: str
        required: true
      label:
        description: Profile display name, defaulting to the profile ID.
        type: str
      directory:
        description: Existing profile basename, defaulting to managed-ID.
        type: str
      item_id:
        description: Bitwarden secure note identity containing the profile metadata and recovery words.
        type: str
        required: true
      theme_colors:
        description:
          - Optional ordered palette of one to three colors in C(#RRGGBB) format.
          - The first color selects the native profile theme; remaining colors are retained as metadata.
        type: list
        elements: str
      avatar_attachment_id:
        description: Optional Bitwarden attachment identity, never written to browser settings.
        type: str
      avatar_png:
        description: Optional base64-encoded PNG loaded from the profile's encrypted avatar attachment.
        type: str
"""
