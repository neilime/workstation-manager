"""Regression tests for piped backups and their interactive terminal relay."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

from backup_prompt_helpers import run_interactive
from entrypoint_test_helpers import (
    entrypoint_source_with_mock_controller,
    sudo_passthrough_script,
)

ENTRYPOINT_PATH = pathlib.Path(__file__).parents[2] / "workstation.sh"


class PipedBackupTests(unittest.TestCase):
    """Exercise the public piped backup with a real terminal and isolated commands."""

    def _prepare_fixture(self, fixture: pathlib.Path) -> dict[str, str]:
        """Stub dependencies and Ansible while retaining the actual shell and script relay."""

        commands = fixture / "bin"
        commands.mkdir()
        (fixture / "private.override.yml").write_text("{}\n")
        scripts = {
            "sudo": sudo_passthrough_script(
                'if [ "$1" = "-v" ]; then exit 0; fi\n'
                'if [ "${TEST_CAPTURE_READ_FAILURE:-0}" = 1 ] && [ "$1" = cat ]; then exit 23; fi\n'
            ),
            "chown": (
                "#!/bin/sh\n"
                'if [ "${TEST_TERMINAL_OWNER_FAILURE:-0}" = "1" ]; then exit 1; fi\n'
                'printf "%s|%s\n" "$2" "$3" >"$TEST_TERMINAL_OWNER_FILE"\n'
            ),
            "git": "#!/bin/sh\nexit 99\n",
            "getent": '#!/bin/sh\nprintf "fixture:x:1000:1000::%s:/bin/sh\\n" "$HOME"\n',
            "ansible-playbook": "#!/bin/sh\nexit 99\n",
            "ansible-galaxy": "#!/bin/sh\nexit 0\n",
            "wget": (
                f"#!{sys.executable}\n"
                "import os, pathlib, shutil, sys\n"
                "arguments = sys.argv[1:]\n"
                "destination = None\n"
                'url = ""\n'
                "index = 0\n"
                "while index < len(arguments):\n"
                "    argument = arguments[index]\n"
                '    if argument == "-q":\n'
                "        index += 1\n"
                "        continue\n"
                '    if argument == "-O":\n'
                "        destination = pathlib.Path(arguments[index + 1])\n"
                "        index += 2\n"
                "        continue\n"
                '    if argument == "--header":\n'
                "        index += 2\n"
                "        continue\n"
                '    if argument.startswith("--header="):\n'
                "        index += 1\n"
                "        continue\n"
                "    url = argument\n"
                "    index += 1\n"
                "if destination is None or not url:\n"
                "    sys.exit(98)\n"
                'with open(os.environ["TEST_DOWNLOAD_LOG"], "a") as log:\n'
                '    log.write(url + "\\n")\n'
                'if url.endswith("/workstation.sh"):\n'
                '    if os.environ.get("TEST_DOWNLOAD_FAILURE") == "1":\n'
                "        sys.exit(4)\n"
                '    if os.environ.get("TEST_INVALID_SOURCE") == "1":\n'
                '        destination.write_text("run_ansible_pull() {\\nunterminated=\\"\\n")\n'
                "    else:\n"
                '        shutil.copyfile(os.environ["TEST_ENTRYPOINT_FILE"], destination)\n'
                'elif url.endswith("/ansible/collections/requirements.yml"):\n'
                '    destination.write_text("collections: []\\n")\n'
                "else:\n"
                "    sys.exit(99)\n"
            ),
            "curl": (
                f"#!{sys.executable}\n"
                "import os, pathlib, shutil, sys\n"
                "arguments = sys.argv[1:]\n"
                "destination = None\n"
                'url = ""\n'
                "index = 0\n"
                "while index < len(arguments):\n"
                "    argument = arguments[index]\n"
                '    if argument == "-o":\n'
                "        destination = pathlib.Path(arguments[index + 1])\n"
                "        index += 2\n"
                "        continue\n"
                '    if argument == "-H":\n'
                "        index += 2\n"
                "        continue\n"
                '    if argument.startswith("-"):\n'
                "        index += 1\n"
                "        continue\n"
                "    url = argument\n"
                "    index += 1\n"
                "if destination is None or not url:\n"
                "    sys.exit(98)\n"
                'with open(os.environ["TEST_DOWNLOAD_LOG"], "a") as log:\n'
                '    log.write(url + "\\n")\n'
                'if url.endswith("/workstation.sh"):\n'
                '    if os.environ.get("TEST_DOWNLOAD_FAILURE") == "1":\n'
                "        sys.exit(22)\n"
                '    if os.environ.get("TEST_INVALID_SOURCE") == "1":\n'
                '        destination.write_text("run_ansible_pull() {\\\\nunterminated=\\\\"\\\\n")\n'
                "    else:\n"
                '        shutil.copyfile(os.environ["TEST_ENTRYPOINT_FILE"], destination)\n'
                'elif url.endswith("/ansible/collections/requirements.yml"):\n'
                '    destination.write_text("collections: []\\\\n")\n'
                "else:\n"
                "    sys.exit(99)\n"
            ),
            "ansible-pull": (
                f"#!{sys.executable}\n"
                "import json, os, subprocess, sys\n"
                'print("Fixture recovery confirmation: ", end="", flush=True)\n'
                "answer = sys.stdin.readline().strip()\n"
                'if os.environ.get("TEST_BITWARDEN_CODE") == "1":\n'
                "    from ansible_collections.neilime.workstation_setup.plugins.module_utils import bitwarden_auth\n"
                "    code = bitwarden_auth._prompt_for_hidden_code(\n"
                "        'Fixture Bitwarden emailed code: ', tty_path=os.environ['WORKSTATION_MANAGER_TTY'])\n"
                "    if code != '654321': sys.exit(8)\n"
                "terminal = subprocess.check_output(\n"
                "    ['ps', '-o', 'tty=', '-p', str(os.getpid())], text=True).strip()\n"
                'with open(os.environ["TEST_INVOCATION_FILE"], "w") as output:\n'
                "    json.dump({\n"
                '        "args": sys.argv[1:], "answer": answer,\n'
                '        "stdin_tty": sys.stdin.isatty(), "stdout_tty": sys.stdout.isatty(),\n'
                '        "password": os.environ["BITWARDEN_PASSWORD"],\n'
                '        "output_dir": os.environ["WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR"],\n'
                '        "user_home": os.environ["WORKSTATION_MANAGER_USER_HOME"],\n'
                '        "prompt_tty": os.environ["WORKSTATION_MANAGER_TTY"], "relay_tty": "/dev/" + terminal,\n'
                "    }, output)\n"
                'sys.exit(0 if answer == "continue" else 9)\n'
            ),
        }
        for name, content in scripts.items():
            command = commands / name
            command.write_text(content)
            command.chmod(0o700)
        entrypoint = fixture / "workstation.sh"
        source = entrypoint_source_with_mock_controller().rsplit('main "$@"', 1)[0]
        # Bootstrap dependency installation is covered separately; these tests exercise the terminal relay.
        entrypoint.write_text(source + '\ninstall_ansible_packages() { :; }\nmain "$@"\n')
        return {
            "PATH": f"{commands}:/usr/bin:/bin",
            "HOME": str(fixture),
            "TMPDIR": str(fixture),
            "SUDO_USER": "fixture",
            "REPOSITORY_URL": "https://github.com/fixture/workstation-manager.git",
            "REPOSITORY_BRANCH": "fixture-ref",
            "WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE": str(fixture / "private.override.yml"),
            "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR": str(fixture / "backup's files"),
            "BITWARDEN_CLIENT_ID": "fixture-client",
            "BITWARDEN_CLIENT_SECRET": "fixture-secret",
            "BITWARDEN_PASSWORD": "fixture'password $HOME `false` $(false)",
            "TEST_ENTRYPOINT_FILE": str(entrypoint),
            "TEST_DOWNLOAD_LOG": str(fixture / "downloads.txt"),
            "TEST_INVOCATION_FILE": str(fixture / "invocation.json"),
            "TEST_TERMINAL_OWNER_FILE": str(fixture / "terminal-owner.txt"),
            "PYTHONPATH": str(ENTRYPOINT_PATH.parent / "ansible/collections"),
        }

    def test_piped_backup_preserves_terminal_credentials_paths_and_check_mode(
        self,
    ) -> None:
        """The downloaded runner must execute backup once with literal values and a tty."""

        for dry_run in (False, True):
            with (
                self.subTest(dry_run=dry_run),
                tempfile.TemporaryDirectory() as temporary_dir,
            ):
                fixture = pathlib.Path(temporary_dir) / "runner's files"
                fixture.mkdir()
                environment = self._prepare_fixture(fixture)
                command = 'cat "$TEST_ENTRYPOINT_FILE" | sh -s -- backup'
                if dry_run:
                    command += " --dry-run"
                returncode, output = run_interactive(
                    ["sh", "-c", command],
                    fixture,
                    environment,
                    [("Fixture recovery confirmation: ", "continue")],
                )
                self.assertEqual(returncode, 0, output)
                invocation = json.loads((fixture / "invocation.json").read_text())
                self.assertEqual(invocation["password"], environment["BITWARDEN_PASSWORD"])
                self.assertEqual(
                    invocation["output_dir"],
                    environment["WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR"],
                )
                self.assertEqual(invocation["user_home"], str(fixture))
                self.assertEqual(invocation["answer"], "continue")
                self.assertTrue(invocation["stdin_tty"])
                self.assertTrue(invocation["stdout_tty"])
                self.assertIn("ansible/backup.yml", invocation["args"])
                self.assertEqual("--check" in invocation["args"], dry_run)
                self.assertEqual("--diff" in invocation["args"], dry_run)
                self.assertEqual(output.count("Running workstation backup from"), 1)
                self.assertIn("Workstation command completed", output)
                self.assertNotIn(environment["BITWARDEN_PASSWORD"], output)
                self.assertEqual(
                    (fixture / "downloads.txt").read_text().splitlines(),
                    [
                        "https://raw.githubusercontent.com/fixture/workstation-manager/fixture-ref/"
                        "ansible/collections/requirements.yml",
                        "https://raw.githubusercontent.com/fixture/workstation-manager/fixture-ref/workstation.sh",
                    ],
                )
                self.assertEqual(list(fixture.glob("workstation-manager-*")), [])

    def test_piped_capture_assigns_prompt_terminal_and_hides_emailed_code(self) -> None:
        """The runner must assign its own terminal before reopening it for hidden input."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            environment = self._prepare_fixture(fixture)
            environment["TEST_BITWARDEN_CODE"] = "1"
            returncode, output = run_interactive(
                ["sh", "-c", 'cat "$TEST_ENTRYPOINT_FILE" | sh -s -- backup'],
                fixture,
                environment,
                [("Fixture recovery confirmation: ", "continue"), ("Fixture Bitwarden emailed code: ", "654321")],
            )
            self.assertEqual(returncode, 0, output)
            invocation = json.loads((fixture / "invocation.json").read_text())
            self.assertEqual(invocation["prompt_tty"], invocation["relay_tty"])
            self.assertEqual(
                (fixture / "terminal-owner.txt").read_text().strip(), f"fixture|{invocation['prompt_tty']}"
            )
            self.assertNotIn("654321", output)

    def test_prompt_terminal_ownership_failure_stops_before_ansible(self) -> None:
        """An inaccessible relay must fail before any authentication or workstation work."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            environment = self._prepare_fixture(fixture)
            environment["TEST_TERMINAL_OWNER_FAILURE"] = "1"
            returncode, output = run_interactive(
                ["sh", "-c", 'cat "$TEST_ENTRYPOINT_FILE" | sh -s -- backup'], fixture, environment
            )
            self.assertNotEqual(returncode, 0)
            self.assertIn("Failed to make the interactive relay terminal accessible", output)
            self.assertFalse((fixture / "invocation.json").exists())

    def test_unreadable_capture_fails_and_removes_temporary_files(self) -> None:
        """Missing retry evidence must fail rather than silently report success."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            environment = self._prepare_fixture(fixture)
            environment["TEST_CAPTURE_READ_FAILURE"] = "1"
            returncode, output = run_interactive(
                ["sh", "-c", 'cat "$TEST_ENTRYPOINT_FILE" | sh -s -- backup'],
                fixture,
                environment,
                [("Fixture recovery confirmation: ", "continue")],
            )
            self.assertNotEqual(returncode, 0, output)
            self.assertIn("Failed to read captured Ansible output", output)
            self.assertNotIn("Workstation command completed", output)
            self.assertEqual(list(fixture.glob("workstation-manager-*")), [])

    def test_unavailable_or_invalid_runner_source_stops_before_ansible(self) -> None:
        """Download and parsing failures must fail clearly and remove temporary source files."""

        for failure in ("TEST_DOWNLOAD_FAILURE", "TEST_INVALID_SOURCE"):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as temporary_dir,
            ):
                fixture = pathlib.Path(temporary_dir)
                environment = self._prepare_fixture(fixture)
                environment[failure] = "1"
                returncode, output = run_interactive(
                    ["sh", "-c", 'cat "$TEST_ENTRYPOINT_FILE" | sh -s -- backup'],
                    fixture,
                    environment,
                )
                self.assertNotEqual(returncode, 0, output)
                self.assertIn(
                    "Failed to prepare the entrypoint for interactive Ansible execution",
                    output,
                )
                self.assertNotIn("Workstation command completed", output)
                self.assertFalse((fixture / "invocation.json").exists())
                self.assertEqual(list(fixture.glob("workstation-manager-*")), [])


if __name__ == "__main__":
    unittest.main()
