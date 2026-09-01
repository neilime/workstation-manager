"""End-to-end checks for the setup bootstrap tests."""


def test_setup_bootstrap_tools_are_available(host) -> None:
    """The bootstrapped machine should have the setup tools available."""

    # Arrange
    ansible_pull_command = "command -v ansible-pull"
    chezmoi_command = "command -v chezmoi"
    git_command = "command -v git"

    # Act
    ansible_pull_result = host.run(ansible_pull_command)
    chezmoi_result = host.run(chezmoi_command)
    git_result = host.run(git_command)

    # Assert
    assert ansible_pull_result.succeeded
    assert chezmoi_result.succeeded
    assert git_result.succeeded


def test_setup_reattaches_restored_git_project(host) -> None:
    """Setup should reattach restored Git-backed projects to their recorded remote."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    restored_project_file = host.file(f"{user_home}/Documents/dev-projects/client-restore/project.txt")
    restored_git_dir = host.file(f"{user_home}/Documents/dev-projects/client-restore/.git")
    restored_local_note = host.file(f"{user_home}/Documents/dev-projects/client-restore/local-note.txt")

    # Act
    origin_url = host.check_output(
        "git -C %s remote get-url origin",
        f"{user_home}/Documents/dev-projects/client-restore",
    )
    current_branch = host.check_output(
        "git -C %s branch --show-current",
        f"{user_home}/Documents/dev-projects/client-restore",
    )

    # Assert
    assert restored_project_file.exists
    assert restored_project_file.is_file
    assert restored_project_file.contains("restored-project")
    assert restored_git_dir.exists
    assert restored_git_dir.is_directory
    assert restored_local_note.exists
    assert restored_local_note.is_file
    assert restored_local_note.contains("local-untracked")
    assert origin_url == "/tmp/workstation-manager-e2e-origin-client-restore.git"
    assert current_branch == "main"


def test_setup_replays_managed_user_backup_data(host) -> None:
    """Setup should replay the backup archive after the managed baseline is applied."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    managed_config_file = host.file(f"{user_home}/.config/workstation-manager/restore-fixture.txt")
    browser_profile_file = host.file(
        f"{user_home}/.local/share/workstation-manager/browser-profiles/personal/profile.txt"
    )
    chrome_bookmarks_file = host.file(f"{user_home}/.config/google-chrome/Default/Bookmarks")

    # Assert
    assert managed_config_file.exists
    assert managed_config_file.is_file
    assert managed_config_file.contains("managed-config-fixture")
    assert browser_profile_file.exists
    assert browser_profile_file.is_file
    assert browser_profile_file.contains("browser-profile-fixture")
    assert chrome_bookmarks_file.exists
    assert chrome_bookmarks_file.is_file
    assert chrome_bookmarks_file.contains('"checksum": "backup-fixture"')


def test_setup_preserves_local_git_worktree_changes_after_reattach(host) -> None:
    """Setup should preserve backed-up local worktree changes on top of the cloned repo."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    tracked_file = host.file(f"{user_home}/Documents/dev-projects/client-restore/tracked.txt")

    # Assert
    assert tracked_file.exists
    assert tracked_file.is_file
    assert tracked_file.contains("remote-base")
    assert tracked_file.contains("local-change")
