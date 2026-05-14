"""End-to-end checks for managed browser profile directories."""


def test_primary_browser_profile_directories_exist(host) -> None:
    """Declared browser profiles should have stable managed directories."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    profiles_root = f"{user_home}/.local/share/workstation-manager/browser-profiles"
    profile_ids = ["personal", "escemi"]

    # Act
    root_directory = host.file(profiles_root)
    profile_directories = {
        profile_id: host.file(f"{profiles_root}/{profile_id}")
        for profile_id in profile_ids
    }

    # Assert
    assert root_directory.exists
    assert root_directory.is_directory
    for profile_id, profile_directory in profile_directories.items():
        assert profile_directory.exists, profile_id
        assert profile_directory.is_directory, profile_id
        assert profile_directory.user == host.check_output("whoami"), profile_id


def test_primary_browser_profile_directories_do_not_seed_browser_databases(
    host,
) -> None:
    """Managed browser profile directories should start without browser databases."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    profiles_root = f"{user_home}/.local/share/workstation-manager/browser-profiles"
    profile_ids = ["personal", "escemi"]
    seeded_files = [
        "Default/Cookies",
        "Default/History",
        "Default/Login Data",
        "Default/Preferences",
    ]

    # Act
    profile_seed_files = {
        f"{profile_id}:{seeded_file}": host.file(
            f"{profiles_root}/{profile_id}/{seeded_file}"
        )
        for profile_id in profile_ids
        for seeded_file in seeded_files
    }

    # Assert
    for file_key, profile_seed_file in profile_seed_files.items():
        assert not profile_seed_file.exists, file_key
