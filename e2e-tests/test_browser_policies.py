"""End-to-end checks for primary browser policy files."""


def test_primary_browser_managed_policy_file_exists(host) -> None:
    """The install should generate the managed Chrome policy file explicitly."""

    # Arrange
    policy_file = host.file("/etc/opt/chrome/policies/managed/workstation-manager.json")

    # Act
    mode = host.check_output(
        "stat -c '%a' /etc/opt/chrome/policies/managed/workstation-manager.json"
    )

    # Assert
    assert policy_file.exists
    assert policy_file.user == "root"
    assert policy_file.group == "root"
    assert mode == "644"


def test_primary_browser_managed_policy_file_contains_expected_entries(host) -> None:
    """The managed policy file should contain the repository browser defaults."""

    # Arrange
    policy_file = host.file("/etc/opt/chrome/policies/managed/workstation-manager.json")

    # Act
    has_bitwarden_extension = policy_file.contains('"nngceckbapebfimnlniiiahkandclblb"')
    has_password_manager_policy = policy_file.contains(
        '"PasswordManagerEnabled": false'
    )
    has_bookmark_bar_policy = policy_file.contains('"BookmarkBarEnabled": true')
    has_startup_policy = policy_file.contains('"RestoreOnStartup": 1')

    # Assert
    assert has_bitwarden_extension
    assert has_password_manager_policy
    assert has_bookmark_bar_policy
    assert has_startup_policy
