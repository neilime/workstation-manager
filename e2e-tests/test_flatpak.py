"""End-to-end checks for managed Flatpak applications."""


def test_flathub_remote_is_configured(host) -> None:
    """The installed machine should configure the declared Flatpak remote."""

    # Arrange
    remote_command = "flatpak remotes --system --columns=name"

    # Act
    remote_result = host.run(remote_command)

    # Assert
    assert remote_result.succeeded
    assert "flathub" in remote_result.stdout.splitlines()


def test_declared_flatpak_applications_are_installed(host) -> None:
    """The installed machine should install the declared Flatpak applications."""

    # Arrange
    application_command = "flatpak list --system --app --columns=application"

    # Act
    application_result = host.run(application_command)

    # Assert
    assert application_result.succeeded
    installed_applications = application_result.stdout.splitlines()

    assert "org.torproject.torbrowser-launcher" in installed_applications
    assert "com.slack.Slack" in installed_applications
    assert "com.usebruno.Bruno" in installed_applications
    assert "com.spotify.Client" in installed_applications
    assert "org.videolan.VLC" in installed_applications
    assert "org.jdownloader.JDownloader" in installed_applications
    assert "com.github.hluk.copyq" in installed_applications
    assert "org.gnome.SimpleScan" in installed_applications
    assert "org.gnome.DejaDup" in installed_applications
    assert "org.libreoffice.LibreOffice" in installed_applications
    assert "com.bitwarden.desktop" in installed_applications
