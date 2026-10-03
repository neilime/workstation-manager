"""Exercise VS Code launcher installation and invocation without installing an editor."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from ansible.parsing.dataloader import DataLoader

COLLECTIONS_PATH = pathlib.Path(__file__).parents[2] / "ansible" / "collections"
ROLE_PATH = COLLECTIONS_PATH / "ansible_collections/neilime/workstation_setup/roles/development_tooling"


class EditorCliRoleTests(unittest.TestCase):
    """A terminal launcher must preserve arguments, failures, and existing commands."""

    def setUp(self) -> None:
        """Redirect system destinations to a temporary fixture and provide a fake Flatpak."""
        # Isolated role fixtures repeat Ansible play and environment declarations.
        # pylint: disable=duplicate-code
        # pylint: disable-next=consider-using-with
        self.fixture = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.launcher_dir = self.fixture / "bin"
        self.launcher = self.launcher_dir / "code"
        self.stub_dir = self.fixture / "stubs"
        self.stub_dir.mkdir()
        flatpak = self.stub_dir / "flatpak"
        flatpak.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "print(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd(),\n"
            "                  'home': os.environ['HOME'], 'stdin': sys.stdin.read()}))\n"
            "sys.exit(int(os.environ.get('FIXTURE_FLATPAK_STATUS', '0')))\n"
        )
        flatpak.chmod(0o755)
        (self.fixture / "ansible.cfg").write_text("[defaults]\n")
        self.environment = {
            "PATH": os.pathsep.join((str(self.launcher_dir), str(self.stub_dir), os.environ["PATH"])),
            "HOME": str(self.fixture),
            "LC_ALL": "C.UTF-8",
            "ANSIBLE_CONFIG": str(self.fixture / "ansible.cfg"),
            "ANSIBLE_HOME": str(self.fixture / ".ansible"),
            "ANSIBLE_COLLECTIONS_PATH": str(COLLECTIONS_PATH),
        }
        tasks = DataLoader().load_from_file(str(ROLE_PATH / "tasks/editor_cli.yml"))
        for task in tasks:
            if "ansible.builtin.file" in task:
                module_args = task["ansible.builtin.file"]
                module_args["path"] = str(self.launcher_dir)
            else:
                module_args = task["ansible.builtin.copy"]
                module_args["src"] = str(ROLE_PATH / "files" / module_args["src"])
                module_args["dest"] = str(self.launcher)
            module_args["owner"] = str(os.getuid())
            module_args["group"] = str(os.getgid())
        self.task_file = self.fixture / "editor_cli.json"
        self.task_file.write_text(json.dumps(tasks))
        self.last_apply_output = ""
        # pylint: enable=duplicate-code

    def apply(self, *, check: bool = False, editor_packages: list[str] | None = None) -> None:
        """Run the production task import, including its editor selection condition."""
        # Isolated role fixtures repeat Ansible play and environment declarations.
        # pylint: disable=duplicate-code
        import_task = next(
            task
            for task in DataLoader().load_from_file(str(ROLE_PATH / "tasks/main.yml"))
            if task.get("ansible.builtin.import_tasks") == "editor_cli.yml"
        )
        import_task["ansible.builtin.import_tasks"] = str(self.task_file)
        playbook = self.fixture / "playbook.json"
        playbook.write_text(
            json.dumps(
                [
                    {
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "vars": {
                            "ansible_python_interpreter": sys.executable,
                            "workstation_manager_use_become": False,
                            "workstation_manager_resolved": {
                                "development": {
                                    "editor_packages": (
                                        ["com.visualstudio.code"] if editor_packages is None else editor_packages
                                    )
                                }
                            },
                        },
                        "tasks": [import_task],
                    }
                ]
            )
        )
        command = ["ansible-playbook", "--inventory", "localhost,", str(playbook)]
        if check:
            command.append("--check")
        result = subprocess.run(
            command, cwd=self.fixture, env=self.environment, capture_output=True, text=True, check=False, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.last_apply_output = result.stdout
        # pylint: enable=duplicate-code

    def test_installation_exposes_code_and_is_idempotent(self) -> None:
        """Installing twice should expose an executable without reporting repeat changes."""
        self.apply()
        self.assertEqual(self.launcher.stat().st_mode & 0o777, 0o755)
        self.apply()
        self.assertRegex(self.last_apply_output, r"changed=0\s")
        arguments = ["--wait", ".", "project with spaces/file.txt", "literal'$;*.txt", ""]
        result = subprocess.run(
            ["code", *arguments],
            cwd=self.fixture,
            env=self.environment,
            input="editor input\n",
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "args": ["run", "com.visualstudio.code", *arguments],
                "cwd": str(self.fixture),
                "home": str(self.fixture),
                "stdin": "editor input\n",
            },
        )

    def test_launcher_propagates_flatpak_failures(self) -> None:
        """Missing applications and launch failures must remain visible to callers."""
        self.apply()
        result = subprocess.run(
            ["code", "--version"],
            cwd=self.fixture,
            env={**self.environment, "FIXTURE_FLATPAK_STATUS": "17"},
            input="",
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 17)

    def test_fresh_check_mode_does_not_install_a_launcher(self) -> None:
        """A setup preview should leave the command directory untouched."""
        self.apply(check=True)
        self.assertFalse(self.launcher_dir.exists())

    def test_other_editor_selections_do_not_install_a_launcher(self) -> None:
        """An empty list or a different editor must not introduce a VS Code command."""
        for packages in ([], ["other.editor"]):
            with self.subTest(editor_packages=packages):
                self.apply(editor_packages=packages)
                self.assertFalse(self.launcher_dir.exists())

    def test_existing_commands_and_symlinks_are_preserved(self) -> None:
        """A preexisting code command must retain its content, permissions, and target."""
        self.launcher_dir.mkdir()
        original = self.fixture / "existing-code"
        original.write_text("#!/bin/sh\nexit 0\n")
        original.chmod(0o700)
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    self.launcher.symlink_to(original)
                else:
                    self.launcher.write_text(original.read_text())
                    self.launcher.chmod(0o700)
                self.apply()
                self.assertEqual(self.launcher.is_symlink(), symlink)
                self.assertEqual(self.launcher.read_text(), original.read_text())
                self.assertEqual(self.launcher.stat().st_mode & 0o777, 0o700)
                self.launcher.unlink()


if __name__ == "__main__":
    unittest.main()
