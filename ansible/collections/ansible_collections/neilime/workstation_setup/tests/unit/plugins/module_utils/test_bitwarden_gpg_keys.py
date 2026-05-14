"""Unit tests for Bitwarden GPG key restore helpers."""

from __future__ import annotations

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_gpg_keys import (
    BitwardenGpgKeyRestorePlanner,
)


def test_build_plan_uses_required_fields_and_optional_ownertrust() -> None:
    """The planner should derive a normalized import plan from item fields."""

    # Arrange
    planner = BitwardenGpgKeyRestorePlanner()
    item_payload = {
        "id": "item-123",
        "name": "Example primary GPG key",
        "fields": [
            {"name": "fingerprint", "value": "0123 4567 89ab cdef"},
            {
                "name": "private_key",
                "value": "private-gpg-material-line-1\nprivate-gpg-material-line-2",
            },
            {
                "name": "public_key",
                "value": "public-gpg-material-line-1\npublic-gpg-material-line-2",
            },
            {"name": "ownertrust", "value": "0123456789ABCDEF:6:"},
        ],
    }

    # Act
    plan = planner.build_plan(item_payload)

    # Assert
    assert plan == {
        "item_id": "item-123",
        "name": "Example primary GPG key",
        "fingerprint": "0123456789ABCDEF",
        "private_key": ("private-gpg-material-line-1\nprivate-gpg-material-line-2\n"),
        "public_key": ("public-gpg-material-line-1\npublic-gpg-material-line-2\n"),
        "ownertrust": "0123456789ABCDEF:6:\n",
    }


def test_build_plan_allows_missing_ownertrust() -> None:
    """Ownertrust should remain optional for GPG restore items."""

    # Arrange
    planner = BitwardenGpgKeyRestorePlanner()
    item_payload = {
        "id": "item-123",
        "name": "Example primary GPG key",
        "fields": [
            {"name": "fingerprint", "value": "0123456789ABCDEF"},
            {"name": "private_key", "value": "private-gpg-material"},
            {"name": "public_key", "value": "public-gpg-material"},
        ],
    }

    # Act
    plan = planner.build_plan(item_payload)

    # Assert
    assert plan["ownertrust"] is None


def test_build_plan_derives_fingerprint_from_ownertrust() -> None:
    """The planner should avoid duplicated fingerprint data when ownertrust exists."""

    # Arrange
    planner = BitwardenGpgKeyRestorePlanner()
    item_payload = {
        "id": "item-123",
        "name": "Example primary GPG key",
        "fields": [
            {"name": "private_key", "value": "private-gpg-material"},
            {"name": "public_key", "value": "public-gpg-material"},
            {"name": "ownertrust", "value": "0123456789ABCDEF:6:"},
        ],
    }

    # Act
    plan = planner.build_plan(item_payload)

    # Assert
    assert plan["fingerprint"] == "0123456789ABCDEF"
    assert plan["ownertrust"] == "0123456789ABCDEF:6:\n"


def test_build_plan_normalizes_flattened_openpgp_armor_and_appends_subkey() -> None:
    """Flattened Bitwarden armor should become importable multiline key material."""

    # Arrange
    planner = BitwardenGpgKeyRestorePlanner()
    begin_private = "".join(["-----", "BEGIN", " PGP PRIVATE KEY ", "BLOCK", "-----"])
    end_private = "".join(["-----", "END", " PGP PRIVATE KEY ", "BLOCK", "-----"])
    begin_public = "".join(["-----", "BEGIN", " PGP PUBLIC KEY ", "BLOCK", "-----"])
    end_public = "".join(["-----", "END", " PGP PUBLIC KEY ", "BLOCK", "-----"])
    item_payload = {
        "id": "item-123",
        "name": "Example primary GPG key",
        "fields": [
            {
                "name": "private_key",
                "value": f"{begin_private} private-body-1 private-body-2 =priv {end_private}",
            },
            {
                "name": "sub_private_key",
                "value": f"{begin_private} sub-body-1 sub-body-2 =sub {end_private}",
            },
            {
                "name": "public_key",
                "value": f"{begin_public} public-body-1 public-body-2 =pub {end_public}",
            },
            {"name": "ownertrust", "value": "0123456789ABCDEF:6:"},
        ],
    }

    # Act
    plan = planner.build_plan(item_payload)

    # Assert
    assert plan["fingerprint"] == "0123456789ABCDEF"
    assert plan["private_key"] == (
        f"{begin_private}\n"
        "\n"
        "private-body-1\n"
        "private-body-2\n"
        "=priv\n"
        f"{end_private}\n"
        f"{begin_private}\n"
        "\n"
        "sub-body-1\n"
        "sub-body-2\n"
        "=sub\n"
        f"{end_private}\n"
    )
    assert plan["public_key"] == (
        f"{begin_public}\n"
        "\n"
        "public-body-1\n"
        "public-body-2\n"
        "=pub\n"
        f"{end_public}\n"
    )


def test_build_plan_rejects_missing_fingerprint() -> None:
    """GPG restore items must provide a fingerprint field for idempotency."""

    # Arrange
    planner = BitwardenGpgKeyRestorePlanner()
    item_payload = {
        "id": "item-123",
        "name": "Example primary GPG key",
        "fields": [
            {"name": "private_key", "value": "private-gpg-material"},
            {"name": "public_key", "value": "public-gpg-material"},
        ],
    }

    # Act / Assert
    with pytest.raises(ValueError, match="missing field 'fingerprint'"):
        planner.build_plan(item_payload)


def test_build_plan_rejects_ownertrust_without_fingerprint_prefix() -> None:
    """Malformed ownertrust should not silently produce an unusable fingerprint."""

    # Arrange
    planner = BitwardenGpgKeyRestorePlanner()
    item_payload = {
        "id": "item-123",
        "name": "Example primary GPG key",
        "fields": [
            {"name": "private_key", "value": "private-gpg-material"},
            {"name": "public_key", "value": "public-gpg-material"},
            {"name": "ownertrust", "value": ":6:"},
        ],
    }

    # Act / Assert
    with pytest.raises(ValueError, match="ownertrust must start with a fingerprint"):
        planner.build_plan(item_payload)


def test_build_plan_rejects_invalid_fingerprint_characters() -> None:
    """Fingerprints should stay machine-parseable."""

    # Arrange
    planner = BitwardenGpgKeyRestorePlanner()
    item_payload = {
        "id": "item-123",
        "name": "Example primary GPG key",
        "fields": [
            {"name": "fingerprint", "value": "0123-4567"},
            {"name": "private_key", "value": "private-gpg-material"},
            {"name": "public_key", "value": "public-gpg-material"},
        ],
    }

    # Act / Assert
    with pytest.raises(ValueError, match="hexadecimal characters"):
        planner.build_plan(item_payload)
