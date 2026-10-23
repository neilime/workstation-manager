"""Exercise native Docker installation with isolated Ansible operations."""

from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import (
    ansible_environment,
    run_playbook,
    write_local_playbook,
    write_stateful_module,
)

ROLE_PATH = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup/roles/development_tooling"
)
FIXTURE_OPERATIONS = r"""
if operation == "apt":
    packages = args["name"] if isinstance(args["name"], list) else [args["name"]]
    state["packages"] = sorted(set(state["packages"] + packages))
elif operation == "deb822_repository":
    state["repository"] = args
elif operation == "get_url":
    state["keyring"] = args
elif operation == "command":
    assert args["argv"] == ["/usr/sbin/runuser", "--user", "fixture", "--",
                            "/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "info"]
    assert state["services"]["docker.service"]["state"] == "started"
    assert "docker" in state["groups"]
    result.update(rc=0, stdout="Docker ready", stderr="")
elif operation == "systemd_service":
    state["services"][args["name"]] = args
elif operation == "user":
    assert args["append"] is True
    state["groups"] = sorted(set(state["groups"] + args["groups"]))
"""


@pytest.fixture(name="docker_setup")
def make_docker_setup(tmp_path: pathlib.Path):
    """Keep real role conditions and assertions while replacing privileged adapters."""
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "packages": [],
                "services": {},
                "groups": ["existing-group"],
            }
        )
    )
    library = tmp_path / "library"
    library.mkdir()
    write_stateful_module(library / "fixture_docker_state.py", FIXTURE_OPERATIONS)
    tasks = DataLoader().load_from_file(str(ROLE_PATH / "tasks/docker.yml"))

    def isolate(task):
        task.pop("become", None)
        task.pop("become_user", None)
        if "ansible.builtin.copy" in task:
            arguments = task["ansible.builtin.copy"]
            arguments["src"] = str(ROLE_PATH / "files" / arguments["src"])
            arguments["dest"] = str(tmp_path / "docker-compose")
            arguments["owner"] = str(os.getuid())
            arguments["group"] = str(os.getgid())
        for operation in (
            "apt",
            "deb822_repository",
            "get_url",
            "command",
            "systemd_service",
            "user",
        ):
            arguments = task.pop("ansible.builtin." + operation, None)
            if arguments is not None:
                task["fixture_docker_state"] = {
                    "operation": operation,
                    "arguments": arguments,
                    "state_file": str(state_path),
                }

    for task in tasks:
        isolate(task)
    playbook = write_local_playbook(
        tmp_path / "playbook.json",
        tasks,
        {
            "ansible_facts": {"distribution_release": "resolute"},
            "workstation_manager_native_arch": "amd64",
            "workstation_manager_resolved": {"user": {"name": "fixture", "home": str(tmp_path)}},
        },
    )

    def run(*, check=False):
        arguments = ["ansible-playbook", "-i", "localhost,", str(playbook)]
        if check:
            arguments.append("--check")
        environment = ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library))
        result = run_playbook(arguments, environment)
        return result, json.loads(state_path.read_text())

    return run


def test_native_installation_preserves_groups_and_uses_current_suite(docker_setup) -> None:
    """The vendor service is usable with the complete package set and account membership."""
    result, state = docker_setup()
    assert result.returncode == 0, result.stdout + result.stderr
    assert state["packages"] == sorted(
        ["docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin"]
    )
    assert state["repository"]["suites"] == "resolute"
    assert state["repository"]["signed_by"] == "/etc/apt/keyrings/docker.asc"
    assert state["services"]["docker.service"]["state"] == "started"
    assert state["groups"] == ["docker", "existing-group"]
    repeated, after = docker_setup()
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert after == state
    assert "changed=0" in repeated.stdout


def test_compose_alias_forwards_arguments_streams_and_exit_status(docker_setup, tmp_path: pathlib.Path) -> None:
    """The installed executable delegates unchanged arguments and streams to Docker Compose."""
    setup, _state = docker_setup()
    assert setup.returncode == 0, setup.stdout + setup.stderr
    launcher = tmp_path / "docker-compose"
    assert stat.S_IMODE(launcher.stat().st_mode) == 0o755

    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    docker = binary_directory / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "print(json.dumps({'args': sys.argv[1:], 'stdin': sys.stdin.read()}))\n"
        "sys.stderr.write('compose diagnostic\\n')\n"
        "sys.exit(23)\n"
    )
    docker.chmod(0o755)
    arguments = ["-f", "compose file.yml", "config", "--", "", "$HOME", "; exit 99", "*"]
    result = subprocess.run(
        [str(launcher), *arguments],
        env={"PATH": str(binary_directory)},
        input="compose input\n",
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert json.loads(result.stdout) == {"args": ["compose", *arguments], "stdin": "compose input\n"}
    assert result.stderr == "compose diagnostic\n"
    assert result.returncode == 23


def test_preview_does_not_mutate_services_groups_or_compose_alias(docker_setup, tmp_path: pathlib.Path) -> None:
    """Check mode must preserve the fixture state and leave the executable absent."""
    result, state = docker_setup(check=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not state["services"]
    assert state["groups"] == ["existing-group"]
    assert not (tmp_path / "docker-compose").exists()
