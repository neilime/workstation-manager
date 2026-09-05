"""Unit tests for editor settings sync helpers."""

from __future__ import annotations

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.editor_settings_sync import (
    VscodeSettingsSyncPlanner,
)


def test_build_sync_state_dir_returns_stable_path() -> None:
    """The sync state directory should live under the managed VS Code user data."""

    # Arrange
    planner = VscodeSettingsSyncPlanner()

    # Act
    sync_state_dir = planner.build_sync_state_dir("/home/emilien")

    # Assert
    assert sync_state_dir == "/home/emilien/.config/Code/User/sync"


def test_build_sync_state_dir_rejects_empty_user_home() -> None:
    """An empty home path should fail before a sync path is produced."""

    # Arrange
    planner = VscodeSettingsSyncPlanner()

    # Act / Assert
    with pytest.raises(ValueError, match="user_home must not be empty"):
        planner.build_sync_state_dir("  ")


def test_has_vscode_editor_package_detects_managed_vscode() -> None:
    """The managed editor set should recognize the VS Code Flatpak package id."""

    # Arrange
    planner = VscodeSettingsSyncPlanner()

    # Act
    has_vscode = planner.has_vscode_editor_package(["com.visualstudio.code", "other.editor"])

    # Assert
    assert has_vscode is True


def test_should_request_sync_returns_true_when_setup_can_launch_the_cli_flow() -> None:
    """Setup should request sync when VS Code is managed and a desktop session exists."""

    # Arrange
    planner = VscodeSettingsSyncPlanner()

    # Act
    should_request = planner.should_request_sync(
        editor_packages=["com.visualstudio.code"],
        sync_state_exists=False,
        has_desktop_session=True,
        interactive=True,
        check_mode=False,
    )

    # Assert
    assert should_request is True


@pytest.mark.parametrize(
    ("sync_state_exists", "has_desktop_session", "interactive", "check_mode"),
    [
        (True, True, True, False),
        (False, False, True, False),
        (False, True, False, False),
        (False, True, True, True),
    ],
)
def test_should_request_sync_returns_false_when_preconditions_fail(
    sync_state_exists: bool,
    has_desktop_session: bool,
    interactive: bool,
    check_mode: bool,
) -> None:
    """Setup should skip the CLI request when any required precondition is missing."""

    # Arrange
    planner = VscodeSettingsSyncPlanner()

    # Act
    should_request = planner.should_request_sync(
        editor_packages=["com.visualstudio.code"],
        sync_state_exists=sync_state_exists,
        has_desktop_session=has_desktop_session,
        interactive=interactive,
        check_mode=check_mode,
    )

    # Assert
    assert should_request is False


def test_should_remind_sync_returns_true_when_setup_should_show_guidance() -> None:
    """Setup should remind when VS Code is managed and no sync state exists."""

    # Arrange
    planner = VscodeSettingsSyncPlanner()

    # Act
    should_remind = planner.should_remind_sync(
        editor_packages=["com.visualstudio.code"],
        sync_state_exists=False,
        interactive=True,
        check_mode=False,
    )

    # Assert
    assert should_remind is True


@pytest.mark.parametrize(
    ("sync_state_exists", "interactive", "check_mode"),
    [
        (True, True, False),
        (False, False, False),
        (False, True, True),
    ],
)
def test_should_remind_sync_returns_false_when_preconditions_fail(
    sync_state_exists: bool,
    interactive: bool,
    check_mode: bool,
) -> None:
    """Setup should skip the reminder when any required precondition is missing."""

    # Arrange
    planner = VscodeSettingsSyncPlanner()

    # Act
    should_remind = planner.should_remind_sync(
        editor_packages=["com.visualstudio.code"],
        sync_state_exists=sync_state_exists,
        interactive=interactive,
        check_mode=check_mode,
    )

    # Assert
    assert should_remind is False


def test_should_remind_sync_returns_false_without_managed_vscode() -> None:
    """Setup should not remind when VS Code is not part of the managed editor set."""

    # Arrange
    planner = VscodeSettingsSyncPlanner()

    # Act
    should_remind = planner.should_remind_sync(
        editor_packages=[],
        sync_state_exists=False,
        interactive=True,
        check_mode=False,
    )

    # Assert
    assert should_remind is False
