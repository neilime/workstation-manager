"""End-to-end checks for the desktop tests."""


def test_desktop_dark_mode_preference(host) -> None:
    """The installed machine should persist the configured GNOME color scheme."""

    # Arrange
    color_scheme_command = (
        "dbus-run-session -- gsettings get org.gnome.desktop.interface color-scheme"
    )

    # Act
    color_scheme = host.check_output(color_scheme_command)

    # Assert
    assert color_scheme == "'prefer-dark'"


def test_desktop_favorites_preference(host) -> None:
    """The installed machine should persist the configured GNOME favorites."""

    # Act
    favorites = host.check_output(
        "dbus-run-session -- gsettings get org.gnome.shell favorite-apps"
    )

    # Assert
    assert favorites == (
        "['gnome-control-center.desktop', 'org.gnome.Nautilus.desktop', "
        "'com.slack.Slack.desktop', 'com.visualstudio.code.desktop', "
        "'org.gnome.Terminal.desktop', 'com.spotify.Client.desktop', "
        "'com.github.hluk.copyq.desktop', 'com.bitwarden.desktop.desktop']"
    )
