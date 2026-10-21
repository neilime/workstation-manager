#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Require a fresh, safely updated Chezmoi source before applying workstation settings."""

# Ansible requires the same token, author, and check-mode documentation schema as other modules.
# pylint: disable=duplicate-code
DOCUMENTATION = r"""
---
module: chezmoi_source
short_description: Fast-forward the managed Chezmoi source to its fetched tracking branch
version_added: "1.0.0"
description:
  - Fetches the existing remote tracking branch before inspecting or applying dotfiles.
  - Rejects local changes, unpublished commits, detached checkouts, and unfinished Git operations.
  - Fast-forwards clean checkouts without resetting, rebasing, committing, or pushing user work.
  - Leaves the existing remote and branch selection unchanged.
options:
  source:
    description: Absolute path to the existing Chezmoi source Git checkout.
    type: path
    required: true
  github_token:
    description: Optional token scoped to HTTPS requests to github.com.
    type: str
    default: ''
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Inspect local state without fetching or updating; remote freshness remains unverified.
    support: full
"""

EXAMPLES = r"""
- name: Refresh the managed Chezmoi source before dotfile inspection
  neilime.workstation_setup.chezmoi_source:
    source: /home/user/.local/share/chezmoi
"""

RETURN = r"""
revision:
  description: Verified source revision, or the existing local revision in check mode.
  type: str
  returned: success
  sample: '0123456789012345678901234567890123456789'
remote_verified:
  description: Whether the source matches the tracking branch fetched during this run.
  type: bool
  returned: success
  sample: true
"""
# pylint: enable=duplicate-code

# Ansible requires runtime imports after the module documentation.
# pylint: disable=wrong-import-position
from pathlib import Path  # noqa: E402

from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.chezmoi_source import (  # noqa: E402
    ChezmoiSourceError,
    ChezmoiSourceUpdater,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Expose safe status metadata without returning Git diagnostics or credentials."""
    module = AnsibleModule(
        argument_spec={
            "source": {"type": "path", "required": True},
            "github_token": {"type": "str", "default": "", "no_log": True},
        },
        supports_check_mode=True,
    )
    source = Path(module.params["source"])
    if not source.is_absolute():
        module.fail_json(msg="Chezmoi source must be an absolute path")
    try:
        result = ChezmoiSourceUpdater(source, module.run_command, module.params["github_token"]).ensure(
            check_mode=module.check_mode
        )
    except ChezmoiSourceError as error:
        module.fail_json(msg=str(error), changed=error.changed)
    except OSError:
        module.fail_json(msg="Cannot access Git or the Chezmoi source checkout; check its ownership and permissions")
    module.exit_json(**result)


if __name__ == "__main__":
    main()
