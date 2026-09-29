"""Keep the CI bootstrap revision aligned with the checked-out E2E assertions."""

from __future__ import annotations

import errno
import json
import os
import pathlib
import pty
import select
import shlex
import subprocess
import sys
import tempfile
import time
import unittest

from ansible.parsing.dataloader import DataLoader
from entrypoint_test_helpers import controlling_tty_exec_python, sudo_passthrough_script

WORKSPACE = pathlib.Path(__file__).parents[2]
CHEZMOI_RECONCILE_TASKS = (
    WORKSPACE
    / "ansible/collections/ansible_collections/neilime/workstation_backup/roles/chezmoi/tasks/reconcile_git.yml"
)
RETRY_PROMPT = b"Choose [save/restore/retry/skip/abort]:"
RETRY_WRAPPER_COMMAND = "run_ansible_pull_with_bitwarden_retry check.yml 0\n"


class E2EWorkflowRevisionTests(unittest.TestCase):
    """Exercise the actual workflow shell step against divergent local Git history."""

    def setUp(self) -> None:
        # enterContext registers cleanup even if fixture preparation fails.
        # pylint: disable-next=consider-using-with
        self.fixture = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.environment = {
            "PATH": f"{self.fixture / 'bin'}:{os.environ['PATH']}",
            "HOME": str(self.fixture),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "TEST_E2E_COMMON": str(WORKSPACE / "e2e-tests/e2e-common.sh"),
            "E2E_REPOSITORY_URL": "https://github.com/fixture/workstation-manager.git",
        }
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.fixture / "workstation.sh").write_text("# Fixture entrypoint\n")
        (self.fixture / "setup.txt").write_text("initial setup\n")
        self.git("add", ".")
        self.git("commit", "-m", "Initial")
        self.git("checkout", "-b", "feature")
        (self.fixture / "backup.txt").write_text("backup improvement\n")
        self.git("add", ".")
        self.git("commit", "-m", "Feature change")
        self.environment["E2E_REPOSITORY_REF"] = self.git("rev-parse", "HEAD")
        self.git("checkout", "main")
        (self.fixture / "setup.txt").write_text("install Oh My Zsh\n")
        self.git("commit", "-am", "New baseline installation and assertion")
        self.git("merge", "--no-ff", "feature", "-m", "Pull request merge")
        (self.fixture / "bin").mkdir()
        # Context resolution only checks for curl; no test may use the network.
        curl = self.fixture / "bin/curl"
        curl.write_text("#!/bin/sh\nexit 99\n")
        curl.chmod(0o755)
        make = self.fixture / "bin/make"
        make.write_text(
            "#!/bin/bash\nset -euo pipefail\n"
            '[[ "$*" == "e2e-test" ]]\n'
            '[[ "$REPORTS_DIR" == ".reports" ]]\n'
            'source "$TEST_E2E_COMMON"\n'
            "resolve_e2e_workspace_dir() { pwd; }\n"
            "resolve_e2e_workstation_context fixture-vm\n"
            'printf "%s\\n" "$E2E_BRANCH_NAME" "$E2E_ENTRYPOINT_SCRIPT_URL"\n'
            'git show "$E2E_BRANCH_NAME:setup.txt"\n'
        )
        make.chmod(0o755)
        workflow = DataLoader().load_from_file(str(WORKSPACE / ".github/workflows/__shared-ci.yml"))
        self.step = next(
            step for step in workflow["jobs"]["e2e"]["steps"] if step.get("name") == "Run phased e2e assertions"
        )

    def git(self, *arguments: str) -> str:
        """Create fixture history without network access or workstation changes."""

        return subprocess.check_output(
            ["git", *arguments], cwd=self.fixture, env=self.environment, stderr=subprocess.PIPE, text=True
        ).strip()

    def run_step(self, directory: pathlib.Path) -> subprocess.CompletedProcess[str]:
        """Run the production workflow shell with only its final make command intercepted."""

        return subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.step["run"]],
            cwd=directory,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_pr_bootstrap_includes_base_changes_used_by_assertions(self) -> None:
        """The PR head lacks a base installation, while its tested merge contains it."""

        self.git("checkout", "--detach")
        self.assertEqual(self.git("show", f"{self.environment['E2E_REPOSITORY_REF']}:setup.txt"), "initial setup")
        result = self.run_step(self.fixture)
        self.assertEqual(result.returncode, 0, result.stderr)
        revision = self.git("rev-parse", "HEAD")
        self.assertEqual(
            result.stdout.splitlines(),
            [
                revision,
                f"https://raw.githubusercontent.com/fixture/workstation-manager/{revision}/workstation.sh",
                "install Oh My Zsh",
            ],
        )

    def test_branch_checkout_is_pinned_even_if_the_branch_moves(self) -> None:
        """Push/manual runs must also select the tested commit instead of a mutable branch."""

        result = self.run_step(self.fixture)
        self.assertEqual(result.returncode, 0, result.stderr)
        revision = self.git("rev-parse", "HEAD")
        (self.fixture / "setup.txt").write_text("later change\n")
        self.git("commit", "-am", "Branch advanced")
        self.assertNotEqual(self.git("rev-parse", "HEAD"), revision)
        self.assertEqual(result.stdout.splitlines()[0], revision)
        self.assertEqual(self.git("show", f"{revision}:setup.txt"), "install Oh My Zsh")

    def test_missing_checkout_stops_before_running_e2e(self) -> None:
        """A failed revision lookup must not silently fall back to the PR head."""

        with tempfile.TemporaryDirectory() as outside_checkout:
            result = self.run_step(pathlib.Path(outside_checkout))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


