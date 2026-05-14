"""Secrets section normalization for the desired state schema."""

from __future__ import annotations

import re

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    desired_state_support,
)


# pylint: disable=too-few-public-methods
class SecretsSectionNormalizer(
    desired_state_support.DesiredStateDefaultsSectionNormalizer
):
    """Normalize the secrets section of the desired-state schema."""

    _UUID_PATTERN = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )

    def _normalize(
        self, config: dict[str, object], defaults: dict[str, object]
    ) -> dict[str, object]:
        secrets = self._resolver.mapping(
            config.get("secrets"), "workstation_manager.secrets"
        )
        bitwarden = self._resolver.mapping(
            secrets.get("bitwarden"), "workstation_manager.secrets.bitwarden"
        )
        default_bitwarden = self._resolver.mapping(
            defaults.get("bitwarden"), "workstation_manager.secrets.defaults.bitwarden"
        )
        server = self._optional_string_value(
            self._resolver.value_or_default(
                bitwarden.get("server"),
                default_bitwarden.get("server"),
            ),
            "workstation_manager.secrets.bitwarden.server",
        )
        ssh_collection_id = self._optional_uuid_string_value(
            self._resolver.value_or_default(
                bitwarden.get("ssh_collection_id"),
                default_bitwarden.get("ssh_collection_id"),
            ),
            "workstation_manager.secrets.bitwarden.ssh_collection_id",
        )
        gpg_collection_id = self._optional_uuid_string_value(
            self._resolver.value_or_default(
                bitwarden.get("gpg_collection_id"),
                default_bitwarden.get("gpg_collection_id"),
            ),
            "workstation_manager.secrets.bitwarden.gpg_collection_id",
        )
        has_declared_collection = bool(ssh_collection_id or gpg_collection_id)

        if has_declared_collection and not server:
            raise ValueError(
                "workstation_manager.secrets.bitwarden.server must not be empty"
            )

        return {
            "bitwarden": {
                "server": server,
                "ssh_collection_id": ssh_collection_id,
                "gpg_collection_id": gpg_collection_id,
            },
        }

    def _optional_string_value(self, value: object, name: str) -> str:
        """Return a trimmed string, allowing the empty default placeholder."""

        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")

        return value.strip()

    def _optional_uuid_string_value(self, value: object, name: str) -> str:
        """Return a trimmed UUID string, allowing the empty default placeholder."""

        normalized_value = self._optional_string_value(value, name)
        if normalized_value and not self._UUID_PATTERN.match(normalized_value):
            raise ValueError(f"{name} must be a UUID string")

        return normalized_value
