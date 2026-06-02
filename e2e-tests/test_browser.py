"""End-to-end checks for the primary browser."""


def resolve_primary_browser_source_file(host):
    """Return the active Chrome APT source in legacy or Deb822 format."""

    source_paths = (
        "/etc/apt/sources.list.d/google-chrome.sources",
        "/etc/apt/sources.list.d/google-chrome.list",
    )
    for source_path in source_paths:
        source_file = host.file(source_path)
        if source_file.exists:
            return source_file

    raise AssertionError(f"Chrome APT source not found in: {', '.join(source_paths)}")


def test_primary_browser_vendor_repository_is_configured(host) -> None:
    """The installed machine should persist the primary browser vendor repository."""

    # Arrange
    source_file = resolve_primary_browser_source_file(host)
    repository_urls = (
        "https://dl.google.com/linux/chrome-stable/deb/",
        "https://dl.google.com/linux/chrome/deb/",
    )
    keyring_paths = (
        "/usr/share/keyrings/google-chrome.gpg",
        "/usr/share/keyrings/google-linux-signing-key.asc",
    )

    # Act
    source_content = source_file.content_string.lower()
    configured_keyrings = [path for path in keyring_paths if path.lower() in source_content]

    # Assert
    assert any(url in source_content for url in repository_urls)
    assert configured_keyrings
    assert all(host.file(path).exists for path in configured_keyrings)


def test_primary_browser_is_installed_and_default(host) -> None:
    """The installed machine should install Chrome and register it as default."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    browser_command = "command -v google-chrome"
    mimeapps_file = host.file(f"{user_home}/.config/mimeapps.list")

    # Act
    browser_result = host.run(browser_command)
    has_http_default = mimeapps_file.contains("x-scheme-handler/http=google-chrome.desktop")
    has_https_default = mimeapps_file.contains("x-scheme-handler/https=google-chrome.desktop")
    has_html_default = mimeapps_file.contains("text/html=google-chrome.desktop")

    # Assert
    assert browser_result.succeeded
    assert mimeapps_file.exists
    assert has_http_default
    assert has_https_default
    assert has_html_default
