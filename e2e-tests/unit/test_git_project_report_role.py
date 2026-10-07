"""Exercise mandatory Git report scheduling without changing host packages or services."""

import json
import os
import shutil

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import (
    SETUP_ROLES,
    ansible_environment,
    managed_user,
    run_playbook,
    write_local_playbook,
)

pytestmark = pytest.mark.integration


def test_notifications_install_without_configuration_and_converge(tmp_path):
    """A preview preserves the home; setup enables future sessions and converges once."""
    role = tmp_path / "development_tooling"
    shutil.copytree(SETUP_ROLES / role.name, role)
    notifications = role / "tasks/git_project_notifications.yml"
    tasks = DataLoader().load_from_file(str(notifications))
    for task in tasks:
        if "ansible.builtin.apt" in task:
            # The VM test verifies packages; all user files use real Ansible modules here.
            task["ansible.builtin.debug"] = {"msg": task.pop("ansible.builtin.apt")}
    notifications.write_text(json.dumps(tasks))
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    autostart = home / ".config/autostart/workstation-manager-git-project-report.desktop"
    timer = home / ".config/systemd/user/timers.target.wants/workstation-manager-git-project-report.timer"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "id").write_text('#!/bin/sh\nprintf "%s\\n" "4294967294"\n')
    (stubs / "id").chmod(0o755)
    (stubs / "systemctl").write_text("#!/bin/sh\nexit 99\n")
    (stubs / "systemctl").chmod(0o755)
    playbook = tmp_path / "playbook.json"
    write_local_playbook(
        playbook,
        [
            {
                "ansible.builtin.import_role": {
                    "name": str(role),
                    "tasks_from": "git_project_report",
                }
            }
        ],
        {
            "workstation_manager_use_become": False,
            "workstation_manager_resolved": {
                "user": {**managed_user(home), "projects_directory": str(home / "projects")},
            },
        },
    )
    environment = ansible_environment(tmp_path, PATH=str(stubs) + ":" + os.environ["PATH"])
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    result = run_playbook([*command, "--check"], environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".config").exists()
    assert not any((home / ".local/bin").iterdir())
    assert not (home / ".local/share").exists()
    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "next graphical login" in result.stdout
    assert autostart.exists()
    assert timer.is_symlink()
    assert timer.resolve().is_file()
    assert (timer.parent.parent / "workstation-manager-git-project-report.service").is_file()
    assert (home / ".local/bin/workstation-manager-git-project-report").exists()
    assert (home / ".local/bin/workstation-manager-git-project-report-activate-timer").exists()
    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=0" in result.stdout
