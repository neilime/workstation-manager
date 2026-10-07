"""End-to-end checks for development tooling."""

import json
import tomllib


def test_git_automatic_garbage_collection_is_enabled(host) -> None:
    """Git should use a positive automatic garbage collection threshold after setup."""

    result = host.run("git config --global --int --get gc.auto")

    assert result.succeeded
    assert int(result.stdout.strip()) > 0


def test_selected_mise_tools_are_installed(host, workstation_config) -> None:
    """Global tools resolve from the maintained configuration after activation."""
    for tool in workstation_config["development"]["mise"]["tools"]:
        result = host.run('bash -lc \'"$HOME/.local/bin/mise" where "$1"\' fixture %s', tool)
        assert result.succeeded, result.stderr


def test_starship_launcher_runs_the_configured_release(host, workstation_config) -> None:
    """The prompt executable must be usable through its managed link without mise activation."""
    version = workstation_config["development"]["mise"]["tools"].get("aqua:starship/starship")
    if version is None:
        return
    executable = f"{host.user().home}/.local/bin/starship"
    assert host.file(executable).is_symlink
    assert host.check_output("%s --version", executable).splitlines()[0] == "starship " + version


def test_mise_global_config_and_activation_are_managed(host, workstation_config) -> None:
    """The generated manifest must carry the configured versions and tracks."""
    home = host.user().home
    content = host.file(f"{home}/.config/mise/config.toml").content_string
    configured = tomllib.loads(content)["tools"]
    versions = {tool: entry["version"] if isinstance(entry, dict) else entry for tool, entry in configured.items()}
    assert versions == workstation_config["development"]["mise"]["tools"]
    assert host.file(f"{home}/.config/workstation-manager/mise.sh").exists


def test_php_and_composer_use_the_managed_mise_runtime(host, workstation_config) -> None:
    """The shell selects pinned PHP/Composer and retains the required PHP extensions."""
    php = host.check_output("zsh -ic %s", "php -r 'echo PHP_VERSION;'")
    assert php == workstation_config["development"]["mise"]["tools"]["vfox:jdx/vfox-php"]
    composer = host.check_output("zsh -ic 'composer --version --no-ansi'")
    assert composer.startswith(
        "Composer version " + workstation_config["development"]["mise"]["tools"]["github:composer/composer"] + " "
    )
    composer_home = host.check_output('"$HOME/.local/bin/mise" where github:composer/composer')
    assert host.check_output("zsh -ic 'command -v composer'").startswith(composer_home + "/")
    modules = host.check_output("zsh -ic 'php -m'").splitlines()
    assert {"curl", "dom", "intl", "mbstring", "openssl", "pdo_sqlite", "xml", "zip"}.issubset(modules)
    executable = host.check_output("zsh -ic 'command -v php'")
    assert executable.startswith(host.user().home + "/.local/share/mise/")


def test_docker_engine_is_available_to_the_managed_user(host) -> None:
    """Docker must provide a running daemon, not just working client commands."""

    docker_service = host.service("docker")
    docker_socket = host.file("/var/run/docker.sock")
    docker_info = host.run("docker --host unix:///var/run/docker.sock info")

    assert docker_service.is_running
    assert docker_service.is_enabled
    assert docker_socket.is_socket
    assert docker_socket.group == "docker"
    assert "docker" in host.user().groups
    assert docker_info.succeeded, docker_info.stderr
    for plugin in ("buildx", "compose"):
        assert host.run("docker %s version", plugin).succeeded


def test_native_docker_service_survives_restart(host) -> None:
    """The vendor daemon and socket must remain usable by a fresh managed-user session."""
    host.check_output("sudo -n systemctl restart docker.service")
    assert host.run("docker --host unix:///var/run/docker.sock info").succeeded
    command = host.check_output("systemctl show docker.service --property=ExecStart --value")
    assert "/usr/bin/dockerd" in command
    assert ".local/share/mise" not in command
    for package in ("docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin"):
        assert host.package(package).is_installed
    assert host.file("/etc/apt/keyrings/docker.asc").user == "root"
    assert host.file("/etc/apt/sources.list.d/docker.sources").contains("Signed-By: /etc/apt/keyrings/docker.asc")


def test_native_github_cli_uses_its_vendor_repository(host) -> None:
    """GitHub CLI is available without activating mise or changing user credentials."""
    assert host.package("gh").is_installed
    assert host.check_output("env -i PATH=/usr/local/bin:/usr/bin:/bin sh -c 'command -v gh'") == "/usr/bin/gh"
    assert host.file("/etc/apt/keyrings/githubcli-archive-keyring.gpg").user == "root"
    assert host.file("/etc/apt/sources.list.d/github-cli.sources").contains("https://cli.github.com/packages")


