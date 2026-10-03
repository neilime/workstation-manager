"""Regression tests for the shell entrypoint's target context and prompts."""

from __future__ import annotations

import json
import os
import pathlib
import pty
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
import unittest

from backup_prompt_helpers import run_interactive
from entrypoint_test_helpers import controlling_tty_exec_python, sudo_passthrough_script

ENTRYPOINT_PATH = pathlib.Path(__file__).parents[2] / "workstation.sh"


class EntrypointSourceTests(unittest.TestCase):
    """Resolve shell source without mistaking the piped interpreter for it."""

    def test_piped_source_does_not_resolve_the_shell_executable(self) -> None:
        """Both shell names and absolute interpreter paths must reject the binary."""

        definitions = ENTRYPOINT_PATH.read_text().rsplit('main "$@"', 1)[0]
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

        definitions = ENTRYPOINT_PATH.read_text().rsplit('main "$@"', 1)[0]
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

        definitions = ENTRYPOINT_PATH.read_text().rsplit('main "$@"', 1)[0]
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            shutil.copyfile(ENTRYPOINT_PATH, fixture / "workstation.sh")
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
                        controlling_tty_exec_python('["sh", "-s", "--", sys.argv[2]]'),
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
                    '. "$1"\n'
                    'REPOSITORY_URL=""\n'
                    'REPOSITORY_BRANCH=""\n'
                    "initialize_repository_source\n"
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
            ansible_galaxy.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >"$TEST_ANSIBLE_GALAXY_LOG"\n')
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
                    "install_collection_requirements\n",
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
                    '. "$1"\n'
                    'REPOSITORY_URL="$2"\n'
                    'REPOSITORY_BRANCH="feature/local-fix"\n'
                    "run_ansible_pull ansible/backup.yml 0\n",
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
                    '    printf "%s\\n" "WORKSTATION_MANAGER_BITWARDEN_EMAIL_PASSWORD_REJECTED: synthetic rejection"\n'
                    "    return 2\n"
                    "  fi\n"
                    '  printf "%s\\n" "synthetic success"\n'
                    "}\n"
                    'PROMPTED_BITWARDEN_EMAIL="$(prompt_for_required_value '
                    'BITWARDEN_EMAIL "Bitwarden email: " 0)"\n'
                    'BITWARDEN_PASSWORD_VALUE="$(prompt_for_required_value '
                    'BITWARDEN_PASSWORD "Bitwarden vault password: " 1)"\n'
                    "run_ansible_pull_with_bitwarden_retry ansible/setup.yml 0\n",
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
                "sudo": sudo_passthrough_script(
                    'printf "%s\\n" "$*" >>"$TEST_SUDO_LOG_FILE"\n'
                    'if [ "$1" = "mktemp" ]; then\n'
                    "  shift\n"
                    '  exec mktemp "$@"\n'
                    "fi\n"
                    'if [ "$1" = "cat" ]; then\n'
                    "  shift\n"
                    '  exec cat "$@"\n'
                    "fi\n"
                    'if [ "$1" = "rm" ]; then\n'
                    "  shift\n"
                    '  exec rm "$@"\n'
                    "fi\n"
                ),
                "script": (
                    "#!/bin/sh\n"
                    'command_value=""\n'
                    'output_file=""\n'
                    'while [ "$#" -gt 0 ]; do\n'
                    '  case "$1" in\n'
                    '    --command) command_value="$2"; shift 2; continue ;; \n'
                    "    --quiet|--return) shift; continue ;; \n"
                    '    *) output_file="$1"; shift; continue ;; \n'
                    "  esac\n"
                    "done\n"
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
                    shutil.which("script") or "script",
                    "--quiet",
                    "--return",
                    "--command",
                    shlex.join(
                        [
                            "/bin/sh",
                            "-c",
                            '. "$1"\n'
                            'TARGET_USER="fixture"\n'
                            'TARGET_USER_HOME="$HOME"\n'
                            'COLLECTIONS_INSTALL_DIR="$HOME/.ansible/collections"\n'
                            "run_ansible_pull_with_bitwarden_retry ansible/backup.yml 0\n",
                            "entrypoint-test",
                            str(wrapper),
                        ]
                    ),
                    os.devnull,
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


class GitHubCliAuthenticationTests(unittest.TestCase):
    """Prompt for GitHub CLI authentication with supported flags."""

    def test_prompt_uses_https_login_without_skip_ssh_key_flag(self) -> None:
        """Private override auth should not depend on the removed skip-ssh-key flag."""

        definitions = ENTRYPOINT_PATH.read_text().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            wrapper = fixture / "wrapper-definitions.sh"
            wrapper.write_text("\n".join(definitions) + "\n")
            gh_log = fixture / "gh.log"
            gh = fixture / "gh"
            gh.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >>"$TEST_GH_LOG_FILE"\n'
                'case "$1 $2" in\n'
                '  "auth login") exit 0 ;;\n'
                '  "auth setup-git") exit 0 ;;\n'
                "  *) exit 99 ;;\n"
                "esac\n"
            )
            gh.chmod(0o700)

            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$1"\n'
                    "install_github_cli() { :; }\n"
                    'println_to_tty() { printf "%s\\n" "$1"; }\n'
                    "prompt_for_github_cli_authentication\n",
                    "entrypoint-test",
                    str(wrapper),
                ],
                env={
                    "PATH": f"{fixture}:/usr/bin:/bin",
                    "HOME": temporary_dir,
                    "TEST_GH_LOG_FILE": str(gh_log),
                },
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertIn(
                "Private override access requires GitHub authentication; prompting through GitHub CLI",
                result.stdout,
            )
            self.assertIn(
                "Complete the GitHub CLI login flow. If this machine has no "
                "browser, use the device code on another device.",
                result.stdout,
            )
            self.assertEqual(
                gh_log.read_text().splitlines(),
                ["auth login --git-protocol https", "auth setup-git"],
            )


class PipedBackupTests(unittest.TestCase):
    """Exercise the public piped backup with a real terminal and isolated commands."""

    def _prepare_fixture(self, fixture: pathlib.Path) -> dict[str, str]:
        """Stub dependencies and Ansible while retaining the actual shell and script relay."""

        commands = fixture / "bin"
        commands.mkdir()
        (fixture / "private.override.yml").write_text("{}\n")
        scripts = {
            "sudo": sudo_passthrough_script('if [ "$1" = "-v" ]; then exit 0; fi\n'),
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
                "import json, os, sys\n"
                'print("Fixture recovery confirmation: ", end="", flush=True)\n'
                "answer = sys.stdin.readline().strip()\n"
                'with open(os.environ["TEST_INVOCATION_FILE"], "w") as output:\n'
                "    json.dump({\n"
                '        "args": sys.argv[1:], "answer": answer,\n'
                '        "stdin_tty": sys.stdin.isatty(), "stdout_tty": sys.stdout.isatty(),\n'
                '        "password": os.environ["BITWARDEN_PASSWORD"],\n'
                '        "output_dir": os.environ["WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR"],\n'
                '        "user_home": os.environ["WORKSTATION_MANAGER_USER_HOME"],\n'
                "    }, output)\n"
                'sys.exit(0 if answer == "continue" else 9)\n'
            ),
        }
        for name, content in scripts.items():
            command = commands / name
            command.write_text(content)
            command.chmod(0o700)
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
            "TEST_ENTRYPOINT_FILE": str(ENTRYPOINT_PATH),
            "TEST_DOWNLOAD_LOG": str(fixture / "downloads.txt"),
            "TEST_INVOCATION_FILE": str(fixture / "invocation.json"),
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
