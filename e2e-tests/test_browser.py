"""End-to-end checks for the primary browser."""


def test_native_browser_sync_automation_is_available(host) -> None:
    """SSH-launched automation must reach the desktop and preserve disposable native profiles."""
    result = host.run("python3 /workspace/e2e-tests/browser_sync_smoke.py")
    assert result.succeeded, result.stdout + result.stderr


def test_primary_browser_vendor_repository_is_configured(host) -> None:
    """Brave uses the managed Deb822 source and its vendor signing key."""
    source = host.file("/etc/apt/sources.list.d/brave-browser-release.sources")
    keyring = "/usr/share/keyrings/brave-browser-archive-keyring.gpg"
    assert source.exists
    assert "https://brave-browser-apt-release.s3.brave.com/" in source.content_string
    assert "Signed-By: " + keyring in source.content_string
    assert host.file(keyring).exists


def test_primary_browser_is_installed_and_default(host) -> None:
    """The installed machine should install Brave and register it as default."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    browser_command = "command -v brave-browser"

    # Act
    browser_result = host.run(browser_command)

    # Assert
    assert browser_result.succeeded
    for filename in ("mimeapps.list", "ubuntu-mimeapps.list", "gnome-mimeapps.list"):
        mimeapps_file = host.file(f"{user_home}/.config/{filename}")
        assert mimeapps_file.exists
        for mime_type in ("x-scheme-handler/http", "x-scheme-handler/https", "text/html"):
            assert mimeapps_file.contains(f"{mime_type}=brave-browser.desktop")

    for mime_type in ("x-scheme-handler/http", "x-scheme-handler/https", "text/html"):
        default = host.check_output("env XDG_CURRENT_DESKTOP=ubuntu:GNOME xdg-mime query default %s", mime_type)
        assert default == "brave-browser.desktop"
