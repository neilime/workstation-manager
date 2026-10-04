"""Exercise orchestration with gathered facts and no injected fact variables."""

from __future__ import annotations

import json
import os
import pathlib
import pwd
import subprocess
import sys

import pytest
from ansible.parsing.dataloader import DataLoader

REPOSITORY_PATH = pathlib.Path(__file__).parents[2]
COLLECTIONS_PATH = REPOSITORY_PATH / "ansible/collections"


def selected_task(relative_path: str, name: str) -> dict[str, object]:
    """Read the production task without executing other workstation operations."""

    tasks = DataLoader().load_from_file(str(REPOSITORY_PATH / relative_path))
    return next(task for task in tasks if task["name"] == name)


@pytest.mark.parametrize("use_become,same_user", [(False, False), (True, False), (True, True)])
def test_gathered_facts_work_without_injection(tmp_path: pathlib.Path, use_become: bool, same_user: bool) -> None:
    """Configuration, desktop privilege decisions, and reports must use namespaced facts."""

    controller_user = pwd.getpwuid(os.getuid()).pw_name
    managed_user = controller_user if same_user else "fixture-managed-user"
    setup_roles = "ansible/collections/ansible_collections/neilime/workstation_setup/roles"
    cleanup_tasks = "ansible/collections/ansible_collections/neilime/workstation_cleanup/roles/cleanup/tasks/main.yml"
    config_tasks = "ansible/tasks/resolve_workstation_config.yml"
    tasks = [
        selected_task(config_tasks, "Merge public defaults with local private overrides"),
        selected_task(config_tasks, "Normalize desired state schema"),
        selected_task(f"{setup_roles}/gnome_preferences/tasks/main.yml", "Compute GNOME task privilege requirements"),
        selected_task(f"{setup_roles}/editor_settings_sync/tasks/main.yml", "Resolve VS Code settings sync state"),
        selected_task(cleanup_tasks, "Build cleanup report payload"),
        {
            "name": "Verify namespaced facts preserve orchestration results",
            "ansible.builtin.assert": {
                "that": [
                    "ansible_user_id is undefined",
                    "ansible_env is undefined",
                    "ansible_date_time is undefined",
                    "workstation_manager_resolved.user.name == ansible_facts['env']['SUDO_USER']",
                    "workstation_manager_gnome_use_become_user == fixture_expected_become_user",
                    "workstation_manager_vscode_settings_sync_use_become_user == fixture_expected_become_user",
                    "workstation_manager_cleanup_report.generated_at == ansible_facts['date_time']['iso8601']",
                ]
            },
        },
    ]
    variables: dict[str, object] = {
        "ansible_python_interpreter": sys.executable,
        "workstation_manager": {},
        "workstation_use_become": use_become,
        "fixture_expected_become_user": use_become and not same_user,
        "workstation_manager_cleanup_has_package_baseline": False,
        "workstation_manager_cleanup_docker_command": {"rc": 1},
        "workstation_manager_cleanup_docker_prune": {},
        "workstation_manager_cleanup_apt_upgrade": {},
        "workstation_manager_cleanup_journal_vacuum": {},
    }
    for field in (
        "unexpected_manual_apt_packages",
        "unexpected_flatpak_packages",
        "unmanaged_browser_profile_directories",
        "unexpected_system_state_paths",
        "unexpected_user_state_paths",
        "unexpected_managed_config_paths",
    ):
        variables[f"workstation_manager_cleanup_{field}"] = []
    playbook = tmp_path / "playbook.json"
    playbook.write_text(
        json.dumps(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": True,
                    "gather_subset": ["min"],
                    "vars": variables,
                    "tasks": tasks,
                }
            ]
        )
    )
    config = tmp_path / "ansible.cfg"
    config.write_text("[defaults]\ninject_facts_as_vars = False\n")
    result = subprocess.run(
        ["ansible-playbook", "--inventory", "localhost,", str(playbook)],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "USER": controller_user,
            "SUDO_USER": managed_user,
            "LC_ALL": "C.UTF-8",
            "ANSIBLE_CONFIG": str(config),
            "ANSIBLE_HOME": str(tmp_path / ".ansible"),
            "ANSIBLE_COLLECTIONS_PATH": str(COLLECTIONS_PATH),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INJECT_FACTS_AS_VARS" not in result.stdout + result.stderr
