"""End-to-end checks for the system tests."""


def test_system_locale_configuration(host) -> None:
    """The installed machine should persist the configured locale."""

    # Arrange
    locale_file = host.file("/etc/default/locale")

    # Act
    has_lang = locale_file.contains("LANG=en_US.UTF-8")
    has_lc_all = locale_file.contains("LC_ALL=en_US.UTF-8")

    # Assert
    assert locale_file.exists
    assert has_lang
    assert has_lc_all


def test_system_timezone_configuration(host) -> None:
    """The installed machine should persist the configured timezone."""

    # Arrange
    timezone_file = host.file("/etc/timezone")

    # Act
    has_timezone = timezone_file.contains("Europe/Paris")
    localtime_target = host.check_output("readlink -f /etc/localtime")

    # Assert
    assert timezone_file.exists
    assert has_timezone
    assert localtime_target == "/usr/share/zoneinfo/Europe/Paris"


def test_system_state_file(host) -> None:
    """The installation should write the system state marker."""

    # Arrange
    system_state = host.file("/etc/workstation-manager-v1/system.json")

    # Act
    is_managed = system_state.contains('"managed": true')

    # Assert
    assert system_state.exists
    assert is_managed
