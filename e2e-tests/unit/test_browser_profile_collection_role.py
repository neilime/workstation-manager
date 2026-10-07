"""Exercise cleanup metadata loading separately from setup and backup avatar recovery."""

from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import ansible_environment, managed_user, write_local_playbook

pytestmark = pytest.mark.integration

WORKSPACE = pathlib.Path(__file__).parents[2]
COLLECTION_ROLE = "neilime.workstation_setup.browser_profile_collection"
RECOVERY_WORDS = "synthetic recovery words must stay private"
AVATAR = b"synthetic avatar attachment"
ATTACHMENT_ERROR = "synthetic private attachment error"


class BrowserProfileCollectionRoleTests(unittest.TestCase):
    """Use real collection parsing and profile inspection with an isolated Bitwarden CLI."""

    def setUp(self) -> None:
        # enterContext also cleans up fixtures when preparation fails.
        # pylint: disable-next=consider-using-with
        self.fixture = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.browser_root = self.fixture / ".config/BraveSoftware/Brave-Browser"
        for directory in ("Default", "Profile 9999", "e2e-component-cache"):
            profile = self.browser_root / directory
            profile.mkdir(parents=True)
            (profile / "marker").write_text("preserve\n")
            if directory != "e2e-component-cache":
                (profile / "Preferences").write_text("{}\n")
        self.items = [
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "type": 2,
                "name": "Personal",
                "notes": RECOVERY_WORDS,
                "fields": [{"name": "id", "value": "personal"}, {"name": "directory", "value": "Default"}],
                "attachments": [{"id": "fixture-avatar", "fileName": "avatar.png"}],
            }
        ]
        (self.fixture / "avatar").write_bytes(AVATAR)
        (self.fixture / "bin").mkdir()
        cli = self.fixture / "bin/bw"
        cli.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, sys\n"
            "root = pathlib.Path(os.environ['HOME'])\n"
            "command = sys.argv[1:]\n"
            "has_session = len(command) >= 2 and command[-2] == '--session'\n"
            "if has_session:\n"
            "    command = command[:-2]\n"
            "with (root / 'calls').open('a') as log:\n"
            "    log.write(json.dumps(command) + '\\n')\n"
            "if command == ['--version']:\n"
            "    print('fixture')\n"
            "elif command == ['status']:\n"
            "    status = 'unlocked' if has_session else 'locked'\n"
            "    print(json.dumps({'status': status, 'serverUrl': 'https://vault.example.invalid'}))\n"
            "elif command[0] == 'unlock':\n"
            "    if (root / 'unlock-rejected').exists():\n"
            "        sys.exit(1)\n"
            "    print('fixture-session')\n"
            "elif command == ['sync']:\n"
            "    pass\n"
            "elif command[:2] == ['list', 'items']:\n"
            "    if '--search' in command:\n"
            "        sys.exit(98)\n"
            "    print((root / 'items.json').read_text())\n"
            "elif command[:2] == ['get', 'attachment']:\n"
            "    failures = root / 'attachment-failures'\n"
            "    if failures.exists() and int(failures.read_text()) > 0:\n"
            "        failures.write_text(str(int(failures.read_text()) - 1))\n"
            f"        print({ATTACHMENT_ERROR!r}, file=sys.stderr)\n"
            "        sys.exit(1)\n"
            "    if (root / 'attachment-unavailable').exists():\n"
            f"        print({ATTACHMENT_ERROR!r}, file=sys.stderr)\n"
            "        sys.exit(1)\n"
            "    sys.stdout.buffer.write((root / 'avatar').read_bytes())\n"
            "else:\n"
            "    sys.exit(99)\n"
        )
        cli.chmod(0o755)
        cleanup = DataLoader().load_from_file(str(WORKSPACE / "ansible/cleanup.yml"))[0]
        self.cleanup_loader = next(
            task
            for task in cleanup["tasks"]
            if task.get("ansible.builtin.import_role", {}).get("name") == COLLECTION_ROLE
        )

    def run_loader(self, *, cleanup: bool = True, check: bool = False) -> subprocess.CompletedProcess[str]:
        """Execute the production cleanup import or the full recovery loader without live credentials."""

        (self.fixture / "items.json").write_text(json.dumps(self.items))
        tasks = [self.cleanup_loader if cleanup else {"ansible.builtin.import_role": {"name": COLLECTION_ROLE}}]
        if cleanup:
            tasks.append(
                {
                    "name": "Inspect native profiles using the cleanup adapter",
                    "ansible.builtin.include_role": {
                        "name": "neilime.workstation_setup.browser_brave",
                        "tasks_from": "inspect_profiles",
                    },
                }
            )
        tasks.append(
            {
                "name": "Capture only the public inventory for test assertions",
                "ansible.builtin.copy": {
                    "content": "{{ {'profiles': workstation_manager_browser_profiles, 'drift': "
                    "workstation_manager_cleanup_unmanaged_browser_profile_directories | default([])} | to_json }}",
                    "dest": str(self.fixture / "result.json"),
                    "mode": "0600",
                },
                "check_mode": False,
            }
        )
        variables = {
            "ansible_python_interpreter": sys.executable,
            "workstation_manager_use_become": False,
            "workstation_manager_resolved": {
                "user": managed_user(self.fixture),
                "secrets": {
                    "bitwarden": {
                        "server": "https://vault.example.invalid",
                        "browser_profiles_collection_id": "22222222-2222-4222-8222-222222222222",
                    }
                },
            },
        }
        playbook = self.fixture / "playbook.json"
        write_local_playbook(playbook, tasks, variables, name="Exercise browser profile recovery boundaries")
        result = subprocess.run(
            ["ansible-playbook", "-i", "localhost,", str(playbook), *(["--check"] if check else [])],
            env=ansible_environment(
                self.fixture, PATH=f"{self.fixture / 'bin'}:{os.environ['PATH']}", BITWARDEN_PASSWORD="fixture-password"
            ),
            cwd=self.fixture,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertNotIn(RECOVERY_WORDS, result.stdout)
        self.assertNotIn(ATTACHMENT_ERROR, result.stdout)
        self.assertNotIn(base64.b64encode(AVATAR).decode(), result.stdout)
        return result

    def test_cleanup_reports_drift_without_downloading_avatars(self) -> None:
        """Apply and preview classify profiles correctly even when attachments are unavailable."""

        (self.fixture / "attachment-unavailable").touch()
        original = {path: path.read_bytes() for path in self.browser_root.rglob("*") if path.is_file()}
        for check in (False, True):
            with self.subTest(check=check):
                result = self.run_loader(check=check)
                self.assertEqual(result.returncode, 0, result.stdout)
                inventory = json.loads((self.fixture / "result.json").read_text())
                self.assertEqual(inventory["drift"], [str(self.browser_root / "Profile 9999")])
                self.assertEqual(inventory["profiles"][0]["directory"], "Default")
                self.assertNotIn("avatar_png", inventory["profiles"][0])
                self.assertNotIn(RECOVERY_WORDS, json.dumps(inventory))
                calls = [json.loads(line) for line in (self.fixture / "calls").read_text().splitlines()]
                self.assertFalse(any(call[:2] == ["get", "attachment"] for call in calls))
                self.assertEqual(
                    {path: path.read_bytes() for path in self.browser_root.rglob("*") if path.is_file()}, original
                )

    def test_cleanup_still_rejects_missing_or_invalid_profile_definitions(self) -> None:
        """Skipping images must never turn an inaccessible or malformed collection into success."""

        self.items[0]["notes"] = ""
        for items in (self.items, []):
            with self.subTest(items=bool(items)):
                self.items = items
                result = self.run_loader()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.fixture / "result.json").exists())

    def test_setup_and_backup_loader_still_requires_avatar_recovery(self) -> None:
        """A failed avatar download must remain fatal after exhausting recovery retries."""

        (self.fixture / "attachment-unavailable").touch()
        result = self.run_loader(cleanup=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Browser avatar recovery failed after retrying", result.stdout)
        calls = [json.loads(line) for line in (self.fixture / "calls").read_text().splitlines()]
        self.assertEqual(sum(call[:2] == ["get", "attachment"] for call in calls), 4)
        self.assertFalse((self.fixture / "result.json").exists())

    def test_avatar_download_recovers_from_a_temporary_failure(self) -> None:
        """Apply and preview retry a failed read without publishing partial avatar data."""

        for check in (False, True):
            with self.subTest(check=check):
                (self.fixture / "attachment-failures").write_text("1")
                (self.fixture / "calls").write_text("")

                result = self.run_loader(cleanup=False, check=check)

                self.assertEqual(result.returncode, 0, result.stdout)
                inventory = json.loads((self.fixture / "result.json").read_text())
                self.assertEqual(base64.b64decode(inventory["profiles"][0]["avatar_png"]), AVATAR)
                calls = [json.loads(line) for line in (self.fixture / "calls").read_text().splitlines()]
                self.assertEqual(sum(call[:2] == ["get", "attachment"] for call in calls), 2)

    def test_unlock_rejection_surfaces_a_retryable_marker(self) -> None:
        """A rejected vault password must fail without exposing secrets and leave a retry marker."""

        (self.fixture / "unlock-rejected").touch()
        result = self.run_loader(cleanup=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WORKSTATION_MANAGER_BITWARDEN_PASSWORD_REJECTED", result.stdout)
        self.assertFalse((self.fixture / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
