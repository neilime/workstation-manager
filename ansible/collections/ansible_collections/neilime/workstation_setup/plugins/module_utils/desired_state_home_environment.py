"""Home-environment section normalization for the desired state schema."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    desired_state_support,
)


# pylint: disable=too-few-public-methods
class HomeEnvironmentSectionNormalizer(
    desired_state_support.DesiredStateDefaultsSectionNormalizer
):
    """Normalize the home_environment section of the desired-state schema."""

    def _string_or_default(self, value: object, default: object, name: str) -> str:
        resolved = self._resolver.value_or_default(value, default)
        if not isinstance(resolved, str):
            raise ValueError(f"{name} must be a string")
        return resolved

    def _required_non_empty_string(
        self, value: object, default: object, name: str
    ) -> str:
        try:
            return self._resolver.first_non_empty_string(value, default)
        except ValueError as exc:
            raise ValueError(f"{name} must be a non-empty string") from exc

    def _normalize(
        self, config: dict[str, object], defaults: dict[str, object]
    ) -> dict[str, object]:
        home_environment = self._resolver.mapping(
            config.get("home_environment"), "workstation_manager.home_environment"
        )
        chezmoi = self._resolver.mapping(
            home_environment.get("chezmoi"),
            "workstation_manager.home_environment.chezmoi",
        )
        default_home_environment = self._resolver.mapping(
            defaults, "workstation_manager.home_environment.defaults"
        )
        default_chezmoi = self._resolver.mapping(
            default_home_environment.get("chezmoi"),
            "workstation_manager.home_environment.defaults.chezmoi",
        )

        return {
            "chezmoi": {
                "source": self._required_non_empty_string(
                    default_chezmoi.get("source"),
                    None,
                    "workstation_manager.home_environment.chezmoi.source",
                ),
                "version": self._string_or_default(
                    chezmoi.get("version"),
                    default_chezmoi.get("version"),
                    "workstation_manager.home_environment.chezmoi.version",
                ),
                "apply": self._resolver.bool_value(
                    chezmoi.get("apply"),
                    self._resolver.bool_value(
                        default_chezmoi.get("apply"),
                        True,
                    ),
                ),
                "bin_path": self._string_or_default(
                    chezmoi.get("bin_path"),
                    default_chezmoi.get("bin_path"),
                    "workstation_manager.home_environment.chezmoi.bin_path",
                ),
                "config_path": self._string_or_default(
                    chezmoi.get("config_path"),
                    default_chezmoi.get("config_path"),
                    "workstation_manager.home_environment.chezmoi.config_path",
                ),
            },
        }
