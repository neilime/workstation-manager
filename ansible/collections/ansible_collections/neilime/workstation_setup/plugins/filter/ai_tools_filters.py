"""Filter adapters for private AI credential and resource resolution."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils.ai_tools import (
    AiToolsRuntime,
)


# Ansible filter plugins expose one registration method.
# pylint: disable-next=too-few-public-methods
class FilterModule:
    """Expose runtime planning separately from public desired state."""

    def filters(self) -> dict[str, object]:
        """Return the AI extension filters."""
        runtime = AiToolsRuntime()
        return {
            "ai_runtime_servers": runtime.servers,
            "ai_skill_sources": runtime.skills,
            "ai_credential_ids": runtime.credential_ids,
        }
