"""End-to-end checks for the fixed Brave Sync policy."""

import json


def test_primary_browser_managed_policy_file_exists(host) -> None:
    """The install should generate the managed Brave policy file explicitly."""

    # Arrange
    policy_file = host.file("/etc/brave/policies/managed/workstation-manager.json")

    # Act
    mode = host.check_output("stat -c '%a' /etc/brave/policies/managed/workstation-manager.json")

    # Assert
    assert policy_file.exists
    assert policy_file.user == "root"
    assert policy_file.group == "root"
    assert mode == "644"


def test_primary_browser_policy_leaves_extensions_and_preferences_to_sync(host) -> None:
    """Setup must replace legacy extension and preference policies with Sync availability only."""

    policy_file = host.file("/etc/brave/policies/managed/workstation-manager.json")
    assert json.loads(policy_file.content_string) == {"SyncDisabled": False}
