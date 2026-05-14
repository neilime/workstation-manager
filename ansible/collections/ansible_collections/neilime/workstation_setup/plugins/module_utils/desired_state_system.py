"""System section normalization for the desired state schema."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    desired_state_support,
)


# pylint: disable=too-few-public-methods
class SystemSectionNormalizer:
    """Normalize the system section of the desired-state schema."""

    def __init__(
        self,
        resolver: desired_state_support.DesiredStateValueResolver,
    ) -> None:
        self._resolver = resolver

    def normalize(
        self,
        config: dict[str, object],
        environment: dict[str, str],
        defaults: dict[str, object],
    ) -> dict[str, object]:
        """Return the normalized system section."""

        system = self._resolver.mapping(
            config.get("system"), "workstation_manager.system"
        )
        packages = self._resolver.mapping(
            system.get("packages"), "workstation_manager.system.packages"
        )
        repositories = self._resolver.mapping(
            system.get("repositories"), "workstation_manager.system.repositories"
        )
        services = self._resolver.mapping(
            system.get("services"), "workstation_manager.system.services"
        )
        settings = self._resolver.mapping(
            system.get("settings"), "workstation_manager.system.settings"
        )
        default_packages = self._resolver.mapping(
            defaults.get("packages"), "workstation_manager.system.defaults.packages"
        )
        default_cache_valid_time = self._resolver.int_value(
            default_packages.get("cache_valid_time"), 86400
        )
        default_repositories = self._resolver.mapping(
            defaults.get("repositories"),
            "workstation_manager.system.defaults.repositories",
        )
        default_services = self._resolver.mapping(
            defaults.get("services"),
            "workstation_manager.system.defaults.services",
        )
        default_settings = self._resolver.mapping(
            defaults.get("settings"), "workstation_manager.system.defaults.settings"
        )

        return {
            "state_dir": self._resolver.first_non_empty_string(
                environment.get("WORKSTATION_MANAGER_SYSTEM_STATE_DIR"),
                system.get("state_dir"),
                defaults.get("state_dir"),
            ),
            "locale": self._resolver.first_non_empty_string(
                system.get("locale"),
                defaults.get("locale"),
            ),
            "timezone": self._resolver.first_non_empty_string(
                system.get("timezone"),
                defaults.get("timezone"),
            ),
            "packages": {
                "prerequisites": self._resolver.list_value(
                    self._resolver.value_or_default(
                        packages.get("prerequisites"),
                        default_packages.get("prerequisites"),
                    ),
                    "workstation_manager.system.packages.prerequisites",
                ),
                "apt": self._resolver.list_value(
                    self._resolver.value_or_default(
                        packages.get("apt"),
                        default_packages.get("apt"),
                    ),
                    "workstation_manager.system.packages.apt",
                ),
                "cache_valid_time": self._resolver.int_value(
                    packages.get("cache_valid_time"), default_cache_valid_time
                ),
            },
            "repositories": self._resolver.apt_repositories(
                repositories,
                default_repositories,
                "workstation_manager.system.repositories",
            ),
            "directories": self._resolver.list_value(
                self._resolver.value_or_default(
                    system.get("directories"),
                    defaults.get("directories"),
                ),
                "workstation_manager.system.directories",
            ),
            "services": {
                "enabled": self._resolver.list_value(
                    self._resolver.value_or_default(
                        services.get("enabled"),
                        default_services.get("enabled"),
                    ),
                    "workstation_manager.system.services.enabled",
                ),
                "disabled": self._resolver.list_value(
                    self._resolver.value_or_default(
                        services.get("disabled"),
                        default_services.get("disabled"),
                    ),
                    "workstation_manager.system.services.disabled",
                ),
            },
            "settings": self._resolver.sysctl_settings(
                settings,
                default_settings,
                "workstation_manager.system.settings",
            ),
        }
