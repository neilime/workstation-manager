"""End-to-end checks for managed APT packages."""


def test_vendor_apt_repository_is_configured(host) -> None:
    """The installed machine should persist the declared vendor APT repository."""

    # Arrange
    keyring_file = host.file("/usr/share/keyrings/githubcli-archive-keyring.gpg")
    source_file = host.file("/etc/apt/sources.list.d/github-cli.list")

    # Act
    has_repository_url = source_file.contains("https://cli.github.com/packages")
    has_signed_by = source_file.contains(
        "signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg"
    )

    # Assert
    assert keyring_file.exists
    assert source_file.exists
    assert has_repository_url
    assert has_signed_by


def test_system_vendor_apt_repository_is_configured(host) -> None:
    """The installed machine should persist the declared system vendor repository."""

    # Arrange
    keyring_file = host.file("/usr/share/keyrings/utappia-archive-keyring.asc")
    source_file = host.file("/etc/apt/sources.list.d/utappia-stable.list")

    # Act
    has_repository_url = source_file.contains(
        "https://ppa.launchpadcontent.net/utappia/stable/ubuntu"
    )
    has_signed_by = source_file.contains(
        "signed-by=/usr/share/keyrings/utappia-archive-keyring.asc"
    )

    # Assert
    assert keyring_file.exists
    assert source_file.exists
    assert has_repository_url
    assert has_signed_by


def test_declared_apt_packages_are_available(host) -> None:
    """The installed machine should install representative APT packages."""

    # Arrange
    htop_command = "command -v htop"
    github_cli_command = "command -v gh"
    ucaresystem_command = "command -v ucaresystem-core"
    zsh_command = "command -v zsh"
    starship_command = "command -v starship"

    # Act
    htop_result = host.run(htop_command)
    github_cli_result = host.run(github_cli_command)
    ucaresystem_result = host.run(ucaresystem_command)
    zsh_result = host.run(zsh_command)
    starship_result = host.run(starship_command)

    # Assert
    assert htop_result.succeeded
    assert github_cli_result.succeeded
    assert ucaresystem_result.succeeded
    assert zsh_result.succeeded
    assert starship_result.succeeded
