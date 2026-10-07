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
        clipboard = self._clipboard(desktop)
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
        favorites = self._resolver.value_or_default(gnome.get("favorites"), default_gnome.get("favorites"))
        if favorites is not None:
            favorites = self._resolver.list_value(favorites, "workstation_manager.desktop.gnome.favorites")

        packages = self._resolver.list_value(
            self._resolver.value_or_default(flatpak.get("packages"), default_flatpak.get("packages")),
            "workstation_manager.desktop.flatpak.packages",
        )
        if "org.gnome.SimpleScan" in packages:
            raise ValueError(
                "Simple Scan is installed through APT; remove org.gnome.SimpleScan from desktop.flatpak.packages"
            )
        if "com.github.hluk.copyq" in packages:
            raise ValueError(
                "Clipboard Indicator replaces CopyQ; remove com.github.hluk.copyq from desktop.flatpak.packages"
            )

        return {
            "clipboard_indicator": clipboard,
            "flatpak": {
                "remote": self._resolver.first_non_empty_string(
                    flatpak.get("remote"),
                    default_flatpak.get("remote"),
                ),
                "packages": packages,
            },
            "browser": browser,
            "gnome": {"favorites": favorites},
        }

    def _clipboard(self, desktop: dict[str, object]) -> dict[str, object]:
        """Require reviewed pins for the managed clipboard extension."""
        clipboard = self._resolver.mapping(
            desktop.get("clipboard_indicator"),
            "desktop.clipboard_indicator",
            allowed_keys={"version", "sha256"},
        )
        for field, pattern in (("version", r"[1-9][0-9]*"), ("sha256", r"[0-9a-f]{64}")):
            value = clipboard.get(field)
            if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
                raise ValueError(f"desktop.clipboard_indicator.{field} requires an explicit valid pin")
        return clipboard
