"""Regression tests for the shell entrypoint's Ansible target context."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ENTRYPOINT_PATH = pathlib.Path(__file__).parents[2] / "workstation.sh"


class AnsibleTargetContextTests(unittest.TestCase):
    """Pass the resolved account and home to every Ansible runner."""

    def test_runners_preserve_resolved_home_and_check_mode(self) -> None:
        """Backup and root actions must agree even when passwd uses a custom home."""
        definitions = ENTRYPOINT_PATH.read_text().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            wrapper = fixture / "wrapper-definitions.sh"
            wrapper.write_text("\n".join(definitions) + "\n")
            commands = {
                "id": '#!/bin/sh\nprintf "%s\n" "$TEST_PROCESS_USER"\n',
                "getent": ('#!/bin/sh\nprintf "runner:x:1000:1000::%s:/bin/sh\n" "$TEST_TARGET_HOME"\n'),
                "sudo": ('#!/bin/sh\nshift\nif [ "${1:-}" = "-u" ]; then shift 2; fi\nexec "$@"\n'),
                "ansible-pull": (
                    f"#!{sys.executable}\n"
                    "import json, os, sys\n"
                    "print(json.dumps({\n"
                    '    "name": os.environ.get("WORKSTATION_MANAGER_USER"),\n'
                    '    "home": os.environ.get("WORKSTATION_MANAGER_USER_HOME"),\n'
                    '    "collections": os.environ.get("ANSIBLE_COLLECTIONS_PATH"),\n'
                    '    "args": sys.argv[1:],\n'
                    "}))\n"
                ),
            }
            for name, content in commands.items():
                (fixture / name).write_text(content)
                (fixture / name).chmod(0o700)

            for target_home in ("/home/runner", "/home/runner.guest"):
                for runner, process_user, dry_run in (
                    ("user", "runner", "0"),
                    ("root", "runner", "0"),
                    ("user", "root", "1"),
                ):
                    with self.subTest(home=target_home, runner=runner, process_user=process_user):
                        environment = {
                            "PATH": f"{fixture}:/usr/bin:/bin",
                            "HOME": target_home if process_user == "runner" else "/root",
                            "USER": process_user,
                            "TEST_PROCESS_USER": process_user,
                            "TEST_TARGET_HOME": target_home,
                        }
                        if process_user == "root":
                            environment["SUDO_USER"] = "runner"
                        result = subprocess.run(
                            [
                                "/bin/sh",
                                "-c",
                                '. "$1"\n'
                                "has_interactive_terminal() { return 1; }\n"
                                'run_ansible_pull "$2" ansible/backup.yml "$3"',
                                "entrypoint-test",
                                str(wrapper),
                                runner,
                                dry_run,
                            ],
                            env=environment,
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        invocation = json.loads(result.stdout)
                        self.assertEqual(invocation["name"], "runner")
                        self.assertEqual(invocation["home"], target_home)
                        self.assertEqual(
                            invocation["collections"],
                            f"{target_home}/.ansible/collections:/usr/share/ansible/collections",
                        )
                        self.assertIn("ansible/backup.yml", invocation["args"])
                        self.assertEqual("--check" in invocation["args"], dry_run == "1")
                        self.assertEqual("--diff" in invocation["args"], dry_run == "1")


if __name__ == "__main__":
    unittest.main()
