#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Expose only the effective user's allowed desktop environment variables."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: desktop_session_info
short_description: Discover the managed user's live desktop session
version_added: '1.0.0'
description:
  - Reads the effective user's systemd environment to discover displays published after GNOME starts.
  - Returns only desktop connection variables and a sanitized base environment, without credentials.
  - Run as the managed desktop user using become_user when needed.
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: This read-only query works unchanged in check mode.
    support: full
"""

EXAMPLES = r"""
- name: Discover the managed desktop
  become: true
  become_user: workstation
  neilime.workstation_setup.desktop_session_info:
  register: desktop_session
"""

RETURN = r"""
available:
  description: A Wayland or X11 display is present in the discovered environment.
  returned: success
  type: bool
environment:
  description: Allowlisted desktop connection variables and a sanitized base environment.
  returned: success
  type: dict
"""

# pylint: disable=wrong-import-position
from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desktop_session import (  # noqa: E402
    DesktopSession,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Report session access without changing the desktop or returning raw command output."""
    module = AnsibleModule(argument_spec={}, supports_check_mode=True)
    try:
        environment = DesktopSession.environment()
    except ValueError as error:
        module.fail_json(msg=str(error))
    except OSError:
        module.fail_json(msg="Cannot discover the managed desktop session; log in to GNOME and retry")
    module.exit_json(
        changed=False,
        available=bool(environment.get("DISPLAY") or environment.get("WAYLAND_DISPLAY")),
        environment=environment,
    )


if __name__ == "__main__":
    main()
