"""End-to-end checks for the desktop tests."""

import ast


def read_favorite_app_ids(host) -> list[str]:
    """Return the configured GNOME favorite application IDs in dock order."""

    value = host.check_output("dbus-run-session -- gsettings get org.gnome.shell favorite-apps")
    favorite_app_ids = ast.literal_eval(value)

    assert isinstance(favorite_app_ids, list)
    assert all(isinstance(app_id, str) for app_id in favorite_app_ids)
    return favorite_app_ids


def read_gnome_shell_application_directories(host) -> list[str]:
    """Return the application directories visible to the running GNOME Shell."""

    shell_environment = host.check_output(
        'shell_pid=$(pgrep --euid "$(id -u)" --oldest --exact gnome-shell); '
        "tr '\\0' '\\n' <\"/proc/${shell_pid}/environ\""
    )
    environment = dict(line.split("=", maxsplit=1) for line in shell_environment.splitlines() if "=" in line)
    data_home = environment.get("XDG_DATA_HOME", f"{environment['HOME']}/.local/share")
    data_directories = environment.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")

    return [f"{directory}/applications" for directory in [data_home, *data_directories]]


def desktop_application_exists(host, app_id: str, application_directories: list[str]) -> bool:
    """Return whether an application ID resolves in the supplied XDG directories."""

    return any(host.file(f"{directory}/{app_id}").exists for directory in application_directories)


def test_desktop_dark_mode_preference(host) -> None:
    """The installed machine should persist the configured GNOME color scheme."""

    # Arrange
    color_scheme_command = "dbus-run-session -- gsettings get org.gnome.desktop.interface color-scheme"

    # Act
    color_scheme = host.check_output(color_scheme_command)

    # Assert
    assert color_scheme == "'prefer-dark'"


def test_desktop_favorites_preference(host) -> None:
    """The dock should contain the desired applications in the desired order."""

    # Arrange
    default_browser_app_id = host.check_output("xdg-mime query default text/html")

    # Act
    favorite_app_ids = read_favorite_app_ids(host)

    # Assert
    assert default_browser_app_id
    assert favorite_app_ids == [
        "org.gnome.Nautilus.desktop",
        "org.gnome.Software.desktop",
        "com.visualstudio.code.desktop",
        default_browser_app_id,
        "com.slack.Slack.desktop",
        "com.spotify.Client.desktop",
        "com.github.hluk.copyq.desktop",
        "com.bitwarden.desktop.desktop",
        "org.gnome.Terminal.desktop",
    ]


def test_desktop_favorite_applications_are_discoverable(host) -> None:
    """Every favorite should resolve to a launcher in the running GNOME session."""

    # Act
    favorite_app_ids = read_favorite_app_ids(host)
    application_directories = read_gnome_shell_application_directories(host)

    # Assert
    assert "/var/lib/flatpak/exports/share/applications" in application_directories
    missing_app_ids = [
        app_id for app_id in favorite_app_ids if not desktop_application_exists(host, app_id, application_directories)
    ]
    assert missing_app_ids == []


def test_desktop_trash_is_pinned_to_dock(host) -> None:
    """Ubuntu Dock should display Trash after the ordered application favorites."""

    # Act
    show_trash = host.check_output(
        "dbus-run-session -- gsettings get org.gnome.shell.extensions.dash-to-dock show-trash"
    )

    # Assert
    assert show_trash == "true"
