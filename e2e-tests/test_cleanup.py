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


def test_cleanup_preserves_all_native_browser_profiles_and_internal_data(host) -> None:
    """Undeclared native profiles and Brave internal directories must survive cleanup."""

    user_home = host.check_output("printf '%s' \"$HOME\"")
    root = f"{user_home}/.config/BraveSoftware/Brave-Browser"
    unmanaged_paths = [f"{root}/managed-e2e-stale", f"{root}/Profile 9999"]
    internal_path = f"{root}/e2e-component-cache"
    report_path = f"{user_home}/.local/state/workstation-manager-v1/cleanup-report.json"
    report = json.loads(host.file(report_path).content_string)

    assert set(unmanaged_paths) <= set(report["drift"]["unmanaged_browser_profile_directories"])
    assert internal_path not in report["drift"]["unmanaged_browser_profile_directories"]
    for profile_path in unmanaged_paths:
        assert host.file(f"{profile_path}/Preferences").exists
        assert host.file(f"{profile_path}/e2e-preserve-marker").content_string == "preserve\n"
    assert host.file(f"{internal_path}/e2e-preserve-marker").content_string == "preserve\n"
