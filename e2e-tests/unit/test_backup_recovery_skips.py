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
        self.variables: dict = {
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

    def _prepare_browser(self, *, drift: bool) -> list[dict]:
        """Stub inspection and vault loading while keeping the real browser decision tasks."""

        setup = self.fixture / "collections/ansible_collections/neilime/workstation_setup/roles"
        loader = setup / "browser_profile_collection/tasks"
        loader.mkdir(parents=True)
        (setup.parent / "plugins").symlink_to(
            WORKSPACE / "ansible/collections/ansible_collections/neilime/workstation_setup/plugins",
            target_is_directory=True,
        )
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
                    },
                    {
                        "ansible.builtin.set_fact": {
                            "workstation_backup_browser_recovery_report": (
                                "{{ workstation_backup_browser_inspection | "
                                "neilime.workstation_setup.browser_recovery_report }}"
                            )
                        }
                    },
                ]
            )
        )
        self._set_browser_drift(drift)
        return [{"ansible.builtin.include_role": {"name": "neilime.workstation_backup.browser"}}]

    def _set_browser_drift(self, drift: bool) -> None:
        """Represent a user's manual reconciliation without operating on real profiles."""

        (self.fixture / "inspection.json").write_text(
            json.dumps(
                {
                    "profiles": [{"id": "fixture", "label": "Fixture", "directory": "Default"}],
                    "drift": (
                        [
                            {
                                "kind": "avatar",
                                "directory": "Default",
                                "issues": ["missing_avatar_file", "avatar_disabled"],
                            }
                        ]
                        if drift
                        else []
                    ),
                    "sync_issues": [],
                }
            )
        )

    def test_browser_drift_skip_does_not_request_live_sync(self) -> None:
        """A skipped browser recovery check must not fall into another confirmation prompt."""

        code, output = self.run_backup(self._prepare_browser(drift=True), (("[retry/skip/abort]", "skip"),))
        self.assertEqual(code, 0, output)
        self.assertNotIn("Choose [synced/skip/abort]", output)
        self.assertIn("incomplete recovery coverage", output)
        self.assertEqual(output.count("Restore missing profile logos."), 1)
        self.assertIn("Fixture (Default)", output)
        self.assertIn("restore", output)
        self.assertIn("stop backup without creating an archive", output)
        self.assertNotIn("profile_drift", output)
        self.assertNotIn("avatar_disabled", output)
        self.assertNotIn("theme_colors", output)
        self.assertNotIn("Check fixture browser Sync.", output)
        self.assert_archive(["browser-recovery"])

    def test_browser_sync_can_be_skipped_after_clean_inspection(self) -> None:
        """Choosing skip must not claim that live synchronization was confirmed."""

        code, output = self.run_backup(self._prepare_browser(drift=False), (("[synced/skip/abort]", "skip"),))
        self.assertEqual(code, 0, output)
        self.assert_archive(["browser-sync"])

    def test_browser_retry_still_requires_a_new_check_and_sync_confirmation(self) -> None:
        """Retry remains a recheck, not an implicit skip."""

        def reconcile() -> str:
            self._set_browser_drift(False)
            return "retry"

        code, output = self.run_backup(
            self._prepare_browser(drift=True),
            (
                ("[retry/skip/abort]", reconcile),
                ("[synced/skip/abort]", "synced"),
            ),
        )
        self.assertEqual(code, 0, output)
        self.assert_archive([])

    def test_browser_abort_still_prevents_archiving(self) -> None:
        """Both browser decisions retain an explicit abort that stops the backup."""

        tasks = self._prepare_browser(drift=True)
        for drift, prompt in ((True, "[retry/skip/abort]"), (False, "[synced/skip/abort]")):
            with self.subTest(drift=drift):
                self._set_browser_drift(drift)
                code, output = self.run_backup(tasks, ((prompt, "abort"),))
                self.assertNotEqual(code, 0, output)
                self.assertFalse((self.fixture / "backup.tar.gz").exists())

    def test_browser_noninteractive_and_dry_run_do_not_invent_skips(self) -> None:
        """Skipping requires a real choice; previews must not record recovery completion."""

        tasks = self._prepare_browser(drift=True)
        self.environment["WORKSTATION_MANAGER_INTERACTIVE"] = "0"
        code, output = self.run_backup(tasks)
        self.assertNotEqual(code, 0, output)
        self.assertIn("requires an interactive run", output)
        self.assertIn("Restore missing profile logos.", output)
        code, output = self.run_backup(tasks, check=True)
        self.assertEqual(code, 0, output)
        self.assertNotIn("Choose [", output)
        self.assertIn("Restore missing profile logos.", output)
        self.assertIn("Fixture (Default)", output)
        self.assertFalse((self.fixture / "backup.tar.gz").exists())
        self.assertFalse((self.fixture / "backup.manifest.txt").exists())

    def prepare_keys(self) -> list[dict]:
        """Use a fake CLI that logs operations and enforces post-write verification."""

        self.variables["bitwarden_collection_session"] = "synthetic-current-session"
        cli = self.fixture / "bin/bw"
        cli.write_text(
            f"#!{sys.executable}\n"
            "import base64\nimport json\nimport os\nimport pathlib\nimport sys\n"
            "root = pathlib.Path(os.environ['HOME'])\n"
            "command = sys.argv[1:]\n"
            "with (root / 'bw-calls').open('a') as log: log.write(command[0] + '\\n')\n"
            "store = root / 'saved-item.json'\n"
            "unlocked = os.environ.get('BW_SESSION') == 'synthetic-current-session'\n"
            "if command == ['status']:\n"
            "    print(json.dumps({'status': 'unlocked' if unlocked else 'locked'})); sys.exit(0)\n"
            "if command != ['encode'] and not unlocked: sys.exit(1)\n"
            "if command != ['encode'] and os.environ.get('BW_NOINTERACTION') != 'true': sys.exit(3)\n"
            "if command == ['encode']: print(base64.b64encode(sys.stdin.buffer.read()).decode())\n"
            "elif command[0] in ('create', 'edit'):\n"
            "    item = json.loads(base64.b64decode(sys.stdin.read())); item.setdefault('id', 'fixture-id')\n"
            "    if (root / 'save-fails').exists():\n"
            "        print(json.dumps(item), os.environ['BW_SESSION'], file=sys.stderr); sys.exit(2)\n"
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
                # A token captured before another collection unlock is obsolete.
                "bitwarden_session": "synthetic-stale-session",
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

    def _prepare_native_browser(self) -> tuple[list, dict, pathlib.Path, pathlib.Path]:
        """Load the real Brave adapter against a disposable native profile and vault record."""

        self.prepare_keys()
        tasks = self._prepare_browser(drift=True)
        setup = self.fixture / "collections/ansible_collections/neilime/workstation_setup/roles"
        (setup / "browser_brave").symlink_to(
            WORKSPACE / "ansible/collections/ansible_collections/neilime/workstation_setup/roles/browser_brave",
            target_is_directory=True,
        )
        self.variables["workstation_manager_use_become"] = False
        self.variables["workstation_manager_resolved"] = {
            "desktop": {"browser": "brave"},
            "user": {"name": "fixture", "home": str(self.fixture)},
            "secrets": {"bitwarden": {"browser_profiles_collection_id": "fixture-collection"}},
        }
        record = {
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "Remote",
            "type": 2,
            "notes": "synthetic-recovery-words",
            "collectionIds": ["fixture-collection"],
            "fields": [
                {"name": "id", "value": "fixture"},
                {"name": "directory", "value": "Default"},
                {"name": "theme_colors", "value": "#123456"},
            ],
        }
        store = self.fixture / "saved-item.json"
        (setup / "browser_profile_collection/tasks/main.yml").write_text(
            json.dumps(
                [
                    {
                        "ansible.builtin.set_fact": {
                            "workstation_manager_browser_profiles": "{{ [lookup('ansible.builtin.file', '"
                            + str(store)
                            + "') | from_json] | "
                            "neilime.workstation_setup.bitwarden_browser_profiles }}"
                        },
                        "no_log": True,
                    },
                ]
            )
        )
        root = self.fixture / ".config/BraveSoftware/Brave-Browser"
        (root / "Default").mkdir(parents=True)
        preferences = root / "Default/Preferences"
        return tasks, record, store, preferences

    def test_browser_metadata_directions_reload_and_verify_with_real_adapter(self) -> None:
        """Metadata and Sync-only repairs must finish before live confirmation and archiving."""

        tasks, record, store, preferences = self._prepare_native_browser()
        for direction, sync_only in (("save", False), ("restore", False), ("restore", True)):
            with self.subTest(direction=direction, sync_only=sync_only):
                store.write_text(json.dumps(record))
                local_name = "Remote" if sync_only else "Local"
                (preferences.parent.parent / "Local State").write_text(
                    json.dumps({"profile": {"info_cache": {"Default": {"name": local_name}}}})
                )
                preferences.write_text(
                    json.dumps(
                        {
                            "profile": {"name": local_name},
                            "sync": {"keep_everything_synced": not sync_only},
                            "brave_sync_v2": {"seed": "synthetic-browser-seed"},
                            "browser": {
                                "theme": {"user_color2": int("123456" if sync_only else "654321", 16) - 0x1000000}
                            },
                            "extensions": {"theme": {"id": "user_color_theme_id"}},
                            "pinned_tabs": [{"url": "https://example.invalid"}],
                        }
                    )
                )
                before = json.loads(preferences.read_text())
                code, output = self.run_backup(
                    tasks,
                    (
                        ("[restore/retry/skip/abort]" if sync_only else "[save/restore/retry/skip/abort]", direction),
                        ("[synced/skip/abort]", "synced"),
                    ),
                )
                self.assertEqual(code, 0, output)
                current = json.loads(preferences.read_text())
                saved = json.loads(store.read_text())
                if sync_only:
                    before["sync"]["keep_everything_synced"] = True
                    self.assertEqual(current, before)
                    self.assertEqual(saved, record)
                    self.assertIn("enable Sync everything", output)
                expected = "Local" if direction == "save" else "Remote"
                self.assertEqual(current["profile"]["name"], expected)
                self.assertEqual(saved["name"], expected)
                self.assertEqual(saved["notes"], record["notes"])
                self.assertEqual(current["brave_sync_v2"]["seed"], "synthetic-browser-seed")
                self.assertEqual(current["pinned_tabs"], [{"url": "https://example.invalid"}])
                for secret in ("synthetic-recovery-words", "synthetic-browser-seed", "synthetic-current-session"):
                    self.assertNotIn(secret, output)
                self.assert_archive([])

    def _prepare_locked_browser(self) -> tuple[list, pathlib.Path, pathlib.Path]:
        """Use the real adapter with a disposable, drifted profile and a persistent lock."""

        tasks, record, store, preferences = self._prepare_native_browser()
        record["fields"] = record["fields"][:2]
        store.write_text(json.dumps(record))
        preferences.write_text(
            json.dumps(
                {
                    "profile": {"name": "Local"},
                    "sync": {"keep_everything_synced": False},
                    "brave_sync_v2": {"seed": "synthetic-browser-seed"},
                }
            )
        )
        (preferences.parent.parent / "Local State").write_text(
            json.dumps({"profile": {"info_cache": {"Default": {"name": "Local"}}}})
        )
        lock = preferences.parent.parent / "SingletonLock"
        lock.symlink_to("fixture-browser-lock")
        return tasks, preferences, lock

    def test_locked_browser_retry_requires_fresh_sync_approval(self) -> None:
        """A busy profile offers a safe retry, reloads, and never reuses the previous approval."""

        tasks, preferences, lock = self._prepare_locked_browser()
        before = preferences.read_bytes()
        store = self.fixture / "saved-item.json"
        saved = store.read_bytes()

        def close_browser() -> str:
            self.assertEqual(preferences.read_bytes(), before)
            self.assertEqual(store.read_bytes(), saved)
            self.assertFalse((self.fixture / "backup.tar.gz").exists())
            lock.unlink()
            return "retry"

        code, output = self.run_backup(
            tasks,
            (
                ("[save/restore/retry/skip/abort]", "restore"),
                ("[retry/skip/abort]", "retry"),
                ("[save/restore/retry/skip/abort]", "restore"),
                ("[retry/skip/abort]", close_browser),
                ("[save/restore/retry/skip/abort]", "restore"),
                ("[synced/skip/abort]", "synced"),
            ),
        )
        self.assertEqual(code, 0, output)
        self.assertEqual(output.count("Choose [save/restore/retry/skip/abort]"), 3)
        self.assertIn("profile lock is still present", output)
        self.assertIn("No browser settings or Bitwarden records were changed by this attempt.", output)
        self.assertNotIn("synthetic-browser-seed", output)
        self.assertNotIn("synthetic-recovery-words", output)
        current = json.loads(preferences.read_text())
        self.assertEqual(current["profile"]["name"], "Remote")
        self.assertTrue(current["sync"]["keep_everything_synced"])
        self.assertEqual(store.read_bytes(), saved)
        self.assert_archive([])

    def test_locked_browser_can_abort_or_explicitly_skip_without_changes(self) -> None:
        """Blocked actions cannot produce an archive unless recovery is explicitly skipped."""

        tasks, preferences, lock = self._prepare_locked_browser()
        before = preferences.read_bytes()
        for decision in ("abort", "skip"):
            with self.subTest(decision=decision):
                code, output = self.run_backup(
                    tasks,
                    (("[save/restore/retry/skip/abort]", "save"), ("[retry/skip/abort]", decision)),
                )
                self.assertEqual(preferences.read_bytes(), before)
                self.assertTrue(lock.is_symlink())
                self.assertFalse((self.fixture / "bw-calls").exists())
                self.assertNotIn("Choose [synced/skip/abort]", output)
                if decision == "abort":
                    self.assertNotEqual(code, 0, output)
                    self.assertFalse((self.fixture / "backup.tar.gz").exists())
                else:
                    self.assertEqual(code, 0, output)
                    self.assert_archive(["browser-recovery"])

    def test_browser_write_error_still_stops_backup(self) -> None:
        """The retryable browser guard must not conceal a real filesystem failure."""

        tasks, preferences, lock = self._prepare_locked_browser()
        lock.unlink()

        def break_destination() -> str:
            original = preferences.with_name("fixture-original")
            preferences.rename(original)
            preferences.symlink_to(original)
            return "restore"

        code, output = self.run_backup(tasks, (("[save/restore/retry/skip/abort]", break_destination),))
        self.assertNotEqual(code, 0, output)
        self.assertNotIn("Choose [retry/skip/abort]", output)
        self.assertFalse((self.fixture / "backup.tar.gz").exists())

    def test_remote_key_directions_restore_without_writing_the_vault(self) -> None:
        """Both differing and remote-only SSH keys restore only after the matching explicit choice."""

        tasks = self.prepare_keys()
        tasks[0]["loop"] = tasks[0]["loop"][:1]
        self.variables["workstation_manager_use_become"] = False
        self.variables["workstation_manager_resolved"]["user"] = {"name": "fixture", "home": str(self.fixture)}
        remote = {
            "id": "fixture-id",
            "name": "fixture-key",
            "collectionIds": ["fixture-collection"],
            "fields": [
                {"name": "private_key", "value": "remote-private"},
                {"name": "public_key", "value": "remote-public"},
            ],
        }
        (self.fixture / "saved-item.json").write_text(json.dumps(remote))
        for action, prompt in (
            ("restore", "[restore/skip/abort]"),
            ("update", "[save/restore/skip/abort]"),
        ):
            with self.subTest(action=action):
                tasks[0]["loop"][0]["action"] = action
                code, output = self.run_backup(tasks, ((prompt, "restore"),))
                self.assertEqual(code, 0, output)
                self.assertEqual((self.fixture / ".ssh/fixture-key").read_text(), "remote-private\n")
                self.assertEqual((self.fixture / ".ssh/fixture-key.pub").read_text(), "remote-public\n")
                self.assertNotIn("remote-private", output)
                self.assertEqual(json.loads((self.fixture / "saved-item.json").read_text()), remote)
                (self.fixture / ".ssh/fixture-key").write_text("local change")
        self.assertEqual(
            (self.fixture / "bw-calls").read_text().splitlines(), ["status", "sync", "get", "status", "sync", "get"]
        )

    def test_each_key_can_be_skipped_without_any_vault_write(self) -> None:
        """SSH and GPG skips must not encode, save, or claim to verify a key."""

        code, output = self.run_backup(
            self.prepare_keys(),
            (
                ("[save/skip/abort]", "skip"),
                ("[save/restore/skip/abort]", "skip"),
            ),
        )
        self.assertEqual(code, 0, output)
        self.assertFalse((self.fixture / "bw-calls").exists())
        self.assertNotIn("synthetic-private-key", output)
        self.assertNotIn("synthetic-current-session", output)
        self.assertNotIn("synthetic-stale-session", output)
        self.assert_archive(["ssh-keys", "gpg-keys"])

    def test_key_skip_does_not_skip_the_next_approved_key(self) -> None:
        """A skip applies only to its item and must not suppress another item's verification."""

        code, output = self.run_backup(
            self.prepare_keys(),
            (
                ("[save/skip/abort]", "skip"),
                ("[save/restore/skip/abort]", "save"),
            ),
        )
        self.assertEqual(code, 0, output)
        self.assertEqual(
            (self.fixture / "bw-calls").read_text().splitlines(),
            ["status", "get", "encode", "edit", "sync", "get"],
        )
        self.assert_archive(["ssh-keys"])

    def test_key_verification_failure_after_a_skip_still_stops_backup(self) -> None:
        """Skipping one key cannot turn a failed save of another key into a successful backup."""

        (self.fixture / "bad-readback").touch()
        code, output = self.run_backup(
            self.prepare_keys(),
            (
                ("[save/skip/abort]", "skip"),
                ("[save/restore/skip/abort]", "save"),
            ),
        )
        self.assertNotEqual(code, 0, output)
        self.assertFalse((self.fixture / "backup.tar.gz").exists())
        self.assertNotIn("synthetic-private-key", output)

    def test_approved_keys_use_the_latest_unlocked_session(self) -> None:
        """Deferred SSH and GPG writes must ignore tokens superseded by another unlock."""

        code, output = self.run_backup(
            self.prepare_keys(),
            (("[save/skip/abort]", "save"), ("[save/restore/skip/abort]", "save")),
        )
        self.assertEqual(code, 0, output)
        self.assertEqual(
            (self.fixture / "bw-calls").read_text().splitlines(),
            ["status", "encode", "create", "sync", "get", "status", "get", "encode", "edit", "sync", "get"],
        )
        for sensitive in ("synthetic-private-key", "synthetic-current-session", "synthetic-stale-session"):
            self.assertNotIn(sensitive, output)
        self.assert_archive([])

    def test_expired_session_stops_before_saving_with_a_safe_error(self) -> None:
        """An invalidated session must fail clearly without exposing keys or tokens."""

        tasks = self.prepare_keys()
        self.variables["bitwarden_collection_session"] = "synthetic-expired-session"
        code, output = self.run_backup(tasks, (("[save/skip/abort]", "save"),))
        self.assertNotEqual(code, 0, output)
        self.assertIn("Bitwarden session is locked or expired", output)
        self.assertEqual((self.fixture / "bw-calls").read_text().splitlines(), ["status"])
        self.assertFalse((self.fixture / "backup.tar.gz").exists())
        self.assertNotIn("synthetic-private-key", output)
        self.assertNotIn("synthetic-expired-session", output)

    def test_failed_key_save_still_stops_backup_without_reporting_a_change(self) -> None:
        """A valid session cannot hide a rejected save or expose sensitive CLI errors."""

        (self.fixture / "save-fails").touch()
        code, output = self.run_backup(self.prepare_keys(), (("[save/skip/abort]", "save"),))
        self.assertNotEqual(code, 0, output)
        self.assertEqual((self.fixture / "bw-calls").read_text().splitlines(), ["status", "encode", "create"])
        self.assertIn("changed=0", output)
        self.assertFalse((self.fixture / "backup.tar.gz").exists())
        self.assertNotIn("synthetic-private-key", output)
        self.assertNotIn("synthetic-current-session", output)


if __name__ == "__main__":
    unittest.main()
