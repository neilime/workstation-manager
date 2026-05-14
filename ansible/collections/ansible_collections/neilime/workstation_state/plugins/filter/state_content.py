"""Filter plugins for rendering managed state documents."""

from __future__ import annotations

from ansible_collections.neilime.workstation_state.plugins.module_utils.managed_state import (
    ManagedStateContentBuilder,
)

_builder = ManagedStateContentBuilder()


# pylint: disable=too-few-public-methods
class FilterModule:
    """Expose managed state renderers as Ansible filters."""

    def filters(self) -> dict[str, object]:
        """Return the filters provided by this collection."""

        return {
            "managed_system_state": _builder.build_system_content,
            "managed_user_state": _builder.build_user_content,
        }
