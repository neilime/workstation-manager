"""End-to-end checks for the primary browser."""


def resolve_primary_browser_source_file(host):
    """Return the active Brave APT source in legacy or Deb822 format."""

    source_paths = (
        "/etc/apt/sources.list.d/brave-browser-release.sources",
        "/etc/apt/sources.list.d/brave-browser-release.list",
    )
    for source_path in source_paths:
        source_file = host.file(source_path)
        if source_file.exists:
            return source_file

    raise AssertionError(f"Brave APT source not found in: {', '.join(source_paths)}")


def test_primary_browser_vendor_repository_is_configured(host) -> None:
    """The installed machine should persist the primary browser vendor repository."""

    # Arrange
    source_file = resolve_primary_browser_source_file(host)
    repository_urls = (
        "https://brave-browser-apt-release.s3.brave.com/",
        "https://brave-browser-apt-release.s3.brave.com/",
    )
    keyring_paths = (
        "/usr/share/keyrings/brave-browser-archive-keyring.gpg",
        "/usr/share/keyrings/brave-browser-archive-keyring.gpg",
    )

    # Act
    source_content = source_file.content_string.lower()
    configured_keyrings = [path for path in keyring_paths if path.lower() in source_content]

    # Assert
    assert any(url in source_content for url in repository_urls)
    assert configured_keyrings
    assert all(host.file(path).exists for path in configured_keyrings)


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
