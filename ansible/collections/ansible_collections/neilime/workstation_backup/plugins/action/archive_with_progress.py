"""Run the project archive writer and display progress on the controller."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any

from ansible.errors import AnsibleActionFail
from ansible.plugins.action import ActionBase
from ansible.utils.display import Display
from ansible_collections.neilime.workstation_backup.plugins.module_utils.archive_progress import (
    archive_progress,
)


# Ansible actions expose the single run entrypoint required by ActionBase.
# pylint: disable-next=too-few-public-methods
class ActionModule(ActionBase):
    """Observe local archive growth without changing module execution privileges."""

    _VALID_ARGS = frozenset(("path", "dest", "exclusion_patterns"))
    _supports_check_mode = True

    def run(self, tmp: str | None = None, task_vars: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a private gzip archive with periodic size and elapsed-time output."""

        # Retain Ansible's action signature without using its obsolete tmp argument.
        del tmp
        result = super().run(task_vars=task_vars)
        _validation, arguments = self.validate_argument_spec(
            argument_spec={
                "path": {"type": "list", "elements": "path", "required": True},
                "dest": {"type": "path", "required": True},
                "exclusion_patterns": {"type": "list", "elements": "str", "default": []},
            }
        )
        if self._connection.transport != "local":
            raise AnsibleActionFail("Backup archive progress requires a local Ansible connection.")
        destination = Path(arguments["dest"])
        if not destination.is_absolute():
            # The local connection executes modules from the playbook's directory.
            arguments["dest"] = str(Path(self._loader.get_basedir()) / destination)
        progress = (
            nullcontext()
            if self._task.check_mode or self._task.no_log
            else archive_progress(arguments["dest"], Display().display)
        )
        try:
            with progress:
                result.update(
                    self._execute_module(
                        module_name="neilime.workstation_backup.archive_with_progress",
                        module_args=arguments,
                        task_vars=task_vars,
                    )
                )
        except OSError as error:
            raise AnsibleActionFail(f"Backup archive operation failed: {error}") from error
        return result
