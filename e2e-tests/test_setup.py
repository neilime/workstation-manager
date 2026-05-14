"""End-to-end checks for the setup bootstrap tests."""


def test_setup_bootstrap_tools_are_available(host) -> None:
    """The bootstrapped machine should have the setup tools available."""

    # Arrange
    ansible_pull_command = "command -v ansible-pull"
    chezmoi_command = "command -v chezmoi"
    git_command = "command -v git"

    # Act
    ansible_pull_result = host.run(ansible_pull_command)
    chezmoi_result = host.run(chezmoi_command)
    git_result = host.run(git_command)

    # Assert
    assert ansible_pull_result.succeeded
    assert chezmoi_result.succeeded
    assert git_result.succeeded
