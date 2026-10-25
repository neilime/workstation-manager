"""Keep the CI bootstrap revision aligned with the checked-out E2E assertions."""

from __future__ import annotations

import os
import pathlib
import shlex
import subprocess
import tempfile
import time
import unittest

from ansible.parsing.dataloader import DataLoader

WORKSPACE = pathlib.Path(__file__).parents[2]
STAGES = tuple(f"{phase}-{stage}" for phase in ("backup", "setup", "cleanup") for stage in ("arrange", "act", "assert"))


class E2EWorkflowRevisionTests(unittest.TestCase):
    """Exercise separate workflow stages against divergent local Git history."""

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
            "TEST_STAGE_CALLS": str(self.fixture / "stage-calls"),
            "GITHUB_ENV": str(self.fixture / "github-env"),
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
            '[[ "$1" == "e2e-stage" && "$2" == STAGE=* ]]\n'
            '[[ "$REPORTS_DIR" == ".reports" ]]\n'
            '[[ "$E2E_SUITE_DEADLINE" == "$TEST_SUITE_DEADLINE" ]]\n'
            'printf "%s\\n" "${2#STAGE=}" >>"$TEST_STAGE_CALLS"\n'
            'source "$TEST_E2E_COMMON"\n'
            "resolve_e2e_workspace_dir() { pwd; }\n"
            "resolve_e2e_workstation_context fixture-vm\n"
            'printf "%s\\n" "${2#STAGE=}" "$E2E_BRANCH_NAME" "$E2E_ENTRYPOINT_SCRIPT_URL"\n'
            'git show "$E2E_BRANCH_NAME:setup.txt"\n'
        )
        make.chmod(0o755)
        workflow = DataLoader().load_from_file(str(WORKSPACE / ".github/workflows/__shared-ci.yml"))
        job = workflow["jobs"]["e2e"]
        self.environment.update({key: str(value) for key, value in job["env"].items() if "${{" not in str(value)})
        self.initialization = next(step for step in job["steps"] if "GITHUB_ENV" in step.get("run", ""))
        self.stages = [
            step
            for step in job["steps"]
            if shlex.split(step.get("run", ""))[:2] == ["make", "e2e-stage"]
            and "STAGE=finish" not in shlex.split(step["run"])
        ]

    def git(self, *arguments: str) -> str:
        """Create fixture history without network access or workstation changes."""

        return subprocess.check_output(
            ["git", *arguments], cwd=self.fixture, env=self.environment, stderr=subprocess.PIPE, text=True
        ).strip()

    def run_step(self, step: dict, directory: pathlib.Path) -> subprocess.CompletedProcess[str]:
        """Run production workflow shell with only make intercepted."""

        return subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
            cwd=directory,
            env={
                **self.environment,
                **{key: str(value) for key, value in step.get("env", {}).items()},
            },
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def initialize(self) -> str:
        """Import the actual exported environment just as subsequent Actions steps receive it."""
        started = int(time.time())
        result = self.run_step(self.initialization, self.fixture)
        self.assertEqual(result.returncode, 0, result.stderr)
        exported = dict(line.split("=", 1) for line in (self.fixture / "github-env").read_text().splitlines())
        self.environment.update(exported)
        deadline = int(exported["E2E_SUITE_DEADLINE"])
        self.assertGreaterEqual(deadline, started + 35 * 60)
        self.assertLessEqual(deadline, int(time.time()) + 35 * 60)
        self.environment["TEST_SUITE_DEADLINE"] = str(deadline)
        return exported["E2E_REPOSITORY_REF"]

    def assert_stages_resolve_revision(self, revision: str) -> None:
        """Every configured stage must use the initialized revision and shared suite deadline."""
        for step in self.stages:
            self.assertIn(step.get("if"), (None, "success()", "${{ success() }}"))
            self.assertFalse(step.get("continue-on-error", False))
            result = self.run_step(step, self.fixture)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.splitlines()[1:],
                [
                    revision,
                    f"https://raw.githubusercontent.com/fixture/workstation-manager/{revision}/workstation.sh",
                    "install Oh My Zsh",
                ],
            )
        self.assertEqual(tuple((self.fixture / "stage-calls").read_text().splitlines()), STAGES)

    def test_pr_bootstrap_includes_base_changes_used_by_assertions(self) -> None:
        """The PR head lacks a base installation, while its tested merge contains it."""

        self.git("checkout", "--detach")
        self.assertEqual(self.git("show", f"{self.environment['E2E_REPOSITORY_REF']}:setup.txt"), "initial setup")
        revision = self.git("rev-parse", "HEAD")
        self.assertEqual(self.initialize(), revision)
        self.assert_stages_resolve_revision(revision)

    def test_branch_checkout_is_pinned_even_if_the_branch_moves(self) -> None:
        """Push/manual runs must also select the tested commit instead of a mutable branch."""

        revision = self.git("rev-parse", "HEAD")
        self.assertEqual(self.initialize(), revision)
        (self.fixture / "setup.txt").write_text("later change\n")
        self.git("commit", "-am", "Branch advanced")
        self.assertNotEqual(self.git("rev-parse", "HEAD"), revision)
        self.assert_stages_resolve_revision(revision)

    def test_missing_checkout_stops_before_running_e2e(self) -> None:
        """A failed revision lookup must not silently fall back to the PR head."""

        with tempfile.TemporaryDirectory() as outside_checkout:
            result = self.run_step(self.initialization, pathlib.Path(outside_checkout))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.fixture / "stage-calls").exists())
        self.assertFalse((self.fixture / "github-env").exists())
        self.assertFalse(self.initialization.get("continue-on-error", False))
        for step in self.stages:
            self.assertIn(step.get("if"), (None, "success()", "${{ success() }}"))
