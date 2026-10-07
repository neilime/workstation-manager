"""Verify mandatory weekly BleachBit scheduling with preserved personal presets."""

from __future__ import annotations

import configparser
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


def test_weekly_bleachbit_preserves_preferences_and_converges(tmp_path):
    """Setup enables weekly runs without a configuration flag and keeps the manual command."""
    home = tmp_path / "home"
    preferences = home / ".config/bleachbit/bleachbit.ini"
    preferences.parent.mkdir(parents=True)
    preferences.write_text("[tree]\nfixture.cleaner=true\n")
    timer = home / ".config/systemd/user/workstation-manager-bleachbit-clean.timer"
    variables = desktop_variables(home)
    playbook = write_local_playbook(
        tmp_path / "playbook.json",
        [
            {"ansible.builtin.include_role": {"name": "neilime.workstation_setup.bleachbit"}},
        ],
        variables,
    )
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    environment = ansible_environment(tmp_path)
    preview = run_playbook([*command, "--check"], environment)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert not timer.exists()
    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    schedule = configparser.ConfigParser()
    schedule.read(timer)
    assert schedule["Timer"]["OnCalendar"] == "weekly"
    assert schedule["Timer"]["Persistent"] == "true"
    assert schedule["Timer"]["RandomizedDelaySec"] == "30m"
    link = timer.parent / "timers.target.wants" / timer.name
    assert link.is_symlink()
    assert link.resolve() == timer
    service = timer.with_suffix(".service")
    assert "ExecStart=%h/.local/bin/workstation-manager-bleachbit-clean" in service.read_text()
    autostart = home / ".config/autostart/workstation-manager-bleachbit-clean.desktop"
    assert f"Exec={home}/.local/bin/workstation-manager-bleachbit-clean-activate-timer" in autostart.read_text()
    assert preferences.read_text() == "[tree]\nfixture.cleaner=true\n"
    assert (home / ".local/bin/workstation-manager-bleachbit-clean").is_file()
    repeated = run_playbook(command, environment)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout


SESSION_OPERATIONS = r"""
if operation == "command":
    if args["argv"][:2] != ["id", "-u"]:
        module.fail_json(msg="Unexpected session command")
    result.update(rc=0, stdout="15123")
elif operation == "stat":
    if args["path"] != "/run/user/15123/bus":
        module.fail_json(msg="Wrong target user bus")
    result["stat"] = {"exists": True}
elif operation == "systemd_service":
    import os
    if (
        args["name"] != "workstation-manager-bleachbit-clean.timer"
        or args["scope"] != "user"
        or args["state"] != "started"
    ):
        module.fail_json(msg="Unexpected timer activation")
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS") != "unix:path=/run/user/15123/bus":
        module.fail_json(msg="Wrong activation bus")
    if state["fail_activation"]:
        module.fail_json(msg="synthetic timer activation failure")
    state["timer_started"] = True
"""


def session_tasks(role, state_file):
    """Exercise real scheduling assets while isolating the user session boundary."""
    tasks = DataLoader().load_from_file(str(role / "tasks/schedule.yml"))
    for task in tasks:
        for name, directory in (("copy", "files"), ("template", "templates")):
            if (arguments := task.get("ansible.builtin." + name)) is not None:
                arguments["src"] = str(role / directory / arguments["src"])
        for name in ("command", "stat", "systemd_service"):
            if "ansible.builtin." + name in task:
                task["fixture_session"] = {
                    "operation": name,
                    "arguments": task.pop("ansible.builtin." + name),
                    "state_file": str(state_file),
                }
    return tasks


@pytest.mark.parametrize("fail_activation", [False, True])
def test_weekly_bleachbit_activates_in_the_managed_session(tmp_path, fail_activation):
    """An active bus starts the timer; activation errors must fail setup."""
    role = SETUP_ROLES / "bleachbit"
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"timer_started": False, "fail_activation": fail_activation}))
    library = tmp_path / "library"
    library.mkdir()
    write_stateful_module(library / "fixture_session.py", SESSION_OPERATIONS)
    tasks = session_tasks(role, state_file)
    playbook = write_local_playbook(tmp_path / "playbook.json", tasks, desktop_variables(home))
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    environment = ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library))
    preview = run_playbook([*command, "--check"], environment)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert not json.loads(state_file.read_text())["timer_started"]
    result = run_playbook(command, environment)
    assert (result.returncode != 0) == fail_activation, result.stdout + result.stderr
    assert json.loads(state_file.read_text())["timer_started"] is not fail_activation
    if fail_activation:
        assert "synthetic timer activation failure" in result.stdout
