"""Exercise fixed desktop behavior through isolated Ansible tasks."""

from __future__ import annotations

import json
from typing import Any

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

FIXTURE_OPERATIONS = r"""
if operation == "apt":
    names = args["name"] if isinstance(args["name"], list) else [args["name"]]
    packages = set(state["packages"])
    packages = packages - set(names) if args["state"] == "absent" else packages | set(names)
    state["packages"] = sorted(packages)
elif operation == "stat":
    exists = args["path"].endswith(".gschema.xml") and "gnome-software" in state["packages"]
    result["stat"] = {"exists": exists, "isreg": exists}
elif operation == "dconf":
    state["dconf"][args["key"]] = args["value"]
elif operation == "flatpak":
    if args.get("delete_data"):
        module.fail_json(msg="Application removal must preserve user data")
    state["flatpaks"][args["method"]] = [app for app in state["flatpaks"][args["method"]] if app != args["name"]]

"""


def isolated_tasks(state_file):
    """Keep role expressions while replacing adapters that mutate host state."""
    loader = DataLoader()
    tasks = [
        task
        for task in loader.load_from_file(str(SETUP_ROLES / "flatpak_apps/tasks/main.yml"))
        if "ansible.builtin.apt" in task
    ]
    tasks.extend(loader.load_from_file(str(SETUP_ROLES / "flatpak_apps/tasks/updates.yml")))
    tasks.extend(loader.load_from_file(str(SETUP_ROLES / "flatpak_apps/tasks/scanner.yml")))
    tasks.extend(
        task
        for task in loader.load_from_file(str(SETUP_ROLES / "gnome_preferences/tasks/main.yml"))
        if "community.general.dconf" in task or task.get("register") == "workstation_manager_gnome_wallpaper"
    )
    for task in tasks:
        for action in ("apt", "stat", "dconf", "flatpak"):
            module = ("community.general." if action in ("dconf", "flatpak") else "ansible.builtin.") + action
            if module in task:
                task["fixture_desktop_state"] = {
                    "operation": action,
                    "arguments": task.pop(module),
                    "state_file": str(state_file),
                }
    return tasks


def test_fixed_desktop_settings_preserve_personal_state(tmp_path) -> None:
    """Actual role conditions apply fixed values, preserve optional state, and converge once."""
    state_file = tmp_path / "state.json"
    original: dict[str, Any] = {
        "packages": [],
        "flatpaks": {"system": ["org.gnome.SimpleScan", "example.Other"], "user": ["org.gnome.SimpleScan"]},
        "scanner_data": "synthetic preserved preferences",
        "dconf": {
            "/org/gnome/desktop/interface/color-scheme": "'default'",
            "/org/gnome/shell/extensions/dash-to-dock/show-trash": "false",
            "/org/gnome/software/download-updates": "false",
            "/org/gnome/shell/favorite-apps": "['personal.desktop']",
            "/org/gnome/desktop/background/picture-uri": "'file:///personal.jpg'",
        },
    }
    state_file.write_text(json.dumps(original))
    library = tmp_path / "library"
    library.mkdir()
    write_stateful_module(library / "fixture_desktop_state.py", FIXTURE_OPERATIONS)
    tasks = isolated_tasks(state_file)
    home = tmp_path / "home"
    playbook = write_local_playbook(
        tmp_path / "playbook.json",
        tasks,
        desktop_variables(
            home,
            system={"packages": {"cache_valid_time": 0}},
            desktop={"gnome": {"favorites": None}},
        ),
    )
    environment = ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library))
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    preview = run_playbook([*command, "--check"], environment)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert json.loads(state_file.read_text()) == original
    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(state_file.read_text())
    assert state["dconf"] == {
        **original["dconf"],
        "/org/gnome/desktop/interface/color-scheme": "'prefer-dark'",
        "/org/gnome/shell/extensions/dash-to-dock/show-trash": "true",
        "/org/gnome/software/download-updates": "true",
    }
    assert {"gnome-software", "gnome-software-plugin-flatpak"}.issubset(state["packages"])
    assert {"simple-scan", "sane-utils"}.issubset(state["packages"])
    assert state["flatpaks"] == {"system": ["example.Other"], "user": []}
    assert state["scanner_data"] == original["scanner_data"]
    repeated = run_playbook(command, environment)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    assert json.loads(state_file.read_text()) == state
