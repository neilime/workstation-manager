"""Desktop section normalization for the desired state schema."""

from __future__ import annotations

import re

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    desired_state_support,
)


# pylint: disable=too-few-public-methods
class DesktopSectionNormalizer(desired_state_support.DesiredStateDefaultsSectionNormalizer):
    """Normalize the desktop section of the desired-state schema."""

    def normalize(self, config: dict[str, object], defaults: dict[str, object]) -> dict[str, object]:
        """Return the normalized desktop section."""

        desktop = self._resolver.mapping(config.get("desktop"), "workstation_manager.desktop")
        flatpak = self._resolver.mapping(desktop.get("flatpak"), "workstation_manager.desktop.flatpak")
        browser = desktop.get("browser", defaults.get("browser"))
        if not isinstance(browser, str) or re.fullmatch(r"[a-z][a-z0-9_]*", browser) is None:
            raise ValueError(
                "workstation_manager.desktop.browser must be a browser identifier matching [a-z][a-z0-9_]*"
            )
        gnome = self._resolver.mapping(desktop.get("gnome"), "workstation_manager.desktop.gnome")
        default_flatpak = self._resolver.mapping(
            defaults.get("flatpak"), "workstation_manager.desktop.defaults.flatpak"
        )
        default_gnome = self._resolver.mapping(defaults.get("gnome"), "workstation_manager.desktop.defaults.gnome")
        preferences = {
            key: self._resolver.value_or_default(gnome.get(key), default_gnome.get(key))
            for key in ("dark_mode", "show_trash", "favorites")
        }
        for key in ("dark_mode", "show_trash"):
            if preferences[key] is not None:
                preferences[key] = self._resolver.bool_value(preferences[key], False)
        if preferences["favorites"] is not None:
            preferences["favorites"] = self._resolver.list_value(
                preferences["favorites"], "workstation_manager.desktop.gnome.favorites"
            )

        return {
            "flatpak": {
                "remote": self._resolver.first_non_empty_string(
                    flatpak.get("remote"),
                    default_flatpak.get("remote"),
                ),
                "packages": self._resolver.list_value(
                    self._resolver.value_or_default(
                        flatpak.get("packages"),
                        default_flatpak.get("packages"),
                    ),
                    "workstation_manager.desktop.flatpak.packages",
                ),
            },
            "browser": browser,
            "gnome": preferences,
        }
