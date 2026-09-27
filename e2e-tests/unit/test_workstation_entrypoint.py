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
