"""Exercise mise-managed Docker orchestration without changing the workstation."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest
from ansible.parsing.dataloader import DataLoader

REPOSITORY_PATH = pathlib.Path(__file__).parents[2]
ROLE_PATH = (
    REPOSITORY_PATH / "ansible/collections/ansible_collections/neilime/workstation_setup/roles/development_tooling"
)
MANAGED_USER = "fixture-managed-user"
FIXTURE_MODULE = """
import json
import os
import shlex
from pathlib import Path
from ansible.module_utils.basic import AnsibleModule

module = AnsibleModule(argument_spec={
    "operation": {"type": "str", "required": True},
    "arguments": {"type": "dict", "required": True},
    "state_file": {"type": "path", "required": True},
    "unit_file": {"type": "path", "required": True},
}, supports_check_mode=True)
path = Path(module.params["state_file"])
state = json.loads(path.read_text())
before = json.dumps(state, sort_keys=True)
operation = module.params["operation"]
args = module.params["arguments"]
if operation == "distribution_facts":
    module.exit_json(changed=False, ansible_facts={"distribution": "Ubuntu"})
elif operation == "apt":
    if sorted(args["name"]) != ["acl", "iptables"] or args["state"] != "present":
        module.fail_json(msg="Only networking and socket permission prerequisites should be installed through APT")
    state["packages"].update({package: True for package in args["name"]})
elif operation == "group":
    assert args == {"name": "docker", "state": "present"}
    state["group_exists"] = True
elif operation == "user":
    groups = state["users"].get(args["name"], [])
    state["users"][args["name"]] = sorted(set(groups + args["groups"] if args["append"] else args["groups"]))
elif operation == "acl":
    if os.environ.get("FIXTURE_ACL_FAILURE"):
        module.fail_json(msg="Cannot grant Docker socket access")
    assert args["path"] == "/var/run/docker.sock"
    assert args["etype"] == "user" and args["state"] == "present"
    state["socket_acls"][args["entity"]] = args["permissions"]
elif operation == "systemd_service":
    if not module.check_mode:
        lines = Path(module.params["unit_file"]).read_text().splitlines()
        binary = json.loads(next(line.removeprefix("ExecStart=") for line in lines if line.startswith("ExecStart=")))
        binary = binary.replace("%%", "%").replace("$$", "$")
        environment = json.loads(next(
            line.removeprefix("Environment=") for line in lines if line.startswith("Environment=")
        )).replace("%%", "%")
        assert Path(binary).is_file()
        assert environment.startswith("PATH=" + str(Path(binary).parent) + ":")
        previous = state["services"].get(args["name"], {})
        starts = previous.get("starts", 0)
        if not previous.get("running") or args["state"] == "restarted":
            starts += 1
            state["socket_acls"] = {}
            for line in lines:
                if not line.startswith("ExecStartPost="):
                    continue
                command = shlex.split(line.removeprefix("ExecStartPost=").replace("%%", "%").replace("$$", "$"))
                assert command[:2] == ["/usr/bin/setfacl", "--modify"]
                assert command[3:] == ["/var/run/docker.sock"]
                etype, entity, permissions = command[2].split(":")
                assert etype == "user"
                state["socket_acls"][entity] = permissions
            state["startup_socket_acls"] = dict(state["socket_acls"])
        if args["state"] == "restarted":
            assert args["daemon_reload"]
        state["services"][args["name"]] = {
            "enabled": args["enabled"], "running": True, "binary": binary, "starts": starts
        }
else:
    module.fail_json(msg="Unexpected operation: " + operation)
changed = before != json.dumps(state, sort_keys=True)
if not module.check_mode:
    path.write_text(json.dumps(state))
module.exit_json(changed=changed)
"""
MISE_SCRIPT = """
import os
from pathlib import Path
import sys

