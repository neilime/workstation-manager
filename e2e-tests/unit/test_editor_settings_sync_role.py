"""Exercise editor sync orchestration when the desktop session probe is skipped."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

COLLECTIONS_PATH = pathlib.Path(__file__).parents[2] / "ansible" / "collections"


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
                (fixture / "ansible.cfg").write_text("[defaults]\n")
                user_home = fixture / "home"
                user_home.mkdir()
                if scenario.get("sync_state_exists"):
                    (user_home / ".config" / "Code" / "User" / "sync").mkdir(parents=True)
                playbook = fixture / "playbook.json"
                playbook.write_text(
                    json.dumps(
                        [
                            {
                                "name": "Verify skipped editor sync probes",
                                "hosts": "localhost",
                                "connection": "local",
                                "gather_facts": False,
                                "vars": {
                                    "ansible_user_id": "test-user",
                                    "ansible_python_interpreter": sys.executable,
                                    "workstation_manager_use_become": False,
                                    "workstation_manager_resolved": {
                                        "user": {"name": "test-user", "home": str(user_home)},
                                        "development": {
                                            "editor_packages": scenario.get(
                                                "editor_packages", ["com.visualstudio.code"]
                                            )
                                        },
                                    },
                                },
                                "roles": ["neilime.workstation_setup.editor_settings_sync"],
                                "tasks": [
                                    {
                                        "name": "Verify the editor remains untouched",
                                        "ansible.builtin.assert": {
                                            "that": [
                                                "workstation_manager_vscode_settings_sync_session_environment "
                                                "is skipped",
                                                "not workstation_manager_vscode_should_request_settings_sync",
                                                "workstation_manager_vscode_settings_sync_command is skipped",
                                                "not workstation_manager_vscode_should_remind_settings_sync",
                                            ]
                                        },
                                    }
                                ],
                            }
                        ]
                    )
                )
                command = ["ansible-playbook", "--inventory", "localhost,", str(playbook)]
                if scenario.get("check_mode"):
                    command.append("--check")
                result = subprocess.run(
                    command,
                    cwd=fixture,
                    env={
                        "PATH": os.environ["PATH"],
                        "HOME": str(fixture),
                        "LC_ALL": "C.UTF-8",
                        "ANSIBLE_CONFIG": str(fixture / "ansible.cfg"),
                        "ANSIBLE_HOME": str(fixture / ".ansible"),
                        "ANSIBLE_COLLECTIONS_PATH": str(COLLECTIONS_PATH),
                        "WORKSTATION_MANAGER_INTERACTIVE": str(scenario.get("interactive", "1")),
                    },
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
