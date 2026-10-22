"""Exercise Flatpak download retries through isolated Ansible tasks."""

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

FIXTURE_OPERATIONS = r"""
if operation in ("flatpak_remote", "flatpak"):
    if args["state"] != "present" or args["method"] != "system":
        module.fail_json(msg="Expected system-wide installation")
    if operation == "flatpak" and args["remote"] not in state["remotes"]:
        module.fail_json(msg="Remote must exist before installing applications")
    if not module.check_mode and state["failures"][operation] > 0:
        state["failures"][operation] -= 1
        if operation == "flatpak":
            # A failed transaction can leave some applications installed.
            state["applications"] = sorted(set(state["applications"]) | {args["name"][0]})
        path.write_text(json.dumps(state))
        module.fail_json(msg="Synthetic download failure: SSL connect error")
    if operation == "flatpak_remote":
        state["remotes"] = sorted(set(state["remotes"]) | {args["name"]})
    else:
        state["applications"] = sorted(set(state["applications"]) | set(args["name"]))
"""


@pytest.fixture(name="flatpak_playbook")
def flatpak_playbook_fixture(tmp_path):
    """Keep role retries and conditions while isolating external downloads."""
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "failures": {"flatpak_remote": 0, "flatpak": 0},
                "remotes": [],
                "applications": ["org.example.Personal"],
            }
        )
    )
    library = tmp_path / "library"
    library.mkdir()
    write_stateful_module(library / "fixture_flatpak.py", FIXTURE_OPERATIONS)
    tasks = []
    for task in DataLoader().load_from_file(str(SETUP_ROLES / "flatpak_apps/tasks/main.yml")):
        for operation in ("flatpak_remote", "flatpak"):
            module = "community.general." + operation
            if module in task:
                task["fixture_flatpak"] = {
                    "operation": operation,
                    "arguments": task.pop(module),
                    "state_file": str(state_file),
                }
                task["delay"] = 0
                tasks.append(task)
    playbook = write_local_playbook(
        tmp_path / "playbook.json",
        tasks,
        desktop_variables(
            tmp_path / "home",
            desktop={"flatpak": {"remote": "fixture", "packages": ["org.example.First", "org.example.Second"]}},
        ),
    )
    return (
        ["ansible-playbook", "-i", "localhost,", str(playbook)],
        ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library)),
        state_file,
    )


def test_flatpak_downloads_recover_and_converge(flatpak_playbook) -> None:
    """Retry remote and partial application failures, preserving installed applications."""
    command, environment, state_file = flatpak_playbook
    original = json.loads(state_file.read_text())
    original["failures"] = {"flatpak_remote": 1, "flatpak": 2}
    state_file.write_text(json.dumps(original))

    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(state_file.read_text())
    assert state == {
        "failures": {"flatpak_remote": 0, "flatpak": 0},
        "remotes": ["fixture"],
        "applications": ["org.example.First", "org.example.Personal", "org.example.Second"],
    }
    repeated = run_playbook(command, environment)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    assert json.loads(state_file.read_text()) == state


@pytest.mark.parametrize("operation", ["flatpak_remote", "flatpak"])
def test_flatpak_persistent_download_failure_stops_setup(flatpak_playbook, operation) -> None:
    """Exhausted download retries still fail instead of reporting incomplete setup as successful."""
    command, environment, state_file = flatpak_playbook
    state = json.loads(state_file.read_text())
    state["failures"][operation] = 100
    state_file.write_text(json.dumps(state))

    result = run_playbook(command, environment)
    assert result.returncode != 0
    assert "Synthetic download failure: SSL connect error" in result.stdout + result.stderr
    remaining = json.loads(state_file.read_text())
    assert 1 < 100 - remaining["failures"][operation] <= 5
    assert "org.example.Second" not in remaining["applications"]


def test_flatpak_preview_preserves_installed_state(flatpak_playbook) -> None:
    """Check mode previews applications without writing state or consuming download attempts."""
    command, environment, state_file = flatpak_playbook
    state = json.loads(state_file.read_text())
    state["remotes"] = ["fixture"]
    state["failures"]["flatpak"] = 2
    state_file.write_text(json.dumps(state))

    result = run_playbook([*command, "--check"], environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(state_file.read_text()) == state
