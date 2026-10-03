"""End-to-end checks for managed package and CLI availability."""


def resolve_mise_command(host, tool: str):
    """Return the resolved command path for a mise-managed tool."""

    return host.run(
        "bash -lc \
        '. \"$HOME/.config/workstation-manager/mise.sh\" && command -v %s'",
        tool,
    )


def test_declared_development_commands_are_available(host) -> None:
    """The installed machine should expose representative development commands."""

    # Arrange
    # Ubuntu 24.04's bat APT package installs the executable as batcat.
    bat_command = "command -v batcat"
    bleachbit_command = "command -v bleachbit"
    htop_command = "command -v htop"
    zsh_command = "command -v zsh"

    # Act
    bat_result = host.run(bat_command)
    bleachbit_result = host.run(bleachbit_command)
    htop_result = host.run(htop_command)
    github_cli_result = resolve_mise_command(host, "gh")
    zsh_result = host.run(zsh_command)
    starship_result = resolve_mise_command(host, "starship")

    # Assert
    assert bat_result.succeeded
    assert bleachbit_result.succeeded
    assert htop_result.succeeded
    assert github_cli_result.succeeded
    assert zsh_result.succeeded
    assert starship_result.succeeded
