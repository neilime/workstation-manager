"""Facade for desired state normalization."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    desired_state_desktop,
    desired_state_development,
    desired_state_home_environment,
    desired_state_secrets,
    desired_state_support,
    desired_state_system,
    desired_state_user,
)


# pylint: disable=too-few-public-methods
class DesiredStateConfigNormalizer:
    """Orchestrate the section-specific desired-state normalizers."""

    def __init__(self, state_slug: str = "workstation-manager-v1") -> None:
        self._state_slug = state_slug

    def normalize(
        self,
        raw_config: dict[str, object] | None,
        env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Return a normalized workstation_manager mapping with safe defaults."""

        resolver = desired_state_support.DesiredStateValueResolver()
        defaults_factory = desired_state_support.DesiredStateDefaultsFactory(
            self._state_slug
        )
        config = resolver.mapping(raw_config, "workstation_manager")
        environment = env or {}
        defaults = defaults_factory.build()

        return {
            "user": desired_state_user.UserSectionNormalizer(
                resolver, self._state_slug
            ).normalize(config, environment),
            "system": desired_state_system.SystemSectionNormalizer(resolver).normalize(
                config,
                environment,
                resolver.mapping(
                    defaults.get("system"), "workstation_manager.system.defaults"
                ),
            ),
            "desktop": desired_state_desktop.DesktopSectionNormalizer(
                resolver
            ).normalize(
                config,
                resolver.mapping(
                    defaults.get("desktop"), "workstation_manager.desktop.defaults"
                ),
            ),
            "development": desired_state_development.DevelopmentSectionNormalizer(
                resolver
            ).normalize(
                config,
                resolver.mapping(
                    defaults.get("development"),
                    "workstation_manager.development.defaults",
                ),
            ),
            "home_environment": desired_state_home_environment.HomeEnvironmentSectionNormalizer(
                resolver
            ).normalize(
                config,
                resolver.mapping(
                    defaults.get("home_environment"),
                    "workstation_manager.home_environment.defaults",
                ),
            ),
            "secrets": desired_state_secrets.SecretsSectionNormalizer(
                resolver
            ).normalize(
                config,
                resolver.mapping(
                    defaults.get("secrets"),
                    "workstation_manager.secrets.defaults",
                ),
            ),
        }
