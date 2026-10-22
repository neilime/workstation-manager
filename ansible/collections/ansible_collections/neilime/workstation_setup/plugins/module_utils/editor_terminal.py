"""Configure the native terminal and clipboard without rewriting personal VS Code JSONC."""

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
            raise ValueError(  # noqa: TRY004 - Schema validation reports ValueError.
                "VS Code terminal profiles must be a JSONC object."
            )
        content = document.set(
            content, ("terminal.integrated.profiles.linux", "zsh"), {"path": "/usr/bin/zsh", "args": ["-l"]}
        )
        return document.set(content, ("terminal.integrated.defaultProfile.linux",), "zsh")


# The module selects the appropriate document configurator.
# pylint: disable-next=too-few-public-methods
class EditorTerminalKeybindings:
    """Route terminal paste shortcuts to the same clipboard as the Paste menu."""

    def configure(self, content: str) -> str:
        """Keep personal bindings and add terminal-scoped overrides with higher priority."""
        bindings = [
            {"key": key, "command": "workbench.action.terminal.paste", "when": "terminalFocus"}
            for key in ("ctrl+v", "shift+insert")
        ]
        return JsoncDocument().append_keybindings(content, bindings)