def bootstrap_fixture(fixture: pathlib.Path) -> str:
    """Load the entrypoint with isolated target paths and a non-privileged sudo stub."""

    (fixture / "bin").mkdir()
    sudo = fixture / "bin/sudo"
    sudo.write_text(sudo_passthrough_script("unset PYTHONUNBUFFERED\n"))
    sudo.chmod(0o755)
    definitions = (WORKSPACE / "workstation.sh").read_text().splitlines()
    if definitions.pop() != 'main "$@"':
        raise AssertionError("The entrypoint must end with its main invocation")
    (fixture / "entrypoint.sh").write_text("\n".join(definitions) + "\n")
    # CI's numeric container UID may have no passwd entry; provide the target context.
    return (
        ". ./entrypoint.sh\n"
        'TARGET_USER="$USER"\n'
        'TARGET_USER_HOME="$HOME"\n'
        'COLLECTIONS_INSTALL_DIR="$HOME/.ansible/collections"\n'
        'ANSIBLE_CHECKOUT_DIR="$HOME/checkout"\n'
    )


def load_chezmoi_retry_task() -> dict[str, object]:
    """Load the interactive drift-resolution task from the production role."""

    tasks = DataLoader().load_from_file(str(CHEZMOI_RECONCILE_TASKS))
    return next(task for task in tasks if task["name"] == "Resolve chezmoi tracking branch drift")


def write_retry_playbook(repository: pathlib.Path, decision_task: dict[str, object]) -> None:
    """Create a minimal playbook that exercises the real retry decision prompt."""

    (repository / "check.yml").write_text(
        json.dumps(
            [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {
                        "workstation_backup_chezmoi_source_dir": "/fixture/chezmoi",
                        "workstation_backup_chezmoi_git_preflight": {
                            "state": {
                                "ahead": 0,
                                "behind": 2,
                                "upstream": "origin/main",
                                "status": "M  README.md\n D home/dot_bashrc",
                            }
                        },
                        "workstation_backup_chezmoi_git_needs_decision": True,
                        "workstation_backup_dry_run": False,
                    },
                    "tasks": [
                        decision_task,
                        {
                            "name": "Verify the answer",
                            "ansible.builtin.assert": {
                                "that": "workstation_backup_recovery_choices['chezmoi-git'] == 'retry'"
                            },
                        },
                        {"ansible.builtin.debug": {"msg": "FIXTURE_COMPLETED"}},
                    ],
                }
            ]
        )
    )


def initialize_git_repository(repository: pathlib.Path, environment: dict[str, str]) -> None:
    """Create a throwaway repository for interactive entrypoint tests."""

    for arguments in (
        ["init", "--initial-branch=main"],
        ["add", "."],
        ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "Fixture"],
    ):
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            env=environment,
            check=True,
            capture_output=True,
        )


