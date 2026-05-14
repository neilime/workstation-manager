"""End-to-end checks for development tooling."""


def test_declared_development_tools_are_available(host) -> None:
    """The installed machine should provide representative command-line tools."""

    mise_lookup_command = (
        'bash -lc \'. "$HOME/.config/workstation-manager/mise.sh" '
        "&& command -v {tool}'"
    )

    # Act
    git_result = host.run("command -v git")
    make_result = host.run("command -v make")
    github_cli_result = host.run("command -v gh")
    docker_result = host.run("command -v docker")
    docker_buildx_result = host.run("docker buildx version")
    docker_compose_result = host.run("docker compose version")
    mise_result = host.run(mise_lookup_command.format(tool="mise"))
    mise_node_result = host.run(mise_lookup_command.format(tool="node"))
    mise_php_result = host.run(mise_lookup_command.format(tool="php"))
    mise_helm_result = host.run(mise_lookup_command.format(tool="helm"))

    # Assert
    assert git_result.succeeded
    assert make_result.succeeded
    assert github_cli_result.succeeded
    assert docker_result.succeeded
    assert docker_buildx_result.succeeded
    assert docker_compose_result.succeeded
    assert mise_result.succeeded
    assert mise_node_result.succeeded
    assert mise_php_result.succeeded
    assert mise_helm_result.succeeded


def test_mise_global_config_and_activation_are_managed(host) -> None:
    """The installed machine should manage global mise configuration and activation."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    config_file = host.file(f"{user_home}/.config/mise/config.toml")
    activation_file = host.file(f"{user_home}/.config/workstation-manager/mise.sh")

    # Assert
    assert config_file.exists
    assert config_file.contains('"node" = "lts"')
    assert config_file.contains(r'^"php" = "[^"]+"$')
    assert config_file.contains('"aqua:cli/cli" = "latest"')
    assert config_file.contains('"aqua:docker/cli" = "latest"')
    assert config_file.contains('"aqua:docker/compose" = "latest"')
    assert config_file.contains(r'^"aqua:helm/helm" = "\d+"$')
    assert activation_file.exists
    assert activation_file.contains('MISE_BACKENDS_PHP="vfox:mise-plugins/vfox-php"')
    assert activation_file.contains('eval "$("$HOME/.local/bin/mise" activate zsh)"')


def test_development_vendor_repositories_are_not_required(host) -> None:
    """The installed machine should not require vendor APT repositories for dev CLIs."""

    # Arrange
    github_keyring_file = host.file("/usr/share/keyrings/githubcli-archive-keyring.gpg")
    github_source_file = host.file("/etc/apt/sources.list.d/github-cli.list")
    docker_keyring_file = host.file("/etc/apt/keyrings/docker.asc")
    docker_source_file = host.file("/etc/apt/sources.list.d/docker.list")

    # Act
    # Assert
    assert not github_keyring_file.exists
    assert not github_source_file.exists
    assert not docker_keyring_file.exists
    assert not docker_source_file.exists


def test_declared_editor_package_is_installed(host) -> None:
    """The installed machine should install the declared editor package."""

    # Arrange
    application_command = "flatpak list --system --app --columns=application"

    # Act
    application_result = host.run(application_command)

    # Assert
    assert application_result.succeeded
    assert "com.visualstudio.code" in application_result.stdout.splitlines()


def test_development_sysctl_configuration(host) -> None:
    """Development tooling should apply the configured filesystem watch limit."""

    # Arrange
    sysctl_file = host.file("/etc/sysctl.d/99-workstation-manager.conf")

    # Act
    has_watch_limit = sysctl_file.contains(
        r"^fs\.inotify\.max_user_watches\s*=\s*524288$"
    )
    configured_watch_limit = host.check_output("sysctl -n fs.inotify.max_user_watches")

    # Assert
    assert sysctl_file.exists
    assert has_watch_limit
    assert configured_watch_limit == "524288"
