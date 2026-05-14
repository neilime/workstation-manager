"""Helpers for restoring SSH keys from Bitwarden item payloads."""

from __future__ import annotations

from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    bitwarden_item_fields,
)

BitwardenItemFieldReader = bitwarden_item_fields.BitwardenItemFieldReader


# pylint: disable=too-few-public-methods
class BitwardenSshKeyRestorePlanner:
    """Build an SSH-key restore plan from a Bitwarden item payload."""

    def __init__(self) -> None:
        self._reader = BitwardenItemFieldReader()

    def build_plan(
        self,
        item_payload: dict[str, object],
        user_home: str,
    ) -> dict[str, object]:
        """Return the file restore plan for a Bitwarden SSH-key item."""

        item_name = self._key_name(item_payload.get("name"))
        private_path = str(Path(user_home) / ".ssh" / item_name)
        public_path = f"{private_path}.pub"

        return {
            "item_id": self._reader.required_string(item_payload.get("id"), "item.id"),
            "name": item_name,
            "private": {
                "dest": private_path,
                "mode": "0600",
                "content": self._reader.content_with_trailing_newline(
                    self._reader.field_value(item_payload, "private_key"),
                    "private_key",
                ),
            },
            "public": {
                "dest": public_path,
                "mode": "0644",
                "content": self._reader.content_with_trailing_newline(
                    self._reader.field_value(item_payload, "public_key"),
                    "public_key",
                ),
            },
        }

    def _key_name(self, value: object) -> str:
        """Return a safe SSH key filename derived from the Bitwarden item name."""

        key_name = self._reader.required_string(value, "item.name")
        if Path(key_name).name != key_name or key_name in {".", ".."}:
            raise ValueError("item.name must be a single SSH key filename")

        return key_name