home = Path(os.environ["HOME"])
root = home / ".local/share/mise/installs"
bundle = root / "aqua-docker-cli" / os.environ["FIXTURE_VERSION"] / "docker"
paths = {
    ("aqua:docker/cli", "dockerd"): bundle / "dockerd",
    ("aqua:docker/compose", "docker-cli-plugin-docker-compose"):
        root / "aqua-docker-compose/fixture/docker-cli-plugin-docker-compose",
    ("aqua:docker/buildx", "docker-cli-plugin-docker-buildx"):
        root / "aqua-docker-buildx/fixture/docker-cli-plugin-docker-buildx",
}
if sys.argv[1:] == ["install"]:
    bundle.mkdir(parents=True, exist_ok=True)
    for name in ("dockerd", "containerd", "containerd-shim-runc-v2", "runc", "docker-init", "docker-proxy"):
        if name == os.environ.get("FIXTURE_MISSING_BINARY"):
            continue
        path = bundle / name
        path.write_text("#!/bin/sh\\nexit 0\\n")
        path.chmod(0o755)
    docker = bundle / "docker"
    docker.write_text(Path(os.environ["FIXTURE_CLIENT_SCRIPT"]).read_text())
    docker.chmod(0o755)
    for (_, name), path in paths.items():
        if name == "dockerd":
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\\nprintf '%s\\\\n' " + name + "\\n")
        path.chmod(0o755)
elif len(sys.argv) == 5 and sys.argv[1:3] == ["which", "--tool"]:
    path = paths.get(tuple(sys.argv[3:]))
    if path is None or not path.is_file():
        sys.exit("The requested tool binary is not installed")
    print(path)
else:
    sys.exit("Unexpected mise invocation: " + repr(sys.argv[1:]))
"""
CLIENT_SCRIPT = """
import json
import os
from pathlib import Path
import subprocess
import sys

if sys.argv[1:] == ["--host", "unix:///var/run/docker.sock", "info"]:
    if os.environ.get("FIXTURE_DOCKER_FAILURE"):
        sys.exit("Docker API unavailable")
    state_file = Path(os.environ["FIXTURE_STATE_FILE"])
    state = json.loads(state_file.read_text())
    service = state["services"]["workstation-manager-docker.service"]
    assert service["running"] and service["enabled"]
    assert "docker" in state["users"]["fixture-managed-user"]
    assert state["socket_acls"].get("fixture-managed-user") == "rw", "Existing sessions cannot access the Docker socket"
    assert state["packages"] == {"acl": True, "iptables": True}
    state["verified"] = True
    state_file.write_text(json.dumps(state))
elif len(sys.argv) == 3 and sys.argv[1] in ("compose", "buildx") and sys.argv[2] == "version":
    plugin = Path(os.environ["HOME"]) / ".docker/cli-plugins" / ("docker-" + sys.argv[1])
    subprocess.run([str(plugin), "version"], check=True)
else:
    sys.exit("Unexpected Docker invocation: " + repr(sys.argv[1:]))
