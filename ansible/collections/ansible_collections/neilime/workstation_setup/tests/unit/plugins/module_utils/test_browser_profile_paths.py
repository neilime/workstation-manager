"""Unit tests for managed browser profile path helpers."""

from __future__ import annotations

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    browser_profile_paths,
)

BrowserProfilePathsPlanner = browser_profile_paths.BrowserProfilePathsPlanner


def test_build_profile_directory_returns_stable_profile_path() -> None:
    """Each declared profile id should map to a stable managed directory."""

    # Arrange
    planner = BrowserProfilePathsPlanner()
    profiles_root_dir = "/home/emilien/.config/BraveSoftware/Brave-Browser"

    # Act
    profile_directory = planner.build_profile_directory(
        profiles_root_dir,
        "client-2",
    )

    # Assert
    assert profile_directory == "/home/emilien/.config/BraveSoftware/Brave-Browser/managed-client-2"


def test_build_profile_directory_rejects_invalid_profile_id() -> None:
    """Invalid profile ids should fail before a filesystem path is produced."""

    # Arrange
    planner = BrowserProfilePathsPlanner()
    profiles_root_dir = "/home/emilien/.config/BraveSoftware/Brave-Browser"

    # Act / Assert
    with pytest.raises(
        ValueError,
        match="profile_id must use only lowercase letters, numbers, and dashes",
    ):
        planner.build_profile_directory(profiles_root_dir, "Client Example")


def test_has_valid_profile_id_returns_true_for_slug_ids() -> None:
    """Lowercase slug ids should be accepted for managed profile directories."""

    # Arrange
    planner = BrowserProfilePathsPlanner()

    # Act
    is_valid = planner.has_valid_profile_id("client-1")

    # Assert
    assert is_valid is True


def test_has_valid_profile_id_returns_false_for_non_slug_ids() -> None:
    """Whitespace and uppercase labels should not be accepted as profile ids."""

    # Arrange
    planner = BrowserProfilePathsPlanner()

    # Act
    is_valid = planner.has_valid_profile_id("Client Example")

    # Assert
    assert is_valid is False
