"""Shared helpers for parsing Bitwarden item payloads."""

from __future__ import annotations


# pylint: disable=too-few-public-methods
class BitwardenItemFieldReader:
    """Read normalized custom-field data from Bitwarden item payloads."""

    def field_value(self, item_payload: dict[str, object], field_name: str) -> str:
        """Extract a required custom field from a Bitwarden item payload."""

        for candidate in self.fields(item_payload.get("fields")):
            if candidate["name"] == field_name:
                return self.required_string(
                    candidate.get("value"),
                    f"item.fields[{field_name}]",
                )

        raise ValueError(f"Bitwarden item is missing field '{field_name}'")

    def optional_field_value(
        self,
        item_payload: dict[str, object],
        field_name: str,
    ) -> str | None:
        """Extract an optional custom field from a Bitwarden item payload."""

        for candidate in self.fields(item_payload.get("fields")):
            if candidate["name"] == field_name:
                return self.required_string(
                    candidate.get("value"),
                    f"item.fields[{field_name}]",
                )

        return None

    def fields(self, raw_fields: object) -> list[dict[str, object]]:
        """Return normalized custom fields from a Bitwarden item payload."""

        if raw_fields is None:
            return []
        if not isinstance(raw_fields, list):
            raise ValueError("item.fields must be a list")

        normalized_fields: list[dict[str, object]] = []
        for index, raw_field in enumerate(raw_fields):
            if not isinstance(raw_field, dict):
                raise ValueError(f"item.fields[{index}] must be a mapping")
            normalized_fields.append(raw_field)

        return normalized_fields

    def required_string(self, value: object, name: str) -> str:
        """Return a trimmed required string value."""

        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")

        trimmed_value = value.strip()
        if not trimmed_value:
            raise ValueError(f"{name} must not be empty")

        return trimmed_value

    def content_with_trailing_newline(self, value: str, name: str) -> str:
        """Normalize rendered content to a single trailing newline."""

        normalized_value = value.rstrip("\n")
        if not normalized_value:
            raise ValueError(f"{name} must not be empty")

        return f"{normalized_value}\n"
