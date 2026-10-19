"""Desktop section normalization for the desired state schema."""

from __future__ import annotations

import re

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    desired_state_support,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_sync_devices import (
    disposable_device_names,
)


# pylint: disable=too-few-public-methods
class DesktopSectionNormalizer(desired_state_support.DesiredStateDefaultsSectionNormalizer):
    """Normalize the desktop section of the desired-state schema."""

    def normalize(self, config: dict[str, object], defaults: dict[str, object]) -> dict[str, object]:
        """Return the normalized desktop section."""

        desktop = self._resolver.mapping(config.get("desktop"), "workstation_manager.desktop")
        clipboard = self._pinned_extension(desktop, "clipboard_indicator")
        system_monitor = self._pinned_extension(desktop, "system_monitor")
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

        return {
            "clipboard_indicator": clipboard,
            "system_monitor": system_monitor,
            "flatpak": {
                "remote": self._resolver.first_non_empty_string(
                    flatpak.get("remote"),
                    default_flatpak.get("remote"),
                ),
                "packages": packages,
            },
            "browser": browser,
            "browser_sync_disposable_device_names": disposable_device_names(
                desktop.get(
                    "browser_sync_disposable_device_names", defaults.get("browser_sync_disposable_device_names")
                )
            ),
            "gnome": {"favorites": favorites},
        }

    def _pinned_extension(self, desktop: dict[str, object], key: str) -> dict[str, object]:
        """Require reviewed version and digest pins for a managed GNOME extension."""
        extension = self._resolver.mapping(
            desktop.get(key),
            f"desktop.{key}",
            allowed_keys={"version", "sha256"},
        )
        for field, pattern in (("version", r"[1-9][0-9]*"), ("sha256", r"[0-9a-f]{64}")):
            value = extension.get(field)
            if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
                raise ValueError(f"desktop.{key}.{field} requires an explicit valid pin")
        if extension["sha256"] == "0" * 64:
            raise ValueError(f"desktop.{key}.sha256 must be the reviewed archive digest, not an all-zero placeholder")
        return extension