def test_github_extensions_match_configured_pins(host, workstation_config) -> None:
    """Installed release tags and script checkout commits match the managed configuration."""
    installed = {}
    for line in host.check_output("gh extension list").splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0] == "gh":
            installed[fields[2]] = fields[3]
    for repository, revision in workstation_config["development"]["github"]["extensions"].items():
        assert repository in installed
        if len(revision) == 40:
            extension = f"{host.user().home}/.local/share/gh/extensions/{repository.split('/')[1]}"
            assert host.check_output("git -C %s rev-parse HEAD", extension) == revision
        else:
            assert installed[repository] == revision


def test_node_and_bundled_package_commands_work_with_a_clean_environment(host, workstation_config) -> None:
    """Ordinary non-login processes must find the complete system Node distribution."""
    home = host.user().home
    for command in ("node", "npm", "npx"):
        result = host.run("env -i HOME=%s PATH=/usr/local/bin:/usr/bin:/bin %s --version", home, command)
        assert result.succeeded, result.stderr
        assert host.file(f"/usr/local/bin/{command}").is_symlink
    assert host.check_output("node --version") == "v" + workstation_config["development"]["node"]["version"]
    assert host.file("/opt/nodejs/current").user == "root"
    result = host.run("env -i HOME=%s PATH=/usr/local/bin:/usr/bin:/bin npm exec --offline -- node --version", home)
    assert result.succeeded, result.stderr


def test_native_editor_and_terminal_are_available(host, workstation_config) -> None:
    """The vendor command and native Zsh profile expose the workstation tools."""
    if "code" not in workstation_config["development"]["editor_packages"]:
        return
    assert host.package("code").is_installed
    assert host.check_output("command -v code") == "/usr/bin/code"
    assert host.run("code --version").succeeded
    settings = host.file(f"{host.user().home}/.config/Code/User/settings.json")
    assert '"terminal.integrated.defaultProfile.linux": "zsh"' in settings.content_string
    assert '"path": "/usr/bin/zsh"' in settings.content_string
    assert host.run("/usr/bin/zsh -lc 'node --version && npm --version && gh --version'").succeeded


def test_persistent_github_login_is_independent_of_token_overrides(host, workstation_config) -> None:
    """The managed user's keyring login is available in fresh non-interactive processes."""
    home = host.user().home
    hostname = workstation_config["development"]["github"]["host"]
    result = host.run(
        "env -u GH_TOKEN -u GITHUB_TOKEN -u GH_ENTERPRISE_TOKEN -u GITHUB_ENTERPRISE_TOKEN "
        "HOME=%s XDG_CONFIG_HOME=%s GH_CONFIG_DIR=%s gh auth status --active --hostname %s --json hosts",
        home,
        home + "/.config",
        home + "/.config/gh",
        hostname,
    )
    assert result.succeeded, "Stored GitHub authentication could not be checked"
    active = json.loads(result.stdout)["hosts"][hostname][0]
    assert active["state"] == "success"
    assert active["tokenSource"] == "keyring"
    assert active["login"] == workstation_config["development"]["github"]["account"]


def test_standard_agent_clis_match_configured_pins_without_shell_activation(host, workstation_config) -> None:
    """Both baseline CLIs use the system runtime and their reviewed npm releases."""
    home = host.user().home
    for name, package in workstation_config["development"]["npm_packages"].items():
        installed = json.loads(
            host.check_output("/usr/local/bin/npm ls --global --prefix /usr/local --depth=0 --json %s", name)
        )
        assert installed["dependencies"][name]["version"] == package["version"]
        assert host.run(
            "env -i HOME=%s PATH=/usr/local/bin:/usr/bin:/bin %s --version", home, package["command"]
        ).succeeded


def test_development_sysctl_configuration(host, workstation_config) -> None:
    """Configured kernel settings must be persisted and applied."""
    content = host.file("/etc/sysctl.d/99-workstation-manager.conf").content_string
    persisted = dict(line.split("=", 1) for line in content.splitlines() if "=" in line and not line.startswith("#"))
    persisted = {key.strip(): value.strip() for key, value in persisted.items()}
    for name, value in workstation_config["development"]["settings"]["sysctl"].items():
        assert persisted[name] == str(value)
        assert host.check_output("sysctl -n %s", name) == str(value)


def test_git_project_report_command_and_schedule_are_managed(host) -> None:
    """Setup always installs the manual report and daily desktop notifications."""

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
    report_result = host.run(report_command)
    timer_link_result = host.run("test -L %s", timer_link)

    # Assert
    assert helper_script.exists
    assert helper_script.mode == 0o644
    assert timer_link_result.succeeded
    assert autostart_file.exists
    assert host.run("command -v notify-send").succeeded
    assert activator_script.exists
    assert service_unit.exists
    assert timer_unit.contains(r"^OnCalendar=daily$")
    assert timer_unit.contains(r"^Persistent=true$")
    assert report_result.succeeded
    assert "client-restore [main]" in report_result.stdout
    assert "local-note.txt" in report_result.stdout
    assert "tracked.txt" in report_result.stdout
