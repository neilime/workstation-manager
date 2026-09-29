"""Helpers for restoring SSH keys from Bitwarden item payloads."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    bitwarden_item_fields,
)

BitwardenItemFieldReader = bitwarden_item_fields.BitwardenItemFieldReader


class SshKeyFile(TypedDict):
    """Validated key content and destination for one restored file."""

    dest: str
    mode: str
    content: str


class SshKeyRestorePlan(TypedDict):
    """A vault key identity and its private/public file pair."""

    item_id: str
    name: str
    private: SshKeyFile
    public: SshKeyFile


# pylint: disable=too-few-public-methods
class BitwardenSshKeyRestorePlanner:
    """Build an SSH-key restore plan from a Bitwarden item payload."""

    def __init__(self) -> None:
        self._reader = BitwardenItemFieldReader()

    def build_plan(
        self,
        item_payload: dict[str, object],
        user_home: str,
    ) -> SshKeyRestorePlan:
        """Return the file restore plan for a Bitwarden SSH-key item."""

        item_name = self._key_name(item_payload.get("name"))
        private_key = self._reader.field_value(item_payload, "private_key")
        public_key = self._reader.field_value(item_payload, "public_key")
        if re.search(r"^-----BEGIN ([A-Z0-9]+ )?PRIVATE KEY-----", public_key, re.MULTILINE):
            raise ValueError(
                f"Bitwarden SSH key {item_name!r} has private key material in 'public_key'. "
                "Check whether 'private_key' and 'public_key' are swapped before restoring."
            )

        private_path = str(Path(user_home) / ".ssh" / item_name)
        public_path = f"{private_path}.pub"

        return {
            "item_id": self._reader.required_string(item_payload.get("id"), "item.id"),
            "name": item_name,
            "private": {
                "dest": private_path,
                "mode": "0600",
                "content": self._reader.content_with_trailing_newline(
                    private_key,
                    "private_key",
                ),
            },
            "public": {
                "dest": public_path,
                "mode": "0644",
                "content": self._reader.content_with_trailing_newline(
                    public_key,
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
