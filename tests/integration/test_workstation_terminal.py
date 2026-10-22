"""Exercise real terminal prompts, capture, and privilege handoff."""

from __future__ import annotations

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

from entrypoint_test_helpers import (
    controlling_tty_exec_python,
    entrypoint_source_with_mock_controller,
    sudo_passthrough_script,
    terminal_command,
)

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
        definitions = entrypoint_source_with_mock_controller().splitlines()
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
        interrupt: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            master, slave = pty.openpty()
            try:
                original = termios.tcgetattr(slave)
                original[3] |= termios.ECHO
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


class TerminalContextTests(unittest.TestCase):
    """Preserve controlling terminal paths and capture privilege boundaries."""

    def test_interactive_terminal_path_resolves_concrete_device(self) -> None:
        """The resolved TTY must be a concrete device the relayed setup can reopen."""

        definitions = entrypoint_source_with_mock_controller().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            wrapper = fixture / "resolve-terminal.sh"
            wrapper.write_text("\n".join(definitions) + "\ninteractive_terminal_path\n")
            master, slave = pty.openpty()
            slave_path = os.ttyname(slave)
            try:
                # Mirror the interactive `script` capture path: the entrypoint
                # runs with the terminal on stdin, so the helper must resolve its
                # concrete device rather than the unreopenable "/dev/tty" alias.
                with subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        controlling_tty_exec_python('["sh", sys.argv[2]]'),
                        slave_path,
                        str(wrapper),
                    ],
                    stdin=slave,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env={"PATH": "/usr/bin:/bin", "HOME": temporary_dir},
                    start_new_session=True,
                    text=True,
                ) as process:
                    stdout, stderr = process.communicate(timeout=10)
            finally:
                os.close(slave)
                os.close(master)

            # slave_path is a concrete pty device (never the "/dev/tty" alias),
            # so matching it proves the helper resolved a reopenable device.
            self.assertEqual(stdout.strip(), slave_path, stderr)

    def test_script_capture_uses_one_outer_sudo_and_marks_runner_to_skip_nested_sudo(self) -> None:
        """Interactive capture must elevate before allocating its relay terminal."""

        definitions = entrypoint_source_with_mock_controller().splitlines()
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
                terminal_command(
                    [
                        "/bin/sh",
                        "-c",
                        (
                            '. "$1"\n'
                            'TARGET_USER="fixture"\n'
                            'TARGET_USER_HOME="$HOME"\n'
                            'COLLECTIONS_INSTALL_DIR="$HOME/.ansible/collections"\n'
                            "run_ansible_pull_with_bitwarden_retry ansible/backup.yml 0\n"
                        ),
                        "entrypoint-test",
                        str(wrapper),
                    ]
                ),
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
