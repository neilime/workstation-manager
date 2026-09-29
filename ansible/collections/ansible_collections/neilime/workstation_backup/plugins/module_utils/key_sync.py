"""Pure helpers for comparing local key material with Bitwarden items."""

from __future__ import annotations

import re
from typing import cast

from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_gpg_keys import (
    BitwardenGpgKeyRestorePlanner,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_item_fields import (
    BitwardenItemFieldReader,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_ssh_keys import (
    BitwardenSshKeyRestorePlanner,
)


def normalize_ownertrust(value: object) -> str | None:
    """Treat an absent ownertrust entry and explicitly undefined trust as unassigned."""

    if value is None:
        return None
    value = BitwardenItemFieldReader().required_string(value, "ownertrust")
    if re.fullmatch(r"[0-9A-Fa-f]+:2:\s*", value):
        return None
    return value.rstrip("\n") + "\n"


# pylint: disable=too-few-public-methods
class BitwardenSshKeySyncPlanner:
    """Compare local SSH keys with Bitwarden-backed managed key items."""

    def __init__(self) -> None:
        self._reader = BitwardenItemFieldReader()
        self._restore_planner = BitwardenSshKeyRestorePlanner()

    def build(
        self,
        local_items: list[dict[str, object]],
        bitwarden_items: list[dict[str, object]],
        user_home: str,
    ) -> list[dict[str, object]]:
        """Return upload or restore decisions for keys missing or different on either side."""

        remote_items_by_name = self._remote_items_by_name(bitwarden_items, user_home)
        actions: list[dict[str, object]] = []

        local_identities = set()
        for local_item in local_items:
            normalized_local_item = self._normalized_local_item(local_item)
            local_identities.add(normalized_local_item["name"])
            remote_item = remote_items_by_name.get(normalized_local_item["name"])

            if remote_item is None:
                actions.append(
                    self._action_payload(
                        normalized_local_item,
                        action="add",
                    )
                )
                continue

            if self._contents_match(normalized_local_item, remote_item):
                continue

            actions.append(
                self._action_payload(
                    normalized_local_item,
                    action="update",
                    bitwarden_item_id=remote_item["item_id"],
                )
            )

        for name, remote_item in remote_items_by_name.items():
            if name not in local_identities:
                actions.append(
                    self._action_payload(
                        {**remote_item, "name": name}, action="restore", bitwarden_item_id=remote_item["item_id"]
                    )
                )
        return actions

    def _remote_items_by_name(
        self,
        bitwarden_items: list[dict[str, object]],
        user_home: str,
    ) -> dict[str, dict[str, str]]:
        remote_items_by_name: dict[str, dict[str, str]] = {}

        for bitwarden_item in bitwarden_items:
            restore_plan = self._restore_planner.build_plan(bitwarden_item, user_home)
            key_name = str(restore_plan["name"])
            if key_name in remote_items_by_name:
                raise ValueError(f"duplicate Bitwarden SSH key item name: {key_name}")

            remote_items_by_name[key_name] = {
                "item_id": str(restore_plan["item_id"]),
                "private_key": str(restore_plan["private"]["content"]),
                "public_key": str(restore_plan["public"]["content"]),
            }

        return remote_items_by_name

    def _normalized_local_item(self, local_item: dict[str, object]) -> dict[str, str]:
        return {
            "name": self._reader.required_string(local_item.get("name"), "local_ssh_key.name"),
            "private_key": self._reader.content_with_trailing_newline(
                self._reader.required_string(local_item.get("private_key"), "local_ssh_key.private_key"),
                "local_ssh_key.private_key",
            ),
            "public_key": self._reader.content_with_trailing_newline(
                self._reader.required_string(local_item.get("public_key"), "local_ssh_key.public_key"),
                "local_ssh_key.public_key",
            ),
        }

    def _contents_match(self, local_item: dict[str, str], remote_item: dict[str, str]) -> bool:
        return (
            local_item["private_key"] == remote_item["private_key"]
            and local_item["public_key"] == remote_item["public_key"]
        )

    def _action_payload(
        self,
        local_item: dict[str, str],
        *,
        action: str,
        bitwarden_item_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "kind": "ssh",
            "name": local_item["name"],
            "action": action,
            "bitwarden_item_id": bitwarden_item_id,
            "fields": [
                {"name": "private_key", "type": 1, "value": local_item["private_key"]},
                {"name": "public_key", "type": 0, "value": local_item["public_key"]},
            ],
        }


class BitwardenGpgKeySyncPlanner:
    """Compare local GPG key material with Bitwarden-backed managed key items."""

    def __init__(self) -> None:
        self._reader = BitwardenItemFieldReader()
        self._restore_planner = BitwardenGpgKeyRestorePlanner()

    def build(
        self,
        local_items: list[dict[str, object]],
        bitwarden_items: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """Return upload or restore decisions for keys missing or different on either side."""

        remote_items_by_fingerprint = self._remote_items_by_fingerprint(bitwarden_items)
        actions: list[dict[str, object]] = []

        local_identities = set()
        for local_item in local_items:
            normalized_local_item = self._normalized_local_item(local_item)
            fingerprint = cast(str, normalized_local_item["fingerprint"])
            local_identities.add(fingerprint)
            remote_item = remote_items_by_fingerprint.get(fingerprint)

            if remote_item is None:
                actions.append(
                    self._action_payload(
                        normalized_local_item,
                        action="add",
                    )
                )
                continue

            if self._contents_match(normalized_local_item, remote_item):
                continue

            actions.append(
                self._action_payload(
                    normalized_local_item,
                    action="update",
                    bitwarden_item_id=remote_item["item_id"],
                )
            )

        for fingerprint, remote_item in remote_items_by_fingerprint.items():
            if fingerprint not in local_identities:
                actions.append(
                    self._action_payload(
                        {**remote_item, "fingerprint": fingerprint},
                        action="restore",
                        bitwarden_item_id=remote_item["item_id"],
                    )
                )
        return actions

    def _remote_items_by_fingerprint(
        self,
        bitwarden_items: list[dict[str, object]],
    ) -> dict[str, dict[str, str | None]]:
        remote_items_by_fingerprint: dict[str, dict[str, str | None]] = {}

        for bitwarden_item in bitwarden_items:
            restore_plan = self._restore_planner.build_plan(bitwarden_item)
            fingerprint = str(restore_plan["fingerprint"])
            if fingerprint in remote_items_by_fingerprint:
                raise ValueError(f"duplicate Bitwarden GPG key fingerprint: {fingerprint}")

            remote_items_by_fingerprint[fingerprint] = {
                "item_id": str(restore_plan["item_id"]),
                "name": str(restore_plan["name"]),
                "private_key": str(restore_plan["private_key"]),
                "public_key": str(restore_plan["public_key"]),
                "ownertrust": normalize_ownertrust(restore_plan.get("ownertrust")),
            }

        return remote_items_by_fingerprint

    def _normalized_local_item(self, local_item: dict[str, object]) -> dict[str, str | None]:
        fingerprint = self._restore_planner._fingerprint(  # pylint: disable=protected-access
            self._reader.required_string(local_item.get("fingerprint"), "local_gpg_key.fingerprint")
        )
        name_value = local_item.get("name")
        name = (
            self._reader.required_string(name_value, "local_gpg_key.name")
            if name_value is not None
            else f"GPG key {fingerprint}"
        )

        return {
            "name": name,
            "fingerprint": fingerprint,
            "private_key": self._reader.content_with_trailing_newline(
                self._reader.required_string(local_item.get("private_key"), "local_gpg_key.private_key"),
                "local_gpg_key.private_key",
            ),
            "public_key": self._reader.content_with_trailing_newline(
                self._reader.required_string(local_item.get("public_key"), "local_gpg_key.public_key"),
                "local_gpg_key.public_key",
            ),
            "ownertrust": normalize_ownertrust(local_item.get("ownertrust")),
        }

    def _contents_match(
        self,
        local_item: dict[str, str | None],
        remote_item: dict[str, str | None],
    ) -> bool:
        return (
            local_item["private_key"] == remote_item["private_key"]
            and local_item["public_key"] == remote_item["public_key"]
            and local_item["ownertrust"] == remote_item["ownertrust"]
        )

    def _action_payload(
        self,
        local_item: dict[str, str | None],
        *,
        action: str,
        bitwarden_item_id: str | None = None,
    ) -> dict[str, object]:
        fields: list[dict[str, object]] = [
            {"name": "fingerprint", "type": 0, "value": local_item["fingerprint"]},
            {"name": "private_key", "type": 1, "value": local_item["private_key"]},
            {"name": "public_key", "type": 0, "value": local_item["public_key"]},
        ]
        if local_item["ownertrust"] is not None:
            fields.append({"name": "ownertrust", "type": 0, "value": local_item["ownertrust"]})

        return {
            "kind": "gpg",
            "name": local_item["name"],
            "action": action,
            "bitwarden_item_id": bitwarden_item_id,
            "fields": fields,
        }
