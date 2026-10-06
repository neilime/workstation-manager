#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Configure the VS Code Flatpak's integrated terminal to use host Zsh."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: editor_terminal
short_description: Configure the VS Code Flatpak host terminal
version_added: "1.0.0"
description:
  - Adds a C(zsh (host)) terminal profile using the Flatpak's C(/app/bin/host-spawn) bridge.
  - Selects that profile as the Linux default and preserves other settings and terminal profiles.
  - Excludes Linux terminal profiles and their default selection from Settings Sync.
  - Preserves other sync exclusions and removes explicit sync opt-ins for these terminal settings.
  - Supports JSONC comments and trailing commas without rewriting unrelated text.
  - Follows settings-file symlinks and preserves existing file permissions and ownership.
options:
  path:
    description: Absolute path to the managed user's VS Code settings file.
    type: path
    required: true
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Inspect settings without creating directories or modifying files.
    support: full
"""

EXAMPLES = r"""
- name: Configure host Zsh for the VS Code Flatpak
  neilime.workstation_setup.editor_terminal:
    path: /home/user/.var/app/com.visualstudio.code/config/Code/User/settings.json
"""

RETURN = r"""
path:
  description: Settings file configured for the managed user.
  type: str
  returned: success
"""

# Ansible requires runtime imports after the module documentation.
# pylint: disable=wrong-import-position
import os  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from ansible.module_utils.basic import AnsibleModule  # noqa: E402
from ansible_collections.neilime.workstation_setup.plugins.module_utils.editor_terminal import (  # noqa: E402
    EditorTerminalSettings,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Read privately and publish an atomic settings update under the task's user."""

    module = AnsibleModule(
        argument_spec={"path": {"type": "path", "required": True}},
        supports_check_mode=True,
    )
    configured_path = Path(module.params["path"])
    if not configured_path.is_absolute():
        module.fail_json(msg="The VS Code settings path must be absolute.")
    try:
        path = configured_path.resolve()
        exists = path.exists()
        if exists:
            with path.open(encoding="utf-8", newline="") as settings_file:
                original = settings_file.read()
        else:
            original = "{}\n"
        updated = EditorTerminalSettings().configure(original)
        changed = updated != original or not exists
        if changed and not module.check_mode:
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            descriptor, temporary_path = tempfile.mkstemp(prefix=".workstation-editor-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as settings_file:
                    settings_file.write(updated)
                module.atomic_move(temporary_path, str(path))
                if not exists:
                    path.chmod(0o600)
            finally:
                Path(temporary_path).unlink(missing_ok=True)
    except (OSError, ValueError) as error:
        module.fail_json(msg=f"Cannot configure VS Code terminal at {configured_path}: {error}")
    module.exit_json(changed=changed, path=str(configured_path))


if __name__ == "__main__":
    main()
