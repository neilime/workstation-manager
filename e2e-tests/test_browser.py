"""End-to-end checks for the primary browser."""


def test_primary_browser_vendor_repository_is_configured(host) -> None:
    """The installed machine should persist the primary browser vendor repository."""

    # Arrange
    keyring_file = host.file("/usr/share/keyrings/google-linux-signing-key.asc")
    source_file = host.file("/etc/apt/sources.list.d/google-chrome.list")

    # Act
    has_repository_url = source_file.contains("https://dl.google.com/linux/chrome/deb/")
    has_signed_by = source_file.contains(
        "signed-by=/usr/share/keyrings/google-linux-signing-key.asc"
    )

    # Assert
    assert keyring_file.exists
    assert source_file.exists
    assert has_repository_url
    assert has_signed_by


def test_primary_browser_is_installed_and_default(host) -> None:
    """The installed machine should install Chrome and register it as default."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    browser_command = "command -v google-chrome"
    mimeapps_file = host.file(f"{user_home}/.config/mimeapps.list")

    # Act
    browser_result = host.run(browser_command)
    has_http_default = mimeapps_file.contains(
        "x-scheme-handler/http=google-chrome.desktop"
    )
    has_https_default = mimeapps_file.contains(
        "x-scheme-handler/https=google-chrome.desktop"
    )
    has_html_default = mimeapps_file.contains("text/html=google-chrome.desktop")

    # Assert
    assert browser_result.succeeded
    assert mimeapps_file.exists
    assert has_http_default
    assert has_https_default
    assert has_html_default
