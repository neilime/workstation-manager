"""Helpers for VS Code settings sync during workstation setup."""

from __future__ import annotations


class VscodeSettingsSyncPlanner:
    """Plan when workstation setup should request or remind about VS Code settings sync."""

    _VSCODE_FLATPAK_APP_ID = "com.visualstudio.code"

    def build_sync_state_dir(self, user_home: str) -> str:
        """Return the VS Code sync state directory under the managed home."""

        normalized_user_home = user_home.strip()
        if not normalized_user_home:
            raise ValueError("user_home must not be empty")
        return normalized_user_home.rstrip("/") + "/.config/Code/User/sync"

    def has_vscode_editor_package(self, editor_packages: list[object]) -> bool:
        """Return whether the managed editor set includes VS Code."""

        return self._VSCODE_FLATPAK_APP_ID in editor_packages

    def should_request_sync(
        self,
        editor_packages: list[object],
        sync_state_exists: bool,
        has_desktop_session: bool,
        interactive: bool,
        check_mode: bool,
    ) -> bool:
        """Return whether setup should request the VS Code sync-on flow."""

        return (
            self.has_vscode_editor_package(editor_packages)
            and not sync_state_exists
            and has_desktop_session
            and interactive
            and not check_mode
        )

    def should_remind_sync(
        self,
        editor_packages: list[object],
        sync_state_exists: bool,
        interactive: bool,
        check_mode: bool,
    ) -> bool:
        """Return whether setup should remind the user to enable settings sync."""

        return (
            self.has_vscode_editor_package(editor_packages) and not sync_state_exists and interactive and not check_mode
        )