"""


@pytest.fixture(name="docker_setup")
def fixture_docker_setup(tmp_path: pathlib.Path):
    """Keep production ordering, lookups, templates, and conditions; isolate privileged mutations."""

    home = tmp_path / "managed home%$"
    home.mkdir()
    initial_state = {
        "packages": {},
        "group_exists": False,
        "users": {MANAGED_USER: ["existing-group"]},
        "services": {},
        "socket_acls": {},
    }
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(initial_state))
    unit_file = tmp_path / "workstation-manager-docker.service"
    library = tmp_path / "library"
    library.mkdir()
    (library / "fixture_docker_state.py").write_text(FIXTURE_MODULE)
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    systemctl = binary_dir / "systemctl"
    systemctl.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "assert sys.argv[1:] == ['list-unit-files', '--no-legend', '--no-pager', 'docker.service', 'docker.socket']\n"
        "result = json.loads(os.environ['FIXTURE_SYSTEMCTL_RESULT'])\n"
        "if result is not None:\n"
        "    rc, stdout, stderr = result\n"
        "    sys.stdout.write(stdout)\n"
        "    sys.stderr.write(stderr)\n"
        "    sys.exit(rc)\n"
        "state = json.loads(pathlib.Path(os.environ['FIXTURE_STATE_FILE']).read_text())\n"
        "services = [name for name in ('docker.service', 'docker.socket') if name in state['services']]\n"
        "for name in services:\n"
        "    print(name + ' enabled enabled')\n"
        "sys.exit(0 if services else 1)\n"
    )
    systemctl.chmod(0o755)
    mise = home / ".local/bin/mise"
    mise.parent.mkdir(parents=True)
    mise.write_text(f"#!{sys.executable}\n" + MISE_SCRIPT)
    mise.chmod(0o755)
    client_script = tmp_path / "docker-client.py"
    client_script.write_text(f"#!{sys.executable}\n" + CLIENT_SCRIPT)

    def isolate_task(task):
        """Replace privileged operations while retaining real binary and template handling."""

        for child in task.get("block", []):
            isolate_task(child)
        for module in (
            "ansible.builtin.apt",
            "ansible.builtin.group",
            "ansible.builtin.user",
            "ansible.builtin.systemd_service",
            "ansible.posix.acl",
        ):
            arguments = task.pop(module, None)
            if arguments is not None:
                task["fixture_docker_state"] = {
                    "operation": module.rsplit(".", 1)[1],
                    "arguments": arguments,
                    "state_file": str(state_file),
                    "unit_file": str(unit_file),
                }
        if "ansible.builtin.stat" in task:
            args = task["ansible.builtin.stat"]
            if args["path"] == "/etc/systemd/system/workstation-manager-docker.service":
                args["path"] = str(unit_file)
        for operation in ("template", "file"):
            if f"ansible.builtin.{operation}" in task:
                args = task[f"ansible.builtin.{operation}"]
                if operation == "template":
                    args["src"] = str(ROLE_PATH / "templates" / args["src"])
                    args["dest"] = str(unit_file)
                if "owner" in args:
                    args["owner"] = str(os.getuid())
                    args["group"] = str(os.getgid())

    docker_tasks = DataLoader().load_from_file(str(ROLE_PATH / "tasks/docker.yml"))
    for task in docker_tasks:
        isolate_task(task)
    task_file = tmp_path / "docker.json"
    task_file.write_text(json.dumps(docker_tasks))
    selected_tasks = {
        "Validate declared Docker CLI plugins",
        "Install globally configured mise tools",
        "Ensure Docker CLI plugin directory exists",
        "Resolve declared Docker CLI plugin binaries through mise",
        "Link Docker CLI plugins from mise-managed binaries",
        "Report Docker CLI plugins deferred until mise tools are installed",
        "Configure and start the mise-managed Docker daemon",
    }
    tasks = [
        task
        for task in DataLoader().load_from_file(str(ROLE_PATH / "tasks/main.yml"))
        if task["name"] in selected_tasks
    ]
    for task in tasks:
        if task.get("ansible.builtin.import_tasks") == "docker.yml":
            task["ansible.builtin.import_tasks"] = str(task_file)
        isolate_task(task)
    config_file = tmp_path / "ansible.cfg"
    config_file.write_text("[defaults]\ninject_facts_as_vars = False\n")
    development_defaults = DataLoader().load_from_file(str(REPOSITORY_PATH / "ansible/group_vars/all.yml"))[
        "workstation_manager"
    ]["development"]

    def run(
        *,
        install_tools_only=False,
        check=False,
        version="29.0.0",
        mise_exists=True,
        service=None,
        missing="",
        fail=False,
        fail_acl=False,
        systemctl_result: tuple[int, str, str] | None = None,
    ):
        """Run the production tasks using public Docker/plugin defaults and an isolated runtime."""

        state = json.loads(state_file.read_text())
        if service:
            state["services"][service] = {"enabled": True, "running": True}
            state_file.write_text(json.dumps(state))
        mise_config = development_defaults["mise"]
        playbook = tmp_path / "playbook.json"
        playbook.write_text(
            json.dumps(
                [
                    {
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "vars": {
                            "ansible_python_interpreter": sys.executable,
                            "workstation_manager_use_become": False,
                            "workstation_manager_development_mise_binary": {"stat": {"exists": mise_exists}},
                            "workstation_manager_resolved": {
                                "user": {"name": MANAGED_USER, "home": str(home)},
                                "system": {"packages": {"cache_valid_time": 86400}},
                                "development": {"mise": mise_config},
                            },
                        },
                        "pre_tasks": [
                            {
                                "name": "Provide fixture Ubuntu facts",
                                "fixture_docker_state": {
                                    "operation": "distribution_facts",
                                    "arguments": {},
                                    "state_file": str(state_file),
                                    "unit_file": str(unit_file),
                                },
                            }
                        ],
                        "tasks": (
                            [task for task in tasks if task["name"] == "Install globally configured mise tools"]
                            if install_tools_only
                            else tasks
                        ),
                    }
                ]
            )
        )
        command = ["ansible-playbook", "--inventory", "localhost,", str(playbook)]
        if check:
            command.append("--check")
        result = subprocess.run(
            command,
            cwd=tmp_path,
            env={
                **os.environ,
                "PATH": os.pathsep.join((str(binary_dir), os.environ["PATH"])),
                "HOME": str(home),
                "LC_ALL": "C.UTF-8",
                "ANSIBLE_CONFIG": str(config_file),
                "ANSIBLE_HOME": str(tmp_path / ".ansible"),
                "ANSIBLE_LIBRARY": str(library),
                "WORKSTATION_MANAGER_GITHUB_TOKEN": "",
                "FIXTURE_STATE_FILE": str(state_file),
                "FIXTURE_CLIENT_SCRIPT": str(client_script),
                "FIXTURE_VERSION": version,
                "FIXTURE_MISSING_BINARY": missing,
                "FIXTURE_DOCKER_FAILURE": "1" if fail else "",
                "FIXTURE_ACL_FAILURE": "1" if fail_acl else "",
                "FIXTURE_SYSTEMCTL_RESULT": json.dumps(systemctl_result),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        return result, json.loads(state_file.read_text())

    return run, initial_state, home, unit_file


@pytest.mark.parametrize("empty_probe_rc", [0, 1])
def test_docker_setup_uses_mise_and_preserves_existing_groups(docker_setup, empty_probe_rc: int) -> None:
    """Setup must always configure a working daemon and plugins without needing a Docker option."""

    run, _, home, unit_file = docker_setup
    result, state = run(systemctl_result=(empty_probe_rc, "", ""))
    assert result.returncode == 0, result.stdout + result.stderr
    assert state["verified"]
    assert state["packages"] == {"acl": True, "iptables": True}
    assert state["users"][MANAGED_USER] == ["docker", "existing-group"]
    assert state["socket_acls"] == {MANAGED_USER: "rw"}
    assert state["startup_socket_acls"] == {MANAGED_USER: "rw"}
    assert unit_file.stat().st_mode & 0o777 == 0o644
    binary = state["services"]["workstation-manager-docker.service"]["binary"]
    assert binary.startswith(str(home / ".local/share/mise/installs/aqua-docker-cli"))
    for plugin in ("compose", "buildx"):
        result = subprocess.run(
            [str(pathlib.Path(binary).with_name("docker")), plugin, "version"],
            env={**os.environ, "HOME": str(home)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    result, state = run(systemctl_result=(empty_probe_rc, "", ""))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=0 " in result.stdout
    assert state["services"]["workstation-manager-docker.service"]["starts"] == 1


def test_docker_version_change_refreshes_and_restarts_the_service(docker_setup) -> None:
    """A changed mise selection must replace the running daemon path exactly once."""

    run, _, _, _ = docker_setup
    result, _ = run()
    assert result.returncode == 0, result.stdout + result.stderr
    result, state = run(version="29.1.0")
    assert result.returncode == 0, result.stdout + result.stderr
    service = state["services"]["workstation-manager-docker.service"]
    assert "/29.1.0/docker/dockerd" in service["binary"]
    assert service["starts"] == 2
    assert state["startup_socket_acls"] == {MANAGED_USER: "rw"}
    result, state = run(version="29.1.0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=0 " in result.stdout
    assert state["services"]["workstation-manager-docker.service"]["starts"] == 2


@pytest.mark.parametrize("mise_exists", [False, True])
def test_fresh_docker_dry_run_defers_missing_binaries(docker_setup, mise_exists: bool) -> None:
    """Previewing a fresh workstation must not install tools, configure a service, or probe Docker."""

    run, initial_state, home, unit_file = docker_setup
    result, state = run(check=True, mise_exists=mise_exists)
    assert result.returncode == 0, result.stdout + result.stderr
    assert state == initial_state
    assert not unit_file.exists()
    assert not (home / ".local/share/mise/installs").exists()
    assert "configuration and verification are deferred" in result.stdout


def test_existing_docker_dry_run_does_not_mutate_or_probe_the_daemon(docker_setup) -> None:
    """A version-change preview must leave the real unit and service state intact."""

    run, _, _, unit_file = docker_setup
    result, _ = run()
    assert result.returncode == 0, result.stdout + result.stderr
    previous_unit = unit_file.read_bytes()
    result, previous_state = run(version="29.1.0", install_tools_only=True)
    assert result.returncode == 0, result.stdout + result.stderr
    result, state = run(check=True, version="29.1.0", fail=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert state == previous_state
    assert unit_file.read_bytes() == previous_unit


def test_dry_run_with_installed_tools_defers_creating_the_service(docker_setup) -> None:
    """Installed mise tools must allow a fresh service preview without requiring a real group or unit."""

    run, initial_state, _, unit_file = docker_setup
    result, state = run(install_tools_only=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert state == initial_state
    result, state = run(check=True, fail=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert state == initial_state
    assert not unit_file.exists()


@pytest.mark.parametrize("service", ["docker.service", "docker.socket"])
def test_conflicting_docker_services_fail_before_daemon_configuration(docker_setup, service: str) -> None:
    """An existing Docker service/socket must not be replaced or allowed to compete for the socket."""

    run, initial_state, _, unit_file = docker_setup
    result, state = run(service=service)
    assert result.returncode != 0
    assert "Another Docker installation provides" in result.stdout
    assert state == {**initial_state, "services": {service: {"enabled": True, "running": True}}}
    assert not unit_file.exists()


@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize(
    "systemctl_result",
    [
        (1, "", "Failed to list unit files: Access denied\n"),
        (2, "", ""),
        (1, "docker.service enabled enabled\n", ""),
    ],
    ids=["diagnostic", "unexpected-exit-status", "partial-output"],
)
def test_docker_service_probe_errors_fail_before_daemon_configuration(
    docker_setup, check: bool, systemctl_result: tuple[int, str, str]
) -> None:
    """Only an empty no-match result may be accepted as the absence of Docker units."""

    run, initial_state, _, unit_file = docker_setup
    result, state = run(check=check, systemctl_result=systemctl_result)
    assert result.returncode != 0
    assert "Inspect existing Docker services" in result.stdout
    assert "Resolve the mise-managed Docker daemon binary" not in result.stdout
    assert systemctl_result[2].strip() in result.stdout + result.stderr
    assert state == initial_state
    assert not unit_file.exists()


def test_incomplete_docker_bundle_fails_before_daemon_configuration(docker_setup) -> None:
    """A runtime missing runc cannot be reported as successfully configured."""

    run, initial_state, _, unit_file = docker_setup
    result, state = run(missing="runc")
    assert result.returncode != 0
    assert "Docker runtime binary runc is missing or not executable" in result.stdout
    assert state == initial_state
    assert not unit_file.exists()


def test_missing_docker_daemon_reports_an_actionable_lookup_failure(docker_setup) -> None:
    """A missing dockerd must fail with instructions instead of skipping daemon setup."""

    run, initial_state, _, unit_file = docker_setup
    result, state = run(missing="dockerd")
    assert result.returncode != 0
    assert "Cannot resolve dockerd from aqua:docker/cli" in result.stdout
    assert "Check the mise installation and rerun setup" in result.stdout
    assert state == initial_state
    assert not unit_file.exists()


def test_docker_api_failure_is_not_reported_as_success(docker_setup) -> None:
    """Successful service operations must not hide a failed managed-user API probe."""

    run, _, _, _ = docker_setup
    result, state = run(fail=True)
    assert result.returncode != 0
    assert "Docker API unavailable" in result.stdout + result.stderr
    assert "verified" not in state


def test_setup_repairs_socket_permissions_without_restarting_docker(docker_setup) -> None:
    """A rerun must restore direct user access even when the existing service unit is unchanged."""

    run, _, _, unit_file = docker_setup
    result, state = run()
    assert result.returncode == 0, result.stdout + result.stderr
    state["socket_acls"] = {}
    unit_file.with_name("state.json").write_text(json.dumps(state))

    result, state = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert state["socket_acls"] == {MANAGED_USER: "rw"}
    assert state["services"]["workstation-manager-docker.service"]["starts"] == 1
    assert "changed=1 " in result.stdout


def test_socket_permission_failure_is_not_reported_as_success(docker_setup) -> None:
    """Setup must fail if it cannot ensure access for the managed user's existing sessions."""

    run, _, _, _ = docker_setup
    result, state = run(fail_acl=True)
    assert result.returncode != 0
    assert "Cannot grant Docker socket access" in result.stdout + result.stderr
    assert "verified" not in state
