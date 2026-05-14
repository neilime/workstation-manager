"""User section normalization for the desired state schema."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    desired_state_support,
)


# pylint: disable=too-few-public-methods
class UserSectionNormalizer:
    """Normalize the user section of the desired-state schema."""

    def __init__(
        self,
        resolver: desired_state_support.DesiredStateValueResolver,
        state_slug: str,
    ) -> None:
        self._resolver = resolver
        self._state_slug = state_slug

    def normalize(
        self,
        config: dict[str, object],
        environment: dict[str, str],
    ) -> dict[str, str]:
        """Return the normalized user section."""

        user = self._resolver.mapping(config.get("user"), "workstation_manager.user")
        resolved_user_name = self._resolver.first_non_empty_string(
            environment.get("WORKSTATION_MANAGER_USER"),
            user.get("name"),
            environment.get("SUDO_USER"),
            environment.get("USER"),
            "root",
        )
        resolved_user_home = self._resolver.first_non_empty_string(
            environment.get("WORKSTATION_MANAGER_USER_HOME"),
            user.get("home"),
            f"/home/{resolved_user_name}",
        )

        return {
            "name": resolved_user_name,
            "home": resolved_user_home,
            "projects_directory": self._resolver.first_non_empty_string(
                user.get("projects_directory"),
                f"{resolved_user_home}/Documents/dev-projects",
            ),
            "state_dir": self._resolver.first_non_empty_string(
                environment.get("WORKSTATION_MANAGER_USER_STATE_DIR"),
                user.get("state_dir"),
                f"{resolved_user_home}/.local/state/{self._state_slug}",
            ),
        }
