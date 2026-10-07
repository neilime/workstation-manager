"""Exercise native Docker installation with isolated Ansible operations."""

from __future__ import annotations

import json
import pathlib

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import (
    ansible_environment,
    run_playbook,
    write_local_playbook,
    write_stateful_module,
)

pytestmark = pytest.mark.integration

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


def test_preview_does_not_start_services_or_change_group_membership(docker_setup) -> None:
    """Check mode must not mutate the privileged fixture state."""
    result, state = docker_setup(check=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not state["services"]
    assert state["groups"] == ["existing-group"]
