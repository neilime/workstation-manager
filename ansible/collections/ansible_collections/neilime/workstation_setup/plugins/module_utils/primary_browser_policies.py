"""Helpers for rendering primary-browser policy payloads."""

from __future__ import annotations


# pylint: disable=too-few-public-methods
class PrimaryBrowserPoliciesPlanner:
    """Build Chrome-managed policy payloads from repository data."""

    _default_extension_update_url = "https://clients2.google.com/service/update2/crx"

    def build_policy_payload(
        self, policy_inputs: dict[str, object] | None
    ) -> dict[str, object]:
        """Return the managed policy payload for the primary browser."""

        normalized_policy_inputs = self._normalize_mapping(
            policy_inputs or {}, "policy_inputs"
        )
        policy_payload: dict[str, object] = {}

        extension_settings = self._build_extension_settings(normalized_policy_inputs)
        if extension_settings:
            policy_payload["ExtensionSettings"] = extension_settings

        if "managed_bookmarks" in normalized_policy_inputs:
            raise ValueError(
                "policy_inputs.managed_bookmarks is not supported; "
                "bookmarks belong to browser profiles, sync, or export flows"
            )

        password_manager = self._normalize_mapping(
            normalized_policy_inputs.get("password_manager") or {},
            "policy_inputs.password_manager",
        )
        if "enabled" in password_manager:
            policy_payload["PasswordManagerEnabled"] = self._normalize_bool(
                password_manager.get("enabled"),
                "policy_inputs.password_manager.enabled",
            )

        startup = self._normalize_mapping(
            normalized_policy_inputs.get("startup") or {},
            "policy_inputs.startup",
        )
        if "bookmark_bar_enabled" in startup:
            policy_payload["BookmarkBarEnabled"] = self._normalize_bool(
                startup.get("bookmark_bar_enabled"),
                "policy_inputs.startup.bookmark_bar_enabled",
            )
        if "restore_on_startup" in startup:
            policy_payload["RestoreOnStartup"] = self._normalize_int(
                startup.get("restore_on_startup"),
                "policy_inputs.startup.restore_on_startup",
            )
        startup_urls = self._normalize_list(
            startup.get("restore_on_startup_urls"),
            "policy_inputs.startup.restore_on_startup_urls",
        )
        if startup_urls:
            policy_payload["RestoreOnStartupURLs"] = startup_urls

        third_party_password_manager = self._normalize_mapping(
            normalized_policy_inputs.get("third_party_password_manager") or {},
            "policy_inputs.third_party_password_manager",
        )
        if third_party_password_manager:
            extension_id = self._normalize_required_string(
                third_party_password_manager.get("extension_id"),
                "policy_inputs.third_party_password_manager.extension_id",
            )
            extension_policy = self._normalize_mapping(
                third_party_password_manager.get("policy") or {},
                "policy_inputs.third_party_password_manager.policy",
            )
            policy_payload["3rdparty"] = {
                "extensions": {extension_id: extension_policy}
            }

        return policy_payload

    def _build_extension_settings(
        self, policy_inputs: dict[str, object]
    ) -> dict[str, dict[str, str]]:
        """Build Chrome ExtensionSettings entries from repository inputs."""

        extension_settings: dict[str, dict[str, str]] = {}
        baseline_extensions = self._normalize_list(
            policy_inputs.get("baseline_extensions"),
            "policy_inputs.baseline_extensions",
        )

        for extension in baseline_extensions:
            normalized_extension = self._normalize_mapping(
                extension,
                "policy_inputs.baseline_extensions[]",
            )
            extension_id = self._normalize_required_string(
                normalized_extension.get("id"),
                "policy_inputs.baseline_extensions[].id",
            )
            installation_mode = self._normalize_optional_string(
                normalized_extension.get("installation_mode"),
                default="force_installed",
            )
            update_url = self._normalize_optional_string(
                normalized_extension.get("update_url"),
                default=self._default_extension_update_url,
            )
            extension_settings[extension_id] = {
                "installation_mode": installation_mode,
                "update_url": update_url,
            }

        third_party_password_manager = self._normalize_mapping(
            policy_inputs.get("third_party_password_manager") or {},
            "policy_inputs.third_party_password_manager",
        )
        if third_party_password_manager:
            extension_id = self._normalize_required_string(
                third_party_password_manager.get("extension_id"),
                "policy_inputs.third_party_password_manager.extension_id",
            )
            installation_mode = self._normalize_optional_string(
                third_party_password_manager.get("installation_mode"),
                default="force_installed",
            )
            update_url = self._normalize_optional_string(
                third_party_password_manager.get("update_url"),
                default=self._default_extension_update_url,
            )
            extension_settings[extension_id] = {
                "installation_mode": installation_mode,
                "update_url": update_url,
            }

        return extension_settings

    def _normalize_mapping(self, value: object, name: str) -> dict[str, object]:
        """Return a mapping or raise a clear type error."""

        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be a mapping")

        return value

    def _normalize_list(self, value: object, name: str) -> list[object]:
        """Return a list or raise a clear type error."""

        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")

        return value

    def _normalize_required_string(self, value: object, name: str) -> str:
        """Return a required non-empty string input."""

        normalized_value = self._normalize_optional_string(value)
        if not normalized_value:
            raise ValueError(f"{name} must not be empty")

        return normalized_value

    def _normalize_optional_string(self, value: object, default: str = "") -> str:
        """Return a normalized string value or a default."""

        if value is None:
            return default
        if not isinstance(value, str):
            raise ValueError("string values must be strings")

        normalized_value = value.strip()
        if not normalized_value:
            return default

        return normalized_value

    def _normalize_bool(self, value: object, name: str) -> bool:
        """Return a boolean policy value or raise a clear type error."""

        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")

        return value

    def _normalize_int(self, value: object, name: str) -> int:
        """Return an integer policy value or raise a clear type error."""

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")

        return value
