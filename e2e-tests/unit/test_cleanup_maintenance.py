"""Exercise maintenance policies through real Ansible with isolated command adapters."""

from __future__ import annotations

import json

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import (
    SETUP_ROLES,
    ansible_environment,
    desktop_variables,
    run_playbook,
    write_local_playbook,
    write_stateful_module,
)

pytestmark = pytest.mark.integration

OPERATIONS = r"""
if operation == "command":
    argv = args["argv"]
    if state.get("fail_docker") and argv[0] == "docker":
        module.fail_json(msg="synthetic Docker failure")
    output = "Inst fixture-package (1 fixture)"
    result.update(rc=0, stdout=output, stdout_lines=[output], stderr="")
    if argv[0] == "docker":
        state["commands"].append(argv)
        result["stdout"] = "Total reclaimed space: 0B"
    elif argv[0] == "journalctl":
        state["commands"].append(argv)
        result["stdout"] = ""
    elif argv != ["apt-get", "--simulate", "dist-upgrade"]:
        module.fail_json(msg="Unexpected mutating command")
elif operation == "apt":
    if args != {"autoclean": True}:
        module.fail_json(msg="Only obsolete package download cleanup is authorized")
    state["apt"].append(args)
elif operation == "stat":
    result["stat"] = {"exists": True}
"""


def run_policy(tmp_path, *, preview=False, fail_docker=False, docker_available=True):
    """Preserve role conditions and arguments while redirecting OS mutations."""
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"commands": [], "apt": [], "fail_docker": fail_docker}))
    library = tmp_path / "library"
    library.mkdir(exist_ok=True)
    write_stateful_module(library / "fixture_maintenance.py", OPERATIONS)
    path = SETUP_ROLES.parents[1] / "workstation_cleanup/roles/cleanup/tasks/maintenance.yml"
    tasks = DataLoader().load_from_file(str(path))
    for task in tasks:
        for action in ("command", "apt", "stat"):
            key = "ansible.builtin." + action
            if key in task:
                task["fixture_maintenance"] = {
                    "operation": action,
                    "arguments": task.pop(key),
                    "state_file": str(state),
                }
    variables = desktop_variables(tmp_path / "home")
    variables["workstation_manager_cleanup_docker_command"] = {"rc": 0 if docker_available else 1}
    playbook = write_local_playbook(tmp_path / "playbook.json", tasks, variables)
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    if preview:
        command.append("--check")
    result = run_playbook(command, ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library)))
    return result, json.loads(state.read_text())


def test_routine_maintenance_preserves_volumes_and_running_work(tmp_path):
    """Only old dangling images, bounded build cache, and archived logs are reclaimed."""
    result, state = run_policy(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert state["commands"] == [
        ["docker", "image", "prune", "--force", "--filter", "until=168h"],
        ["docker", "builder", "prune", "--force", "--filter", "until=168h", "--keep-storage", "10GB"],
        ["journalctl", "--vacuum-time=14days", "--vacuum-size=1024M"],
    ]
    assert state["apt"] == [{"autoclean": True}]
    assert "Inst fixture-package" in result.stdout
    assert "Reboot required: True" in result.stdout


def test_maintenance_without_docker_still_cleans_downloads_and_logs(tmp_path):
    """Docker availability gates only Docker operations."""
    result, state = run_policy(tmp_path, docker_available=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert state["commands"] == [["journalctl", "--vacuum-time=14days", "--vacuum-size=1024M"]]
    assert state["apt"] == [{"autoclean": True}]


def test_cleanup_preview_does_not_mutate(tmp_path):
    """A dry run still plans APT updates but cannot reclaim or remove anything."""
    result, state = run_policy(tmp_path, preview=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert state["commands"] == []
    assert state["apt"] == []
    assert "Inst fixture-package" in result.stdout


def test_failed_maintenance_is_not_reported_as_success(tmp_path):
    """Unexpected daemon errors must stop cleanup instead of being swallowed."""
    result, _state = run_policy(tmp_path, fail_docker=True)
    assert result.returncode != 0
    assert "synthetic Docker failure" in result.stdout
