"""Verify backup privilege and home scopes without executing workstation tasks."""

from __future__ import annotations

import pathlib
import unittest
from collections.abc import Iterator

from ansible.parsing.dataloader import DataLoader
from ansible.playbook import Playbook
from ansible.playbook.block import Block
from ansible.playbook.task import Task
from ansible.plugins.loader import init_plugin_loader
from ansible.template import Templar
from ansible.utils.collection_loader._collection_config import AnsibleCollectionConfig
from ansible.vars.manager import VariableManager

REPOSITORY_PATH = pathlib.Path(__file__).parents[2]
COLLECTIONS_PATH = REPOSITORY_PATH / "ansible/collections"
BACKUP_PATH = COLLECTIONS_PATH / "ansible_collections/neilime/workstation_backup"


class BackupPrivilegeTests(unittest.TestCase):
    """Preserve managed-user operations when the Ansible controller runs as root."""

    def setUp(self) -> None:
        if AnsibleCollectionConfig.collection_finder is None:
            init_plugin_loader(
                prefix_collections_path=[
                    str(COLLECTIONS_PATH),
                    str(REPOSITORY_PATH / "ansible/vendor-collections"),
                ]
            )
        self.loader = DataLoader()
        self.manager = VariableManager(loader=self.loader)
        self.play = Playbook.load(
            str(REPOSITORY_PATH / "ansible/backup.yml"),
            loader=self.loader,
            variable_manager=self.manager,
        ).get_plays()[0]
        self.tasks = {task.name: task for task in self._walk_tasks(self.play.compile())}
        defaults = self.loader.load_from_file(
            str(BACKUP_PATH / "roles/state/defaults/main.yml"), trusted_as_template=True
        )
        self.templar = Templar(
            loader=self.loader,
            variables={
                **defaults,
                "ansible_env": {"HOME": "/root"},
                "workstation_manager_use_become": True,
                "workstation_manager_resolved": {"user": {"name": "runner", "home": "/home/runner.guest"}},
                "workstation_backup_extra_paths_raw": "~/notes",
            },
        )

    def _walk_tasks(self, entries: list[Block | Task]) -> Iterator[Task]:
        for entry in entries:
            if isinstance(entry, Block):
                yield from self._walk_tasks(entry.block)
            else:
                yield entry
                if (
                    entry.action == "ansible.builtin.include_role"
                    and entry.args["name"] == "neilime.workstation_setup.bitwarden_collection"
                ):
                    blocks, _ = entry.get_block_list(play=self.play, variable_manager=self.manager, loader=self.loader)
                    yield from self._walk_tasks(blocks)

    def test_user_state_and_archives_run_as_managed_user(self) -> None:
        """Checks, vault caches, Git operations, and output files must retain user ownership."""
        for name in (
            "Check whether the managed chezmoi config file exists",
            "Check whether the managed chezmoi source directory exists",
            "Inspect chezmoi Git recovery state",
            "Discover local SSH private keys",
            "Read local GPG key fingerprints",
            "Read Bitwarden session status",
            "Unlock the Bitwarden vault for this run",
            "Ensure backup output directory exists",
            "Collect Git repository metadata",
            "Write Git repository inventory",
            "Write backup manifest",
            "Create backup archive",
        ):
            with self.subTest(task=name):
                task = self.tasks[name]
                self.assertTrue(self.templar.template(task.become))
                self.assertEqual(self.templar.template(task.become_user), "runner")
                homes = [self.templar.template(env["HOME"]) for env in task.environment if "HOME" in env]
                self.assertIn("/home/runner.guest", homes)

    def test_dependency_installation_remains_privileged(self) -> None:
        """User-scoped backup roles must explicitly elevate system dependency tasks."""
        for name in (
            "Ensure GPG tooling is installed for key synchronization",
            "Install unzip for Bitwarden CLI extraction",
            "Download the Bitwarden CLI archive",
            "Install the Bitwarden CLI binary",
        ):
            with self.subTest(task=name):
                task = self.tasks[name]
                self.assertTrue(self.templar.template(task.become))
                self.assertEqual(self.templar.template(task.become_user), "root")

    def test_backup_paths_use_resolved_home_with_root_controller(self) -> None:
        """Default sources and tilde expansion must ignore the controller's root home."""
        task = self.tasks["Initialize requested backup paths"]
        requested = self.templar.template(task.args["workstation_backup_requested_paths"])
        self.assertEqual(
            [item["path"] for item in requested],
            [
                "/home/runner.guest/Documents/dev-projects",
                "/home/runner.guest/.config/workstation-manager",
                "/home/runner.guest/notes",
            ],
        )


if __name__ == "__main__":
    unittest.main()
