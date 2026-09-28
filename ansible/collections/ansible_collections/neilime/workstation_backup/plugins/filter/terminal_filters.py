"""Filter plugins for readable interactive backup prompts."""

from __future__ import annotations

from ansible_collections.neilime.workstation_backup.plugins.module_utils.terminal import (
    terminal_prompt,
)


# pylint: disable=too-few-public-methods
class FilterModule:
    """Expose terminal formatting helpers as Ansible filters."""

    def filters(self) -> dict[str, object]:
        """Return the filters provided by this collection."""

        return {"terminal_prompt": terminal_prompt}