class PinnedCommitBootstrapTests(unittest.TestCase):
    """Exercise the real Git module and ansible-pull with a commit reachable only via a PR ref."""

    def test_bootstrap_fetches_merge_commit_outside_branches_and_tags(self) -> None:
        """A regular clone cannot see this commit; the entrypoint must explicitly fetch it."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            environment = {
                "PATH": f"{fixture / 'bin'}:{os.environ['PATH']}",
                "HOME": str(fixture),
                "ANSIBLE_HOME": str(fixture / ".ansible"),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "USER": "fixture",
            }

            def git(*arguments: str) -> str:
                return subprocess.check_output(
                    ["git", *arguments], cwd=fixture, env=environment, stderr=subprocess.PIPE, text=True
                ).strip()

            git("init", "--initial-branch=main")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            (fixture / "baseline").write_text("baseline\n")
            git("add", ".")
            git("commit", "-m", "Base")
            (fixture / "ansible").mkdir()
            (fixture / "ansible/check.yml").write_text(
                json.dumps(
                    [
                        {
                            "name": "Verify the playbook exists only in the PR ref",
                            "hosts": "localhost",
                            "gather_facts": False,
                            "tasks": [
                                {"name": "Confirm checkout", "ansible.builtin.debug": {"msg": "PR_REF_BOOTSTRAPPED"}}
                            ],
                        }
                    ]
                )
            )
            git("add", ".")
            git("commit", "-m", "Unmerged change")
            revision = git("rev-parse", "HEAD")
            git("init", "--bare", "--initial-branch=main", str(fixture / "remote.git"))
            git("push", str(fixture / "remote.git"), "HEAD~1:refs/heads/main", "HEAD:refs/pull/252/merge")
            environment["REPOSITORY_URL"] = (fixture / "remote.git").as_uri()
            environment["REPOSITORY_BRANCH"] = revision
            # file:// uses Git transport instead of copying all local objects into the clone.
            git("clone", environment["REPOSITORY_URL"], str(fixture / "regular-clone"))
            self.assertNotIn(revision, git("-C", str(fixture / "regular-clone"), "rev-list", "--all").splitlines())
            bootstrap = bootstrap_fixture(fixture)
            result = subprocess.run(
                [
                    "sh",
                    "-c",
                    bootstrap + "run_ansible_pull ansible/check.yml 0",
                ],
                cwd=fixture,
                env=environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("PR_REF_BOOTSTRAPPED", result.stdout)
            self.assertFalse((fixture / "checkout").exists(), "ansible-pull must still purge its checkout")


class InteractiveBootstrapTests(unittest.TestCase):
    """Exercise prompt answers and keyboard cancellation with an isolated repository."""

    def _prepare_retry_fixture(
        self, fixture: pathlib.Path, *, disable_script_capture: bool = False
    ) -> tuple[dict[str, str], str]:
        """Build the repository and environment shared by the retry-wrapper tests."""

        repository = fixture / "repository"
        repository.mkdir()
        write_retry_playbook(repository, load_chezmoi_retry_task())
        environment = {
            "PATH": f"{fixture / 'bin'}:{os.environ['PATH']}",
            "HOME": str(fixture),
            "USER": "fixture",
            "ANSIBLE_HOME": str(fixture / ".ansible"),
            "ANSIBLE_CONFIG": str(fixture / "ansible.cfg"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "REPOSITORY_URL": repository.as_uri(),
            "WORKSTATION_MANAGER_INTERACTIVE": "1",
        }
        if disable_script_capture:
            environment["WORKSTATION_MANAGER_DISABLE_SCRIPT_CAPTURE"] = "1"
        (fixture / "ansible.cfg").write_text("[defaults]\n")
        initialize_git_repository(repository, environment)
        bootstrap = bootstrap_fixture(fixture)
        environment["WORKSTATION_MANAGER_ENTRYPOINT_SOURCE"] = str(fixture / "entrypoint.sh")
        bootstrap += "COLLECTIONS_INSTALL_DIR=" + shlex.quote(str(WORKSPACE / "ansible/collections")) + "\n"
        return environment, bootstrap

    @staticmethod
    def _read_terminal_session(master: int, process: subprocess.Popen[bytes]) -> str:
        """Drive the retry prompt over a controlling tty until the fixture exits."""

        output = bytearray()
        deadline = time.monotonic() + 30
        answered = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            if not select.select([master], [], [], 0.2)[0]:
                continue
            try:
                data = os.read(master, 65536)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not data:
                break
            output.extend(data)
            if RETRY_PROMPT in output and not answered:
                # Ansible's pause task can still flush pending tty input just after the prompt renders.
                time.sleep(0.1)
                os.write(master, b"retry\n")
                answered = True
            if b"FIXTURE_COMPLETED" in output:
                break
        transcript = output.decode(errors="replace")
        if not answered:
            raise AssertionError(transcript)
        return transcript

    def _run_direct_terminal_bootstrap(self, fixture: pathlib.Path, environment: dict[str, str], bootstrap: str) -> str:
        """Run the bootstrap through a real controlling tty and return its transcript."""

        master, slave = pty.openpty()
        try:
            with subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    controlling_tty_exec_python('["sh"]'),
                    os.ttyname(slave),
                ],
                cwd=fixture,
                env=environment,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
                text=False,
            ) as process:
                try:
                    os.close(slave)
                    slave = -1
                    os.write(master, bootstrap.encode())
                    return self._read_terminal_session(master, process)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
        finally:
            if slave != -1:
                os.close(slave)
            os.close(master)

    def test_pull_flushes_prompts_and_accepts_answers_and_interrupts(self) -> None:
        """Buffered relay output must not hide either the decision or the abort prompt."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            # Do not inherit the tooling image's PYTHONUNBUFFERED: the entrypoint must set it after sudo.
            environment, bootstrap = self._prepare_retry_fixture(fixture, disable_script_capture=True)
            # Read the script from a pipe while Ansible reads answers from /dev/tty.
            command = "printf '%s\\n' " + shlex.quote(bootstrap + RETRY_WRAPPER_COMMAND.rstrip("\n")) + " | sh"
            for interrupt in (False, True):
                with self.subTest(interrupt=interrupt):
                    with subprocess.Popen(
                        [
                            "script",
                            "--quiet",
                            "--return",
                            "--command",
                            command,
                            os.devnull,
                        ],
                        cwd=fixture,
                        env=environment,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    ) as process:
                        assert process.stdin is not None
                        output = bytearray()

                        try:
                            self.wait_for_prompt(process, output, RETRY_PROMPT)
                            self.assert_prompt_layout(output)
                            if interrupt:
                                process.stdin.write(b"\x03")
                                process.stdin.flush()
                                self.wait_for_prompt(process, output, b"to abort")
                                process.stdin.write(b"a")
                            else:
                                process.stdin.write(b"retry\n")
                            process.stdin.flush()
                            remaining, _ = process.communicate(timeout=20)
                            output.extend(remaining)
                            if interrupt:
                                self.assertNotEqual(process.returncode, 0, output)
                                self.assertNotIn(b"FIXTURE_COMPLETED", output)
                            else:
                                self.assertEqual(process.returncode, 0, output)
                                self.assertIn(b"FIXTURE_COMPLETED", output)
                        finally:
                            if process.poll() is None:
                                process.terminate()
                                process.communicate(timeout=5)

    def test_retry_wrapper_accepts_answers_in_a_direct_terminal_run(self) -> None:
        """The retry wrapper must still allow Ansible pause prompts in a real controlling tty."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            environment, bootstrap = self._prepare_retry_fixture(fixture)
            transcript = self._run_direct_terminal_bootstrap(fixture, environment, bootstrap + RETRY_WRAPPER_COMMAND)
            self.assertIn(RETRY_PROMPT.decode(), transcript)
            self.assertIn("FIXTURE_COMPLETED", transcript)

    def assert_prompt_layout(self, output: bytearray) -> None:
        """Check real terminal output for left-aligned lines and unescaped Git status."""

        prompt_start = output.index(b"Chezmoi source: /fixture/chezmoi")
        self.assertEqual(output[prompt_start - 1], ord("\r"))
        prompt_output = output[prompt_start - 1 :].replace(b"\r\n", b"\n")
        for line in prompt_output.split(b"\n"):
            if line.strip():
                self.assertTrue(line.startswith(b"\r"), line)
        self.assertNotIn(b"\\n", prompt_output)
        self.assertIn(b"Source changes:\n\rM  README.md\n\r D home/dot_bashrc", prompt_output)

    def wait_for_prompt(self, process: subprocess.Popen[bytes], output: bytearray, marker: bytes) -> None:
        """Read a visible prompt before sending input, with a bounded wait on regressions."""

        assert process.stdout is not None
        deadline = time.monotonic() + 20
        while marker not in output:
            self.assertLess(time.monotonic(), deadline, output.decode(errors="replace"))
            self.assertIsNone(process.poll(), output.decode(errors="replace"))
            if select.select([process.stdout], [], [], 0.1)[0]:
                output.extend(os.read(process.stdout.fileno(), 65536))
        # pause flushes pending input immediately after displaying the prompt.
        time.sleep(0.1)


if __name__ == "__main__":
    unittest.main()
