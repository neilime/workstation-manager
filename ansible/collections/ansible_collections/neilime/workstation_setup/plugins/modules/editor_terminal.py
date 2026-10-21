#!/usr/bin/python
# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Configure the native VS Code terminal shell and clipboard paste shortcuts."""

from __future__ import annotations

# Ansible requires each module to repeat its own argument and check-mode documentation.
# pylint: disable=duplicate-code
DOCUMENTATION = r"""
---
module: editor_terminal
short_description: Configure the native VS Code terminal
version_added: "1.0.0"
description:
  - Adds a C(zsh) terminal profile using the native C(/usr/bin/zsh) executable.
  - Selects that profile as the Linux default and preserves other settings and terminal profiles.
  - Preserves other profiles and sync preferences.
  - Supports JSONC comments and trailing commas without rewriting unrelated text.
  - Follows settings-file symlinks and preserves existing file permissions and ownership.
  - Can configure terminal paste shortcuts to read the regular clipboard.
options:
  path:
    description: Absolute path to the managed user's VS Code settings or keybindings file.
    type: path
    required: true
  kind:
    description: The VS Code configuration document to update.
    type: str
    choices: [settings, keybindings]
    default: settings
author:
  - workstation-manager contributors (@neilime)
attributes:
  check_mode:
    description: Inspect settings without creating directories or modifying files.
    support: full
"""

# pylint: enable=duplicate-code

EXAMPLES = r"""
- name: Configure native Zsh for VS Code
  neilime.workstation_setup.editor_terminal:
    path: /home/user/.config/Code/User/settings.json

- name: Configure terminal clipboard paste shortcuts
  neilime.workstation_setup.editor_terminal:
    path: /home/user/.config/Code/User/keybindings.json
    kind: keybindings
"""

RETURN = r"""
path:
  description: Configuration file updated for the managed user.
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
    EditorTerminalKeybindings,
    EditorTerminalSettings,
)

# pylint: enable=wrong-import-position


def main() -> None:
    """Read privately and publish an atomic settings update under the task's user."""

    module = AnsibleModule(
        argument_spec={
            "path": {"type": "path", "required": True},
            "kind": {"type": "str", "choices": ["settings", "keybindings"], "default": "settings"},
        },
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
            original = "[]\n" if module.params["kind"] == "keybindings" else "{}\n"
        configurator = (
            EditorTerminalKeybindings() if module.params["kind"] == "keybindings" else EditorTerminalSettings()
        )
        updated = configurator.configure(original)
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
