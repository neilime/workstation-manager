"""Exercise alert installation with isolated files and a simulated user session."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

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

SESSION_OPERATIONS = r"""
if operation == "command":
    if args["argv"][:2] == ["id", "-u"]:
        result.update(rc=0, stdout="15123")
    elif args["argv"] == ["systemctl", "--user", "is-active", "--quiet", "graphical-session.target"]:
        result.update(rc=0 if state["graphical"] else 3, stdout="")
    else:
        module.fail_json(msg="Unexpected session command")
elif operation == "stat":
    if args["path"] != "/run/user/15123/bus":
        module.fail_json(msg="Wrong target user bus")
    result["stat"] = {"exists": state["bus"]}
elif operation == "systemd_service":
    import os
    if args["scope"] != "user" or os.environ.get("DBUS_SESSION_BUS_ADDRESS") != "unix:path=/run/user/15123/bus":
        module.fail_json(msg="Wrong activation bus")
    if args.get("daemon_reload"):
        state["reloaded"] = True
    else:
        if args["name"] != "workstation-manager-memory-alerts.service" or args["state"] not in ["started", "restarted"]:
            module.fail_json(msg="Unexpected service activation")
        if state["fail_activation"]:
            module.fail_json(msg="synthetic activation failure")
        state["started"] = True
        state["restarts"] += int(args["state"] == "restarted")
"""


def isolated_tasks(role, state_file):
    """Keep real file operations and isolate only the systemd session boundary."""
    tasks = DataLoader().load_from_file(str(role / "tasks/memory_alerts.yml"))

    def isolate(task):
        if "ansible.builtin.template" in task:
            arguments = task["ansible.builtin.template"]
            arguments["src"] = str(role / "templates" / arguments["src"])
        for name in ("command", "stat", "systemd_service"):
            if "ansible.builtin." + name in task:
                task["fixture_session"] = {
                    "operation": name,
                    "arguments": task.pop("ansible.builtin." + name),
                    "state_file": str(state_file),
                }
        for child in task.get("block", []):
            isolate(child)

    for task in tasks:
        isolate(task)
    return tasks


@pytest.fixture(name="installation")
def memory_alerts_installation(tmp_path, public_defaults, session):
    """Prepare isolated Ansible execution without touching the real desktop."""
    role = SETUP_ROLES / "gnome_preferences"
    home = tmp_path / "home with spaces"
    home.mkdir()
    unfinished_work = home / "unfinished-work.txt"
    unfinished_work.write_text("keep my work\n")
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "bus": session != "headless",
                "graphical": session in {"active", "failure"},
                "fail_activation": session == "failure",
                "started": False,
                "reloaded": False,
                "restarts": 0,
            }
        )
    )
    library = tmp_path / "library"
    library.mkdir()
    write_stateful_module(library / "fixture_session.py", SESSION_OPERATIONS)
    thresholds = dict(public_defaults["desktop"]["memory_alerts"])
    variables = desktop_variables(home, desktop={"memory_alerts": thresholds})
    variables["role_path"] = str(role)
    tasks = isolated_tasks(role, state_file)
    playbook = write_local_playbook(tmp_path / "playbook.json", tasks, variables)
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    environment = ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library))
    return home, state_file, command, environment, thresholds


def assert_installed_files(home, environment, thresholds):
    """Check ownership, enablement, and the executable in a home containing spaces."""
    executable = home / ".local/bin/workstation-manager-memory-alerts"
    config = home / ".config/workstation-manager/memory-alerts.json"
    service = home / ".config/systemd/user/workstation-manager-memory-alerts.service"
    monitor = home / ".local/share/workstation-manager/memory-alerts.py"
    for path, mode in ((executable, 0o755), (config, 0o644), (service, 0o644), (monitor, 0o644)):
        assert path.stat().st_mode & 0o777 == mode
        assert path.stat().st_uid == os.getuid()
    link = service.parent / "graphical-session.target.wants" / service.name
    assert link.is_symlink()
    assert link.resolve() == service
    assert json.loads(config.read_text()) == thresholds
    status = subprocess.run(
        [str(executable), "--status"],
        env={**environment, "HOME": str(home)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert status.returncode == 0, status.stderr
    assert "RAM available:" in status.stdout
    assert "Memory stalls (last 10 seconds):" in status.stdout


@pytest.mark.parametrize("session", ["headless", "inactive", "active", "failure"])
def test_memory_alerts_install_preview_and_session_lifecycle(installation, session):
    """Preserve user files, preview safely, converge, and surface activation failures."""
    home, state_file, command, environment, thresholds = installation
    preview = run_playbook([*command, "--check"], environment)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert list(home.iterdir()) == [home / "unfinished-work.txt"]
    assert not json.loads(state_file.read_text())["started"]
    assert not json.loads(state_file.read_text())["reloaded"]

    result = run_playbook(command, environment)
    if session == "failure":
        assert result.returncode != 0
        assert "synthetic activation failure" in result.stdout
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(state_file.read_text())["started"] == (session == "active")
    assert json.loads(state_file.read_text())["reloaded"] == (session != "headless")
    if session != "active":
        assert "next graphical login" in result.stdout
    assert_installed_files(home, environment, thresholds)
    installed_state = state_file.read_text()
    repeated = run_playbook(command, environment)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    assert state_file.read_text() == installed_state
    if session == "active":
        config = home / ".config/workstation-manager/memory-alerts.json"
        playbook = Path(command[-1])
        play = json.loads(playbook.read_text(encoding="utf-8"))
        thresholds["available_warning_percent"] = 35
        play[0]["vars"]["workstation_manager_resolved"]["desktop"]["memory_alerts"] = thresholds
        playbook.write_text(json.dumps(play), encoding="utf-8")
        preview = run_playbook([*command, "--check"], environment)
        assert preview.returncode == 0, preview.stdout + preview.stderr
        assert json.loads(config.read_text())["available_warning_percent"] != 35
        assert state_file.read_text() == installed_state
        updated = run_playbook(command, environment)
        assert updated.returncode == 0, updated.stdout + updated.stderr
        assert json.loads(config.read_text()) == thresholds
        assert json.loads(state_file.read_text())["restarts"] == 2
    assert (home / "unfinished-work.txt").read_text() == "keep my work\n"
