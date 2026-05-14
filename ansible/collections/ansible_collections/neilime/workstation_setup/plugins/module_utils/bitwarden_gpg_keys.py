"""Helpers for restoring GPG keys from Bitwarden item payloads."""

from __future__ import annotations

import re

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    bitwarden_item_fields,
)

BitwardenItemFieldReader = bitwarden_item_fields.BitwardenItemFieldReader


# pylint: disable=too-few-public-methods
class BitwardenGpgKeyRestorePlanner:
    """Build a GPG-key restore plan from a Bitwarden item payload."""

    _OPENPGP_ARMOR_PATTERN = re.compile(
        r"^(-----BEGIN PGP [A-Z ]+-----)\s+(.*)\s+(-----END PGP [A-Z ]+-----)$",
        re.DOTALL,
    )

    def __init__(self) -> None:
        self._reader = BitwardenItemFieldReader()

    def build_plan(self, item_payload: dict[str, object]) -> dict[str, object]:
        """Return the import plan for a Bitwarden GPG-key item."""

        ownertrust = self._reader.optional_field_value(item_payload, "ownertrust")
        sub_private_key = self._reader.optional_field_value(
            item_payload, "sub_private_key"
        )

        return {
            "item_id": self._reader.required_string(item_payload.get("id"), "item.id"),
            "name": self._reader.required_string(item_payload.get("name"), "item.name"),
            "fingerprint": self._resolved_fingerprint(item_payload, ownertrust),
            "private_key": self._secret_key_content(
                self._reader.field_value(item_payload, "private_key"),
                sub_private_key,
            ),
            "public_key": self._armored_content_with_trailing_newline(
                self._reader.field_value(item_payload, "public_key"),
                "public_key",
            ),
            "ownertrust": self._optional_content_with_trailing_newline(
                ownertrust,
            ),
        }

    def _resolved_fingerprint(
        self,
        item_payload: dict[str, object],
        ownertrust: str | None,
    ) -> str:
        """Return the declared fingerprint or derive it from ownertrust."""

        fingerprint = self._reader.optional_field_value(item_payload, "fingerprint")
        if fingerprint is not None:
            return self._fingerprint(fingerprint)

        if ownertrust is not None:
            return self._fingerprint(self._ownertrust_fingerprint(ownertrust))

        raise ValueError("Bitwarden item is missing field 'fingerprint'")

    def _ownertrust_fingerprint(self, ownertrust: str) -> str:
        """Return the leading fingerprint from an ownertrust entry."""

        fingerprint = ownertrust.partition(":")[0]
        normalized_fingerprint = fingerprint.strip()
        if not normalized_fingerprint:
            raise ValueError("ownertrust must start with a fingerprint")

        return normalized_fingerprint

    def _secret_key_content(
        self,
        private_key: str,
        sub_private_key: str | None,
    ) -> str:
        """Return the normalized secret-key import payload."""

        secret_blocks = [
            self._armored_content_with_trailing_newline(private_key, "private_key")
        ]
        if sub_private_key is not None:
            secret_blocks.append(
                self._armored_content_with_trailing_newline(
                    sub_private_key,
                    "sub_private_key",
                )
            )

        return "".join(secret_blocks)

    def _armored_content_with_trailing_newline(self, value: str, name: str) -> str:
        """Normalize Bitwarden-exported OpenPGP armor to a newline-delimited block."""

        normalized_value = self._reader.content_with_trailing_newline(value, name)
        return self._normalized_openpgp_armor(normalized_value)

    def _normalized_openpgp_armor(self, value: str) -> str:
        """Return multiline OpenPGP armor when Bitwarden has flattened the block."""

        stripped_value = value.strip()
        if "\n" in stripped_value:
            return value

        armor_match = self._OPENPGP_ARMOR_PATTERN.match(stripped_value)
        if armor_match is None:
            return value

        header, body, footer = armor_match.groups()
        normalized_body = "\n".join(
            segment for segment in re.split(r"\s+", body) if segment
        )
        return f"{header}\n\n{normalized_body}\n{footer}\n"

    def _fingerprint(self, value: str) -> str:
        """Return a normalized GPG fingerprint."""

        fingerprint = value.replace(" ", "").upper()
        if not fingerprint.isalnum():
            raise ValueError("fingerprint must contain only hexadecimal characters")
        if len(fingerprint) < 16:
            raise ValueError("fingerprint must be at least 16 characters")

        return fingerprint

    def _optional_content_with_trailing_newline(self, value: str | None) -> str | None:
        """Normalize optional ownertrust content to a single trailing newline."""

        if value is None:
            return None

        return f"{value.rstrip('\n')}\n"
