"""Regression tests for the shell entrypoint's target context and prompts."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from entrypoint_test_helpers import (
    entrypoint_source_with_mock_controller,
    sudo_passthrough_script,
)

ENTRYPOINT_PATH = pathlib.Path(__file__).parents[2] / "workstation.sh"


class EntrypointSourceTests(unittest.TestCase):
    """Resolve shell source without mistaking the piped interpreter for it."""

    def test_piped_source_does_not_resolve_the_shell_executable(self) -> None:
        """Both shell names and absolute interpreter paths must reject the binary."""

        definitions = entrypoint_source_with_mock_controller().rsplit('main "$@"', 1)[0]
        for interpreter in ("sh", "/bin/sh"):
            with self.subTest(interpreter=interpreter):
                result = subprocess.run(
                    [interpreter, "-s"],
                    input=definitions + "resolve_entrypoint_source\n",
                    env={"PATH": "/usr/bin:/bin"},
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")

    def test_shell_quoting_preserves_literal_values(self) -> None:
        """Generated assignments must retain quotes, whitespace, and shell metacharacters."""

        definitions = entrypoint_source_with_mock_controller().rsplit('main "$@"', 1)[0]
        for value in (
            "",
            "a'b",
            "'",
            "two''quotes",
            "spaces $HOME `false` $(false) \\\nnext line\n",
        ):
            with self.subTest(value=value):
                result = subprocess.run(
                    ["/bin/sh", "-s"],
                    input=definitions + 'eval "value=$(shell_quote "$TEST_QUOTE_VALUE")"\nprintf "%s" "$value"\n',
                    env={"PATH": "/usr/bin:/bin", "TEST_QUOTE_VALUE": value},
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, value)

    def test_piped_local_source_uses_the_configured_checkout(self) -> None:
        """A local repository override must prepare its source without downloading it."""

        definitions = entrypoint_source_with_mock_controller().rsplit('main "$@"', 1)[0]
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            (fixture / "workstation.sh").write_text(entrypoint_source_with_mock_controller())
            output = fixture / "definitions.sh"
            result = subprocess.run(
                ["/bin/sh", "-s"],
                input=definitions + 'prepare_entrypoint_definitions "$TEST_DEFINITIONS_FILE"\n',
                env={
                    "PATH": "/usr/bin:/bin",
                    "REPOSITORY_URL": str(fixture),
                    "REPOSITORY_BRANCH": "fixture-ref",
                    "TEST_DEFINITIONS_FILE": str(output),
                },
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(output.read_text(), definitions)


class AnsibleTargetContextTests(unittest.TestCase):
    """Authenticate the controller while preserving the managed account and home."""

    def test_actions_preserve_resolved_home_and_check_mode(self) -> None:
        """Every action must preserve the target context when passwd uses a custom home."""
        definitions = entrypoint_source_with_mock_controller().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            wrapper = fixture / "wrapper-definitions.sh"
            wrapper.write_text("\n".join(definitions) + "\n")
            commands = {
                "id": '#!/bin/sh\nprintf "%s\n" "$TEST_PROCESS_USER"\n',
                "getent": ('#!/bin/sh\nprintf "runner:x:1000:1000::%s:/bin/sh\n" "$TEST_TARGET_HOME"\n'),
                "sudo": (
                    "#!/bin/sh\nshift\n"
                    "export TEST_CONTROLLER_PRIVILEGED=1\n"
                    "unset WORKSTATION_MANAGER_BACKUP_EXTRA_PATHS WORKSTATION_MANAGER_RESTORE_ARCHIVE SSH_AUTH_SOCK\n"
                    'exec "$@"\n'
                ),
                "ansible-pull": (
                    f"#!{sys.executable}\n"
                    "import json, os, sys\n"
                    "print(json.dumps({\n"
                    '    "name": os.environ.get("WORKSTATION_MANAGER_USER"),\n'
                    '    "home": os.environ.get("WORKSTATION_MANAGER_USER_HOME"),\n'
                    '    "collections": os.environ.get("ANSIBLE_COLLECTIONS_PATH"),\n'
                    '    "args": sys.argv[1:],\n'
                    '    "privileged": os.environ.get("TEST_CONTROLLER_PRIVILEGED"),\n'
                    '    "extra_paths": os.environ.get("WORKSTATION_MANAGER_BACKUP_EXTRA_PATHS"),\n'
                    '    "ssh_auth_sock": os.environ.get("SSH_AUTH_SOCK"),\n'
                    '    "restore_archive": os.environ.get("WORKSTATION_MANAGER_RESTORE_ARCHIVE"),\n'
                    "}))\n"
                ),
            }
            for name, content in commands.items():
                (fixture / name).write_text(content)
                (fixture / name).chmod(0o700)

            for target_home in ("/home/runner", "/home/runner.guest"):
                for action, process_user, dry_run in (
                    ("backup", "runner", "0"),
                    ("backup", "root", "1"),
                    ("setup", "runner", "0"),
                    ("cleanup", "runner", "1"),
                ):
                    with self.subTest(home=target_home, action=action, process_user=process_user):
                        environment = {
                            "PATH": f"{fixture}:/usr/bin:/bin",
                            "HOME": target_home if process_user == "runner" else "/root",
                            "USER": process_user,
                            "TEST_PROCESS_USER": process_user,
                            "TEST_TARGET_HOME": target_home,
                            "WORKSTATION_MANAGER_BACKUP_EXTRA_PATHS": "~/notes:/mnt/project files",
                            "WORKSTATION_MANAGER_RESTORE_ARCHIVE": "/mnt/backup's archive.tar.gz",
                            "SSH_AUTH_SOCK": "/tmp/fixture-ssh-agent",
                        }
                        if process_user == "root":
                            environment["SUDO_USER"] = "runner"
                        result = subprocess.run(
                            [
                                "/bin/sh",
                                "-c",
                                (
                                    '. "$1"\n'
                                    "has_interactive_terminal() { return 1; }\n"
                                    "prepare_action_dependencies() { :; }\n"
                                    "prepare_bitwarden_credentials() { :; }\n"
                                    "prompt_for_backup_output_dir_if_needed() { :; }\n"
                                    'run_action "$2" "$3"'
                                ),
                                "entrypoint-test",
                                str(wrapper),
                                action,
                                dry_run,
                            ],
                            env=environment,
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        invocation = json.loads(result.stdout.splitlines()[-1])
                        self.assertEqual(invocation["name"], "runner")
                        self.assertEqual(invocation["home"], target_home)
                        self.assertEqual(
                            invocation["collections"],
                            f"{target_home}/.ansible/collections:/usr/share/ansible/collections",
                        )
                        self.assertEqual(invocation["privileged"], "1")
                        self.assertEqual(invocation["ssh_auth_sock"], "/tmp/fixture-ssh-agent")
                        if action == "backup":
                            self.assertEqual(invocation["extra_paths"], "~/notes:/mnt/project files")
                        if action == "setup":
                            self.assertEqual(invocation["restore_archive"], "/mnt/backup's archive.tar.gz")
                        else:
                            self.assertIsNone(invocation["restore_archive"])
                        self.assertIn(f"ansible/{action}.yml", invocation["args"])
                        self.assertEqual("--check" in invocation["args"], dry_run == "1")
                        self.assertEqual("--diff" in invocation["args"], dry_run == "1")


class RepositorySourceTests(unittest.TestCase):
    """Prefer the local checkout when the entrypoint runs from a repository clone."""

    def test_local_entrypoint_defaults_to_local_repo_and_branch(self) -> None:
        """Without an explicit repository URL, the entrypoint should use its own checkout and current branch."""

        definitions = entrypoint_source_with_mock_controller().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            repository = fixture / "repository"
            (repository / "ansible/collections").mkdir(parents=True)
            (repository / "ansible/collections/requirements.yml").write_text("collections: []\n")
            wrapper = repository / "workstation.sh"
            wrapper.write_text("\n".join(definitions) + "\n")
            git = fixture / "git"
            git.write_text(
                "#!/bin/sh\n"
                'if [ "$1" = "-C" ]; then\n'
                '  directory="$2"\n'
                "  shift 2\n"
                "fi\n"
                'case "$1 $2" in\n'
                '  "rev-parse --show-toplevel") printf "%s\\n" "$TEST_REPO_ROOT" ;;\n'
                '  "branch --show-current") printf "%s\\n" "fixture-branch" ;;\n'
                '  "rev-parse HEAD") printf "%s\\n" "0123456789abcdef0123456789abcdef01234567" ;;\n'
                "  *) exit 99 ;;\n"
                "esac\n"
            )
            git.chmod(0o700)
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    (
                        '. "$1"\n'
                        'REPOSITORY_URL=""\n'
                        'REPOSITORY_BRANCH=""\n'
                        "initialize_repository_source\n"
                        'printf "%s\\n%s\\n" "$REPOSITORY_URL" "$REPOSITORY_BRANCH"\n'
                    ),
                    "entrypoint-test",
                    str(wrapper),
                ],
                env={
                    "PATH": f"{fixture}:/usr/bin:/bin",
                    "HOME": temporary_dir,
                    "TEST_REPO_ROOT": str(repository),
                    "WORKSTATION_MANAGER_ENTRYPOINT_SOURCE": str(wrapper),
                },
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.stdout.splitlines(), [str(repository), "fixture-branch"])

    def test_local_repository_requirements_use_local_manifest(self) -> None:
        """A local repository URL should install collection requirements from the local checkout."""

        definitions = entrypoint_source_with_mock_controller().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            repository = fixture / "repository"
            requirements = repository / "ansible/collections/requirements.yml"
            requirements.parent.mkdir(parents=True)
            requirements.write_text("collections: []\n")
            wrapper = fixture / "wrapper-definitions.sh"
            wrapper.write_text("\n".join(definitions) + "\n")
            ansible_galaxy_log = fixture / "ansible-galaxy.log"
            ansible_galaxy = fixture / "ansible-galaxy"
            ansible_galaxy.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >"$TEST_ANSIBLE_GALAXY_LOG"\n')
            ansible_galaxy.chmod(0o700)
            curl = fixture / "curl"
            curl.write_text("#!/bin/sh\nexit 99\n")
            curl.chmod(0o700)
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    (
                        '. "$1"\n'
                        'REPOSITORY_URL="$2"\n'
                        'COLLECTIONS_INSTALL_DIR="/tmp/collections"\n'
                        "install_collection_requirements\n"
                    ),
                    "entrypoint-test",
                    str(wrapper),
                    str(repository),
                ],
                env={
                    "PATH": f"{fixture}:/usr/bin:/bin",
                    "HOME": temporary_dir,
                    "TEST_ANSIBLE_GALAXY_LOG": str(ansible_galaxy_log),
                },
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.stderr, "")
            self.assertIn(f"collection install -r {requirements} -p /tmp/collections", ansible_galaxy_log.read_text())

    def test_local_repository_runs_playbook_from_worktree(self) -> None:
        """A local repository source should run ansible-playbook from the working tree."""

        definitions = entrypoint_source_with_mock_controller().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            repository = fixture / "repository"
            (repository / "ansible").mkdir(parents=True)
            (repository / "ansible/backup.yml").write_text("[]\n")
            wrapper = fixture / "wrapper-definitions.sh"
            wrapper.write_text("\n".join(definitions) + "\n")
            commands = {
                "id": '#!/bin/sh\nprintf "%s\n" "$TEST_PROCESS_USER"\n',
                "getent": ('#!/bin/sh\nprintf "runner:x:1000:1000::%s:/bin/sh\n" "$TEST_TARGET_HOME"\n'),
                "sudo": sudo_passthrough_script("export TEST_CONTROLLER_PRIVILEGED=1\n"),
                "ansible-playbook": (
                    f"#!{sys.executable}\n"
                    "import json, os, sys\n"
                    "print(json.dumps({\n"
                    '    "cwd": os.getcwd(),\n'
                    '    "args": sys.argv[1:],\n'
                    "}))\n"
                ),
                "ansible-pull": "#!/bin/sh\nexit 99\n",
            }
            for name, content in commands.items():
                command = fixture / name
                command.write_text(content)
                command.chmod(0o700)

            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    (
                        '. "$1"\n'
                        'REPOSITORY_URL="$2"\n'
                        'REPOSITORY_BRANCH="feature/local-fix"\n'
                        "run_ansible_pull ansible/backup.yml 0\n"
                    ),
                    "entrypoint-test",
                    str(wrapper),
                    str(repository),
                ],
                env={
                    "PATH": f"{fixture}:/usr/bin:/bin",
                    "HOME": temporary_dir,
                    "USER": "runner",
                    "TEST_PROCESS_USER": "runner",
                    "TEST_TARGET_HOME": "/home/runner",
                },
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            invocation = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual(invocation["cwd"], str(repository))
            self.assertIn(str(repository / "ansible/backup.yml"), invocation["args"])

    def test_run_ansible_pull_exports_interactive_tty_path(self) -> None:
        """Interactive runs should forward the resolved TTY path to Ansible."""

        definitions = entrypoint_source_with_mock_controller().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            repository = fixture / "repository"
            (repository / "ansible").mkdir(parents=True)
            (repository / "ansible/backup.yml").write_text("[]\n")
            wrapper = fixture / "wrapper-definitions.sh"
            wrapper.write_text("\n".join(definitions) + "\n")
            commands = {
                "id": '#!/bin/sh\nprintf "%s\n" "$TEST_PROCESS_USER"\n',
                "getent": ('#!/bin/sh\nprintf "runner:x:1000:1000::%s:/bin/sh\n" "$TEST_TARGET_HOME"\n'),
                "sudo": sudo_passthrough_script("export TEST_CONTROLLER_PRIVILEGED=1\n"),
                "ansible-playbook": (
                    f"#!{sys.executable}\n"
                    "import json, os, sys\n"
                    "print(json.dumps({\n"
                    '    "cwd": os.getcwd(),\n'
                    '    "args": sys.argv[1:],\n'
                    '    "tty": os.environ.get("WORKSTATION_MANAGER_TTY", ""),\n'
                    "}))\n"
                ),
                "ansible-pull": "#!/bin/sh\nexit 99\n",
            }
            for name, content in commands.items():
                command = fixture / name
                command.write_text(content)
                command.chmod(0o700)

            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    (
                        '. "$1"\n'
                        'interactive_terminal_flag() { printf "%s\\n" "1"; }\n'
                        'interactive_terminal_path() { printf "%s\\n" "/dev/pts/fake"; }\n'
                        'REPOSITORY_URL="$2"\n'
                        'REPOSITORY_BRANCH="feature/local-fix"\n'
                        "run_ansible_pull ansible/backup.yml 0\n"
                    ),
                    "entrypoint-test",
                    str(wrapper),
                    str(repository),
                ],
                env={
                    "PATH": f"{fixture}:/usr/bin:/bin",
                    "HOME": temporary_dir,
                    "USER": "runner",
                    "TEST_PROCESS_USER": "runner",
                    "TEST_TARGET_HOME": "/home/runner",
                },
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            invocation = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual(invocation["tty"], "/dev/pts/fake")


class BitwardenRetryTests(unittest.TestCase):
    """Retry interactive Bitwarden auth without leaking credentials."""

    def test_retry_helper_reprompts_after_rejected_email_password(self) -> None:
        """A rejected interactive login should prompt again and rerun with the replacement values."""

        definitions = entrypoint_source_with_mock_controller().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            wrapper = fixture / "wrapper-definitions.sh"
            wrapper.write_text("\n".join(definitions) + "\n")
            attempt_file = fixture / "attempt.txt"
            records_file = fixture / "records.txt"
            prompt_count_file = fixture / "prompt-count.txt"
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    (
                        '. "$1"\n'
                        "has_interactive_terminal() { return 0; }\n"
                        "prompt_for_required_value() {\n"
                        "  prompt_count=0\n"
                        '  if [ -f "$TEST_PROMPT_COUNT_FILE" ]; then\n'
                        '    prompt_count="$(cat "$TEST_PROMPT_COUNT_FILE")"\n'
                        "  fi\n"
                        "  prompt_count=$((prompt_count + 1))\n"
                        '  printf "%s\\n" "$prompt_count" >"$TEST_PROMPT_COUNT_FILE"\n'
                        '  case "$prompt_count" in\n'
                        '    1) printf "%s" "first@example.com" ;;\n'
                        '    2) printf "%s" "first-password" ;;\n'
                        '    3) printf "%s" "second@example.com" ;;\n'
                        '    4) printf "%s" "second-password" ;;\n'
                        "    *) return 99 ;;\n"
                        "  esac\n"
                        "}\n"
                        "run_ansible_pull() {\n"
                        "  attempt=0\n"
                        '  if [ -f "$TEST_ATTEMPT_FILE" ]; then\n'
                        '    attempt="$(cat "$TEST_ATTEMPT_FILE")"\n'
                        "  fi\n"
                        "  attempt=$((attempt + 1))\n"
                        '  printf "%s\\n" "$attempt" >"$TEST_ATTEMPT_FILE"\n'
                        '  printf "%s|%s\\n" "$PROMPTED_BITWARDEN_EMAIL" '
                        '"$BITWARDEN_PASSWORD_VALUE" >>"$TEST_RECORDS_FILE"\n'
                        '  if [ "$attempt" -eq 1 ]; then\n'
                        '    printf "%s\\n" "WORKSTATION_MANAGER_BITWARDEN_EMAIL_PASSWORD_REJECTED: '
                        'synthetic rejection"\n'
                        "    return 2\n"
                        "  fi\n"
                        '  printf "%s\\n" "synthetic success"\n'
                        "}\n"
                        'PROMPTED_BITWARDEN_EMAIL="$(prompt_for_required_value '
                        'BITWARDEN_EMAIL "Bitwarden email: " 0)"\n'
                        'BITWARDEN_PASSWORD_VALUE="$(prompt_for_required_value '
                        'BITWARDEN_PASSWORD "Bitwarden vault password: " 1)"\n'
                        "run_ansible_pull_with_bitwarden_retry ansible/setup.yml 0\n"
                    ),
                    "entrypoint-test",
                    str(wrapper),
                ],
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": temporary_dir,
                    "TEST_ATTEMPT_FILE": str(attempt_file),
                    "TEST_RECORDS_FILE": str(records_file),
                    "TEST_PROMPT_COUNT_FILE": str(prompt_count_file),
                    "WORKSTATION_MANAGER_DISABLE_SCRIPT_CAPTURE": "1",
                },
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                records_file.read_text().splitlines(),
                [
                    "first@example.com|first-password",
                    "second@example.com|second-password",
                ],
            )
            self.assertEqual(prompt_count_file.read_text().strip(), "4")
            self.assertIn("Bitwarden rejected the supplied email or password; prompting again", result.stdout)
            self.assertIn("synthetic success", result.stdout)


if __name__ == "__main__":
    unittest.main()
