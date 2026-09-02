"""Unit tests for backup-time key synchronization planners."""

from __future__ import annotations

import pytest
from ansible_collections.neilime.workstation_backup.plugins.module_utils.key_sync import (
    BitwardenGpgKeySyncPlanner,
    BitwardenSshKeySyncPlanner,
)


def test_ssh_sync_planner_returns_add_action_for_missing_remote_item() -> None:
    """Local SSH keys missing from Bitwarden should be queued for creation."""

    planner = BitwardenSshKeySyncPlanner()

    actions = planner.build(
        [
            {
                "name": "id_ed25519",
                "private_key": "private-material",
                "public_key": "ssh-ed25519 AAAA fixture@example",
            }
        ],
        [],
        "/home/emilien",
    )

    assert actions == [
        {
            "kind": "ssh",
            "name": "id_ed25519",
            "action": "add",
            "reason": "missing_in_secret_manager",
            "bitwarden_item_id": None,
            "fields": [
                {"name": "private_key", "type": 1, "value": "private-material\n"},
                {"name": "public_key", "type": 0, "value": "ssh-ed25519 AAAA fixture@example\n"},
            ],
        }
    ]


def test_ssh_sync_planner_returns_update_action_for_mismatched_remote_item() -> None:
    """Remote SSH items with drift should be queued for update."""

    planner = BitwardenSshKeySyncPlanner()

    actions = planner.build(
        [
            {
                "name": "id_ed25519",
                "private_key": "local-private-material",
                "public_key": "ssh-ed25519 AAAA local@example",
            }
        ],
        [
            {
                "id": "item-123",
                "name": "id_ed25519",
                "fields": [
                    {"name": "private_key", "value": "remote-private-material"},
                    {"name": "public_key", "value": "ssh-ed25519 AAAA remote@example"},
                ],
            }
        ],
        "/home/emilien",
    )

    assert actions == [
        {
            "kind": "ssh",
            "name": "id_ed25519",
            "action": "update",
            "reason": "content_mismatch",
            "bitwarden_item_id": "item-123",
            "fields": [
                {"name": "private_key", "type": 1, "value": "local-private-material\n"},
                {"name": "public_key", "type": 0, "value": "ssh-ed25519 AAAA local@example\n"},
            ],
        }
    ]


def test_ssh_sync_planner_skips_matching_remote_item() -> None:
    """Already synchronized SSH items should not produce any action."""

    planner = BitwardenSshKeySyncPlanner()

    actions = planner.build(
        [
            {
                "name": "id_ed25519",
                "private_key": "private-material\n",
                "public_key": "ssh-ed25519 AAAA fixture@example\n",
            }
        ],
        [
            {
                "id": "item-123",
                "name": "id_ed25519",
                "fields": [
                    {"name": "private_key", "value": "private-material"},
                    {"name": "public_key", "value": "ssh-ed25519 AAAA fixture@example"},
                ],
            }
        ],
        "/home/emilien",
    )

    assert actions == []


def test_ssh_sync_planner_rejects_duplicate_remote_names() -> None:
    """Ambiguous SSH item names should fail fast before backup updates secrets."""

    planner = BitwardenSshKeySyncPlanner()

    with pytest.raises(ValueError, match="duplicate Bitwarden SSH key item name"):
        planner.build(
            [],
            [
                {
                    "id": "item-123",
                    "name": "id_ed25519",
                    "fields": [
                        {"name": "private_key", "value": "private-material"},
                        {"name": "public_key", "value": "ssh-ed25519 AAAA fixture@example"},
                    ],
                },
                {
                    "id": "item-456",
                    "name": "id_ed25519",
                    "fields": [
                        {"name": "private_key", "value": "other-private-material"},
                        {"name": "public_key", "value": "ssh-ed25519 AAAA other@example"},
                    ],
                },
            ],
            "/home/emilien",
        )


def test_gpg_sync_planner_returns_add_action_for_missing_remote_item() -> None:
    """Local GPG keys missing from Bitwarden should be queued for creation."""

    planner = BitwardenGpgKeySyncPlanner()

    actions = planner.build(
        [
            {
                "name": "Escemi Primary Key",
                "fingerprint": "0123 4567 89ab cdef",
                "private_key": "private-gpg-material",
                "public_key": "public-gpg-material",
                "ownertrust": "0123456789ABCDEF:6:",
            }
        ],
        [],
    )

    assert actions == [
        {
            "kind": "gpg",
            "name": "Escemi Primary Key",
            "action": "add",
            "reason": "missing_in_secret_manager",
            "fingerprint": "0123456789ABCDEF",
            "bitwarden_item_id": None,
            "fields": [
                {"name": "fingerprint", "type": 0, "value": "0123456789ABCDEF"},
                {"name": "private_key", "type": 1, "value": "private-gpg-material\n"},
                {"name": "public_key", "type": 0, "value": "public-gpg-material\n"},
                {"name": "ownertrust", "type": 0, "value": "0123456789ABCDEF:6:\n"},
            ],
        }
    ]


def test_gpg_sync_planner_returns_update_action_for_mismatched_remote_item() -> None:
    """Remote GPG items with drift should be queued for update."""

    planner = BitwardenGpgKeySyncPlanner()

    actions = planner.build(
        [
            {
                "name": "Escemi Primary Key",
                "fingerprint": "0123456789ABCDEF",
                "private_key": "local-private-gpg-material",
                "public_key": "local-public-gpg-material",
            }
        ],
        [
            {
                "id": "item-123",
                "name": "Escemi Primary Key",
                "fields": [
                    {"name": "fingerprint", "value": "0123456789ABCDEF"},
                    {"name": "private_key", "value": "remote-private-gpg-material"},
                    {"name": "public_key", "value": "remote-public-gpg-material"},
                ],
            }
        ],
    )

    assert actions == [
        {
            "kind": "gpg",
            "name": "Escemi Primary Key",
            "action": "update",
            "reason": "content_mismatch",
            "fingerprint": "0123456789ABCDEF",
            "bitwarden_item_id": "item-123",
            "fields": [
                {"name": "fingerprint", "type": 0, "value": "0123456789ABCDEF"},
                {"name": "private_key", "type": 1, "value": "local-private-gpg-material\n"},
                {"name": "public_key", "type": 0, "value": "local-public-gpg-material\n"},
            ],
        }
    ]


def test_gpg_sync_planner_skips_matching_remote_item() -> None:
    """Already synchronized GPG items should not produce any action."""

    planner = BitwardenGpgKeySyncPlanner()

    actions = planner.build(
        [
            {
                "fingerprint": "0123456789ABCDEF",
                "private_key": "private-gpg-material\n",
                "public_key": "public-gpg-material\n",
                "ownertrust": "0123456789ABCDEF:6:\n",
            }
        ],
        [
            {
                "id": "item-123",
                "name": "Escemi Primary Key",
                "fields": [
                    {"name": "fingerprint", "value": "0123456789ABCDEF"},
                    {"name": "private_key", "value": "private-gpg-material"},
                    {"name": "public_key", "value": "public-gpg-material"},
                    {"name": "ownertrust", "value": "0123456789ABCDEF:6:"},
                ],
            }
        ],
    )

    assert actions == []
