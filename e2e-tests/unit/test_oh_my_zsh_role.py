"""Exercise the framework checkout using a local Git origin and isolated home."""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import ansible_environment, run_playbook, write_local_playbook

pytestmark = pytest.mark.integration

TASK_FILE = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup"
    / "roles/home_environment/tasks/oh_my_zsh.yml"
)


class OhMyZshRoleTests(unittest.TestCase):
    """Setup must honor the pin and preserve user files in normal and check mode."""

    def setUp(self) -> None:
        """Create a local upstream with two revisions and an existing shell config."""
        # TestCase.enterContext keeps this fixture alive until registered cleanup runs.
        # pylint: disable-next=consider-using-with
        self.fixture = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.fixture / "home"
        self.home.mkdir()
        (self.home / ".zshrc").write_text("# existing personal configuration\n")
        self.origin = self.fixture / "origin"
        self.origin.mkdir()
        self.checkout = self.home / ".oh-my-zsh"
        self.env = ansible_environment(
            self.fixture,
            HOME=str(self.home),
            GIT_CONFIG_GLOBAL="/dev/null",
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="Fixture",
            GIT_AUTHOR_EMAIL="fixture@example.invalid",
            GIT_COMMITTER_NAME="Fixture",
            GIT_COMMITTER_EMAIL="fixture@example.invalid",
        )
        self.git("init", "--quiet")
        (self.origin / "oh-my-zsh.sh").write_text("# first revision\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "First revision")
        self.first_revision = self.git("rev-parse", "HEAD")
        (self.origin / "oh-my-zsh.sh").write_text("# second revision\n")
        self.git("commit", "--quiet", "--all", "-m", "Second revision")
        self.second_revision = self.git("rev-parse", "HEAD")

    def git(self, *args: str) -> str:
        """Run fixture Git operations without loading host Git configuration."""
        return subprocess.check_output(["git", *args], cwd=self.origin, env=self.env, text=True).strip()

    def apply(self, version: str, *, check: bool = False) -> subprocess.CompletedProcess[str]:
        """Run the production task with an isolated upstream and fixture revision."""
        # Account changes are exercised in the VM; this fixture owns only a home.
        tasks = [task for task in DataLoader().load_from_file(str(TASK_FILE)) if "ansible.builtin.git" in task]
        tasks[0]["ansible.builtin.git"]["repo"] = str(self.origin)
        playbook = self.fixture / "playbook.json"
        write_local_playbook(
            playbook,
            tasks,
            {
                "workstation_manager_use_become": False,
                "workstation_manager_oh_my_zsh_revision": version,
                "workstation_manager_resolved": {"user": {"name": "fixture-user", "home": str(self.home)}},
            },
            name="Exercise isolated Oh My Zsh installation",
        )
        command = ["ansible-playbook", "--inventory", "localhost,", str(playbook)]
        if check:
            command.append("--check")
        return run_playbook(command, self.env, cwd=self.fixture)

    def assert_succeeded(self, result: subprocess.CompletedProcess[str]) -> None:
        """Report complete Ansible output when a scenario fails."""
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fresh_check_mode_preserves_the_home(self) -> None:
        """A preview must not create the framework or overwrite shell settings."""
        self.assert_succeeded(self.apply(self.first_revision, check=True))
        self.assertFalse(self.checkout.exists())
        self.assertEqual((self.home / ".zshrc").read_text(), "# existing personal configuration\n")

    def test_pinned_install_is_idempotent_and_preserves_custom_files(self) -> None:
        """Install the requested revision and preserve custom plugins during updates."""
        self.assert_succeeded(self.apply(self.first_revision))
        self.assertEqual(self.git("-C", str(self.checkout), "rev-parse", "HEAD"), self.first_revision)
        self.assertEqual((self.checkout / "oh-my-zsh.sh").stat().st_uid, os.getuid())
        repeat = self.apply(self.first_revision)
        self.assert_succeeded(repeat)
        self.assertRegex(repeat.stdout, r"changed=0\s")
        custom = self.checkout / "custom" / "personal.zsh"
        custom.parent.mkdir()
        custom.write_text("# preserve personal extensions\n")
        self.assert_succeeded(self.apply(self.second_revision, check=True))
        self.assertEqual(self.git("-C", str(self.checkout), "rev-parse", "HEAD"), self.first_revision)
        self.assert_succeeded(self.apply(self.second_revision))
        self.assertEqual(
            self.git("-C", str(self.checkout), "rev-parse", "HEAD"),
            self.second_revision,
        )
        self.assertEqual(custom.read_text(), "# preserve personal extensions\n")
        self.assertEqual((self.home / ".zshrc").read_text(), "# existing personal configuration\n")

    def test_updates_refuse_to_discard_tracked_local_changes(self) -> None:
        """Modified framework files must survive a rejected update."""
        self.assert_succeeded(self.apply(self.first_revision))
        framework = self.checkout / "oh-my-zsh.sh"
        framework.write_text("# local changes must survive\n")
        rejected = self.apply(self.second_revision)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("Local modifications exist", rejected.stdout)
        self.assertEqual(framework.read_text(), "# local changes must survive\n")


if __name__ == "__main__":
    unittest.main()
