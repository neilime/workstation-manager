"""Exercise managed APT updates with isolated package and repository state."""

from __future__ import annotations

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

FIXTURE_OPERATIONS = r"""
if operation == "apt":
    if args.get("upgrade") or args.get("autoremove"):
        module.fail_json(msg="Setup must limit updates to managed packages")
    if args.get("update_cache") and args.get("cache_valid_time", 0) == 0:
        state["candidates"] = dict(state["available"])
    names = args.get("name", [])
    if isinstance(names, str):
        names = [names]
    for specification in names:
        name, separator, version = specification.partition("=")
        if name == "*":
            module.fail_json(msg="Setup must limit updates to managed packages")
        desired = version if separator else state["candidates"][name]
        installed = state["packages"].get(name)
        if installed == desired or (installed is not None and args["state"] != "latest"):
            continue
        if name in state["held"] and not args.get("allow_change_held_packages", False):
            module.fail_json(msg="Held package requires an explicit decision")
        if name in state["removals"]:
            if args.get("force_apt_get") and args.get("fail_on_autoremove"):
                module.fail_json(msg="Upgrade would remove an installed package")
            state["packages"].pop(state["removals"][name])
        state["packages"][name] = desired
"""


@pytest.fixture(name="apt_playbook")
def apt_playbook_fixture(tmp_path):
    """Retain cache ordering and role conditions without touching host APT state."""
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "packages": {"managed": "1.0", "pinned": "1.0", "personal": "1.0"},
                "candidates": {"managed": "1.0", "missing": "1.0", "pinned": "1.0", "personal": "1.0"},
                "available": {"managed": "2.0", "missing": "2.0", "pinned": "2.0", "personal": "2.0"},
                "held": [],
                "removals": {},
            }
        )
    )
    library = tmp_path / "library"
    library.mkdir()
    write_stateful_module(library / "fixture_apt.py", FIXTURE_OPERATIONS)
    tasks = []
    for role in ("system_base", "apt_packages"):
        for task in DataLoader().load_from_file(str(SETUP_ROLES / role / "tasks/main.yml")):
            arguments = task.pop("ansible.builtin.apt", None)
            if arguments is not None:
                task["fixture_apt"] = {
                    "operation": "apt",
                    "arguments": arguments,
                    "state_file": str(state_file),
                }
                tasks.append(task)
    variables = {
        "workstation_manager_use_become": False,
        "workstation_manager_resolved": {
            "system": {
                "packages": {
                    "prerequisites": [],
                    "apt": ["managed", "missing", "pinned=1.0"],
                    "cache_valid_time": 86400,
                },
            },
        },
    }
    playbook = write_local_playbook(tmp_path / "playbook.json", tasks, variables)
    return (
        ["ansible-playbook", "-i", "localhost,", str(playbook)],
        ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library)),
        state_file,
    )


def test_setup_refreshes_candidates_and_updates_only_managed_packages(apt_playbook) -> None:
    """Fresh metadata drives installs and upgrades even with no prerequisites; exact pins remain effective."""
    command, environment, state_file = apt_playbook

    result = run_playbook(command, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(state_file.read_text())
    assert state["packages"] == {"managed": "2.0", "missing": "2.0", "pinned": "1.0", "personal": "1.0"}
    repeated = run_playbook(command, environment)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    assert json.loads(state_file.read_text()) == state


def test_apt_update_preview_preserves_packages_and_metadata(apt_playbook) -> None:
    """Check mode must leave both installed packages and the APT cache untouched."""
    command, environment, state_file = apt_playbook
    original = state_file.read_text()

    result = run_playbook([*command, "--check"], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert state_file.read_text() == original


@pytest.mark.parametrize(
    ("restriction", "value", "message"),
    [
        ("held", ["managed"], "Held package requires an explicit decision"),
        ("removals", {"managed": "personal"}, "Upgrade would remove an installed package"),
    ],
)
def test_apt_update_conflicts_stop_setup_without_changing_packages(apt_playbook, restriction, value, message) -> None:
    """Package holds and removal conflicts must fail visibly and preserve installed packages."""
    command, environment, state_file = apt_playbook
    state = json.loads(state_file.read_text())
    state[restriction] = value
    state_file.write_text(json.dumps(state))

    result = run_playbook(command, environment)

    assert result.returncode != 0
    assert message in result.stdout + result.stderr
    assert json.loads(state_file.read_text())["packages"] == state["packages"]
