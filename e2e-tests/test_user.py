"""End-to-end checks for the user tests."""


def test_user_state_file(host) -> None:
    """The installation should write the user state marker."""

    # Arrange
    user_name = host.check_output("whoami")
    user_home = host.check_output("printf '%s' \"$HOME\"")
    user_state = host.file(
        f"{user_home}/.local/state/workstation-manager-v1/state.json"
    )

    # Act
    is_managed = user_state.contains('"managed": true')
    has_user_name = user_state.contains(f'"user": "{user_name}"')

    # Assert
    assert user_state.exists
    assert is_managed
    assert has_user_name


def test_chezmoi_bootstrap_from_tracked_repository(host) -> None:
    """The setup should clone the tracked Chezmoi repository and render machine data."""

    # Arrange
    user_name = host.check_output("whoami")
    user_home = host.check_output("printf '%s' \"$HOME\"")
    chezmoi_config = host.file(f"{user_home}/.config/chezmoi/chezmoi.yaml")
    chezmoi_source_dir = host.file(f"{user_home}/.local/share/chezmoi")
    chezmoi_git_dir = host.file(f"{user_home}/.local/share/chezmoi/.git")
    chezmoi_git_config = host.file(f"{user_home}/.local/share/chezmoi/.git/config")

    # Assert
    assert chezmoi_config.exists
    assert chezmoi_config.contains("workstation_manager:")
    assert chezmoi_config.contains(f"name: {user_name}")
    assert chezmoi_config.contains(
        f"projects_directory: {user_home}/Documents/dev-projects"
    )
    assert chezmoi_source_dir.exists
    assert chezmoi_source_dir.is_directory
    assert chezmoi_git_dir.exists
    assert chezmoi_git_dir.is_directory
    assert chezmoi_git_config.exists
    assert chezmoi_git_config.contains('[remote "origin"]')
    assert chezmoi_git_config.contains("workstation-config")
