"""Exercise key/browser skips and real archive reporting with isolated recovery services."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tarfile
import tempfile
import unittest

from backup_prompt_helpers import run_interactive

WORKSPACE = pathlib.Path(__file__).parents[2]


class BackupRecoverySkipTests(unittest.TestCase):
    """Skips must preserve recovery sources, continue backup, and remain visible in its manifest."""

    def setUp(self) -> None:
        # pylint: disable-next=consider-using-with
        self.fixture = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.environment = {
            "PATH": f"{self.fixture / 'bin'}:{os.environ['PATH']}",
            "HOME": str(self.fixture),
            "ANSIBLE_HOME": str(self.fixture / ".ansible"),
            "ANSIBLE_CONFIG": str(self.fixture / "ansible.cfg"),
            "ANSIBLE_COLLECTIONS_PATH": ":".join(
                [
                    str(self.fixture / "collections"),
                    str(WORKSPACE / "ansible/collections"),
                    os.environ.get(
                        "ANSIBLE_COLLECTIONS_PATH", "/opt/ansible/collections:/usr/share/ansible/collections"
                    ),
                ]
            ),
            "WORKSTATION_MANAGER_INTERACTIVE": "1",
        }
        (self.fixture / "ansible.cfg").write_text("[defaults]\n")
        (self.fixture / "projects").mkdir()
        (self.fixture / "projects/project.txt").write_text("project fixture\n")
        (self.fixture / "local-key").write_text("synthetic-private-key\n")
        (self.fixture / "bin").mkdir()
        self.variables = {
            "ansible_python_interpreter": sys.executable,
            "workstation_backup_dry_run": "{{ ansible_check_mode }}",
            "workstation_backup_timestamp": "fixture",
            "workstation_backup_archive_path": str(self.fixture / "backup.tar.gz"),
            "workstation_backup_manifest_path": str(self.fixture / "backup.manifest.txt"),
            "workstation_backup_manifest_lines": [],
            "workstation_backup_tab": "\t",
            "workstation_backup_newline": "\n",
            "workstation_backup_include_paths": [str(self.fixture / "projects")],
            "workstation_backup_archive_exclusion_patterns": [],
            "workstation_manager_resolved": {"desktop": {"browser": "fixture"}},
        }

    def run_backup(self, tasks: list[dict], answers=(), *, check=False) -> tuple[int, str]:
        """Run production recovery tasks followed by the actual manifest and archive roles."""

        finish = [
            {"ansible.builtin.include_role": {"name": "neilime.workstation_backup.manifest"}},
            {"ansible.builtin.include_role": {"name": "neilime.workstation_backup.archive"}},
        ]
        playbook = [{"hosts": "localhost", "gather_facts": False, "vars": self.variables, "tasks": tasks + finish}]
        path = self.fixture / "playbook.json"
        path.write_text(json.dumps(playbook))
        command = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(path)]
        if check:
            command.append("--check")
        return run_interactive(command, self.fixture, self.environment, answers)

    def assert_archive(self, scopes: list[str]) -> None:
        """The archive must exist without silently including skipped recovery data."""

        manifest = (self.fixture / "backup.manifest.txt").read_text()
        self.assertEqual("recovery_status\tincomplete" in manifest, bool(scopes))
        self.assertEqual(
            [line for line in manifest.splitlines() if line.startswith("recovery_skipped\t")],
            ["recovery_skipped\t" + scope for scope in scopes],
        )
        self.assertNotIn("synthetic-private-key", manifest)
        with tarfile.open(self.fixture / "backup.tar.gz") as archive:
            self.assertTrue(any(name.endswith("project.txt") for name in archive.getnames()))
            self.assertFalse(any("local-key" in name for name in archive.getnames()))
        self.assertEqual((self.fixture / "local-key").read_text(), "synthetic-private-key\n")

    def prepare_browser(self, *, drift: bool) -> list[dict]:
        """Stub inspection and vault loading while keeping the real browser decision tasks."""

        setup = self.fixture / "collections/ansible_collections/neilime/workstation_setup/roles"
        loader = setup / "browser_profile_collection/tasks"
        loader.mkdir(parents=True)
        (loader / "main.yml").write_text(
            json.dumps(
                [
                    {
                        "ansible.builtin.set_fact": {
                            "workstation_manager_browser_profiles": [{"id": "fixture"}],
                            "fixture_browser_reads": "{{ (fixture_browser_reads | default(0) | int) + 1 }}",
                        }
                    }
                ]
            )
        )
        adapter = setup / "browser_fixture/tasks"
        adapter.mkdir(parents=True)
        (adapter / "backup.yml").write_text(
            json.dumps(
                [
                    {
                        "ansible.builtin.set_fact": {
                            "workstation_backup_browser_inspection": "{{ lookup('ansible.builtin.file', '"
                            + str(self.fixture / "inspection.json")
                            + "') | from_json }}",
                            "workstation_backup_browser_sync_instructions": "Check fixture browser Sync.",
                        }
                    }
                ]
            )
        )
        self.set_browser_drift(drift)
        return [{"ansible.builtin.include_role": {"name": "neilime.workstation_backup.browser"}}]

    def set_browser_drift(self, drift: bool) -> None:
        """Represent a user's manual reconciliation without operating on real profiles."""

        (self.fixture / "inspection.json").write_text(
            json.dumps(
                {
                    "profiles": [{"id": "fixture"}],
                    "drift": ["fixture drift"] if drift else [],
                    "sync_issues": [],
                }
            )
        )

    def test_browser_drift_skip_does_not_request_live_sync(self) -> None:
        """A skipped browser recovery check must not fall into another confirmation prompt."""

        code, output = self.run_backup(self.prepare_browser(drift=True), (("[retry/skip/abort]", "skip"),))
        self.assertEqual(code, 0, output)
        self.assertNotIn("Choose [synced/skip/abort]", output)
        self.assertIn("incomplete recovery coverage", output)
        self.assert_archive(["browser-recovery"])

    def test_browser_sync_can_be_skipped_after_clean_inspection(self) -> None:
        """Choosing skip must not claim that live synchronization was confirmed."""

        code, output = self.run_backup(self.prepare_browser(drift=False), (("[synced/skip/abort]", "skip"),))
        self.assertEqual(code, 0, output)
        self.assert_archive(["browser-sync"])

    def test_browser_retry_still_requires_a_new_check_and_sync_confirmation(self) -> None:
        """Retry remains a recheck, not an implicit skip."""

        def reconcile() -> str:
            self.set_browser_drift(False)
            return "retry"

        code, output = self.run_backup(
            self.prepare_browser(drift=True),
            (
                ("[retry/skip/abort]", reconcile),
                ("[synced/skip/abort]", "synced"),
            ),
        )
        self.assertEqual(code, 0, output)
        self.assert_archive([])

    def test_browser_abort_still_prevents_archiving(self) -> None:
        """Both browser decisions retain an explicit abort that stops the backup."""

        tasks = self.prepare_browser(drift=True)
        for drift, prompt in ((True, "[retry/skip/abort]"), (False, "[synced/skip/abort]")):
            with self.subTest(drift=drift):
                self.set_browser_drift(drift)
                code, output = self.run_backup(tasks, ((prompt, "abort"),))
                self.assertNotEqual(code, 0, output)
                self.assertFalse((self.fixture / "backup.tar.gz").exists())

    def test_browser_noninteractive_and_dry_run_do_not_invent_skips(self) -> None:
        """Skipping requires a real choice; previews must not record recovery completion."""

        tasks = self.prepare_browser(drift=True)
        self.environment["WORKSTATION_MANAGER_INTERACTIVE"] = "0"
        code, output = self.run_backup(tasks)
        self.assertNotEqual(code, 0, output)
        self.assertIn("requires an interactive run", output)
        code, output = self.run_backup(tasks, check=True)
        self.assertEqual(code, 0, output)
        self.assertNotIn("Choose [", output)
        self.assertFalse((self.fixture / "backup.tar.gz").exists())
        self.assertFalse((self.fixture / "backup.manifest.txt").exists())

    def prepare_keys(self) -> list[dict]:
        """Use a fake CLI that logs operations and enforces post-write verification."""

        cli = self.fixture / "bin/bw"
        cli.write_text(
            f"#!{sys.executable}\n"
            "import json\nimport os\nimport pathlib\nimport sys\n"
            "root = pathlib.Path(os.environ['HOME'])\n"
            "command = sys.argv[1:]\n"
            "with (root / 'bw-calls').open('a') as log: log.write(command[0] + '\\n')\n"
            "store = root / 'saved-item.json'\n"
            "if command == ['encode']: print(sys.stdin.read())\n"
            "elif command[0] in ('create', 'edit'):\n"
            "    item = json.load(sys.stdin); item['id'] = 'fixture-id'\n"
            "    store.write_text(json.dumps(item)); print(json.dumps(item))\n"
            "elif command == ['sync']: pass\n"
            "elif command[:2] == ['get', 'item']:\n"
            "    item = (json.loads(store.read_text()) if store.exists()\n"
            "            else {'collectionIds': ['fixture-collection']})\n"
            "    if (root / 'bad-readback').exists(): item['fields'] = []\n"
            "    print(json.dumps(item))\n"
            "else: sys.exit(99)\n"
        )
        cli.chmod(0o755)
        actions = [
            {
                "kind": kind,
                "name": "fixture-key",
                "action": action,
                "collection_id": "fixture-collection",
                "organization_id": "",
                "bitwarden_item_id": "fixture-id",
                "bitwarden_session": "synthetic-session",
                "fields": [{"name": "private_key", "value": "synthetic-private-key"}],
            }
            for kind, action in (("ssh", "add"), ("gpg", "update"))
        ]
        return [
            {
                "ansible.builtin.include_role": {
                    "name": "neilime.workstation_backup.secret_manager_keys",
                    "tasks_from": "prompt_and_apply_action",
                },
                "loop": actions,
                "no_log": True,
            }
        ]

    def test_each_key_can_be_skipped_without_any_vault_write(self) -> None:
        """SSH and GPG skips must not encode, save, or claim to verify a key."""

        code, output = self.run_backup(
            self.prepare_keys(),
            (
                ("[add/skip/abort]", "skip"),
                ("[update/skip/abort]", "skip"),
            ),
        )
        self.assertEqual(code, 0, output)
        self.assertFalse((self.fixture / "bw-calls").exists())
        self.assertNotIn("synthetic-private-key", output)
        self.assertNotIn("synthetic-session", output)
        self.assert_archive(["ssh-keys", "gpg-keys"])

    def test_key_skip_does_not_skip_the_next_approved_key(self) -> None:
        """A skip applies only to its item and must not suppress another item's verification."""

        code, output = self.run_backup(
            self.prepare_keys(),
            (
                ("[add/skip/abort]", "skip"),
                ("[update/skip/abort]", "update"),
            ),
        )
        self.assertEqual(code, 0, output)
        self.assertEqual((self.fixture / "bw-calls").read_text().splitlines(), ["get", "encode", "edit", "sync", "get"])
        self.assert_archive(["ssh-keys"])

    def test_key_verification_failure_after_a_skip_still_stops_backup(self) -> None:
        """Skipping one key cannot turn a failed save of another key into a successful backup."""

        (self.fixture / "bad-readback").touch()
        code, output = self.run_backup(
            self.prepare_keys(),
            (
                ("[add/skip/abort]", "skip"),
                ("[update/skip/abort]", "update"),
            ),
        )
        self.assertNotEqual(code, 0, output)
        self.assertFalse((self.fixture / "backup.tar.gz").exists())
        self.assertNotIn("synthetic-private-key", output)


if __name__ == "__main__":
    unittest.main()
