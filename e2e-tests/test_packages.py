"""End-to-end checks for managed package and CLI availability."""


def resolve_mise_command(host, tool: str):
    """Return the resolved command path for a mise-managed tool."""

    return host.run(
        "bash -lc \
        '. \"$HOME/.config/workstation-manager/mise.sh\" && command -v %s'",
        tool,
    )


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


def test_declared_development_commands_are_available(host) -> None:
    """The installed machine should expose representative development commands."""

    # Arrange
    htop_command = "command -v htop"
    ucaresystem_command = "command -v ucaresystem-core"
    zsh_command = "command -v zsh"

    # Act
    htop_result = host.run(htop_command)
    github_cli_result = resolve_mise_command(host, "gh")
    ucaresystem_result = host.run(ucaresystem_command)
    zsh_result = host.run(zsh_command)
    starship_result = resolve_mise_command(host, "starship")

    # Assert
    assert htop_result.succeeded
    assert github_cli_result.succeeded
    assert ucaresystem_result.succeeded
    assert zsh_result.succeeded
    assert starship_result.succeeded
