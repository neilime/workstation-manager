"""End-to-end checks for development tooling."""


def resolve_mise_command(host, tool: str):
    """Return the resolved command path for a mise-managed tool."""

    return host.run(
        "bash -lc \
        '. \"$HOME/.config/workstation-manager/mise.sh\" && command -v %s'",
        tool,
    )


def run_with_mise_activation(host, command: str):
    """Run a shell command after loading the managed mise activation."""

    return host.run(
        "bash -lc \
        '. \"$HOME/.config/workstation-manager/mise.sh\" && %s'",
        command,
    )


def assert_mise_tool_is_declared(config_file, tool_name: str) -> None:
    """Assert that the global mise config declares a non-empty version selector."""

    assert config_file.contains(rf'^"{tool_name}" = "[^"][^"]*"$')


def assert_mise_tool_uses_pinned_version(config_file, tool_name: str) -> None:
    """Assert that the global mise config pins the tool to one concrete version."""

    assert config_file.contains(rf'^"{tool_name}" = "[0-9][0-9.]*"$')


def assert_mise_tool_uses_major_track(config_file, tool_name: str) -> None:
    """Assert that the global mise config tracks a major version line."""

    assert config_file.contains(rf'^"{tool_name}" = "[0-9][0-9]*"$')


def test_declared_development_tools_are_available(host) -> None:
    """The installed machine should provide representative command-line tools."""

    # Act
    git_result = host.run("command -v git")
    make_result = host.run("command -v make")
    docker_result = resolve_mise_command(host, "docker")
    docker_buildx_result = run_with_mise_activation(host, "docker buildx version")
    docker_compose_result = run_with_mise_activation(host, "docker compose version")
    mise_result = resolve_mise_command(host, "mise")
    mise_github_cli_result = resolve_mise_command(host, "gh")
    mise_deja_result = resolve_mise_command(host, "deja")
    mise_node_result = resolve_mise_command(host, "node")
    mise_php_result = resolve_mise_command(host, "php")
    mise_helm_result = resolve_mise_command(host, "helm")

    # Assert
    assert git_result.succeeded
    assert make_result.succeeded
    assert docker_result.succeeded
    assert docker_buildx_result.succeeded
    assert docker_compose_result.succeeded
    assert mise_result.succeeded
    assert mise_github_cli_result.succeeded
    assert mise_deja_result.succeeded
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
    assert_mise_tool_uses_pinned_version(config_file, "php")
    assert_mise_tool_is_declared(config_file, "aqua:cli/cli")
    assert_mise_tool_uses_pinned_version(config_file, "github:Giammarco-Ferranti/deja")
    assert_mise_tool_is_declared(config_file, "aqua:docker/cli")
    assert_mise_tool_is_declared(config_file, "aqua:docker/compose")
    assert_mise_tool_uses_major_track(config_file, "aqua:helm/helm")
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
    has_watch_limit = sysctl_file.contains(r"^fs\.inotify\.max_user_watches\s*=\s*524288$")
    configured_watch_limit = host.check_output("sysctl -n fs.inotify.max_user_watches")

    # Assert
    assert sysctl_file.exists
    assert has_watch_limit
    assert configured_watch_limit == "524288"


def test_git_project_report_command_and_schedule_are_managed(host) -> None:
    """Development tooling should install the Git report command and its daily schedule."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    report_command = f"{user_home}/.local/bin/workstation-manager-git-project-report"
    helper_script = host.file(f"{user_home}/.local/share/workstation-manager/git-project-report.py")
    activator_script = host.file(f"{user_home}/.local/bin/workstation-manager-git-project-report-activate-timer")
    service_unit = host.file(f"{user_home}/.config/systemd/user/workstation-manager-git-project-report.service")
    timer_unit = host.file(f"{user_home}/.config/systemd/user/workstation-manager-git-project-report.timer")
    timer_link = f"{user_home}/.config/systemd/user/timers.target.wants/workstation-manager-git-project-report.timer"
    autostart_file = host.file(f"{user_home}/.config/autostart/workstation-manager-git-project-report.desktop")

    # Act
    notify_send_result = host.run("command -v notify-send")
    report_result = host.run(report_command)
    timer_link_result = host.run("test -L %s", timer_link)

    # Assert
    assert notify_send_result.succeeded
    assert helper_script.exists
    assert helper_script.mode == 0o644
    assert activator_script.exists
    assert activator_script.mode == 0o755
    assert service_unit.exists
    assert service_unit.contains(r"^ExecStart=%h/\.local/bin/workstation-manager-git-project-report --notify$")
    assert timer_unit.exists
    assert timer_unit.contains(r"^OnCalendar=daily$")
    assert timer_unit.contains(r"^Persistent=true$")
    assert timer_link_result.succeeded
    assert autostart_file.exists
    assert autostart_file.contains(
        rf"^Exec={user_home}/\.local/bin/workstation-manager-git-project-report-activate-timer$"
    )
    assert report_result.succeeded
    assert "client-restore [main]" in report_result.stdout
    assert "local-note.txt" in report_result.stdout
    assert "tracked.txt" in report_result.stdout
