"""Exercise orchestration with gathered facts and no injected fact variables."""

from __future__ import annotations

import os
import pathlib
import pwd
import sys

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible.utils.vars import merge_hash
from ansible_test_helpers import ansible_environment, run_playbook, write_local_playbook

pytestmark = pytest.mark.integration

REPOSITORY_PATH = pathlib.Path(__file__).parents[2]


def selected_task(relative_path: str, name: str) -> dict[str, object]:
    """Read the production task without executing other workstation operations."""

    tasks = DataLoader().load_from_file(str(REPOSITORY_PATH / relative_path))
    return next(task for task in tasks if task["name"] == name)


@pytest.mark.parametrize("use_become,same_user", [(False, False), (True, False), (True, True)])
def test_gathered_facts_work_without_injection(
    tmp_path: pathlib.Path, public_defaults, private_overrides, use_become: bool, same_user: bool
) -> None:
    """Configuration and desktop privilege decisions must use namespaced facts."""

    controller_user = pwd.getpwuid(os.getuid()).pw_name
    managed_user = controller_user if same_user else "fixture-managed-user"
    setup_roles = "ansible/collections/ansible_collections/neilime/workstation_setup/roles"
    config_tasks = "ansible/tasks/resolve_workstation_config.yml"
    tasks: list[dict[str, object]] = [
        selected_task(config_tasks, "Merge public defaults with local private overrides"),
        selected_task(config_tasks, "Normalize desired state schema"),
        selected_task(f"{setup_roles}/gnome_preferences/tasks/main.yml", "Compute GNOME task privilege requirements"),
        selected_task(f"{setup_roles}/editor_settings_sync/tasks/main.yml", "Resolve VS Code settings sync state"),
        {
            "name": "Verify namespaced facts preserve orchestration results",
            "ansible.builtin.assert": {
                "that": [
                    "ansible_user_id is undefined",
                    "ansible_env is undefined",
                    "ansible_date_time is undefined",
                    "workstation_manager_resolved.user.name == ansible_facts['env']['SUDO_USER']",
                    "workstation_manager_resolved.development.github.account == 'fixture'",
                    "workstation_manager_gnome_use_become_user == fixture_expected_become_user",
                    "workstation_manager_vscode_settings_sync_use_become_user == fixture_expected_become_user",
                ]
            },
        },
    ]
    variables: dict[str, object] = {
        "ansible_python_interpreter": sys.executable,
        "workstation_manager": public_defaults,
        "workstation_private_override": private_overrides,
        "workstation_use_become": use_become,
        "fixture_expected_become_user": use_become and not same_user,
    }
    playbook = tmp_path / "playbook.json"
    write_local_playbook(playbook, tasks, variables, gather_facts=True, gather_subset=["min"])
    config = tmp_path / "ansible.cfg"
    config.write_text("[defaults]\ninject_facts_as_vars = False\n")
    result = run_playbook(
        ["ansible-playbook", "--inventory", "localhost,", str(playbook)],
        ansible_environment(tmp_path, USER=controller_user, SUDO_USER=managed_user),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INJECT_FACTS_AS_VARS" not in result.stdout + result.stderr


def test_private_values_merge_before_schema_normalization(tmp_path, public_defaults, private_overrides) -> None:
    """Nested mappings retain public fields and declared lists replace default lists."""
    config_tasks = "ansible/tasks/resolve_workstation_config.yml"
    tasks: list[dict[str, object]] = [
        selected_task(config_tasks, "Merge public defaults with local private overrides"),
        selected_task(config_tasks, "Normalize desired state schema"),
        {
            "name": "Verify merged values reach consumers without changing the defaults",
            "ansible.builtin.assert": {
                "that": [
                    "workstation_manager_resolved.development.ai_tools.providers.codex.version == '9.8.7'",
                    (
                        "workstation_manager_resolved.development.ai_tools.providers.codex.npm == "
                        "workstation_manager.development.ai_tools.providers.codex.npm"
                    ),
                    "workstation_manager_resolved.development.ai_tools.skills == []",
                    "workstation_manager.development.ai_tools.providers.codex.version == fixture_public_version",
                    "workstation_manager.development.ai_tools.skills | length > 0",
                    "context7.env.CONTEXT7_API_KEY.bitwarden_item_id == fixture_context7_item_id",
                    "context7.env.CONTEXT7_API_KEY.field == 'login.password'",
                    "context7.auth_check == context7_public.auth_check",
                    "context7.npm.version == context7_public.version",
                ]
            },
        },
    ]
    variables = {
        "workstation_manager": public_defaults,
        "workstation_private_override": merge_hash(
            private_overrides,
            {
                "development": {
                    "github": {"account": "fixture"},
                    "ai_tools": {"providers": {"codex": {"version": "9.8.7"}}, "skills": []},
                },
                "secrets": {"bitwarden": {"context7-api-key": "{{ fixture_context7_item_id }}"}},
            },
        ),
        "workstation_use_become": False,
        "ansible_facts": {"env": {"USER": "fixture"}},
        "fixture_context7_item_id": "11111111-1111-1111-1111-111111111111",
        "context7": (
            "{{ workstation_manager_resolved.development.ai_tools.mcp_servers "
            "| selectattr('name', 'equalto', 'context7') | first }}"
        ),
        "context7_public": (
            "{{ workstation_manager.development.ai_tools.mcp_servers "
            "| selectattr('name', 'equalto', 'context7') | first }}"
        ),
        "fixture_public_version": public_defaults["development"]["ai_tools"]["providers"]["codex"]["version"],
    }
    playbook = write_local_playbook(tmp_path / "playbook.json", tasks, variables)
    result = run_playbook(
        ["ansible-playbook", "--inventory", "localhost,", str(playbook)],
        ansible_environment(tmp_path),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
