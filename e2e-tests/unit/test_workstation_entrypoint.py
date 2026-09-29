"""Regression tests for the shell entrypoint's target context and prompts."""

from __future__ import annotations

import json
import os
import pathlib
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
import unittest

ENTRYPOINT_PATH = pathlib.Path(__file__).parents[2] / "workstation.sh"


class TerminalPromptTests(unittest.TestCase):
    """Keep piped secret prompts private and restore the original terminal mode."""

    def _read_until(self, terminal: int, expected: bytes) -> bytes:
        output = b""
        deadline = time.monotonic() + 5
        while expected not in output:
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, f"Missing prompt: {output!r}")
            ready, _, _ = select.select([terminal], [], [], remaining)
            self.assertTrue(ready, f"Missing prompt: {output!r}")
            output += os.read(terminal, 4096)
        return output

    def _write_prompt_fixture(self, fixture: pathlib.Path) -> pathlib.Path:
        definitions = ENTRYPOINT_PATH.read_text().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        wrapper = fixture / "wrapper-definitions.sh"
        wrapper.write_text("\n".join(definitions) + "\n")
        # Reproduce uutils 0.2.2's rejected saved state even with GNU stty.
        stty = fixture / "stty"
        stty.write_text(
            '#!/bin/sh\ncase "$1" in\n'
            '  *:*) printf "stty: invalid saved state\\n" >&2; exit 1 ;;\n'
            "esac\n"
            'if [ "$1" = "-echo" ]; then printf "%s" "$PPID" >"$TEST_PROMPT_PID_FILE"; fi\n'
            f'exec "{shutil.which("stty")}" "$@"\n'
        )
        stty.chmod(0o700)
        return wrapper

    def _run_prompt(
        self,
        value: bytes,
        *,
        echo_enabled: bool = True,
        interrupt: int | None = None,
        retry_empty: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            master, slave = pty.openpty()
            try:
                original = termios.tcgetattr(slave)
                if echo_enabled:
                    original[3] |= termios.ECHO
                else:
                    original[3] &= ~termios.ECHO
                termios.tcsetattr(slave, termios.TCSANOW, original)

                with subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        "import fcntl, os, sys, termios\n"
                        "with open(sys.argv[1]) as terminal:\n"
                        "    fcntl.ioctl(terminal.fileno(), termios.TIOCSCTTY, 0)\n"
                        'os.execv("/bin/sh", ["sh", "-s", "--", sys.argv[2]])\n',
                        os.ttyname(slave),
                        str(self._write_prompt_fixture(fixture)),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env={
                        "PATH": f"{fixture}:/usr/bin:/bin",
                        "HOME": temporary_dir,
                        "TEST_PROMPT_PID_FILE": str(fixture / "prompt.pid"),
                    },
                    start_new_session=True,
                    text=True,
                ) as process:
                    try:
                        assert process.stdin is not None
                        process.stdin.write(
                            '. "$1"\n'
                            'value="$(prompt_for_required_value TEST_SECRET "Secret: " 1)"\n'
                            'printf "<%s>" "$value"\n'
                        )
                        process.stdin.flush()
                        transcript = self._read_until(master, b"Secret: ")
                        self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO)
                        if retry_empty:
                            os.write(master, b"\n")
                            transcript += self._read_until(master, b"Secret: ")
                        if interrupt is not None:
                            # Signal the reader while its controlling session remains alive.
                            os.kill(int((fixture / "prompt.pid").read_text()), interrupt)
                        else:
                            os.write(master, value)
                        stdout, stderr = process.communicate(timeout=5)
                        while select.select([master], [], [], 0)[0]:
                            transcript += os.read(master, 4096)
                        if value.strip():
                            self.assertNotIn(value.strip(), transcript)
                        self.assertEqual(termios.tcgetattr(slave), original)
                        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
                    finally:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.communicate(timeout=5)
            finally:
                os.close(slave)
                os.close(master)

    def test_secret_prompt_preserves_value_and_terminal_settings(self) -> None:
        """Piped shell input must not consume the password or expose it on the tty."""
        for echo_enabled in (True, False):
            with self.subTest(echo_enabled=echo_enabled):
                result = self._run_prompt(b"  synthetic\\password  \n", echo_enabled=echo_enabled)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "<  synthetic\\password  >")
                self.assertEqual(result.stderr, "")

    def test_empty_secret_reprompts(self) -> None:
        """An empty line should restore the terminal and open another hidden prompt."""
        result = self._run_prompt(b"synthetic-password\n", retry_empty=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "<synthetic-password>")

    def test_eof_restores_terminal_and_fails(self) -> None:
        """Ctrl-D must fail without leaving echo disabled."""
        result = self._run_prompt(b"\x04")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("Failed to read TEST_SECRET", result.stderr)

    def test_interruption_restores_terminal(self) -> None:
        """Interrupting a password prompt must restore the original echo setting."""
        for interrupt in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(interrupt=interrupt):
                result = self._run_prompt(b"", interrupt=interrupt)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")


