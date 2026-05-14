"""Helpers for planning managed browser profile paths."""

from __future__ import annotations

import re


# pylint: disable=too-few-public-methods
class BrowserProfilePathsPlanner:
    """Plan stable paths for managed browser profiles."""

    _profile_id_pattern = re.compile(r"^[a-z0-9][a-z0-9-]*$")

    def build_profiles_root_dir(self, user_home: str) -> str:
        """Return the stable root directory for managed browser profiles."""

        normalized_user_home = self._normalize_required_value(user_home, "user_home")
        return (
            f"{normalized_user_home}/.local/share/workstation-manager/browser-profiles"
        )

    def build_profile_directory(self, profiles_root_dir: str, profile_id: str) -> str:
        """Return the stable path for one declared browser profile."""

        normalized_profiles_root_dir = self._normalize_required_value(
            profiles_root_dir,
            "profiles_root_dir",
        )
        normalized_profile_id = self.validate_profile_id(profile_id)

        return f"{normalized_profiles_root_dir}/{normalized_profile_id}"

    def has_valid_profile_id(self, profile_id: object) -> bool:
        """Return whether the given profile id matches the supported slug format."""

        if not isinstance(profile_id, str):
            return False

        normalized_profile_id = profile_id.strip()
        if not normalized_profile_id:
            return False

        return self._profile_id_pattern.match(normalized_profile_id) is not None

    def validate_profile_id(self, profile_id: str) -> str:
        """Return a validated browser profile id."""

        normalized_profile_id = self._normalize_required_value(profile_id, "profile_id")
        if not self.has_valid_profile_id(normalized_profile_id):
            raise ValueError(
                "profile_id must use only lowercase letters, numbers, and dashes"
            )

        return normalized_profile_id

    def _normalize_required_value(self, value: str, name: str) -> str:
        """Validate that required string inputs are present."""

        normalized_value = (value or "").strip()
        if not normalized_value:
            raise ValueError(f"{name} must not be empty")

        return normalized_value
