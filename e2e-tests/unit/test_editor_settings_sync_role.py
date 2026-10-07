"""Exercise editor sync orchestration when the desktop session probe is skipped."""

from __future__ import annotations

import pathlib
import tempfile
import unittest

import pytest
from ansible_test_helpers import ansible_environment, run_playbook, write_local_playbook

pytestmark = pytest.mark.integration


class EditorSettingsSyncRoleTests(unittest.TestCase):
    """Skipped probes must not require shell-only result fields or launch an editor."""

    def test_skipped_session_probes_complete_without_requesting_sync(self) -> None:
        """Each independent skip condition must remain safe during real role evaluation."""
        scenarios = (
            {"name": "noninteractive", "interactive": "0"},
            {"name": "check_mode", "check_mode": True},
            {"name": "existing_sync_state", "sync_state_exists": True},
            {"name": "no_vscode", "editor_packages": []},
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]), tempfile.TemporaryDirectory() as temporary_dir:
                fixture = pathlib.Path(temporary_dir)
                (fixture / "ansible.cfg").write_text("[defaults]\ninject_facts_as_vars = False\n")
                user_home = fixture / "home"
                user_home.mkdir()
                if scenario.get("sync_state_exists"):
                    (user_home / ".config" / "Code" / "User" / "sync").mkdir(parents=True)
                playbook = fixture / "playbook.json"
                write_local_playbook(
                    playbook,
                    [
                        {
                            "name": "Verify the editor remains untouched",
                            "ansible.builtin.assert": {
                                "that": [
                                    "workstation_manager_vscode_settings_sync_session_environment is skipped",
                                    "not workstation_manager_vscode_should_request_settings_sync",
                                    "workstation_manager_vscode_settings_sync_command is skipped",
                                    "not workstation_manager_vscode_should_remind_settings_sync",
                                ]
                            },
                        }
                    ],
                    {
                        "ansible_facts": {"user_id": "test-user"},
                        "workstation_manager_use_become": False,
                        "workstation_manager_resolved": {
                            "user": {"name": "test-user", "home": str(user_home)},
                            "development": {"editor_packages": scenario.get("editor_packages", ["code"])},
                        },
                    },
                    name="Verify skipped editor sync probes",
                    roles=["neilime.workstation_setup.editor_settings_sync"],
                )
                command = ["ansible-playbook", "--inventory", "localhost,", str(playbook)]
                if scenario.get("check_mode"):
                    command.append("--check")
                result = run_playbook(
                    command,
                    ansible_environment(fixture, WORKSTATION_MANAGER_INTERACTIVE=str(scenario.get("interactive", "1"))),
                    cwd=fixture,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