class AnsibleTargetContextTests(unittest.TestCase):
    """Authenticate the controller while preserving the managed account and home."""

    def test_actions_preserve_resolved_home_and_check_mode(self) -> None:
        """Every action must preserve the target context when passwd uses a custom home."""
        definitions = ENTRYPOINT_PATH.read_text().splitlines()
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
                    "unset WORKSTATION_MANAGER_BACKUP_EXTRA_PATHS SSH_AUTH_SOCK\n"
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
                            "SSH_AUTH_SOCK": "/tmp/fixture-ssh-agent",
                        }
                        if process_user == "root":
                            environment["SUDO_USER"] = "runner"
                        result = subprocess.run(
                            [
                                "/bin/sh",
                                "-c",
                                '. "$1"\n'
                                "has_interactive_terminal() { return 1; }\n"
                                "prepare_action_dependencies() { :; }\n"
                                "prompt_for_bitwarden_credentials_if_needed() { :; }\n"
                                "prompt_for_backup_output_dir_if_needed() { :; }\n"
                                'run_"$2" "$3"',
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
                        self.assertIn(f"ansible/{action}.yml", invocation["args"])
                        self.assertEqual("--check" in invocation["args"], dry_run == "1")
                        self.assertEqual("--diff" in invocation["args"], dry_run == "1")


class RepositorySourceTests(unittest.TestCase):
    """Prefer the local checkout when the entrypoint runs from a repository clone."""

    def test_local_entrypoint_defaults_to_local_repo_and_branch(self) -> None:
        """Without an explicit repository URL, the entrypoint should use its own checkout and current branch."""

        definitions = ENTRYPOINT_PATH.read_text().splitlines()
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
                '  shift 2\n'
                'fi\n'
                'case "$1 $2" in\n'
                '  "rev-parse --show-toplevel") printf "%s\\n" "$TEST_REPO_ROOT" ;;\n'
                '  "branch --show-current") printf "%s\\n" "fixture-branch" ;;\n'
                '  "rev-parse HEAD") printf "%s\\n" "0123456789abcdef0123456789abcdef01234567" ;;\n'
                '  *) exit 99 ;;\n'
                'esac\n'
            )
            git.chmod(0o700)
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$1"\n'
                    'REPOSITORY_URL=""\n'
                    'REPOSITORY_BRANCH=""\n'
                    'initialize_repository_source\n'
                    'printf "%s\\n%s\\n" "$REPOSITORY_URL" "$REPOSITORY_BRANCH"\n',
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

        definitions = ENTRYPOINT_PATH.read_text().splitlines()
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
            ansible_galaxy.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >"$TEST_ANSIBLE_GALAXY_LOG"\n'
            )
            ansible_galaxy.chmod(0o700)
            curl = fixture / "curl"
            curl.write_text("#!/bin/sh\nexit 99\n")
            curl.chmod(0o700)
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$1"\n'
                    'REPOSITORY_URL="$2"\n'
                    'COLLECTIONS_INSTALL_DIR="/tmp/collections"\n'
                    'install_collection_requirements\n',
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

        definitions = ENTRYPOINT_PATH.read_text().splitlines()
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
                "sudo": (
                    "#!/bin/sh\n"
                    'while [ "$#" -gt 0 ]; do\n'
                    '  case "$1" in\n'
                    '    --preserve-env=*) shift; continue ;;\n'
                    '    *) break ;;\n'
                    '  esac\n'
                    'done\n'
                    'export TEST_CONTROLLER_PRIVILEGED=1\n'
                    'exec "$@"\n'
                ),
                "ansible-playbook": (
                    f"#!{sys.executable}\n"
                    "import json, os, sys\n"
                    "print(json.dumps({\n"
                    '    "cwd": os.getcwd(),\n'
                    '    "args": sys.argv[1:],\n'
                    '}))\n'
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
                    '. "$1"\n'
                    'REPOSITORY_URL="$2"\n'
                    'REPOSITORY_BRANCH="feature/local-fix"\n'
                    'run_ansible_pull ansible/backup.yml 0\n',
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


class BitwardenRetryTests(unittest.TestCase):
    """Retry interactive Bitwarden auth without leaking credentials."""

    def test_retry_helper_reprompts_after_rejected_email_password(self) -> None:
        """A rejected interactive login should prompt again and rerun with the replacement values."""

        definitions = ENTRYPOINT_PATH.read_text().splitlines()
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
                    '. "$1"\n'
                    'has_interactive_terminal() { return 0; }\n'
                    'prompt_for_required_value() {\n'
                    '  prompt_count=0\n'
                    '  if [ -f "$TEST_PROMPT_COUNT_FILE" ]; then\n'
                    '    prompt_count="$(cat "$TEST_PROMPT_COUNT_FILE")"\n'
                    '  fi\n'
                    '  prompt_count=$((prompt_count + 1))\n'
                    '  printf "%s\\n" "$prompt_count" >"$TEST_PROMPT_COUNT_FILE"\n'
                    '  case "$prompt_count" in\n'
                    '    1) printf "%s" "first@example.com" ;;\n'
                    '    2) printf "%s" "first-password" ;;\n'
                    '    3) printf "%s" "second@example.com" ;;\n'
                    '    4) printf "%s" "second-password" ;;\n'
                    '    *) return 99 ;;\n'
                    '  esac\n'
                    '}\n'
                    'run_ansible_pull() {\n'
                    '  attempt=0\n'
                    '  if [ -f "$TEST_ATTEMPT_FILE" ]; then\n'
                    '    attempt="$(cat "$TEST_ATTEMPT_FILE")"\n'
                    '  fi\n'
                    '  attempt=$((attempt + 1))\n'
                    '  printf "%s\\n" "$attempt" >"$TEST_ATTEMPT_FILE"\n'
                    '  printf "%s|%s\\n" "$PROMPTED_BITWARDEN_EMAIL" "$BITWARDEN_PASSWORD_VALUE" >>"$TEST_RECORDS_FILE"\n'
                    '  if [ "$attempt" -eq 1 ]; then\n'
                    '    printf "%s\\n" "WORKSTATION_MANAGER_BITWARDEN_EMAIL_PASSWORD_REJECTED: synthetic rejection"\n'
                    '    return 2\n'
                    '  fi\n'
                    '  printf "%s\\n" "synthetic success"\n'
                    '}\n'
                    'PROMPTED_BITWARDEN_EMAIL="$(prompt_for_required_value BITWARDEN_EMAIL "Bitwarden email: " 0)"\n'
                    'BITWARDEN_PASSWORD_VALUE="$(prompt_for_required_value BITWARDEN_PASSWORD "Bitwarden vault password: " 1)"\n'
                    'run_ansible_pull_with_bitwarden_retry ansible/setup.yml 0\n',
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

    def test_script_capture_uses_one_outer_sudo_and_marks_runner_to_skip_nested_sudo(self) -> None:
        """Interactive capture must elevate before allocating its relay terminal."""

        definitions = ENTRYPOINT_PATH.read_text().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            wrapper = fixture / "wrapper-definitions.sh"
            wrapper.write_text("\n".join(definitions) + "\n")
            script_command_file = fixture / "script-command.txt"
            runner_content_file = fixture / "runner-content.txt"
            sudo_log_file = fixture / "sudo-log.txt"
            script_output_file = fixture / "script-output.txt"
            commands = {
                "sudo": (
                    "#!/bin/sh\n"
                    'printf "%s\\n" "$*" >>"$TEST_SUDO_LOG_FILE"\n'
                    'if [ "$1" = "mktemp" ]; then\n'
                    '  shift\n'
                    '  exec mktemp "$@"\n'
                    'fi\n'
                    'if [ "$1" = "cat" ]; then\n'
                    '  shift\n'
                    '  exec cat "$@"\n'
                    'fi\n'
                    'if [ "$1" = "rm" ]; then\n'
                    '  shift\n'
                    '  exec rm "$@"\n'
                    'fi\n'
                    'while [ "$#" -gt 0 ]; do\n'
                    '  case "$1" in\n'
                    '    --preserve-env=*) shift; continue ;; \n'
                    '    *) break ;; \n'
                    '  esac\n'
                    'done\n'
                    'exec "$@"\n'
                ),
                "script": (
                    "#!/bin/sh\n"
                    'command_value=""\n'
                    'output_file=""\n'
                    'while [ "$#" -gt 0 ]; do\n'
                    '  case "$1" in\n'
                    '    --command) command_value="$2"; shift 2; continue ;; \n'
                    '    --quiet|--return) shift; continue ;; \n'
                    '    *) output_file="$1"; shift; continue ;; \n'
                    '  esac\n'
                    'done\n'
                    'printf "%s\\n" "$command_value" >"$TEST_SCRIPT_COMMAND_FILE"\n'
                    'eval "set -- $command_value"\n'
                    'cat "$2" >"$TEST_RUNNER_CONTENT_FILE"\n'
                    'printf "%s\\n" "synthetic success" >"$output_file"\n'
                    'cat "$output_file" >"$TEST_SCRIPT_OUTPUT_FILE"\n'
                    'cat "$output_file"\n'
                ),
            }
            for name, content in commands.items():
                command = fixture / name
                command.write_text(content)
                command.chmod(0o700)

            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$1"\n'
                    'has_interactive_terminal() { return 0; }\n'
                    'TARGET_USER="fixture"\n'
                    'TARGET_USER_HOME="$HOME"\n'
                    'COLLECTIONS_INSTALL_DIR="$HOME/.ansible/collections"\n'
                    'run_ansible_pull_with_bitwarden_retry ansible/backup.yml 0\n',
                    "entrypoint-test",
                    str(wrapper),
                ],
                env={
                    "PATH": f"{fixture}:/usr/bin:/bin",
                    "HOME": temporary_dir,
                    "WORKSTATION_MANAGER_ENTRYPOINT_SOURCE": str(wrapper),
                    "TEST_SCRIPT_COMMAND_FILE": str(script_command_file),
                    "TEST_RUNNER_CONTENT_FILE": str(runner_content_file),
                    "TEST_SCRIPT_OUTPUT_FILE": str(script_output_file),
                    "TEST_SUDO_LOG_FILE": str(sudo_log_file),
                },
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertGreaterEqual(len(sudo_log_file.read_text().splitlines()), 4)
            self.assertIn("script --quiet --return --command", sudo_log_file.read_text())
            self.assertIn("mktemp -d", sudo_log_file.read_text())
            self.assertIn("cat ", sudo_log_file.read_text())
            self.assertIn("rm -rf", sudo_log_file.read_text())
            self.assertIn("WORKSTATION_MANAGER_SKIP_SUDO=1", runner_content_file.read_text())
            self.assertIn("run_ansible_pull 'ansible/backup.yml' '0' \"$@\"", runner_content_file.read_text())
            self.assertEqual(script_output_file.read_text(), "synthetic success\n")


if __name__ == "__main__":
    unittest.main()
