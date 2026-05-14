"""Unit tests for primary browser policy helpers."""

from __future__ import annotations

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    primary_browser_policies,
)


def test_build_policy_payload_returns_expected_chrome_policies() -> None:
    """Repository policy inputs should render to Chrome managed-policy keys."""

    # Arrange
    planner = primary_browser_policies.PrimaryBrowserPoliciesPlanner()
    policy_inputs = {
        "baseline_extensions": [
            {
                "id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "installation_mode": "force_installed",
            }
        ],
        "password_manager": {"enabled": False},
        "third_party_password_manager": {
            "extension_id": "nngceckbapebfimnlniiiahkandclblb",
            "policy": {},
        },
        "startup": {
            "bookmark_bar_enabled": True,
            "restore_on_startup": 1,
        },
    }

    # Act
    payload = planner.build_policy_payload(policy_inputs)

    # Assert
    assert payload == {
        "3rdparty": {"extensions": {"nngceckbapebfimnlniiiahkandclblb": {}}},
        "BookmarkBarEnabled": True,
        "ExtensionSettings": {
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": {
                "installation_mode": "force_installed",
                "update_url": "https://clients2.google.com/service/update2/crx",
            },
            "nngceckbapebfimnlniiiahkandclblb": {
                "installation_mode": "force_installed",
                "update_url": "https://clients2.google.com/service/update2/crx",
            },
        },
        "PasswordManagerEnabled": False,
        "RestoreOnStartup": 1,
    }


def test_build_policy_payload_rejects_invalid_extension_lists() -> None:
    """Non-list extension inputs should fail before policy JSON is rendered."""

    # Arrange
    planner = primary_browser_policies.PrimaryBrowserPoliciesPlanner()

    # Act / Assert
    with pytest.raises(
        ValueError,
        match="policy_inputs.baseline_extensions must be a list",
    ):
        planner.build_policy_payload({"baseline_extensions": "bitwarden"})


def test_build_policy_payload_rejects_managed_bookmarks() -> None:
    """Bookmarks should not be modeled as browser-wide managed policy input."""

    # Arrange
    planner = primary_browser_policies.PrimaryBrowserPoliciesPlanner()

    # Act / Assert
    with pytest.raises(
        ValueError,
        match="policy_inputs.managed_bookmarks is not supported",
    ):
        planner.build_policy_payload(
            {
                "managed_bookmarks": [
                    {"name": "workstation-manager", "url": "https://github.com"}
                ]
            }
        )


def test_build_policy_payload_rejects_missing_third_party_extension_id() -> None:
    """Third-party extension policy data requires an explicit extension id."""

    # Arrange
    planner = primary_browser_policies.PrimaryBrowserPoliciesPlanner()

    # Act / Assert
    with pytest.raises(
        ValueError,
        match=(
            "policy_inputs.third_party_password_manager.extension_id "
            "must not be empty"
        ),
    ):
        planner.build_policy_payload(
            {
                "third_party_password_manager": {
                    "policy": {"serverUrl": "https://vault.example.test"}
                }
            }
        )
