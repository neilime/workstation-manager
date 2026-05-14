"""Desktop section normalization for the desired state schema."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    desired_state_support,
)


# pylint: disable=too-few-public-methods
class DesktopSectionNormalizer(
    desired_state_support.DesiredStateDefaultsSectionNormalizer
):
    """Normalize the desktop section of the desired-state schema."""

    def _normalize(
        self, config: dict[str, object], defaults: dict[str, object]
    ) -> dict[str, object]:
        desktop = self._resolver.mapping(
            config.get("desktop"), "workstation_manager.desktop"
        )
        flatpak = self._resolver.mapping(
            desktop.get("flatpak"), "workstation_manager.desktop.flatpak"
        )
        browser = self._resolver.mapping(
            desktop.get("browser"), "workstation_manager.desktop.browser"
        )
        gnome = self._resolver.mapping(
            desktop.get("gnome"), "workstation_manager.desktop.gnome"
        )
        default_flatpak = self._resolver.mapping(
            defaults.get("flatpak"), "workstation_manager.desktop.defaults.flatpak"
        )
        default_browser = self._resolver.mapping(
            defaults.get("browser"), "workstation_manager.desktop.defaults.browser"
        )
        default_gnome = self._resolver.mapping(
            defaults.get("gnome"), "workstation_manager.desktop.defaults.gnome"
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
            "browser": {
                "package": self._resolver.first_non_empty_string(
                    browser.get("package"),
                    default_browser.get("package"),
                ),
                "repository": self._resolver.mapping(
                    self._resolver.value_or_default(
                        browser.get("repository"),
                        default_browser.get("repository"),
                    ),
                    "workstation_manager.desktop.browser.repository",
                ),
                "default": self._resolver.bool_value(
                    browser.get("default"),
                    self._resolver.bool_value(default_browser.get("default"), True),
                ),
                "profiles": self._resolver.list_value(
                    self._resolver.value_or_default(
                        browser.get("profiles"),
                        default_browser.get("profiles"),
                    ),
                    "workstation_manager.desktop.browser.profiles",
                ),
                "policies": self._resolver.mapping(
                    self._resolver.value_or_default(
                        browser.get("policies"),
                        default_browser.get("policies"),
                    ),
                    "workstation_manager.desktop.browser.policies",
                ),
            },
            "gnome": {
                "dark_mode": self._resolver.bool_value(
                    gnome.get("dark_mode"),
                    self._resolver.bool_value(default_gnome.get("dark_mode"), True),
                ),
                "favorites": self._resolver.list_value(
                    self._resolver.value_or_default(
                        gnome.get("favorites"),
                        default_gnome.get("favorites"),
                    ),
                    "workstation_manager.desktop.gnome.favorites",
                ),
            },
        }
