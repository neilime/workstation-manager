"""End-to-end checks for the desktop tests."""

import ast
import json
import pathlib

import pytest


def test_current_ubuntu_desktop_and_terminal(host) -> None:
    """The VM qualifies Ubuntu's current Wayland session and native terminal."""
    assert host.package("ptyxis").is_installed
    assert host.package("gnome-shell-ubuntu-extensions").is_installed
    assert host.file("/usr/share/applications/org.gnome.Ptyxis.desktop").exists
    sessions = host.check_output("loginctl list-sessions --json=short")
    types = [
        host.check_output("loginctl show-session %s -p Type --value", session["session"])
        for session in json.loads(sessions)
        if session["user"] == host.user().name
    ]
    assert "wayland" in types


def test_gnome_portals_and_keyring_are_available_in_the_user_session(host) -> None:
    """Desktop applications can reach GNOME portals and open a Secret Service session."""
    user_id = host.user().uid
    environment = f"XDG_RUNTIME_DIR=/run/user/{user_id} DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{user_id}/bus"
    portal = host.check_output(
        f"env {environment} gdbus introspect --session --dest org.freedesktop.portal.Desktop "
        "--object-path /org/freedesktop/portal/desktop"
    )
    assert "org.freedesktop.portal.FileChooser" in portal
    assert "org.freedesktop.portal.ScreenCast" in portal
    assert host.package("gnome-keyring").is_installed
    assert host.package("libpam-gnome-keyring").is_installed
    session = host.run(
        f"env {environment} gdbus call --session --dest org.freedesktop.secrets "
        "--object-path /org/freedesktop/secrets --method org.freedesktop.Secret.Service.OpenSession plain %s",
        "<''>",
    )
    assert session.succeeded, session.stderr


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


def test_desktop_dark_mode(host) -> None:
    """Setup always selects GNOME's dark color scheme."""
    assert (
        host.check_output("dbus-run-session -- gsettings get org.gnome.desktop.interface color-scheme")
        == "'prefer-dark'"
    )


def test_projects_directory_is_bookmarked_in_files(host) -> None:
    """The projects directory should appear once in the Files sidebar bookmarks."""
    user_home = host.check_output('printf %s "$HOME"')
    user_name = host.check_output("whoami")
    projects = pathlib.Path(user_home) / "Documents/dev-projects"
    bookmarks = host.file(f"{user_home}/.config/gtk-3.0/bookmarks")

    assert host.file(str(projects)).is_directory
    assert bookmarks.is_file
    assert bookmarks.user == user_name
    bookmark_uris = [line.split(" ", maxsplit=1)[0].rstrip("/") for line in bookmarks.content_string.splitlines()]
    assert bookmark_uris.count(projects.as_uri()) == 1


def test_desktop_wallpaper(host) -> None:
    """The branded wallpaper should be installed and selected for both color schemes."""

    # Arrange
    user_home = host.check_output('printf %s "$HOME"')
    wallpaper_path = f"{user_home}/.local/share/backgrounds/wallpaper.jpg"
    wallpaper_file = host.file(wallpaper_path)
    expected_uri = f"'file://{wallpaper_path}'"
    background_setting_command = "dbus-run-session -- gsettings get org.gnome.desktop.background"

    # Act
    picture_uri = host.check_output(f"{background_setting_command} picture-uri")
    picture_uri_dark = host.check_output(f"{background_setting_command} picture-uri-dark")
    picture_options = host.check_output(f"{background_setting_command} picture-options")

    # Assert
    assert wallpaper_file.exists
    assert wallpaper_file.is_file
    assert wallpaper_file.user == host.check_output("whoami")
    assert wallpaper_file.mode == 0o644
    source = host.file(f"{user_home}/.local/share/chezmoi/home/dot_local/share/backgrounds/wallpaper.jpg")
    assert wallpaper_file.sha256sum == source.sha256sum
    assert picture_uri == expected_uri
    assert picture_uri_dark == expected_uri
    assert picture_options == "'zoom'"


def test_desktop_favorites_preference(host, workstation_config) -> None:
    """The dock should contain the desired applications in the desired order."""

    # Arrange
    configured_favorites = workstation_config["desktop"]["gnome"]["favorites"]
    if configured_favorites is None:
        pytest.skip("Favorite applications are not configured")
    default_browser_app_id = host.check_output("xdg-mime query default text/html")

    # Act
    favorite_app_ids = read_favorite_app_ids(host)

    # Assert
    assert default_browser_app_id
    assert favorite_app_ids == [
        default_browser_app_id if app_id == "browser" else app_id for app_id in configured_favorites
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


def test_desktop_trash_is_visible(host) -> None:
    """Setup always shows Trash in Ubuntu Dock."""
    assert (
        host.check_output("dbus-run-session -- gsettings get org.gnome.shell.extensions.dash-to-dock show-trash")
        == "true"
    )


def test_native_scanner_has_one_delivery(host) -> None:
    """Native Simple Scan and SANE replace both possible Flatpak installations."""
    assert host.package("simple-scan").is_installed
    assert host.package("sane-utils").is_installed
    for method in ("--system", "--user"):
        applications = host.check_output("flatpak list %s --app --columns=application", method).splitlines()
        assert "org.gnome.SimpleScan" not in applications
    assert host.run("simple-scan --version").succeeded
    assert host.run("scanimage --version").succeeded


def test_selected_clipboard_extension_is_active(host, workstation_config) -> None:
    """The managed release must load in Wayland with exactly one clipboard manager."""
    selection = workstation_config["desktop"]["clipboard_indicator"]
    root = f"{host.user().home}/.local/share/gnome-shell/extensions/clipboard-indicator@tudmotu.com"
    metadata = json.loads(host.file(f"{root}/metadata.json").content_string)
    assert str(metadata["version"]) == selection["version"]
    assert host.file(f"{root}/extension.zip").sha256sum == selection["sha256"]
    assert host.run("pgrep --uid %s --exact copyq", host.user().name).rc == 1
    for method in ("--system", "--user"):
        assert (
            "com.github.hluk.copyq"
            not in host.check_output("flatpak list %s --app --columns=application", method).splitlines()
        )
    environment = (
        f"XDG_RUNTIME_DIR=/run/user/{host.user().uid} "
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{host.user().uid}/bus"
    )
    info = host.check_output(f"env {environment} gnome-extensions info clipboard-indicator@tudmotu.com")
    assert "State: ACTIVE" in info
