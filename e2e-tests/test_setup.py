"""End-to-end checks for the setup bootstrap tests."""

import json


def test_setup_installs_and_configures_orca(host) -> None:
    """Orca should be installed with a launcher and usable initial settings."""

    user_home = host.check_output("printf '%s' \"$HOME\"")
    data_file = host.file(f"{user_home}/.config/orca/orca-data.json")

    assert host.package("orca-ide").is_installed
    assert host.run("command -v orca-ide").succeeded
    assert host.file("/usr/share/applications/orca-ide.desktop").exists
    assert data_file.is_file
    assert data_file.mode == 0o600
    settings = json.loads(data_file.content_string)["settings"]
    assert settings["theme"] == "system"
    assert settings["terminalFontFamily"] == "Fira Code"
    assert settings["workspaceDir"] == f"{user_home}/Documents/dev-projects/workspaces/orca"
    assert host.file(settings["workspaceDir"]).is_directory


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


def test_setup_manages_weekly_bleachbit_schedule(host) -> None:
    """Setup should install the weekly BleachBit preset-clean timer assets."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    clean_command = f"{user_home}/.local/bin/workstation-manager-bleachbit-clean"
    helper_script = host.file(f"{user_home}/.local/share/workstation-manager/bleachbit-clean.py")
    activator_script = host.file(f"{user_home}/.local/bin/workstation-manager-bleachbit-clean-activate-timer")
    service_unit = host.file(f"{user_home}/.config/systemd/user/workstation-manager-bleachbit-clean.service")
    timer_unit = host.file(f"{user_home}/.config/systemd/user/workstation-manager-bleachbit-clean.timer")
    timer_link = f"{user_home}/.config/systemd/user/timers.target.wants/workstation-manager-bleachbit-clean.timer"
    autostart_file = host.file(f"{user_home}/.config/autostart/workstation-manager-bleachbit-clean.desktop")

    # Act
    clean_result = host.run(clean_command)
    timer_link_result = host.run("test -L %s", timer_link)

    # Assert
    for installed_file, expected_mode in ((helper_script, 0o644), (activator_script, 0o755)):
        assert installed_file.exists
        assert installed_file.mode == expected_mode
    assert service_unit.exists
    assert service_unit.contains(r"^ExecStart=%h/\.local/bin/workstation-manager-bleachbit-clean$")
    assert timer_unit.exists
    assert timer_unit.contains(r"^OnCalendar=weekly$")
    assert timer_unit.contains(r"^Persistent=true$")
    assert timer_link_result.succeeded
    assert autostart_file.exists
    assert autostart_file.contains(
        rf"^Exec={user_home}/\.local/bin/workstation-manager-bleachbit-clean-activate-timer$"
    )
    assert clean_result.succeeded


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
    assert not host.file(f"{user_home}/dev-projects/client-restore").exists
    # Ansible's Git module converts absolute local repository paths to file URLs.
    assert origin_url == "file:///tmp/workstation-manager-e2e-origin-client-restore.git"
    assert current_branch == "main"


def test_setup_replays_managed_user_backup_data(host) -> None:
    """Setup should replay the backup archive after the managed baseline is applied."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    managed_config_file = host.file(f"{user_home}/.config/workstation-manager/restore-fixture.txt")
    # Assert
    assert managed_config_file.exists
    assert managed_config_file.is_file
    assert managed_config_file.contains("managed-config-fixture")


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
