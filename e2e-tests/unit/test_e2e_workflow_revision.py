"""Keep the CI bootstrap revision aligned with the checked-out E2E assertions."""

from __future__ import annotations

import json
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
            (fixture / "bin").mkdir()
            sudo = fixture / "bin/sudo"
            sudo.write_text('#!/bin/sh\nshift\nexec "$@"\n')
            sudo.chmod(0o755)
            definitions = (WORKSPACE / "workstation.sh").read_text().splitlines()
            self.assertEqual(definitions.pop(), 'main "$@"')
            (fixture / "entrypoint.sh").write_text("\n".join(definitions) + "\n")
            result = subprocess.run(
                [
                    "sh",
                    "-c",
                    # CI's numeric container UID may have no passwd entry; use an isolated target context.
                    ". ./entrypoint.sh\n"
                    'TARGET_USER="$USER"\n'
                    'TARGET_USER_HOME="$HOME"\n'
                    'COLLECTIONS_INSTALL_DIR="$HOME/.ansible/collections"\n'
                    'ANSIBLE_CHECKOUT_DIR="$HOME/checkout"\n'
                    "run_ansible_pull ansible/check.yml 0",
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


if __name__ == "__main__":
    unittest.main()
