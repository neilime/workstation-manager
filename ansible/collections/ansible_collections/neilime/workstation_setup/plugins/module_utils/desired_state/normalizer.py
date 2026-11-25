"""Facade for desired state normalization."""

from __future__ import annotations

from typing import Any

from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    desktop as desired_state_desktop,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    development as desired_state_development,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    home_environment as desired_state_home_environment,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    secrets as desired_state_secrets,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    support as desired_state_support,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    system as desired_state_system,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    user as desired_state_user,
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
    ) -> dict[str, dict[str, Any]]:
        """Normalize merged configuration, requiring dependency versions from config."""

        resolver = desired_state_support.DesiredStateValueResolver()
        defaults_factory = desired_state_support.DesiredStateDefaultsFactory(self._state_slug)
        config = resolver.mapping(raw_config, "workstation_manager")
        environment = env or {}
        defaults = defaults_factory.build()
        user = desired_state_user.UserSectionNormalizer(resolver, self._state_slug).normalize(config, environment)

        secrets = desired_state_secrets.SecretsSectionNormalizer(resolver).normalize(
            config,
            resolver.mapping(defaults.get("secrets"), "workstation_manager.secrets.defaults"),
        )

        return {
            "user": user,
            "system": desired_state_system.SystemSectionNormalizer(resolver).normalize(
                config,
                environment,
                resolver.mapping(defaults.get("system"), "workstation_manager.system.defaults"),
            ),
            "desktop": desired_state_desktop.DesktopSectionNormalizer(resolver).normalize(
                config,
                resolver.mapping(defaults.get("desktop"), "workstation_manager.desktop.defaults"),
            ),
            "development": desired_state_development.DevelopmentSectionNormalizer(resolver).normalize(
                config,
                resolver.mapping(
                    defaults.get("development"),
                    "workstation_manager.development.defaults",
                ),
                secrets["bitwarden"],
            ),
            "home_environment": desired_state_home_environment.HomeEnvironmentSectionNormalizer(resolver).normalize(
                config,
                resolver.mapping(
                    defaults.get("home_environment"),
                    "workstation_manager.home_environment.defaults",
                ),
            ),
            "secrets": secrets,
        }
