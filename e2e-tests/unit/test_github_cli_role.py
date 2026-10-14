"""Exercise native GitHub CLI updates without modifying the host's packages."""

import json

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import (
    SETUP_ROLES,
    ansible_environment,
    run_playbook,
    write_local_playbook,
    write_stateful_module,
)

pytestmark = pytest.mark.integration

FIXTURE_OPERATIONS = r"""
if operation == "apt":
    name = args["name"]
    if name not in state["packages"] or args["state"] == "latest":
        state["packages"][name] = "current"
elif operation in ("file", "get_url", "deb822_repository"):
    state[operation] = args
"""


@pytest.fixture(name="github_cli_setup")
def github_cli_setup_fixture(tmp_path):
    """Retain real task conditions while simulating package presence and candidate updates."""
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"packages": {"gh": "older"}}))
    library = tmp_path / "library"
    library.mkdir()
    write_stateful_module(library / "fixture_github_cli.py", FIXTURE_OPERATIONS)
    tasks = DataLoader().load_from_file(str(SETUP_ROLES / "development_tooling/tasks/github_cli.yml"))
    for task in tasks:
        for operation in ("apt", "file", "get_url", "deb822_repository"):
            arguments = task.pop("ansible.builtin." + operation, None)
            if arguments is not None:
                task["fixture_github_cli"] = {
                    "operation": operation,
                    "arguments": arguments,
                    "state_file": str(state_path),
                }
    playbook = write_local_playbook(
        tmp_path / "playbook.json",
        tasks,
        {
            "ansible_facts": {"architecture": "x86_64"},
            "workstation_manager_use_become": False,
            "workstation_manager_resolved": {"system": {"packages": {"cache_valid_time": 3600}}},
        },
    )

    def run(*, check=False):
        command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
        if check:
            command.append("--check")
        result = run_playbook(command, ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library)))
        assert result.returncode == 0, result.stdout + result.stderr
        return result, json.loads(state_path.read_text())

    return run


def test_github_cli_updates_an_installed_package_and_is_idempotent(github_cli_setup):
    """An existing CLI is updated to the repository candidate before authentication and then reused."""
    _, state = github_cli_setup()
    assert state["packages"]["gh"] == "current"
    repeated, after = github_cli_setup()
    assert after == state
    assert "changed=0" in repeated.stdout


def test_github_cli_preview_leaves_installed_packages_unchanged(github_cli_setup):
    """Check mode reports the pending CLI update without changing the package or repository."""
    result, state = github_cli_setup(check=True)
    assert state == {"packages": {"gh": "older"}}
    assert "changed=0" not in result.stdout
