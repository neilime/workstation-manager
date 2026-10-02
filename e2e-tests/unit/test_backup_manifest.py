"""Exercise manifest accumulation across browser export and filesystem backup."""

from __future__ import annotations

import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import unittest

WORKSPACE = pathlib.Path(__file__).parents[2]


class BackupManifestTests(unittest.TestCase):
    """Run the production export and state roles with isolated workstation files."""

    def setUp(self) -> None:
        """Create local profile and project inputs without credentials or live recovery."""

        # enterContext removes each fixture even when an assertion fails.
        # pylint: disable-next=consider-using-with
        fixture = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        projects = fixture / "Documents/dev-projects"
        projects.mkdir(parents=True)
        (projects / "project.txt").write_text("fixture project\n")
        self.output = fixture / "backup"
        self.output.mkdir()
        browser_root = fixture / ".config/BraveSoftware/Brave-Browser"
        profile = browser_root / "Default"
        profile.mkdir(parents=True)
        (profile / "Bookmarks").write_text(json.dumps({"roots": {"bookmark_bar": {"children": []}}}))
        (profile / "Preferences").write_text(json.dumps({"profile": {"name": "Fixture"}}))
        (fixture / "ansible.cfg").write_text("[defaults]\n")
        self.archive = self.output / "workstation-manager-backup-fixture.tar.gz"
        self.browser_export = self.archive.with_suffix("").with_suffix(".browser-profiles.json")
        self.inventory = self.archive.with_suffix("").with_suffix(".git-repositories.json")
        self.restore_command = self.archive.with_suffix("").with_suffix(".restore-command.txt")
        self.expected_lines = [
            f"include\tdev-projects\t{projects}",
            f"missing\tworkstation-manager-user-config\t{fixture / '.config/workstation-manager'}",
        ]
        self.playbook = fixture / "playbook.json"
        self.environment = {
            "PATH": os.environ["PATH"],
            "HOME": str(fixture),
            "ANSIBLE_HOME": str(fixture / ".ansible"),
            "ANSIBLE_CONFIG": str(fixture / "ansible.cfg"),
            "ANSIBLE_COLLECTIONS_PATH": f"{WORKSPACE / 'ansible/collections'}:"
            + os.environ.get("ANSIBLE_COLLECTIONS_PATH", "/opt/ansible/collections"),
            "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR": str(self.output),
        }

    def _assert_backup(self, profiles_present: bool, check: bool) -> None:
        """Run the real workflow and compare the manifest with the generated artifacts."""

        expected_lines = self.expected_lines.copy()
        if profiles_present:
            expected_lines.append(f"export\tbrowser-profiles\t{self.browser_export}")
        expected_lines.append(f"export\tgit-repositories\t{self.inventory}")
        expected_lines.append(f"export\trestore-command\t{self.restore_command}")
        self.playbook.write_text(
            json.dumps(
                [
                    {
                        "hosts": "localhost",
                        "gather_facts": False,
                        "vars": {
                            "ansible_python_interpreter": sys.executable,
                            "workstation_backup_timestamp": "fixture",
                            "workstation_manager_resolved": {
                                "user": {"home": str(self.playbook.parent)},
                                "desktop": {"browser": "brave"},
                            },
                            "workstation_backup_browser_user_data_dir": str(
                                self.playbook.parent / ".config/BraveSoftware/Brave-Browser"
                            ),
                            "workstation_backup_browser_inspection": {
                                "profiles": [{"directory": "Default", "label": "Fixture"}] if profiles_present else [],
                            },
                            "fixture_expected_manifest_lines": expected_lines,
                        },
                        "tasks": [
                            {"ansible.builtin.assert": {"that": "workstation_backup_manifest_lines is not defined"}},
                            {
                                "ansible.builtin.import_role": {
                                    "name": "neilime.workstation_backup.state",
                                    "tasks_from": "prepare",
                                }
                            },
                            {
                                "ansible.builtin.import_role": {
                                    "name": "neilime.workstation_backup.browser",
                                    "tasks_from": "export",
                                }
                            },
                            {"ansible.builtin.import_role": {"name": "neilime.workstation_backup.state"}},
                            {
                                "ansible.builtin.assert": {
                                    "that": "workstation_backup_manifest_lines == fixture_expected_manifest_lines"
                                }
                            },
                        ],
                    }
                ]
            )
        )
        command = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(self.playbook)]
        if check:
            command.append("--check")
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=self.playbook.parent,
            timeout=60,
            check=False,
            env=self.environment,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if check:
            self.assertNotIn("Creating backup archive:", result.stdout)
            self.assertEqual(list(self.output.iterdir()), [])
            return
        self.assertIn("Creating backup archive: preparing files, elapsed 00:00", result.stdout)
        self.assertRegex(result.stdout, r"Creating backup archive: [0-9.]+ MiB written, elapsed [0-9:]+")
        self.assertEqual(
            self.archive.with_suffix("").with_suffix(".manifest.txt").read_text().splitlines(),
            ["created_at\tfixture", f"archive\t{self.archive}", "dry_run\t0"] + expected_lines,
        )
        self.assertTrue(self.inventory.is_file())
        self.assertTrue(self.restore_command.is_file())
        self.assertEqual(self.browser_export.is_file(), profiles_present)
        if profiles_present:
            export = json.loads(self.browser_export.read_text())
            self.assertEqual(export["profiles"][0]["directory"], "Default")
            self.assertEqual(self.browser_export.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.archive.is_file())
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.restore_command.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            self.restore_command.read_text(),
            "wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh"
            f" | WORKSTATION_MANAGER_RESTORE_ARCHIVE={shlex.quote(str(self.archive))} sh -s -- setup\n",
        )

    def test_browser_export_survives_repeated_preparation(self) -> None:
        """The manifest must retain the browser sidecar through filesystem planning."""

        self._assert_backup(profiles_present=True, check=False)

    def test_browser_export_preview_creates_no_artifacts(self) -> None:
        """Check mode must accumulate the browser entry without writing backup files."""

        self._assert_backup(profiles_present=True, check=True)

    def test_no_profiles_omit_the_browser_manifest_entry(self) -> None:
        """An absent browser export must not leave a phantom sidecar record."""

        self._assert_backup(profiles_present=False, check=False)

    def test_no_profiles_preview_creates_no_artifacts(self) -> None:
        """A preview without browser profiles must keep its manifest plan valid."""

        self._assert_backup(profiles_present=False, check=True)

    def test_ignored_dependency_repository_is_omitted_from_inventory(self) -> None:
        """The full role must ignore a nested dependency before trying to read its missing HEAD."""

        repository = self.playbook.parent / "Documents/dev-projects/open-source/twbs-helper-module"
        repository.mkdir(parents=True)
        (repository / ".gitignore").write_text("tools/vendor/\n")
        dependency = repository / "tools/vendor/phpstan/extension-installer"
        for arguments in (
            ["init", "--initial-branch=main", str(repository)],
            ["-C", str(repository), "add", ".gitignore"],
            [
                "-C",
                str(repository),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-m",
                "Initial",
            ],
            ["init", "--initial-branch=main", str(dependency)],
        ):
            subprocess.run(["git", *arguments], env=self.environment, check=True, capture_output=True)
        self._assert_backup(profiles_present=False, check=False)
        inventory = json.loads(self.inventory.read_text())
        self.assertEqual([record["relative_path"] for record in inventory], ["open-source/twbs-helper-module"])


if __name__ == "__main__":
    unittest.main()
