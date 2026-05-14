"""Development section normalization for the desired state schema."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    desired_state_support,
)


# pylint: disable=too-few-public-methods
class DevelopmentSectionNormalizer(
    desired_state_support.DesiredStateDefaultsSectionNormalizer
):
    """Normalize the development section of the desired-state schema."""

    def _normalize(
        self, config: dict[str, object], defaults: dict[str, object]
    ) -> dict[str, object]:
        development = self._resolver.mapping(
            config.get("development"), "workstation_manager.development"
        )
        repositories = self._resolver.mapping(
            development.get("repositories"),
            "workstation_manager.development.repositories",
        )
        mise = self._resolver.mapping(
            development.get("mise"), "workstation_manager.development.mise"
        )
        settings = self._resolver.mapping(
            development.get("settings"), "workstation_manager.development.settings"
        )
        default_mise = self._resolver.mapping(
            defaults.get("mise"), "workstation_manager.development.defaults.mise"
        )
        default_repositories = self._resolver.mapping(
            defaults.get("repositories"),
            "workstation_manager.development.defaults.repositories",
        )
        default_settings = self._resolver.mapping(
            defaults.get("settings"),
            "workstation_manager.development.defaults.settings",
        )

        return {
            "packages": self._resolver.list_value(
                self._resolver.value_or_default(
                    development.get("packages"),
                    defaults.get("packages"),
                ),
                "workstation_manager.development.packages",
            ),
            "repositories": self._resolver.apt_repositories(
                repositories,
                default_repositories,
                "workstation_manager.development.repositories",
            ),
            "editor_packages": self._resolver.list_value(
                self._resolver.value_or_default(
                    development.get("editor_packages"),
                    defaults.get("editor_packages"),
                ),
                "workstation_manager.development.editor_packages",
            ),
            "mise": {
                "tools": self._resolver.mapping(
                    self._resolver.value_or_default(
                        mise.get("tools"), default_mise.get("tools")
                    ),
                    "workstation_manager.development.mise.tools",
                ),
                "gh_extensions": self._resolver.list_value(
                    self._resolver.value_or_default(
                        mise.get("gh_extensions"),
                        default_mise.get("gh_extensions"),
                    ),
                    "workstation_manager.development.mise.gh_extensions",
                ),
                "docker_cli_plugins": self._resolver.list_value(
                    self._resolver.value_or_default(
                        mise.get("docker_cli_plugins"),
                        default_mise.get("docker_cli_plugins"),
                    ),
                    "workstation_manager.development.mise.docker_cli_plugins",
                ),
            },
            "settings": self._resolver.sysctl_settings(
                settings,
                default_settings,
                "workstation_manager.development.settings",
            ),
            "runtimes": self._resolver.mapping(
                self._resolver.value_or_default(
                    development.get("runtimes"),
                    defaults.get("runtimes"),
                ),
                "workstation_manager.development.runtimes",
            ),
        }
