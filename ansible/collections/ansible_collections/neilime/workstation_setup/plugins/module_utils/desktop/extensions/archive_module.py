"""Adapt managed GNOME extension archive validation to Ansible."""

from __future__ import annotations

import zipfile
from collections.abc import Callable

from ansible.module_utils.basic import AnsibleModule


def run_archive_module(validator: Callable[[str, str, str, str], dict[str, object]], label: str) -> None:
    """Expose read-only archive checks with consistent arguments and failure reporting."""
    module = AnsibleModule(
        argument_spec={
            "path": {"type": "path", "required": True},
            "sha256": {"type": "str", "required": True},
            "version": {"type": "str", "required": True},
            "shell_version": {"type": "str", "required": True},
        },
        supports_check_mode=True,
    )
    try:
        metadata = validator(
            module.params["path"], module.params["sha256"], module.params["version"], module.params["shell_version"]
        )
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        module.fail_json(msg=f"Cannot install {label}: {error}")
    module.exit_json(changed=False, metadata=metadata)
