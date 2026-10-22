"""Keep the CI bootstrap revision aligned with the checked-out E2E assertions."""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest

from ansible.parsing.dataloader import DataLoader

WORKSPACE = pathlib.Path(__file__).parents[2]


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
