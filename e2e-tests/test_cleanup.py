"""End-to-end checks for the cleanup workflow."""

import re


def test_cleanup_report_is_written(host) -> None:
    """The cleanup flow should write its machine-readable report."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    cleanup_report = host.file(
        f"{user_home}/.local/state/workstation-manager-v1/cleanup-report.json"
    )
    cleanup_report_path = (
        f"{user_home}/.local/state/workstation-manager-v1/cleanup-report.json"
    )

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


def test_cleanup_removes_unmanaged_browser_profile_directories(host) -> None:
    """Cleanup should delete unmanaged browser profile directories under the managed root."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    stale_profile_dir = (
        f"{user_home}/.local/share/workstation-manager/browser-profiles/e2e-stale"
    )
    cleanup_report_path = (
        f"{user_home}/.local/state/workstation-manager-v1/cleanup-report.json"
    )
    cleanup_report = host.file(cleanup_report_path)

    # Act
    stale_profile = host.file(stale_profile_dir)
    removed_profile_recorded = cleanup_report.contains(re.escape(stale_profile_dir))
    cleanup_result = host.run(
        "python3 -c %s %s %s",
        (
            "import json,sys; "
            "report=json.load(open(sys.argv[1], encoding='utf-8')); "
            "removed=report['actions']['removed_browser_profile_directories']; "
            "drift=report['drift']['unmanaged_browser_profile_directories']; "
            "raise SystemExit(0 if sys.argv[2] in removed and sys.argv[2] in drift else 1)"
        ),
        cleanup_report_path,
        stale_profile_dir,
    )

    # Assert
    assert not stale_profile.exists
    assert removed_profile_recorded
    assert cleanup_result.succeeded
