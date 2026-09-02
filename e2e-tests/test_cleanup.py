"""End-to-end checks for the cleanup workflow."""

import json


def test_cleanup_report_is_written(host) -> None:
    """The cleanup flow should write its machine-readable report."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    cleanup_report = host.file(f"{user_home}/.local/state/workstation-manager-v1/cleanup-report.json")
    cleanup_report_path = f"{user_home}/.local/state/workstation-manager-v1/cleanup-report.json"

    # Act
    cleanup_mode_result = host.run(
        "python3 -c %s %s",
        (
            "import json,sys; "
            "report=json.load(open(sys.argv[1], encoding='utf-8')); "
            "raise SystemExit(0 if report['cleanup_mode'] == 'apply' else 1)"
        ),
        cleanup_report_path,
    )

    # Assert
    assert cleanup_report.exists
    assert cleanup_report.is_file
    assert cleanup_report.user == host.check_output("whoami")
    assert cleanup_mode_result.succeeded


def test_cleanup_runs_system_maintenance(host) -> None:
    """Cleanup should complete its APT maintenance and journal vacuum actions."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    cleanup_report_path = f"{user_home}/.local/state/workstation-manager-v1/cleanup-report.json"

    # Act
    cleanup_report = json.loads(host.file(cleanup_report_path).content_string)
    actions = cleanup_report["actions"]

    # Assert
    assert isinstance(actions["apt_upgrade_changed"], bool)
    assert actions["journal_vacuum_exit_code"] == 0
    assert actions["apt_autoremove_requested"] is True


def test_cleanup_report_preserves_json_scalar_types(host) -> None:
    """Cleanup report scalars should retain their machine-readable JSON types."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    cleanup_report_path = f"{user_home}/.local/state/workstation-manager-v1/cleanup-report.json"

    # Act
    cleanup_report = json.loads(host.file(cleanup_report_path).content_string)
    actions = cleanup_report["actions"]

    # Assert
    assert isinstance(cleanup_report["package_baseline_available"], bool)
    assert isinstance(actions["docker_prune_available"], bool)
    assert actions["docker_prune_exit_code"] is None or (
        isinstance(actions["docker_prune_exit_code"], int) and not isinstance(actions["docker_prune_exit_code"], bool)
    )
    assert isinstance(actions["apt_upgrade_changed"], bool)
    assert actions["journal_vacuum_exit_code"] is None or (
        isinstance(actions["journal_vacuum_exit_code"], int)
        and not isinstance(actions["journal_vacuum_exit_code"], bool)
    )
    assert isinstance(actions["apt_autoremove_requested"], bool)


def test_cleanup_removes_only_unmanaged_browser_profile_directories(host) -> None:
    """Cleanup should delete the stale profile while preserving declared profiles."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    stale_profile_dir = f"{user_home}/.local/share/workstation-manager/browser-profiles/e2e-stale"
    cleanup_report_path = f"{user_home}/.local/state/workstation-manager-v1/cleanup-report.json"

    # Act
    stale_profile = host.file(stale_profile_dir)
    cleanup_report = json.loads(host.file(cleanup_report_path).content_string)
    removed_profiles = cleanup_report["actions"]["removed_browser_profile_directories"]
    unmanaged_profiles = cleanup_report["drift"]["unmanaged_browser_profile_directories"]

    # Assert
    assert not stale_profile.exists
    assert removed_profiles == [stale_profile_dir]
    assert unmanaged_profiles == [stale_profile_dir]
