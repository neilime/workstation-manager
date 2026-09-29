"""Unit tests for Bitwarden SSH key restore helpers."""

from __future__ import annotations

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_ssh_keys import (
    BitwardenSshKeyRestorePlanner,
)


def test_build_plan_uses_declared_key_fields_and_item_name() -> None:
    """The planner should derive file paths from the Bitwarden item name."""

    # Arrange
    planner = BitwardenSshKeyRestorePlanner()
    item_payload: dict[str, object] = {
        "id": "item-123",
        "name": "id_rsa_escemi",
        "fields": [
            {
                "name": "private_key",
                "value": "ssh-private-material-line-1\nssh-private-material-line-2",
            },
            {
                "name": "public_key",
                "value": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA fixture@example",
            },
        ],
    }

    # Act
    plan = planner.build_plan(item_payload, "/home/emilien")

    # Assert
    assert plan["item_id"] == "item-123"
    assert plan["name"] == "id_rsa_escemi"
    assert plan["private"] == {
        "dest": "/home/emilien/.ssh/id_rsa_escemi",
        "mode": "0600",
        "content": ("ssh-private-material-line-1\nssh-private-material-line-2\n"),
    }
    assert plan["public"] == {
        "dest": "/home/emilien/.ssh/id_rsa_escemi.pub",
        "mode": "0644",
        "content": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA fixture@example\n",
    }


def test_build_plan_rejects_nested_item_names() -> None:
    """Bitwarden item names must map to a single SSH key filename."""

    # Arrange
    planner = BitwardenSshKeyRestorePlanner()
    item_payload: dict[str, object] = {
        "id": "item-123",
        "name": "nested/id_client",
        "fields": [
            {
                "name": "private_key",
                "value": "custom-private-material-line-1\ncustom-private-material-line-2",
            },
            {
                "name": "public_key",
                "value": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA custom@example",
            },
        ],
    }

    # Act / Assert
    with pytest.raises(ValueError, match="single SSH key filename"):
        planner.build_plan(item_payload, "/home/emilien")


def test_build_plan_rejects_missing_public_key_field() -> None:
    """A missing declared custom field should fail with a clear error."""

    # Arrange
    planner = BitwardenSshKeyRestorePlanner()
    item_payload: dict[str, object] = {
        "id": "item-123",
        "name": "id_rsa_escemi",
        "fields": [
            {
                "name": "private_key",
                "value": "ssh-private-material-line-1\nssh-private-material-line-2",
            }
        ],
    }

    # Act / Assert
    with pytest.raises(ValueError, match="missing field 'public_key'"):
        planner.build_plan(item_payload, "/home/emilien")


def test_build_plan_rejects_missing_private_key_field() -> None:
    """Each SSH key item must provide a private_key custom field."""

    # Arrange
    planner = BitwardenSshKeyRestorePlanner()
    item_payload: dict[str, object] = {
        "id": "item-123",
        "name": "id_rsa_escemi",
        "fields": [],
    }

    # Act / Assert
    with pytest.raises(ValueError, match="missing field 'private_key'"):
        planner.build_plan(item_payload, "/home/emilien")


@pytest.mark.parametrize("key_format", ["OPENSSH ", "RSA ", "EC ", "DSA ", "ENCRYPTED ", ""])
@pytest.mark.parametrize("prefix", ["", "ssh-ed25519 synthetic-public-key fixture@example\n"])
def test_build_plan_rejects_private_key_material_in_public_field(key_format: str, prefix: str) -> None:
    """Private material must never be restored into a public file with mode 0644."""

    planner = BitwardenSshKeyRestorePlanner()
    private_content = f"-----BEGIN {key_format}PRIVATE KEY-----\nsynthetic-sensitive-material\n"
    item_payload: dict[str, object] = {
        "id": "item-123",
        "name": "id_client",
        "fields": [
            {"name": "private_key", "value": "synthetic-private-key"},
            {"name": "public_key", "value": f"{prefix}{private_content}"},
        ],
    }

    with pytest.raises(ValueError, match="private key material in 'public_key'") as error:
        planner.build_plan(item_payload, "/home/emilien")

    assert "id_client" in str(error.value)
    assert "swapped" in str(error.value)
    assert "synthetic-sensitive-material" not in str(error.value)
