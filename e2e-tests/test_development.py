"""End-to-end checks for development tooling."""

import json


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
    """Assert that the global mise config pins the tool to a dotted release string."""

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
    assert_mise_tool_is_declared(config_file, "aqua:docker/buildx")
    assert_mise_tool_uses_major_track(config_file, "aqua:helm/helm")
    assert activation_file.exists
    assert activation_file.contains('MISE_BACKENDS_PHP="vfox:mise-plugins/vfox-php"')
    assert activation_file.contains('eval "$("$HOME/.local/bin/mise" activate zsh)"')


def test_docker_engine_is_available_to_the_managed_user(host) -> None:
    """Docker must provide a running daemon, not just working client commands."""

    docker_service = host.service("workstation-manager-docker")
    docker_socket = host.file("/var/run/docker.sock")
    docker_info = run_with_mise_activation(host, "docker --host unix:///var/run/docker.sock info")

    assert docker_service.is_running
    assert docker_service.is_enabled
    assert docker_socket.is_socket
    assert docker_socket.group == "docker"
    assert "docker" in host.user().groups
    assert docker_info.succeeded, docker_info.stderr


def test_docker_access_without_group_refresh_survives_service_restart(host) -> None:
    """Direct socket access must work without supplementary groups, including after a daemon restart."""

    account = host.user()
    user_home = host.check_output("printf '%s' \"$HOME\"")
    docker_binary = host.check_output("%s/.local/bin/mise which --tool aqua:docker/cli docker", user_home)
    assert account.uid != 0
    assert account.gid != host.group("docker").gid

    for restart in (False, True):
        if restart:
            host.check_output("sudo -n systemctl restart workstation-manager-docker.service")
        acl = host.check_output("getfacl --numeric --omit-header /var/run/docker.sock").splitlines()
        assert f"user:{account.uid}:rw-" in acl
        assert "other::---" in acl
        docker_info = host.run(
            "sudo -n setpriv --reuid %s --regid %s --clear-groups --reset-env -- "
            "%s --host unix:///var/run/docker.sock info",
            str(account.uid),
            str(account.gid),
            docker_binary,
        )
        assert docker_info.succeeded, docker_info.stderr


def test_docker_service_uses_the_mise_runtime_bundle(host) -> None:
    """The system service must use mise's runtime without a second Docker installation."""

    user_home = host.check_output("printf '%s' \"$HOME\"")
    daemon = host.check_output("%s/.local/bin/mise which --tool aqua:docker/cli dockerd", user_home)
    unit = host.file("/etc/systemd/system/workstation-manager-docker.service")
    service_command = host.check_output(
        "systemctl show workstation-manager-docker.service --property=ExecStart --value"
    )
    service_environment = host.check_output(
        "systemctl show workstation-manager-docker.service --property=Environment --value"
    )
    runtime_directory = daemon.rsplit("/", 1)[0]

    assert unit.exists
    assert unit.user == "root"
    assert unit.group == "root"
    assert unit.mode == 0o644
    assert daemon in service_command
    assert f"PATH={runtime_directory}:" in service_environment
    for binary in ("containerd", "containerd-shim-runc-v2", "runc", "docker-init", "docker-proxy"):
        assert host.file(f"{runtime_directory}/{binary}").is_executable
    for package in ("docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin"):
        assert not host.package(package).is_installed
    assert not host.file("/etc/apt/keyrings/docker.asc").exists
    assert not host.file("/etc/apt/sources.list.d/docker.list").exists
    assert not host.file("/etc/apt/sources.list.d/docker.sources").exists


def test_github_cli_does_not_require_a_vendor_repository(host) -> None:
    """The mise-managed GitHub CLI should not require its vendor APT repository."""

    # Arrange
    github_keyring_file = host.file("/usr/share/keyrings/githubcli-archive-keyring.gpg")
    github_source_file = host.file("/etc/apt/sources.list.d/github-cli.list")

    # Act
    # Assert
    assert not github_keyring_file.exists
    assert not github_source_file.exists


def test_declared_editor_package_is_installed(host) -> None:
    """The installed machine should install the declared editor package."""

    # Arrange
    application_command = "flatpak list --system --app --columns=application"

    # Act
    application_result = host.run(application_command)

    # Assert
    assert application_result.succeeded
    assert "com.visualstudio.code" in application_result.stdout.splitlines()


def test_vscode_terminal_command_is_available(host) -> None:
    """The managed Flatpak editor should also expose its command on the host PATH."""

    launcher = host.file("/usr/local/bin/code")

    command_result = host.run("command -v code")
    version_result = host.run("code --version")

    assert launcher.exists
    assert launcher.mode == 0o755
    assert launcher.user == "root"
    assert launcher.group == "root"
    assert command_result.succeeded
    assert command_result.stdout.strip() == launcher.path
    assert version_result.succeeded
    assert version_result.stdout.strip()


def test_vscode_integrated_terminal_uses_host_zsh(host) -> None:
    """The Flatpak editor should select a profile that can run the workstation's Zsh."""

    user_home = host.check_output("printf '%s' \"$HOME\"")
    settings = host.file(f"{user_home}/.var/app/com.visualstudio.code/config/Code/User/settings.json")
    bridge_result = host.run(
        "sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) "
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus "
        "flatpak run --command=/app/bin/host-spawn com.visualstudio.code /usr/bin/zsh --version'"
    )

    assert settings.exists
    assert '"terminal.integrated.defaultProfile.linux": "zsh (host)"' in settings.content_string
    assert '"path": "/app/bin/host-spawn"' in settings.content_string
    ignored_settings = json.loads(settings.content_string)["settingsSync.ignoredSettings"]
    for setting in ("terminal.integrated.profiles.linux", "terminal.integrated.defaultProfile.linux"):
        assert setting in ignored_settings
        assert f"-{setting}" not in ignored_settings
    assert bridge_result.succeeded
    assert "zsh " in bridge_result.stdout


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
