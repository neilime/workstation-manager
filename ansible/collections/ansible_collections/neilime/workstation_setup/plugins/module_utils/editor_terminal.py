"""Configure a host Zsh terminal without rewriting personal VS Code JSONC settings."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils.jsonc_document import (
    JsoncDocument,
)


# The editor exposes the single configuration operation used by its module.
# pylint: disable-next=too-few-public-methods
class EditorTerminalSettings:
    """Configure native Zsh while preserving personal editor settings."""

    def configure(self, content: str) -> str:
        """Preserve comments, unrelated settings and profiles, including trailing commas."""
        document = JsoncDocument()
        settings = document.loads(content)
        if not isinstance(settings.get("terminal.integrated.profiles.linux", {}), dict):
            raise ValueError("VS Code terminal profiles must be a JSONC object.")
        content = document.set(
            content, ("terminal.integrated.profiles.linux", "zsh"), {"path": "/usr/bin/zsh", "args": ["-l"]}
        )
        return document.set(content, ("terminal.integrated.defaultProfile.linux",), "zsh")
